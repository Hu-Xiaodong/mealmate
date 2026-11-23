"""HowToCook 导入试运行命令。

用途：
在不写数据库的前提下扫描一份已解压的 HowToCook 仓库，输出解析统计和质量警告。
后台“数据导入”页面的试运行结果与这里的报告使用同一个解析器，避免两套逻辑。

使用方式（在 server 目录执行）：

    python scripts/howtocook_dry_run.py E:\\path\\to\\HowToCook
    python scripts/howtocook_dry_run.py E:\\path\\to\\HowToCook --json report.json

参数：
- root：仓库根目录，或 GitHub 压缩包解压后的唯一子目录；
- --json：把完整报告写入指定文件；
- --include-recipes：JSON 中附带每道菜的解析详情，文件会比较大；
- --strict：存在解析失败或缺少原料/步骤时返回非零退出码，便于自动化检查。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.services.howtocook_parser import RepositoryReport, parse_repository


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。

    单独抽成函数是为了测试可以复用，不需要启动整个命令行。
    """
    parser = argparse.ArgumentParser(description="HowToCook 菜谱导入试运行")
    parser.add_argument("root", type=Path, help="HowToCook 仓库根目录")
    parser.add_argument("--json", type=Path, help="把完整报告写入 JSON 文件")
    parser.add_argument(
        "--include-recipes",
        action="store_true",
        help="JSON 中附带每道菜的解析详情",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="存在解析失败或无效菜谱时返回非零退出码",
    )
    return parser


def print_summary(report: RepositoryReport) -> None:
    """在终端打印人可读的汇总。

    只打印关键指标和少量样例，完整数据通过 --json 输出，
    避免几百道菜的警告把终端刷满。
    """
    print("HowToCook 试运行报告")
    print("=" * 40)
    print(f"Markdown 文件：{report.total_files}")
    print(f"解析成功：{report.parsed}")
    print(f"解析失败：{report.failed}")
    print(f"缺少原料或步骤：{report.invalid}")
    print(f"警告总数：{report.warning_count}")
    print(f"未写总时长：{report.missing_time}")
    print(f"用量已数值化：{report.numeric_amounts}")
    print(f"用量为文本：{report.text_amounts}")
    print(f"原文未写用量：{report.missing_amounts}")
    print(
        "原料总数："
        f"{report.numeric_amounts + report.text_amounts + report.missing_amounts}"
    )

    if report.category_counts:
        print("\n分类分布：")
        for category, count in report.category_counts.most_common():
            print(f"  {category}：{count}")

    if report.duplicate_titles:
        print("\n重复标题：")
        for title, count in sorted(report.duplicate_titles.items()):
            print(f"  {title}：{count} 次")

    if report.unknown_tools:
        print("\n未识别厨具：")
        for tool, count in report.unknown_tools.most_common(20):
            print(f"  {tool}：{count} 次")

    if report.failures:
        print("\n解析失败样例：")
        for failure in report.failures[:10]:
            print(f"  {failure['path']}：{failure['reason']}")

    warnings = [
        (recipe.source_path, warning)
        for recipe in report.recipes
        for warning in recipe.warnings
    ]
    if warnings:
        print("\n警告样例：")
        for path, warning in warnings[:10]:
            print(f"  {path}：{warning}")


def main(argv: list[str] | None = None) -> int:
    """命令入口：解析参数、扫描仓库、输出报告。"""
    args = build_parser().parse_args(argv)
    try:
        report = parse_repository(args.root)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print_summary(report)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = report.to_dict(include_recipes=args.include_recipes)
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n完整报告已写入：{args.json}")

    if args.strict and (report.failed or report.invalid):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
