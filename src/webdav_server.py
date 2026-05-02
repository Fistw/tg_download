from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

try:
    from wsgidav import wsgidav_app
    from wsgidav.fs_dav_provider import FilesystemProvider
    from wsgidav.mw.cors import Cors
    from wsgidav.wsgidav_app import WsgiDAVApp
    WEBDAV_AVAILABLE = True
except ImportError:
    WEBDAV_AVAILABLE = False
    wsgidav_app = None
    FilesystemProvider = None
    Cors = None
    WsgiDAVApp = None

from src.config import WebDAVServerConfig

logger = logging.getLogger(__name__)


class WebDAVServer:
    def __init__(self, config: WebDAVServerConfig, download_dir: str):
        self.config = config
        self.download_dir = download_dir
        self._server_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._app = None

    def _get_mount_dir(self) -> Path:
        """获取实际挂载的目录"""
        if self.config.directory:
            return Path(self.config.directory)
        return Path(self.download_dir)

    def _build_config(self) -> dict:
        """构建 WsgiDAV 配置"""
        if not WEBDAV_AVAILABLE:
            raise RuntimeError("WebDAV 依赖未安装，请运行: pip install tg-download[nas]")

        mount_dir = self._get_mount_dir()
        mount_dir.mkdir(parents=True, exist_ok=True)

        # 从默认配置开始
        config = wsgidav_app.DEFAULT_CONFIG.copy()

        # 更新我们的配置
        config.update({
            "host": self.config.host,
            "port": self.config.port,
            "provider_mapping": {self.config.mount_path: FilesystemProvider(str(mount_dir))},
            "verbose": 1,
        })

        # 如果配置了用户名和密码，启用 HTTP 基本认证
        if self.config.username and self.config.password:
            config["http_authenticator"] = {
                "accept_basic": True,
                "accept_digest": False,
                "default_to_digest": False,
            }
            config["simple_dc"] = {
                "user_mapping": {
                    self.config.mount_path: {
                        self.config.username: {"password": self.config.password},
                    },
                },
            }
        else:
            config["http_authenticator"] = None
            config["simple_dc"] = None

        return config

    def _run_server(self):
        """在独立线程中运行服务器"""
        if not WEBDAV_AVAILABLE:
            logger.error("WebDAV 依赖未安装，无法启动服务器")
            return

        try:
            from cheroot import wsgi

            config = self._build_config()
            self._app = WsgiDAVApp(config)

            server = wsgi.Server(
                (self.config.host, self.config.port),
                self._app,
                numthreads=10,
            )

            logger.info(f"WebDAV 服务器启动在 http://{self.config.host}:{self.config.port}{self.config.mount_path}")
            logger.info(f"挂载目录: {self._get_mount_dir()}")

            try:
                server.start()
            except Exception as e:
                if not self._stop_event.is_set():
                    logger.error(f"WebDAV 服务器错误: {e}")
            finally:
                logger.info("WebDAV 服务器已停止")
        except ImportError:
            logger.error("cheroot 依赖未安装，请运行: pip install tg-download[nas]")

    def start(self):
        """启动 WebDAV 服务器"""
        if not self.config.enable:
            logger.info("WebDAV 服务器未启用，跳过启动")
            return

        if not WEBDAV_AVAILABLE:
            logger.warning("WebDAV 依赖未安装，无法启动服务器")
            logger.warning("请运行: pip install tg-download[nas]")
            return

        if self._server_thread and self._server_thread.is_alive():
            logger.warning("WebDAV 服务器已在运行")
            return

        self._stop_event.clear()
        self._server_thread = threading.Thread(target=self._run_server, daemon=True)
        self._server_thread.start()

    def stop(self):
        """停止 WebDAV 服务器"""
        if not self._server_thread or not self._server_thread.is_alive():
            return

        logger.info("正在停止 WebDAV 服务器...")
        self._stop_event.set()

        # 尝试优雅停止
        try:
            import requests

            # 发送一个请求来中断服务器
            requests.get(f"http://127.0.0.1:{self.config.port}/", timeout=1)
        except Exception:
            pass

        self._server_thread.join(timeout=5)
        if self._server_thread.is_alive():
            logger.warning("WebDAV 服务器未能在 5 秒内停止")
