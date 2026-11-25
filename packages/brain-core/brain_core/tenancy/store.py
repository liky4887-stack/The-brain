"""Multi-tenant storage with path-containment isolation (Stage 4,
slice 7).

Each tenant gets its own directory tree (factories, plans, audit
logs). Isolation is STRUCTURAL: tenant ids are validated slugs and
every resolved path must stay inside that tenant's directory - a
crafted id ("../other", absolute paths, separators) is rejected
before the filesystem is touched. No shared mutable state between
tenants: the AuditLog per tenant is an independent file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..audit import AuditLog
from ..records.models import Factory

_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|"
                        r"^[a-z0-9]$")


class TenantError(ValueError):
    pass


class TenantStore:
    """Filesystem store: root/<tenant>/{factories,plans,audit}."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _tenant_dir(self, tenant_id: str) -> Path:
        if not _TENANT_RE.match(tenant_id or ""):
            raise TenantError(f"invalid tenant id: {tenant_id!r}")
        d = (self.root / tenant_id).resolve()
        if d.parent != self.root:      # containment, belt and braces
            raise TenantError(f"tenant id escapes root: {tenant_id!r}")
        return d

    @staticmethod
    def _name(name: str) -> str:
        if not _TENANT_RE.match(name or ""):
            raise TenantError(f"invalid object name: {name!r}")
        return name

    def put_factory(self, tenant_id: str, name: str,
                    factory: Factory) -> Path:
        d = self._tenant_dir(tenant_id) / "factories"
        d.mkdir(parents=True, exist_ok=True)
        p = d / (self._name(name) + ".json")
        p.write_text(factory.model_dump_json(indent=1))
        return p

    def get_factory(self, tenant_id: str, name: str) -> Factory:
        p = self._tenant_dir(tenant_id) / "factories" / (
            self._name(name) + ".json")
        if not p.exists():
            raise TenantError(f"no factory {name!r} for tenant "
                              f"{tenant_id!r}")
        return Factory.model_validate(json.loads(p.read_text()))

    def put_plan(self, tenant_id: str, name: str,
                 assignments: list[dict]) -> Path:
        d = self._tenant_dir(tenant_id) / "plans"
        d.mkdir(parents=True, exist_ok=True)
        p = d / (self._name(name) + ".json")
        p.write_text(json.dumps(assignments, indent=1))
        return p

    def get_plan(self, tenant_id: str, name: str) -> list[dict]:
        p = self._tenant_dir(tenant_id) / "plans" / (
            self._name(name) + ".json")
        if not p.exists():
            raise TenantError(f"no plan {name!r} for tenant "
                              f"{tenant_id!r}")
        return json.loads(p.read_text())

    def audit_log(self, tenant_id: str) -> AuditLog:
        """The tenant's own append-only decision log."""
        d = self._tenant_dir(tenant_id) / "audit"
        d.mkdir(parents=True, exist_ok=True)
        return AuditLog(d / "decisions.jsonl")

    def list_tenants(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir()
                      if p.is_dir())
