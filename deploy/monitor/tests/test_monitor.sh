#!/usr/bin/env bash

set -Eeuo pipefail

readonly project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
readonly monitor_script="$project_root/deploy/monitor/multi-agent-arena-monitor.sh"

test_root="$(mktemp -d)"
trap 'rm -r -- "$test_root"' EXIT

make_fake_commands() {
    local fake_bin="$1"
    mkdir -p "$fake_bin"

    cat >"$fake_bin/docker" <<'SCRIPT'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$1" == "inspect" ]]; then
    if [[ "$*" == *"State.Status"* ]]; then printf 'running\n'; else printf 'healthy\n'; fi
elif [[ "$1" == "ps" ]]; then
    if [[ "${FAKE_ARENA_RESIDUE:-0}" == "1" ]]; then printf 'deadbeef\n'; fi
elif [[ "$1" == "compose" ]]; then
    exit 0
fi
SCRIPT
    cat >"$fake_bin/systemctl" <<'SCRIPT'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$1" == "is-active" && "${FAKE_CONTROLLER_INACTIVE:-0}" == "1" && "$3" == "multi-agent-arena-sandbox-controller.service" ]]; then
    exit 3
fi
if [[ "$1" == "show" ]]; then printf 'success\n'; fi
SCRIPT
    cat >"$fake_bin/curl" <<'SCRIPT'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${FAKE_CONTROLLER_HTTP_FAILURE:-0}" == "1" && "$*" == *"172.30.0.1:8001/health"* ]]; then
    exit 22
fi
SCRIPT
    chmod +x "$fake_bin/docker" "$fake_bin/systemctl" "$fake_bin/curl"
}

run_monitor() {
    local scenario="$1"
    shift
    local scenario_root="$test_root/$scenario"
    local fake_bin="$scenario_root/bin"
    local backup_dir="$scenario_root/backups"
    mkdir -p "$backup_dir"
    printf 'backup\n' | gzip -c >"$backup_dir/multi-agent-arena-test.sql.gz"
    make_fake_commands "$fake_bin"

    set +e
    local output
    output="$(PATH="$fake_bin:$PATH" BACKUP_DIR="$backup_dir" DISK_PATH="$scenario_root" COMPOSE_FILE="$scenario_root/compose.yaml" "$@" "$monitor_script" 2>&1)"
    local status=$?
    set -e
    printf '%s\n' "$status" >"$scenario_root/status"
    printf '%s\n' "$output" >"$scenario_root/output"
}

assert_failure_contains() {
    local scenario="$1"
    local expected="$2"
    [[ "$(cat "$test_root/$scenario/status")" != "0" ]]
    grep -Fqx "monitor_failed checks=$expected" "$test_root/$scenario/output"
}

run_monitor healthy env EVALUATION_ENABLED=true
[[ "$(cat "$test_root/healthy/status")" == "0" ]]
grep -Fqx 'monitor_ok checked=backend,postgres,http,sandbox,disk,backup,logs' "$test_root/healthy/output"

run_monitor controller-inactive env EVALUATION_ENABLED=true FAKE_CONTROLLER_INACTIVE=1
assert_failure_contains controller-inactive 'sandbox controller systemd inactive'

run_monitor controller-http env EVALUATION_ENABLED=true FAKE_CONTROLLER_HTTP_FAILURE=1
assert_failure_contains controller-http 'sandbox controller HTTP check failed'

run_monitor arena-residue env EVALUATION_ENABLED=true FAKE_ARENA_RESIDUE=1
assert_failure_contains arena-residue 'exited Arena task residue detected'

run_monitor evaluation-disabled env
[[ "$(cat "$test_root/evaluation-disabled/status")" == "0" ]]
grep -Fqx 'monitor_ok checked=backend,postgres,http,disk,backup,logs' "$test_root/evaluation-disabled/output"