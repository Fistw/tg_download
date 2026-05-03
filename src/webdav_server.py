from __future__ import annotations

import json
import logging
import mimetypes
import os
import threading
import time
from pathlib import Path
from typing import Optional, Callable
from wsgiref.simple_server import make_server, WSGIServer

try:
    from wsgidav import wsgidav_app
    from wsgidav.fs_dav_provider import FilesystemProvider
    from wsgidav.wsgidav_app import WsgiDAVApp
    WEBDAV_AVAILABLE = True
except ImportError:
    WEBDAV_AVAILABLE = False
    wsgidav_app = None
    FilesystemProvider = None
    WsgiDAVApp = None

from src.config import WebDAVServerConfig

logger = logging.getLogger(__name__)

# 全局监控实例
_monitoring_db = None


def set_monitoring_db(db):
    """设置监控数据库实例"""
    global _monitoring_db
    _monitoring_db = db


def get_system_metrics() -> dict:
    """获取系统指标（简化版）"""
    mem_percent = 0
    cpu_percent = 0
    
    try:
        # 尝试使用 psutil
        import psutil
        mem_percent = psutil.virtual_memory().percent
        cpu_percent = psutil.cpu_percent()
    except ImportError:
        pass
    
    return {
        "memory_percent": mem_percent,
        "cpu_percent": cpu_percent,
        "active_connections": 0
    }


class MonitoringApp:
    """简单的监控 WSGI 应用"""

    def __init__(self, static_dir: Path):
        self.static_dir = static_dir
        self.routes = {
            "/": self.handle_dashboard,
            "/dashboard": self.handle_dashboard,
            "/api/dashboard/stats": self.handle_api_stats,
            "/api/downloads": self.handle_api_downloads,
            "/api/uploads": self.handle_api_uploads,
            "/api/system": self.handle_api_system,
        }

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "/")
        
        # 检查是否是静态文件
        if path.startswith("/static/"):
            return self.handle_static(environ, start_response)
        
        # 检查是否是 API 路由
        handler = self.routes.get(path)
        if handler:
            return handler(environ, start_response)
        
        # 检查是否是看板相关路径
        if path == "/dashboard" or path == "/dashboard/":
            return self.handle_dashboard(environ, start_response)
        
        # 默认返回 404
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"404 Not Found"]

    def handle_dashboard(self, environ, start_response):
        """返回看板主页"""
        index_path = self.static_dir / "dashboard" / "index.html"
        if not index_path.exists():
            start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"404 Not Found"]
        
        with open(index_path, "rb") as f:
            content = f.read()
        
        start_response("200 OK", [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(content)))
        ])
        return [content]

    def handle_static(self, environ, start_response):
        """处理静态文件"""
        path = environ.get("PATH_INFO", "/")
        # 去除 /static 前缀
        file_path = self.static_dir / path.lstrip("/")
        
        if not file_path.exists() or file_path.is_dir():
            start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"404 Not Found"]
        
        # 猜测 MIME 类型
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if not mime_type:
            mime_type = "application/octet-stream"
        
        with open(file_path, "rb") as f:
            content = f.read()
        
        start_response("200 OK", [
            ("Content-Type", mime_type),
            ("Content-Length", str(len(content)))
        ])
        return [content]

    def handle_api_stats(self, environ, start_response):
        """返回看板统计数据"""
        stats = {}
        if _monitoring_db:
            stats = _monitoring_db.get_dashboard_stats()
        
        # 添加最新系统指标
        sys_metrics = get_system_metrics()
        stats["system"] = sys_metrics
        
        response = json.dumps(stats, ensure_ascii=False).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(response)))
        ])
        return [response]

    def handle_api_downloads(self, environ, start_response):
        """返回下载历史"""
        data = []
        if _monitoring_db:
            data = _monitoring_db.get_download_metrics(hours=24, limit=50)
        
        response = json.dumps(data, ensure_ascii=False).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(response)))
        ])
        return [response]

    def handle_api_uploads(self, environ, start_response):
        """返回上传历史"""
        data = []
        if _monitoring_db:
            data = _monitoring_db.get_upload_metrics(hours=24, limit=50)
        
        response = json.dumps(data, ensure_ascii=False).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(response)))
        ])
        return [response]

    def handle_api_system(self, environ, start_response):
        """返回系统指标历史"""
        data = []
        if _monitoring_db:
            data = _monitoring_db.get_system_metrics(hours=1, limit=100)
        
        response = json.dumps(data, ensure_ascii=False).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(response)))
        ])
        return [response]


