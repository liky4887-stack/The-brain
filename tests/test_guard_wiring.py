import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_monolith_runner_calls_anomaly_guard():
    src = (ROOT / "benchmarks" / "monolith_scaling.py").read_text()
    assert "check_record" in src and "guard_findings" in src
