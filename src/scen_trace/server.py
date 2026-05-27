from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from scen_trace.analytics import AnalyticsDB
from scen_trace.report import load_trace


def create_app(analytics_dir: Path, traces_dir: Path | None = None) -> Any:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="ScenTrace Dashboard", docs_url=None, redoc_url=None)

    dashboard_html = _load_dashboard_html()

    def _db() -> AnalyticsDB:
        db = AnalyticsDB(analytics_dir=analytics_dir)
        db.init()
        return db

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> str:
        return dashboard_html

    @app.get("/api/scenarios")
    async def list_scenarios() -> list[dict[str, Any]]:
        def _query() -> list[dict[str, Any]]:
            db = _db()
            try:
                runs = db.get_runs(None, 500)
                scenario_ids = sorted(set(r.scenario_id for r in runs))
                results = []
                for sid in scenario_ids:
                    trends = db.get_trends(sid, 30)
                    efficiency = db.compute_efficiency(sid)
                    results.append({
                        "scenario_id": sid,
                        "total_runs": trends.total_runs,
                        "avg_cost": trends.avg_cost,
                        "avg_latency_ms": trends.avg_latency_ms,
                        "pass_rate_pct": trends.pass_rate_pct,
                        "efficiency_score": efficiency.total,
                    })
                return results
            finally:
                db.close()
        return await asyncio.to_thread(_query)

    @app.get("/api/scenarios/{scenario_id}")
    async def scenario_detail(scenario_id: str) -> dict[str, Any]:
        def _query() -> dict[str, Any]:
            db = _db()
            try:
                trends = db.get_trends(scenario_id, 50)
                if trends.total_runs == 0:
                    return {"__not_found__": True, "scenario_id": scenario_id}
                efficiency = db.compute_efficiency(scenario_id)
                return {
                    "scenario_id": scenario_id,
                    "trends": {
                        "total_runs": trends.total_runs,
                        "avg_cost": trends.avg_cost,
                        "avg_latency_ms": trends.avg_latency_ms,
                        "avg_tokens": trends.avg_tokens,
                        "pass_rate_pct": trends.pass_rate_pct,
                    },
                    "efficiency": {
                        "total": efficiency.total,
                        "check_score": efficiency.check_score,
                        "cost_score": efficiency.cost_score,
                        "latency_score": efficiency.latency_score,
                        "token_score": efficiency.token_score,
                    },
                    "recent_runs": [
                        {
                            "id": r.id,
                            "timestamp": r.timestamp,
                            "status": r.status,
                            "total_cost": r.total_cost,
                            "total_tokens": r.total_tokens,
                            "total_latency_ms": r.total_latency_ms,
                            "checks_passed": r.checks_passed,
                            "checks_failed": r.checks_failed,
                            "provider": r.provider,
                            "model": r.model,
                        }
                        for r in trends.recent_runs[:20]
                    ],
                    "agent_breakdown": [
                        {
                            "agent_name": a.agent_name,
                            "turn_count": a.turn_count,
                            "total_tokens": a.total_tokens,
                            "avg_latency_ms": a.avg_latency_ms,
                            "cost_share_pct": a.cost_share_pct,
                        }
                        for a in trends.agent_breakdown
                    ],
                }
            finally:
                db.close()
        result = await asyncio.to_thread(_query)
        if result.get("__not_found__"):
            raise HTTPException(404, f"No runs found for scenario '{scenario_id}'")
        return result

    @app.get("/api/runs")
    async def list_runs(limit: int = 50) -> list[dict[str, Any]]:
        def _query() -> list[dict[str, Any]]:
            db = _db()
            try:
                runs = db.get_runs(None, min(limit, 200))
                return [
                    {
                        "id": r.id,
                        "scenario_id": r.scenario_id,
                        "timestamp": r.timestamp,
                        "status": r.status,
                        "total_cost": r.total_cost,
                        "total_tokens": r.total_tokens,
                        "total_latency_ms": r.total_latency_ms,
                        "checks_passed": r.checks_passed,
                        "checks_failed": r.checks_failed,
                        "provider": r.provider,
                        "model": r.model,
                    }
                    for r in runs
                ]
            finally:
                db.close()
        return await asyncio.to_thread(_query)

    @app.get("/api/traces")
    async def list_traces() -> list[dict[str, Any]]:
        search_dirs = [traces_dir] if traces_dir else [Path("."), analytics_dir]
        traces = []
        seen: set[str] = set()
        for d in search_dirs:
            for ext in ("*.json", "*.jsonl"):
                for f in sorted(d.glob(ext), key=lambda p: p.stat().st_mtime, reverse=True):
                    if f.name in seen or "analytics" in f.name or "baselines" in f.name:
                        continue
                    seen.add(f.name)
                    traces.append({
                        "name": f.name,
                        "path": str(f.resolve()),
                        "size_bytes": f.stat().st_size,
                    })
        return traces[:50]

    @app.get("/api/traces/{trace_name}")
    async def get_trace(trace_name: str) -> dict[str, Any]:
        search_dirs = [traces_dir] if traces_dir else [Path("."), analytics_dir]
        for d in search_dirs:
            candidate = d / trace_name
            if candidate.exists():
                trace = await asyncio.to_thread(load_trace, candidate)
                return {
                    "scenario_id": trace.scenario_id,
                    "status": trace.status,
                    "started_at": trace.started_at,
                    "finished_at": trace.finished_at,
                    "total_duration_ms": trace.total_duration_ms,
                    "total_input_tokens": trace.total_input_tokens,
                    "total_output_tokens": trace.total_output_tokens,
                    "estimated_cost": trace.estimated_cost,
                    "checks_passed": trace.checks_passed,
                    "checks_failed": trace.checks_failed,
                    "turns": trace.turns,
                }
        raise HTTPException(404, f"Trace not found: {trace_name}")

    return app


def _load_dashboard_html() -> str:
    template_path = Path(__file__).parent / "templates" / "dashboard.html"
    if template_path.exists():
        return template_path.read_text()
    return "<html><body><h1>Dashboard template missing</h1></body></html>"
