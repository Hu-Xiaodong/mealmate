"""HowToCook 菜谱 Markdown 解析器。

这个模块只做“文本到结构化对象”的转换，不连接数据库、不调用网络，
因此可以直接在命令行试运行，也可以用普通单元测试覆盖。

它会在两个地方被用到：

1. 后台“数据导入”的试运行阶段：扫描固定版本的 HowToCook 仓库，
   统计能解析多少道菜、哪些菜缺字段、哪些厨具不认识；
2. 正式导入阶段：复用同一份解析结果写菜谱草稿和知识库切片，
   保证“试运行看到的”和“真正入库的”是同一套字段。

为什么不用第三方 Markdown 库：
HowToCook 的菜谱由固定模板约束，四个二级标题在所有菜谱中完全一致；
当前服务器环境无法安装新依赖，因此这里用标准库按行解析这个受控子集。
解析器只依赖标题和列表，不做完整 Markdown 渲染；遇到无法识别的行会记录警告，
不会静默丢弃内容。
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# HowToCook 模板固定的四个二级标题。导入逻辑依赖这四个名字，
# 如果上游改了标题，解析器会把它记为“缺少章节”，而不是猜内容。
SECTION_INGREDIENTS = "必备原料和工具"
SECTION_CALCULATION = "计算"
SECTION_STEPS = "操作"
SECTION_TIPS = "附加内容"

# 仓库目录名到中文菜系标签的映射。目录名来自 HowToCook，
# 中文标签用于后台筛选和后续的菜谱标签，不直接当作现有浏览分类使用。
CATEGORY_LABELS: dict[str, str] = {
    "vegetable_dish": "素菜",
    "meat_dish": "荤菜",
    "aquatic": "水产",
    "breakfast": "早餐",
    "staple": "主食",
    "soup": "汤羹",
    "dessert": "甜品",
    "drink": "饮品",
    "condiment": "调料",
    "semi-finished": "半成品",
}

# 厨具别名到内部编码的映射。
# 编码与现有 AI 筛选使用的小写英文保持一致，后续新增厨具时只在这里补别名，
# 不需要改解析主流程。别名越具体越好，避免“锅巴”这类食材被误判成厨具。
TOOL_ALIASES: dict[str, str] = {
    "微波炉": "microwave",
    "烤箱": "oven",
    "空气炸锅": "air_fryer",
    "电饭煲": "rice_cooker",
    "电饭锅": "rice_cooker",
    "蒸锅": "steamer",
    "蒸笼": "steamer",
    "高压锅": "pressure_cooker",
    "电压力锅": "pressure_cooker",
    "炒锅": "wok",
    "平底锅": "wok",
    "不粘锅": "wok",
    "铁锅": "wok",
    "汤锅": "pot",
    "炖锅": "pot",
    "煮锅": "pot",
    "砂锅": "pot",
    "搅拌机": "blender",
    "破壁机": "blender",
    "料理机": "blender",
    "厨房秤": "scale",
    "电子秤": "scale",
    "打蛋器": "whisk",
    "温度计": "thermometer",
    "密封袋": "sealed_bag",
    "保鲜袋": "sealed_bag",
}

# 用量里的数字和单位。单位做统一小写，方便后续按数值筛选；
# 中文单位保留原样，因为“个、根、片”无法可靠换算成克。
_UNIT_ALIASES: dict[str, str] = {
    "g": "g",
    "克": "g",
    "kg": "kg",
    "千克": "kg",
    "ml": "ml",
    "毫升": "ml",
    "l": "l",
    "升": "l",
    "℃": "℃",
    "摄氏度": "℃",
}

_CN_DIGITS: dict[str, int] = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_H1_RE = re.compile(r"^#\s+(.+?)\s*$")
_H2_RE = re.compile(r"^##\s+(.+?)\s*$")
_LIST_RE = re.compile(r"^(?P<indent>\s*)(?:[-*+]|\d+[.、])\s+(?P<body>.+?)\s*$")
_LABEL_RE = re.compile(r"^([^：:]{1,20})[：:]\s*$")
_TIME_RE = re.compile(
    r"(?P<value>[0-9]+(?:\.[0-9]+)?|[一二两三四五六七八九十百半个数]+)\s*"
    r"(?P<unit>分钟|小时|个小时)"
)
# 数字 + 可选范围 + 单位。范围支持 1-2、1~2、1～2、1至2。
# 数字允许“1/4”这种分数和“2 1/2”这种带整数的分数写法，
# 因为真实菜谱里会出现“美人椒 1/4 个”“生粉 2 1/2 茶匙”。
_NUMBER_PATTERN = r"(?:[0-9]+\s+)?[0-9]+(?:\.[0-9]+)?(?:\s*/\s*[0-9]+)?"
_AMOUNT_RE = re.compile(
    rf"(?P<min>{_NUMBER_PATTERN})"
    rf"(?:\s*[-~～至]\s*(?P<max>{_NUMBER_PATTERN}))?"
    r"\s*(?P<unit>g|克|kg|千克|ml|毫升|mL|L|升|个|只|根|片|勺|茶匙|汤匙|碗|杯|颗|粒|"
    r"瓣|段|张|块|斤|两|把|滴|头|支|枚|条|棵|束|盒|包|袋|瓶|罐|听|份|团|卷|串|对|副|套|扎|"
    r"℃|摄氏度)"
)
_OPTIONAL_RE = re.compile(r"[（(]\s*可选\s*[）)]")
_PAREN_NOTE_RE = re.compile(r"[（(]([^（）()]*)[）)]\s*$")
# 这些前缀开头的列表项是说明文字，不是原料。
_NOTE_PREFIXES = ("注：", "注:", "备注：", "备注:", "说明：", "说明:", "提示：", "提示:")
_FOOTER = "如果您遵循本指南的制作流程而发现有问题或可以改进的流程"


class ParseError(ValueError):
    """菜谱缺少必要结构时抛出的异常。

    试运行会把它转换成失败记录，而不是让整批导入中断。
    """


@dataclass(slots=True)
class ParsedIngredient:
    """一行原料的解析结果。

    字段说明：
    - name：原料名称，去掉描述和用量后的主名称；
    - amount_text：原始用量文本，例如“10-15ml”“2 片，450g”“适量”；
    - amount_min / amount_max：能解析成数字时的最小值和最大值；
    - unit：统一后的单位；
    - optional：是否标注“可选”；
    - note：括号里的补充说明，例如品牌、处理方式。
    """

    name: str
    amount_text: str = ""
    amount_min: float | None = None
    amount_max: float | None = None
    unit: str = ""
    optional: bool = False
    note: str = ""


@dataclass(slots=True)
class ParsedRecipe:
    """一道菜谱的解析结果。

    这是导入阶段的中间对象，不是数据库模型：
    - 试运行只需要统计字段，不写库；
    - 正式导入时再把字段映射到 recipes 表；
    - raw_sections 保留每个章节的原文，供知识库切片使用。
    """

    source_path: str
    title: str
    category: str
    description: str = ""
    difficulty: str = ""
    calories: str = ""
    total_minutes: int | None = None
    servings: float | None = None
    ingredients: list[ParsedIngredient] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    unknown_tools: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)
    image_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checksum: str = ""
    raw_sections: dict[str, str] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        """是否具备入库的最低条件：标题、原料、步骤都不能为空。"""
        return bool(self.title and self.ingredients and self.steps)


@dataclass(slots=True)
class RepositoryReport:
    """一次仓库扫描的汇总结果，供命令行和后台试运行页面使用。"""

    total_files: int = 0
    parsed: int = 0
    failed: int = 0
    invalid: int = 0
    warning_count: int = 0
    # 原料用量分三类统计，方便判断导入质量：
    # missing_amounts 表示原文根本没写用量；
    # text_amounts 表示写了用量但无法变成数字（例如“适量”“少许”）；
    # numeric_amounts 表示成功提取出数值。
    numeric_amounts: int = 0
    text_amounts: int = 0
    missing_amounts: int = 0
    missing_time: int = 0
    category_counts: Counter[str] = field(default_factory=Counter)
    unknown_tools: Counter[str] = field(default_factory=Counter)
    duplicate_titles: dict[str, int] = field(default_factory=dict)
    recipes: list[ParsedRecipe] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self, include_recipes: bool = False) -> dict[str, Any]:
        """转换成可以直接写 JSON 的字典。

        include_recipes=False 时只返回统计，避免后台试运行响应过大；
        命令行需要完整结果时再传 True。
        """
        payload: dict[str, Any] = {
            "totalFiles": self.total_files,
            "parsed": self.parsed,
            "failed": self.failed,
            "invalid": self.invalid,
            "warningCount": self.warning_count,
            "numericAmounts": self.numeric_amounts,
            "textAmounts": self.text_amounts,
            "missingAmounts": self.missing_amounts,
            "totalIngredients": (
                self.numeric_amounts + self.text_amounts + self.missing_amounts
            ),
            "missingTime": self.missing_time,
            "categoryCounts": dict(self.category_counts),
            "unknownTools": dict(self.unknown_tools),
            "duplicateTitles": self.duplicate_titles,
            "failures": self.failures,
        }
        if include_recipes:
            payload["recipes"] = [_recipe_to_dict(recipe) for recipe in self.recipes]
        return payload


def parse_markdown(text: str, source_path: str) -> ParsedRecipe:
    """把一份 HowToCook Markdown 解析成 ParsedRecipe。

    参数：
    - text：Markdown 原文；
    - source_path：仓库内的相对路径，用于去重和追溯来源。

    解析失败（例如没有一级标题）时抛出 ParseError；
    缺原料、缺步骤等质量问题不抛出，而是写入 warnings，
    让试运行能一次性看到所有问题。
    """
    cleaned = _HTML_COMMENT_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = cleaned.split("\n")

    title = ""
    for line in lines:
        match = _H1_RE.match(line)
        if match:
            title = _clean_inline(match.group(1)).removesuffix("的做法").strip()
            break

    if not title:
        raise ParseError("缺少一级标题（菜名）")

    sections = _split_sections(lines)
    intro = "\n".join(sections.get("", []))
    recipe = ParsedRecipe(
        source_path=source_path,
        title=title,
        category=_category_from_path(source_path),
        description=_parse_description(intro),
        difficulty=_parse_labeled_line(intro, "预估烹饪难度"),
        calories=_parse_labeled_line(intro, "预估卡路里"),
        image_paths=_parse_images(cleaned),
        raw_sections=_raw_sections(sections),
        checksum=_checksum(cleaned),
    )

    recipe.total_minutes, time_warnings = _parse_total_minutes(intro)
    recipe.warnings.extend(time_warnings)
    recipe.servings = _parse_servings(
        "\n".join(sections.get(SECTION_CALCULATION, [])), intro
    )

    ingredient_lines = sections.get(SECTION_INGREDIENTS)
    if ingredient_lines is None:
        recipe.warnings.append(f"缺少章节：{SECTION_INGREDIENTS}")
    else:
        ingredients, tools, unknown_tools = _parse_ingredients(ingredient_lines)
        recipe.ingredients = ingredients
        recipe.tools = tools
        recipe.unknown_tools = unknown_tools
        if unknown_tools:
            recipe.warnings.append("未识别厨具：" + "、".join(sorted(set(unknown_tools))))

    calculation_lines = sections.get(SECTION_CALCULATION)
    if calculation_lines:
        recipe.ingredients = _merge_calculation(recipe.ingredients, calculation_lines)

    step_lines = sections.get(SECTION_STEPS)
    if step_lines is None:
        recipe.warnings.append(f"缺少章节：{SECTION_STEPS}")
    else:
        recipe.steps = _parse_steps(step_lines)
        if not recipe.steps:
            recipe.warnings.append("操作章节没有可识别的步骤")

    tips_lines = sections.get(SECTION_TIPS)
    if tips_lines:
        recipe.tips = _parse_tips(tips_lines)

    if not recipe.ingredients:
        recipe.warnings.append("没有识别到任何原料")
    if not recipe.steps:
        recipe.warnings.append("没有识别到任何步骤")
    if recipe.total_minutes is None:
        recipe.warnings.append("原文没有写明总时长")

    filename = Path(source_path).stem
    if filename and filename != title:
        recipe.warnings.append(f"标题与文件名不一致：{filename}")

    return recipe


def parse_repository(root: Path) -> RepositoryReport:
    """扫描一个已解压的 HowToCook 仓库目录。

    root 可以是仓库根目录，也可以是包含唯一子目录的解压目录；
    解析器会自动找到 dishes 目录，跳过 template 模板。
    """
    dishes_root = _find_dishes_root(root)
    files = sorted(
        path
        for path in dishes_root.rglob("*.md")
        if "template" not in path.relative_to(dishes_root).parts
    )
    report = RepositoryReport(total_files=len(files))
    title_counter: Counter[str] = Counter()

    for path in files:
        relative = path.relative_to(dishes_root)
        source_path = f"dishes/{relative.as_posix()}"
        category = relative.parts[0] if relative.parts else "unknown"
        report.category_counts[CATEGORY_LABELS.get(category, category)] += 1
        try:
            text = path.read_text(encoding="utf-8-sig")
            recipe = parse_markdown(text, source_path)
        except (OSError, UnicodeError, ParseError) as exc:
            report.failed += 1
            report.failures.append({"path": source_path, "reason": str(exc)})
            continue

        report.parsed += 1
        report.recipes.append(recipe)
        title_counter[recipe.title] += 1
        report.warning_count += len(recipe.warnings)
        if not recipe.valid:
            report.invalid += 1
        if recipe.total_minutes is None:
            report.missing_time += 1
        for ingredient in recipe.ingredients:
            if not ingredient.amount_text:
                report.missing_amounts += 1
            elif ingredient.amount_min is None:
                report.text_amounts += 1
            else:
                report.numeric_amounts += 1
        for tool in recipe.unknown_tools:
            report.unknown_tools[tool] += 1

    report.duplicate_titles = {
        title: count for title, count in title_counter.items() if count > 1
    }
    for recipe in report.recipes:
        if recipe.title in report.duplicate_titles:
            recipe.warnings.append(
                f"标题重复：{recipe.title} 出现 {report.duplicate_titles[recipe.title]} 次"
            )
    report.warning_count = sum(len(recipe.warnings) for recipe in report.recipes)
    return report


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    """按二级标题切分正文。

    返回的键是标题文字，空字符串键表示第一个二级标题之前的介绍。
    标题行本身不进入章节内容，后续按章节名取字段。
    """
    sections: dict[str, list[str]] = {"": []}
    current = ""
    for line in lines:
        match = _H2_RE.match(line)
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
            continue
        if _H1_RE.match(line):
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _raw_sections(sections: dict[str, list[str]]) -> dict[str, str]:
    """把章节内容原样保留，供知识库切片使用。

    结构化字段会丢掉表格、嵌套列表等细节；RAG 需要原文，
    所以这里额外保存一份按章节整理的文本。
    """
    return {
        key: "\n".join(lines).strip()
        for key, lines in sections.items()
        if "\n".join(lines).strip()
    }


def _clean_inline(text: str) -> str:
    """去掉 Markdown 行内标记，保留可读文字。

    只处理模板里实际出现的语法：行内代码、粗体、斜体、链接。
    不处理整段 HTML，因为 HowToCook 正文里的 HTML 主要是注释，
    注释在解析开始前已经统一删除。
    """
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_description(intro: str) -> str:
    """从标题下方的介绍段提取菜谱简介。

    介绍里可能混有“预估烹饪难度”“预估卡路里”两行，
    它们会单独解析成字段，不重复写进简介。
    """
    paragraphs: list[str] = []
    for raw in intro.split("\n"):
        line = _clean_inline(raw)
        if not line:
            continue
        if line.startswith("预估烹饪难度") or line.startswith("预估卡路里"):
            continue
        if line.startswith("!["):
            continue
        paragraphs.append(line)
    return " ".join(paragraphs).strip()


def _parse_labeled_line(text: str, label: str) -> str:
    """提取“预估烹饪难度：★★”这类单行字段。"""
    match = re.search(rf"{re.escape(label)}[：:]\s*(.+)", text)
    return _clean_inline(match.group(1)) if match else ""


def _parse_images(text: str) -> list[str]:
    """提取 Markdown 图片路径，保持原始相对路径。

    真正下载图片发生在导入阶段，解析器不访问网络。
    """
    images: list[str] = []
    for match in _IMAGE_RE.finditer(text):
        path = match.group(1).strip().strip("<>")
        if path.startswith(("http://", "https://", "data:")):
            images.append(path)
        else:
            images.append(path.removeprefix("./"))
    return images


def _category_from_path(source_path: str) -> str:
    """从 `dishes/vegetable_dish/菜名.md` 取出菜系标签。"""
    parts = Path(source_path).parts
    if len(parts) >= 3 and parts[0] == "dishes":
        return CATEGORY_LABELS.get(parts[1], parts[1])
    return "unknown"


def _parse_total_minutes(intro: str) -> tuple[int | None, list[str]]:
    """从介绍段提取总时长，单位分钟。

    只读介绍段，不读操作步骤：步骤里的“微波 3 分钟”是单步耗时，
    加起来不等于总时长。中文数字（二十分钟、半小时、一个半小时）也支持。
    同时出现小时和分钟时相加，例如“1 小时 30 分钟”得到 90；
    出现多个时长时相加并记录警告，提醒人工核对。
    """
    values: list[float] = []
    has_hour = False
    for match in _TIME_RE.finditer(intro):
        raw_value = match.group("value")
        unit = match.group("unit")
        number = _parse_cn_number(raw_value)
        if number is None:
            continue
        minutes = number * 60 if unit in {"小时", "个小时"} else number
        values.append(minutes)
        if unit in {"小时", "个小时"}:
            has_hour = True

    if not values:
        return None, []
    total = int(round(sum(values)))
    warnings: list[str] = []
    if len(values) > 1:
        warnings.append("介绍中出现多个时长，已按总和估算，请人工核对")
    if not has_hour and total <= 0:
        return None, warnings
    return total, warnings


def _parse_servings(calculation: str, intro: str) -> float | None:
    """从“计算”章节或介绍中提取份数。

    常见写法：
    - “每 2 份”
    - “一份正好够 1 个人食用”
    - “够 2 人吃”
    解析不出来时返回 None，不默认成 1，避免误导用户。
    """
    text = f"{calculation}\n{intro}"
    patterns = [
        r"一份[^。\n]{0,20}?([0-9]+(?:\.[0-9]+)?)\s*个?人",
        r"([0-9]+(?:\.[0-9]+)?)\s*个?人(?:食用|吃)",
        r"每\s*([0-9]+(?:\.[0-9]+)?)\s*份",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
    return None


def _parse_cn_number(text: str) -> float | None:
    """把中文数字转换成浮点数。

    支持“二”“二十”“二十三”“一百二十”“半”“一个半”等写法；
    无法识别时返回 None，由调用方决定是否记录警告。
    """
    text = text.strip()
    if not text:
        return None

    # 阿拉伯数字（15、3.5）直接转换；中文数字再走下面的逐字解析。
    try:
        return float(text)
    except ValueError:
        pass

    if "半" in text:
        base_text = text.replace("个", "").replace("半", "")
        if not base_text:
            return 0.5
        base = _parse_cn_integer(base_text)
        return None if base is None else base + 0.5

    value = _parse_cn_integer(text)
    return None if value is None else float(value)


def _parse_cn_integer(text: str) -> int | None:
    """解析整数形式的中文数字，供时长和份数使用。"""
    total = 0
    current = 0
    for char in text:
        if char in _CN_DIGITS:
            current = _CN_DIGITS[char]
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char == "百":
            total += (current or 1) * 100
            current = 0
        elif char == "零":
            continue
        else:
            return None
    return total + current


def _parse_ingredients(
    lines: list[str],
) -> tuple[list[ParsedIngredient], list[str], list[str]]:
    """解析“必备原料和工具”章节。

    章节里可能用“原料：”“调味料：”“工具：”这类小标题分组。
    分组标题不是数据，只用来切换后续列表项属于原料还是工具。
    没有显式“工具：”分组时，再用厨具词典判断。
    """
    ingredients: list[ParsedIngredient] = []
    tools: list[str] = []
    unknown_tools: list[str] = []
    mode = "ingredient"

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        label = _LABEL_RE.match(_clean_inline(stripped))
        if label and not _LIST_RE.match(raw):
            mode = "tool" if "工具" in label.group(1) else "ingredient"
            continue
        item = _list_item(raw)
        if item is None:
            continue
        # “注：”“备注：”这类行是说明文字，不是原料。
        if item.startswith(_NOTE_PREFIXES):
            continue

        if mode == "tool" or _looks_like_tool(item):
            code = _tool_code(item)
            if code is None:
                unknown_tools.append(item)
            elif code not in tools:
                tools.append(code)
            continue

        # 有些菜谱会写只有括号备注、没有名称的行，这种行不能当成原料；
        # “1 汤匙 = 15ml”这种单位换算说明也要跳过。
        for parsed in _split_multi_ingredients(_parse_ingredient(item)):
            if parsed.name and not _is_unit_definition(parsed):
                ingredients.append(parsed)

    return ingredients, tools, unknown_tools


def _merge_calculation(
    ingredients: list[ParsedIngredient], lines: list[str]
) -> list[ParsedIngredient]:
    """把“计算”章节的用量合并到原料列表。

    模板要求原料在“必备原料和工具”里列名称，在“计算”里列数量；
    但实际菜谱经常只在计算章节出现水、淀粉等原料。
    合并规则：按名称匹配已有原料，匹配不到就追加，并保留原始用量文本。
    """
    for raw in lines:
        item = _list_item(raw)
        if item is None:
            continue
        for parsed in _split_multi_ingredients(_parse_ingredient(item)):
            if not parsed.name or _is_unit_definition(parsed):
                continue
            existing = next(
                (
                    ingredient
                    for ingredient in ingredients
                    if ingredient.name == parsed.name
                    or ingredient.name.startswith(parsed.name + "，")
                    or parsed.name.startswith(ingredient.name + "，")
                ),
                None,
            )
            if existing is None:
                parsed.note = "；".join(filter(None, [parsed.note, "仅出现在计算章节"]))
                ingredients.append(parsed)
                continue
            # 计算章节写的是标准用量，优先覆盖；如果计算章节那一行没写用量，
            # 就保留原料章节已经解析出的结果，避免把有效数值清空。
            if parsed.amount_text:
                existing.amount_text = parsed.amount_text
                existing.amount_min = parsed.amount_min
                existing.amount_max = parsed.amount_max
                existing.unit = parsed.unit
            existing.optional = existing.optional or parsed.optional
            if parsed.note and parsed.note not in existing.note:
                existing.note = "；".join(filter(None, [existing.note, parsed.note]))
    return ingredients


def _strip_parenthetical_note(name: str) -> tuple[str, str]:
    """把名称里的括号说明拆出来，返回（纯名称，括号备注）。

    例：“食用油（花生油/菜籽油）”拆成名称“食用油”和备注“花生油/菜籽油”。
    如果去掉括号后名称为空（整行就是一个括号说明），保留原文，
    避免把原料名称清空。
    """
    match = re.search(r"[（(]([^（）()]*)[）)]", name)
    if match is None:
        return name, ""
    cleaned = (name[: match.start()] + name[match.end() :]).strip(" ，,、")
    if not cleaned:
        return name, ""
    return cleaned, match.group(1).strip()


def _parse_ingredient(raw: str) -> ParsedIngredient:
    """解析一条原料，拆出名称、用量、单位和备注。

    典型输入：
    - “西红柿 = 1 个（约 180g） * 份数”
    - “食用油 10-15ml”
    - “黑鳕鱼，带皮，2 片，450g（所有调料按实际重量调整）”
    - “糖（可选）”
    """
    text = _clean_inline(raw).rstrip("。")
    optional = bool(_OPTIONAL_RE.search(text))
    text = _OPTIONAL_RE.sub("", text).strip()

    note = ""
    paren = _PAREN_NOTE_RE.search(text)
    if paren:
        note = paren.group(1).strip()
        text = text[: paren.start()].strip()

    if "=" in text:
        name, amount = text.split("=", 1)
        name = name.strip(" ，,、")
        amount = amount.strip()
    else:
        name, note_from_parts, amount = _split_name_amount(text)
        if note_from_parts:
            note = "；".join(filter(None, [note, note_from_parts]))

    name, name_note = _strip_parenthetical_note(name)
    if name_note:
        note = "；".join(filter(None, [note, name_note]))

    amount_min, amount_max, unit = _extract_amount(amount)
    return ParsedIngredient(
        name=name.strip(),
        amount_text=amount.strip(),
        amount_min=amount_min,
        amount_max=amount_max,
        unit=unit,
        optional=optional,
        note=note,
    )


def _split_multi_ingredients(parsed: ParsedIngredient) -> list[ParsedIngredient]:
    """一行里列了多个原料时拆成多条，例如“油、盐、生抽”。

    只在没有写用量时拆分：一行写了用量又列了多个名称，
    无法判断用量属于哪个原料，保留原样交给人工审核。
    """
    if "、" not in parsed.name or parsed.amount_text:
        return [parsed]
    return [
        ParsedIngredient(name=part.strip(), optional=parsed.optional, note=parsed.note)
        for part in parsed.name.split("、")
        if part.strip()
    ]


def _is_unit_definition(parsed: ParsedIngredient) -> bool:
    """判断一行是不是“1 汤匙 = 15ml”这种单位换算说明，不是原料。"""
    return bool(parsed.name) and _AMOUNT_RE.fullmatch(parsed.name.strip()) is not None


def _split_name_amount(text: str) -> tuple[str, str, str]:
    """按逗号拆分“名称、描述、用量”。

    返回（名称，描述，用量文本）。没有用量时用量为空字符串，
    不会把描述误当成用量。真实菜谱主要有三种写法：
    - “名称，描述，用量”，例如“黑鳕鱼，带皮，2 片，450g”；
    - “名称 用量，说明”，例如“盐 10g，如果辣椒辣度高，建议多一点”；
    - “名称，用量，说明”，例如“鸡蛋，2 个，打散”。
    """
    parts = [part.strip() for part in re.split(r"[，,]", text) if part.strip()]
    if not parts:
        return "", "", ""

    amount_index = next(
        (index for index, part in enumerate(parts) if _AMOUNT_RE.search(part)),
        None,
    )
    if amount_index is None:
        return parts[0], "，".join(parts[1:]), ""

    if amount_index == 0:
        # 第一段里同时写了名称和用量，需要从用量起点切开。
        match = _AMOUNT_RE.search(parts[0])
        name = parts[0][: match.start()].strip(" ，,、")
        if not name:
            return "", "，".join(parts[1:]), "，".join(parts)
        note_parts: list[str] = []
        amount_parts = [parts[0][match.start() :].strip()]
    else:
        name = parts[0]
        note_parts = parts[1:amount_index]
        amount_parts = [parts[amount_index]]

    # 只有连续命中“数字 + 单位”的片段才继续算作用量，
    # 后面的说明文字（例如“打散”“如果辣椒辣度高”）回到备注。
    for part in parts[amount_index + 1 :]:
        if _AMOUNT_RE.search(part):
            amount_parts.append(part)
        else:
            note_parts.append(part)

    return name, "，".join(note_parts), "，".join(amount_parts)


def _to_number(text: str) -> float:
    """把数字文本转成浮点数，支持“1/4”和“2 1/2”两种分数写法。"""
    text = text.strip()
    mixed = re.fullmatch(r"([0-9]+)\s+([0-9]+(?:\s*/\s*[0-9]+)?)", text)
    if mixed:
        return float(mixed.group(1)) + _to_number(mixed.group(2))
    if "/" not in text:
        return float(text)
    numerator, denominator = (piece.strip() for piece in text.split("/", 1))
    denominator_value = float(denominator)
    if denominator_value == 0:
        raise ValueError("分数分母不能为 0")
    return float(numerator) / denominator_value


def _extract_amount(text: str) -> tuple[float | None, float | None, str]:
    """从用量文本里提取最小数值、最大数值和单位。

    一行里可能有多个数量，例如“2 片，450g”“1 个（约 180g）”。
    这里优先取克、千克、毫升、升这类重量或体积单位，因为后续按营养、
    成本筛选时它们比“片、个”更可计算；没有重量单位才退回第一个数量。
    “适量”“少许”没有任何数字，返回三个空值，由调用方记为文本用量，
    不强行填 0，避免把“没写数量”误导成“数量为零”。
    """
    if not text:
        return None, None, ""
    cleaned = re.sub(r"[*×]\s*份数", "", text)
    cleaned = re.sub(r"[*×]\s*[^，,；;\s]+/[^，,；;\s]+", "", cleaned)
    matches = list(_AMOUNT_RE.finditer(cleaned))
    if not matches:
        return None, None, ""

    # 同时出现“2 片，450g”时优先取重量/体积，因为克和毫升更适合后续筛选；
    # 没有重量/体积再退回第一个数量，例如“1 个”“3 瓣”。
    preferred_units = {"g", "kg", "ml", "l", "克", "千克", "毫升", "升"}
    match = next(
        (item for item in matches if item.group("unit").lower() in preferred_units),
        matches[0],
    )
    unit = match.group("unit")
    normalized_unit = _UNIT_ALIASES.get(unit.lower(), _UNIT_ALIASES.get(unit, unit))
    try:
        minimum = _to_number(match.group("min"))
        maximum = _to_number(match.group("max")) if match.group("max") else minimum
    except ValueError:
        return None, None, ""
    return minimum, maximum, normalized_unit


def _parse_steps(lines: list[str]) -> list[str]:
    """解析“操作”章节。

    顶层有序列表是步骤；缩进的嵌套列表是对上一步的补充说明，
    这里用中文分号拼接到上一步，避免丢失“可选做法”等信息。
    """
    steps: list[str] = []
    for raw in lines:
        if not raw.strip():
            continue
        match = _LIST_RE.match(raw)
        if match is None:
            continue
        body = _clean_inline(match.group("body"))
        if not body:
            continue
        indent = len(match.group("indent").replace("\t", "    "))
        if indent > 0 and steps:
            steps[-1] = f"{steps[-1]}；{body}"
        else:
            steps.append(body)
    return steps


def _parse_tips(lines: list[str]) -> list[str]:
    """解析“附加内容”章节。

    列表项直接保留；普通段落（例如表格前的说明）也保留。
    表格分隔行和页脚声明没有信息量，跳过。
    """
    tips: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith(_FOOTER):
            continue
        if set(stripped) <= {"|", "-", ":", " "}:
            continue
        item = _list_item(raw)
        if item is not None:
            tips.append(item)
            continue
        if stripped.startswith("|"):
            tips.append(_clean_inline(stripped.strip("|")))
            continue
        if stripped.startswith("#"):
            continue
        tips.append(_clean_inline(stripped))
    return [tip for tip in tips if tip]


def _list_item(raw: str) -> str | None:
    """取出一行列表项的文字；不是列表项返回 None。"""
    match = _LIST_RE.match(raw)
    if match is None:
        return None
    item = _clean_inline(match.group("body"))
    return item or None


def _looks_like_tool(item: str) -> bool:
    """判断一个没有分组标记的列表项是不是厨具。

    只在“必备原料和工具”章节使用。为避免“锅巴”被误判，
    单字别名不参与包含匹配，只做精确匹配。
    """
    text = item.split("（", 1)[0].split("(", 1)[0].strip()
    for alias in TOOL_ALIASES:
        if text == alias:
            return True
        if len(alias) >= 2 and alias in text:
            return True
    return False


def _tool_code(item: str) -> str | None:
    """把厨具名称映射成内部编码；不认识的返回 None。"""
    text = item.split("（", 1)[0].split("(", 1)[0].strip()
    for alias, code in TOOL_ALIASES.items():
        if text == alias or (len(alias) >= 2 and alias in text):
            return code
    return None


def _checksum(text: str) -> str:
    """计算正文摘要，用于判断导入源是否发生变化。

    计算前去掉多余空白和 HTML 注释，避免上游只改格式就触发全量更新。
    """
    normalized = _HTML_COMMENT_RE.sub("", text)
    normalized = "\n".join(line.rstrip() for line in normalized.splitlines())
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _find_dishes_root(root: Path) -> Path:
    """找到仓库里的 dishes 目录。

    支持两种输入：仓库根目录，或 GitHub 压缩包解压后的唯一子目录。
    """
    if (root / "dishes").is_dir():
        return root / "dishes"
    candidates = [path for path in root.iterdir() if path.is_dir()]
    if len(candidates) == 1 and (candidates[0] / "dishes").is_dir():
        return candidates[0] / "dishes"
    raise FileNotFoundError(f"没有找到 dishes 目录：{root}")


def _recipe_to_dict(recipe: ParsedRecipe) -> dict[str, Any]:
    """把 ParsedRecipe 转成 JSON 友好结构，供命令行完整报告使用。"""
    return {
        "sourcePath": recipe.source_path,
        "title": recipe.title,
        "category": recipe.category,
        "description": recipe.description,
        "difficulty": recipe.difficulty,
        "calories": recipe.calories,
        "totalMinutes": recipe.total_minutes,
        "servings": recipe.servings,
        "ingredients": [
            {
                "name": ingredient.name,
                "amountText": ingredient.amount_text,
                "amountMin": ingredient.amount_min,
                "amountMax": ingredient.amount_max,
                "unit": ingredient.unit,
                "optional": ingredient.optional,
                "note": ingredient.note,
            }
            for ingredient in recipe.ingredients
        ],
        "tools": recipe.tools,
        "unknownTools": recipe.unknown_tools,
        "steps": recipe.steps,
        "tips": recipe.tips,
        "imagePaths": recipe.image_paths,
        "warnings": recipe.warnings,
        "checksum": recipe.checksum,
        "valid": recipe.valid,
    }
