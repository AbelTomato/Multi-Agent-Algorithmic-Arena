#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

: "${COMPOSE_FILE:=/opt/multi-agent-arena/app/compose.yaml}"
: "${BACKUP_DIR:=/opt/multi-agent-arena/backups}"
: "${BACKUP_SERVICE:=multi-agent-arena-postgres-backup.service}"
: "${BACKUP_MAX_AGE_SECONDS:=93600}"
: "${DISK_PATH:=/opt}"
: "${DISK_MAX_PERCENT:=80}"
: "${HTTP_TIMEOUT_SECONDS:=10}"
: "${LOG_WINDOW:=15m}"
: "${NGINX_ACCESS_LOG:=/var/log/nginx/multi-agent-arena.access.log}"
: "${NGINX_ERROR_LOG:=/var/log/nginx/multi-agent-arena.error.log}"

failures=()
record_failure() {
    failures+=("$1")
}

check_docker_health() {
    local service="$1"
    local container="$2"
    local state health

    if ! state="$(docker inspect "$container" --format '{{.State.Status}}' 2>/dev/null)"; then
        record_failure "$service container unavailable"
        return
    fi
    if [[ "$state" != running ]]; then
        record_failure "$service container not running"
        return
    fi
    if ! health="$(docker inspect "$container" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null)"; then
        record_failure "$service health unavailable"
    elif [[ "$health" != healthy ]]; then
        record_failure "$service health is $health"
    fi
}

check_http() {
    local name="$1"
    local url="$2"
    if ! curl --fail --silent --show-error --max-time "$HTTP_TIMEOUT_SECONDS" \
        -o /dev/null "$url"; then
        record_failure "$name HTTP check failed"
    fi
}

check_disk() {
    local used_percent
    used_percent="$(df -P "$DISK_PATH" | awk 'NR == 2 {gsub(/%/, "", $5); print $5}')"
    if [[ -z "$used_percent" || "$used_percent" -ge "$DISK_MAX_PERCENT" ]]; then
        record_failure "disk usage threshold exceeded"
    fi
}

check_backup() {
    local latest age result
    latest="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'multi-agent-arena-*.sql.gz' \
        -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)"
    if [[ -z "$latest" || ! -f "$latest" ]]; then
        record_failure "backup file missing"
        return
    fi

    age=$(( $(date +%s) - $(stat -c '%Y' "$latest") ))
    if (( age < 0 || age > BACKUP_MAX_AGE_SECONDS )); then
        record_failure "backup file is stale"
    fi
    if ! gzip -t "$latest" 2>/dev/null; then
        record_failure "backup gzip validation failed"
    fi

    result="$(systemctl show "$BACKUP_SERVICE" -p Result --value 2>/dev/null || true)"
    if [[ "$result" != success ]]; then
        record_failure "backup service result is ${result:-unknown}"
    fi
}

check_sensitive_logs() {
    local backend_pattern='authorization|api[_ -]?key|bearer|password|database_url|secret|sk-[A-Za-z0-9]+'
    local access_pattern='(authorization|bearer):[[:space:]]+[A-Za-z0-9._~-]{20,}|(api[_ -]?key|secret|password|token)=[A-Za-z0-9._~+/%-]{20,}|sk-[A-Za-z0-9]{20,}'
    if docker compose -f "$COMPOSE_FILE" logs --since="$LOG_WINDOW" backend 2>&1 \
        | grep -Eiq "$backend_pattern"; then
        record_failure "backend logs contain sensitive-field pattern"
    fi
    if [[ -f "$NGINX_ACCESS_LOG" ]] && tail -n 1000 "$NGINX_ACCESS_LOG" | grep -Eiq "$access_pattern"; then
        record_failure "Nginx access log contains credential-like value"
    fi
    if [[ -f "$NGINX_ERROR_LOG" ]] && tail -n 1000 "$NGINX_ERROR_LOG" | grep -Eiq "$backend_pattern"; then
        record_failure "Nginx error log contains sensitive-field pattern"
    fi
}

check_docker_health backend app-backend-1
check_docker_health postgres app-postgres-1
check_http health http://127.0.0.1/health
check_http problems http://127.0.0.1/api/problems
check_disk
check_backup
check_sensitive_logs

if ((${#failures[@]} > 0)); then
    printf 'monitor_failed checks=%s\n' "$(IFS=,; echo "${failures[*]}")" >&2
    exit 1
fi

printf 'monitor_ok checked=backend,postgres,http,disk,backup,logs\n'