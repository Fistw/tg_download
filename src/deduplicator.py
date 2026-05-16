from __future__ import annotations

import asyncio
import io
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

from telethon import TelegramClient
from telethon.tl.types import MessageMediaDocument

from .database import DownloadDB
from .limiter import FloodWaitCoordinator, get_flood_coordinator
from .downloader import download_message, _is_video
from .image_similarity import ImageSimilarity

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
        media_list, _ = self._db.get_dedupe_media_list(task_id, page, limit, search, filter_type)
        return media_list

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

    def compute_phashes_for_task(self, task_id: int) -> int:
        """
        为任务中的所有媒体计算感知哈希
        
        Args:
            task_id: 去重任务ID
            
        Returns:
            成功计算哈希的媒体数量
        """
        logger.info(f"开始为任务 {task_id} 计算感知哈希")
        
        # 获取该任务的所有媒体
        media_list, _ = self._db.get_dedupe_media_list(task_id, limit=10000)
        
        similarity = ImageSimilarity()
        count = 0
        
        for media in media_list:
            media_id = media['id']
            file_id = media['file_id']
            
            # 如果已经有phash则跳过
            if media.get('phash'):
                continue
                
            # 尝试获取缩略图
            thumbnail = self._db.get_dedupe_media_thumbnail(task_id, media_id=media_id)
            if thumbnail and thumbnail.get('thumbnail_path'):
                try:
                    # 从文件系统读取缩略图
                    thumbnail_data = self._db.thumbnail_store.load(thumbnail['thumbnail_path'])
                    if thumbnail_data:
                        phash = similarity.compute_hash(thumbnail_data)
                        if phash:
                            self._db.update_media_phash(task_id, file_id, phash)
                            count += 1
                            logger.debug(f"为媒体 {file_id} 计算哈希: {phash}")
                except Exception as e:
                    logger.debug(f"计算媒体 {file_id} 哈希失败: {e}")
        
        logger.info(f"任务 {task_id} 完成哈希计算，共 {count} 个媒体")
        return count

    def run_level2_dedupe(
        self,
        task_id: int,
        similarity_threshold: Optional[int] = None
    ) -> int:
        """
        运行第二层去重（基于图片相似度）
        
        Args:
            task_id: 去重任务ID
            similarity_threshold: 汉明距离阈值，默认使用 ImageSimilarity.DEFAULT_SIMILARITY_THRESHOLD
            
        Returns:
            第二层去重组数
        """
        logger.info(f"开始任务 {task_id} 第二层去重（基于图片相似度）")
        
        # 首先确保所有媒体都计算了感知哈希
        phash_count = self.compute_phashes_for_task(task_id)
        logger.info(f"任务 {task_id} 已计算 {phash_count} 个感知哈希")
        
        similarity = ImageSimilarity(
            similarity_threshold or ImageSimilarity.DEFAULT_SIMILARITY_THRESHOLD
        )
        
        # 先获取完整的两层去重汇总（包含第一层按 file_id 分组）
        summary = self._db.get_two_level_dedupe_summary(task_id)
        level1_groups = summary['level1_groups']
        
        # 获取所有有 phash 的媒体（按 file_id 索引）
        media_with_phash = self._db.get_media_with_phash(task_id)
        media_by_file_id = {m['file_id']: m for m in media_with_phash}
        
        # 为每个 level1 组分配代表哈希
        group_phashes: Dict[str, Dict[str, Any]] = {}
        for group in level1_groups:
            # 用组的 file_id 查找是否有 phash
            group_file_id = group['group_id']
            if group_file_id in media_by_file_id and media_by_file_id[group_file_id].get('phash'):
                group_phashes[group_file_id] = {
                    'phash': media_by_file_id[group_file_id]['phash'],
                    'group_id': group_file_id
                }
        
        # 对第一层组进行相似度分组
        used_groups = set()
        level2_groups = []
        
        group_ids = list(group_phashes.keys())
        for i, group_id1 in enumerate(group_ids):
            if group_id1 in used_groups:
                continue
                
            current_group = group_phashes[group_id1]
            similar_groups = [group_id1]
            used_groups.add(group_id1)
            min_distance = None
            
            for j in range(i + 1, len(group_ids)):
                group_id2 = group_ids[j]
                if group_id2 in used_groups:
                    continue
                    
                group2 = group_phashes[group_id2]
                
                # 计算相似度
                is_similar, distance = similarity.is_similar(
                    current_group['phash'], group2['phash']
                )
                
                if is_similar:
                    similar_groups.append(group_id2)
                    used_groups.add(group_id2)
                    if min_distance is None or distance < min_distance:
                        min_distance = distance
                    logger.debug(
                        f"组 {group_id1} 和 {group_id2} 相似，距离: {distance}"
                    )
            
            if len(similar_groups) > 1:
                # 计算相似度分数
                score = similarity.similarity_score(
                    current_group['phash'],
                    group_phashes[similar_groups[1]]['phash']
                )
                
                level2_groups.append({
                    'primary_group_id': group_id1,
                    'group_ids': similar_groups,
                    'similarity_score': score,
                    'hamming_distance': min_distance
                })
        
        # 清除旧的第二层结果并保存新的
        self._db.clear_dedupe_results(task_id)
        for i, lg in enumerate(level2_groups):
            self._db.add_dedupe_level2(
                task_id,
                f"level2_group_{i}",
                lg['primary_group_id'],
                lg['group_ids'],
                lg['similarity_score'],
                lg['hamming_distance']
            )
        
        logger.info(f"任务 {task_id} 第二层去重完成，共 {len(level2_groups)} 组")
        return len(level2_groups)

    def run_two_level_dedupe(
        self,
        task_id: int,
        similarity_threshold: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        运行完整的两层去重流程
        
        Args:
            task_id: 去重任务ID
            similarity_threshold: 汉明距离阈值
            
        Returns:
            去重汇总结果
        """
        logger.info(f"开始任务 {task_id} 完整两层去重流程")
        
        # 第二层去重（第一层在 get_two_level_dedupe_summary 中动态计算）
        # 注意：run_level2_dedupe 内部已经会先计算哈希
        level2_count = self.run_level2_dedupe(task_id, similarity_threshold)
        
        # 获取汇总结果
        summary = self._db.get_two_level_dedupe_summary(task_id)
        
        # 统计已计算的哈希数量
        media_with_phash = self._db.get_media_with_phash(task_id)
        
        logger.info(
            f"任务 {task_id} 两层去重完成: "
            f"{len(media_with_phash)} 个哈希, "
            f"{summary['level1_count']} 第一层组, "
            f"{level2_count} 第二层组"
        )
        
        return summary

    def get_two_level_dedupe_summary(self, task_id: int) -> Dict[str, Any]:
        """获取两层去重汇总结果"""
        return self._db.get_two_level_dedupe_summary(task_id)
