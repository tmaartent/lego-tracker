# lego-tracker

I buy old LEGO sets second-hand. They're rarely complete, and the good deals go fast.
This app keeps track of the sets I own, which parts each one is missing, and turns
those missing parts into a BrickLink wanted list so I can order them in one go.
It also watches second-hand marketplaces for cheap, nearby offers and notifies me on
Telegram when a new one shows up.

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
- **Watch for sets**: "6086-1, max €150 including shipping, within 50 km of Genk".
  The watcher service polls its sources, recognizes the set number in listing titles,
  works out the total price and the distance from home, and announces new matches and
  price drops as events. It searches eBay through the official Browse API, and has a
  fake marketplace for demos.
- **Get notified on Telegram** of every new match and price drop. Failed sends are
  retried with increasing delays; messages that keep failing wait in a dead-letter
  queue until they're replayed.

## Architecture

The app is being split into small services that talk through RabbitMQ events.
For a single-user hobby app that is more machinery than it needs; I'm doing it on
purpose, to practise service boundaries and reliable messaging on a domain I know.

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
                                            │             │
                                            └─────────────┘
```

| Part | What it does | Stack |
|---|---|---|
| `services/core` | Catalog, owned sets, missing parts, watches; publishes watch events | Django, django-ninja, PostgreSQL |
| `libs/events` | Event contracts shared by every service | pydantic |
| `services/watcher` | Polls marketplaces, deduplicates, matches listings to watches, publishes matches and price drops | FastAPI, FastStream, SQLAlchemy, Alembic, PostgreSQL |
| `services/notifier` | Sends Telegram messages for matches and price drops, with delayed retries and a dead-letter queue | FastAPI, FastStream, SQLAlchemy, Alembic, PostgreSQL |

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
- Watcher API docs: http://localhost:8001/docs
- Notifier API docs: http://localhost:8002/docs
- RabbitMQ: http://localhost:15672 (lego / lego)

To see a match: create a watch for 6086-1 in the admin, then put a listing on the fake
marketplace and poll it:

```bash
curl -X POST localhost:8001/sources/fake/listings -H 'Content-Type: application/json' \
  -d '{"external_id": "demo-1", "title": "LEGO 6086 kasteel compleet", "url": "https://example.test",
       "price": "120", "shipping": "0", "postcode": "3500"}'
curl -X POST localhost:8001/sources/fake/poll
curl 'localhost:8001/listings?matched=true'
```

The notifier sends it, or logs it if Telegram isn't set up (`docker compose logs notifier`).
Post the same listing with a lower price and poll again for a price drop.

To get the messages on Telegram: create a bot with [@BotFather](https://t.me/BotFather),
put its token in `.env` as `NOTIFIER_TELEGRAM_BOT_TOKEN`, send the bot a message, and
find your chat id with `docker compose exec notifier python -m notifier.find_chat_id`.
Put that in `.env` as `NOTIFIER_TELEGRAM_CHAT_ID` and run `docker compose up -d notifier`.
Group and channel ids start with a minus sign; keep it.

To search eBay: create a free developer account at https://developer.ebay.com, and a
production keyset. eBay asks how you handle its account deletion notifications; this
app stores no eBay user data, so you can apply for the exemption. Put the App ID and
Cert ID in `.env` as `WATCHER_EBAY_CLIENT_ID` and `WATCHER_EBAY_CLIENT_SECRET`, add
`WATCHER_SOURCES=["fake","ebay"]`, and run `docker compose up -d watcher`. It searches
every 15 minutes; `curl -X POST localhost:8001/sources/ebay/poll` searches now.

Without Docker (Python 3.12+, SQLite, no events published):

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows; use .venv/bin/activate on macOS/Linux
pip install -e "libs/events[dev]" -e "services/core[dev]"
cd services/core
python manage.py migrate
python manage.py runserver
```

Tests: run `pytest` in `libs/events` and in each service under `services/`
(`pip install -e "services/<name>[dev]"` first). Locally they use SQLite and
in-memory fakes. The tests against a real RabbitMQ only run when `RABBITMQ_URL` (core)
or `NOTIFIER_TEST_RABBITMQ_URL` (notifier) is set; CI runs everything against
PostgreSQL and RabbitMQ.

## Roadmap

- [x] **Watches**: "set 6086-1, max €150 incl. shipping, within 50 km of Genk", published as events.
- [x] **Watcher service** with a fake source, deduplication, distance from home, and
      `listing.matched` / `listing.price_dropped` events.
- [x] **Notifier service** with Telegram, delayed retries and a dead-letter queue.
- [ ] **Email alerts source**: saved-search alerts from 2dehands and Marktplaats, read over IMAP.
      Sites without a public API only via their own saved-search email alerts, not scraping.
- [x] **eBay source** through the official Browse API.
- [ ] **Offers in core**: show matched listings in the admin, next to the watch.
- [ ] **Deal score** against typical BrickLink prices.
- [ ] Daily digest of new matches.
- [ ] **Back-off** when a marketplace rate-limits (each source already has its own poll interval).
- [ ] Minifigures in set inventories.
