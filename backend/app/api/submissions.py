from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_subject
from app.auth.models import Account
from app.database import get_db
from app.judges.client import ControllerError
from app.models.evaluation import Evaluation
from app.models.submission import Submission
from app.schemas.evaluation_submission import SubmissionEvaluationResponse
from app.schemas.submission import SubmissionCreate, SubmissionResponse, SubmissionRevisionCreate
from app.services.submission_evaluations import (
    SubmissionEvaluationError,
    SubmissionEvaluationForbiddenError,
    SubmissionEvaluationNotFoundError,
    SubmissionNotReplayableError,
    SubmissionEvaluationService,
)
from app.services.submissions import (
    SubmissionConflictError,
    SubmissionError,
    SubmissionForbiddenError,
    SubmissionNotFoundError,
    SubmissionService,
    SubmissionValidationError,
)


router = APIRouter(tags=["submissions"])


def get_submission_service(session: AsyncSession = Depends(get_db)) -> SubmissionService:
    return SubmissionService(session)


def get_submission_evaluation_service(
    session: AsyncSession = Depends(get_db),
) -> SubmissionEvaluationService:
    return SubmissionEvaluationService(session)


def _submission_error(error: SubmissionError) -> HTTPException:
    if isinstance(error, SubmissionForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Submission access is forbidden")
    if isinstance(error, SubmissionNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission or problem not found")
    if isinstance(error, SubmissionConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invalid submission revision")
    if isinstance(error, SubmissionValidationError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid submission")


def _evaluation_error(error: SubmissionEvaluationError) -> HTTPException:
    if isinstance(error, SubmissionEvaluationForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Submission access is forbidden")
    if isinstance(error, SubmissionEvaluationNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission or problem not found")
    if isinstance(error, SubmissionNotReplayableError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Submission source is not replayable")
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Evaluation service unavailable")


@router.post(
    "/api/submissions",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_submission(
    payload: SubmissionCreate,
    subject: Account = Depends(get_current_subject),
    service: SubmissionService = Depends(get_submission_service),
) -> SubmissionResponse:
    try:
        submission = await service.create(
            subject,
            problem_id=payload.problem_id,
            language=payload.language,
            source=payload.source,
            supersedes_submission_id=payload.supersedes_submission_id,
        )
    except SubmissionError as error:
        raise _submission_error(error) from error
    await service.session.commit()
    return SubmissionResponse.from_submission(submission)


@router.get("/api/submissions/{submission_id}", response_model=SubmissionResponse)
async def get_submission(
    submission_id: UUID,
    subject: Account = Depends(get_current_subject),
    service: SubmissionService = Depends(get_submission_service),
) -> SubmissionResponse:
    try:
        submission = await service.get(subject, submission_id)
    except SubmissionError as error:
        raise _submission_error(error) from error
    await service.session.commit()
    return SubmissionResponse.from_submission(submission)


@router.post(
    "/api/submissions/{submission_id}/revisions",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def revise_submission(
    submission_id: UUID,
    payload: SubmissionRevisionCreate,
    subject: Account = Depends(get_current_subject),
    service: SubmissionService = Depends(get_submission_service),
) -> SubmissionResponse:
    try:
        submission = await service.revise(
            subject,
            submission_id,
            problem_id=payload.problem_id,
            language=payload.language,
            source=payload.source,
        )
    except SubmissionError as error:
        raise _submission_error(error) from error
    return SubmissionResponse.from_submission(submission)


@router.post(
    "/api/submissions/{submission_id}/evaluations",
    response_model=SubmissionEvaluationResponse,
)
async def evaluate_submission(
    submission_id: UUID,
    subject: Account = Depends(get_current_subject),
    service: SubmissionEvaluationService = Depends(get_submission_evaluation_service),
) -> SubmissionEvaluationResponse:
    try:
        evaluation = await service.evaluate(subject, submission_id)
    except SubmissionEvaluationError as error:
        raise _evaluation_error(error) from error
    except (ControllerError, RuntimeError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Evaluation service unavailable",
        ) from error
    await service.session.commit()
    return SubmissionEvaluationResponse.from_evaluation(evaluation)
