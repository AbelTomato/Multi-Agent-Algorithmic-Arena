from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.problem import Problem
from app.schemas.problem import ProblemDetail, ProblemSummary


router = APIRouter(prefix="/api/problems", tags=["problems"])


@router.get("", response_model=list[ProblemSummary])
async def get_problems(session: AsyncSession = Depends(get_db)) -> list[Problem]:
    statement = select(Problem).order_by(Problem.id)
    result = await session.execute(statement)
    return list(result.scalars().all())


@router.get("/{problem_id}", response_model=ProblemDetail)
async def get_problem(
    problem_id: int,
    session: AsyncSession = Depends(get_db),
) -> Problem:
    problem = await session.get(Problem, problem_id)
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Problem not found",
        )
    return problem