class CombinedApp:
    """组合 WSGI 应用（支持 WebDAV 和监控）"""

    def __init__(self, webdav_app: Optional[Callable], monitoring_app: MonitoringApp, webdav_prefix: str = "/"):
        self.webdav_app = webdav_app
        self.monitoring_app = monitoring_app
        self.webdav_prefix = webdav_prefix.rstrip("/")

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "/")
        
        # 监控路由
        if path == "/" or path.startswith("/dashboard") or path.startswith("/api/") or path.startswith("/static/"):
            return self.monitoring_app(environ, start_response)
        
        # WebDAV 路由
        if self.webdav_app:
            return self.webdav_app(environ, start_response)
        
        # 默认返回 404
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"404 Not Found"]


class WebDAVServer:
    def __init__(self, config: WebDAVServerConfig, download_dir: str):
        self.config = config
        self.download_dir = download_dir
        self._server_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._httpd: Optional[WSGIServer] = None
        self._static_dir = Path(__file__).parent.parent / "static"

    def _get_mount_dir(self) -> Path:
        """获取实际挂载的目录"""
        if self.config.directory:
            return Path(self.config.directory)
        return Path(self.download_dir)

    def _build_webdav_config(self) -> dict:
        """构建 WsgiDAV 配置"""
        if not WEBDAV_AVAILABLE:
            raise RuntimeError("WebDAV 依赖未安装，请运行: pip install tg-download[nas]")

        mount_dir = self._get_mount_dir()
        mount_dir.mkdir(parents=True, exist_ok=True)

        config = wsgidav_app.DEFAULT_CONFIG.copy()
        config.update({
            "host": "127.0.0.1",
            "port": 0,
            "provider_mapping": {self.config.mount_path: FilesystemProvider(str(mount_dir))},
            "verbose": 0,
        })

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
        try:
            webdav_app_obj = None
            if self.config.enable and WEBDAV_AVAILABLE:
                wd_config = self._build_webdav_config()
                webdav_app_obj = WsgiDAVApp(wd_config)
            
            monitoring_app = MonitoringApp(self._static_dir)
            combined_app = CombinedApp(
                webdav_app_obj,
                monitoring_app,
                self.config.mount_path
            )

            # 启动系统指标收集
            def collect_system_metrics():
                while not self._stop_event.is_set():
                    if _monitoring_db:
                        metrics = get_system_metrics()
                        _monitoring_db.record_system_metrics(**metrics)
                    time.sleep(30)
            
            metrics_thread = threading.Thread(target=collect_system_metrics, daemon=True)
            metrics_thread.start()

            self._httpd = make_server(
                self.config.host,
                self.config.port,
                combined_app,
                server_class=WSGIServer
            )

            logger.info(f"服务器启动在 http://{self.config.host}:{self.config.port}")
            logger.info(f"监控看板: http://{self.config.host}:{self.config.port}/dashboard")
            if self.config.enable:
                logger.info(f"WebDAV: http://{self.config.host}:{self.config.port}{self.config.mount_path}")

            try:
                self._httpd.serve_forever()
            except Exception as e:
                if not self._stop_event.is_set():
                    logger.error(f"服务器错误: {e}")
            finally:
                logger.info("服务器已停止")
        except Exception as e:
            logger.exception(f"服务器启动失败: {e}")

    def start(self):
        """启动服务器"""
        if self._server_thread and self._server_thread.is_alive():
            logger.warning("服务器已在运行")
            return

        self._stop_event.clear()
        self._server_thread = threading.Thread(target=self._run_server, daemon=True)
        self._server_thread.start()

    def stop(self):
        """停止服务器"""
        if not self._server_thread or not self._server_thread.is_alive():
            return

        logger.info("正在停止服务器...")
        self._stop_event.set()
        
        if self._httpd:
            self._httpd.shutdown()
        
        self._server_thread.join(timeout=5)
        if self._server_thread.is_alive():
            logger.warning("服务器未能在 5 秒内停止")
