from app.schemas.problem import ProblemDetail, ProblemSummary


def test_problem_summary_excludes_description() -> None:
    summary = ProblemSummary(id=1, slug="two-sum", title="Two Sum")

    assert summary.model_dump() == {"id": 1, "slug": "two-sum", "title": "Two Sum"}


def test_problem_detail_includes_description() -> None:
    detail = ProblemDetail(
        id=1,
        slug="two-sum",
        title="Two Sum",
        description="# Two Sum",
    )

    assert detail.model_dump()["description"] == "# Two Sum"