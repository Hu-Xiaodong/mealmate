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

图片怎么处理：
- 切片 content 保留 `![说明](地址)` 图片标记，管理后台预览时才能把图片渲染出来；
- 统计 token 数、生成向量前用 strip_media_markup 去掉图片标记，
  因为图片地址对语义检索没有帮助，还会浪费嵌入模型的输入长度。

这些都是“字符数”而不是“模型 token 数”的近似值：
中文一个汉字通常约等于一个 token，英文一个单词约等于一到两个 token。
用字符数控制切片简单、稳定、无需依赖具体模型的分词器，
误差可以通过调整 chunk_size 吸收。

调用关系（谁在用这个文件）：
1. app/services/kb_service.py 的 _split_text：知识库文档“上传 / 重新切片”时，
   调用 split_document 把正文切成片段，写入 kb_draft_chunks（切片列表）；
   运营点“建立索引”后，这些片段才由 embedding_service 生成向量并写入 kb_chunks；
2. server/tests/test_kb.py：单元测试直接调用 split_document，
   验证“按标题分节、保留上下文头、相邻片段有重叠”等行为。

因此本文件只做纯文本处理（不连数据库、不发网络请求），
这样既能独立测试切片逻辑，也方便以后替换实现而不影响索引流程。
"""

import re
from dataclasses import dataclass, field
from typing import Any

# 默认目标长度：400 字左右。经验上 300 到 800 字既能保留完整语义，
# 又不会让一个片段混杂太多主题。
# 注意：知识库切片流程（kb_service._split_text）会传入“索引版本”里的 chunk_size
# 作为 target_chars，并把 max_chars 设为 chunk_size 的两倍；
# 这里的默认值主要用于单元测试或没有显式传参的调用。
DEFAULT_TARGET_CHARS = 400
# 单个片段允许的最大长度。超过这个值时，即使段落还没结束也会强制切开。
# 它是“硬上限”，保证每个片段都不会超过嵌入模型的输入长度限制。
DEFAULT_MAX_CHARS = 800
# 相邻片段的重叠长度（默认 80 字）。
# 作用：一句话恰好被切在两个片段之间时，前后两个片段都包含这句话的一部分，
# 检索命中任意一边都能拿到相对完整的上下文，避免“两边都检索不到”。
DEFAULT_OVERLAP_CHARS = 80

# 匹配 Markdown 标题行，例如 "## 步骤"。
# 第 1 组是井号数量，代表标题层级（1~6 级）；第 2 组是标题文字；
# 结尾的 "#*" 兼容 "## 步骤 ##" 这种带闭合井号的写法。
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
# 匹配汉字（CJK 统一表意文字），用于估算 token 数。
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
# 匹配连续的英文字母或数字，把一段英文/数字当作一个计数单位。
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
# 匹配 Markdown 图片，例如 "![白灼虾](./白灼虾.webp)"。
# 只用于“去图片”场景（统计 token、生成向量），不会改写切片正文，
# 所以这里只要求匹配成功即可，不关心图片说明和地址分别是什么。
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)\s]+(?:\s+[\"'][^\"']*[\"'])?\)")
# 匹配 HTML 图片标签，例如 <img src="x.png" />。
# 有些 Markdown 文档会混用 HTML 写法，生成向量前也要一并去掉。
_HTML_IMAGE_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
# 句子切分正则：匹配到句末标点（。！？!?；;）或换行为止的一段文字。
# 前半段 [^...]* 表示“不含句末标点的任意内容”，后半段 [。！？!?；;\n]? 是可选的一个标点，
# 因此最后一段即使没有标点也能被匹配到。用于超长段落的安全切分。
_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]*[。！？!?；;\n]?")


@dataclass
class TextChunk:
    """一个文本切片（chunk）及其定位信息。

    作用：split_document 的返回值类型。用一个小对象同时携带“要存的内容”和“定位信息”，
    避免调用方在多个平行列表或元组之间来回对应。

    哪里用到：
    - app/services/kb_service.py 的 _save_drafts：把 content 写入切片列表
      （kb_draft_chunks）的 content、token_count、metadata；
    - app/services/kb_service.py 的 _build_index：把 content 列表交给 embedding_service
      批量生成向量（向量与切片按下标一一对应），再写入 kb_chunks。

    为什么这样设计：
    content 已经带上上下文头，可以直接用于生成向量和展示（片段脱离原文后仍知道属于哪个章节）；
    metadata 只保存结构化定位信息，便于前端或后续问答引用来源，不参与向量计算，避免浪费 token。
    """

    # 切片正文，开头已经拼好“【文档标题｜章节路径】”上下文头，可直接入库、向量化、展示。
    content: str
    # 粗略估算的 token 数，仅用于统计与展示（不是计费依据），由 estimate_tokens 计算。
    token_count: int
    # 结构化定位信息：heading（最近一级标题）、headingPath（完整标题路径）、
    # sectionIndex（第几个正文小节）。默认空字典，便于以后扩展字段。
    metadata: dict[str, Any] = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数。

    作用：给每个切片算一个“体量”指标，随切片存入数据库，便于运营查看切片大小。
    哪里用到：只在本文件 split_document 里为每个 TextChunk 计算 token_count。

    规则：一个汉字算一个，一个连续的英文或数字串算一个。
    为什么不用真实分词器（如 tiktoken）：真实分词器依赖具体模型，引入额外依赖、速度慢，
    而且换模型后会失效；这里只需要一个稳定的近似值用于展示与统计，不参与计费。
    """
    if not text:
        return 0
    # 统计汉字数量：每个汉字大约等于 1 个 token。
    cjk = len(_CJK_RE.findall(text))
    # 先把汉字替换成空格，避免“中文english”被当成一个整体，
    # 再统计英文单词/数字串数量：每个词大约 1~2 个 token，这里按 1 个估算。
    words = len(_WORD_RE.findall(_CJK_RE.sub(" ", text)))
    return cjk + words


