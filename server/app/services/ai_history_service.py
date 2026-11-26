"""AI 对话历史：会话、消息、摘要与本地记录合并。

这个文件只负责“历史怎么存、怎么取、怎么清理”，不负责调用大模型。
调用模型做摘要压缩的逻辑放在 ai_service.py，原因是：
1. 模型调用需要复用网关的超时、错误码、调用日志和过程明细；
2. 历史服务保持纯数据操作，测试时不需要模拟模型，职责更清晰。

存储分层：
- Redis：只放最近 30 分钟的会话快照，每次写入都重新计时（滑动过期）。
  作用是让多轮对话读取足够快，并且游客不落库也能连续追问。
- PostgreSQL / SQLite：登录用户的会话、消息、摘要长期保存（默认 30 天）。
- 手机本地：游客的长期记录由 Flutter 的 SharedPreferences 保存，默认 7 天；
  登录时调用同步接口合并上云，按“客户端消息编号”去重。

为什么游客不写数据库：
产品定位是“本地为主 + 登录后合并上云”。游客没有稳定身份，
如果服务端也保存，会产生大量无法归属、无法跨设备找回的数据，
还要额外设计游客身份合并规则；不如只依赖 Redis 的 30 分钟会话
和手机本地存储，登录后再一次性合并。

为什么 Redis 也要存登录用户的会话：
数据库适合长期保存，但每次多轮对话都查两张表、再按时间排序，
高频问答下会多出不必要的数据库压力；Redis 快照让热点会话在内存里完成，
数据库只在需要长期保存或 Redis 失效时兜底。
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import new_id
from app.db.models import AIConversation, AIMessage, User
from app.schemas import AIChatMessage, AISyncRequest
from app.services import cache
from app.utils.time import as_utc, now_utc

logger = logging.getLogger("mealmate.ai_history")

# 单个会话最多在内存/Redis 中保留多少条消息。
# 正常对话 30 分钟无操作就会开新会话，很难达到这个数量；
# 设上限是为了防御异常客户端或脚本刷消息，避免 Redis 单键无限增长。
MAX_STORED_MESSAGES = 500

# Redis 键前缀。统一前缀便于运维用 SCAN 观察、按前缀清理。
REDIS_KEY_PREFIX = "ai:chat:"


def _redis_key(conversation_id: str) -> str:
    return f"{REDIS_KEY_PREFIX}{conversation_id}"


def estimate_tokens(text: str) -> int:
    """粗略估算一段文字的 token 数。

    为什么不调用供应商的 tokenizer：
    1. 每家模型的分词器不同，项目会切换模型，无法保证一致；
    2. 引入分词库会增加依赖和内存占用，而这里只需要“是否达到 60%”的判断，
       不需要精确到个位；
    3. 估算偏保守即可：宁可提前压缩，也不要等超限报错。

    估算规则（业界常用的快速近似）：
    - 中文、日文、韩文等全角字符：约 1 个字符 = 1 token；
    - 英文、数字、半角符号：约 4 个字符 = 1 token。
    这个比例对常见中英文模型足够接近，误差在可接受范围。
    """
    if not text:
        return 0
    wide = 0
    for char in text:
        code = ord(char)
        # 常用汉字、中文标点、全角符号都按 1 token 计。
        if (
            0x4E00 <= code <= 0x9FFF  # 中日韩统一表意文字
            or 0x3000 <= code <= 0x303F  # 中文标点
            or 0xFF00 <= code <= 0xFFEF  # 全角字符
        ):
            wide += 1
    other = len(text) - wide
    return max(1, wide + math.ceil(other / 4))


def message_tokens(content: str) -> int:
    """单条消息的估算 token。

    除了正文，角色标记、分隔符也会占用少量 token，
    这里统一加 4，避免大量短消息被明显低估。
    """
    return estimate_tokens(content) + 4


@dataclass
class HistoryMessage:
    """历史消息在服务内部的标准结构。

    为什么不用数据库模型直接传递：
    游客消息只存在于 Redis，没有数据库行；用同一个轻量结构表示，
    上层拼提示词、算 token、做压缩时不需要关心消息来自哪里。
    """

    client_message_id: str
    role: str
    content: str
    created_at: datetime
    token_estimate: int = 0

    def __post_init__(self) -> None:
        if not self.token_estimate:
            self.token_estimate = message_tokens(self.content)
        self.created_at = as_utc(self.created_at)


@dataclass
class ConversationState:
    """一段会话的完整内存快照。"""

    conversation_id: str
    subject_ref: str
    user_id: str | None
    context_type: str
    summary: str
    summary_message_count: int
    messages: list[HistoryMessage] = field(default_factory=list)
    last_active_at: datetime = field(default_factory=now_utc)
    created_at: datetime = field(default_factory=now_utc)
    # 是否本次新建。调用方据此决定是否要在提示词里忽略旧历史。
    is_new: bool = False

    def window(self, limit: int | None = None) -> list[HistoryMessage]:
        """最近若干条消息。

        为什么总是取“尾部”：
        对话按时间正序保存，越靠后越接近当前问题。
        只取最近 8 条既能让模型理解指代，又不会让提示词无限增长。
        """
        size = limit or settings.ai_history_window_messages
        return self.messages[-size:]

    def total_tokens(self) -> int:
        """整段会话的估算 token（摘要 + 全部消息）。

        压缩阈值用这个值判断：它代表“如果所有历史都塞进提示词”的规模。
        即使实际只带最近 8 条，旧消息迟早需要被压缩成摘要，
        提前在 60% 时处理，可以避免压缩请求本身也超限。
        """
        total = estimate_tokens(self.summary)
        for item in self.messages:
            total += item.token_estimate
        return total


def _dump_state(state: ConversationState) -> dict[str, Any]:
    """把会话快照序列化成 Redis 可存的 JSON。"""
    return {
        "conversationId": state.conversation_id,
        "subjectRef": state.subject_ref,
        "userId": state.user_id,
        "contextType": state.context_type,
        "summary": state.summary,
        "summaryMessageCount": state.summary_message_count,
        "lastActiveAt": state.last_active_at.isoformat(),
        "createdAt": state.created_at.isoformat(),
        "messages": [
            {
                "clientMessageId": item.client_message_id,
                "role": item.role,
                "content": item.content,
                "createdAt": item.created_at.isoformat(),
            }
            for item in state.messages
        ],
    }


def _parse_time(value: Any, fallback: datetime | None = None) -> datetime:
    """解析 Redis 中的时间字符串，解析失败时回退到给定时间。

    为什么要容错：Redis 里的数据是缓存，不是事实来源；
    格式异常时应该当作缓存未命中重新从数据库加载，而不是让整个问答失败。
    """
    if isinstance(value, str) and value:
        try:
            return as_utc(datetime.fromisoformat(value))
        except ValueError:
            pass
    return fallback or now_utc()


def _state_from_dump(
    data: dict[str, Any] | None, subject_ref: str
) -> ConversationState | None:
    """把 Redis 快照还原成会话状态，并校验归属。

    归属校验不能省：会话编号会返回给客户端，
    如果只按编号读取而不校验 subjectRef，别人拿到编号就能读到他人的对话。
    """
    if not isinstance(data, dict):
        return None
    if data.get("subjectRef") != subject_ref:
        return None
    conversation_id = str(data.get("conversationId") or "")
    if not conversation_id:
        return None
    messages: list[HistoryMessage] = []
    raw_messages = data.get("messages")
    if isinstance(raw_messages, list):
        for raw in raw_messages:
            if not isinstance(raw, dict):
                continue
            content = str(raw.get("content") or "")
            if not content:
                continue
            messages.append(
                HistoryMessage(
                    client_message_id=str(raw.get("clientMessageId") or ""),
                    role=str(raw.get("role") or "user"),
                    content=content,
                    created_at=_parse_time(raw.get("createdAt")),
                )
            )
    return ConversationState(
        conversation_id=conversation_id,
        subject_ref=subject_ref,
        user_id=data.get("userId") or None,
        context_type=str(data.get("contextType") or "home"),
        summary=str(data.get("summary") or ""),
        summary_message_count=int(data.get("summaryMessageCount") or 0),
        messages=messages,
        last_active_at=_parse_time(data.get("lastActiveAt")),
        created_at=_parse_time(data.get("createdAt")),
    )


async def save_state(state: ConversationState) -> None:
    """把会话快照写入 Redis，并重置过期时间。

    这里就是“滑动过期”的实现：
    每次有新消息都重新 SET 并带上 30 分钟过期时间，
    用户持续对话时键不会消失；停止操作 30 分钟后自动删除。
    Redis 不可用时 cache.set_json 内部会静默跳过，
    登录用户仍然可以通过数据库继续多轮对话。
    """
    await cache.set_json(
        _redis_key(state.conversation_id),
        _dump_state(state),
        settings.ai_history_redis_ttl_seconds,
    )


async def drop_state_cache(conversation_id: str) -> None:
    """删除 Redis 快照。

    本地记录同步上云、批量写入数据库之后必须调用，
    否则下一次读取会拿到旧快照，看不到刚同步进来的消息。
    """
    await cache.delete_key(_redis_key(conversation_id))


def _is_idle_expired(state: ConversationState) -> bool:
    """判断会话是否已经超过“无操作自动开新会话”的时间。"""
    idle = now_utc() - as_utc(state.last_active_at)
    return idle > timedelta(minutes=settings.ai_conversation_idle_minutes)


async def _load_from_db(
    db: AsyncSession, conversation_id: str, user: User
) -> ConversationState | None:
    """从数据库加载登录用户的会话。

    只允许读取属于当前用户的会话：
    会话编号可能被猜测或泄露，必须用 user_id 再做一次归属校验。
    """
    row = await db.get(AIConversation, conversation_id)
    if row is None or row.user_id != user.id:
        return None
    rows = (
        await db.scalars(
            select(AIMessage)
            .where(AIMessage.conversation_id == conversation_id)
            .order_by(AIMessage.created_at, AIMessage.id)
            .limit(MAX_STORED_MESSAGES)
        )
    ).all()
    state = ConversationState(
        conversation_id=row.id,
        subject_ref=row.subject_ref,
        user_id=row.user_id,
        context_type=row.context_type,
        summary=row.summary or "",
        summary_message_count=row.summary_message_count,
        messages=[
            HistoryMessage(
                client_message_id=item.client_message_id,
                role=item.role,
                content=item.content,
                created_at=item.created_at,
                token_estimate=item.token_estimate,
            )
            for item in rows
        ],
        last_active_at=row.last_active_at,
        created_at=row.created_at,
    )
    # 数据库读出来顺手写回 Redis：下一次请求直接走内存，减少数据库查询。
    await save_state(state)
    return state


async def load_conversation(
    db: AsyncSession,
    *,
    conversation_id: str,
    subject_ref: str,
    user: User | None,
) -> ConversationState | None:
    """按编号加载会话：登录用户先校验归属，再优先读 Redis。

    为什么登录用户不能直接相信 Redis：
    Redis 是缓存，写入发生在数据库事务提交之前；
    如果某次请求在提交前异常回滚，缓存里可能留下一段数据库并不存在的会话。
    先查一次主键确认会话真实存在且属于当前用户，既防止读到脏缓存，
    也防止有人拿到别人的会话编号越权读取。主键查询成本很低，
    确认后再走 Redis 快照，仍然省掉了消息表的排序查询。

    游客没有数据库记录，只能依赖 Redis；读不到就按新会话处理。
    """
    if user is not None:
        row = await db.get(AIConversation, conversation_id)
        if row is None or row.user_id != user.id:
            return None

    cached = _state_from_dump(
        await cache.get_json(_redis_key(conversation_id)), subject_ref
    )
    if cached is not None:
        return cached
    if user is not None:
        return await _load_from_db(db, conversation_id, user)
    return None


async def create_conversation(
    db: AsyncSession,
    *,
    subject_ref: str,
    user: User | None,
    context_type: str,
    first_message: str,
    client_conversation_id: str | None = None,
    created_at: datetime | None = None,
) -> ConversationState:
    """新建一段会话。

    登录用户立刻写一行会话记录（消息在后续 append 时写入）；
    游客不落库，只把内存状态写进 Redis。
    """
    conversation_id = new_id("conv")
    now = now_utc()
    state = ConversationState(
        conversation_id=conversation_id,
        subject_ref=subject_ref,
        user_id=user.id if user else None,
        context_type=context_type,
        summary="",
        summary_message_count=0,
        last_active_at=now,
        created_at=created_at or now,
        is_new=True,
    )
    if user is not None:
        db.add(
            AIConversation(
                id=conversation_id,
                subject_ref=subject_ref,
                user_id=user.id,
                client_conversation_id=client_conversation_id,
                context_type=context_type,
                title=(first_message or "").strip()[:30],
                summary=None,
                summary_message_count=0,
                message_count=0,
                last_active_at=now,
                created_at=created_at or now,
                updated_at=now,
            )
        )
        await db.flush()
    await save_state(state)
    return state


def _seed_from_client_history(
    state: ConversationState, history: list[AIChatMessage]
) -> None:
    """用客户端带来的历史初始化会话。

    适用场景：
    1. 游客且 Redis 不可用：服务端没有历史，只能相信客户端带的最近 8 条；
    2. 旧版本客户端：还没有会话编号，只带历史提问。
    每条消息生成一个临时客户端编号，保证同一次会话内可区分。
    """
    for item in history[-settings.ai_history_window_messages :]:
        content = item.content.strip()
        if not content:
            continue
        state.messages.append(
            HistoryMessage(
                client_message_id=new_id("cm"),
                role=item.role,
                content=content,
                created_at=now_utc(),
            )
        )


async def resolve_conversation(
    db: AsyncSession,
    *,
    subject_ref: str,
    user: User | None,
    conversation_id: str | None,
    context_type: str,
    message: str,
    fallback_history: list[AIChatMessage],
) -> ConversationState:
    """拿到本次问答应该使用的会话。

    规则：
    - 有编号且能读取、且未超过 30 分钟空闲：复用原会话；
    - 有编号但读取不到（Redis 过期、数据库已清理）或已空闲超时：
      开新会话，并且不再带入客户端旧历史——用户已经中断 30 分钟，
      按产品定义这是一段新对话；
    - 没有编号：开新会话；如果客户端带了历史（游客 / 旧客户端），
      把它作为新会话的初始窗口，保证“那换成鸡肉呢”仍然能理解。
    """
    seed_history = False
    if conversation_id:
        state = await load_conversation(
            db,
            conversation_id=conversation_id,
            subject_ref=subject_ref,
            user=user,
        )
        if state is not None:
            if not _is_idle_expired(state):
                state.is_new = False
                return state
            # 已超过 30 分钟空闲：按产品定义开始新会话，
            # 不再带入客户端旧历史，避免旧话题延续到新会话。
        else:
            # 编号读不到：Redis 过期或 Redis 不可用（游客）。
            # 此时客户端带来的最近历史是唯一可用的上下文，需要接上。
            seed_history = True
    else:
        # 首次提问或旧客户端没有会话编号，客户端历史就是全部上下文。
        seed_history = True

    state = await create_conversation(
        db,
        subject_ref=subject_ref,
        user=user,
        context_type=context_type,
        first_message=message,
    )
    if fallback_history and seed_history:
        _seed_from_client_history(state, fallback_history)
        await save_state(state)
    return state


async def append_turn(
    db: AsyncSession,
    state: ConversationState,
    *,
    role: str,
    content: str,
    client_message_id: str | None = None,
    created_at: datetime | None = None,
) -> HistoryMessage:
    """往会话里追加一条消息（用户问题或助手回答）。

    幂等：同一个客户端消息编号在同一个会话里只写一次。
    网络重试（客户端没收到响应又重发）时，不会在历史里出现两条相同提问。

    返回值是最终落库/入缓存的那条消息，
    调用方需要把它返回的编号告诉客户端，本地记录才能和服务端对上。
    """
    text = (content or "").strip()
    message_id = (client_message_id or "").strip() or new_id("cm")
    # 同步接口允许较长内容，这里统一截断，避免单条消息异常巨大拖垮提示词。
    text = text[:8000]
    moment = as_utc(created_at or now_utc())

    # 先查内存快照，命中就不必再查数据库。
    for existing in state.messages:
        if existing.client_message_id == message_id:
            return existing

    if state.user_id is not None:
        existing_row = await db.scalar(
            select(AIMessage).where(
                AIMessage.conversation_id == state.conversation_id,
                AIMessage.client_message_id == message_id,
            )
        )
        if existing_row is not None:
            message = HistoryMessage(
                client_message_id=existing_row.client_message_id,
                role=existing_row.role,
                content=existing_row.content,
                created_at=existing_row.created_at,
                token_estimate=existing_row.token_estimate,
            )
            state.messages.append(message)
            return message

    message = HistoryMessage(
        client_message_id=message_id,
        role=role,
        content=text,
        created_at=moment,
    )
    state.messages.append(message)
    if len(state.messages) > MAX_STORED_MESSAGES:
        # 超出上限时丢掉最旧的一部分。正常对话不会触发；
        # 真触发时同步下调“已摘要条数”，保证压缩指针不会越界。
        drop_count = len(state.messages) - MAX_STORED_MESSAGES
        state.messages = state.messages[drop_count:]
        state.summary_message_count = max(0, state.summary_message_count - drop_count)

    if state.user_id is not None:
        db.add(
            AIMessage(
                id=new_id("aim"),
                conversation_id=state.conversation_id,
                user_id=state.user_id,
                client_message_id=message.client_message_id,
                role=message.role,
                content=message.content,
                token_estimate=message.token_estimate,
                created_at=moment,
            )
        )
        row = await db.get(AIConversation, state.conversation_id)
        if row is not None:
            row.message_count += 1
            row.last_active_at = moment
            row.updated_at = now_utc()
        await db.flush()

    state.last_active_at = moment
    await save_state(state)
    return message


async def save_summary(
    db: AsyncSession,
    state: ConversationState,
    *,
    summary: str,
    summary_message_count: int,
) -> None:
    """保存压缩后的摘要。

    只有压缩成功才调用；压缩失败时调用方什么都不做，
    原摘要、原消息保持不变，这就是需求里的“压缩失败回滚”。
    """
    state.summary = summary.strip()
    state.summary_message_count = max(0, min(summary_message_count, len(state.messages)))
    if state.user_id is not None:
        row = await db.get(AIConversation, state.conversation_id)
        if row is not None:
            row.summary = state.summary or None
            row.summary_message_count = state.summary_message_count
            row.updated_at = now_utc()
            await db.flush()
    await save_state(state)


def pending_old_messages(state: ConversationState) -> list[HistoryMessage]:
    """返回“超出最近窗口、且还没有被摘要”的旧消息。

    例：会话有 12 条消息，窗口 8 条，已摘要 0 条
    → 返回前 4 条（索引 0 到 4）。
    下一次触发压缩时，summary_message_count 会前进，只处理新增部分。
    """
    window = settings.ai_history_window_messages
    old_end = max(len(state.messages) - window, 0)
    start = min(state.summary_message_count, old_end)
    return state.messages[start:old_end]


def should_compress(state: ConversationState, context_window_tokens: int) -> bool:
    """判断是否需要触发历史压缩。

    两个条件同时满足才压缩：
    1. 整段会话估算 token 达到模型窗口的 60%；
    2. 确实存在“窗口之外且未摘要”的旧消息。
    如果只有最近几条消息就超过 60%，说明是系统提示词或菜谱目录本身太大，
    压缩历史没有意义，交给上下文超限兜底处理。
    """
    if state.total_tokens() < int(
        context_window_tokens * settings.ai_history_compress_ratio
    ):
        return False
    return bool(pending_old_messages(state))


async def sync_conversations(
    db: AsyncSession, user: User, body: AISyncRequest
) -> dict[str, Any]:
    """把手机本地的会话记录合并到云端（登录时调用）。

    设计要点：
    1. 幂等：用“用户编号 + 本地会话编号”找到已合并过的会话，
       重复登录、网络重试不会产生重复会话；
    2. 去重：消息用“会话编号 + 客户端消息编号”判重，
       在线聊天已经写入服务端的消息不会被重复插入；
    3. 不改时间顺序：按客户端提交的顺序写入，保留原始发生时间；
    4. 返回映射：本地会话编号 → 云端会话编号，
       客户端据此把本地会话改用云端编号，后续聊天才能接上云端历史。
    """
    mapping: list[dict[str, Any]] = []
    inserted_total = 0
    now = now_utc()

    for item in body.conversations:
        if not item.messages:
            continue
        existing = await db.scalar(
            select(AIConversation).where(
                AIConversation.user_id == user.id,
                AIConversation.client_conversation_id == item.client_conversation_id,
            )
        )
        first_user_message = next(
            (m.content for m in item.messages if m.role == "user"), ""
        )
        if existing is None:
            last_time = _parse_time(
                item.updated_at.isoformat() if item.updated_at else None,
                fallback=now,
            )
            existing = AIConversation(
                id=new_id("conv"),
                # 同步上来的记录属于登录用户，subject_ref 用 user: 前缀，
                # 与在线问答保持一致，后续读取时归属校验能直接通过。
                subject_ref=f"user:{user.id}",
                user_id=user.id,
                client_conversation_id=item.client_conversation_id,
                context_type=item.context_type,
                title=(first_user_message or "").strip()[:30],
                summary=None,
                summary_message_count=0,
                message_count=0,
                last_active_at=last_time,
                created_at=_parse_time(
                    item.created_at.isoformat() if item.created_at else None,
                    fallback=last_time,
                ),
                updated_at=now,
            )
            db.add(existing)
            await db.flush()
        else:
            # 同步只补消息，不改写已有标题和摘要。
            existing.last_active_at = max(
                as_utc(existing.last_active_at),
                _parse_time(
                    item.updated_at.isoformat() if item.updated_at else None,
                    fallback=now,
                ),
            )
            existing.updated_at = now

        existing_ids = set(
            (
                await db.scalars(
                    select(AIMessage.client_message_id).where(
                        AIMessage.conversation_id == existing.id
                    )
                )
            ).all()
        )
        inserted = 0
        for message in item.messages:
            if message.client_message_id in existing_ids:
                continue
            created = _parse_time(
                message.created_at.isoformat() if message.created_at else None,
                fallback=existing.last_active_at,
            )
            db.add(
                AIMessage(
                    id=new_id("aim"),
                    conversation_id=existing.id,
                    user_id=user.id,
                    client_message_id=message.client_message_id,
                    role=message.role,
                    content=message.content.strip()[:8000],
                    token_estimate=message_tokens(message.content),
                    created_at=created,
                )
            )
            existing_ids.add(message.client_message_id)
            inserted += 1
        if inserted:
            existing.message_count += inserted
            inserted_total += inserted
        # 同步后旧缓存可能缺少新消息，删除即可，下次读取会从数据库重建。
        await drop_state_cache(existing.id)
        mapping.append(
            {
                "clientConversationId": item.client_conversation_id,
                "conversationId": existing.id,
                "insertedMessages": inserted,
            }
        )

    await db.commit()
    return {"conversations": mapping, "insertedMessages": inserted_total}


async def purge_expired_conversations(
    db: AsyncSession, retention_days: int | None = None
) -> int:
    """删除超过保留期的会话及其消息，返回删除的会话数。

    产品约定登录用户会话保留 30 天；
    消息必须和会话一起删除，否则会留下没有归属的孤儿数据。
    这里做物理删除：产品没有提供“恢复已删除对话”的能力，
    软删除只会让数据越积越多，还要在每次查询时过滤。
    """
    days = retention_days or settings.ai_conversation_retention_days
    cutoff = now_utc() - timedelta(days=days)
    conversation_ids = (
        await db.scalars(
            select(AIConversation.id).where(AIConversation.last_active_at < cutoff)
        )
    ).all()
    if not conversation_ids:
        return 0
    await db.execute(
        delete(AIMessage).where(AIMessage.conversation_id.in_(conversation_ids))
    )
    await db.execute(
        delete(AIConversation).where(AIConversation.id.in_(conversation_ids))
    )
    await db.commit()
    for conversation_id in conversation_ids:
        await drop_state_cache(conversation_id)
    return len(conversation_ids)


async def purge_orphan_conversations(db: AsyncSession) -> int:
    """删除所属用户已经不存在的会话。

    账号删除功能将来上线时，应该主动调用 delete_user_ai_data；
    这里再按“用户不存在”兜底清理一次，防止遗漏或手工删库留下孤儿数据。
    """
    user_ids = select(User.id)
    orphan_ids = (
        await db.scalars(
            select(AIConversation.id).where(
                AIConversation.user_id.is_not(None),
                AIConversation.user_id.not_in(user_ids),
            )
        )
    ).all()
    if not orphan_ids:
        return 0
    await db.execute(delete(AIMessage).where(AIMessage.conversation_id.in_(orphan_ids)))
    await db.execute(delete(AIConversation).where(AIConversation.id.in_(orphan_ids)))
    await db.commit()
    for conversation_id in orphan_ids:
        await drop_state_cache(conversation_id)
    return len(orphan_ids)


async def delete_user_ai_data(db: AsyncSession, user_id: str) -> dict[str, int]:
    """删除某个用户的全部 AI 对话数据（删除账号时调用）。

    注意：AI 调用日志（ai_call_logs / ai_call_traces）不在这里删除。
    日志是审计与成本核算依据，即使账号删除也要保留到 180 天自然到期，
    这是需求里明确的“聊天记录跟着账号删，日志不跟着删”。
    """
    conversation_ids = (
        await db.scalars(
            select(AIConversation.id).where(AIConversation.user_id == user_id)
        )
    ).all()
    message_count = 0
    if conversation_ids:
        result = await db.execute(
            delete(AIMessage).where(AIMessage.conversation_id.in_(conversation_ids))
        )
        message_count = int(result.rowcount or 0)
        await db.execute(
            delete(AIConversation).where(AIConversation.id.in_(conversation_ids))
        )
        await db.commit()
        for conversation_id in conversation_ids:
            await drop_state_cache(conversation_id)
    return {"conversations": len(conversation_ids), "messages": message_count}
