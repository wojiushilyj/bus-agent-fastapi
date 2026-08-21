"""HTTP 接口输入模型。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .engine import SPOT_BY_ID


ScenarioName = Literal["normal", "peak", "event", "burst"]
SimulationStatus = Literal["planned", "dispatched", "evaluated"]
ExportFormat = Literal["print", "pdf"]


class SimulationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scenario: ScenarioName = "peak"
    hour: int = Field(default=11, ge=0, le=23)
    spot_id: str = Field(default="xs", min_length=2, max_length=16)

    @field_validator("spot_id")
    @classmethod
    def known_spot(cls, value: str) -> str:
        if value not in SPOT_BY_ID:
            raise ValueError("未知景区/站点")
        return value


class ExportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: ExportFormat = "print"
