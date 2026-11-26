"""Langfuse 可观测服务（可选接入）。

Langfuse 是什么：
    一个开源的大模型应用观测平台，可以记录每一次模型调用的输入输出、
    Token、耗时、成本，还能管理提示词版本、收集人工评分。

为什么只把它当“后端服务（接口）”使用：
    本项目的管理后台已经有一套自己的页面和权限体系。如果直接嵌入
    Langfuse 的网页界面，前端就会被第三方产品绑定，权限、样式、
    数据口径都无法统一。因此这里只调用它的开放接口：
    - 写入：把模型调用、评分上报过去；
    - 读取：拉取指标、提示词版本；
    - 展示：全部由我们自己的管理后台完成。

为什么不用官方 SDK：
    SDK 会额外引入 OpenTelemetry 等一串依赖，而本项目只需要几个固定接口。
    直接用 HTTP 请求，每一步发了什么、收到什么都能在代码里看到，
    测试时也能用假的 HTTP 响应验证，不需要连接外网。

降级原则：
    地址或密钥没有配置时，所有函数直接返回“未配置”，不报错；
    网络失败只记录警告日志，绝不影响用户问答主流程。
    本地数据库（ai_call_logs）始终是事实来源。
"""

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.security import new_id

logger = logging.getLogger("mealmate.langfuse")

# 单次上报最多打包多少个事件。
# 太小会频繁发请求，太大会让单次请求体过大、失败重试成本高。
INGEST_BATCH_SIZE = 50
# 队列里最多堆积多少个事件。超过后丢弃新事件并告警，
# 防止 Langfuse 长时间不可用时把应用内存撑爆。
QUEUE_MAX_SIZE = 2000
# 单条输入输出上报的最大字符数。完整提示词可能上万字，
# 截断后既保留排查所需的主体内容，又避免请求体过大。
MAX_REPORT_CHARS = 8000


class LangfuseError(Exception):
    """Langfuse 接口返回了错误或无法连接。

    调用方通常只记录日志并继续业务流程，不应该把观测失败
    变成用户可见的错误。
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def configured() -> bool:
    """是否已经配置了 Langfuse 地址与密钥。"""
    return settings.langfuse_configured


def _base_url() -> str:
    return settings.langfuse_base_url.strip().rstrip("/")


# ---------------------------------------------------------------------------
# HTTP 客户端
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None


def _http_client() -> httpx.AsyncClient:
    """创建复用的 HTTP 客户端。

    为什么要复用：每次请求都新建客户端会重复建立连接，
    观测是高频旁路操作，连接复用能明显减少握手开销。
    Langfuse 使用 HTTP Basic 认证：用户名是公钥，密码是私钥。
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=_base_url(),
            auth=(settings.langfuse_public_key, settings.langfuse_secret_key),
            timeout=httpx.Timeout(settings.langfuse_timeout_seconds),
            headers={"Content-Type": "application/json"},
        )
    return _client


