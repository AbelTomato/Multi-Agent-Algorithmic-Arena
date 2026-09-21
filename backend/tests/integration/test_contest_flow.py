import asyncio
from collections.abc import AsyncGenerator, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.models import Account, SubjectType
from app.auth.service import AuthService
from app.contests.contracts import ContestActionRequest
from app.contests.rules import ContestActionType
from app.contests.service import ContestService
from app.database import Base, get_db
from app.main import app
from app.models.contest import Contest
from app.models.permission import ProblemSubmissionPermission
from app.models.problem import Problem
from app.services.submissions import SubmissionService


@dataclass(frozen=True)
class ContestFlowData:
    contest_id: UUID
    owner_submission_id: UUID
    agent_submission_id: UUID
    owner_token: str
    agent_token: str
    session_factory: async_sessionmaker[AsyncSession]


@pytest.fixture
def contest_client(tmp_path) -> Iterator[tuple[TestClient, ContestFlowData]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'contest-flow.db'}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def setup_database() -> ContestFlowData:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            owner = Account(subject_type=SubjectType.HUMAN, name="flow-human")
            agent = Account(subject_type=SubjectType.AGENT, name="flow-agent")
            problem = Problem(
                slug="flow-problem",
                title="Flow Problem",
                description="description",
                allowed_languages=["python"],
                active_case_version="v1",
            )
            session.add_all([owner, agent, problem])
            await session.flush()
            session.add_all(
                [
                    ProblemSubmissionPermission(account_id=owner.id, problem_id=problem.id),
                    ProblemSubmissionPermission(account_id=agent.id, problem_id=problem.id),
                ]
            )
            owner_token = await AuthService(session).issue_token(owner.id)
            agent_token = await AuthService(session).issue_token(agent.id)
            await session.flush()

            owner_submission = await SubmissionService(session).create(
                owner,
                problem_id=problem.id,
                language="python",
                source="human-secret-source",
            )
            agent_submission = await SubmissionService(session).create(
                agent,
                problem_id=problem.id,
                language="python",
                source="agent-secret-source",
            )
            starts_at = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
            contest = await ContestService(session).create_draft(
                owner,
                problem_id=problem.id,
                first_account_id=owner.id,
                second_account_id=agent.id,
                starts_at=starts_at,
                solving_deadline=starts_at + timedelta(minutes=30),
            )
            service = ContestService(session)
            await service.apply_action(
                owner,
                contest.id,
                ContestActionRequest(
                    client_action_id="flow-publish",
                    expected_version=0,
                    action_type=ContestActionType.PUBLISH,
                    payload={},
                ),
            )
            await service.advance_time(contest.id, now=starts_at)
            await session.commit()
            return ContestFlowData(
                contest_id=contest.id,
                owner_submission_id=owner_submission.id,
                agent_submission_id=agent_submission.id,
                owner_token=owner_token,
                agent_token=agent_token,
                session_factory=session_factory,
            )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    data = asyncio.run(setup_database())
    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), data
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _submit_payload(submission_id: UUID, *, action_id: str, expected_version: int) -> dict[str, object]:
    return {
        "client_action_id": action_id,
        "expected_version": expected_version,
        "action_type": "submit_submission",
        "payload": {"submission_id": str(submission_id)},
    }


def test_human_and_agent_use_the_same_authenticated_action_route(contest_client) -> None:
    client, data = contest_client

    human_response = client.post(
        f"/api/contests/{data.contest_id}/actions",
        headers=_bearer(data.owner_token),
        json=_submit_payload(
            data.owner_submission_id,
            action_id="flow-human-submit",
            expected_version=2,
        ),
    )
    assert human_response.status_code == 200
    assert human_response.json()["status"] == "SOLVING"

    agent_response = client.post(
        f"/api/contests/{data.contest_id}/actions",
        headers=_bearer(data.agent_token),
        json=_submit_payload(
            data.agent_submission_id,
            action_id="flow-agent-submit",
            expected_version=3,
        ),
    )
    assert agent_response.status_code == 200
    assert agent_response.json()["status"] == "SOLVING"
    assert "agent-secret-source" in agent_response.text
    assert "human-secret-source" not in agent_response.text


def test_contest_route_maps_auth_forbidden_and_version_errors(contest_client) -> None:
    client, data = contest_client
    path = f"/api/contests/{data.contest_id}/actions"

    assert client.get(f"/api/contests/{data.contest_id}").status_code == 401

    cross_seat = client.post(
        path,
        headers=_bearer(data.owner_token),
        json=_submit_payload(
            data.agent_submission_id,
            action_id="flow-cross-seat",
            expected_version=2,
        ),
    )
    assert cross_seat.status_code == 403

    accepted = client.post(
        path,
        headers=_bearer(data.owner_token),
        json=_submit_payload(
            data.owner_submission_id,
            action_id="flow-version-source",
            expected_version=2,
        ),
    )
    assert accepted.status_code == 200

    stale = client.post(
        path,
        headers=_bearer(data.agent_token),
        json=_submit_payload(
            data.agent_submission_id,
            action_id="flow-stale-version",
            expected_version=2,
        ),
    )
    assert stale.status_code == 409


def test_contest_read_uses_a_new_session_and_filters_opponent_source(contest_client) -> None:
    client, data = contest_client
    path = f"/api/contests/{data.contest_id}/actions"

    first = client.post(
        path,
        headers=_bearer(data.owner_token),
        json=_submit_payload(
            data.owner_submission_id,
            action_id="flow-restart-human",
            expected_version=2,
        ),
    )
    assert first.status_code == 200
    second = client.post(
        path,
        headers=_bearer(data.agent_token),
        json=_submit_payload(
            data.agent_submission_id,
            action_id="flow-restart-agent",
            expected_version=3,
        ),
    )
    assert second.status_code == 200

    restarted_read = client.get(
        f"/api/contests/{data.contest_id}",
        headers=_bearer(data.agent_token),
    )
    assert restarted_read.status_code == 200
    payload = restarted_read.json()
    assert payload["state_version"] == 4
    assert payload["event_sequence"] == 5
    assert "agent-secret-source" in restarted_read.text
    assert "human-secret-source" not in restarted_read.text
    assert "prompt" not in restarted_read.text.lower()


def test_public_route_rejects_internal_actions_and_preserves_legacy_evaluation_post(
    contest_client,
) -> None:
    client, data = contest_client
    path = f"/api/contests/{data.contest_id}/actions"

    for action_type in ("advance_time", "record_evaluation"):
        response = client.post(
            path,
            headers=_bearer(data.owner_token),
            json={
                "client_action_id": f"flow-internal-{action_type}",
                "expected_version": 2,
                "action_type": action_type,
                "payload": {},
            },
        )
        assert response.status_code == 422

    assert client.post(
        "/api/evaluations",
        headers=_bearer(data.owner_token),
        json={"problem_id": 1},
    ).status_code == 405
    current = client.get(
        f"/api/contests/{data.contest_id}",
        headers=_bearer(data.owner_token),
    )
    assert current.status_code == 200
    assert current.json()["state_version"] == 2


def test_contest_cors_preflight_allows_bearer_authorization_header() -> None:
    response = TestClient(app).options(
        "/api/contests/00000000-0000-0000-0000-000000000000/actions",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()