def strip_media_markup(text: str) -> str:
    """去掉文本中的图片标记，只保留可读文字。

    作用：图片地址（例如 `./白灼虾.webp`、`/media/kb/xxx/白灼虾.webp`）对语义检索
    没有帮助，还会占用嵌入模型的输入长度；生成向量和统计 token 前统一清理。
    哪里用到：
    1. 本文件 split_document 计算 token_count 时调用；
    2. app/services/kb_service.py 的 _build_index 在调用嵌入服务前调用。

    为什么不在切片时直接删除图片：
    管理后台需要把切片原样展示给运营确认，保留图片标记才能渲染出图片；
    只有“送去向量化”的那份文本需要去掉图片。
    """
    cleaned = _MARKDOWN_IMAGE_RE.sub("", text)
    cleaned = _HTML_IMAGE_RE.sub("", cleaned)
    # 删除图片后可能留下连续空行，压缩成最多一个空行，避免无意义的空白进入向量。
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _split_sections(text: str) -> list[dict[str, Any]]:
    """按 Markdown 标题把正文拆成若干节。

    作用：切片流程的第一步。先把整篇文档按标题拆成“节”，每节带上自己的标题路径，
    后续只在节内部打包片段，保证一个片段不会跨越两个章节、混杂两个主题。
    哪里用到：只被本文件 split_document 调用。
    为什么按标题拆：Markdown 知识文档天然用标题组织主题，按标题切分比纯按长度硬切
    更符合文档语义，检索命中后也能直接告诉用户“答案来自哪一节”。

    标题栈（stack）用于生成“一级 / 二级 / 三级”这样的路径：
    遇到同级或更高级标题时先弹出旧标题，再把新标题压栈，保证栈里始终是当前标题的祖先链。
    循环按“先正文、后标题”的顺序处理，所以最后还需要再执行一次 flush，
    把最后一个标题下的正文也收进结果。
    """
    # 统一换行符：Windows 的 \r\n 和旧 Mac 的 \r 都转成 \n，后续只按 \n 切分即可。
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # sections 保存每一节的数据；stack 是当前标题的祖先链，元素为 (标题层级, 标题文字)。
    sections: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    current_heading = ""
    current_path = ""
    section_index = 0
    buffer: list[str] = []

    def flush() -> None:
        """把缓冲区里的正文收成“一节”。

        正文为空时（例如连续两个标题紧挨着，或文档以标题开头）直接跳过，
        不生成没有内容的空节，避免后续产生空片段。
        """
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
        line = raw_line.rstrip()  # 去掉行尾空白，标题匹配更稳定
        match = _HEADING_RE.match(line.strip())
        if match is None:
            # 普通正文行：先累积到缓冲区，等遇到下一个标题再统一收节。
            buffer.append(line)
            continue
        # 遇到标题：先把上一个标题下的正文收成节，再清空缓冲区准备装新一节的正文。
        flush()
        buffer.clear()
        level = len(match.group(1))  # 井号数量就是标题层级
        title = match.group(2).strip()
        # 弹出所有“同级或更深”的旧标题，剩下的就是新标题的父级链。
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        current_heading = title
        # 路径用 " / " 连接，例如 "常见问题 / 保存 / 冷冻"。
        current_path = " / ".join(item[1] for item in stack)
    # 文档结尾没有新标题来触发 flush，这里补一次，收下最后一节正文。
    flush()
    return sections


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """把超过最大长度的段落按句子边界切开。

    作用：单个段落本身可能就超过 max_chars（例如一大段没有空行的说明文字），
    这里保证“任何一段”都不会超长，是片段长度上限的最后一道保险。
    哪里用到：只被本文件 _pack_paragraphs 在打包每个段落之前调用。

    找不到句号时退化为按固定长度硬切，保证不会产生超长片段。
    """
    if len(paragraph) <= max_chars:
        return [paragraph]
    pieces: list[str] = []
    buffer = ""
    for sentence in _SENTENCE_RE.findall(paragraph):
        # 正则可能匹配出空字符串，跳过，避免把空串当成一句话。
        if not sentence:
            continue
        if buffer and len(buffer) + len(sentence) > max_chars:
            # 再装下这句话就超长：先输出当前缓冲，再把这句话放进新缓冲。
            pieces.append(buffer.strip())
            buffer = sentence
        else:
            buffer += sentence
        # 兜底：某“一句话”本身就超长（中间没有任何句末标点），按固定长度硬切，
        # 保证每一块都不超过 max_chars。
        while len(buffer) > max_chars:
            pieces.append(buffer[:max_chars].strip())
            buffer = buffer[max_chars:]
    if buffer.strip():
        pieces.append(buffer.strip())
    # 过滤空串，保证返回的每一条都是可用文本。
    return [piece for piece in pieces if piece]


