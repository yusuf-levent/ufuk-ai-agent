from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

VALID_ROLES = {"system", "user", "assistant", "tool"}


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible request. `model` is a gateway tier alias."""

    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1, max_length=50)
    messages: list[dict[str, Any]] = Field(min_length=1)
    stream: bool | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    n: int | None = Field(default=None, ge=1, le=16)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    stop: str | list[str] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    response_format: dict[str, Any] | None = None
    seed: int | None = None
    logit_bias: dict[str, float] | None = None
    parallel_tool_calls: bool | None = None
    logprobs: bool | None = None
    top_logprobs: int | None = Field(default=None, ge=0, le=20)

    @field_validator("messages")
    @classmethod
    def _validate_messages(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for message in value:
            if not isinstance(message, dict) or message.get("role") not in VALID_ROLES:
                raise ValueError("each message must be an object with a valid role")
        return value
