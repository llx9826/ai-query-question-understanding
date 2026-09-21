from typing import Literal

from pydantic import Field

from app.contracts.base import DTO


class ConversationTurn(DTO):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4_000)


class QuestionInput(DTO):
    request_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
    question: str = Field(min_length=1, max_length=4_000)
    history: tuple[ConversationTurn, ...] = Field(default=(), max_length=12)
    limit: int = Field(default=200, ge=1, le=500)