def _pack_paragraphs(
    paragraphs: list[str],
    *,
    target_chars: int,
    max_chars: int,
    overlap_chars: int,
) -> list[str]:
    """把段落累积成不超过最大长度的片段，并在片段之间保留重叠。

    作用：切片的核心“装箱”步骤。target_chars 是“可以考虑换片”的目标长度，
    max_chars 是“必须换片”的硬性上限，overlap_chars 让相邻片段共享一小截文字。
    哪里用到：只被本文件 split_document 在每一节内部调用。
    """
    packed: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        # 一个段落可能本身就超长，先按句子切到不超过 max_chars 再参与装箱。
        for piece in _split_long_paragraph(paragraph, max_chars):
            if not buffer:
                buffer = piece
                continue
            # 段落之间用空行连接，保留 Markdown 的段落语义。
            merged = f"{buffer}\n\n{piece}"
            # 分支一：已经达到目标长度，且再合并会超过上限 → 输出当前片段，开始新片段。
            if len(buffer) >= target_chars and len(merged) > max_chars:
                packed.append(buffer)
                # 取当前片段末尾一小段作为新片段开头，避免边界处的句子两边都检索不到。
                tail = buffer[-overlap_chars:] if overlap_chars > 0 else ""
                buffer = f"{tail}\n\n{piece}" if tail else piece
                # 重叠后仍可能超长，这里先硬切一次，超出的部分留给下一轮继续处理。
                if len(buffer) > max_chars:
                    trimmed = buffer[:max_chars]
                    packed.append(trimmed)
                    buffer = buffer[max_chars:]
                continue
            # 分支二：还没到目标长度，但合并后会超过硬上限 → 同样先输出当前片段。
            if len(merged) > max_chars:
                packed.append(buffer)
                tail = buffer[-overlap_chars:] if overlap_chars > 0 else ""
                buffer = f"{tail}\n\n{piece}" if tail else piece
                continue
            # 分支三：合并后仍在长度范围内 → 继续累积，等更多段落一起成片。
            buffer = merged
    # 循环结束后缓冲区里可能还有最后一段没输出。
    if buffer.strip():
        packed.append(buffer.strip())
    # 过滤空白片段，保证返回的每一条都有实际内容。
    return [item for item in packed if item.strip()]


