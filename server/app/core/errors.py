"""统一错误模型与异常处理器。

响应结构与 PRD 4.5.1 对齐：requestId、业务 code、可展示 message、data。
"""

from contextvars import ContextVar
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.data = data
        self.headers = headers
        super().__init__(message)


def error_payload(code: str, message: str, data: Any = None) -> dict[str, Any]:
    return {
        "requestId": request_id_ctx.get(),
        "code": code,
        "message": message,
        "data": data,
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.code, exc.message, exc.data),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(str(part) for part in err["loc"][1:]), "message": err["msg"]}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_payload(
                "VALIDATION_FAILED", "提交内容不完整或格式不正确", {"fields": fields}
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # 只返回通用文案与 requestId，不向客户端泄露堆栈或数据库信息。
        return JSONResponse(
            status_code=500,
            content=error_payload("INTERNAL_ERROR", "服务暂时不可用，请稍后重试"),
        )
