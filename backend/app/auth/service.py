import hashlib
import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AccessToken, Account, SubjectType


class AuthenticationError(Exception):
    """认证凭据无效、已撤销或关联账户不可用。"""


class AuthService:
    authentication_error = AuthenticationError

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    async def issue_token(self, account_id: UUID) -> str:
        raw_token = secrets.token_urlsafe(32)
        self.session.add(
            AccessToken(
                account_id=account_id,
                token_hash=self.hash_token(raw_token),
            )
        )
        return raw_token

    async def revoke_token(self, raw_token: str) -> None:
        token = await self.session.scalar(
            select(AccessToken).where(AccessToken.token_hash == self.hash_token(raw_token))
        )
        if token is not None:
            from datetime import datetime, timezone

            token.revoked_at = datetime.now(timezone.utc)

    async def resolve_subject(self, raw_token: str) -> Account:
        token = await self.session.scalar(
            select(AccessToken).where(AccessToken.token_hash == self.hash_token(raw_token))
        )
        if token is None or token.revoked_at is not None:
            raise AuthenticationError("invalid authentication token")

        account = await self.session.get(Account, token.account_id)
        if account is None or not account.is_active:
            raise AuthenticationError("inactive authentication subject")
        SubjectType(account.subject_type)
        return account