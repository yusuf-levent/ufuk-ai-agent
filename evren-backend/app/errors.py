from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        message: str,
        type: str = "error",
        code: str | None = None,
        headers: dict[str, str] | None = None,
        extra: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.type = type
        self.code = code
        self.headers = headers
        self.extra = extra


def error_body(
    message: str, type: str, code: str | None = None, extra: dict[str, str] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"message": message, "type": type}
    if code is not None:
        error["code"] = code
    if extra:
        error.update(extra)
    return {"error": error}


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.message, exc.type, exc.code, exc.extra),
        headers=exc.headers,
    )
