from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
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

# 全局监控实例
_monitoring_db = None
# 全局去重相关实例
_deduplicator = None
_download_db = None
# 缓存聊天列表
_cached_chats: list[dict] = []
# 主事件循环（来自 CLI）
_main_event_loop = None
# 全局异步任务管理
_dedupe_tasks: Dict[int, asyncio.Future] = {}



def set_monitoring_db(db):
    """设置监控数据库实例"""
    global _monitoring_db
    _monitoring_db = db


def set_deduplication_resources(deduplicator, download_db, chats=None, event_loop=None):
    """设置去重相关资源"""
    global _deduplicator
    global _download_db
    global _cached_chats
    global _main_event_loop
    _deduplicator = deduplicator
    _download_db = download_db
    
    # 保存主事件循环
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
    """简单的监控 WSGI 应用，支持 HTTP Basic 认证"""

    def __init__(self, static_dir: Path, web_dist_dir: Path, username: str, password: str):
        self.static_dir = static_dir
        self.web_dist_dir = web_dist_dir
        self.username = username
        self.password = password
        self.routes = {
            "/": self.handle_dashboard,
            "/dashboard": self.handle_dashboard,
            "/dashboard-legacy": self.handle_dashboard_legacy,
            "/api/dashboard/stats": self.handle_api_stats,
            "/api/downloads": self.handle_api_downloads,
            "/api/uploads": self.handle_api_uploads,
            "/api/system": self.handle_api_system,
            "/api/health/checks": self.handle_api_health_checks,
            "/api/health/recoveries": self.handle_api_recoveries,
            "/health": self.handle_health_endpoint,
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

    def check_auth(self, environ):
        """检查 HTTP Basic 认证"""
        if not self.username or not self.password:
            return True  # 没有配置用户名密码，跳过认证
        
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

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "/")

        # 健康检查端点跳过认证
        if path == "/health":
            return self.handle_health_endpoint(environ, start_response)

        # 静态资源跳过认证（/assets/、/favicon.svg、/icons.svg）
        is_static_resource = path.startswith("/assets/") or path == "/favicon.svg" or path == "/icons.svg"
        
        # 其他路由检查认证
        if not is_static_resource and not self.check_auth(environ):
            start_response("401 Unauthorized", [
                ("WWW-Authenticate", 'Basic realm="tg-download monitoring"'),
                ("Content-Type", "text/plain; charset=utf-8")
            ])
            return [b"401 Unauthorized"]

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

        # 检查是否是新版 React 应用的前端路由（需要返回 index.html）
        if self.web_dist_dir.exists():
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
        """POST /api/dedupe/tasks/{task_id}/start - 开始扫描"""
        try:
            if not _deduplicator:
                error = json.dumps({"error": "去重器未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            if not _main_event_loop:
                error = json.dumps({"error": "事件循环未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            if task_id in _dedupe_tasks and not _dedupe_tasks[task_id].done():
                error = json.dumps({"error": "任务已经在运行中"}, ensure_ascii=False).encode("utf-8")
                start_response("400 Bad Request", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            # 在主事件循环中运行任务
            future = asyncio.run_coroutine_threadsafe(_deduplicator.scan_chat(task_id), _main_event_loop)
            _dedupe_tasks[task_id] = future
            
            response = json.dumps({"success": True, "message": "扫描任务已启动"}, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"启动扫描失败: {e}")
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
            
            media_list = []
            total = 0
            if _deduplicator:
                media_list = _deduplicator.get_media_list(task_id, page, limit, search, filter_type)
                # 暂时假设总数就是当前列表长度，实际应该从数据库获取
                total = len(media_list)
            
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
            
            if not _main_event_loop:
                error = json.dumps({"error": "事件循环未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            # 在主事件循环中运行下载任务
            asyncio.run_coroutine_threadsafe(
                _deduplicator.download_media(task_id, output_dir, file_id=file_id, download_all=download_all),
                _main_event_loop
            )
            
            response = json.dumps({"success": True, "message": "下载任务已启动"}, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"启动下载失败: {e}")
            error = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
            return [error]

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
        """POST /api/dedupe/tasks/{task_id}/restart - 重置并重跑去重任务"""
        try:
            if not _download_db:
                error = json.dumps({"error": "数据库未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            if not _deduplicator:
                error = json.dumps({"error": "去重器未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            if not _main_event_loop:
                error = json.dumps({"error": "事件循环未初始化"}, ensure_ascii=False).encode("utf-8")
                start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8")])
                return [error]
            
            # 如果任务还在运行，先取消
            if task_id in _dedupe_tasks and not _dedupe_tasks[task_id].done():
                _dedupe_tasks[task_id].cancel()
            
            # 重置任务
            _download_db.reset_dedupe_task(task_id)
            
            # 启动扫描并跟踪任务
            future = asyncio.run_coroutine_threadsafe(
                _deduplicator.scan_chat(task_id),
                _main_event_loop
            )
            _dedupe_tasks[task_id] = future
            
            response = json.dumps({"success": True, "message": "任务已重置并开始重新扫描"}, ensure_ascii=False).encode("utf-8")
            start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
            return [response]
        except Exception as e:
            logger.error(f"重置任务失败: {e}")
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
        if path == "/" or path.startswith("/dashboard") or path.startswith("/api/") or path.startswith("/static/") or path.startswith("/assets/") or path == "/favicon.svg" or path == "/icons.svg":
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
        
        # 连续失败计数器
        consecutive_failures = 0
        
        while not self._stop_event.is_set():
            try:
                start_time = time.time()
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.config.health_check_timeout)
                result = sock.connect_ex(('127.0.0.1', self.config.port))
                sock.close()
                
                if result == 0:
                    response_time = (time.time() - start_time) * 1000
                    consecutive_failures = 0
                    self._failure_count = 0
                    if _monitoring_db:
                        try:
                            _monitoring_db.record_health_check("success", response_time)
                            # 减少日志噪音，只记录调试信息
                            logger.debug(f"健康检查成功，已记录")
                        except Exception as record_err:
                            logger.error(f"记录健康检查失败: {record_err}")
                    else:
                        logger.debug(f"健康检查成功，_monitoring_db 未设置，不记录")
                    logger.debug(f"健康检查成功，响应时间: {response_time:.2f}ms")
                else:
                    raise Exception(f"Socket connection failed, result={result}")
            except Exception as e:
                response_time = (time.time() - start_time) * 1000
                error_msg = str(e)
                
                # 对于常见的临时错误（如资源暂时不可用），降低日志级别
                is_temporary_error = '11' in error_msg or 'EAGAIN' in error_msg or 'EWOULDBLOCK' in error_msg
                
                if is_temporary_error:
                    logger.debug(f"健康检查遇到临时错误: {error_msg}")
                else:
                    logger.warning(f"健康检查失败: {error_msg}")
                
                consecutive_failures += 1
                self._failure_count = consecutive_failures
                
                if _monitoring_db:
                    try:
                        # 临时错误标记为 warning 而不是 failed
                        status = "warning" if is_temporary_error else "failed"
                        _monitoring_db.record_health_check(status, response_time, error_msg)
                    except Exception as record_err:
                        logger.error(f"记录健康检查失败: {record_err}")
                
                # 只有真正的失败（非临时错误）才计入恢复机制
                if not is_temporary_error:
                    logger.warning(f"真实健康检查失败 ({consecutive_failures}/{self.config.health_check_failure_threshold}): {error_msg}")
                    # 检查是否需要触发恢复
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
        
        # 退出进程让 systemd 重启
        import sys
        sys.exit(1)

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
            # 启动前清理卡住的任务
            self._cleanup_stuck_tasks()
            
            webdav_app_obj = None
            if self.config.enable and WEBDAV_AVAILABLE:
                wd_config = self._build_webdav_config()
                webdav_app_obj = WsgiDAVApp(wd_config)
            
            monitoring_app = MonitoringApp(self._static_dir, self._web_dist_dir, self.config.username, self.config.password)
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

            # 创建服务器
            self._httpd = make_server(
                self.config.host,
                self.config.port,
                combined_app,
                server_class=WSGIServer
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
