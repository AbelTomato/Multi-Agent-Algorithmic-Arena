"""为评测 API 建立匿名会话，并在响应开始时设置受限 Cookie。"""

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings
from app.services.evaluation_sessions import (
    EVALUATION_SESSION_COOKIE_NAME,
    EVALUATION_SESSION_COOKIE_PATH,
    resolve_evaluation_session,
)


class EvaluationSessionMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._matches(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        session = resolve_evaluation_session(Request(scope), self.settings)
        state = scope.setdefault("state", {})
        state["evaluation_session"] = session

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start" and session.is_new:
                cookie_response = Response()
                cookie_response.set_cookie(
                    key=EVALUATION_SESSION_COOKIE_NAME,
                    value=session.token,
                    max_age=self.settings.evaluation_history_retention_days * 86400,
                    path=EVALUATION_SESSION_COOKIE_PATH,
                    secure=self.settings.evaluation_history_cookie_secure,
                    httponly=True,
                    samesite="lax",
                )
                cookie_header = cookie_response.headers["set-cookie"]
                headers = MutableHeaders(scope=message)
                headers.append("set-cookie", cookie_header)
            await send(message)

        await self.app(scope, receive, send_with_cookie)

    @staticmethod
    def _matches(path: str) -> bool:
        return path == EVALUATION_SESSION_COOKIE_PATH or path.startswith(
            f"{EVALUATION_SESSION_COOKIE_PATH}/"
        )