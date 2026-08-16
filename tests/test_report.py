import argparse
from pathlib import Path

from ceb.cli import run
from ceb.report import render_html

ROOT = Path(__file__).resolve().parents[1]


def _fake_report():
    return {
        "benchmark": "Conversation Execution Benchmark",
        "version": "0.8",
        "model": "mock-reference",
        "created_at": "2026-07-30T00:00:00+00:00",
        "summary": {
            "scenarios": 2,
            "runs": 4,
            "pass_at_1": 0.75,
            "pass_at_k": 1.0,
            "pass_pow_k": 0.5,
            "p0_failures": 1,
            "p0_failures_root_cause": 1,
            "wording_only_suspect_runs": 0,
            "axes": {"policy_safety": {"score": 100.0}, "business_outcome": {"score": 50.0}},
        },
        "gate": {"passed": False},
        "results": [
            {"scenario_id": "case_a", "passed": True, "wording_only_suspect": False, "checks": []},
            {"scenario_id": "case_a", "passed": True, "wording_only_suspect": False, "checks": []},
            {"scenario_id": "case_b", "passed": False, "wording_only_suspect": False,
             "checks": [{"name": "milestone:x", "passed": False, "detail": "x missing"}]},
            {"scenario_id": "case_b", "passed": True, "wording_only_suspect": False, "checks": []},
        ],
    }


def test_render_html_surfaces_summary_and_failing_scenario():
    page = render_html(_fake_report())
    assert "mock-reference" in page
    assert "75.00%" in page  # pass_at_1
    assert "FAIL" in page  # gate failed
    assert "case_b" in page and "milestone:x" in page
    assert page.strip().startswith("<!doctype html>")


def test_render_html_escapes_untrusted_text():
    report = _fake_report()
    report["results"][2]["checks"][0]["detail"] = "<script>alert(1)</script>"
    page = render_html(report)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_cli_run_with_out_writes_sibling_html_report(tmp_path):
    out_json = tmp_path / "reports" / "reference.json"
    args = argparse.Namespace(
        cases=str(ROOT / "cases"), manifest=str(ROOT / "benchmark.json"),
        mock=True, base_url=None, model="model-under-test", api_key="EMPTY",
        trials=None, seed=17, timeout=180, max_retries=3, concurrency=1,
        advisory_model_latency=False, out=str(out_json),
    )
    report = run(args)
    out_html = out_json.with_suffix(".html")
    assert out_json.exists()
    assert out_html.exists()
    page = out_html.read_text(encoding="utf-8")
    assert "mock-reference" in page
    assert f"{report['summary']['pass_at_1']:.2%}" in page


def _cli_args(**overrides):
    base = dict(
        cases=str(ROOT / "cases" / "behavior_gaps_v0_8.json"), manifest=str(ROOT / "benchmark.json"),
        mock=True, base_url=None, model="model-under-test", api_key="EMPTY",
        trials=1, seed=17, timeout=180, max_retries=3, concurrency=1,
        advisory_model_latency=False, out=None, no_report=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_every_run_writes_a_report_even_without_an_out_flag(tmp_path, monkeypatch):
    """A benchmark run that leaves no artefact behind is a run nobody can review later, so the
    report is written whether or not the operator remembered --out."""
    monkeypatch.chdir(tmp_path)
    report = run(_cli_args())
    # a mock sweep is labelled mock-reference in the report, and the filename follows the label
    written = sorted((tmp_path / "reports").glob("mock-reference-*.html"))
    assert len(written) == 1, written
    assert report["report_path"] == str(written[0].relative_to(tmp_path))
    assert written[0].with_suffix(".json").exists()


def test_no_report_flag_suppresses_the_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report = run(_cli_args(no_report=True))
    assert "report_path" not in report
    assert not (tmp_path / "reports").exists()


def test_report_carries_the_conversation_for_every_run(tmp_path, monkeypatch):
    """The transcript is what a reviewer reads to see what the model actually said; a report
    without it can only say a check failed, never why."""
    monkeypatch.chdir(tmp_path)
    report = run(_cli_args())
    assert all(item["transcript"] for item in report["results"])
    page = Path(report["report_path"]).read_text(encoding="utf-8")
    assert "Bu raporda transkript yok" not in page
    assert 'class="turn assistant"' in page
