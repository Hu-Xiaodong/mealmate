"""文本切片器：把一篇文档切成适合向量检索的片段。

为什么必须切片，不能整篇文档直接生成一个向量：
1. 嵌入模型有输入长度上限，长文档会被截断，后半部分内容直接丢失；
2. 一个向量只能表达一个“平均语义”，整篇文档包含多个主题时，
   检索精度会明显下降；
3. 回答问题时需要给出来源，片段越小越容易定位到具体章节。

切片策略（面向 Markdown 知识文档）：
1. 先按标题分节，保留“文档标题 / 一级标题 / 二级标题”的层级路径；
2. 节内按空行分段，再把相邻段落累积到目标长度；
3. 相邻片段保留约 80 字重叠，避免一句话被切断后两边都检索不到；
4. 每个片段开头补一行上下文头（文档标题 + 章节路径），
   因为片段脱离原文后，单看正文可能不知道在讲哪一部分。

这些都是“字符数”而不是“模型 token 数”的近似值：
中文一个汉字通常约等于一个 token，英文一个单词约等于一到两个 token。
用字符数控制切片简单、稳定、无需依赖具体模型的分词器，
误差可以通过调整 chunk_size 吸收。
"""

import re
from dataclasses import dataclass, field
from typing import Any

# 默认目标长度：400 字左右。经验上 300 到 800 字既能保留完整语义，
# 又不会让一个片段混杂太多主题。
DEFAULT_TARGET_CHARS = 400
# 单个片段允许的最大长度。超过这个值时，即使段落还没结束也会强制切开。
DEFAULT_MAX_CHARS = 800
# 相邻片段的重叠长度。
DEFAULT_OVERLAP_CHARS = 80

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
# 句子结束标点，用于超长段落的安全切分。
_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]*[。！？!?；;\n]?")


@dataclass
class TextChunk:
    """一个切片及其定位信息。

    content 已经带上上下文头，会直接用于生成向量和展示；
    metadata 只保存结构化定位信息，便于前端或后续问答引用来源。
    """

    content: str
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数。

    规则：一个汉字算一个，一个连续的英文或数字串算一个。
    这比调用真实分词器便宜得多，也不会因为更换模型而失效；
    它的用途是展示与统计，不参与计费。
    """
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    words = len(_WORD_RE.findall(_CJK_RE.sub(" ", text)))
    return cjk + words


def _split_sections(text: str) -> list[dict[str, Any]]:
    """按 Markdown 标题把正文拆成若干节。

    标题栈用于生成“一级 / 二级 / 三级”这样的路径：
    遇到同级或更高级标题时先弹出旧标题，再把新标题压栈。
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    current_heading = ""
    current_path = ""
    section_index = 0
    buffer: list[str] = []

    def flush() -> None:
        nonlocal section_index
        body = "\n".join(buffer).strip()
        if not body:
            return
        sections.append(
            {
                "heading": current_heading,
                "heading_path": current_path,
                "section_index": section_index,
                "body": body,
            }
        )
        section_index += 1

    for raw_line in lines:
        line = raw_line.rstrip()
        match = _HEADING_RE.match(line.strip())
        if match is None:
            buffer.append(line)
            continue
        flush()
        buffer.clear()
        level = len(match.group(1))
        title = match.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        current_heading = title
        current_path = " / ".join(item[1] for item in stack)
    flush()
    return sections


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """把超过最大长度的段落按句子边界切开。

    找不到句号时退化为按固定长度硬切，保证不会产生超长片段。
    """
    if len(paragraph) <= max_chars:
        return [paragraph]
    pieces: list[str] = []
    buffer = ""
    for sentence in _SENTENCE_RE.findall(paragraph):
        if not sentence:
            continue
        if buffer and len(buffer) + len(sentence) > max_chars:
            pieces.append(buffer.strip())
            buffer = sentence
        else:
            buffer += sentence
        while len(buffer) > max_chars:
            pieces.append(buffer[:max_chars].strip())
            buffer = buffer[max_chars:]
    if buffer.strip():
        pieces.append(buffer.strip())
    return [piece for piece in pieces if piece]


def _pack_paragraphs(
    paragraphs: list[str],
    *,
    target_chars: int,
    max_chars: int,
    overlap_chars: int,
) -> list[str]:
    """把段落累积成不超过最大长度的片段，并在片段之间保留重叠。"""
    packed: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        for piece in _split_long_paragraph(paragraph, max_chars):
            if not buffer:
                buffer = piece
                continue
            merged = f"{buffer}\n\n{piece}"
            # 达到目标长度后，只要再加当前段落会超过上限，就先输出当前片段。
            if len(buffer) >= target_chars and len(merged) > max_chars:
                packed.append(buffer)
                tail = buffer[-overlap_chars:] if overlap_chars > 0 else ""
                buffer = f"{tail}\n\n{piece}" if tail else piece
                # 重叠后仍可能超长，交给下一轮或强制切分处理。
                if len(buffer) > max_chars:
                    trimmed = buffer[:max_chars]
                    packed.append(trimmed)
                    buffer = buffer[max_chars:]
                continue
            if len(merged) > max_chars:
                packed.append(buffer)
                tail = buffer[-overlap_chars:] if overlap_chars > 0 else ""
                buffer = f"{tail}\n\n{piece}" if tail else piece
                continue
            buffer = merged
    if buffer.strip():
        packed.append(buffer.strip())
    return [item for item in packed if item.strip()]


def _context_header(title: str, heading_path: str) -> str:
    """生成片段开头的上下文头。

    标题路径过长时只保留最后两级，避免上下文头本身占用太多字符。
    """
    parts = [part for part in (title.strip(), heading_path.strip()) if part]
    if not parts:
        return ""
    compact: list[str] = []
    for part in parts:
        if " / " in part:
            levels = [level.strip() for level in part.split(" / ") if level.strip()]
            part = " / ".join(levels[-2:])
        compact.append(part[:60])
    return f"【{'｜'.join(compact)}】\n"


def split_document(
    text: str,
    *,
    title: str = "",
    target_chars: int = DEFAULT_TARGET_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[TextChunk]:
    """把文档正文切成片段。

    Args:
        text: 文档正文（Markdown 或纯文本）。
        title: 文档标题，会写入每个片段的上下文头。
        target_chars: 目标片段长度，达到后开始考虑换片。
        max_chars: 片段最大长度，硬性上限。
        overlap_chars: 相邻片段的重叠字符数。
    Returns:
        TextChunk 列表，content 已包含上下文头，metadata 记录章节定位信息。
    Why:
        切片规则集中在一个纯函数里，方便单元测试，也方便以后调整参数后
        新建索引版本重新生成，不影响已有数据。
    """
    if max_chars <= 0:
        raise ValueError("max_chars 必须大于 0")
    if target_chars <= 0 or target_chars > max_chars:
        target_chars = min(DEFAULT_TARGET_CHARS, max_chars)
    if overlap_chars < 0:
        overlap_chars = 0

    chunks: list[TextChunk] = []
    for section in _split_sections(text):
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", section["body"])
            if paragraph.strip()
        ]
        pieces = _pack_paragraphs(
            paragraphs,
            target_chars=target_chars,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )
        header = _context_header(title, section["heading_path"])
        for piece in pieces:
            content = f"{header}{piece}".strip()
            if not content:
                continue
            chunks.append(
                TextChunk(
                    content=content,
                    token_count=estimate_tokens(content),
                    metadata={
                        "heading": section["heading"],
                        "headingPath": section["heading_path"],
                        "sectionIndex": section["section_index"],
                    },
                )
            )
    return chunks
