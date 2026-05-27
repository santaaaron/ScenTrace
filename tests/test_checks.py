from pathlib import Path

from scen_trace.checks import evaluate_check


class TestContainsCheck:
    def test_match(self):
        r = evaluate_check("c1", "contains", {"text": "hello"}, "Say hello world")
        assert r.passed

    def test_case_insensitive(self):
        r = evaluate_check("c1", "contains", {"text": "HELLO"}, "say hello world")
        assert r.passed

    def test_no_match(self):
        r = evaluate_check("c1", "contains", {"text": "goodbye"}, "hello world")
        assert not r.passed

    def test_whitespace_trimmed(self):
        r = evaluate_check("c1", "contains", {"text": " hello "}, "  hello  world")
        assert r.passed


class TestForbiddenCheck:
    def test_absent(self):
        r = evaluate_check("c1", "forbidden", {"text": "error"}, "all good")
        assert r.passed

    def test_present(self):
        r = evaluate_check("c1", "forbidden", {"text": "error"}, "got an error")
        assert not r.passed

    def test_case_insensitive(self):
        r = evaluate_check("c1", "forbidden", {"text": "ERROR"}, "got an error")
        assert not r.passed


class TestRegexCheck:
    def test_match(self):
        r = evaluate_check("c1", "regex", {"pattern": r"\d{3}"}, "code 123")
        assert r.passed

    def test_no_match(self):
        r = evaluate_check("c1", "regex", {"pattern": r"\d{3}"}, "no numbers")
        assert not r.passed

    def test_invalid_pattern(self):
        r = evaluate_check("c1", "regex", {"pattern": "["}, "text")
        assert not r.passed


class TestJsonValidCheck:
    def test_valid_json(self):
        r = evaluate_check("c1", "json_valid", {}, '{"key": "value"}')
        assert r.passed

    def test_invalid_json(self):
        r = evaluate_check("c1", "json_valid", {}, "not json at all")
        assert not r.passed

    def test_markdown_code_block(self):
        r = evaluate_check("c1", "json_valid", {}, '```json\n{"key": "val"}\n```')
        assert r.passed

    def test_plain_code_block(self):
        r = evaluate_check("c1", "json_valid", {}, '```\n{"a": 1}\n```')
        assert r.passed

    def test_json_array(self):
        r = evaluate_check("c1", "json_valid", {}, "[1, 2, 3]")
        assert r.passed


class TestPythonCheck:
    def test_passing_script(self, tmp_path):
        script = tmp_path / "pass_check.py"
        script.write_text("def check(response, context):\n    return 'hello' in response.lower()\n")
        r = evaluate_check("c1", "python", {"script_path": str(script)}, "Hello World")
        assert r.passed
        assert "passed" in r.message

    def test_failing_script(self, tmp_path):
        script = tmp_path / "fail_check.py"
        script.write_text("def check(response, context):\n    return False\n")
        r = evaluate_check("c1", "python", {"script_path": str(script)}, "anything")
        assert not r.passed

    def test_missing_script(self):
        r = evaluate_check("c1", "python", {"script_path": "/nonexistent/check.py"}, "text")
        assert not r.passed
        assert "not found" in r.message.lower()

    def test_script_timeout(self, tmp_path):
        script = tmp_path / "slow_check.py"
        script.write_text("import time\ndef check(response, context):\n    time.sleep(30)\n    return True\n")
        r = evaluate_check("c1", "python", {"script_path": str(script), "timeout": 1}, "text")
        assert not r.passed
        assert "timed out" in r.message.lower()

    def test_script_with_error(self, tmp_path):
        script = tmp_path / "error_check.py"
        script.write_text("def check(response, context):\n    raise ValueError('bad input')\n")
        r = evaluate_check("c1", "python", {"script_path": str(script)}, "text")
        assert not r.passed
        assert "ValueError" in r.message or "bad input" in r.message

    def test_relative_script_path(self, tmp_path):
        script = tmp_path / "rel_check.py"
        script.write_text("def check(response, context):\n    return True\n")
        r = evaluate_check("c1", "python", {"script_path": "rel_check.py"}, "text", scenario_dir=tmp_path)
        assert r.passed

    def test_context_passed_to_script(self, tmp_path):
        script = tmp_path / "ctx_check.py"
        script.write_text(
            "import json, sys\n"
            "def check(response, context):\n"
            "    return context.get('expected') == 'value'\n"
        )
        r = evaluate_check("c1", "python", {"script_path": str(script), "context": {"expected": "value"}}, "text")
        assert r.passed


class TestUnknownCheckType:
    def test_unknown_type_fails(self):
        r = evaluate_check("c1", "unknown", {}, "text")
        assert not r.passed
