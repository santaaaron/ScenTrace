from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CheckResult:
    check_id: str
    check_type: str
    passed: bool
    message: str


def _strip_markdown_code_blocks(text: str) -> str:
    pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _regex_with_timeout(pattern: str, text: str, timeout: int = 5) -> bool | None:
    def _do_match() -> bool:
        return bool(re.search(pattern, text))

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_do_match)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            return None
        except re.error:
            return None


def _run_python_check(
    script_path: str,
    response: str,
    context: dict,
    timeout: int = 5,
    scenario_dir: Path | None = None,
) -> CheckResult:
    resolved = Path(script_path)
    if not resolved.is_absolute() and scenario_dir:
        resolved = scenario_dir / script_path

    if not resolved.exists():
        return CheckResult("", "python", False, f"Script not found: {resolved}")

    wrapper = (
        "import sys, json, importlib.util\n"
        "spec = importlib.util.spec_from_file_location('check_mod', sys.argv[1])\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "result = mod.check(sys.argv[2], json.loads(sys.argv[3]))\n"
        "sys.exit(0 if result else 1)\n"
    )

    try:
        proc = subprocess.run(
            [sys.executable, "-c", wrapper, str(resolved), response, json.dumps(context)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if proc.returncode == 0:
            return CheckResult("", "python", True, "Python check passed")
        stderr = proc.stderr.strip()
        if stderr:
            last_line = stderr.strip().splitlines()[-1]
            return CheckResult("", "python", False, f"Python check failed: {last_line}")
        return CheckResult("", "python", False, "Python check returned non-zero exit code")
    except subprocess.TimeoutExpired:
        return CheckResult("", "python", False, f"Python check timed out after {timeout}s")
    except Exception as e:
        return CheckResult("", "python", False, f"Python check error: {e}")


def evaluate_check(
    check_id: str,
    check_type: str,
    params: dict,
    response: str,
    scenario_dir: Path | None = None,
) -> CheckResult:
    if check_type == "contains":
        target = params.get("text", "").strip().lower()
        passed = target in response.strip().lower()
        return CheckResult(check_id, check_type, passed, f"Contains '{params.get('text', '')}'" if passed else f"Missing '{params.get('text', '')}'")

    if check_type == "forbidden":
        target = params.get("text", "").strip().lower()
        found = target in response.strip().lower()
        return CheckResult(check_id, check_type, not found, "Forbidden text absent" if not found else f"Found forbidden text '{params.get('text', '')}'")

    if check_type == "regex":
        pattern = params.get("pattern", "")
        result = _regex_with_timeout(pattern, response)
        if result is None:
            return CheckResult(check_id, check_type, False, "Regex evaluation timed out or invalid pattern")
        return CheckResult(check_id, check_type, result, "Regex matched" if result else f"Regex did not match: {pattern}")

    if check_type == "json_valid":
        cleaned = _strip_markdown_code_blocks(response)
        try:
            json.loads(cleaned)
            return CheckResult(check_id, check_type, True, "Valid JSON")
        except (json.JSONDecodeError, ValueError) as e:
            return CheckResult(check_id, check_type, False, f"Invalid JSON: {e}")

    if check_type == "max_turns":
        return CheckResult(check_id, check_type, True, "max_turns evaluated at scenario level")

    if check_type == "semantic":
        return CheckResult(check_id, check_type, True, "Semantic check placeholder (V1 pass-through)")

    if check_type == "python":
        script_path = params.get("script_path", "")
        timeout = params.get("timeout", 5)
        result = _run_python_check(script_path, response, params.get("context", {}), timeout=timeout, scenario_dir=scenario_dir)
        result.check_id = check_id
        return result

    # Check for plugin-provided check types
    try:
        from scen_trace.plugins import discover_checks, load_plugin
        plugins = discover_checks()
        if check_type in plugins:
            plugin = load_plugin(plugins[check_type])
            if plugin.loaded and plugin.obj is not None:
                check_fn = plugin.obj
                passed = check_fn(response, params)
                return CheckResult(check_id, check_type, bool(passed), f"Plugin check '{check_type}' {'passed' if passed else 'failed'}")
            return CheckResult(check_id, check_type, False, f"Plugin check '{check_type}' failed to load: {plugin.error}")
    except ImportError:
        pass

    return CheckResult(check_id, check_type, False, f"Unknown check type: {check_type}")
