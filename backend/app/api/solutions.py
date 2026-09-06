from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.agents.factory import get_agent
from app.config import Settings, get_settings
from app.database import get_db
from app.schemas.solution import SolutionRequest, SolutionResponse
from app.services.solutions import AgentGenerationError, SolutionService


router = APIRouter(prefix="/api/solutions", tags=["solutions"])


@router.post("", response_model=SolutionResponse)
async def create_solution(
    request: SolutionRequest,
    session: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_agent),
    settings: Settings = Depends(get_settings),
) -> SolutionResponse:
    service = SolutionService(session=session, agent=agent, settings=settings)
    try:
        result = await service.generate_solution(request.problem_id)
    except LookupError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Problem not found",
        ) from error
    except AgentGenerationError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Agent failed to generate a solution",
        ) from error

    return SolutionResponse(problem_id=request.problem_id, result=result)