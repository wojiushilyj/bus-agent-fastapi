"""HTTP 接口输入模型。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .engine import SPOT_BY_ID


ScenarioName = Literal["normal", "peak", "event", "burst"]


class SimulationCreate(BaseModel):
    scenario: ScenarioName = "peak"
    hour: int = Field(default=11, ge=0, le=23)
    spot_id: str = "xs"

    @field_validator("spot_id")
    @classmethod
    def known_spot(cls, value: str) -> str:
        if value not in SPOT_BY_ID:
            raise ValueError("未知景区/站点")
        return value
