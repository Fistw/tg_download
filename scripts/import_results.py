#!/usr/bin/env python3
"""
导入离线高精度去重的结果

功能：
1. 读取离线计算的去重结果
2. 将分组信息导入到数据库
3. 更新 dedupe_level2 表

使用：
    python scripts/import_results.py --task-id <task_id> --input dedupe_results.zip
"""

import argparse
import json
import zipfile
from pathlib import Path
from typing import List, Dict, Optional

# 添加项目根目录到 PATH
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import DownloadDB


def import_dedupe_results(
    task_id: int,
    input_path: Path,
    db_path: str = "downloads.db",
    dry_run: bool = False
):
    """
    导入去重结果到数据库

    Args:
        task_id: 去重任务 ID
        input_path: 结果文件路径（JSON 或 ZIP）
        db_path: 数据库路径
        dry_run: 是否为试运行（不实际写入数据库）
    """
    # 读取结果数据
    if input_path.suffix == ".zip":
        print(f"📤 正在解压结果包: {input_path}")
        with zipfile.ZipFile(input_path, "r") as zipf:
            if "dedupe_results.json" not in zipf.namelist():
                raise Exception("ZIP 包中找不到 dedupe_results.json")
            with zipf.open("dedupe_results.json") as f:
                results = json.load(f)
    else:
        with open(input_path, "r", encoding="utf-8") as f:
            results = json.load(f)

    # 验证数据
    if "groups" not in results:
        raise Exception("结果格式不正确，缺少 'groups' 字段")

    groups = results["groups"]
    print(f"📊 读取到 {len(groups)} 个重复组")
    print(f"📌 相似度阈值: {results.get('similarity_threshold', 'N/A')}")

    if not groups:
        print("⚠️  没有发现重复组，结束")
        return

    # 连接数据库
    db = DownloadDB(db_path)

    print(f"\n🔄 准备导入到任务 {task_id}")
    if dry_run:
        print("⚠️  试运行模式，不会写入数据库")
    else:
        print("🗑️  清理旧的第二层去重结果")
        # 清理旧结果
        db.clear_dedupe_results(task_id)

    # 导入结果
    imported_count = 0
    for i, group in enumerate(groups):
        group_id = f"offline_group_{i}"
        primary_file_id = group["primary_file_id"]
        file_ids = group["file_ids"]

        if not dry_run:
            db.add_dedupe_level2(
                task_id=task_id,
                group_id=group_id,
                primary_level1_group_id=primary_file_id,
                level1_group_ids=file_ids,
                similarity_score=results.get("similarity_threshold", 0.95),
                hamming_distance=None  # CLIP 用余弦相似度，这里留空
            )

        imported_count += 1
        if imported_count % 10 == 0 or imported_count == len(groups):
            print(f"📥 已导入 {imported_count}/{len(groups)} 个组")

    print(f"\n✅ 导入完成！")
    print(f"📈 统计:")
    print(f"   - 导入的重复组: {imported_count}")
    print(f"   - 涉及媒体数: {sum(len(g['file_ids']) for g in groups)}")

    # 显示一些示例
    print(f"\n📋 前 5 个分组预览:")
    for i, group in enumerate(groups[:5]):
        print(f"   组 {i+1}: {len(group['file_ids'])} 个媒体 - {group['file_ids'][:3]}...")


def main():
    parser = argparse.ArgumentParser(
        description="导入离线高精度去重结果"
    )
    parser.add_argument(
        "--task-id",
        type=int,
        required=True,
        help="去重任务 ID"
    )
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="结果文件路径（dedupe_results.json 或 dedupe_results.zip）"
    )
    parser.add_argument(
        "--db",
        type=str,
        default="downloads.db",
        help="数据库文件路径（默认: downloads.db）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行模式，不写入数据库"
    )

    args = parser.parse_args()

    import_dedupe_results(
        task_id=args.task_id,
        input_path=Path(args.input),
        db_path=args.db,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
