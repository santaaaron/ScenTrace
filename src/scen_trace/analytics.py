from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scen_trace.report import TraceData, load_trace

DEFAULT_ANALYTICS_DIR = Path(".scenetrace")
ANALYTICS_DB_NAME = "analytics.db"


@dataclass
class RunRecord:
    id: int
    scenario_id: str
    timestamp: str
    provider: str
    model: str
    total_cost: float
    total_tokens: int
    total_latency_ms: float
    status: str
    trace_path: str
    checks_passed: int
    checks_failed: int


@dataclass
class AgentMetric:
    run_id: int
    agent_name: str
    turn_count: int
    total_tokens: int
    avg_latency_ms: float
    cost_share_pct: float


@dataclass
class TrendData:
    scenario_id: str
    total_runs: int
    avg_cost: float
    avg_latency_ms: float
    avg_tokens: int
    pass_rate_pct: float
    recent_runs: list[RunRecord]
    agent_breakdown: list[AgentMetric]


@dataclass
class EfficiencyScore:
    total: int
    check_score: int
    cost_score: int
    latency_score: int
    token_score: int
    details: dict[str, str]


class AnalyticsDB:
    def __init__(self, analytics_dir: Path | None = None) -> None:
        self.analytics_dir = analytics_dir or DEFAULT_ANALYTICS_DIR
        self.db_path = self.analytics_dir / ANALYTICS_DB_NAME
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def init(self) -> bool:
        self.analytics_dir.mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scenario_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                total_cost REAL NOT NULL,
                total_tokens INTEGER NOT NULL,
                total_latency_ms REAL NOT NULL,
                status TEXT NOT NULL,
                trace_path TEXT NOT NULL,
                checks_passed INTEGER NOT NULL DEFAULT 0,
                checks_failed INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                agent_name TEXT NOT NULL,
                turn_count INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                avg_latency_ms REAL NOT NULL,
                cost_share_pct REAL NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_scenario ON runs(scenario_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON runs(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_run ON agent_metrics(run_id)")
        conn.commit()
        return True

    def ingest_run(self, trace_path: Path, trace_data: TraceData | None = None) -> int:
        if trace_data is None:
            trace_data = load_trace(trace_path)

        conn = self._get_conn()
        provider = ""
        model = ""
        if trace_data.turns:
            first = trace_data.turns[0]
            provider = first.get("provider", "")
            model = first.get("model", "")

        total_tokens = trace_data.total_input_tokens + trace_data.total_output_tokens

        cursor = conn.execute(
            """INSERT INTO runs (scenario_id, timestamp, provider, model, total_cost,
               total_tokens, total_latency_ms, status, trace_path, checks_passed, checks_failed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trace_data.scenario_id,
                datetime.now(timezone.utc).isoformat(),
                provider,
                model,
                trace_data.estimated_cost,
                total_tokens,
                trace_data.total_duration_ms,
                trace_data.status,
                str(trace_path),
                trace_data.checks_passed,
                trace_data.checks_failed,
            ),
        )
        run_id = cursor.lastrowid

        agent_stats: dict[str, dict[str, Any]] = {}
        for turn in trace_data.turns:
            name = turn.get("agent_name", "unknown")
            if name not in agent_stats:
                agent_stats[name] = {"turns": 0, "tokens": 0, "latencies": []}
            agent_stats[name]["turns"] += 1
            agent_stats[name]["tokens"] += turn.get("input_tokens", 0) + turn.get("output_tokens", 0)
            agent_stats[name]["latencies"].append(turn.get("duration_ms", 0))

        for agent_name, stats in agent_stats.items():
            avg_lat = sum(stats["latencies"]) / len(stats["latencies"]) if stats["latencies"] else 0
            cost_share = (stats["tokens"] / total_tokens * 100) if total_tokens > 0 else 0
            conn.execute(
                """INSERT INTO agent_metrics (run_id, agent_name, turn_count, total_tokens, avg_latency_ms, cost_share_pct)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, agent_name, stats["turns"], stats["tokens"], round(avg_lat, 2), round(cost_share, 2)),
            )

        conn.commit()
        return run_id

    def get_runs(self, scenario_id: str | None = None, limit: int = 50) -> list[RunRecord]:
        conn = self._get_conn()
        if scenario_id:
            rows = conn.execute(
                "SELECT * FROM runs WHERE scenario_id = ? ORDER BY timestamp DESC LIMIT ?",
                (scenario_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_run(r) for r in rows]

    def get_agent_metrics(self, run_id: int) -> list[AgentMetric]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM agent_metrics WHERE run_id = ? ORDER BY cost_share_pct DESC",
            (run_id,),
        ).fetchall()
        return [
            AgentMetric(
                run_id=r["run_id"],
                agent_name=r["agent_name"],
                turn_count=r["turn_count"],
                total_tokens=r["total_tokens"],
                avg_latency_ms=r["avg_latency_ms"],
                cost_share_pct=r["cost_share_pct"],
            )
            for r in rows
        ]

    def get_trends(self, scenario_id: str, limit: int = 30) -> TrendData:
        runs = self.get_runs(scenario_id, limit=limit)
        if not runs:
            return TrendData(
                scenario_id=scenario_id,
                total_runs=0,
                avg_cost=0.0,
                avg_latency_ms=0.0,
                avg_tokens=0,
                pass_rate_pct=0.0,
                recent_runs=[],
                agent_breakdown=[],
            )

        total_cost = sum(r.total_cost for r in runs)
        total_latency = sum(r.total_latency_ms for r in runs)
        total_tokens = sum(r.total_tokens for r in runs)
        passed = sum(1 for r in runs if r.status == "passed")

        agent_breakdown = self.get_agent_metrics(runs[0].id) if runs else []

        return TrendData(
            scenario_id=scenario_id,
            total_runs=len(runs),
            avg_cost=round(total_cost / len(runs), 6),
            avg_latency_ms=round(total_latency / len(runs), 2),
            avg_tokens=total_tokens // len(runs),
            pass_rate_pct=round(passed / len(runs) * 100, 1),
            recent_runs=runs,
            agent_breakdown=agent_breakdown,
        )

    def compute_efficiency(self, scenario_id: str) -> EfficiencyScore:
        trends = self.get_trends(scenario_id)
        if trends.total_runs == 0:
            return EfficiencyScore(
                total=0, check_score=0, cost_score=0,
                latency_score=0, token_score=0,
                details={"note": "No runs recorded"},
            )

        # Check pass rate (40%)
        check_score = min(int(trends.pass_rate_pct), 100)

        # Cost stability (30%) — lower variance = higher score
        costs = [r.total_cost for r in trends.recent_runs]
        if len(costs) > 1 and trends.avg_cost > 0:
            variance = sum((c - trends.avg_cost) ** 2 for c in costs) / len(costs)
            cv = (variance ** 0.5) / trends.avg_cost if trends.avg_cost > 0 else 0
            cost_score = max(0, min(100, int(100 - cv * 200)))
        else:
            cost_score = 100

        # Latency stability (20%)
        latencies = [r.total_latency_ms for r in trends.recent_runs]
        if len(latencies) > 1 and trends.avg_latency_ms > 0:
            lat_var = sum((l - trends.avg_latency_ms) ** 2 for l in latencies) / len(latencies)
            lat_cv = (lat_var ** 0.5) / trends.avg_latency_ms if trends.avg_latency_ms > 0 else 0
            latency_score = max(0, min(100, int(100 - lat_cv * 200)))
        else:
            latency_score = 100

        # Token optimization (10%) — fewer tokens per check = better
        total_checks = sum(r.checks_passed + r.checks_failed for r in trends.recent_runs)
        if total_checks > 0:
            tokens_per_check = trends.avg_tokens / (total_checks / trends.total_runs) if total_checks > 0 else 0
            token_score = max(0, min(100, int(100 - tokens_per_check / 10)))
        else:
            token_score = 50

        total = int(check_score * 0.4 + cost_score * 0.3 + latency_score * 0.2 + token_score * 0.1)

        details = {
            "check_pass_rate": f"{trends.pass_rate_pct:.1f}%",
            "avg_cost": f"${trends.avg_cost:.6f}",
            "avg_latency": f"{trends.avg_latency_ms:.0f}ms",
            "avg_tokens": str(trends.avg_tokens),
            "total_runs": str(trends.total_runs),
        }

        return EfficiencyScore(
            total=total,
            check_score=check_score,
            cost_score=cost_score,
            latency_score=latency_score,
            token_score=token_score,
            details=details,
        )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


def _row_to_run(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        id=row["id"],
        scenario_id=row["scenario_id"],
        timestamp=row["timestamp"],
        provider=row["provider"],
        model=row["model"],
        total_cost=row["total_cost"],
        total_tokens=row["total_tokens"],
        total_latency_ms=row["total_latency_ms"],
        status=row["status"],
        trace_path=row["trace_path"],
        checks_passed=row["checks_passed"],
        checks_failed=row["checks_failed"],
    )
