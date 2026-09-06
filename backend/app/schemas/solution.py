from pydantic import BaseModel, ConfigDict, Field


class SolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_id: int = Field(gt=0)


class SolutionResponse(BaseModel):
    problem_id: int
    result: str
    language: str = "python"