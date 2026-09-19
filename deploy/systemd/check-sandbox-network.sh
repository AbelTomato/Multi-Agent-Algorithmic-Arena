#!/bin/sh
set -eu

network="${SANDBOX_DOCKER_NETWORK:-app_arena_sandbox}"
expected_driver="bridge"
expected_internal="true"
expected_subnet="172.30.0.0/24"
expected_gateway="172.30.0.1"

if ! driver="$(/usr/bin/docker network inspect "$network" --format '{{.Driver}}' 2>/dev/null)"; then
    printf 'sandbox network check failed: network unavailable\n' >&2
    exit 1
fi

internal="$(/usr/bin/docker network inspect "$network" --format '{{.Internal}}' 2>/dev/null)"
network_name="$(/usr/bin/docker network inspect "$network" --format '{{.Name}}' 2>/dev/null)"
subnet="$(/usr/bin/docker network inspect "$network" --format '{{(index .IPAM.Config 0).Subnet}}' 2>/dev/null)"
gateway="$(/usr/bin/docker network inspect "$network" --format '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null)"

if [ "$driver" != "$expected_driver" ] || [ "$internal" != "$expected_internal" ] || [ "$network_name" != "$network" ]; then
    printf 'sandbox network check failed: unexpected driver, internal flag, or name\n' >&2
    exit 1
fi

if [ "$subnet" != "$expected_subnet" ] || [ "$gateway" != "$expected_gateway" ]; then
    printf 'sandbox network check failed: unexpected subnet or gateway\n' >&2
    exit 1
fi

printf 'sandbox_network_ok network=%s subnet=%s gateway=%s\n' "$network" "$expected_subnet" "$expected_gateway"