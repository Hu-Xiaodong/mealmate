"""HowToCook 解析器的单元测试。

这些用例只操作字符串和临时目录，不需要数据库和网络，
用于保证导入试运行与正式导入使用同一套解析规则。
"""

from __future__ import annotations

from pathlib import Path

from app.services.howtocook_parser import parse_markdown, parse_repository

STANDARD_RECIPE = """\
# 微波葱姜黑鳕鱼的做法

微波做鱼，葱姜提鲜，热油一淋，香气四溢。从备料到上桌大约只需二十分钟。

预估烹饪难度：★★★

预估卡路里：749 大卡

## 必备原料和工具

原料：

- 黑鳕鱼，带皮

调味料：

- 青葱
- 姜

工具：

- 密封袋

## 计算

每 2 份：

- 黑鳕鱼，带皮，2 片，450g
- 青葱，25g

## 操作

1. 鱼片放入密封袋。
2. 微波 3.5-5 分钟。
   - 取出鱼片。

## 附加内容

- 可以换成海鲈鱼。
"""


def test_parse_standard_recipe() -> None:
    recipe = parse_markdown(STANDARD_RECIPE, "dishes/aquatic/微波葱姜黑鳕鱼.md")

    assert recipe.title == "微波葱姜黑鳕鱼"
    assert recipe.category == "水产"
    assert recipe.total_minutes == 20
    assert recipe.servings == 2
    assert recipe.difficulty == "★★★"
    assert recipe.calories == "749 大卡"
    assert recipe.valid is True

    black_cod = next(item for item in recipe.ingredients if item.name == "黑鳕鱼")
    assert black_cod.amount_text == "2 片，450g"
    assert black_cod.note == "带皮"
    # “2 片，450g”同时有数量和重量，解析结果优先取重量，方便后续筛选和计算。
    assert black_cod.amount_min == 450
    assert black_cod.amount_max == 450
    assert black_cod.unit == "g"

    assert recipe.tools == ["sealed_bag"]
    assert recipe.steps[0] == "鱼片放入密封袋。"
    assert "取出鱼片" in recipe.steps[1]
    assert recipe.tips == ["可以换成海鲈鱼。"]


def test_calculation_range_and_optional_ingredient() -> None:
    text = """\
# 西红柿炒鸡蛋的做法

一道家常菜。从头备菜到盛盘出锅大约只需 15 分钟。

## 必备原料和工具

* 西红柿
* 鸡蛋
* 糖（可选）

## 计算

每次制作前需要确定计划做几份。一份正好够 1 个人食用

* 西红柿 = 1 个（约 180g） * 份数
* 盐 = 1.5-2g * 份数
* 糖 = 0-2g * 份数

## 操作

1. 西红柿切块。
2. 炒鸡蛋。

## 附加内容

- 无
"""
    recipe = parse_markdown(text, "dishes/vegetable_dish/西红柿炒鸡蛋.md")

    assert recipe.total_minutes == 15
    assert recipe.servings == 1
    assert recipe.valid is True

    salt = next(item for item in recipe.ingredients if item.name == "盐")
    assert salt.amount_min == 1.5
    assert salt.amount_max == 2
    assert salt.unit == "g"
    assert "仅出现在计算章节" in salt.note

    sugar = next(item for item in recipe.ingredients if item.name == "糖")
    assert sugar.optional is True
    assert sugar.amount_min == 0
    assert sugar.amount_max == 2


def test_amount_variants_from_real_recipes() -> None:
    text = """\
# 测试菜的做法

简单介绍。

## 必备原料和工具

- 食用油 15～20 ml
- 盐 10g，如果辣椒辣度高，建议多一点
- 美人椒 1/4 个
- 鸡蛋，2 个，打散
- 生粉 2 1/2 茶匙
- 葱、姜、蒜
- 注：这句是说明，不是原料

## 计算

每 2 份：

- 1 汤匙 = 15ml

## 操作

1. 炒熟。

## 附加内容

- 无
"""
    recipe = parse_markdown(text, "dishes/vegetable_dish/测试菜.md")
    by_name = {item.name: item for item in recipe.ingredients}

    oil = by_name["食用油"]
    assert (oil.amount_min, oil.amount_max, oil.unit) == (15, 20, "ml")

    salt = by_name["盐"]
    assert salt.amount_min == 10
    assert salt.note == "如果辣椒辣度高，建议多一点"

    pepper = by_name["美人椒"]
    assert pepper.amount_min == 0.25
    assert pepper.unit == "个"

    egg = by_name["鸡蛋"]
    assert egg.amount_min == 2
    assert egg.note == "打散"

    starch = by_name["生粉"]
    assert starch.amount_min == 2.5
    assert starch.unit == "茶匙"

    # 一行列了多个原料时拆成多条，说明行和单位换算行不会被当成原料。
    assert {"葱", "姜", "蒜"} <= set(by_name)
    assert not any(item.name.startswith("注：") for item in recipe.ingredients)
    assert "1 汤匙" not in by_name


def test_missing_sections_are_warnings_not_crash() -> None:
    text = """\
# 只有标题的菜

这里只有一句介绍。

## 附加内容

- 没有原料和步骤。
"""
    recipe = parse_markdown(text, "dishes/vegetable_dish/只有标题的菜.md")

    assert recipe.valid is False
    assert any("缺少章节：必备原料和工具" in warning for warning in recipe.warnings)
    assert any("缺少章节：操作" in warning for warning in recipe.warnings)
    assert any("没有识别到任何原料" in warning for warning in recipe.warnings)
    assert any("没有识别到任何步骤" in warning for warning in recipe.warnings)


def test_chinese_time_variants() -> None:
    cases = {
        "大约半小时即可完成。": 30,
        "新手大约一个半小时可以完成。": 90,
        "预计 1 小时 30 分钟完成。": 90,
        "大约二十分钟就能上桌。": 20,
    }
    for intro, expected in cases.items():
        text = f"""\
# 测试菜的做法

{intro}

## 必备原料和工具

- 鸡蛋

## 操作

1. 炒熟。

## 附加内容

- 无
"""
        recipe = parse_markdown(text, "dishes/vegetable_dish/测试菜.md")
        assert recipe.total_minutes == expected, intro


def test_tool_group_and_unknown_tool() -> None:
    text = """\
# 测试菜的做法

简单介绍。

## 必备原料和工具

- 鸡蛋

工具：

- 烤箱
- 神秘机器

## 操作

1. 烤熟。

## 附加内容

- 无
"""
    recipe = parse_markdown(text, "dishes/vegetable_dish/测试菜.md")

    assert recipe.tools == ["oven"]
    assert recipe.unknown_tools == ["神秘机器"]
    assert any("未识别厨具" in warning for warning in recipe.warnings)


def test_repository_scan_skips_template_and_reports_duplicates(tmp_path: Path) -> None:
    recipe_text = """\
# 同名菜的做法

简单介绍。

## 必备原料和工具

- 鸡蛋

## 操作

1. 炒熟。

## 附加内容

- 无
"""
    vegetable = tmp_path / "dishes" / "vegetable_dish" / "同名菜.md"
    meat = tmp_path / "dishes" / "meat_dish" / "同名菜.md"
    template = tmp_path / "dishes" / "template" / "示例菜.md"
    for path in (vegetable, meat, template):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(recipe_text, encoding="utf-8")

    report = parse_repository(tmp_path)

    assert report.total_files == 2
    assert report.parsed == 2
    assert report.failed == 0
    assert report.category_counts["素菜"] == 1
    assert report.category_counts["荤菜"] == 1
    assert report.duplicate_titles == {"同名菜": 2}
