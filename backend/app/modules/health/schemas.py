from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    env: str


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    version: str
    database: Literal["ok", "error"]
