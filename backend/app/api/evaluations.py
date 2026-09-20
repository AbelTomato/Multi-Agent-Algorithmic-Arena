"""本地候选程序评测 API。"""

from uuid import UUID
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.agents.factory import get_agent
from app.auth.dependencies import bearer_scheme
from app.auth.service import AuthService, AuthenticationError
from app.config import Settings, get_settings
from app.database import get_db
from app.judges.catalog import CaseNotFoundError
from app.judges.client import (
    ControllerBusyError,
    ControllerResponseError,
    ControllerTimeoutError,
    ControllerUnavailableError,
)
from app.schemas.evaluation import (
    EvaluationCreateResponse,
    EvaluationRequest,
    EvaluationRunItem,
    EvaluationRunListResponse,
)
from app.services.evaluations import (
    AgentEvaluationError,
    EvaluationDisabledError,
    EvaluationPersistenceError,
    EvaluationService,
    EvaluationTimeoutError,
)
from app.services.evaluation_runs import EvaluationRunRepository
from app.models.evaluation import Evaluation
from app.models.submission import Submission
from app.schemas.evaluation_submission import SubmissionEvaluationResponse


router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


def get_evaluation_service(
    session: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_agent),
    settings: Settings = Depends(get_settings),
) -> EvaluationService:
    return EvaluationService(session=session, agent=agent, settings=settings)


def get_evaluation_run_repository(
    session: AsyncSession = Depends(get_db),
) -> EvaluationRunRepository:
    return EvaluationRunRepository(session)


def _history_cutoff(settings: Settings) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=settings.evaluation_history_retention_days)


@router.get("", response_model=EvaluationRunListResponse)
async def list_evaluations(
    request: Request,
    problem_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    repository: EvaluationRunRepository = Depends(get_evaluation_run_repository),
    settings: Settings = Depends(get_settings),
) -> EvaluationRunListResponse:
    items, total = await repository.list_for_session(
        request.state.evaluation_session.key_hash,
        _history_cutoff(settings),
        problem_id,
        limit,
        offset,
    )
    return EvaluationRunListResponse(
        items=[EvaluationRunItem.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{evaluation_id}", response_model=None)
async def get_evaluation(
    evaluation_id: UUID,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
    repository: EvaluationRunRepository = Depends(get_evaluation_run_repository),
    settings: Settings = Depends(get_settings),
) -> EvaluationRunItem:
    if credentials is not None:
        if credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            subject = await AuthService(session).resolve_subject(credentials.credentials)
        except AuthenticationError as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            ) from error

        evaluation = await session.get(Evaluation, evaluation_id)
        if evaluation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation not found")
        submission = await session.get(Submission, evaluation.submission_id)
        if submission is None or submission.author_subject_id != subject.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Evaluation access is forbidden")
        return SubmissionEvaluationResponse.from_evaluation(evaluation)

    item = await repository.get_for_session(
        evaluation_id,
        request.state.evaluation_session.key_hash,
        _history_cutoff(settings),
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation not found")
    return EvaluationRunItem.model_validate(item)