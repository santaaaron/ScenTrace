from __future__ import annotations

import os

from scen_trace.providers import BaseProvider, ProviderResponse


class OpenAIProvider(BaseProvider):
    def __init__(self):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable is not set. "
                "Set it before using the OpenAI provider."
            )
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key)

    def generate(self, system_prompt: str, prompt: str, **kwargs) -> ProviderResponse:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat.completions.create(
            model=kwargs.get("model", "gpt-4o-mini"),
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 1024),
        )

        choice = response.choices[0]
        usage = response.usage
        return ProviderResponse(
            content=choice.message.content or "",
            model=response.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )
