import pytest
from pydantic import ValidationError

from app.services.candidate_generation import CandidateGeneration, CandidateOutput


@pytest.mark.parametrize(
    ("payload", "language"),
    [
        ({"language": "python", "source": "print(1)"}, "python"),
        ({"language": "cpp", "source": "#include <iostream>"}, "cpp"),
    ],
)
def test_candidate_generation_returns_only_valid_structured_candidate(payload, language: str) -> None:
    candidate = CandidateGeneration.from_payload(payload)

    assert isinstance(candidate, CandidateOutput)
    assert candidate.language == language
    assert candidate.source == payload["source"]


@pytest.mark.parametrize(
    "payload",
    [
        {"language": "javascript", "source": "console.log(1)"},
        {"language": "python"},
        {"language": "python", "source": "", "runtime_id": "attacker"},
        {"language": "cpp", "source": "x" * (64 * 1024 + 1)},
    ],
)
def test_candidate_generation_rejects_invalid_or_execution_payload(payload) -> None:
    with pytest.raises(ValidationError):
        CandidateGeneration.from_payload(payload)