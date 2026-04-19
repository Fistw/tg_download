from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, Callable

try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False
    paramiko = None

try:
    from webdavclient3 import Client as WebDAVClient
    WEBDAV_CLIENT_AVAILABLE = True
except ImportError:
    WEBDAV_CLIENT_AVAILABLE = False
    WebDAVClient = None

from src.config import NASSyncConfig

logger = logging.getLogger(__name__)

SyncCallback = Optional[Callable[[bool, str], None]]


class NASSyncer:
    def __init__(self, config: NASSyncConfig):
        self.config = config

    async def sync_file(self, local_path: Path, callback: SyncCallback = None) -> bool:
        """同步单个文件到 NAS"""
        if not self.config.enable:
            if callback:
                callback(True, "NAS 同步未启用")
            return True

        try:
            if self.config.sync_type == "webdav":
                success = await self._sync_webdav(local_path)
            elif self.config.sync_type == "sftp":
                success = await self._sync_sftp(local_path)
            else:
                logger.error(f"不支持的同步类型: {self.config.sync_type}")
                if callback:
                    callback(False, f"不支持的同步类型: {self.config.sync_type}")
                return False

            if success and self.config.delete_after_sync:
                try:
                    local_path.unlink()
                    logger.info(f"已删除本地文件: {local_path}")
                except Exception as e:
                    logger.warning(f"删除本地文件失败: {e}")

            if callback:
                callback(success, "同步成功" if success else "同步失败")

            return success
        except Exception as e:
            logger.error(f"同步文件失败: {e}")
            if callback:
                callback(False, f"同步失败: {e}")
            return False

    async def _sync_webdav(self, local_path: Path) -> bool:
        """使用 WebDAV 同步文件"""
        if not WEBDAV_CLIENT_AVAILABLE:
            logger.error("WebDAV 客户端依赖未安装，请运行: pip install tg-download[nas]")
            return False

        for attempt in range(self.config.max_retries):
            try:
                options = {
                    "webdav_hostname": self.config.webdav_url,
                    "webdav_login": self.config.webdav_username,
                    "webdav_password": self.config.webdav_password,
                }
                client = WebDAVClient(options)

                # 确保远程目录存在
                remote_path = self.config.webdav_remote_path
                if not client.check(remote_path):
                    client.mkdir(remote_path)

                remote_file_path = os.path.join(remote_path, local_path.name)
                logger.info(f"WebDAV 上传: {local_path} -> {remote_file_path}")

                # 在单独的线程中执行上传以避免阻塞
                await asyncio.to_thread(client.upload_sync, remote_file_path, str(local_path))

                logger.info(f"WebDAV 上传成功: {local_path}")
                return True
            except Exception as e:
                logger.warning(f"WebDAV 上传失败 (尝试 {attempt + 1}/{self.config.max_retries}): {e}")
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay_seconds)
        return False

    async def _sync_sftp(self, local_path: Path) -> bool:
        """使用 SFTP 同步文件"""
        if not PARAMIKO_AVAILABLE:
            logger.error("SFTP 客户端依赖未安装，请运行: pip install tg-download[nas]")
            return False

        for attempt in range(self.config.max_retries):
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                connect_kwargs = {
                    "hostname": self.config.sftp_host,
                    "port": self.config.sftp_port,
                    "username": self.config.sftp_username,
                }

                if self.config.sftp_key_path:
                    connect_kwargs["key_filename"] = self.config.sftp_key_path
                elif self.config.sftp_password:
                    connect_kwargs["password"] = self.config.sftp_password

                await asyncio.to_thread(ssh.connect, **connect_kwargs)

                sftp = ssh.open_sftp()

                # 确保远程目录存在
                remote_path = self.config.sftp_remote_path
                try:
                    sftp.stat(remote_path)
                except FileNotFoundError:
                    # 尝试创建目录
                    try:
                        sftp.mkdir(remote_path)
                    except Exception as mkdir_err:
                        logger.warning(f"创建远程目录失败: {mkdir_err}")

                remote_file_path = os.path.join(remote_path, local_path.name)
                logger.info(f"SFTP 上传: {local_path} -> {remote_file_path}")

                await asyncio.to_thread(sftp.put, str(local_path), remote_file_path)

                sftp.close()
                ssh.close()

                logger.info(f"SFTP 上传成功: {local_path}")
                return True
            except Exception as e:
                logger.warning(f"SFTP 上传失败 (尝试 {attempt + 1}/{self.config.max_retries}): {e}")
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay_seconds)
        return False
