from __future__ import annotations

from pathlib import Path

EXAMPLE_SCENARIO = """\
scenario_id: hello_world
description: A basic multi-agent greeting test to verify ScenTrace is working.

variables:
  user_name: Alice

agents:
  - name: assistant
    role: assistant
    system_prompt: You are a helpful assistant. Always greet users by name.

model_config:
  provider: mock
  model_name: mock-v1
  temperature: 0.7
  max_tokens: 256

turns:
  - agent_name: assistant
    prompt: "Say hello to {{user_name}}"
    expected_checks:
      - greeting_check

checks:
  - id: greeting_check
    type: contains
    params:
      text: "mock response"
"""

ENV_EXAMPLE = """\
# ScenTrace environment variables
# Copy this file to .env and fill in your values.

# OpenAI (required for --provider openai)
# OPENAI_API_KEY=sk-...

# Anthropic (required for --provider anthropic)
# ANTHROPIC_API_KEY=sk-ant-...
"""

GITIGNORE_SNIPPET = """\
# ScenTrace
.env
traces/
reports/
"""

SCAFFOLD_FILES: dict[str, str] = {
    "example_scenario.yaml": EXAMPLE_SCENARIO,
    ".env.example": ENV_EXAMPLE,
    ".gitignore": GITIGNORE_SNIPPET,
}


def scaffold_project(target: Path) -> tuple[list[str], list[str]]:
    target.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    skipped: list[str] = []

    for filename, content in SCAFFOLD_FILES.items():
        filepath = target / filename
        if filepath.exists():
            skipped.append(str(filepath))
        else:
            filepath.write_text(content)
            created.append(str(filepath))

    return created, skipped
