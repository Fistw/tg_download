#!/usr/bin/env python3
from src.database import DownloadDB

db = DownloadDB()
tasks = db.list_dedupe_tasks()
print('当前任务状态:')
for task in tasks:
    print(f'Task {task["id"]} ({task["chat_title"]}):')
    print(f'  - 状态: {task["status"]}')
    print(f'  - 已处理消息: {task.get("processed_messages", 0)}')
    print(f'  - 最后扫描消息ID: {task.get("last_scanned_message_id")}')
    print()
