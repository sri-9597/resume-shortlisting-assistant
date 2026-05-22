from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Provider-agnostic adapter for LLM scoring calls.

    Implementations MUST:
      - Treat `cacheable_prefix` as a stable block that varies rarely across calls
        (rubric + JD + company context). Use prompt caching when supported.
      - Return a dict that conforms to `output_schema`. The pipeline validates it.
    """

    name: str
    model: str

    @abstractmethod
    async def score(
        self,
        *,
        system: str,
        cacheable_prefix: str,
        candidate_block: str,
        output_schema: dict,
        tool_name: str,
        tool_description: str,
    ) -> dict:
        ...
