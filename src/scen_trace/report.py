from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TraceData:
    scenario_id: str
    status: str
    started_at: str
    finished_at: str
    total_duration_ms: float
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost: float
    checks_passed: int
    checks_failed: int
    metadata: dict[str, Any]
    turns: list[dict[str, Any]]


def load_trace(path: Path) -> TraceData:
    if not path.exists():
        raise FileNotFoundError(f"Trace file not found: {path}")

    text = path.read_text().strip()
    if not text:
        raise ValueError(f"Trace file is empty: {path}")

    if path.suffix == ".jsonl":
        turns = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                turns.append(json.loads(line))
        checks_passed = 0
        checks_failed = 0
        for t in turns:
            for cr in t.get("check_results", []):
                if cr.get("passed"):
                    checks_passed += 1
                else:
                    checks_failed += 1
        total_in = sum(t.get("input_tokens", 0) for t in turns)
        total_out = sum(t.get("output_tokens", 0) for t in turns)
        status = "failed" if checks_failed > 0 else "passed"
        return TraceData(
            scenario_id=turns[0].get("agent_name", "unknown") if turns else "unknown",
            status=status,
            started_at=turns[0].get("timestamp", "") if turns else "",
            finished_at=turns[-1].get("timestamp", "") if turns else "",
            total_duration_ms=sum(t.get("duration_ms", 0) for t in turns),
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            estimated_cost=round((total_in + total_out) * 0.000001, 6),
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            metadata={"provider": turns[0].get("provider", "") if turns else ""},
            turns=turns,
        )

    data = json.loads(text)
    if isinstance(data, list):
        return TraceData(
            scenario_id="unknown",
            status="passed",
            started_at="",
            finished_at="",
            total_duration_ms=sum(t.get("duration_ms", 0) for t in data),
            total_input_tokens=sum(t.get("input_tokens", 0) for t in data),
            total_output_tokens=sum(t.get("output_tokens", 0) for t in data),
            estimated_cost=0.0,
            checks_passed=0,
            checks_failed=0,
            metadata={},
            turns=data,
        )

    return TraceData(
        scenario_id=data.get("scenario_id", "unknown"),
        status=data.get("status", "unknown"),
        started_at=data.get("started_at", ""),
        finished_at=data.get("finished_at", ""),
        total_duration_ms=data.get("total_duration_ms", 0),
        total_input_tokens=data.get("total_input_tokens", 0),
        total_output_tokens=data.get("total_output_tokens", 0),
        estimated_cost=data.get("estimated_cost", 0),
        checks_passed=data.get("checks_passed", 0),
        checks_failed=data.get("checks_failed", 0),
        metadata=data.get("metadata", {}),
        turns=data.get("turns", []),
    )


def _escape(text: str) -> str:
    return html.escape(str(text))


def _status_badge(status: str) -> str:
    color_map = {
        "passed": "#22c55e",
        "failed": "#ef4444",
        "error": "#ef4444",
        "max_turns_exceeded": "#f59e0b",
    }
    color = color_map.get(status, "#6b7280")
    return f'<span class="badge" style="background:{color}">{_escape(status.upper())}</span>'


def _check_icon(passed: bool) -> str:
    if passed:
        return '<span class="check-pass">&#10003;</span>'
    return '<span class="check-fail">&#10007;</span>'


