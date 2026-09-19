"""本地候选程序评测 API。"""

from uuid import UUID
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.agents.factory import get_agent
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


@router.post("", response_model=EvaluationCreateResponse)
async def create_evaluation(
    payload: EvaluationRequest,
    request: Request,
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationCreateResponse:
    try:
        return await service.evaluate(payload.problem_id, request.state.evaluation_session.key_hash)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found") from error
    except (CaseNotFoundError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Evaluation cases are not configured",
        ) from error
    except AgentEvaluationError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Agent failed to generate an executable solution",
        ) from error
    except ControllerBusyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Evaluation service is busy") from error
    except (ControllerUnavailableError, ControllerTimeoutError, ControllerResponseError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Evaluation controller is unavailable",
        ) from error
    except EvaluationDisabledError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Evaluation is disabled",
        ) from error
    except EvaluationTimeoutError as error:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Evaluation request timed out",
        ) from error
    except EvaluationPersistenceError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Evaluation result could not be stored",
        ) from error


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


@router.get("/{evaluation_id}", response_model=EvaluationRunItem)
async def get_evaluation(
    evaluation_id: UUID,
    request: Request,
    repository: EvaluationRunRepository = Depends(get_evaluation_run_repository),
    settings: Settings = Depends(get_settings),
) -> EvaluationRunItem:
    item = await repository.get_for_session(
        evaluation_id,
        request.state.evaluation_session.key_hash,
        _history_cutoff(settings),
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation not found")
    return EvaluationRunItem.model_validate(item)