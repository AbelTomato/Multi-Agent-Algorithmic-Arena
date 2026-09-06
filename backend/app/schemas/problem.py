from pydantic import BaseModel, ConfigDict


class ProblemSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str


class ProblemDetail(ProblemSummary):
    description: str