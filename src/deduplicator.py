from __future__ import annotations

import asyncio
import io
import logging
import time
from pathlib import Path
from typing import Optional

from telethon import TelegramClient
from telethon.tl.types import MessageMediaDocument

from .database import DownloadDB
from .limiter import FloodWaitCoordinator, get_flood_coordinator
from .downloader import download_message, _is_video

logger = logging.getLogger(__name__)


class Deduplicator:
    """去重管理器，支持扫描、去重和下载视频。"""

    def __init__(
        self,
        client: TelegramClient,
        db: DownloadDB,
        flood_coordinator: Optional[FloodWaitCoordinator] = None,
    ) -> None:
        self._client = client
        self._db = db
        self._flood_coordinator = flood_coordinator or get_flood_coordinator()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # 默认不暂停

    def create_task(
        self,
        chat_id: int,
        chat_title: Optional[str] = None,
        start_message_id: Optional[int] = None,
        total_messages: Optional[int] = None,
    ) -> int:
        """创建去重任务，返回任务 ID。"""
        return self._db.create_dedupe_task(chat_id, chat_title, start_message_id, total_messages)

    async def scan_chat(self, task_id: int) -> None:
        """扫描聊天记录，识别视频媒体。"""
        task = self._db.get_dedupe_task(task_id)
        if not task:
            raise ValueError(f"任务 {task_id} 不存在")

        chat_id = task["chat_id"]
        last_scanned_id = task["last_scanned_message_id"]
        processed = task.get("processed_messages", 0) or 0
        
        logger.info(f"[任务 {task_id}] 开始扫描聊天 {chat_id} ({task.get('chat_title', '未知')})，从消息 ID {last_scanned_id or '开始'} 开始")
        self._db.update_dedupe_task(task_id, status="scanning")
        
        try:
            # 构建迭代参数，避免传入 None
            iter_kwargs = {}
            if last_scanned_id is not None and last_scanned_id > 0:
                iter_kwargs["offset_id"] = last_scanned_id
            iter_kwargs["reverse"] = False
            
            # 用于批量更新的临时变量
            pending_updates = {
                'last_scanned_message_id': last_scanned_id,
                'processed_messages': processed
            }
            media_batch = []  # 批量存储媒体信息
            result_batch = []  # 批量存储结果
            
            # 记录开始时间
            start_time = time.time()
            
            async for message in self._client.iter_messages(chat_id, **iter_kwargs):
                await self._pause_event.wait()
                
                # 每次迭代都让出事件循环，确保其他请求能够处理
                await asyncio.sleep(0)

                if message is None:
                    continue
                
                # 增加处理计数
                processed += 1
                pending_updates['processed_messages'] = processed
                pending_updates['last_scanned_message_id'] = message.id
                
                if _is_video(message):
                    doc = message.media.document
                    file_id = str(doc.id)
                    file_size = doc.size
                    duration = None
                    width = None
                    height = None
                    thumbnail_data = None
                    thumbnail_width = None
                    thumbnail_height = None

                    for attr in doc.attributes:
                        if type(attr).__name__ == "DocumentAttributeVideo":
                            duration = getattr(attr, "duration", None)
                            width = getattr(attr, "w", None)
                            height = getattr(attr, "h", None)
                            break
                    
                    # 尝试下载缩略图
                    try:
                        thumbnail_data = None
                        thumbnail_width = None
                        thumbnail_height = None
                        
                        if doc.thumbs and len(doc.thumbs) > 0:
                            # 选择最大的缩略图
                            thumb = doc.thumbs[-1]
                            logger.info(f"[任务 {task_id}] 发现视频 {file_id} 有缩略图，正在下载...")
                            
                            # 尝试多种方法下载缩略图
                            import tempfile
                            import os
                            
                            # 辅助函数：带超时的缩略图下载
                            async def download_thumb_with_timeout(download_func, timeout_seconds=30):
                                try:
                                    # 使用 asyncio.wait_for 设置超时
                                    return await asyncio.wait_for(download_func(), timeout=timeout_seconds)
                                except asyncio.TimeoutError:
                                    logger.warning(f"[任务 {task_id}] 缩略图下载超时（{timeout_seconds}秒）: {file_id}")
                                    return None
                                except Exception as e:
                                    logger.debug(f"[任务 {task_id}] 缩略图下载异常: {e}")
                                    return None
                            
                            # 方法1: 使用 thumb=-1 参数 (首选方法)
                            temp_path = None
                            try:
                                temp_path = tempfile.mktemp(suffix='.jpg')
                                logger.debug(f"[任务 {task_id}] 尝试下载缩略图 (方法1: thumb=-1)")
                                
                                async def method1():
                                    return await self._client.download_media(message, thumb=-1, file=temp_path)
                                
                                result_path = await download_thumb_with_timeout(method1, 20)
                                
                                if result_path and os.path.exists(result_path) and os.path.getsize(result_path) > 0:
                                    with open(result_path, 'rb') as f:
                                        thumbnail_data = f.read()
                                    
                                    if thumbnail_data:
                                        thumbnail_width = getattr(thumb, 'w', None)
                                        thumbnail_height = getattr(thumb, 'h', None)
                                        logger.info(f"[任务 {task_id}] 成功获取到视频缩略图 (方法1): {file_id}, 大小: {len(thumbnail_data)} 字节, 尺寸: {thumbnail_width}x{thumbnail_height}")
                            except Exception as e:
                                logger.warning(f"[任务 {task_id}] 缩略图下载方法1失败: {e}")
                            finally:
                                if temp_path and os.path.exists(temp_path):
                                    try:
                                        os.remove(temp_path)
                                    except:
                                        pass
                            
                            # 如果方法1失败，尝试方法2: 使用 thumb 索引
                            if not thumbnail_data:
                                try:
                                    temp_path = tempfile.mktemp(suffix='.jpg')
                                    logger.debug(f"[任务 {task_id}] 尝试下载缩略图 (方法2: thumb=索引)")
                                    
                                    async def method2():
                                        return await self._client.download_media(message, thumb=len(doc.thumbs)-1, file=temp_path)
                                    
                                    result_path = await download_thumb_with_timeout(method2, 20)
                                    
                                    if result_path and os.path.exists(result_path) and os.path.getsize(result_path) > 0:
                                        with open(result_path, 'rb') as f:
                                            thumbnail_data = f.read()
                                        
                                        if thumbnail_data:
                                            thumbnail_width = getattr(thumb, 'w', None)
                                            thumbnail_height = getattr(thumb, 'h', None)
                                            logger.info(f"[任务 {task_id}] 成功获取到视频缩略图 (方法2): {file_id}, 大小: {len(thumbnail_data)} 字节, 尺寸: {thumbnail_width}x{thumbnail_height}")
                                except Exception as e:
                                    logger.warning(f"[任务 {task_id}] 缩略图下载方法2失败: {e}")
                                finally:
                                    if temp_path and os.path.exists(temp_path):
                                        try:
                                            os.remove(temp_path)
                                        except:
                                            pass
                            
                            # 如果方法2也失败，尝试方法3: 直接使用 document
                            if not thumbnail_data:
                                try:
                                    temp_path = tempfile.mktemp(suffix='.jpg')
                                    logger.debug(f"[任务 {task_id}] 尝试下载缩略图 (方法3: 使用 document)")
                                    
                                    async def method3():
                                        if message.media:
                                            return await self._client.download_media(message.media, thumb=-1, file=temp_path)
                                        return None
                                    
                                    result_path = await download_thumb_with_timeout(method3, 20)
                                    
                                    if result_path and os.path.exists(result_path) and os.path.getsize(result_path) > 0:
                                        with open(result_path, 'rb') as f:
                                            thumbnail_data = f.read()
                                        
                                        if thumbnail_data:
                                            thumbnail_width = getattr(thumb, 'w', None)
                                            thumbnail_height = getattr(thumb, 'h', None)
                                            logger.info(f"[任务 {task_id}] 成功获取到视频缩略图 (方法3): {file_id}, 大小: {len(thumbnail_data)} 字节, 尺寸: {thumbnail_width}x{thumbnail_height}")
                                except Exception as e:
                                    logger.warning(f"[任务 {task_id}] 缩略图下载方法3失败: {e}")
                                finally:
                                    if temp_path and os.path.exists(temp_path):
                                        try:
                                            os.remove(temp_path)
                                        except:
                                            pass
                            
                            if not thumbnail_data:
                                logger.warning(f"[任务 {task_id}] 所有缩略图下载方法都失败了: {file_id}")
                        else:
                            logger.info(f"[任务 {task_id}] 视频 {file_id} 没有缩略图")
                    except Exception as e:
                        logger.error(f"[任务 {task_id}] 获取缩略图失败: {e}")
                        thumbnail_data = None
                        thumbnail_width = None
                        thumbnail_height = None
                    
                    # 批量收集数据而不是立即写入
                    media_batch.append({
                        'task_id': task_id,
                        'file_id': file_id,
                        'file_size': file_size,
                        'duration': duration,
                        'width': width,
                        'height': height,
                        'first_seen_message_id': message.id,
                        'first_seen_date': message.date.isoformat() if message.date else None,
                        'thumbnail_data': thumbnail_data,
                        'thumbnail_width': thumbnail_width,
                        'thumbnail_height': thumbnail_height,
                    })
                    
                    result_batch.append({
                        'task_id': task_id,
                        'message_id': message.id,
                        'file_id': file_id,
                        'is_duplicate': False,
                        'is_original': True
                    })
                
                # 每 50 条消息批量更新一次，减少数据库访问频率，并且让出事件循环
                if processed % 50 == 0:
                    # 批量写入数据库
                    self._batch_write_to_db(task_id, media_batch, result_batch)
                    
                    # 清空批处理队列
                    media_batch = []
                    result_batch = []
                    
                    # 更新任务进度
                    self._db.update_dedupe_task(
                        task_id,
                        last_scanned_message_id=pending_updates['last_scanned_message_id'],
                        processed_messages=pending_updates['processed_messages'],
                    )
                    
                    # 记录进度日志
                    elapsed_seconds = time.time() - start_time
                    msg_per_sec = processed / elapsed_seconds if elapsed_seconds > 0 else 0
                    logger.info(f"[任务 {task_id}] 已扫描 {processed} 条消息，当前消息 ID {message.id}，速度: {msg_per_sec:.2f} msg/s")
                    
                    # 显式让出控制权
                    await asyncio.sleep(0)
                
                await self._flood_coordinator.wait_if_needed()
            
            # 处理剩余的批量数据
            if media_batch or result_batch:
                self._batch_write_to_db(task_id, media_batch, result_batch)
            
            # 最终更新任务状态
            self._db.update_dedupe_task(
                task_id,
                status="completed",
                processed_messages=processed,
            )
            
            total_time = time.time() - start_time
            msg_per_sec = processed / total_time if total_time > 0 else 0
            logger.info(f"[任务 {task_id}] 扫描完成！共处理 {processed} 条消息，耗时 {total_time:.2f} 秒，平均 {msg_per_sec:.2f} msg/s")

        except asyncio.CancelledError:
            # 处理剩余的批量数据
            if media_batch or result_batch:
                try:
                    self._batch_write_to_db(task_id, media_batch, result_batch)
                except Exception as e:
                    logger.error(f"[任务 {task_id}] 取消任务后保存剩余数据时出错: {e}")
            
            self._db.update_dedupe_task(task_id, status="pending")
            logger.info(f"[任务 {task_id}] 扫描已取消，重置为 pending 状态")
            raise
        except Exception as e:
            # 处理剩余的批量数据
            if media_batch or result_batch:
                try:
                    self._batch_write_to_db(task_id, media_batch, result_batch)
                except Exception as save_err:
                    logger.error(f"[任务 {task_id}] 保存剩余数据时出错: {save_err}")
            
            self._db.update_dedupe_task(task_id, status="failed")
            logger.exception(f"[任务 {task_id}] 扫描失败: {e}")
            raise

    def _batch_write_to_db(self, task_id: int, media_batch: list, result_batch: list) -> None:
        """批量写入数据到数据库"""
        if not media_batch and not result_batch:
            return
            
        logger.debug(f"[任务 {task_id}] 批量写入 {len(media_batch)} 条媒体，{len(result_batch)} 条结果")
        
        # 使用批量方法，大幅提升性能
        if media_batch:
            self._db.batch_add_dedupe_media(media_batch)
        
        if result_batch:
            self._db.batch_add_dedupe_results(result_batch)

    def pause_scan(self) -> None:
        """暂停扫描。"""
        self._pause_event.clear()
        logger.info("扫描已暂停")

    def resume_scan(self) -> None:
        """恢复扫描。"""
        self._pause_event.set()
        logger.info("扫描已恢复")

    def get_media_list(
        self,
        task_id: int,
        page: int = 1,
        limit: int = 20,
        search: Optional[str] = None,
        filter_type: str = "all",
    ) -> list[dict]:
        """获取媒体列表。"""
        return self._db.get_dedupe_media_list(task_id, page, limit, search, filter_type)

    async def download_media(
        self,
        task_id: int,
        output_dir: str | Path,
        file_id: Optional[str] = None,
        download_all: bool = False,
    ) -> int:
        """下载去重后的视频。

        Args:
            task_id: 去重任务 ID
            output_dir: 输出目录
            file_id: 指定下载单个文件的 file_id
            download_all: 是否下载所有去重后的文件

        Returns:
            下载的文件数量
        """
        task = self._db.get_dedupe_task(task_id)
        if not task:
            raise ValueError(f"任务 {task_id} 不存在")

        chat_id = task["chat_id"]
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 获取要下载的媒体列表
        if download_all:
            media_list = self._db.get_dedupe_media_list(task_id, filter_type="singles")
            # 同时获取重复文件的第一个出现
            duplicates = self._db.get_dedupe_media_list(task_id, filter_type="duplicates")
            media_list.extend(duplicates)
        elif file_id:
            media = self._db.get_dedupe_media(task_id, file_id)
            media_list = [media] if media else []
        else:
            raise ValueError("必须指定 file_id 或设置 download_all=True")

        downloaded_count = 0

        for media in media_list:
            if media is None:
                continue

            message_id = media["first_seen_message_id"]
            try:
                message = await self._client.get_messages(chat_id, ids=message_id)
                if message and _is_video(message):
                    await self._flood_coordinator.wait_if_needed()
                    result = await download_message(
                        self._client,
                        message,
                        output_dir,
                        flood_coordinator=self._flood_coordinator,
                    )
                    if result:
                        downloaded_count += 1
                        logger.info("已下载: %s", result)
            except Exception as e:
                logger.error("下载消息 %d 失败: %s", message_id, e)
                continue

        return downloaded_count
