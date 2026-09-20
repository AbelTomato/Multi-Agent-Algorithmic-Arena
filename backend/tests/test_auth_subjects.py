from collections.abc import AsyncGenerator
from hashlib import sha256
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.dependencies import get_current_subject, require_submission_owner
from app.auth.models import AccessToken, Account, SubjectType
from app.auth.service import AuthService
from app.database import Base, get_db


@pytest.fixture
async def auth_database(tmp_path) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_only_human_and_agent_are_valid_subject_types() -> None:
    assert SubjectType.HUMAN.value == "human"
    assert SubjectType.AGENT.value == "agent"
    with pytest.raises(ValueError):
        SubjectType("service")


@pytest.mark.asyncio
async def test_issued_token_is_stored_only_as_sha256_hash(auth_database) -> None:
    async with auth_database() as session:
        account = Account(subject_type=SubjectType.AGENT, name="solver-agent")
        session.add(account)
        await session.flush()

        raw_token = await AuthService(session).issue_token(account.id)
        await session.commit()

        stored_token = await session.scalar(select(AccessToken))
        assert stored_token is not None
        assert raw_token
        assert stored_token.token_hash == sha256(raw_token.encode("utf-8")).hexdigest()
        assert raw_token not in stored_token.token_hash

        subject = await AuthService(session).resolve_subject(raw_token)
        assert subject.id == account.id
        assert subject.subject_type is SubjectType.AGENT
        assert subject.name == "solver-agent"


@pytest.mark.asyncio
async def test_revoked_token_and_disabled_account_are_rejected(auth_database) -> None:
    async with auth_database() as session:
        account = Account(subject_type=SubjectType.HUMAN, name="alice")
        session.add(account)
        await session.flush()
        service = AuthService(session)
        raw_token = await service.issue_token(account.id)
        await session.commit()

        await service.revoke_token(raw_token)
        await session.commit()
        with pytest.raises(service.authentication_error):
            await service.resolve_subject(raw_token)

        account.is_active = False
        await session.commit()
        with pytest.raises(service.authentication_error):
            await service.resolve_subject(raw_token)


@pytest.mark.asyncio
async def test_dependency_maps_missing_invalid_and_cross_subject_access_to_http_errors(
    auth_database,
) -> None:
    async with auth_database() as session:
        owner = Account(subject_type=SubjectType.HUMAN, name="owner")
        other = Account(subject_type=SubjectType.AGENT, name="other-agent")
        session.add_all([owner, other])
        await session.flush()
        service = AuthService(session)
        owner_token = await service.issue_token(owner.id)
        await session.commit()

        app = FastAPI()

        async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
            yield session

        app.dependency_overrides[get_db] = override_get_db

        @app.get("/subject")
        async def read_subject(subject=Depends(get_current_subject)):
            return {"id": str(subject.id), "type": subject.subject_type.value}

        @app.get("/owned/{owner_id}")
        async def read_owned(
            owner_id: UUID,
            subject=Depends(get_current_subject),
        ):
            require_submission_owner(subject, owner_id)
            return {"ok": True}

        with TestClient(app) as client:
            assert client.get("/subject").status_code == 401
            assert client.get(
                "/subject", headers={"Authorization": "Bearer invalid-token"}
            ).status_code == 401
            assert client.get(
                "/subject", headers={"Authorization": f"Bearer {owner_token}"}
            ).json() == {"id": str(owner.id), "type": "human"}
            assert client.get(
                f"/owned/{other.id}",
                headers={"Authorization": f"Bearer {owner_token}"},
            ).status_code == 403