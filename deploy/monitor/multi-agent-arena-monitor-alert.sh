#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

: "${MONITOR_SCRIPT:=/usr/local/sbin/multi-agent-arena-monitor}"
: "${MAIL_SCRIPT:=/usr/local/libexec/multi-agent-arena-monitor-mail.py}"
: "${MAIL_ENV:=/etc/multi-agent-arena/mail.env}"
: "${ALERT_STATE_DIR:=/var/lib/multi-agent-arena-monitor}"
: "${ALERT_REPEAT_SECONDS:=3600}"

mkdir -p -- "$ALERT_STATE_DIR"
chmod 700 -- "$ALERT_STATE_DIR"
exec 9>"$ALERT_STATE_DIR/monitor.lock"
flock -n 9 || exit 0

output_file="$(mktemp "$ALERT_STATE_DIR/monitor-output.XXXXXX")"
trap 'rm -f -- "$output_file"' EXIT

set +e
"$MONITOR_SCRIPT" >"$output_file" 2>&1
monitor_status=$?
set -e

now="$(date +%s)"
previous_status="$(cat "$ALERT_STATE_DIR/status" 2>/dev/null || printf 'unknown')"
last_alert="$(cat "$ALERT_STATE_DIR/last-alert" 2>/dev/null || printf '0')"
hostname_value="$(hostname -s 2>/dev/null || hostname)"

write_state() {
    local name="$1"
    local value="$2"
    local state_file
    state_file="$(mktemp "$ALERT_STATE_DIR/.state.XXXXXX")"
    printf '%s\n' "$value" >"$state_file"
    chmod 600 -- "$state_file"
    mv -- "$state_file" "$ALERT_STATE_DIR/$name"
}

send_alert() {
    local subject="$1"
    local body="$2"
    if [[ ! -r "$MAIL_ENV" ]]; then
        printf 'alert_not_sent reason=mail_configuration_missing\n' >&2
        return 2
    fi
    if ! printf '%s\n' "$body" | "$MAIL_SCRIPT" --config "$MAIL_ENV" --subject "$subject"; then
        printf 'alert_not_sent reason=smtp_send_failed\n' >&2
        return 1
    fi
    return 0
}

if (( monitor_status == 0 )); then
    cat -- "$output_file"
    write_state status ok
    if [[ "$previous_status" == failed ]]; then
        recovery_body="$(printf '%s\n\nhost=%s\ntime=%s\nstatus=recovered\n\n%s' \
            'Multi-Agent Arena monitor recovered.' \
            "$hostname_value" \
            "$(date --iso-8601=seconds)" \
            'The latest runtime checks passed. Review journald if the preceding failure was unexpected.')"
        if send_alert '[Multi-Agent Arena][RECOVERY] Monitor recovered' "$recovery_body"; then
            printf 'recovery_alert_sent\n'
        fi
    fi
    exit 0
fi

cat -- "$output_file" >&2
write_state status failed

should_alert=0
if [[ "$previous_status" != failed ]]; then
    should_alert=1
elif [[ -r "$MAIL_ENV" && ! -e "$ALERT_STATE_DIR/last-alert" ]]; then
    # Send immediately when mail configuration is added during an ongoing
    # incident; missing configuration does not start the cooldown timer.
    should_alert=1
elif [[ -r "$MAIL_ENV" && "$last_alert" =~ ^[0-9]+$ ]] && (( now - last_alert >= ALERT_REPEAT_SECONDS )); then
    should_alert=1
fi

if (( should_alert == 1 )); then
    failure_summary="$(sed -n 's/^monitor_failed checks=//p' "$output_file" | head -n 1)"
    : "${failure_summary:=unknown monitor failure}"
    failure_body="$(printf '%s\n\nhost=%s\ntime=%s\nstatus=failed\n\nChecks:\n%s\n\n%s' \
        'Multi-Agent Arena monitor failed.' \
        "$hostname_value" \
        "$(date --iso-8601=seconds)" \
        "$failure_summary" \
        'The monitor service remains failed. Inspect the relevant systemd and application status without exposing secrets.')"
    if send_alert '[Multi-Agent Arena][CRITICAL] Monitor failed' "$failure_body"; then
        write_state last-alert "$now"
        printf 'failure_alert_sent\n' >&2
    else
        alert_status=$?
        if [[ "$alert_status" -eq 1 ]]; then
        # An SMTP attempt was made and failed; throttle retries. A missing
        # configuration returns 2 and must not delay the first real alert.
            write_state last-alert "$now"
        fi
    fi
fi

exit "$monitor_status"