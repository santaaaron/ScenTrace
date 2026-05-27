from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from scen_trace.schema import Scenario


def load_scenario(path: Path) -> Scenario:
    if not path.exists():
        raise FileNotFoundError(f"Scenario file not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    if not data:
        raise ValueError(f"Scenario file is empty: {path}")

    return Scenario(**data)


def format_validation_error(error: ValidationError) -> str:
    lines = []
    for err in error.errors():
        loc = " -> ".join(str(x) for x in err["loc"])
        lines.append(f"  {loc}: {err['msg']}")
    return "\n".join(lines)