def _context_header(title: str, heading_path: str) -> str:
    """生成片段开头的上下文头。

    作用：给每个片段加上“【文档标题｜章节路径】”一行，因为片段脱离原文后，
    单看正文可能不知道它在讲哪一部分。
    哪里用到：只被本文件 split_document 调用，结果拼在每个 TextChunk.content 的最前面。

    标题路径过长时只保留最后两级，避免上下文头本身占用太多字符。
    """
    parts = [part for part in (title.strip(), heading_path.strip()) if part]
    if not parts:
        return ""
    compact: list[str] = []
    for part in parts:
        # 文档标题和章节路径分开处理；只有章节路径内部包含 " / " 分隔符。
        if " / " in part:
            levels = [level.strip() for level in part.split(" / ") if level.strip()]
            # 路径太深时只保留最后两级：最贴近正文的两级信息量最大。
            part = " / ".join(levels[-2:])
        # 单个部分最多保留 60 字，防止标题本身过长把上下文头撑得太大。
        compact.append(part[:60])
    # 用中文竖线“｜”把文档标题和章节路径拼成一行，外层用【】包裹，
    # 让人一眼能看出这是上下文头而不是正文。
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

    作用与调用方：
        本模块对外的唯一入口。app/services/kb_service.py 的 _split_text 在
        “文档上传 / 重新切片”时调用它获取切片列表；server/tests/test_kb.py 的单元测试
        也直接调用它，验证切片行为是否符合预期。

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
    # 参数纠偏：目标长度必须落在 (0, max_chars] 区间内，否则回退到默认值，
    # 保证“目标长度 ≤ 硬上限”这个前提始终成立，避免装箱逻辑出现反直觉结果。
    if target_chars <= 0 or target_chars > max_chars:
        target_chars = min(DEFAULT_TARGET_CHARS, max_chars)
    # 重叠长度不能为负数；为 0 表示相邻片段不做重叠。
    if overlap_chars < 0:
        overlap_chars = 0

    chunks: list[TextChunk] = []
    # 第一步：按标题分节，保证片段不跨章节；每一节单独做后续的段落打包。
    for section in _split_sections(text):
        # 第二步：节内按空行拆段落（Markdown 中空行就是段落边界）。
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", section["body"])
            if paragraph.strip()
        ]
        # 第三步：把段落累积打包成接近目标长度的片段（含超长段落切分与相邻重叠）。
        pieces = _pack_paragraphs(
            paragraphs,
            target_chars=target_chars,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )
        # 第四步：为这一节生成统一的上下文头，本节内所有片段共用。
        header = _context_header(title, section["heading_path"])
        for piece in pieces:
            content = f"{header}{piece}".strip()
            if not content:
                continue
            # 组装返回值：content 用于展示，token_count 用于统计，
            # metadata 记录来源章节，最终写入 kb_chunk 表的 chunk_metadata 字段。
            # token_count 按去掉图片标记后的文字计算，和真正送给嵌入模型的内容保持一致。
            chunks.append(
                TextChunk(
                    content=content,
                    token_count=estimate_tokens(strip_media_markup(content)),
                    metadata={
                        "heading": section["heading"],
                        "headingPath": section["heading_path"],
                        "sectionIndex": section["section_index"],
                    },
                )
            )
    return chunks
