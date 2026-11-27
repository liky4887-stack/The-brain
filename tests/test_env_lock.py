"""The installed solver/numeric stack must equal config/ci-requirements.txt.

A silent version drift (for example pyvrp) changes solver behaviour, so
a mismatch fails here instead of showing up as an unexplained result."""
from importlib import metadata
from pathlib import Path

LOCK = Path(__file__).resolve().parent.parent / "config" / "ci-requirements.txt"


def _pins():
    out = {}
    for line in LOCK.read_text().splitlines():
        line = line.split("#")[0].strip()
        if "==" in line:
            name, ver = line.split("==", 1)
            out[name.strip()] = ver.strip()
    return out


def test_lock_file_has_the_expected_packages():
    assert {"numpy", "scipy", "pydantic", "ortools", "highspy",
            "pyvrp"} <= set(_pins())


def test_lock_pins_the_test_runner_too():
    """An unpinned runner is drift as well (pytest 9.2.0, xdist 3.8.0 and
    timeout 2.4.0 are the versions CI resolved when this was pinned)."""
    assert {"pytest", "pytest-xdist", "pytest-timeout"} <= set(_pins())


def test_installed_versions_equal_the_lock():
    bad = {}
    for name, want in _pins().items():
        try:
            have = metadata.version(name)
        except metadata.PackageNotFoundError:
            have = "NOT INSTALLED"
        if have != want:
            bad[name] = {"locked": want, "installed": have}
    assert not bad, bad
