#!/usr/bin/env python3
from src.database import DownloadDB

db = DownloadDB()

task_id = 3
print(f'任务 {task_id} 的去重结果:')
print('=' * 50)

media_list = db.get_dedupe_media_list(task_id)

total_media = len(media_list)
unique_count = 0
duplicate_count = 0
for media in media_list:
    if media.get('occurrence_count', 1) > 1:
        duplicate_count += 1
    else:
        unique_count += 1

print(f'总媒体数: {total_media}')
print(f'独立媒体: {unique_count}')
print(f'重复媒体: {duplicate_count}')
print()
print('媒体列表:')
print('-' * 50)
for i, media in enumerate(media_list[:10]):  # 只显示前10个
    print(f'{i+1}. File ID: {media["file_id"]}')
    print(f'   出现次数: {media.get("occurrence_count", 1)}')
    print(f'   尺寸: {media.get("width")}x{media.get("height")}')
    print(f'   有缩略图: {"是" if media.get("has_thumbnail") else "否"}')
    print()

if len(media_list) > 10:
    print(f'... 还有 {len(media_list) - 10} 个媒体')
