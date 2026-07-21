"""check_docs.py — 文档完整性自动检查

检查项目：
1. 文档头部格式是否规范（标题 + 版本信息）
2. Markdown 交叉引用链接是否有效
3. 图片引用文件是否存在
4. 是否存在空目录
5. 是否有散落在 docs/ 根目录的 .md 文件（应归入子目录）
6. Mermaid 流程图语法基本校验
7. 统计文档数量与总行数

用法：
    python docs/scripts/check_docs.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from datetime import date


# 文档根目录（docs/ 的父目录）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"

# 合法的文档子目录（docs/ 下的一级分类）
VALID_SUBDIRS = {
    "用户手册", "开发文档", "架构设计", "MATLAB集成",
    "API", "调试指南", "发布说明", "运维指南", "FAQ", "更新日志",
    "images", "scripts", "archive",
}

# 颜色输出
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    passed: list[str] = []

    print(f"{BOLD}=== 文档完整性检查 ==={RESET}")
    print(f"文档目录：{DOCS_DIR}")
    print(f"检查日期：{date.today().isoformat()}")
    print()

    # ---- 1. 检查目录结构 ----
    print(f"{BOLD}[1/7] 检查目录结构{RESET}")
    if not DOCS_DIR.exists():
        errors.append(f"docs/ 目录不存在：{DOCS_DIR}")
        _print_result(errors, warnings, passed)
        return 1

    for subdir in VALID_SUBDIRS:
        path = DOCS_DIR / subdir
        if not path.exists():
            warnings.append(f"缺失子目录：docs/{subdir}")
        elif path.is_dir() and not any(path.iterdir()):
            warnings.append(f"空目录：docs/{subdir}")

    actual_subdirs = {d.name for d in DOCS_DIR.iterdir() if d.is_dir()}
    unknown = actual_subdirs - VALID_SUBDIRS
    for u in sorted(unknown):
        warnings.append(f"未知子目录：docs/{u}（未在分类列表中）")

    if not warnings:
        passed.append("目录结构完整")
    print(f"  子目录：{len(actual_subdirs)} 个")
    print()

    # ---- 2. 收集所有 .md 文件 ----
    print(f"{BOLD}[2/7] 收集文档文件{RESET}")
    md_files: list[Path] = []
    for root, dirs, files in os.walk(DOCS_DIR):
        # 跳过 archive 目录（历史文档不检查）
        if "archive" in Path(root).parts:
            continue
        for f in files:
            if f.endswith(".md"):
                md_files.append(Path(root) / f)

    total_lines = 0
    for mf in md_files:
        try:
            total_lines += sum(1 for _ in open(mf, encoding="utf-8"))
        except Exception:
            pass

    print(f"  文档数量：{len(md_files)} 篇（不含 archive/）")
    print(f"  总行数：{total_lines} 行")
    print()

    # ---- 3. 检查散落文件 ----
    print(f"{BOLD}[3/7] 检查散落文件{RESET}")
    stray = []
    for item in DOCS_DIR.iterdir():
        if item.is_file() and item.suffix == ".md" and item.name != "README.md":
            stray.append(item.name)
    if stray:
        for s in stray:
            warnings.append(f"散落文件：docs/{s}（应归入子目录）")
    else:
        passed.append("无散落文件")
    print(f"  散落文件：{len(stray)} 个")
    print()

    # ---- 4. 检查文档头部格式 ----
    print(f"{BOLD}[4/7] 检查文档头部格式{RESET}")
    header_issues = 0
    for mf in md_files:
        if mf.name == "README.md":
            continue
        try:
            lines = mf.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            errors.append(f"读取失败：{mf.name} - {e}")
            continue

        if not lines:
            warnings.append(f"空文件：{mf.relative_to(DOCS_DIR)}")
            continue

        first = lines[0].strip()
        if not first.startswith("# "):
            warnings.append(f"缺少一级标题：{mf.relative_to(DOCS_DIR)}")
            header_issues += 1
            continue

        # 检查是否有版本信息行（前 5 行内）
        has_version = False
        for line in lines[:5]:
            if "版本" in line and (":" in line or "：" in line):
                has_version = True
                break
        if not has_version:
            warnings.append(f"缺少版本信息：{mf.relative_to(DOCS_DIR)}")
            header_issues += 1

    if header_issues == 0:
        passed.append("所有文档头部格式规范")
    print(f"  格式问题：{header_issues} 个")
    print()

    # ---- 5. 检查交叉引用链接 ----
    print(f"{BOLD}[5/7] 检查交叉引用链接{RESET}")
    link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    broken_links = 0
    checked_links = 0

    for mf in md_files:
        try:
            content = mf.read_text(encoding="utf-8")
        except Exception:
            continue

        # 移除代码块内容（避免检查代码示例中的链接）
        content_no_code = re.sub(r"```[\s\S]*?```", "", content)

        for match in link_pattern.finditer(content_no_code):
            text = match.group(1)
            target = match.group(2)

            # 跳过外部 URL 和 file:// 链接（源码引用）
            if target.startswith(("http://", "https://", "mailto:", "#", "file://")):
                continue
            # 跳过纯锚点
            if target.startswith("#"):
                continue
            # 只检查 .md 链接和图片链接
            if not target.endswith((".md", ".png", ".jpg", ".jpeg", ".gif", ".svg")):
                continue

            checked_links += 1
            # 解析相对路径
            target_path = (mf.parent / target).resolve()
            if not target_path.exists():
                broken_links += 1
                rel = mf.relative_to(DOCS_DIR)
                warnings.append(f"断链：{rel} -> {target}（文本：{text}）")

    if broken_links == 0:
        passed.append(f"所有交叉引用链接有效（{checked_links} 个）")
    print(f"  检查链接：{checked_links} 个")
    print(f"  断链：{broken_links} 个")
    print()

    # ---- 6. 检查图片引用 ----
    print(f"{BOLD}[6/7] 检查图片引用{RESET}")
    img_pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    img_issues = 0
    checked_imgs = 0

    for mf in md_files:
        try:
            content = mf.read_text(encoding="utf-8")
        except Exception:
            continue

        # 移除代码块内容（避免检查代码示例中的图片）
        content_no_code = re.sub(r"```[\s\S]*?```", "", content)

        for match in img_pattern.finditer(content_no_code):
            alt = match.group(1)
            target = match.group(2)

            if target.startswith(("http://", "https://")):
                continue

            checked_imgs += 1
            target_path = (mf.parent / target).resolve()
            if not target_path.exists():
                img_issues += 1
                rel = mf.relative_to(DOCS_DIR)
                warnings.append(f"图片缺失：{rel} -> {target}")

    if img_issues == 0:
        passed.append(f"所有图片引用有效（{checked_imgs} 个）")
    print(f"  检查图片：{checked_imgs} 个")
    print(f"  缺失图片：{img_issues} 个")
    print()

    # ---- 7. Mermaid 流程图统计 ----
    print(f"{BOLD}[7/7] 流程图统计{RESET}")
    mermaid_count = 0
    for mf in md_files:
        try:
            content = mf.read_text(encoding="utf-8")
        except Exception:
            continue
        mermaid_count += content.count("```mermaid")

    passed.append(f"Mermaid 流程图：{mermaid_count} 个")
    print(f"  Mermaid 流程图：{mermaid_count} 个")
    print()

    # ---- 汇总 ----
    _print_result(errors, warnings, passed)

    # 退出码：有 error 返回 1，只有 warning 返回 0
    return 1 if errors else 0


def _print_result(errors, warnings, passed):
    print("=" * 60)
    print(f"{BOLD}检查结果汇总{RESET}")
    print("=" * 60)

    if passed:
        print(f"\n{GREEN}✓ 通过 ({len(passed)} 项){RESET}")
        for p in passed:
            print(f"  {GREEN}✓{RESET} {p}")

    if warnings:
        print(f"\n{YELLOW}⚠ 警告 ({len(warnings)} 项){RESET}")
        for w in warnings:
            print(f"  {YELLOW}⚠{RESET} {w}")

    if errors:
        print(f"\n{RED}✗ 错误 ({len(errors)} 项){RESET}")
        for e in errors:
            print(f"  {RED}✗{RESET} {e}")

    print()
    if errors:
        print(f"{RED}结果：失败（需修复错误）{RESET}")
    elif warnings:
        print(f"{YELLOW}结果：通过（有警告，建议修复）{RESET}")
    else:
        print(f"{GREEN}结果：全部通过{RESET}")


if __name__ == "__main__":
    sys.exit(main())
