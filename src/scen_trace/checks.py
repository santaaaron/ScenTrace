from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import regex as regex_lib


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
    try:
        return bool(regex_lib.search(pattern, text, timeout=timeout))
    except regex_lib.error:
        return None
    except TimeoutError:
        return None


_SEMANTIC_MODEL = None


def _get_semantic_model():
    global _SEMANTIC_MODEL
    if _SEMANTIC_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "Semantic checks require extra dependencies.\n"
                "Install with: pip install \"scen-trace[semantic]\""
            )
        _SEMANTIC_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _SEMANTIC_MODEL


def _evaluate_semantic(response: str, params: dict) -> CheckResult:
    reference = params.get("reference_answer", "")
    threshold = params.get("threshold", 0.75)

    if not reference:
        return CheckResult("", "semantic", False, "Missing 'reference_answer' in params")

    try:
        model = _get_semantic_model()
    except ImportError as e:
        return CheckResult("", "semantic", False, str(e))

    embeddings = model.encode([response, reference])
    from numpy import dot
    from numpy.linalg import norm
    similarity = float(dot(embeddings[0], embeddings[1]) / (norm(embeddings[0]) * norm(embeddings[1])))

    passed = similarity >= threshold
    return CheckResult(
        "", "semantic", passed,
        f"Similarity {similarity:.3f} {'≥' if passed else '<'} threshold {threshold}"
    )


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

    safe_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    if "VIRTUAL_ENV" in os.environ:
        safe_env["VIRTUAL_ENV"] = os.environ["VIRTUAL_ENV"]

    try:
        proc = subprocess.run(
            [sys.executable, "-c", wrapper, str(resolved), response, json.dumps(context)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=safe_env,
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
        result = _evaluate_semantic(response, params)
        result.check_id = check_id
        return result

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
