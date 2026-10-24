# lego-tracker

I buy old LEGO sets second-hand. They're rarely complete, and the good deals go fast.
This app keeps track of the sets I own, which parts each one is missing, and turns
those missing parts into a BrickLink wanted list so I can order them in one go.
Now in progress: watching second-hand marketplaces for cheap, nearby offers and notifying me
when a new one shows up.

## What works today

- **Import a set's full parts list** from [Rebrickable](https://rebrickable.com/api/),
  including the BrickLink part and color ids (the two sites number things differently).
  Imports are idempotent: re-running one applies Rebrickable's corrections instead of
  creating duplicates.
- **Track owned copies** of a set (price paid, where it came from, condition) and
  **mark missing parts** in the Django admin. Validation stops you from marking more
  parts than the set contains, or parts from another set.
- **Export a BrickLink wanted list** for any selection of owned sets. Identical parts
  are combined across sets; parts without a BrickLink mapping are reported, not
  silently dropped.

## Architecture

The app is being split into small services that talk through RabbitMQ events.
For a single-user hobby app that is more machinery than it needs; I'm doing it on
purpose, to practise service boundaries and reliable messaging on a domain I know.

```
                 ┌──────────────────┐  watch.upserted / watch.deleted   ┌─────────────┐
  me ──admin──►  │ core (Django)    │ ──────────────┐                    │ watcher     │ ◄── eBay
                 │ catalog          │               ▼                    │ (planned)   │
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

| Part | What it does | Stack |
|---|---|---|
| `services/core` | Catalog, owned sets, missing parts, watches; publishes watch events | Django, django-ninja, PostgreSQL |
| `libs/events` | Event contracts shared by every service | pydantic |
| `services/watcher` | Polls marketplaces, deduplicates, publishes matches (planned) | FastAPI, FastStream, SQLAlchemy |
| `services/notifier` | Sends Telegram messages for matches (planned) | FastAPI, FastStream |

**How events stay reliable**

- **Transactional outbox.** A change and its event are written in one database
  transaction; `relay_outbox` publishes them afterwards, with publisher confirms.
  So an event is never lost when RabbitMQ is down, and never sent for a change
  that rolled back.
- **At-least-once, deduplicated.** If the relay crashes between the broker's
  confirm and its own commit, it sends the event again. Every event has an
  `event_id` that consumers use to skip duplicates.
- **Full state plus a revision.** Watch events carry the whole watch and a
  revision number, so a consumer that receives an old or repeated message can
  simply ignore it.
- **Contracts in one place.** `libs/events` defines every event as a pydantic model.
  Consumers ignore fields they don't know, so producers can add fields safely.
- **Bootstrap, then follow.** A new consumer loads the current watches from
  `GET /api/watches/` and keeps up through events from then on.

The full design, with the event catalog, failure scenarios and design decisions, is in
[docs/architecture.md](docs/architecture.md).

Inside core, **catalog** is reference data mirrored from Rebrickable and
**collection** is my own data, so a catalog re-import never touches what I own.
The Rebrickable client takes an injectable `httpx.Client`, so tests run against an
in-memory fake API with no network and no key.

## Running it

With Docker:

```bash
cp .env.example .env              # add your free Rebrickable API key
docker compose up --build
docker compose exec core python manage.py import_set --colors 6086-1   # Black Knight's Castle
docker compose exec core python manage.py createsuperuser
```

- Admin: http://localhost:8000/admin/
- API docs: http://localhost:8000/api/docs
- RabbitMQ: http://localhost:15672 (lego / lego)

Without Docker (Python 3.12+, SQLite, no events published):

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows; use .venv/bin/activate on macOS/Linux
pip install -e "libs/events[dev]" -e "services/core[dev]"
cd services/core
python manage.py migrate
python manage.py runserver
```

Tests: run `pytest` in `libs/events` and in `services/core`. The RabbitMQ round-trip
test only runs when `RABBITMQ_URL` is set; CI runs everything against PostgreSQL
and RabbitMQ.

## Roadmap

- [x] **Watches**: "set 6086-1, max €150 incl. shipping, within 50 km of Genk", published as events.
- [ ] **Watcher service** with a fake source first, deduplication and `listing.matched` events.
- [ ] **Notifier service** with Telegram, retries and a dead-letter queue.
- [ ] **Marketplace sources** as pluggable modules, starting with eBay's official Browse API.
      Sites without a public API only via their own saved-search email alerts, not scraping.
- [ ] **De-duplication and price tracking**: recognize the same listing across polls, track
      price drops, compute total price including shipping and distance from home.
- [ ] **Deal score** against typical BrickLink prices.
- [ ] Daily digest of new matches.
- [ ] **Scheduled polling** with retries and per-source rate limits.
- [ ] Minifigures in set inventories.
