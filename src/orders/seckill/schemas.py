from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AttemptCode = Literal["ACCEPTED", "DUPLICATE", "SOLD_OUT"]
ResultCode = Literal["PENDING", "SUCCESS", "FAILED", "NOT_FOUND"]


class AttemptRequest(BaseModel):
    user_id: int = Field(gt=0)
    request_id: str = Field(min_length=1, max_length=128)


class AttemptResponse(BaseModel):
    code: AttemptCode


class ResultResponse(BaseModel):
    code: ResultCode
