-- One PostgreSQL server, one database per service. Runs only when the volume is new;
-- for an existing volume: docker compose exec db createdb -U lego <name>
CREATE DATABASE watcher;
CREATE DATABASE notifier;
