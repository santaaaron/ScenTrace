from __future__ import annotations

from scen_trace.providers import BaseProvider, ProviderResponse


class MockProvider(BaseProvider):
    def __init__(self, fail_on_turn: int | None = None):
        self._call_count = 0
        self._fail_on_turn = fail_on_turn

    def generate(self, system_prompt: str, prompt: str, **kwargs) -> ProviderResponse:
        self._call_count += 1
        if self._fail_on_turn is not None and self._call_count == self._fail_on_turn:
            raise RuntimeError(f"Mock failure on turn {self._call_count}")

        response = f"Mock response for: {prompt}"
        input_text = (system_prompt or "") + prompt
        return ProviderResponse(
            content=response,
            model=kwargs.get("model", "mock-v1"),
            input_tokens=max(1, len(input_text) // 4),
            output_tokens=max(1, len(response) // 4),
        )
