from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account
from app.auth.service import AuthService, AuthenticationError
from app.database import get_db


bearer_scheme = HTTPBearer(auto_error=False)


def _authentication_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_subject(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> Account:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _authentication_exception()
    try:
        return await AuthService(session).resolve_subject(credentials.credentials)
    except AuthenticationError as error:
        raise _authentication_exception() from error


def require_submission_owner(subject: Account, owner_id: UUID) -> None:
    if subject.id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Submission access is forbidden",
        )