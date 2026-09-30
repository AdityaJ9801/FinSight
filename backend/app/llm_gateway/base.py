from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMValidationError(Exception):
    """Raised when the model's JSON output fails schema validation after all retries."""


class LLMGateway(ABC):
    """Interface every LLM backend (fake, real HTTP) implements. Agents depend on this,
    never on a concrete client (design doc §4.2/§7: "internal llm_gateway... swap providers").
    """

    @abstractmethod
    def complete(
        self,
        messages: list[dict],
        schema: Type[T] | None = None,
        tier: str = "default",
        max_retries: int = 1,
    ) -> T | str:
        """If schema is given, returns a validated instance of it. Otherwise returns raw text."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...
