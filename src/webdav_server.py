from __future__ import annotations

import json
import logging
import mimetypes
import os
import threading
import time
from pathlib import Path
from typing import Optional, Callable
from socketserver import ThreadingMixIn
from wsgiref.simple_server import make_server, WSGIServer


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    """处理每个请求在独立线程中的 WSGI 服务器"""
    daemon_threads = True

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
    """简单的监控 WSGI 应用，支持 HTTP Basic 认证"""

    def __init__(self, static_dir: Path, monitoring_username: str, monitoring_password: str):
        self.static_dir = static_dir
        self.monitoring_username = monitoring_username
        self.monitoring_password = monitoring_password
        self.routes = {
            "/dashboard": self.handle_dashboard,
            "/api/dashboard/stats": self.handle_api_stats,
            "/api/downloads": self.handle_api_downloads,
            "/api/uploads": self.handle_api_uploads,
            "/api/system": self.handle_api_system,
            "/api/health/checks": self.handle_api_health_checks,
            "/api/health/recoveries": self.handle_api_recoveries,
            "/health": self.handle_health_endpoint,
        }
    
    def handle_health_endpoint(self, environ, start_response):
        """简单的健康检查端点，返回 200 OK"""
        start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"OK"]
    
    def handle_api_health_checks(self, environ, start_response):
        """获取健康检查历史"""
        data = []
        if _monitoring_db:
            data = _monitoring_db.get_health_checks(hours=24, limit=100)
        response = json.dumps(data, ensure_ascii=False).encode("utf-8")
        start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
        return [response]
    
    def handle_api_recoveries(self, environ, start_response):
        """获取恢复历史"""
        data = []
        if _monitoring_db:
            data = _monitoring_db.get_recovery_history(hours=24, limit=20)
        response = json.dumps(data, ensure_ascii=False).encode("utf-8")
        start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
        return [response]

    def check_auth(self, environ):
        """检查 HTTP Basic 认证"""
        if not self.monitoring_username or not self.monitoring_password:
            # 没有配置监控用户名密码，跳过认证，但记录警告
            logger.warning("监控看板未配置认证，任何人都可以访问！")
            return True
        
        auth = environ.get("HTTP_AUTHORIZATION")
        if auth is None:
            return False
        
        if not auth.startswith("Basic "):
            return False
        
        import base64
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            user, passwd = decoded.split(":", 1)
            return user == self.monitoring_username and passwd == self.monitoring_password
        except Exception:
            return False

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "/")
        
        # 健康检查端点跳过认证
        if path == "/health":
            return self.handle_health_endpoint(environ, start_response)
        
        # 其他路由检查认证
        if not self.check_auth(environ):
            start_response("401 Unauthorized", [
                ("WWW-Authenticate", 'Basic realm="tg-download monitoring"'),
                ("Content-Type", "text/plain; charset=utf-8")
            ])
            return [b"401 Unauthorized"]
        
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
        if path.startswith("/static/"):
            relative_path = path[len("/static/"):]
        else:
            relative_path = path.lstrip("/")
        file_path = self.static_dir / relative_path
        
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
    """组合 WSGI 应用（支持 WebDAV 和监控），监控需要认证，WebDAV 使用自己的认证"""

    def __init__(self, webdav_app: Optional[Callable], monitoring_app: MonitoringApp, webdav_prefix: str = "/"):
        self.webdav_app = webdav_app
        self.monitoring_app = monitoring_app
        self.webdav_prefix = webdav_prefix.rstrip("/")

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "/")
        
        # 健康检查端点 - 直接处理返回
        if path == "/health":
            start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"OK"]
        
        # 监控路由 - 使用监控应用（带认证）
        if path.startswith("/dashboard") or path.startswith("/api/") or path.startswith("/static/"):
            return self.monitoring_app(environ, start_response)
        
        # WebDAV 路由 - 使用 WebDAV 应用（带自己的认证）
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
        self._health_check_thread: Optional[threading.Thread] = None
        self._failure_count = 0
        self._restart_timestamps: list[float] = []

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

    def _run_health_check(self):
        """运行健康检查 - 通过 socket 直接检查端口"""
        import socket
        logger.info(f"健康检查线程启动，_monitoring_db={_monitoring_db}")
        
        # 先等 10 秒，让服务器完全启动
        logger.info(f"等待 10 秒让服务器启动完成")
        if self._stop_event.wait(10):
            return
        
        while not self._stop_event.is_set():
            try:
                start_time = time.time()
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.config.health_check_timeout)
                result = sock.connect_ex(('127.0.0.1', self.config.port))
                sock.close()
                
                if result == 0:
                    response_time = (time.time() - start_time) * 1000
                    self._failure_count = 0
                    if _monitoring_db:
                        try:
                            _monitoring_db.record_health_check("success", response_time)
                            logger.info(f"健康检查成功，已记录")
                        except Exception as record_err:
                            logger.error(f"记录健康检查失败: {record_err}")
                    else:
                        logger.info(f"健康检查成功，_monitoring_db 未设置，不记录")
                    logger.debug(f"健康检查成功，响应时间: {response_time:.2f}ms")
                else:
                    raise Exception(f"Socket connection failed, result={result}")
            except Exception as e:
                response_time = (time.time() - start_time) * 1000
                self._failure_count += 1
                error_msg = str(e)
                if _monitoring_db:
                    try:
                        _monitoring_db.record_health_check("failed", response_time, error_msg)
                    except Exception as record_err:
                        logger.error(f"记录健康检查失败: {record_err}")
                logger.warning(f"健康检查失败 ({self._failure_count}/{self.config.health_check_failure_threshold}): {error_msg}")
                
                # 检查是否需要触发恢复
                if self._failure_count >= self.config.health_check_failure_threshold:
                    self._attempt_recovery()
            
            # 等待下一次检查
            self._stop_event.wait(self.config.health_check_interval)
    
    def _attempt_recovery(self):
        """尝试恢复服务 - 通过退出让 systemd 重启"""
        # 检查重启频率限制
        now = time.time()
        hour_ago = now - 3600
        self._restart_timestamps = [t for t in self._restart_timestamps if t > hour_ago]
        
        if len(self._restart_timestamps) >= self.config.health_check_max_restarts_per_hour:
            logger.error(f"重启频率超过限制（{len(self._restart_timestamps)}次/小时），跳过恢复")
            return
        
        # 执行重启
        logger.warning("触发服务恢复机制 - 退出进程让 systemd 重启")
        if _monitoring_db:
            _monitoring_db.record_recovery(
                reason=f"健康检查连续失败{self._failure_count}次",
                action_taken="restart"
            )
        
        # 记录重启时间
        self._restart_timestamps.append(time.time())
        self._failure_count = 0
        
        # 停止服务器和主线程
        self.stop()
        
        # 退出进程让 systemd 重启
        import sys
        sys.exit(1)

    def _run_server(self):
        """在独立线程中运行服务器"""
        try:
            webdav_app_obj = None
            if self.config.enable and WEBDAV_AVAILABLE:
                wd_config = self._build_webdav_config()
                webdav_app_obj = WsgiDAVApp(wd_config)
            
            monitoring_app = MonitoringApp(self._static_dir, self.config.monitoring_username, self.config.monitoring_password)
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
            
            # 启动健康检查线程
            if self.config.health_check_enabled:
                self._health_check_thread = threading.Thread(target=self._run_health_check, daemon=True)
                self._health_check_thread.start()
                logger.info(f"健康检查已启用，间隔: {self.config.health_check_interval}秒")

            # 创建服务器（使用多线程）
            self._httpd = make_server(
                self.config.host,
                self.config.port,
                combined_app,
                server_class=ThreadingWSGIServer
            )
            # 设置 backlog
            if hasattr(self._httpd, 'request_queue_size'):
                self._httpd.request_queue_size = self.config.server_backlog

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
