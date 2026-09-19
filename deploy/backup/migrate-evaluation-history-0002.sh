#!/usr/bin/env bash
# Run only after explicit approval for production backup and migration 0002.
set -Eeuo pipefail
umask 077

readonly app_dir=/opt/multi-agent-arena/app
readonly image=sha256:2cbcc94b937b2a4ff9643afe9669a2d0faa463b43dd8f5daa5bce4cbbc27e9cc
readonly backup_dir=/opt/multi-agent-arena/history-migration-20260919-1544

cd "$app_dir"
docker image inspect "$image" >/dev/null
test "$(docker network inspect --format '{{.Name}}' app_arena_private)" = app_arena_private

state="$(docker compose exec -T postgres sh -c 'psql -X -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "SELECT version_num FROM alembic_version"')"
test "$state" = 0001
table_exists="$(docker compose exec -T postgres sh -c 'psql -X -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_catalog.pg_tables WHERE tablename = '\''evaluation_runs'\'' AND schemaname = '\''public'\''"')"
test "$table_exists" = 0

# An existing directory is an error; never overwrite prior recovery material.
mkdir "$backup_dir"
cp -p compose.yaml "$backup_dir/compose.yaml"
cp -p /etc/nginx/conf.d/multi-agent-arena.conf "$backup_dir/nginx.conf"
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
    | gzip -c > "$backup_dir/pre-0002.sql.gz"
test -s "$backup_dir/pre-0002.sql.gz"
gzip -t "$backup_dir/pre-0002.sql.gz"
sha256sum "$backup_dir/pre-0002.sql.gz" > "$backup_dir/pre-0002.sha256"
sha256sum -c "$backup_dir/pre-0002.sha256"

# Start a migration-only container, not the ASGI app. Do not publish any ports.
# SQLAlchemy's asyncpg connections need server_settings, not libpq PGOPTIONS.
docker run --rm --network app_arena_private \
    --env-file "$app_dir/.env.deploy" \
    --entrypoint python "$image" -c '
from alembic import command
from alembic.config import Config
import sqlalchemy.ext.asyncio as async_sa

original_factory = async_sa.async_engine_from_config
def limited_engine(*args, **kwargs):
    options = dict(kwargs.get("connect_args", {}))
    server_settings = dict(options.get("server_settings", {}))
    server_settings.update(lock_timeout="5s", statement_timeout="60s")
    options["server_settings"] = server_settings
    kwargs["connect_args"] = options
    return original_factory(*args, **kwargs)

async_sa.async_engine_from_config = limited_engine
command.upgrade(Config("/app/alembic.ini"), "0002")
'

state="$(docker compose exec -T postgres sh -c 'psql -X -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "SELECT version_num FROM alembic_version"')"
test "$state" = 0002
docker compose exec -T postgres sh -c 'psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "BEGIN READ ONLY; SELECT indexname FROM pg_indexes WHERE tablename = '\''evaluation_runs'\'' AND schemaname = '\''public'\''; SELECT count(*) AS initial_run_count FROM evaluation_runs; COMMIT;"'
printf 'migration_0002_verified backup_dir=%s\n' "$backup_dir"