def _render_turns(turns: list[dict]) -> str:
    if not turns:
        return '<p class="empty">No turns recorded.</p>'

    parts = []
    for turn in turns:
        idx = turn.get("turn_index", 0)
        agent = _escape(turn.get("agent_name", "unknown"))
        prompt = _escape(turn.get("prompt", ""))
        response = _escape(turn.get("response", ""))
        duration = turn.get("duration_ms", 0)
        in_tok = turn.get("input_tokens", 0)
        out_tok = turn.get("output_tokens", 0)
        status = turn.get("status", "success")
        error = turn.get("error")

        status_class = "turn-success" if status == "success" else "turn-error"

        checks_html = ""
        check_results = turn.get("check_results", [])
        if check_results:
            checks_items = []
            for cr in check_results:
                icon = _check_icon(cr.get("passed", False))
                checks_items.append(
                    f'<div class="check-item">{icon} '
                    f'<strong>{_escape(cr.get("check_id", ""))}</strong> '
                    f'[{_escape(cr.get("check_type", ""))}]: '
                    f'<span class="check-msg">{_escape(cr.get("message", ""))}</span></div>'
                )
            checks_html = f'<div class="checks-section"><h4>Checks</h4>{"".join(checks_items)}</div>'

        error_html = ""
        if error:
            error_html = f'<div class="error-block"><strong>Error:</strong> {_escape(error)}</div>'

        parts.append(f'''
        <details class="turn {status_class}">
            <summary>
                <span class="turn-num">Turn {idx + 1}</span>
                <span class="turn-agent">{agent}</span>
                <span class="turn-meta">{duration:.0f}ms | {in_tok}+{out_tok} tokens</span>
            </summary>
            <div class="turn-body">
                <div class="message prompt-msg">
                    <div class="msg-label">Prompt</div>
                    <pre>{prompt}</pre>
                </div>
                <div class="message response-msg">
                    <div class="msg-label">Response</div>
                    <pre>{response}</pre>
                </div>
                {error_html}
                {checks_html}
            </div>
        </details>''')

    return "\n".join(parts)


def generate_report(trace: TraceData) -> str:
    scenario_id = _escape(trace.scenario_id)
    status = trace.status
    started = _escape(trace.started_at)
    duration = trace.total_duration_ms
    in_tokens = trace.total_input_tokens
    out_tokens = trace.total_output_tokens
    cost = trace.estimated_cost
    checks_passed = trace.checks_passed
    checks_failed = trace.checks_failed
    metadata = trace.metadata
    turns = trace.turns

    provider = _escape(metadata.get("provider", "unknown"))
    model = _escape(metadata.get("model", "unknown"))

    turns_html = _render_turns(turns)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ScenTrace Report — {scenario_id}</title>
<style>
:root {{
    --bg: #ffffff;
    --bg-secondary: #f9fafb;
    --bg-card: #ffffff;
    --text: #111827;
    --text-secondary: #6b7280;
    --border: #e5e7eb;
    --accent: #3b82f6;
    --success: #22c55e;
    --error: #ef4444;
    --warning: #f59e0b;
    --shadow: 0 1px 3px rgba(0,0,0,0.1);
}}
[data-theme="dark"] {{
    --bg: #0f172a;
    --bg-secondary: #1e293b;
    --bg-card: #1e293b;
    --text: #f1f5f9;
    --text-secondary: #94a3b8;
    --border: #334155;
    --shadow: 0 1px 3px rgba(0,0,0,0.3);
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
    max-width: 960px;
    margin: 0 auto;
}}
.header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2rem;
    padding-bottom: 1rem;
    border-bottom: 2px solid var(--border);
}}
.header h1 {{ font-size: 1.5rem; font-weight: 700; }}
.header .subtitle {{ color: var(--text-secondary); font-size: 0.875rem; }}
.theme-toggle {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 0.5rem 1rem;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.875rem;
}}
.badge {{
    display: inline-block;
    padding: 0.25rem 0.75rem;
    border-radius: 9999px;
    color: white;
    font-weight: 600;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}}
