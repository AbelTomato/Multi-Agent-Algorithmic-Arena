"""本地候选程序评测 API。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.agents.factory import get_agent
from app.config import Settings, get_settings
from app.database import get_db
from app.judges.base import JudgeResult
from app.judges.catalog import CaseNotFoundError
from app.judges.client import (
    ControllerBusyError,
    ControllerResponseError,
    ControllerTimeoutError,
    ControllerUnavailableError,
)
from app.schemas.evaluation import EvaluationRequest
from app.services.evaluations import (
    AgentEvaluationError,
    EvaluationDisabledError,
    EvaluationService,
    EvaluationTimeoutError,
)


router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


def get_evaluation_service(
    session: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_agent),
    settings: Settings = Depends(get_settings),
) -> EvaluationService:
    return EvaluationService(session=session, agent=agent, settings=settings)


@router.post("", response_model=JudgeResult)
async def create_evaluation(
    request: EvaluationRequest,
    service: EvaluationService = Depends(get_evaluation_service),
) -> JudgeResult:
    try:
        return await service.evaluate(request.problem_id)
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