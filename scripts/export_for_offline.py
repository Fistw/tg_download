#!/usr/bin/env python3
"""
导出用于离线高精度去重的数据

功能：
1. 从数据库读取去重任务的媒体信息
2. 导出缩略图文件
3. 导出媒体元数据（JSON格式）
4. 打包成 ZIP 文件便于传输

使用：
    python scripts/export_for_offline.py --task-id <task_id> --output <output_dir>
"""

import argparse
import json
import shutil
import zipfile
from pathlib import Path
from typing import Dict, List

# 尝试导入 tqdm，如果没有就做一个简单的替代
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, *args, **kwargs):
        return iterable

# 添加项目根目录到 PATH
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import DownloadDB


def export_task_data(
    task_id: int,
    output_dir: Path,
    db_path: str = "downloads.db"
) -> Path:
    """
    导出指定任务的数据

    Args:
        task_id: 去重任务 ID
        output_dir: 输出目录
        db_path: 数据库文件路径

    Returns:
        生成的 ZIP 文件路径
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 创建临时工作目录
    temp_dir = output_dir / f"task_{task_id}_offline"
    temp_dir.mkdir(exist_ok=True)
    thumbs_dir = temp_dir / "thumbnails"
    thumbs_dir.mkdir(exist_ok=True)

    db = DownloadDB(db_path)
    metadata: List[Dict] = []
    media_list = []

    # 分批获取所有媒体
    batch_size = 10000
    page = 1
    while True:
        batch, total = db.get_dedupe_media_list(task_id, page=page, limit=batch_size)
        if not batch:
            break
        media_list.extend(batch)
        page += 1
        print(f"📥 已获取 {len(media_list)}/{total} 个媒体...")
        if len(media_list) >= total:
            break

    print(f"📥 开始导出任务 {task_id} 的数据，共 {len(media_list)} 个媒体")

    for idx, media in enumerate(media_list):
        if idx % 5000 == 0:
            print(f"   进度: {idx}/{len(media_list)}")
        media_id = media["id"]
        file_id = media["file_id"]

        # 获取缩略图
        thumb_info = db.get_dedupe_media_thumbnail(task_id, media_id=media_id)
        thumb_path = thumb_info.get("thumbnail_path") if thumb_info else None
        has_thumbnail = False

        if thumb_path:
            try:
                # 读取缩略图数据
                thumb_data = db.thumbnail_store.load(thumb_path)
                if thumb_data:
                    # 保存缩略图文件
                    ext = Path(thumb_path).suffix or ".jpg"
                    thumb_filename = f"{file_id}{ext}"
                    thumb_file = thumbs_dir / thumb_filename

                    with open(thumb_file, "wb") as f:
                        f.write(thumb_data)

                    has_thumbnail = True
            except Exception as e:
                print(f"⚠️  媒体 {file_id} 缩略图导出失败: {e}")

        # 保存元数据
        metadata.append({
            "task_id": task_id,
            "media_id": media_id,
            "file_id": file_id,
            "file_size": media.get("file_size"),
            "duration": media.get("duration"),
            "width": media.get("width"),
            "height": media.get("height"),
            "first_seen_message_id": media.get("first_seen_message_id"),
            "first_seen_date": media.get("first_seen_date"),
            "has_thumbnail": has_thumbnail,
            "thumbnail_filename": thumb_filename if has_thumbnail else None,
        })

    # 保存元数据
    metadata_file = temp_dir / "metadata.json"
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    # 创建 ZIP 包
    zip_path = output_dir / f"task_{task_id}_offline.zip"

    print(f"📦 正在打包到 {zip_path}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        # 添加元数据
        zipf.write(metadata_file, metadata_file.name)

        # 添加缩略图
        for thumb_file in thumbs_dir.iterdir():
            if thumb_file.is_file():
                arcname = f"thumbnails/{thumb_file.name}"
                zipf.write(thumb_file, arcname)

    # 清理临时目录
    shutil.rmtree(temp_dir)

    print(f"✅ 导出完成！")
    print(f"📂 输出文件: {zip_path}")
    print(f"📊 导出媒体: {len(media_list)} 个")

    return zip_path


def main():
    parser = argparse.ArgumentParser(
        description="导出数据用于离线高精度去重"
    )
    parser.add_argument(
        "--task-id",
        type=int,
        required=True,
        help="去重任务 ID"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="offline_data",
        help="输出目录（默认: offline_data）"
    )
    parser.add_argument(
        "--db",
        type=str,
        default="downloads.db",
        help="数据库文件路径（默认: downloads.db）"
    )

    args = parser.parse_args()

    output_dir = Path(args.output)

    export_task_data(
        task_id=args.task_id,
        output_dir=output_dir,
        db_path=args.db
    )


if __name__ == "__main__":
    main()
