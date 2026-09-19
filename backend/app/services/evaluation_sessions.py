"""匿名评测历史会话令牌的生成、校验与不可逆哈希。"""

from dataclasses import dataclass
import hashlib
import re
import secrets

from starlette.requests import Request

from app.config import Settings


EVALUATION_SESSION_COOKIE_NAME = "arena_evaluation_session"
EVALUATION_SESSION_COOKIE_PATH = "/api/evaluations"
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


@dataclass(frozen=True, repr=False)
class EvaluationSession:
    token: str
    key_hash: str
    is_new: bool

    def __repr__(self) -> str:
        return (
            "EvaluationSession(token=<redacted>, "
            f"key_hash=<sha256:{self.key_hash[:8]}...>, is_new={self.is_new!r})"
        )


def hash_evaluation_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def is_valid_evaluation_session_token(token: str | None) -> bool:
    return token is not None and _TOKEN_PATTERN.fullmatch(token) is not None


def resolve_evaluation_session(request: Request, settings: Settings) -> EvaluationSession:
    del settings  # 保留固定接口，后续配置扩展无需改变 middleware 调用边界。
    token = request.cookies.get(EVALUATION_SESSION_COOKIE_NAME)
    is_new = not is_valid_evaluation_session_token(token)
    if is_new:
        token = secrets.token_urlsafe(32)
    assert token is not None
    return EvaluationSession(
        token=token,
        key_hash=hash_evaluation_session_token(token),
        is_new=is_new,
    )