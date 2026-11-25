#!/bin/sh
# The-brain on-prem installer (Stage 4, slice 7).
# One host, one Python 3.10+: creates a venv, installs the engine
# with its license-checked dependencies, runs a smoke test, and lays
# down the tenant store root. No network access is needed after the
# wheel cache is populated (set PIP_NO_INDEX=1 + --find-links for
# air-gapped installs).
set -eu

PREFIX="${BRAIN_PREFIX:-/opt/the-brain}"
TENANTS="${BRAIN_TENANTS:-$PREFIX/tenants}"
PYTHON="${PYTHON:-python3}"

echo "== the-brain on-prem install -> $PREFIX"
"$PYTHON" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --upgrade pip
"$PREFIX/venv/bin/pip install" 2>/dev/null || true
"$PREFIX/venv/bin/pip" install ${PIP_FIND_LINKS:+--no-index --find-links "$PIP_FIND_LINKS"} .

mkdir -p "$TENANTS"
chmod 700 "$TENANTS"

echo "== smoke test"
"$PREFIX/venv/bin/python" - << 'PYEOF'
from brain_core.records.models import Factory, Location
from brain_core.tenancy import TenantStore
import os
store = TenantStore(os.environ.get("BRAIN_TENANTS", "/opt/the-brain/tenants"))
store.put_factory("smoke", "check", Factory(locations=[Location(name="P")]))
assert store.get_factory("smoke", "check").locations[0].name == "P"
print("smoke OK: tenant store read/write")
PYEOF

echo "== installed. Tenant data root: $TENANTS"
