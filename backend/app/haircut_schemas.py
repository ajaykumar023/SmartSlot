"""Client-supplied styling wishes, never professional qualifications."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class HaircutPreferencesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    style: Literal[
        "fade", "taper", "trim", "buzz_cut", "layers", "styling", "other", "not_sure"
    ] = "not_sure"
    preferred_length: Literal["short", "medium", "long", "unsure"] = "unsure"
    notes: str = Field(default="", max_length=800)
