from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import http.client
import socketserver
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Optional, Callable, Dict, Any
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

from .config import WebDAVServerConfig

logger = logging.getLogger(__name__)


class ThreadingWSGIServer(socketserver.ThreadingMixIn, WSGIServer):
    """WSGI server that isolates slow clients in separate worker threads."""

    daemon_threads = True
    block_on_close = False
    request_queue_size = 128

# 全局监控实例
_monitoring_db = None
# 全局去重相关实例
_deduplicator = None
_download_db = None
# 缓存聊天列表
_cached_chats: list[dict] = []
# 主事件循环（来自 CLI）
_main_event_loop = None


def set_monitoring_db(db):
    """设置监控数据库实例"""
    global _monitoring_db
    _monitoring_db = db


def set_deduplication_resources(deduplicator, download_db, chats=None, event_loop=None):
    """设置去重相关资源（现在只用于提供数据库和聊天列表）"""
    global _deduplicator
    global _download_db
    global _cached_chats
    global _main_event_loop
    _deduplicator = deduplicator
    _download_db = download_db
    
    # 保存主事件循环（不过现在已经不需要用它来启动任务了）
    if event_loop is not None:
        _main_event_loop = event_loop
    
    # 使用传入的聊天列表缓存
    if chats is not None:
        _cached_chats = chats
        logger.info(f"已缓存 {len(chats)} 个聊天/频道")


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
    """简单的监控 WSGI 应用，支持基于 Cookie 的会话认证"""

    def __init__(self, static_dir: Path, web_dist_dir: Path, username: str, password: str):
        self.static_dir = static_dir
        self.web_dist_dir = web_dist_dir
        self.username = username
        self.password = password
        self.sessions = {}  # 存储会话
        self.session_expiry = 7 * 24 * 60 * 60  # 会话有效期：7天
        self.routes = {
            "/dashboard": self.handle_dashboard,
            "/dashboard-legacy": self.handle_dashboard_legacy,
            "/api/dashboard/stats": self.handle_api_stats,
            "/api/downloads": self.handle_api_downloads,
            "/api/uploads": self.handle_api_uploads,
            "/api/system": self.handle_api_system,
            "/api/health/checks": self.handle_api_health_checks,
            "/api/health/recoveries": self.handle_api_recoveries,
            "/health": self.handle_health_endpoint,
            "/api/login": self.handle_api_login,
            "/api/logout": self.handle_api_logout,
        }
    
    def _parse_query_params(self, environ: dict) -> dict:
        """解析查询参数"""
        query_string = environ.get("QUERY_STRING", "")
        return urllib.parse.parse_qs(query_string)
    
    def _read_request_body(self, environ: dict) -> dict:
        """读取请求体并解析为 JSON"""
        try:
            content_length = int(environ.get("CONTENT_LENGTH", 0))
            if content_length > 0:
                body = environ["wsgi.input"].read(content_length)
                return json.loads(body)
        except Exception:
            pass
        return {}
    
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

    def _generate_session_id(self):
        """生成随机会话 ID"""
        import uuid
        import time
        return f"{uuid.uuid4().hex}_{int(time.time())}"
    
    def _get_session(self, environ):
        """从 Cookie 中获取会话"""
        if not self.username or not self.password:
            return True  # 没有配置用户名密码，跳过认证
        
        cookies = environ.get("HTTP_COOKIE", "")
        for cookie in cookies.split(";"):
            cookie = cookie.strip()
            if cookie.startswith("tg_session="):
                session_id = cookie.split("=", 1)[1]
                # 检查会话是否有效
                session = self.sessions.get(session_id)
                if session:
                    import time
                    if time.time() - session["created_at"] < self.session_expiry:
                        return True
                    # 会话过期，删除
                    del self.sessions[session_id]
        return False
    
    def check_auth(self, environ):
        """检查认证（保持向后兼容 Basic Auth）"""
        # 首先尝试会话认证
        if self._get_session(environ):
            return True
        
        # 如果没有用户名密码配置，直接通过
        if not self.username or not self.password:
            return True
        
        # 回退到 Basic Auth 保持向后兼容
        auth = environ.get("HTTP_AUTHORIZATION")
        if auth is None:
            return False
        
        if not auth.startswith("Basic "):
            return False
        
        import base64
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            user, passwd = decoded.split(":", 1)
            return user == self.username and passwd == self.password
        except Exception:
            return False
    
    def handle_api_login(self, environ, start_response):
        """登录接口"""
        if environ.get("REQUEST_METHOD") != "POST":
            start_response("405 Method Not Allowed", [("Content-Type", "text/plain")])
            return [b"Method Not Allowed"]
        
        body = self._read_request_body(environ)
        username = body.get("username", "")
        password = body.get("password", "")
        
        if username == self.username and password == self.password:
            # 生成会话
            session_id = self._generate_session_id()
            import time
            self.sessions[session_id] = {
                "created_at": time.time(),
                "username": username
            }
            
            # 设置 Cookie
            cookie = f"tg_session={session_id}; Path=/; Max-Age={self.session_expiry}; SameSite=Lax"
            response = json.dumps({"success": True, "message": "登录成功"}, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Set-Cookie", cookie)
            ])
            return [response]
        else:
            response = json.dumps({"success": False, "message": "用户名或密码错误"}, ensure_ascii=False).encode("utf-8")
            start_response("401 Unauthorized", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
    
    def handle_api_logout(self, environ, start_response):
        """登出接口"""
        # 清除会话
        cookies = environ.get("HTTP_COOKIE", "")
        for cookie in cookies.split(";"):
            cookie = cookie.strip()
            if cookie.startswith("tg_session="):
                session_id = cookie.split("=", 1)[1]
                if session_id in self.sessions:
                    del self.sessions[session_id]
        
        # 清除 Cookie
        cookie = "tg_session=; Path=/; Max-Age=0"
        response = json.dumps({"success": True, "message": "已登出"}, ensure_ascii=False).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Set-Cookie", cookie)
        ])
        return [response]

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "/")

        # 健康检查端点跳过认证
        if path == "/health":
            return self.handle_health_endpoint(environ, start_response)

        # 登录和登出接口跳过认证
        if path == "/api/login" or path == "/api/logout":
            handler = self.routes.get(path)
            if handler:
                return handler(environ, start_response)

        # 静态资源跳过认证（/assets/、/favicon.svg、/icons.svg）
        is_static_resource = path.startswith("/assets/") or path == "/favicon.svg" or path == "/icons.svg"
        
        # 其他路由检查认证
        if not is_static_resource and not self.check_auth(environ):
            # 如果是 API 路由，返回 401
            if path.startswith("/api/"):
                start_response("401 Unauthorized", [
                    ("Content-Type", "application/json; charset=utf-8")
                ])
                return [json.dumps({"error": "未登录"}, ensure_ascii=False).encode("utf-8")]
            # 其他情况返回 index.html，让前端处理登录
            return self.handle_dashboard(environ, start_response)

        # 检查是否是旧版静态文件（保留旧版 /static/ 路由用于旧版页面）
        if path.startswith("/static/dashboard/"):
            return self.handle_static(environ, start_response)

        # 检查是否是新版静态文件（/static/、/assets/、/favicon.svg 等都指向新版）
        if path.startswith("/static/") or path.startswith("/assets/") or path == "/favicon.svg" or path == "/icons.svg":
            return self.handle_web_static(environ, start_response)

        # 检查去重相关的动态路由
        handler = self._match_dedupe_route(path, environ.get("REQUEST_METHOD", "GET"))
        if handler:
            return handler(environ, start_response)

        # 检查是否是 API 路由或其他路由
        handler = self.routes.get(path)
        if handler:
            return handler(environ, start_response)

        # 默认：如果是 /dashboard 下的路由，返回 React 应用，否则返回 404
        if path.startswith("/dashboard") and self.web_dist_dir.exists():
            return self.handle_dashboard(environ, start_response)
        
        # 默认返回 404
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"404 Not Found"]
    
    def _match_dedupe_route(self, path: str, method: str):
        """匹配去重相关的动态路由"""
        # GET /api/dedupe/chats
        if path == "/api/dedupe/chats" and method == "GET":
            return self.handle_api_dedupe_chats
        # GET /api/dedupe/tasks
        if path == "/api/dedupe/tasks" and method == "GET":
            return self.handle_api_dedupe_tasks_list
        # POST /api/dedupe/tasks
        if path == "/api/dedupe/tasks" and method == "POST":
            return self.handle_api_dedupe_tasks_create
        # 匹配 /api/dedupe/tasks/{task_id} 相关的路由
        if path.startswith("/api/dedupe/tasks/"):
            parts = path.split("/")
            if len(parts) >= 5:
                task_id_str = parts[4]
                try:
                    task_id = int(task_id_str)
                except ValueError:
                    return None
                
                # GET /api/dedupe/tasks/{task_id}
                if len(parts) == 5 and method == "GET":
                    return lambda e, s: self.handle_api_dedupe_task_detail(e, s, task_id)
                # DELETE /api/dedupe/tasks/{task_id}
                if len(parts) == 5 and method == "DELETE":
                    return lambda e, s: self.handle_api_dedupe_task_delete(e, s, task_id)
                # POST /api/dedupe/tasks/{task_id}/start
                if len(parts) == 6 and parts[5] == "start" and method == "POST":
                    return lambda e, s: self.handle_api_dedupe_task_start(e, s, task_id)
                # POST /api/dedupe/tasks/{task_id}/pause
                if len(parts) == 6 and parts[5] == "pause" and method == "POST":
                    return lambda e, s: self.handle_api_dedupe_task_pause(e, s, task_id)
                # POST /api/dedupe/tasks/{task_id}/resume
                if len(parts) == 6 and parts[5] == "resume" and method == "POST":
                    return lambda e, s: self.handle_api_dedupe_task_resume(e, s, task_id)
                # POST /api/dedupe/tasks/{task_id}/restart
                if len(parts) == 6 and parts[5] == "restart" and method == "POST":
                    return lambda e, s: self.handle_api_dedupe_task_restart(e, s, task_id)
                # GET /api/dedupe/tasks/{task_id}/media
                if len(parts) == 6 and parts[5] == "media" and method == "GET":
                    return lambda e, s: self.handle_api_dedupe_task_media(e, s, task_id)
                # POST /api/dedupe/tasks/{task_id}/download
                if len(parts) == 6 and parts[5] == "download" and method == "POST":
                    return lambda e, s: self.handle_api_dedupe_task_download(e, s, task_id)
                # 两层去重相关端点
                # POST /api/dedupe/tasks/{task_id}/dedupe/level2
                if len(parts) == 7 and parts[5] == "dedupe" and parts[6] == "level2" and method == "POST":
                    return lambda e, s: self.handle_api_dedupe_task_level2(e, s, task_id)
                # POST /api/dedupe/tasks/{task_id}/dedupe/two-level
                if len(parts) == 7 and parts[5] == "dedupe" and parts[6] == "two-level" and method == "POST":
                    return lambda e, s: self.handle_api_dedupe_task_two_level(e, s, task_id)
                # GET /api/dedupe/tasks/{task_id}/dedupe/summary
                if len(parts) == 7 and parts[5] == "dedupe" and parts[6] == "summary" and method == "GET":
                    return lambda e, s: self.handle_api_dedupe_task_summary(e, s, task_id)
                # POST /api/dedupe/tasks/{task_id}/dedupe/level2/{group_id}/interest
                if len(parts) == 9 and parts[5] == "dedupe" and parts[6] == "level2" and parts[8] == "interest" and method == "POST":
                    group_id = parts[7]
                    return lambda e, s: self.handle_api_dedupe_task_level2_interest(e, s, task_id, group_id)
                # GET /api/dedupe/tasks/{task_id}/dedupe/level2/{group_id}
                if len(parts) == 8 and parts[5] == "dedupe" and parts[6] == "level2" and method == "GET":
                    group_id = parts[7]
                    return lambda e, s: self.handle_api_dedupe_task_level2_detail(e, s, task_id, group_id)
                # GET /api/dedupe/tasks/{task_id}/media/{id_or_file_id}/thumbnail
                if len(parts) == 7 and parts[5] == "media" and parts[6] == "thumbnail":
                    # 这种情况没有提供 media_id 或 file_id，不处理
                    return None
                if len(parts) == 8 and parts[5] == "media" and parts[7] == "thumbnail" and method == "GET":
                    media_identifier = parts[6]
                    # 尝试作为数字处理
                    try:
                        media_id = int(media_identifier)
                        return lambda e, s: self.handle_api_dedupe_media_thumbnail(e, s, task_id, media_id=media_id, file_id=None)
                    except ValueError:
                        # 作为 file_id 处理
                        return lambda e, s: self.handle_api_dedupe_media_thumbnail(e, s, task_id, media_id=None, file_id=media_identifier)
        return None

    def handle_dashboard(self, environ, start_response):
        """返回新版 React 看板主页"""
        index_path = self.web_dist_dir / "index.html"
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

    def handle_dashboard_legacy(self, environ, start_response):
        """返回旧版看板主页"""
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

    def handle_web_static(self, environ, start_response):
        """处理新版 React 静态资源"""
        path = environ.get("PATH_INFO", "/")
        if path.startswith("/static/"):
            relative_path = path[len("/static/"):]
        else:
            relative_path = path.lstrip("/")
        file_path = self.web_dist_dir / relative_path
        
        if not file_path.exists() or file_path.is_dir():
            start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"404 Not Found"]
        
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

    def handle_api_dedupe_chats(self, environ, start_response):
        """GET /api/dedupe/chats - 获取可扫描的群组/频道列表"""
        try:
            global _cached_chats
            response = json.dumps(_cached_chats, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"获取聊天列表失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]

    def handle_api_dedupe_tasks_list(self, environ, start_response):
        """GET /api/dedupe/tasks - 获取去重任务列表"""
        try:
            tasks = []
            if _download_db:
                tasks = _download_db.list_dedupe_tasks()
            response = json.dumps(tasks, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"获取去重任务列表失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]

    def handle_api_dedupe_tasks_create(self, environ, start_response):
        """POST /api/dedupe/tasks - 创建新的去重任务"""
        try:
            body = self._read_request_body(environ)
            chat_id = body.get("chat_id")
            chat_title = body.get("chat_title")
            start_message_id = body.get("start_message_id")
            total_messages = body.get("total_messages")
            
            if not chat_id:
                error = json.dumps({"error": "chat_id 是必需的"}, ensure_ascii=False).encode("utf-8")
                start_response("400 Bad Request", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            # 转换为正确的类型
            if isinstance(chat_id, str) and chat_id.lstrip('-').isdigit():
                chat_id = int(chat_id)
            
            if start_message_id is not None and start_message_id != "":
                if isinstance(start_message_id, str) and start_message_id.lstrip('-').isdigit():
                    start_message_id = int(start_message_id)
            else:
                start_message_id = None
                
            if total_messages is not None and total_messages != "":
                if isinstance(total_messages, str) and total_messages.isdigit():
                    total_messages = int(total_messages)
            else:
                total_messages = None
            
            task_id = None
            if _deduplicator:
                task_id = _deduplicator.create_task(chat_id, chat_title, start_message_id, total_messages)
            
            response = json.dumps({"task_id": task_id, "success": True}, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"创建去重任务失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]

    def handle_api_dedupe_task_detail(self, environ, start_response, task_id: int):
        """GET /api/dedupe/tasks/{task_id} - 获取单个任务详情"""
        try:
            task = None
            if _download_db:
                task = _download_db.get_dedupe_task(task_id)
            
            if not task:
                error = json.dumps({"error": "任务不存在"}, ensure_ascii=False).encode("utf-8")
                start_response("404 Not Found", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            response = json.dumps(task, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"获取任务详情失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]

    def handle_api_dedupe_task_start(self, environ, start_response, task_id: int):
        """POST /api/dedupe/tasks/{task_id}/start - 将任务标记为待执行"""
        try:
            if not _download_db:
                error = json.dumps({"error": "数据库未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            task = _download_db.get_dedupe_task(task_id)
            if not task:
                error = json.dumps({"error": "任务不存在"}, ensure_ascii=False).encode("utf-8")
                start_response("404 Not Found", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            if task["status"] == "scanning":
                error = json.dumps({"error": "任务已经在运行中"}, ensure_ascii=False).encode("utf-8")
                start_response("400 Bad Request", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            # 更新任务状态为待执行，调度器会自动启动任务
            _download_db.update_dedupe_task(task_id, status="pending")
            
            logger.info(f"任务 {task_id} 已标记为待执行，调度器将在下次检查时启动")
            
            response = json.dumps({"success": True, "message": "任务已加入执行队列"}, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"启动任务失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]

    def handle_api_dedupe_task_pause(self, environ, start_response, task_id: int):
        """POST /api/dedupe/tasks/{task_id}/pause - 暂停扫描"""
        try:
            if not _deduplicator:
                error = json.dumps({"error": "去重器未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            _deduplicator.pause_scan()
            response = json.dumps({"success": True, "message": "扫描已暂停"}, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"暂停扫描失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]

    def handle_api_dedupe_task_resume(self, environ, start_response, task_id: int):
        """POST /api/dedupe/tasks/{task_id}/resume - 恢复扫描"""
        try:
            if not _deduplicator:
                error = json.dumps({"error": "去重器未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            _deduplicator.resume_scan()
            response = json.dumps({"success": True, "message": "扫描已恢复"}, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"恢复扫描失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]

    def handle_api_dedupe_task_media(self, environ, start_response, task_id: int):
        """GET /api/dedupe/tasks/{task_id}/media - 获取媒体列表"""
        try:
            query_params = self._parse_query_params(environ)
            page = int(query_params.get("page", [1])[0])
            limit = int(query_params.get("limit", [20])[0])
            search = query_params.get("search", [None])[0]
            filter_type = query_params.get("filter_type", ["all"])[0]
            
            # 获取视频时长范围参数
            min_duration_str = query_params.get("min_duration", [None])[0]
            max_duration_str = query_params.get("max_duration", [None])[0]
            min_duration = int(min_duration_str) if min_duration_str and min_duration_str.isdigit() else None
            max_duration = int(max_duration_str) if max_duration_str and max_duration_str.isdigit() else None
            
            media_list = []
            total = 0
            if _download_db:
                media_list, total = _download_db.get_dedupe_media_list(
                    task_id, 
                    page, 
                    limit, 
                    search, 
                    filter_type,
                    min_duration,
                    max_duration
                )
            
            total_pages = (total + limit - 1) // limit if limit > 0 else 0
            
            response = json.dumps({
                "items": media_list,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": total,
                    "total_pages": total_pages
                }
            }, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"获取媒体列表失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]

    def handle_api_dedupe_task_download(self, environ, start_response, task_id: int):
        """POST /api/dedupe/tasks/{task_id}/download - 下载独特媒体"""
        try:
            body = self._read_request_body(environ)
            output_dir = body.get("output_dir", "downloads")
            file_id = body.get("file_id")
            download_all = body.get("download_all", True)
            
            if not _deduplicator:
                error = json.dumps({"error": "去重器未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]

            queued_file_ids: list[str] = []
            file_ids: list[str] = []
            if _download_db:
                if download_all:
                    media_list, _ = _download_db.get_dedupe_media_list(task_id, filter_type="singles", limit=10000)
                    duplicates, _ = _download_db.get_dedupe_media_list(task_id, filter_type="duplicates", limit=10000)
                    file_ids = [item["file_id"] for item in media_list + duplicates if item.get("file_id")]
                elif file_id:
                    media = _download_db.get_dedupe_media(task_id, file_id)
                    if media:
                        file_ids = [file_id]

                queued_file_ids = _download_db.enqueue_dedupe_download_jobs(task_id, file_ids, output_dir)

            for current_file_id in queued_file_ids:
                if hasattr(_deduplicator, "set_download_status"):
                    _deduplicator.set_download_status(task_id, current_file_id, "queued")

            response = json.dumps(
                {
                    "success": True,
                    "message": "下载任务已加入队列",
                    "downloaded_count": len(queued_file_ids),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"启动下载失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]
    
    def handle_api_dedupe_media_thumbnail(self, environ, start_response, task_id: int, media_id: int = None, file_id: str = None):
        """GET /api/dedupe/tasks/{task_id}/media/{media_id}/thumbnail 或 /api/dedupe/tasks/{task_id}/media/{file_id}/thumbnail - 获取媒体缩略图"""
        try:
            if not _download_db:
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [json.dumps({"error": "数据库未初始化"}, ensure_ascii=False).encode("utf-8")]
            
            # 获取缩略图
            thumb_info = _download_db.get_dedupe_media_thumbnail(task_id, media_id=media_id, file_id=file_id)
            
            if not thumb_info or not thumb_info.get('thumbnail_data'):
                start_response("404 Not Found", [("Content-Type", "application/json; charset=utf-8")])
                return [json.dumps({"error": "缩略图不存在"}, ensure_ascii=False).encode("utf-8")]
            
            # 返回缩略图
            start_response("200 OK", [
                ("Content-Type", "image/jpeg"),
                ("Content-Length", str(len(thumb_info['thumbnail_data'])))
            ])
            return [thumb_info['thumbnail_data']]
        except Exception as e:
            logger.error(f"获取缩略图失败: {e}")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")]

    def handle_api_dedupe_task_delete(self, environ, start_response, task_id: int):
        """DELETE /api/dedupe/tasks/{task_id} - 删除去重任务"""
        try:
            if not _download_db:
                error = json.dumps({"error": "数据库未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            # 删除任务
            _download_db.delete_dedupe_task(task_id)
            
            response = json.dumps({"success": True, "message": "任务已删除"}, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"删除任务失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]

    def handle_api_dedupe_task_restart(self, environ, start_response, task_id: int):
        """POST /api/dedupe/tasks/{task_id}/restart - 重置任务为待执行状态"""
        try:
            if not _download_db:
                error = json.dumps({"error": "数据库未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            # 重置任务
            _download_db.reset_dedupe_task(task_id)
            
            # 将任务状态设为待执行
            _download_db.update_dedupe_task(task_id, status="pending")
            
            logger.info(f"任务 {task_id} 已重置并标记为待执行，调度器将在下次检查时启动")
            
            response = json.dumps({"success": True, "message": "任务已重置并加入执行队列"}, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"重置任务失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]

    def handle_api_dedupe_task_level2(self, environ, start_response, task_id: int):
        """POST /api/dedupe/tasks/{task_id}/dedupe/level2 - 运行第二层去重"""
        try:
            if not _deduplicator:
                error = json.dumps({"error": "去重器未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            body = self._read_request_body(environ)
            similarity_threshold = body.get("similarity_threshold")
            
            level2_count = _deduplicator.run_level2_dedupe(task_id, similarity_threshold)
            
            response = json.dumps({"success": True, "message": f"第二层去重完成，共 {level2_count} 个分组", "level2_count": level2_count}, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"第二层去重失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]

    def handle_api_dedupe_task_two_level(self, environ, start_response, task_id: int):
        """POST /api/dedupe/tasks/{task_id}/dedupe/two-level - 运行完整两层去重"""
        try:
            if not _deduplicator:
                error = json.dumps({"error": "去重器未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            body = self._read_request_body(environ)
            similarity_threshold = body.get("similarity_threshold")
            
            _deduplicator.run_two_level_dedupe(task_id, similarity_threshold)
            summary = _download_db.get_two_level_dedupe_summary_page(
                task_id,
                include_level1_groups=True,
            )
            
            response = json.dumps({"success": True, "message": "完整两层去重完成", "summary": summary}, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"完整两层去重失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]

    def handle_api_dedupe_task_summary(self, environ, start_response, task_id: int):
        """GET /api/dedupe/tasks/{task_id}/dedupe/summary - 获取两层去重汇总"""
        try:
            if not _download_db:
                error = json.dumps({"error": "数据库未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            params = self._parse_query_params(environ)
            level2_page = int(params.get("level2_page", ["1"])[0] or 1)
            level2_limit = int(params.get("level2_limit", ["50"])[0] or 50)
            download_status = params.get("download_status", ["all"])[0]
            show_uninterested = params.get("show_uninterested", ["0"])[0] in {"1", "true", "True"}
            min_download_size_mb = params.get("min_download_size_mb", [None])[0]
            max_download_size_mb = params.get("max_download_size_mb", [None])[0]
            min_download_size_bytes = None
            max_download_size_bytes = None
            if min_download_size_mb in (None, ""):
                min_download_size_bytes = 50 * 1024 * 1024
            else:
                min_download_size_bytes = int(float(min_download_size_mb) * 1024 * 1024)
            if max_download_size_mb not in (None, ""):
                max_download_size_bytes = int(float(max_download_size_mb) * 1024 * 1024)
            runtime_status_map = {}
            if _deduplicator and hasattr(_deduplicator, "get_download_status_map"):
                runtime_status_map = _deduplicator.get_download_status_map(task_id)
            summary = _download_db.get_two_level_dedupe_summary_page(
                task_id,
                level2_page=level2_page,
                level2_limit=level2_limit,
                download_status_filter=download_status,
                runtime_status_map=runtime_status_map,
                show_uninterested=show_uninterested,
                include_level1_groups=True,
                min_download_size_bytes=min_download_size_bytes,
                max_download_size_bytes=max_download_size_bytes,
            )
            
            response = json.dumps(summary, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"获取去重汇总失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]

    def handle_api_dedupe_task_level2_detail(self, environ, start_response, task_id: int, group_id: str):
        """GET /api/dedupe/tasks/{task_id}/dedupe/level2/{group_id} - 获取单个二层分组详情"""
        try:
            if not _download_db:
                error = json.dumps({"error": "数据库未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]

            runtime_status_map = {}
            if _deduplicator and hasattr(_deduplicator, "get_download_status_map"):
                runtime_status_map = _deduplicator.get_download_status_map(task_id)

            detail = _download_db.get_two_level_dedupe_group_detail(
                task_id,
                group_id,
                runtime_status_map=runtime_status_map,
            )
            if not detail:
                error = json.dumps({"error": "分组不存在"}, ensure_ascii=False).encode("utf-8")
                start_response("404 Not Found", [("Content-Type", "application/json; charset=utf-8")])
                return [error]

            response = json.dumps(detail, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"获取二层分组详情失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]

    def handle_api_dedupe_task_level2_interest(self, environ, start_response, task_id: int, group_id: str):
        """POST /api/dedupe/tasks/{task_id}/dedupe/level2/{group_id}/interest - 设置分组兴趣状态"""
        try:
            if not _download_db:
                error = json.dumps({"error": "数据库未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]

            body = self._read_request_body(environ)
            uninterested = bool(body.get("uninterested", True))
            _download_db.set_dedupe_level2_uninterested(task_id, group_id, uninterested=uninterested)

            response = json.dumps({
                "success": True,
                "group_id": group_id,
                "uninterested": uninterested,
            }, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"设置分组兴趣状态失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]


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
        if path.startswith("/dashboard") or path.startswith("/api/") or path.startswith("/static/") or path.startswith("/assets/") or path == "/favicon.svg" or path == "/icons.svg":
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
        self._web_dist_dir = Path(__file__).parent.parent / "web" / "dist"
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

        # 如果配置了用户名和密码，就启用认证
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
            # 没有认证时，使用 True 允许匿名访问
            config["http_authenticator"] = None
            config["simple_dc"] = {
                "user_mapping": {
                    self.config.mount_path: True,
                },
            }

        return config

    def _get_health_check_port(self) -> int:
        if self._httpd:
            return int(self._httpd.server_address[1])
        return self.config.port

    def _run_health_check(self):
        """运行健康检查 - 请求 /health，确认应用线程能正常响应。"""
        logger.info(f"健康检查线程启动，_monitoring_db={_monitoring_db}")
        
        # 先等 10 秒，让服务器完全启动
        logger.info(f"等待 10 秒让服务器启动完成")
        if self._stop_event.wait(10):
            return
        
        # 连续失败计数器
        consecutive_failures = 0
        
        while not self._stop_event.is_set():
            try:
                start_time = time.time()
                conn = None
                conn = http.client.HTTPConnection(
                    "127.0.0.1",
                    self._get_health_check_port(),
                    timeout=self.config.health_check_timeout,
                )
                conn.request("GET", "/health")
                response = conn.getresponse()
                body = response.read()
                conn.close()

                if response.status == 200 and body == b"OK":
                    response_time = (time.time() - start_time) * 1000
                    consecutive_failures = 0
                    self._failure_count = 0
                    if _monitoring_db:
                        try:
                            _monitoring_db.record_health_check("success", response_time)
                            logger.debug(f"健康检查成功，已记录")
                        except Exception as record_err:
                            logger.error(f"记录健康检查失败: {record_err}")
                    else:
                        logger.debug(f"健康检查成功，_monitoring_db 未设置，不记录")
                    logger.debug(f"健康检查成功，响应时间: {response_time:.2f}ms")
                else:
                    raise RuntimeError(f"GET /health returned {response.status}: {body!r}")
            except Exception as e:
                if conn:
                    conn.close()
                response_time = (time.time() - start_time) * 1000
                error_msg = str(e)
                logger.warning(f"健康检查失败: {error_msg}")
                
                consecutive_failures += 1
                self._failure_count = consecutive_failures
                
                if _monitoring_db:
                    try:
                        _monitoring_db.record_health_check("failed", response_time, error_msg)
                    except Exception as record_err:
                        logger.error(f"记录健康检查失败: {record_err}")
                
                logger.warning(f"真实健康检查失败 ({consecutive_failures}/{self.config.health_check_failure_threshold}): {error_msg}")
                if consecutive_failures >= self.config.health_check_failure_threshold:
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
        
        self._restart_timestamps.append(time.time())
        
        # 停止服务器和主线程
        self.stop()
        
        # 健康检查运行在子线程中，sys.exit() 只会退出当前线程。
        # 这里必须退出整个进程，才能让 systemd 的 Restart=always 接管。
        logging.shutdown()
        os._exit(1)

    def _cleanup_stuck_tasks(self):
        """清理卡住的任务（比如状态是 scanning 但实际上不在运行的）"""
        global _download_db
        if not _download_db:
            return
        
        try:
            tasks = _download_db.list_dedupe_tasks()
            for task in tasks:
                if task["status"] == "scanning":
                    # 检查这个任务是否有正在运行的 future
                    task_id = task["id"]
                    if task_id not in _dedupe_tasks or _dedupe_tasks[task_id].done():
                        # 任务卡住了，重置为 pending 或者设置为 failed
                        logger.warning(f"任务 {task_id} 卡住了，重置为 pending 状态")
                        _download_db.update_dedupe_task(task_id, status="pending")
                        # 清理这个任务的 future
                        if task_id in _dedupe_tasks:
                            del _dedupe_tasks[task_id]
        except Exception as e:
            logger.error(f"清理卡住任务时出错: {e}")

    def _run_server(self):
        """在独立线程中运行服务器"""
        try:
            webdav_app_obj = None
            if self.config.enable and WEBDAV_AVAILABLE:
                wd_config = self._build_webdav_config()
                webdav_app_obj = WsgiDAVApp(wd_config)
            
            monitoring_app = MonitoringApp(self._static_dir, self._web_dist_dir, self.config.monitoring_username, self.config.monitoring_password)
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

            server_backlog = max(1, int(self.config.server_backlog))

            class ConfiguredThreadingWSGIServer(ThreadingWSGIServer):
                request_queue_size = server_backlog

            # 创建服务器
            self._httpd = make_server(
                self.config.host,
                self.config.port,
                combined_app,
                server_class=ConfiguredThreadingWSGIServer
            )

            logger.info(f"服务器启动在 http://{self.config.host}:{self.config.port}")
            logger.info(f"监控看板: http://{self.config.host}:{self.config.port}/dashboard")
            if self.config.enable:
                logger.info(f"WebDAV: http://{self.config.host}:{self.config.port}/")

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