.summary {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
}}
.stat-card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem;
    box-shadow: var(--shadow);
}}
.stat-card .label {{ font-size: 0.75rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em; }}
.stat-card .value {{ font-size: 1.25rem; font-weight: 600; margin-top: 0.25rem; }}
.turns-section {{ margin-bottom: 2rem; }}
.turns-section h2 {{ font-size: 1.25rem; margin-bottom: 1rem; }}
.turn {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 0.75rem;
    box-shadow: var(--shadow);
    overflow: hidden;
}}
.turn summary {{
    padding: 0.75rem 1rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    font-size: 0.875rem;
    user-select: none;
    list-style: none;
}}
.turn summary::-webkit-details-marker {{ display: none; }}
.turn summary::before {{
    content: "\\25B6";
    font-size: 0.625rem;
    transition: transform 0.2s;
    color: var(--text-secondary);
}}
.turn[open] summary::before {{ transform: rotate(90deg); }}
.turn-num {{ font-weight: 700; color: var(--accent); }}
.turn-agent {{ font-weight: 500; }}
.turn-meta {{ margin-left: auto; color: var(--text-secondary); font-size: 0.75rem; font-family: "SF Mono", Menlo, monospace; }}
.turn-body {{ padding: 0 1rem 1rem; }}
.turn-success {{ border-left: 3px solid var(--success); }}
.turn-error {{ border-left: 3px solid var(--error); }}
.message {{ margin-bottom: 0.75rem; }}
.msg-label {{
    font-size: 0.6875rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text-secondary);
    margin-bottom: 0.25rem;
    font-weight: 600;
}}
.message pre {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.75rem;
    font-size: 0.8125rem;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: "SF Mono", "Fira Code", Menlo, Consolas, monospace;
}}
.prompt-msg pre {{ border-left: 3px solid var(--accent); }}
.response-msg pre {{ border-left: 3px solid var(--success); }}
.error-block {{
    background: rgba(239,68,68,0.1);
    border: 1px solid var(--error);
    border-radius: 6px;
    padding: 0.75rem;
    font-size: 0.8125rem;
    margin-bottom: 0.75rem;
    color: var(--error);
}}
[data-theme="dark"] .error-block {{ background: rgba(239,68,68,0.15); }}
.checks-section h4 {{
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text-secondary);
    margin-bottom: 0.5rem;
}}
.check-item {{
    font-size: 0.8125rem;
    padding: 0.25rem 0;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}}
.check-pass {{ color: var(--success); font-weight: 700; }}
.check-fail {{ color: var(--error); font-weight: 700; }}
.check-msg {{ color: var(--text-secondary); }}
.footer {{
    text-align: center;
    padding-top: 2rem;
    border-top: 1px solid var(--border);
    color: var(--text-secondary);
    font-size: 0.75rem;
}}
.empty {{ color: var(--text-secondary); font-style: italic; }}
</style>
</head>
<body>
<div class="header">
    <div>
        <h1>ScenTrace Report</h1>
        <div class="subtitle">{scenario_id} &middot; {started}</div>
    </div>
    <button class="theme-toggle" onclick="toggleTheme()">Toggle Theme</button>
</div>

<div class="summary">
    <div class="stat-card">
        <div class="label">Status</div>
        <div class="value">{_status_badge(status)}</div>
    </div>
    <div class="stat-card">
        <div class="label">Provider / Model</div>
        <div class="value">{provider}<br><span style="font-size:0.75rem;color:var(--text-secondary)">{model}</span></div>
    </div>
    <div class="stat-card">
        <div class="label">Turns</div>
        <div class="value">{len(turns)}</div>
    </div>
    <div class="stat-card">
        <div class="label">Duration</div>
        <div class="value">{duration:.0f}ms</div>
    </div>
    <div class="stat-card">
        <div class="label">Tokens</div>
        <div class="value">{in_tokens} / {out_tokens}</div>
    </div>
    <div class="stat-card">
        <div class="label">Est. Cost</div>
        <div class="value">${cost:.6f}</div>
    </div>
    <div class="stat-card">
        <div class="label">Checks</div>
        <div class="value"><span class="check-pass">{checks_passed} passed</span> / <span class="check-fail">{checks_failed} failed</span></div>
    </div>
</div>

<div class="turns-section">
    <h2>Execution Trace</h2>
    {turns_html}
</div>

<div class="footer">
    Generated by ScenTrace &middot; Scenario-based regression testing for multi-agent AI workflows
</div>

