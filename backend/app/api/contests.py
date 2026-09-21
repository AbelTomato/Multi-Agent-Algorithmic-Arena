from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_subject
from app.auth.models import Account
from app.contests.service import (
    ContestActionConflictError,
    ContestError,
    ContestForbiddenError,
    ContestNotFoundError,
    ContestService,
    ContestStateError,
    ContestValidationError,
    ContestVersionConflictError,
)
from app.database import get_db
from app.schemas.contest import ContestActionRequest, ContestActionResponse, ContestView


router = APIRouter(prefix="/api/contests", tags=["contests"])


def get_contest_service(session: AsyncSession = Depends(get_db)) -> ContestService:
    return ContestService(session)


def _contest_error(error: ContestError) -> HTTPException:
    if isinstance(error, ContestNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contest not found")
    if isinstance(error, ContestForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Contest access is forbidden")
    if isinstance(error, (ContestActionConflictError, ContestVersionConflictError, ContestStateError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, ContestValidationError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid contest operation")


@router.get("/{contest_id}", response_model=ContestView)
async def get_contest(
    contest_id: UUID,
    subject: Account = Depends(get_current_subject),
    service: ContestService = Depends(get_contest_service),
) -> ContestView:
    try:
        return await service.get_view(subject, contest_id)
    except ContestError as error:
        raise _contest_error(error) from error


@router.post("/{contest_id}/actions", response_model=ContestActionResponse)
async def apply_contest_action(
    contest_id: UUID,
    payload: ContestActionRequest,
    subject: Account = Depends(get_current_subject),
    service: ContestService = Depends(get_contest_service),
) -> ContestActionResponse:
    try:
        response = await service.apply_action(subject, contest_id, payload)
        await service.session.commit()
        return response
    except ContestError as error:
        raise _contest_error(error) from error