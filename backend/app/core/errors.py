"""Typed operational errors exposed through the HTTP contract."""

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class OperationalError(BaseModel):
    code: str
    detail: str
    current_version: int | None = None


class OperationalErrorException(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        detail: str,
        current_version: int | None = None,
    ) -> None:
        self.status_code = status_code
        self.error = OperationalError(
            code=code,
            detail=detail,
            current_version=current_version,
        )
        super().__init__(detail)


async def operational_error_handler(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    if not isinstance(exc, OperationalErrorException):
        raise exc
    return JSONResponse(status_code=exc.status_code, content=exc.error.model_dump())
