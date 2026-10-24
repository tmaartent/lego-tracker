# Architecture

This document describes how lego-tracker is put together: which services exist, what
each one owns, how they talk to each other, and why it's built this way. The
[README](../README.md) has the short version and how to run it.

Parts marked **(planned)** are designed but not built yet. Everything else exists in
the code today.

## Contents

1. [Goals and non-goals](#1-goals-and-non-goals)
2. [Services at a glance](#2-services-at-a-glance)
3. [core](#3-core)
4. [watcher](#4-watcher)
5. [notifier (planned)](#5-notifier-planned)
6. [Messaging](#6-messaging)
7. [Reliability](#7-reliability)
8. [Failure scenarios](#8-failure-scenarios)
9. [Deployment](#9-deployment)
10. [Testing](#10-testing)
11. [Design decisions](#11-design-decisions)
12. [Known limitations](#12-known-limitations)

---

## 1. Goals and non-goals

**What the app does**

- Keep track of the second-hand sets I own and which parts each one is missing.
- Turn missing parts into a BrickLink wanted list.
- Watch second-hand marketplaces for sets I'm looking for, within a price and distance
  limit, and notify me of new matches.

**Why it's split into services**

A single-user hobby app doesn't need microservices; one Django app would do. The split
is deliberate: it's a realistic, small domain to practise service boundaries,
asynchronous messaging and the failure handling that comes with it.

**Non-goals**

- No scraping of sites that don't offer an API. Those can only come in through their
  own saved-search email alerts.
- No multi-user support, no public hosting. Everything runs locally in docker-compose.

## 2. Services at a glance

```
                 ┌──────────────────┐  watch.upserted / watch.deleted   ┌─────────────┐
  me ──admin──►  │ core (Django)    │ ──────────────┐                    │ watcher     │ ◄── eBay
                 │ catalog          │               ▼                    │             │
                 │ collection       │       ┌───────────────┐ ────────►  │             │
                 │ watches, outbox  │ ◄──── │ RabbitMQ      │ ◄────────  └─────────────┘
                 └────────┬─────────┘       │ "lego.events" │  listing.matched
                          │                 └───────┬───────┘
                          ▼                         ▼
                   Postgres (core)          ┌─────────────┐
                                            │ notifier    │ ──► Telegram
                                            │ (planned)   │
                                            └─────────────┘
```

| Service | Owns | Publishes | Consumes | Stack |
|---|---|---|---|---|
| **core** | Catalog, owned sets, missing parts, watches, offers | `watch.*` | `listing.*` (planned) | Django, django-ninja, PostgreSQL |
| **watcher** | Listings seen on marketplaces, its copy of the watches | `listing.*` | `watch.*` | FastAPI, FastStream, SQLAlchemy, PostgreSQL |
| **notifier** (planned) | Which notifications were sent | none | `listing.matched` | FastAPI, FastStream, PostgreSQL |
| **libs/events** | The event contracts | n/a | n/a | pydantic |

**Data ownership rule:** every service has its own database and is the only one that
reads or writes it. Services learn about each other's data through events, or through
an API call when they start up. No shared tables.

## 3. core

The Django app. It's the only service with a user interface (the Django admin) and the
source of truth for everything I enter by hand.

### 3.1 Apps

| App | Purpose |
|---|---|
| `catalog` | Reference data mirrored from Rebrickable: sets, parts, colors and each set's parts list, with BrickLink ids. |
| `collection` | My own data: owned copies of a set and their missing parts; exports a BrickLink wanted list. |
| `watches` | What I'm looking for on marketplaces. Every change becomes an event. |
| `outbox` | Stores events in the same transaction as the change, and relays them to RabbitMQ. |

`catalog` and `collection` are kept apart on purpose: a catalog re-import may rewrite
reference data, but never touches what I own.

### 3.2 Data model

```
catalog                                   collection
───────                                   ──────────
LegoSet ──< InventoryPart >── Part        OwnedSet ──< MissingPart
   │              │                          │              │
   │              └──── Color                │              └──► InventoryPart
   │                                         └──► LegoSet
   │
   └──< Watch          (watches)
                                          outbox
                                          ──────
                                          OutboxEvent (independent table)
```

- **LegoSet**: `set_num` (e.g. `6086-1`), name, year, number of parts.
- **InventoryPart**: one line of a set's parts list: part, color, quantity, spare or not.
  Unique per set, part, color and spare flag.
- **Part / Color**: Rebrickable ids, plus the BrickLink id, because the two sites
  number things differently.
- **OwnedSet**: a copy I own: when and where I bought it, what I paid, its condition.
- **MissingPart**: an inventory line of that set and how many are missing. Validation
  stops a part from another set, or more than the set contains.
- **Watch**: a set I'm looking for, with optional max total price (EUR, including
  shipping), max distance (km from home), whether incomplete sets are acceptable,
  and an `active` flag. `revision` goes up on every change (see [7.3](#73-full-state-and-revisions)).
- **OutboxEvent**: an event waiting to be published (see [7.1](#71-transactional-outbox)).

### 3.3 Rebrickable import

`python manage.py import_set [--colors] <set_num>...`

- `RebrickableClient` wraps the Rebrickable v3 API. It follows pagination and raises
  `RebrickableError` for missing keys and unknown sets. It takes an injectable
  `httpx.Client`, which is how the tests swap in a fake API.
- The importer is idempotent: it upserts parts and colors, updates the set, and removes
  parts list lines Rebrickable no longer lists. Re-running an import applies
  Rebrickable's corrections instead of creating duplicates. It never overwrites a known
  BrickLink id with an empty one.

### 3.4 BrickLink wanted list

An admin action on owned sets. Missing parts are added up across the selected sets per
BrickLink part and color, and exported as BrickLink's wanted-list XML. Parts without a
BrickLink mapping are listed in a warning instead of being dropped silently.

### 3.5 Internal API

django-ninja, mounted at `/api/`. OpenAPI docs at `/api/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Liveness, used by the docker-compose health check. |
| `GET /api/watches/` | Current state of every watch, as `WatchState` from `libs/events`. Used by consumers when they start (see [7.5](#75-bootstrap-then-follow)). |

The API reuses the pydantic models from `libs/events`, so the snapshot and the events
have the same shape by construction.

### 3.6 Processes

core runs as two containers from the same image:

| Container | Command | Job |
|---|---|---|
| `core` | `migrate`, then `runserver` | Admin and API |
| `core-relay` | `relay_outbox` | Publishes outbox events to RabbitMQ |

The relay is separate so the web app is unaffected when RabbitMQ is slow or down, and
so it can be restarted on its own.

## 4. watcher

Finds marketplace listings that match a watch. A FastAPI app; the RabbitMQ consumer,
the poller and the outbox relay run in the same process as background tasks.

### 4.1 Modules

| Module | Job |
|---|---|
| `app.py` | Wires everything together; the FastAPI lifespan starts the broker, then the background tasks. |
| `consumer.py` | FastStream subscriber on `watcher.watches`. |
| `watches.py` | Applies watch events and core's snapshot to the local copy, by revision. |
| `sources/` | Source adapters behind one `Source` interface. Today: `FakeSource`. |
| `poller.py` | Fetches from a source, stores listings, matches them, announces matches. |
| `matching.py` | Set number in the title, incomplete-set words, price and distance limits. |
| `geo.py` | Approximate distance between Belgian postcodes. |
| `outbox.py` | Same outbox pattern as core, on SQLAlchemy. |
| `api.py` | HTTP endpoints. |

### 4.2 Data model

Its own PostgreSQL database `watcher`, migrated with Alembic.

| Table | Holds |
|---|---|
| `watches` | Copy of core's watches, with their revision. Deleted watches stay as tombstones, so a late event can't bring them back. |
| `listings` | Every listing seen, unique per source and the source's own id. Price, shipping, postcode, first and last seen. |
| `matches` | Which listing matches which watch, and the lowest total price announced so far. |
| `processed_events` | Ids of events already handled (see [7.4](#74-idempotent-consumers)). |
| `outbox` | Events waiting to be published. |

### 4.3 Startup

1. Start the broker. This declares and binds `watcher.watches`, so watch changes start
   collecting in the queue.
2. Load the snapshot from core's `GET /api/watches/`. If core isn't up yet, retry every
   5 seconds; the rest of the watcher already runs.
3. Start the background tasks: poll every source on a schedule
   (`WATCHER_POLL_INTERVAL_SECONDS`), and relay the outbox every second.

### 4.4 Sources

A source gets the live watches and returns what it found. It decides itself how: a
search API runs a query per watch, an email inbox returns whatever arrived.

| Source | How | Status |
|---|---|---|
| `fake` | In memory. Listings are added with `POST /sources/fake/listings`, for tests and demos. | built |
| Email alerts | Reads saved-search alert emails over IMAP. 2dehands and Marktplaats first; Catawiki, Kleinanzeigen, Facebook Marketplace and Vinted only if their alerts turn out to be usable by email. | planned |
| eBay | The official Browse API. Still to check: whether results include shipping to Belgium, and how precise the item location is. | planned |
| BrickLink / Brick Owl | Official APIs, if access is granted (BrickLink requires a seller account). Also a source of typical prices for a deal score. | planned |

Sites without an API are only used through their own email alerts. No scraping.

### 4.5 A poll, step by step

1. Read the live watches, then call the source. This happens **outside** a database
   transaction, so a slow marketplace doesn't hold locks.
2. In one transaction, for each listing found:
   - insert it, or update its price, title and `last_seen` if it's known;
   - check it against every live watch;
   - a match not seen before: store it and enqueue `listing.matched`;
   - a known match whose total price is below the lowest announced: enqueue
     `listing.price_dropped` and remember the new price. A price that goes up and back
     down again is not announced twice.
3. Commit. The relay publishes the events afterwards.

Polls of the same source never run at the same time: a manual poll waits for a
scheduled one.

### 4.6 Matching

A listing matches a watch when all of these hold:

- the watch is active and not deleted;
- the title names the set: `6086` or `6086-1` for set 6086-1, but not `60861`, `16086`,
  `6086-2`, `€6086` or `6086 euro`;
- if the watch doesn't accept incomplete sets, the title has no words like *incompleet*,
  *niet volledig*, *ontbreekt*, *incomplete*, *missing*, *incomplet* or *unvollständig*;
- the total price (price + shipping) is within the maximum;
- the distance from home is within the maximum.

Unknown shipping or distance does **not** rule a listing out; the event carries it as
unknown (`shipping: null`, `distance_km: null`). The rules err on the side of reporting
a listing: a false alarm costs a glance, a missed deal costs the deal.

Distance is a straight line between postcode centres, so it's good to a few kilometres.
It only works for Belgian postcodes (GeoNames data, CC BY 4.0); everywhere else it's
unknown.

### 4.7 HTTP endpoints

OpenAPI docs at `/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness, used by the docker-compose health check. |
| `GET /listings?matched=true` | Listings seen, newest first, with the watches they match. |
| `POST /sources/{name}/poll` | Poll one source now instead of waiting for the schedule. |
| `POST /sources/fake/listings` | Put a listing on the fake marketplace. Reusing an `external_id` changes that listing, e.g. to demo a price drop. |

## 5. notifier (planned)

Sends a Telegram message for every `listing.matched`.

- Consumes `listing.matched` from its own queue.
- Deduplicates on `event_id`, so a redelivered event doesn't buzz twice.
- If Telegram is unavailable: a few delayed retries, then the message goes to a
  dead-letter queue that can be inspected and replayed.
- HTTP endpoints for health and for inspecting the dead-letter queue.

## 6. Messaging

### 6.1 Broker topology

- One **topic exchange**, `lego.events`, durable.
- Every event is published with its `routing_key` as the routing key.
- Each consuming service declares **its own durable queue** and binds it to the keys it
  needs. RabbitMQ copies a message to every bound queue, so adding a consumer never
  affects the others.

| Queue | Bound to | Owner | Status |
|---|---|---|---|
| `watcher.watches` | `watch.*` | watcher | built |
| `core.listings` | `listing.*` | core | planned |
| `notifier.matches` | `listing.matched` | notifier | planned |

Planned: a dead-letter exchange and a queue per consumer for messages that keep failing.

Messages are persistent (`delivery_mode=2`). Properties: `content_type` is
`application/json`, `message_id` is the event id, `type` is the routing key.

### 6.2 Event contracts

All events are pydantic models in `libs/events`, subclasses of `Event`:

| Field | Meaning |
|---|---|
| `event_id` | UUID, generated when the event is created. The idempotency key. |
| `occurred_at` | Timezone-aware timestamp of the change. |
| *payload fields* | Defined per event type. |

`parse(routing_key, body)` turns a received message back into the right class, and
rejects unknown routing keys and invalid payloads.

**Event catalog**

| Routing key | Producer | Payload | Status |
|---|---|---|---|
| `watch.upserted` | core | `watch: WatchState` | built |
| `watch.deleted` | core | `watch_id`, `revision` | built |
| `listing.matched` | watcher | `watch_id`, `set_num`, `listing: ListingSnapshot` | built |
| `listing.price_dropped` | watcher | as above, plus `previous_total_price` | built |

`WatchState`: `watch_id`, `revision`, `set_num`, `set_name`, `max_total_price`,
`max_distance_km`, `accept_incomplete`, `active`.

### 6.3 Evolving contracts

- **Adding a field** is safe. Consumers ignore fields they don't know
  (`extra="ignore"`), so producers can be deployed first.
- **Removing, renaming or changing a field** is a breaking change. It gets a new
  routing key (e.g. `watch.upserted.v2`), and the producer publishes both versions until
  every consumer has moved over.
- Routing keys are registered when the class is defined; a duplicate key fails at
  import time.

## 7. Reliability

The guarantees, in one line: **every change is published at least once, in order,
and consumers make duplicates harmless.**

### 7.1 Transactional outbox

Publishing directly to RabbitMQ after saving fails in two ways:

- The database commits, RabbitMQ is down: **the event is lost.**
- RabbitMQ accepts, the database rolls back: **an event for a change that never happened.**

Instead, the change and its event are written **in one database transaction**:

```
admin save
  └─ transaction
       ├─ UPDATE watches_watch ...
       └─ INSERT outbox_outboxevent (id = event_id, routing_key, payload)
commit  ──► both exist, or neither does
```

`enqueue()` refuses to run outside `transaction.atomic()`, so this can't be skipped by
accident. `Watch.save()` and `Watch.delete()` call it. The admin's bulk delete is
overridden to delete one by one, so it also produces events.

### 7.2 The relay

`relay_outbox` runs in a loop, every second:

1. In a transaction, select the oldest unpublished rows (up to 100), locked with
   `FOR UPDATE SKIP LOCKED`.
2. Publish them one by one, in order. Publisher confirms are on, so each publish only
   returns once RabbitMQ has the message.
3. Set `published_at` on the confirmed rows and commit.

If a publish fails, the rows confirmed before it are still marked and committed, and
the rest wait for the next run. Nothing overtakes an earlier event. If RabbitMQ is
unreachable, the relay closes its connection, waits, and reconnects. Events wait safely
in the outbox in the meantime.

### 7.3 Full state and revisions

Watch events carry the **whole watch**, not what changed. A consumer that missed a
message is put right by the next one.

Every change increments `revision`, read from the database under a row lock so two
concurrent saves can't hand out the same number. A deletion gets the next revision as
well. A consumer keeps the highest revision it has seen per watch and **ignores any
message whose revision is not higher**. That makes redelivered and reordered messages
harmless.

### 7.4 Idempotent consumers

RabbitMQ delivers at least once, and the relay can publish an event twice (see
[8](#8-failure-scenarios)). Each consumer stores the `event_id` values it has
processed, in the same transaction as the effect of the message, and skips ids it has
already seen. Messages are acknowledged only after that transaction commits.

In the watcher this is the `processed_events` table. For watch events the revision
check would already catch most duplicates; the event id makes it hold for any event
type, including ones that carry no revision.

Ack policy in the watcher's consumer:

- handled, or a duplicate: **ack**;
- an error while handling (e.g. the database is briefly unavailable): **nack and
  requeue**, so it's tried again;
- a message that can never be handled (unknown routing key, invalid payload): **reject
  without requeue**, so it can't block the queue.

### 7.5 Bootstrap, then follow

A consumer that starts for the first time, or has lost its data, can't replay the past
from RabbitMQ: a message is gone once it's consumed. So:

1. Bind its queue first, so new events start collecting.
2. Load the current state from `GET /api/watches/`.
3. Process the queued events. Revisions sort out any overlap between the snapshot and
   the events.

## 8. Failure scenarios

| What fails | What happens | Result |
|---|---|---|
| RabbitMQ is down when I save a watch | The watch and its event are committed; the relay can't publish and retries. | Published when RabbitMQ is back. Nothing lost. |
| Database rolls back after the change | The outbox row rolls back with it. | No event. |
| Relay crashes after RabbitMQ confirms, before it commits | The row is still unpublished, so it's published again. | Duplicate, ignored by consumers through `event_id` and `revision`. |
| A publish fails halfway through a batch | Earlier rows are committed as published; the rest wait. | No duplicates for the earlier rows, order kept. |
| Consumer crashes while handling a message | The message wasn't acknowledged, so RabbitMQ redelivers it. | Handled again; idempotency keeps it to one effect. |
| Consumer gets an old or repeated watch event | Revision not higher than what it has. | Ignored. |
| Telegram is down (planned) | Delayed retries, then the dead-letter queue. | Visible and replayable, not lost. |
| A message can't be parsed | Rejected without requeue (planned: to the dead-letter queue). | Doesn't block the queue. |

## 9. Deployment

Everything runs locally with `docker compose up --build`:

| Container | Image | Notes |
|---|---|---|
| `db` | `postgres:17` | One server, one database per service: `core` and `watcher`. Created by `docker/postgres/create-databases.sql` on a new volume. |
| `rabbitmq` | `rabbitmq:4-management` | AMQP on 5672, management UI on 15672. |
| `core` | built from `services/core/Dockerfile` | Port 8000. Health check on `/api/health`. |
| `core-relay` | same image | Starts after `core` is healthy (migrations done) and RabbitMQ is up. |
| `watcher` | built from `services/watcher/Dockerfile` | Port 8001. Runs `alembic upgrade head`, then uvicorn. Doesn't wait for core: it retries the snapshot itself. |

Both images are built from the repo root, because they need `libs/events`. The
services' source is mounted into the containers. core's web app reloads on code changes;
the relay and the watcher need a restart, and changes to `libs/events` need a rebuild.

Configuration comes from environment variables (`DATABASE_URL`, `RABBITMQ_URL`,
`REBRICKABLE_API_KEY`, `DJANGO_*`), with a `.env` file in the repo root for local
values. Without `DATABASE_URL`, core falls back to SQLite. The watcher reads
`WATCHER_*` variables (`WATCHER_DATABASE_URL`, `WATCHER_RABBITMQ_URL`, `WATCHER_CORE_URL`,
`WATCHER_HOME_POSTCODE`, `WATCHER_SOURCES`, `WATCHER_POLL_INTERVAL_SECONDS`), and falls
back to a local SQLite file.

## 10. Testing

| Level | What | How |
|---|---|---|
| Contracts | Round trip through JSON, unknown fields ignored, invalid messages rejected, unique routing keys | `libs/events/tests` |
| Unit, core | Importer, wanted list, watches and their events, outbox relay | Fake Rebrickable API (`httpx.MockTransport`) and a fake publisher; no network |
| Unit, watcher | Matching, distances, watch copies by revision, polling and price drops, outbox, HTTP endpoints | In-memory SQLite (PostgreSQL in CI), the fake source, a fake publisher |
| Consumer | Watch events through the exchange into the watcher; unreadable messages rejected | FastStream's in-memory `TestRabbitBroker` |
| Integration | Publishing through a real RabbitMQ and reading it back | Runs when `RABBITMQ_URL` is set |
| End-to-end | Watch created in core → arrives in the watcher → fake listing polled → `listing.matched` and `listing.price_dropped` on RabbitMQ | By hand against docker-compose so far; automating it, with the notifier, is planned |

CI (GitHub Actions) runs on every push: the contract tests, the core tests against
real PostgreSQL and RabbitMQ, and the watcher tests against real PostgreSQL. It also
fails if a model change in either service has no migration (`makemigrations --check`,
`alembic check`).

## 11. Design decisions

### RabbitMQ rather than Kafka

The traffic is a few kinds of events, routed to a few consumers, each with their own
retries and dead-letter queue. That is what RabbitMQ is built for, and it's light to run
locally. Kafka would be the better choice to replay the full event history to new
consumers, or for high volume. Neither applies here; the bootstrap endpoint covers the
replay need.

### Outbox rather than publishing directly

See [7.1](#71-transactional-outbox). The cost is a polling delay of about a second and
one extra process. Both are acceptable here.

### Full state rather than changes

Events with the full state plus a revision let a consumer recover from any missed or
repeated message without asking core. Change events ("price lowered by €10") would need
every message, exactly once, in order.

### Django for core, FastAPI for the new services

core's main value is the Django admin, which comes for free. The watcher and notifier
have no UI. They are mostly network I/O (polling APIs, consuming messages), which suits
an async stack. FastStream adds RabbitMQ consumers that validate with the same pydantic
models, and runs inside the FastAPI process. django-ninja gives core's API the same
pydantic style.

### Shared contracts package

One source of truth for event shapes, tested on its own, versioned with the services in
the same repo. The risk of a shared package (coupling) is limited by keeping it to
contracts only: no logic, no database code.

## 12. Known limitations

- **Bulk queryset operations skip events.** `Watch.objects.update()` and
  `Watch.objects.filter(...).delete()` don't call `save()` or `delete()`, so they produce
  no events. Use instance methods; the admin does.
- **The outbox table grows.** Published rows are never cleaned up yet. A periodic
  cleanup of rows published more than a few days ago is needed.
- **One relay at a time.** `SKIP LOCKED` keeps two relays from sending the same row,
  but two relays could publish batches out of order. That's fine with revisions, but
  for strict order run one relay.
- **Polling delay.** Events go out within about a second, not instantly. PostgreSQL
  `LISTEN/NOTIFY` could wake the relay instead.
- **The internal API has no authentication.** It's only meant for the docker-compose
  network. It would need a service token before running anywhere else.
- **A failed save leaves the in-memory revision raised.** If `Watch.save()` rolls back,
  the instance's `revision` is one too high. The next save reads it from the database
  again, so it doesn't end up in an event.
- **Outbox code exists twice.** core (Django ORM) and the watcher (SQLAlchemy) each
  have their own small outbox. Sharing it would mean a shared library with database
  code in it, which is the coupling `libs/events` is meant to avoid.
- **Requeued errors retry immediately.** A message that keeps failing for a reason
  other than being unreadable is requeued over and over. Delayed retries and a
  dead-letter queue are planned.
- **The fake source forgets on restart.** Its listings live in memory; what the watcher
  stored about them stays in its database.
- **Incomplete-set words are naive.** "compleet, niets ontbreekt" contains *ontbreekt*,
  so it looks incomplete. That only matters for watches that refuse incomplete sets.
