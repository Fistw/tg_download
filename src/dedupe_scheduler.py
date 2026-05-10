
from __future__ import annotations

import asyncio
import logging
from typing import Optional
from .database import DownloadDB
from .deduplicator import Deduplicator

logger = logging.getLogger(__name__)


class DedupeTaskScheduler:
    """独立的去重任务调度器，通过数据库与接口通信"""
    
    def __init__(self, db: DownloadDB, deduplicator: Deduplicator, check_interval: float = 2.0):
        self.db = db
        self.deduplicator = deduplicator
        self.check_interval = check_interval
        self.running = False
        self.running_tasks: dict[int, asyncio.Task] = {}
        self._main_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """启动任务调度器"""
        if self.running:
            logger.warning("任务调度器已经在运行中")
            return
        
        self.running = True
        logger.info("去重任务调度器已启动")
        self._main_task = asyncio.create_task(self._scheduler_loop())
    
    async def stop(self):
        """停止任务调度器"""
        if not self.running:
            return
        
        self.running = False
        
        # 取消所有运行中的任务
        for task_id, task in list(self.running_tasks.items()):
            if not task.done():
                logger.info(f"正在取消任务 {task_id}")
                task.cancel()
        
        # 等待所有任务完成
        if self.running_tasks:
            await asyncio.gather(*self.running_tasks.values(), return_exceptions=True)
        
        # 停止主调度循环
        if self._main_task and not self._main_task.done():
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass
        
        logger.info("去重任务调度器已停止")
    
    async def _scheduler_loop(self):
        """主调度循环"""
        while self.running:
            try:
                await self._check_and_process_tasks()
            except Exception as e:
                logger.exception(f"调度循环出错: {e}")
            
            # 等待下一次检查
            if self.running:
                await asyncio.sleep(self.check_interval)
    
    async def _check_and_process_tasks(self):
        """检查并处理待执行的任务"""
        try:
            # 获取所有任务
            all_tasks = self.db.list_dedupe_tasks()
            
            for task in all_tasks:
                task_id = task["id"]
                status = task["status"]
                
                # 检查是否是需要启动的任务
                if status == "pending":
                    logger.info(f"发现待执行任务 {task_id} ({task['chat_title']})，正在启动...")
                    await self._start_task(task_id)
                
                # 检查是否是已经完成但没有更新状态的任务
                elif status == "scanning" and task_id in self.running_tasks:
                    if self.running_tasks[task_id].done():
                        logger.warning(f"任务 {task_id} 已完成但状态未更新，正在清理...")
                        del self.running_tasks[task_id]
                
        except Exception as e:
            logger.exception(f"检查任务时出错: {e}")
    
    async def _start_task(self, task_id: int):
        """启动一个任务"""
        if task_id in self.running_tasks and not self.running_tasks[task_id].done():
            logger.warning(f"任务 {task_id} 已经在运行中")
            return
        
        # 更新任务状态为扫描中
        self.db.update_dedupe_task(task_id, status="scanning")
        
        # 启动任务
        task = asyncio.create_task(self._run_task_wrapper(task_id))
        self.running_tasks[task_id] = task
        
        logger.info(f"任务 {task_id} 已开始执行")
    
    async def _run_task_wrapper(self, task_id: int):
        """任务执行包装器，确保状态正确更新"""
        try:
            await self.deduplicator.scan_chat(task_id)
            
        except asyncio.CancelledError:
            logger.info(f"任务 {task_id} 被取消")
            # 重置为待执行状态
            self.db.update_dedupe_task(task_id, status="pending")
            raise
        
        except Exception as e:
            logger.exception(f"任务 {task_id} 执行失败: {e}")
            # 更新状态为失败
            self.db.update_dedupe_task(task_id, status="failed")
        
        finally:
            # 清理任务跟踪
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]

