from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scen_trace.checks import CheckResult, evaluate_check
from scen_trace.providers import BaseProvider, ProviderResponse
from scen_trace.schema import Scenario


@dataclass
class TurnTrace:
    turn_index: int
    agent_name: str
    prompt: str
    response: str
    timestamp: str
    model: str = ""
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: float = 0.0
    status: str = "success"
    error: str | None = None
    check_results: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunResult:
    scenario_id: str
    status: str  # passed, failed, max_turns_exceeded, error
    turns: list[TurnTrace]
    started_at: str = ""
    finished_at: str = ""
    total_duration_ms: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost: float = 0.0
    checks_passed: int = 0
    checks_failed: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["turns"] = [t.to_dict() for t in self.turns]
        return d


def _resolve_variables(text: str, variables: dict[str, str]) -> str:
    def replacer(match):
        var_name = match.group(1)
        return variables.get(var_name, match.group(0))
    return re.sub(r"\{\{(\w+)\}\}", replacer, text)


COST_PER_TOKEN = 0.000001


def run_scenario(
    scenario: Scenario,
    provider: BaseProvider,
    max_turns: int | None = None,
    stop_on_error: bool = False,
    stop_on_fail: bool = False,
    on_turn_complete: Callable[[TurnTrace], None] | None = None,
    scenario_dir: Path | None = None,
) -> RunResult:
    effective_max = max_turns if max_turns is not None else len(scenario.turns)
    check_map = {c.id: c for c in scenario.checks}

    traces: list[TurnTrace] = []
    status = "passed"
    all_check_results: list[CheckResult] = []
    started_at = datetime.now(timezone.utc).isoformat()
    run_start = time.monotonic()

    for i, turn in enumerate(scenario.turns):
        if i >= effective_max:
            status = "max_turns_exceeded"
            break

        resolved_prompt = _resolve_variables(turn.prompt, scenario.variables)
        agent = next((a for a in scenario.agents if a.name == turn.agent_name), None)
        system_prompt = agent.system_prompt if agent else ""

        turn_start = time.monotonic()
        try:
            resp: ProviderResponse = provider.generate(
                system_prompt=system_prompt,
                prompt=resolved_prompt,
                model=scenario.model_config_.model_name,
                temperature=scenario.model_config_.temperature,
                max_tokens=scenario.model_config_.max_tokens,
            )
            duration_ms = (time.monotonic() - turn_start) * 1000

            turn_checks: list[CheckResult] = []
            for check_ref in turn.expected_checks:
                if check_ref in check_map:
                    c = check_map[check_ref]
                    result = evaluate_check(c.id, c.type, c.params, resp.content, scenario_dir=scenario_dir)
                    turn_checks.append(result)
                    all_check_results.append(result)

            trace = TurnTrace(
                turn_index=i,
                agent_name=turn.agent_name,
                prompt=resolved_prompt,
                response=resp.content,
                timestamp=datetime.now(timezone.utc).isoformat(),
                model=resp.model,
                provider=scenario.model_config_.provider,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                duration_ms=round(duration_ms, 2),
                status="success",
                check_results=[asdict(cr) for cr in turn_checks],
            )

            if any(not cr.passed for cr in turn_checks):
                if stop_on_fail:
                    trace.status = "check_failed"
                    traces.append(trace)
                    if on_turn_complete:
                        on_turn_complete(trace)
                    status = "failed"
                    break

        except Exception as e:
            duration_ms = (time.monotonic() - turn_start) * 1000
            trace = TurnTrace(
                turn_index=i,
                agent_name=turn.agent_name,
                prompt=resolved_prompt,
                response="",
                timestamp=datetime.now(timezone.utc).isoformat(),
                duration_ms=round(duration_ms, 2),
                status="error",
                error=str(e),
            )
            if stop_on_error:
                traces.append(trace)
                if on_turn_complete:
                    on_turn_complete(trace)
                status = "error"
                break

        traces.append(trace)
        if on_turn_complete:
            on_turn_complete(trace)

    run_duration = (time.monotonic() - run_start) * 1000
    finished_at = datetime.now(timezone.utc).isoformat()

    total_in = sum(t.input_tokens for t in traces)
    total_out = sum(t.output_tokens for t in traces)
    checks_passed = sum(1 for cr in all_check_results if cr.passed)
    checks_failed = sum(1 for cr in all_check_results if not cr.passed)

    if checks_failed > 0 and status == "passed":
        status = "failed"

    return RunResult(
        scenario_id=scenario.scenario_id,
        status=status,
        turns=traces,
        started_at=started_at,
        finished_at=finished_at,
        total_duration_ms=round(run_duration, 2),
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        estimated_cost=round((total_in + total_out) * COST_PER_TOKEN, 6),
        checks_passed=checks_passed,
        checks_failed=checks_failed,
        metadata={
            "provider": scenario.model_config_.provider,
            "model": scenario.model_config_.model_name,
        },
    )


def write_trace(result: RunResult, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix == ".jsonl":
        with open(output_path, "w") as f:
            for turn in result.turns:
                f.write(json.dumps(turn.to_dict()) + "\n")
    else:
        with open(output_path, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
