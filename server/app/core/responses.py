from typing import Any

from app.core.errors import request_id_ctx


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    return {
        "requestId": request_id_ctx.get(),
        "code": 0,
        "message": message,
        "data": data,
    }
