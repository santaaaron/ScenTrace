from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scen_trace.report import TraceData, load_trace

DEFAULT_BASELINES_DIR = Path(".scenetrace")
DB_NAME = "baselines.db"


@dataclass
class BaselineEntry:
    tag: str
    scenario_id: str
    trace_path: str
    timestamp: str
    status: str
    total_duration_ms: float
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost: float
    checks_passed: int
    checks_failed: int
    trace_hash: str


@dataclass
class DriftResult:
    field: str
    baseline_value: Any
    current_value: Any
    delta: Any
    severity: str  # "ok", "warning", "critical"
    message: str


@dataclass
class ComparisonResult:
    tag: str
    scenario_id: str
    drifts: list[DriftResult]
    check_flips: list[dict[str, Any]]
    overall: str  # "stable", "warning", "regression"


def _compute_trace_hash(trace_data: TraceData) -> str:
    content = json.dumps(
        {"turns": [{"prompt": t.get("prompt", ""), "response": t.get("response", "")} for t in trace_data.turns]},
        sort_keys=True,
    )
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class BaselineRegistry:
    def __init__(self, baselines_dir: Path | None = None) -> None:
        self.baselines_dir = baselines_dir or DEFAULT_BASELINES_DIR
        self.db_path = self.baselines_dir / DB_NAME
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def init(self) -> bool:
        self.baselines_dir.mkdir(parents=True, exist_ok=True)
        traces_dir = self.baselines_dir / "baselines"
        traces_dir.mkdir(exist_ok=True)

        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS baselines (
                tag TEXT PRIMARY KEY,
                scenario_id TEXT NOT NULL,
                trace_path TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                status TEXT NOT NULL,
                total_duration_ms REAL NOT NULL,
                total_input_tokens INTEGER NOT NULL,
                total_output_tokens INTEGER NOT NULL,
                estimated_cost REAL NOT NULL,
                checks_passed INTEGER NOT NULL,
                checks_failed INTEGER NOT NULL,
                trace_hash TEXT NOT NULL
            )
        """)
        conn.commit()
        return True

    def save(self, trace_path: Path, tag: str, force: bool = False) -> BaselineEntry:
        trace_data = load_trace(trace_path)
        trace_hash = _compute_trace_hash(trace_data)

        conn = self._get_conn()
        existing = conn.execute("SELECT tag FROM baselines WHERE tag = ?", (tag,)).fetchone()
        if existing and not force:
            raise ValueError(f"Baseline tag '{tag}' already exists. Use --force to overwrite.")

        dest_dir = self.baselines_dir / "baselines"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{tag}.json"

        raw = trace_path.read_text()
        dest.write_text(raw)

        entry = BaselineEntry(
            tag=tag,
            scenario_id=trace_data.scenario_id,
            trace_path=str(dest),
            timestamp=datetime.now(timezone.utc).isoformat(),
            status=trace_data.status,
            total_duration_ms=trace_data.total_duration_ms,
            total_input_tokens=trace_data.total_input_tokens,
            total_output_tokens=trace_data.total_output_tokens,
            estimated_cost=trace_data.estimated_cost,
            checks_passed=trace_data.checks_passed,
            checks_failed=trace_data.checks_failed,
            trace_hash=trace_hash,
        )

        if existing:
            conn.execute("DELETE FROM baselines WHERE tag = ?", (tag,))

        conn.execute(
            """INSERT INTO baselines (tag, scenario_id, trace_path, timestamp, status,
               total_duration_ms, total_input_tokens, total_output_tokens, estimated_cost,
               checks_passed, checks_failed, trace_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry.tag, entry.scenario_id, entry.trace_path, entry.timestamp,
             entry.status, entry.total_duration_ms, entry.total_input_tokens,
             entry.total_output_tokens, entry.estimated_cost, entry.checks_passed,
             entry.checks_failed, entry.trace_hash),
        )
        conn.commit()
        return entry

    def list_baselines(self) -> list[BaselineEntry]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM baselines ORDER BY timestamp DESC").fetchall()
        return [
            BaselineEntry(
                tag=r["tag"],
                scenario_id=r["scenario_id"],
                trace_path=r["trace_path"],
                timestamp=r["timestamp"],
                status=r["status"],
                total_duration_ms=r["total_duration_ms"],
                total_input_tokens=r["total_input_tokens"],
                total_output_tokens=r["total_output_tokens"],
                estimated_cost=r["estimated_cost"],
                checks_passed=r["checks_passed"],
                checks_failed=r["checks_failed"],
                trace_hash=r["trace_hash"],
            )
            for r in rows
        ]

    def get_baseline(self, tag: str) -> BaselineEntry | None:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM baselines WHERE tag = ?", (tag,)).fetchone()
        if row is None:
            return None
        return BaselineEntry(
            tag=row["tag"],
            scenario_id=row["scenario_id"],
            trace_path=row["trace_path"],
            timestamp=row["timestamp"],
            status=row["status"],
            total_duration_ms=row["total_duration_ms"],
            total_input_tokens=row["total_input_tokens"],
            total_output_tokens=row["total_output_tokens"],
            estimated_cost=row["estimated_cost"],
            checks_passed=row["checks_passed"],
            checks_failed=row["checks_failed"],
            trace_hash=row["trace_hash"],
        )

    def remove(self, tag: str) -> bool:
        entry = self.get_baseline(tag)
        if entry is None:
            return False

        trace_file = Path(entry.trace_path)
        if trace_file.exists():
            trace_file.unlink()

        conn = self._get_conn()
        conn.execute("DELETE FROM baselines WHERE tag = ?", (tag,))
        conn.commit()
        return True

    def compare(
        self,
        trace_path: Path,
        tag: str,
        cost_threshold_pct: float = 15.0,
        latency_threshold_ms: float = 200.0,
    ) -> ComparisonResult:
        entry = self.get_baseline(tag)
        if entry is None:
            raise ValueError(f"No baseline found with tag '{tag}'.")

        current = load_trace(trace_path)
        baseline_trace = load_trace(Path(entry.trace_path))

        drifts: list[DriftResult] = []

        # Cost drift
        if entry.estimated_cost > 0:
            cost_pct = ((current.estimated_cost - entry.estimated_cost) / entry.estimated_cost) * 100
        else:
            cost_pct = 0.0 if current.estimated_cost == 0 else 100.0

        cost_severity = "critical" if abs(cost_pct) > cost_threshold_pct else "ok"
        drifts.append(DriftResult(
            field="estimated_cost",
            baseline_value=entry.estimated_cost,
            current_value=current.estimated_cost,
            delta=round(cost_pct, 1),
            severity=cost_severity,
            message=f"Cost {'increased' if cost_pct > 0 else 'decreased'} by {abs(cost_pct):.1f}%" if cost_pct != 0 else "Cost stable",
        ))

        # Latency drift
        latency_delta = current.total_duration_ms - entry.total_duration_ms
        latency_severity = "warning" if abs(latency_delta) > latency_threshold_ms else "ok"
        drifts.append(DriftResult(
            field="total_duration_ms",
            baseline_value=entry.total_duration_ms,
            current_value=current.total_duration_ms,
            delta=round(latency_delta, 1),
            severity=latency_severity,
            message=f"Latency {'increased' if latency_delta > 0 else 'decreased'} by {abs(latency_delta):.0f}ms" if latency_delta != 0 else "Latency stable",
        ))

        # Token drift
        token_delta_in = current.total_input_tokens - entry.total_input_tokens
        token_delta_out = current.total_output_tokens - entry.total_output_tokens
        token_severity = "ok"
        if abs(token_delta_in) > 100 or abs(token_delta_out) > 100:
            token_severity = "warning"
        drifts.append(DriftResult(
            field="tokens",
            baseline_value=f"{entry.total_input_tokens}in/{entry.total_output_tokens}out",
            current_value=f"{current.total_input_tokens}in/{current.total_output_tokens}out",
            delta=f"{token_delta_in:+d}in/{token_delta_out:+d}out",
            severity=token_severity,
            message=f"Token delta: {token_delta_in:+d} in, {token_delta_out:+d} out" if (token_delta_in or token_delta_out) else "Tokens stable",
        ))

        # Status drift
        if current.status != entry.status:
            drifts.append(DriftResult(
                field="status",
                baseline_value=entry.status,
                current_value=current.status,
                delta="changed",
                severity="critical",
                message=f"Status changed: {entry.status} -> {current.status}",
            ))

        # Check flips
        check_flips: list[dict[str, Any]] = []
        baseline_checks: dict[str, bool] = {}
        for turn in baseline_trace.turns:
            for cr in turn.get("check_results", []):
                baseline_checks[cr.get("check_id", "")] = cr.get("passed", False)

        for turn in current.turns:
            for cr in turn.get("check_results", []):
                check_id = cr.get("check_id", "")
                current_passed = cr.get("passed", False)
                if check_id in baseline_checks:
                    baseline_passed = baseline_checks[check_id]
                    if baseline_passed != current_passed:
                        check_flips.append({
                            "check_id": check_id,
                            "baseline": "PASS" if baseline_passed else "FAIL",
                            "current": "PASS" if current_passed else "FAIL",
                            "direction": "regression" if baseline_passed and not current_passed else "improvement",
                        })

        # Overall assessment
        has_critical = any(d.severity == "critical" for d in drifts)
        has_regression_flip = any(f["direction"] == "regression" for f in check_flips)
        has_warning = any(d.severity == "warning" for d in drifts)

        if has_critical or has_regression_flip:
            overall = "regression"
        elif has_warning:
            overall = "warning"
        else:
            overall = "stable"

        return ComparisonResult(
            tag=tag,
            scenario_id=current.scenario_id,
            drifts=drifts,
            check_flips=check_flips,
            overall=overall,
        )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
