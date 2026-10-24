# lego-tracker

I buy old LEGO sets second-hand. They're rarely complete, and the good deals go fast.
This app keeps track of the sets I own, which parts each one is missing, and turns
those missing parts into a BrickLink wanted list so I can order them in one go.
Next up: watching second-hand marketplaces for cheap, nearby offers and notifying me
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

```
            Rebrickable API                      BrickLink (XML upload)
                  │                                       ▲
                  ▼                                       │
  ┌───────────────────────────┐        ┌──────────────────┴─────────┐
  │ catalog                   │        │ collection                 │
  │  rebrickable.py  client   │        │  OwnedSet, MissingPart     │
  │  importer.py     upserts  │◄───────│  wanted_list.py  combine   │
  │  LegoSet, Part, Color,    │  FK    │                  → XML     │
  │  InventoryPart            │        │                            │
  └───────────────────────────┘        └────────────────────────────┘
                  │                                       │
                  └──────────────► PostgreSQL ◄────────────┘
```

- **catalog** is reference data mirrored from Rebrickable. **collection** is my own data.
  Keeping them apart means a catalog re-import never touches what I own.
- The Rebrickable client takes an injectable `httpx.Client`, so tests run against an
  in-memory fake API with no network and no key.

## Running it

Requires Python 3.12+.

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows; use .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
cp .env.example .env              # add your free Rebrickable API key

python manage.py migrate
python manage.py import_set --colors 6086-1   # Black Knight's Castle
python manage.py createsuperuser
python manage.py runserver        # http://localhost:8000/admin/
```

Without `DATABASE_URL` it uses SQLite. With Docker, `docker compose up` runs it on PostgreSQL.

```bash
pytest
```

CI runs the tests against PostgreSQL on every push.

## Roadmap

- [ ] **Offer watches**: "set 6086-1, max €150 incl. shipping, within 50 km of Genk".
- [ ] **Marketplace sources** as pluggable modules, starting with eBay's official Browse API.
      Sites without a public API only via their own saved-search email alerts, not scraping.
- [ ] **De-duplication and price tracking**: recognize the same listing across polls, track
      price drops, compute total price including shipping and distance from home.
- [ ] **Deal score** against typical BrickLink prices.
- [ ] **Notifications** via Telegram for new matches, plus a daily digest.
- [ ] **Scheduled polling** with retries and per-source rate limits.
- [ ] Minifigures in set inventories.
