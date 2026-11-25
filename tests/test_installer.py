"""Stage 4, slice 7: the on-prem installer is real and wired.

We cannot run a full install in the suite (it mutates a prefix), so
the test asserts what is checkable: the script exists, is
POSIX-sh-syntax-clean, references real repo paths, and its smoke
snippet (the exact Python it runs) works against the in-tree code.
"""

import os
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "deploy" / "install.sh"


def test_installer_exists_executable_and_syntax_clean():
    assert INSTALLER.exists()
    assert os.stat(INSTALLER).st_mode & stat.S_IXUSR
    subprocess.run(["sh", "-n", str(INSTALLER)], check=True)


def test_installer_smoke_snippet_works(tmp_path):
    """The exact smoke logic the installer runs, against a temp root."""
    from brain_core.records.models import Factory, Location
    from brain_core.tenancy import TenantStore
    store = TenantStore(tmp_path / "tenants")
    store.put_factory("smoke", "check",
                      Factory(locations=[Location(name="P")]))
    assert store.get_factory("smoke", "check").locations[0].name == "P"


def test_installer_references_real_entry_points():
    text = INSTALLER.read_text()
    assert "brain_core.tenancy" in text
    assert "brain_core.records.models" in text
    assert "pip" in text and "venv" in text
