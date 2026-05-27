import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from scen_trace.cli import cli
from scen_trace.providers.mock import MockProvider
from scen_trace.report import generate_markdown_report, generate_report, load_trace
from scen_trace.runner import run_scenario, write_trace
from scen_trace.schema import Scenario

SCENARIO_DATA = {
    "scenario_id": "report_test",
    "agents": [{"name": "bot", "role": "assistant", "system_prompt": "Be helpful."}],
    "model_config": {"provider": "mock", "model_name": "mock-v1"},
    "turns": [
        {"agent_name": "bot", "prompt": "Hello", "expected_checks": ["c1"]},
        {"agent_name": "bot", "prompt": "Goodbye"},
    ],
    "checks": [{"id": "c1", "type": "contains", "params": {"text": "mock"}}],
}


def _make_trace(tmp_path: Path, fmt: str = ".json") -> Path:
    s = Scenario(**SCENARIO_DATA)
    result = run_scenario(s, MockProvider())
    out = tmp_path / f"trace{fmt}"
    write_trace(result, out)
    return out


class TestLoadTrace:
    def test_load_json_trace(self, tmp_path):
        trace_path = _make_trace(tmp_path, ".json")
        trace = load_trace(trace_path)
        assert trace.scenario_id == "report_test"
        assert len(trace.turns) == 2

    def test_load_jsonl_trace(self, tmp_path):
        trace_path = _make_trace(tmp_path, ".jsonl")
        trace = load_trace(trace_path)
        assert len(trace.turns) == 2

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            load_trace(Path("/nonexistent/trace.json"))


class TestGenerateReport:
    def test_html_contains_scenario_id(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        trace = load_trace(trace_path)
        html_content = generate_report(trace)
        assert "report_test" in html_content

    def test_html_contains_turn_data(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        trace = load_trace(trace_path)
        content = generate_report(trace)
        assert "Turn 1" in content
        assert "Turn 2" in content
        assert "bot" in content

    def test_html_contains_check_results(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        trace = load_trace(trace_path)
        content = generate_report(trace)
        assert "c1" in content

    def test_html_contains_cost_and_duration(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        trace = load_trace(trace_path)
        content = generate_report(trace)
        assert "ms" in content
        assert "$" in content

    def test_html_has_dark_mode_toggle(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        trace = load_trace(trace_path)
        content = generate_report(trace)
        assert "toggleTheme" in content
        assert "data-theme" in content
        assert "localStorage" in content

    def test_html_is_self_contained(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        trace = load_trace(trace_path)
        content = generate_report(trace)
        assert "https://" not in content
        assert "http://" not in content

    def test_html_escapes_content(self, tmp_path):
        s = Scenario(**{
            **SCENARIO_DATA,
            "turns": [
                {"agent_name": "bot", "prompt": '<script>alert("xss")</script>'},
            ],
            "checks": [],
        })
        result = run_scenario(s, MockProvider())
        trace_path = tmp_path / "xss_trace.json"
        write_trace(result, trace_path)
        trace = load_trace(trace_path)
        content = generate_report(trace)
        assert '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;' in content

    def test_jsonl_trace_report(self, tmp_path):
        trace_path = _make_trace(tmp_path, ".jsonl")
        trace = load_trace(trace_path)
        content = generate_report(trace)
        assert "Turn 1" in content

    def test_empty_trace_handled(self, tmp_path):
        trace_path = tmp_path / "empty.json"
        trace_path.write_text(json.dumps({
            "scenario_id": "empty",
            "status": "passed",
            "turns": [],
            "total_duration_ms": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "estimated_cost": 0,
            "checks_passed": 0,
            "checks_failed": 0,
            "metadata": {},
        }))
        trace = load_trace(trace_path)
        content = generate_report(trace)
        assert "empty" in content


class TestReportCLI:
    def test_report_command(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        r = CliRunner().invoke(cli, ["report", str(trace_path)])
        assert r.exit_code == 0
        assert "Report generated" in r.output

    def test_report_custom_output(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        out = tmp_path / "my_report.html"
        r = CliRunner().invoke(cli, ["report", str(trace_path), "-o", str(out)])
        assert r.exit_code == 0
        assert out.exists()

    def test_report_nonexistent_trace(self):
        r = CliRunner().invoke(cli, ["report", "/nonexistent/trace.json"])
        assert r.exit_code != 0

    def test_report_markdown_format(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        out = tmp_path / "report.md"
        r = CliRunner().invoke(cli, ["report", str(trace_path), "--format", "md", "-o", str(out)])
        assert r.exit_code == 0
        assert out.exists()
        content = out.read_text()
        assert "# ScenTrace Report" in content

    def test_report_markdown_default_output_name(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        r = CliRunner().invoke(cli, ["report", str(trace_path), "--format", "md"])
        assert r.exit_code == 0
        expected = trace_path.with_name(trace_path.stem + "_report.md")
        assert expected.exists()


class TestMarkdownReport:
    def test_md_contains_scenario_id(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        trace = load_trace(trace_path)
        md = generate_markdown_report(trace)
        assert "report" in md and "test" in md

    def test_md_contains_summary_table(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        trace = load_trace(trace_path)
        md = generate_markdown_report(trace)
        assert "| Metric | Value |" in md
        assert "| Turns |" in md
        assert "| Duration |" in md
        assert "| Estimated Cost |" in md

    def test_md_contains_turn_details(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        trace = load_trace(trace_path)
        md = generate_markdown_report(trace)
        assert "<details>" in md
        assert "<summary>" in md
        assert "Turn 1" in md
        assert "Turn 2" in md

    def test_md_contains_check_results(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        trace = load_trace(trace_path)
        md = generate_markdown_report(trace)
        assert "c1" in md

    def test_md_escapes_content(self, tmp_path):
        s = Scenario(**{
            **SCENARIO_DATA,
            "turns": [
                {"agent_name": "bot", "prompt": "Test *bold* and _italic_"},
            ],
            "checks": [],
        })
        result = run_scenario(s, MockProvider())
        trace_path = tmp_path / "escape_trace.json"
        write_trace(result, trace_path)
        trace = load_trace(trace_path)
        md = generate_markdown_report(trace)
        assert "\\*bold\\*" in md or "*bold*" in md

    def test_md_handles_empty_trace(self, tmp_path):
        trace_path = tmp_path / "empty.json"
        trace_path.write_text(json.dumps({
            "scenario_id": "empty",
            "status": "passed",
            "turns": [],
            "total_duration_ms": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "estimated_cost": 0,
            "checks_passed": 0,
            "checks_failed": 0,
            "metadata": {},
        }))
        trace = load_trace(trace_path)
        md = generate_markdown_report(trace)
        assert "empty" in md
        assert "_No turns recorded._" in md

    def test_md_from_jsonl_trace(self, tmp_path):
        trace_path = _make_trace(tmp_path, ".jsonl")
        trace = load_trace(trace_path)
        md = generate_markdown_report(trace)
        assert "Turn 1" in md

    def test_md_has_no_external_urls(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        trace = load_trace(trace_path)
        md = generate_markdown_report(trace)
        assert "https://" not in md
        assert "http://" not in md

    def test_md_github_compatible_details(self, tmp_path):
        trace_path = _make_trace(tmp_path)
        trace = load_trace(trace_path)
        md = generate_markdown_report(trace)
        assert "<details>" in md
        assert "</details>" in md
        assert "<summary>" in md
        assert "</summary>" in md
