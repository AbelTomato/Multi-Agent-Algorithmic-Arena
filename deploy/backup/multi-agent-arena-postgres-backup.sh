#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

: "${COMPOSE_FILE:=/opt/multi-agent-arena/app/compose.yaml}"
: "${BACKUP_DIR:=/opt/multi-agent-arena/backups}"
: "${OSS_BUCKET_URI:?OSS_BUCKET_URI must be set, for example oss://bucket/multi-agent-arena/postgres}"
: "${OSS_REGION:=cn-hangzhou}"
: "${OSSUTIL_MODE:=EcsRamRole}"

readonly compose_service="postgres"
readonly timestamp="$(date +%F-%H%M%S)"
readonly filename="multi-agent-arena-${timestamp}.sql.gz"
readonly object_uri="${OSS_BUCKET_URI%/}/${filename}"

tmp_file=""
cleanup() {
    if [[ -n "$tmp_file" ]]; then
        rm -f -- "$tmp_file"
    fi
}
trap cleanup EXIT

mkdir -p -- "$BACKUP_DIR"
chmod 700 -- "$BACKUP_DIR"

tmp_file="$(mktemp "$BACKUP_DIR/.multi-agent-arena-${timestamp}.XXXXXX.sql.gz")"
chmod 600 -- "$tmp_file"

docker compose -f "$COMPOSE_FILE" exec -T "$compose_service" \
    sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
    | gzip -c > "$tmp_file"

test -s "$tmp_file"
gzip -t "$tmp_file"

readonly final_file="$BACKUP_DIR/$filename"
mv -- "$tmp_file" "$final_file"
tmp_file=""
chmod 600 -- "$final_file"

readonly local_sha256="$(sha256sum "$final_file" | awk '{print $1}')"
readonly local_bytes="$(stat -c '%s' "$final_file")"

ossutil cp "$final_file" "$object_uri" \
    --mode "$OSSUTIL_MODE" \
    --region "$OSS_REGION" \
    --quiet

readonly remote_sha256="$(
    ossutil cp "$object_uri" - \
        --mode "$OSSUTIL_MODE" \
        --region "$OSS_REGION" \
        --quiet \
        | sha256sum \
        | awk '{print $1}'
)"

test "$local_sha256" = "$remote_sha256"
printf 'backup_verified object=%s bytes=%s sha256=%s\n' \
    "$object_uri" "$local_bytes" "$local_sha256"