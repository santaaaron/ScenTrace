from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Agent(BaseModel):
    name: str
    role: str
    system_prompt: str


class ModelConfig(BaseModel):
    provider: str = "mock"
    model_name: str = "mock-v1"
    temperature: float = 0.7
    max_tokens: int = 1024


class Check(BaseModel):
    id: str
    type: str
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_check_type(self) -> Check:
        allowed = {"contains", "forbidden", "regex", "json_valid", "max_turns", "semantic", "python"}
        if self.type not in allowed:
            raise ValueError(f"Unknown check type '{self.type}'. Allowed: {', '.join(sorted(allowed))}")
        return self


class Turn(BaseModel):
    agent_name: str
    prompt: str
    expected_checks: list[str] = Field(default_factory=list)


class Scenario(BaseModel):
    scenario_id: str
    description: str = ""
    variables: dict[str, str] = Field(default_factory=dict)
    agents: list[Agent]
    model_config_: ModelConfig = Field(default_factory=ModelConfig, alias="model_config")
    turns: list[Turn]
    checks: list[Check] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def validate_references(self) -> Scenario:
        agent_names = {a.name for a in self.agents}
        check_ids = {c.id for c in self.checks}

        for turn in self.turns:
            if turn.agent_name not in agent_names:
                raise ValueError(f"Turn references unknown agent '{turn.agent_name}'. Known: {', '.join(sorted(agent_names))}")
            for check_ref in turn.expected_checks:
                if check_ref not in check_ids:
                    raise ValueError(f"Turn references unknown check '{check_ref}'. Known: {', '.join(sorted(check_ids))}")

        var_pattern = re.compile(r"\{\{(\w+)\}\}")
        defined_vars = set(self.variables.keys())
        for turn in self.turns:
            for match in var_pattern.finditer(turn.prompt):
                var_name = match.group(1)
                if var_name not in defined_vars:
                    raise ValueError(f"Prompt references undefined variable '{{{{{var_name}}}}}'. Defined: {', '.join(sorted(defined_vars))}")

        return self
