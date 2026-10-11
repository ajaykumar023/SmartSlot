"""Cross-industry booking intake. The request is a customer preference, never a credential."""
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServiceIntakeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=1200)
    answers: dict[str, str] = Field(default_factory=dict)

    @field_validator("answers")
    @classmethod
    def check_answers(cls, value: dict[str, str]) -> dict[str, str]:
        # Field IDs are checked against the branch category at the API boundary.
        if len(value) > 8:
            raise ValueError("At most 8 intake answers are permitted")
        cleaned = {}
        for key, answer in value.items():
            if not isinstance(answer, str) or len(answer.strip()) > 300:
                raise ValueError("Each intake answer must be text of at most 300 characters")
            cleaned[key] = answer.strip()
        return cleaned