async def close_client() -> None:
    """应用关闭时释放连接池。"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def request(
    method: str,
    path: str,
    *,
    json_body: Any = None,
    params: dict[str, Any] | None = None,
) -> Any:
    """调用 Langfuse 开放接口并返回 JSON。

    Args:
        method: HTTP 方法，例如 GET、POST、PATCH。
        path: 以 /api/public 开头的路径。
        json_body: 请求体，没有则为 None。
        params: 查询参数。
    Raises:
        LangfuseError: 未配置、网络错误或接口返回非 2xx。
    """
    if not configured():
        raise LangfuseError("尚未配置 Langfuse")
    try:
        response = await _http_client().request(
            method, path, json=json_body, params=params
        )
    except httpx.HTTPError as exc:
        raise LangfuseError(f"连接 Langfuse 失败：{exc}") from exc
    # 207 是批量写入的“部分成功”，也按成功处理，但要把错误明细记下来。
    if response.status_code >= 400:
        raise LangfuseError(
            f"Langfuse 返回 {response.status_code}：{response.text[:500]}",
            status_code=response.status_code,
        )
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise LangfuseError("Langfuse 返回的内容不是合法 JSON") from exc


async def health() -> dict[str, Any]:
    """测试连接：读取当前项目信息。

    `/api/public/projects` 是只读接口，密钥有效时返回项目列表，
    适合做“测试连接”而不产生任何观测数据。
    """
    if not configured():
        return {
            "configured": False,
            "ok": False,
            "message": "未配置 LANGFUSE_BASE_URL / PUBLIC_KEY / SECRET_KEY",
        }
    try:
        data = await request("GET", "/api/public/projects")
    except LangfuseError as exc:
        return {"configured": True, "ok": False, "message": exc.message}
    projects = data.get("data") if isinstance(data, dict) else data
    count = len(projects) if isinstance(projects, list) else 0
    return {
        "configured": True,
        "ok": True,
        "message": f"连接正常，可访问 {count} 个项目",
        "baseUrl": _base_url(),
    }


# ---------------------------------------------------------------------------
# 调用日志上报：先入内存队列，再由后台协程批量发送
# ---------------------------------------------------------------------------

_queue: asyncio.Queue[dict[str, Any] | None] | None = None
_worker: asyncio.Task | None = None


def start_worker() -> None:
    """应用启动时开启后台上报协程。

    为什么不在请求线程里直接 await 上报：
    观测是旁路能力，网络抖动不应该增加用户等待时间。
    放进队列后，用户请求立即返回，后台上报失败只影响观测数据。
    """
    global _queue, _worker
    if not configured() or _queue is not None:
        return
    _queue = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
    _worker = asyncio.create_task(_worker_loop(), name="langfuse-reporter")
    logger.info("Langfuse 上报已启用：%s", _base_url())


async def stop_worker() -> None:
    """应用关闭时尽量把队列里的事件发完，再关闭连接。"""
    global _queue, _worker
    if _queue is not None:
        with contextlib.suppress(asyncio.QueueFull):
            _queue.put_nowait(None)
    if _worker is not None:
        try:
            await asyncio.wait_for(_worker, timeout=5)
        except (TimeoutError, asyncio.CancelledError):
            _worker.cancel()
    _queue = None
    _worker = None
    await close_client()


def enqueue_events(events: list[dict[str, Any]]) -> None:
    """把事件放进上报队列。队列满时丢弃并记录警告。

    这个函数设计成同步的：它只做内存入队，不产生网络等待，
    所以可以安全地在写数据库的同步代码里调用。
    """
    if not events or _queue is None:
        return
    for event in events:
        try:
            _queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Langfuse 上报队列已满，丢弃本次事件")
            return


async def _worker_loop() -> None:
    """后台批量上报循环：攒够一批或等待超过 1 秒就发送。"""
    assert _queue is not None
    batch: list[dict[str, Any]] = []
    while True:
        try:
            item = await asyncio.wait_for(_queue.get(), timeout=1.0)
        except TimeoutError:
            if batch:
                await _flush(batch)
                batch = []
            continue
        if item is None:
            if batch:
                await _flush(batch)
            return
        batch.append(item)
        if len(batch) >= INGEST_BATCH_SIZE:
            await _flush(batch)
            batch = []


async def _flush(batch: list[dict[str, Any]]) -> None:
    """发送一批事件。失败只记日志，不重试，避免故障时无限堆积。"""
    try:
        await request("POST", "/api/public/ingestion", json_body={"batch": batch})
    except LangfuseError as exc:
        logger.warning("Langfuse 上报失败（%s 条）：%s", len(batch), exc.message)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _short(value: Any, limit: int = MAX_REPORT_CHARS) -> str:
    text = "" if value is None else str(value)
    return text[:limit]


def _step_detail(steps: list[Any] | None, names: set[str]) -> str:
    """从调用过程明细里取出某一步的正文。

    为什么从明细里取而不是给每个调用点加参数：
    明细本来就在记录“模型看到了什么、原样返回了什么”，
    再让所有调用点各传一份输入输出，既重复又容易漏。
    """
    for step in steps or []:
        step_name = getattr(step, "step", "")
        if step_name in names:
            detail = getattr(step, "detail", None)
            if detail:
                return str(detail)
    return ""


def build_model_call_events(
    *,
    call_log_id: str,
    request_id: str | None,
    subject_ref: str,
    context_type: str,
    provider_name: str,
    model: str,
    status: str,
    latency_ms: int,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    error_code: str | None,
    error_message: str | None,
    steps: list[Any] | None,
    input_price_per_1k: float = 0,
    output_price_per_1k: float = 0,
    prompt_name: str | None = None,
    prompt_version: int | None = None,
) -> list[dict[str, Any]]:
    """把一次模型调用转换成 Langfuse 的“调用链 + 生成”两个事件。

    为什么一次调用单独一条调用链：
    Langfuse 的调用链（trace）表示一次完整请求，生成（generation）表示链路中的模型调用。
    本项目一次用户提问可能尝试多个模型，如果都塞进同一条调用链，
    失败模型和成功模型的输入输出会互相覆盖。让每次尝试独立成链，
    再用 requestId 元数据把它们串起来，既清晰又不会丢信息。
    """
    trace_id = call_log_id
    generation_id = f"{call_log_id}_gen"
    now = datetime.now(UTC)
    started_at = now - timedelta(milliseconds=max(latency_ms, 0))
    input_text = _short(
        _step_detail(steps, {"model_request", "embedding_request", "http_request"})
    )
    output_text = _short(
        _step_detail(steps, {"model_response", "embedding_response", "model_error"})
    )
    cost_input = prompt_tokens / 1000 * max(input_price_per_1k, 0)
    cost_output = completion_tokens / 1000 * max(output_price_per_1k, 0)

    generation_body: dict[str, Any] = {
        "id": generation_id,
        "traceId": trace_id,
        "name": "model-call",
        "startTime": _iso(started_at),
        "endTime": _iso(now),
        "model": model,
        "input": input_text or None,
        "output": output_text or None,
        "usageDetails": {
            "input": max(prompt_tokens, 0),
            "output": max(completion_tokens, 0),
            "total": max(total_tokens, 0),
        },
        "metadata": {
            "providerName": provider_name,
            "requestId": request_id,
            "subjectRef": subject_ref,
            "contextType": context_type,
            "errorCode": error_code,
            "latencyMs": max(latency_ms, 0),
        },
        "level": "ERROR" if status != "success" else "DEFAULT",
    }
    if cost_input or cost_output:
        # 只有运营填了单价才上报成本，避免把“未配置”误报成 0 成本。
        generation_body["costDetails"] = {
            "input": round(cost_input, 8),
            "output": round(cost_output, 8),
            "total": round(cost_input + cost_output, 8),
        }
    if error_message:
        generation_body["statusMessage"] = _short(error_message, 500)
    if prompt_name:
        generation_body["promptName"] = prompt_name
    if prompt_version:
        generation_body["promptVersion"] = prompt_version

    trace_body: dict[str, Any] = {
        "id": trace_id,
        "name": f"{context_type}-call",
        "timestamp": _iso(started_at),
        "input": input_text or None,
        "output": output_text or None,
        "userId": subject_ref,
        "tags": ["mealmate", context_type],
        "metadata": {
            "requestId": request_id,
            "providerName": provider_name,
            "status": status,
            "errorCode": error_code,
            "callLogId": call_log_id,
        },
    }
    return [
        {
            "id": new_id("lfe"),
            "type": "trace-create",
            "timestamp": _iso(now),
            "body": trace_body,
        },
        {
            "id": new_id("lfe"),
            "type": "generation-create",
            "timestamp": _iso(now),
            "body": generation_body,
        },
    ]


def report_model_call(**kwargs: Any) -> None:
    """构造事件并入队。参数与 build_model_call_events 一致。"""
    if not configured():
        return
    try:
        enqueue_events(build_model_call_events(**kwargs))
    except Exception:  # noqa: BLE001 - 观测失败不能影响业务
        logger.exception("构造 Langfuse 事件失败")


# ---------------------------------------------------------------------------
# 人工评分
# ---------------------------------------------------------------------------


async def push_score(
    *,
    score_id: str,
    call_log_id: str,
    score: int,
    comment: str | None,
    scorer_name: str,
) -> bool:
    """把人工评分推送到 Langfuse。

    使用 `/api/public/scores` 批量评分接口，一次只传一条。
    返回是否成功；失败不抛异常，由调用方记录“未同步”状态即可。
    """
    if not configured():
        return False
    payload = [
        {
            "id": score_id,
            "traceId": call_log_id,
            "name": "human_quality",
            "value": score,
            "dataType": "NUMERIC",
            "comment": comment or f"评分人：{scorer_name}",
        }
    ]
    try:
        await request("POST", "/api/public/scores", json_body=payload)
        return True
    except LangfuseError as exc:
        logger.warning("评分推送 Langfuse 失败：%s", exc.message)
        return False


# ---------------------------------------------------------------------------
# 指标查询
# ---------------------------------------------------------------------------


def _metric_value(row: dict[str, Any], measure: str, aggregation: str) -> float:
    """从指标接口返回的一行里取出某个数值。

    不同版本的 Langfuse 对字段名的拼法略有差异（下划线或驼峰），
    这里按“聚合方式 + 指标名”组合查找，避免升级后页面直接空白。
    """
    candidates = [
        f"{aggregation}_{measure}",
        f"{aggregation}{measure[:1].upper()}{measure[1:]}",
        measure,
    ]
    for key in candidates:
        if key in row and isinstance(row[key], (int, float)):
            return float(row[key])
    lowered = {str(key).lower(): value for key, value in row.items()}
    target = f"{aggregation}{measure}".lower()
    for key, value in lowered.items():
        if key.replace("_", "") == target and isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _time_key(row: dict[str, Any]) -> str:
    """找出按天聚合结果里的时间字段。"""
    for key in ("time_dimension", "timeDimension", "date", "timestamp", "bucket"):
        value = row.get(key)
        if value:
            return str(value)
    return ""


async def _metrics_query(
    metrics: list[dict[str, str]],
    *,
    from_time: datetime,
    to_time: datetime,
    granularity: str | None = None,
    filters: list[dict[str, Any]] | None = None,
    dimensions: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """调用 Langfuse 指标接口并返回 data 数组。

    指标接口要求把查询对象序列化成 JSON 放在 query 参数里。
    时间粒度用 day 时，每行代表一天；不传时返回整体汇总一行。
    """
    query: dict[str, Any] = {
        "view": "observations",
        "metrics": metrics,
        "dimensions": dimensions or [],
        "filters": filters or [],
        "fromTimestamp": _iso(from_time),
        "toTimestamp": _iso(to_time),
    }
    if granularity:
        query["timeDimension"] = {"granularity": granularity}
    # 指标接口要求 query 是一个 JSON 字符串，而不是嵌套的查询参数字典。
    data = await request(
        "GET",
        "/api/public/v2/metrics",
        params={"query": json.dumps(query, ensure_ascii=False)},
    )
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"]
    return []


async def fetch_metrics(days: int = 7) -> dict[str, Any]:
    """汇总看板需要的调用量、延迟、Token、成本、错误率和评分。

    为什么拆成多次查询：
    - 汇总查询：整体数字，不需要按天；
    - 趋势查询：按天分组，用于画柱状图；
    - 错误查询：只统计 level=ERROR 的生成；
    - 评分查询：来自 scores-numeric 视图，属于另一类数据。
    指标接口的过滤条件放在查询里比取回全量再过滤更省流量、更准确。
    """
    if not configured():
        return {
            "configured": False,
            "message": "未配置 Langfuse，先在后端环境变量里填写地址与密钥",
            "rangeDays": days,
            "summary": {},
            "trend": [],
            "scores": {},
        }

    days = max(1, min(days, 30))
    to_time = datetime.now(UTC)
    from_time = to_time - timedelta(days=days)
    base_metrics = [
        {"measure": "count", "aggregation": "count"},
        {"measure": "latency", "aggregation": "avg"},
        {"measure": "latency", "aggregation": "p95"},
        {"measure": "totalTokens", "aggregation": "sum"},
        {"measure": "totalCost", "aggregation": "sum"},
    ]
    try:
        overall = await _metrics_query(
            base_metrics, from_time=from_time, to_time=to_time
        )
        daily = await _metrics_query(
            base_metrics, from_time=from_time, to_time=to_time, granularity="day"
        )
        errors = await _metrics_query(
            [{"measure": "count", "aggregation": "count"}],
            from_time=from_time,
            to_time=to_time,
            granularity="day",
            filters=[
                {"column": "level", "operator": "=", "value": "ERROR", "type": "string"}
            ],
        )
        score_rows = await _metrics_query(
            [
                {"measure": "value", "aggregation": "avg"},
                {"measure": "count", "aggregation": "count"},
            ],
            from_time=from_time,
            to_time=to_time,
        )
    except LangfuseError as exc:
        return {
            "configured": True,
            "message": f"读取 Langfuse 指标失败：{exc.message}",
            "rangeDays": days,
            "summary": {},
            "trend": [],
            "scores": {},
        }

    def summary_of(rows: list[dict[str, Any]]) -> dict[str, float]:
        row = rows[0] if rows else {}
        count = _metric_value(row, "count", "count")
        error_count = 0.0
        # 整体汇总没有按 level 分组，错误数用趋势查询的结果累加。
        for item in errors:
            error_count += _metric_value(item, "count", "count")
        return {
            "calls": count,
            "errors": error_count,
            "errorRate": round(error_count / count, 4) if count else 0,
            "avgLatencyMs": round(_metric_value(row, "latency", "avg"), 1),
            "p95LatencyMs": round(_metric_value(row, "latency", "p95"), 1),
            "totalTokens": int(_metric_value(row, "totalTokens", "sum")),
            "totalCost": round(_metric_value(row, "totalCost", "sum"), 6),
        }

    error_by_day = {
        _time_key(item)[:10]: _metric_value(item, "count", "count") for item in errors
    }
    trend: list[dict[str, Any]] = []
    for item in daily:
        day = _time_key(item)[:10]
        if not day:
            continue
        trend.append(
            {
                "date": day,
                "calls": int(_metric_value(item, "count", "count")),
                "errors": int(error_by_day.get(day, 0)),
                "avgLatencyMs": round(_metric_value(item, "latency", "avg"), 1),
                "totalTokens": int(_metric_value(item, "totalTokens", "sum")),
                "totalCost": round(_metric_value(item, "totalCost", "sum"), 6),
            }
        )
    trend.sort(key=lambda item: item["date"])

    score_row = score_rows[0] if score_rows else {}
    score_count = int(_metric_value(score_row, "count", "count"))
    return {
        "configured": True,
        "message": "",
        "rangeDays": days,
        "summary": summary_of(overall),
        "trend": trend,
        "scores": {
            "count": score_count,
            "average": round(_metric_value(score_row, "value", "avg"), 2),
        },
    }


# ---------------------------------------------------------------------------
# 提示词版本
# ---------------------------------------------------------------------------


def _prompt_path(name: str) -> str:
    """提示词名称可能带点或斜杠，路径里必须完整编码。"""
    return f"/api/public/v2/prompts/{quote(name, safe='')}"


async def fetch_prompt(name: str, *, label: str = "production") -> dict[str, Any]:
    """读取指定标签的提示词。默认 production，即线上正在使用的版本。"""
    return await request("GET", _prompt_path(name), params={"label": label})


async def fetch_prompt_version(name: str, version: int) -> dict[str, Any]:
    """读取指定版本的提示词正文。"""
    return await request(
        "GET", _prompt_path(name), params={"version": version}
    )


async def list_prompt_meta(name: str | None = None) -> list[dict[str, Any]]:
    """列出提示词名称及其版本号、标签。"""
    params = {"limit": 100}
    if name:
        params["name"] = name
    data = await request("GET", "/api/public/v2/prompts", params=params)
    rows = data.get("data") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


async def create_prompt(
    name: str,
    content: str,
    *,
    labels: list[str] | None = None,
    commit_message: str | None = None,
) -> dict[str, Any]:
    """创建提示词的新版本。

    Langfuse 的提示词版本不可修改：同名再提交一次就是新版本。
    这样历史版本永远可追溯，回滚只需要把 production 标签移到旧版本。
    """
    body: dict[str, Any] = {
        "name": name,
        "type": "text",
        "prompt": content,
        "labels": labels or ["production"],
    }
    if commit_message:
        body["commitMessage"] = commit_message
    return await request("POST", "/api/public/v2/prompts", json_body=body)
