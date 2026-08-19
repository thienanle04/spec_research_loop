"""Idea HTTP schemas."""

from pydantic import BaseModel, Field, model_validator


class GenerateAnswer(BaseModel):
    option: str | None = None
    other: str | None = None

    @model_validator(mode="after")
    def option_xor_other(self) -> "GenerateAnswer":
        has_option = bool((self.option or "").strip())
        has_other = bool((self.other or "").strip())
        if has_option == has_other:
            raise ValueError("Each answer must be a Grilling Option or Other text")
        return self


class GenerateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    message: str | None = None
    answers: list[GenerateAnswer] | None = None
