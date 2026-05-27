from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ProviderResponse:
    content: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    metadata: dict = field(default_factory=dict)


class BaseProvider(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, prompt: str, **kwargs) -> ProviderResponse:
        ...