<script>
function toggleTheme() {{
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("scenetrace-theme", next);
}}
(function() {{
    const saved = localStorage.getItem("scenetrace-theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    else if (window.matchMedia("(prefers-color-scheme: dark)").matches)
        document.documentElement.setAttribute("data-theme", "dark");
}})();
</script>
</body>
</html>'''


def _md_escape(text: str) -> str:
    for ch in ("\\", "`", "*", "_", "{", "}", "[", "]", "(", ")", "#", "+", "-", ".", "!", "|"):
        text = text.replace(ch, f"\\{ch}")
    return text


def _md_status_badge(status: str) -> str:
    icons = {"passed": "PASSED", "failed": "FAILED", "error": "ERROR", "max_turns_exceeded": "LIMIT REACHED"}
    return f"**{icons.get(status, status.upper())}**"


def _md_check_icon(passed: bool) -> str:
    return "✅" if passed else "❌"


def generate_markdown_report(trace: TraceData) -> str:
    scenario_id = _md_escape(trace.scenario_id)
    status = trace.status
    started = trace.started_at
    duration = trace.total_duration_ms
    in_tokens = trace.total_input_tokens
    out_tokens = trace.total_output_tokens
    cost = trace.estimated_cost
    checks_passed = trace.checks_passed
    checks_failed = trace.checks_failed
    metadata = trace.metadata
    turns = trace.turns

    provider = _md_escape(metadata.get("provider", "unknown"))
    model = _md_escape(metadata.get("model", "unknown"))

    lines = [
        f"# ScenTrace Report — {scenario_id}",
        "",
        f"**Status:** {_md_status_badge(status)} | **Provider:** {provider} | **Model:** {model}",
        f"**Started:** {started}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Turns | {len(turns)} |",
        f"| Duration | {duration:.0f}ms |",
        f"| Input Tokens | {in_tokens} |",
        f"| Output Tokens | {out_tokens} |",
        f"| Estimated Cost | ${cost:.6f} |",
        f"| Checks Passed | {checks_passed} |",
        f"| Checks Failed | {checks_failed} |",
        "",
        "## Execution Trace",
        "",
    ]

    if not turns:
        lines.append("_No turns recorded._")
    else:
        for turn in turns:
            idx = turn.get("turn_index", 0)
            agent = _md_escape(turn.get("agent_name", "unknown"))
            prompt = turn.get("prompt", "")
            response = turn.get("response", "")
            dur = turn.get("duration_ms", 0)
            in_tok = turn.get("input_tokens", 0)
            out_tok = turn.get("output_tokens", 0)
            t_status = turn.get("status", "success")
            error = turn.get("error")

            status_icon = "✅" if t_status == "success" else "❌"
            lines.append(f"<details>")
            lines.append(f"<summary>{status_icon} <strong>Turn {idx + 1}</strong> — {agent} ({dur:.0f}ms | {in_tok}+{out_tok} tokens)</summary>")
            lines.append("")
            lines.append("**Prompt:**")
            lines.append(f"```\n{prompt}\n```")
            lines.append("")
            lines.append("**Response:**")
            lines.append(f"```\n{response}\n```")

            if error:
                lines.append("")
                lines.append(f"> **Error:** {_md_escape(error)}")

            check_results = turn.get("check_results", [])
            if check_results:
                lines.append("")
                lines.append("**Checks:**")
                for cr in check_results:
                    icon = _md_check_icon(cr.get("passed", False))
                    cid = _md_escape(cr.get("check_id", ""))
                    ctype = _md_escape(cr.get("check_type", ""))
                    msg = _md_escape(cr.get("message", ""))
                    lines.append(f"- {icon} **{cid}** [{ctype}]: {msg}")

            lines.append("")
            lines.append("</details>")
            lines.append("")

    lines.extend([
        "---",
        "",
        "_Generated by ScenTrace — Scenario-based regression testing for multi-agent AI workflows_",
    ])

    return "\n".join(lines)


def generate_report_file(trace_path: Path, output_path: Path | None = None, fmt: str = "html") -> Path:
    trace = load_trace(trace_path)

    if fmt == "md":
        content = generate_markdown_report(trace)
        ext = ".md"
    else:
        content = generate_report(trace)
        ext = ".html"

    if output_path is None:
        output_path = trace_path.with_name(trace_path.stem + f"_report{ext}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)
    return output_path
