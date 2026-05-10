# Telegram 群组媒体去重功能设计文档

**日期：2026-05-09
**作者：AI Assistant

## 一、概述

本设计文档描述了为 tg-download 项目新增的群组媒体去重功能。该功能允许用户扫描 Telegram 群组/频道中的媒体消息，识别重复内容（基于 Telegram file_id），并在 Dashboard 上展示去重结果，支持下载独特版本到本地。

### 1.1 背景与目标

- **背景**：用户有一个包含 200,000+ 条消息的群组，存在大量重复媒体
- **目标用户**：Telegram 普通成员（无删除消息权限）
- **核心目标**：
  1. 快速扫描群组历史，识别重复媒体
  2. 在 Dashboard 展示去重报告
  3. 下载独特媒体（仅一份）
  4. 支持断点续扫
  5. 后续新消息实时去重

---

## 二、总体架构

### 2.1 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                React + TypeScript Dashboard (Frontend)             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Overview   │  │ Downloads  │  │   Dedupe   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌──────────────────────────────────────────────────────┐  │
│  │           去重页面：群组选择、进度、报告、操作按钮              │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   MonitoringApp (Backend)                    │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  /api/dedupe/*  - 去重相关 API                        │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Deduplicator (新增)                       │
│  ┌──────────────────┐  ┌──────────────────┐                │
│  │  scan_chat()    │  │  find_duplicates()│                │
│  └──────────────────┘  └──────────────────┘                │
│  ┌──────────────────┐  ┌──────────────────┐                │
│  │ pause_scan()    │  │ resume_scan()    │                │
│  └──────────────────┘  └──────────────────┘                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              DownloadDB + DedupeDB (数据库扩展)              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  dedupe_tasks    - 去重任务表                          │  │
│  │  dedupe_media    - 媒体指纹表                          │  │
│  │  dedupe_results  - 去重结果表                          │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心组件说明

| 组件 | 职责 |
|------|------|
| `Deduplicator` | 去重引擎核心，负责扫描、去重逻辑、暂停/恢复 |
| `DownloadDB` 扩展 | 新增 3 张表存储去重任务和结果 |
| MonitoringApp 扩展 | 新增去重相关 API 端点 |
| React Dashboard | 重构后的前端界面，含去重页面 |

---

## 三、数据库设计

### 3.1 新增表结构

#### 表 1：`dedupe_tasks` - 去重任务表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| chat_id | TEXT | 群组/频道 ID |
| chat_title | TEXT | 群组名称 |
| status | TEXT | 任务状态（pending/scanning/paused/completed/failed） |
| start_message_id | INTEGER | 起始消息 ID |
| last_scanned_message_id | INTEGER | 最后扫描的消息 ID（断点续扫） |
| total_messages | INTEGER | 预估总消息数 |
| processed_messages | INTEGER | 已处理消息数 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

#### 表 2：`dedupe_media` - 媒体指纹表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| task_id | INTEGER | 关联的去重任务 ID |
| file_id | TEXT | Telegram file_id（去重键） |
| file_size | INTEGER | 文件大小（字节） |
| duration | INTEGER | 视频时长（秒） |
| width | INTEGER | 视频宽度 |
| height | INTEGER | 视频高度 |
| first_seen_message_id | INTEGER | 最早出现的消息 ID |
| first_seen_date | TIMESTAMP | 最早发布时间 |
| occurrence_count | INTEGER | 出现次数 |

**唯一约束**：`(task_id, file_id)`

#### 表 3：`dedupe_results` - 去重结果表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| task_id | INTEGER | 关联的去重任务 ID |
| message_id | INTEGER | 消息 ID |
| file_id | TEXT | Telegram file_id |
| is_duplicate | BOOLEAN | 是否是重复的 |
| is_original | BOOLEAN | 是否是最早的（保留项） |
| downloaded | BOOLEAN | 是否已下载 |
| created_at | TIMESTAMP | 创建时间 |

### 3.2 数据库迁移

在 `DownloadDB._migrate()` 方法中添加创建新表的逻辑，保持向后兼容性。

---

## 四、API 设计

### 4.1 新增 API 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/dedupe/chats` | GET | 获取可扫描的群组/频道列表 |
| `/api/dedupe/tasks` | GET | 获取去重任务列表 |
| `/api/dedupe/tasks` | POST | 创建新的去重任务 |
| `/api/dedupe/tasks/:id` | GET | 获取单个任务详情 |
| `/api/dedupe/tasks/:id/start` | POST | 开始扫描 |
| `/api/dedupe/tasks/:id/pause` | POST | 暂停扫描 |
| `/api/dedupe/tasks/:id/resume` | POST | 恢复扫描 |
| `/api/dedupe/tasks/:id/media` | GET | 获取去重后的媒体列表（分页、搜索、筛选） |
| `/api/dedupe/tasks/:id/download` | POST | 下载独特媒体 |

### 4.2 API 响应示例

#### 获取任务详情

```json
{
  "id": 1,
  "chat_id": "-1001234567890",
  "chat_title": "我的视频群",
  "status": "scanning",
  "total_messages": 200000,
  "processed_messages": 50000,
  "unique_media": 8000,
  "duplicate_count": 12000,
  "progress": 25
}
```

#### 获取媒体列表（分页）

```json
{
  "items": [
    {
      "file_id": "AgACAgUAAj...",
      "file_size": 104857600,
      "duration": 120,
      "width": 1920,
      "height": 1080,
      "occurrence_count": 50,
      "first_seen_message_id": 12345,
      "first_seen_date": "2026-01-01T00:00:00Z",
      "is_original": true,
      "downloaded": false
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 15000,
    "total_pages": 750
  }
}
```

---

## 五、前端设计

### 5.1 技术栈

- **框架**：React 18 + TypeScript
- **构建工具**：Vite
- **样式**：Tailwind CSS 3
- **图表**：Chart.js + react-chartjs-2
- **路由**：React Router
- **HTTP 客户端**：Axios

### 5.2 项目结构

```
web/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── router.tsx
│   ├── api/
│   │   └── client.ts
│   ├── components/
│   │   ├── Layout.tsx
│   │   └── Navbar.tsx
│   ├── pages/
│   │   ├── Overview.tsx
│   │   ├── Downloads.tsx
│   │   ├── Uploads.tsx
│   │   └── Dedupe.tsx
│   └── types/
│       └── index.ts
```

### 5.3 去重页面设计

```
┌─────────────────────────────────────────────────────────┐
│  概览  │  下载历史  │  上传统计  │  **去重**  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────────────────────────────────────────┐  │
│  │  选择群组：[下拉选择群组 ▼]  [开始扫描]    │  │
│  └─────────────────────────────────────────────────┘  │
│                                                         │
│  ┌─────────────────────────────────────────────────┐  │
│  │  扫描进度：[████████░░░░░░░░░░] 45%          │  │
│  │  已处理：90,000 / 200,000 条消息            │  │
│  │  独特视频：15,000 个                           │  │
│  │  重复视频：10,000 个（重复率 40%）            │  │
│  │  预估剩余时间：15 分钟                             │  │
│  │  [暂停] [恢复]                                  │  │
│  └─────────────────────────────────────────────────┘  │
│                                                         │
│  ┌─────────────────────────────────────────────────┐  │
│  │  去重报告                                      │  │
│  │  [搜索 file_id...]  [筛选：全部/独特/重复]  │  │
│  │  ┌─────────────────────────────────────────┐  │  │
│  │  │ 预览图 │  file_id  │ 出现次数 │ 操作  │  │  │
│  │  ├─────────────────────────────────────────┤  │  │
│  │  │  🖼️   │  xxx...  │   50    │ [下载] │  │  │
│  │  │  🖼️   │  xxx...  │   42    │ [下载] │  │  │
│  │  └─────────────────────────────────────────┘  │  │
│  │  [← 上一页]  第 1 页 / 共 150 页  [下一页 →]  │  │
│  └─────────────────────────────────────────────────┘  │
│                                                         │
│  [下载全部独特视频]  [导出报告]                       │
└─────────────────────────────────────────────────────────┘
```

### 5.4 后端静态文件服务调整

- `/` 和 `/dashboard` → React 构建产物
- `/api/*` → API 端点（不变）
- `/dashboard-legacy` → 旧版 Dashboard（备份）

---

## 六、核心模块设计

### 6.1 `Deduplicator` 类

```python
class Deduplicator:
    """去重引擎核心类"""

    def __init__(self, client: TelegramClient, db: DownloadDB):
        self.client = client
        self.db = db
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        self._running = False

    async def create_task(self, chat_id: str) -> int:
        """创建新的去重任务"""

    async def scan_chat(self, task_id: int) -> None:
        """扫描群组消息（支持暂停/恢复）"""
        # 从数据库读取 last_scanned_message_id
        # 从新到旧迭代消息
        # 每 1000 条保存一次进度
        # 检查 self._pause_event

    async def pause_scan(self, task_id: int) -> None:
        """暂停扫描"""

    async def resume_scan(self, task_id: int) -> None:
        """恢复扫描"""

    async def get_media_list(
        self,
        task_id: int,
        page: int = 1,
        limit: int = 20,
        search: str | None = None,
        filter_type: str = "all"
    ) -> dict:
        """获取去重后的媒体列表"""

    async def download_media(self, task_id: int, file_id: str | None = None) -> None:
        """下载独特媒体"""
```

---

## 七、错误处理

### 7.1 错误类型和处理策略

| 错误类型 | 处理策略 |
|---------|---------|
| Telegram API 限流 | 使用 `FloodWaitCoordinator` 自动等待重试 |
| 网络断开 | 记录进度，自动重连后继续 |
| 群组无权限 | 任务设为 failed，记录错误 |
| 消息被删除 | 跳过继续 |
| 元数据获取失败 | 记录警告，跳过继续 |
| 数据库写入失败 | 回滚，重试 3 次 |

### 7.2 任务状态流转

```
pending → scanning ↔ paused → completed
         ↓
        failed
```

---

## 八、测试计划

### 8.1 单元测试

| 模块 | 测试内容 |
|------|---------|
| `Deduplicator` | 创建任务、暂停/恢复、分页查询 |
| `DownloadDB` 扩展 | 新表 CRUD、数据库迁移 |
| API 端点 | 请求/响应验证 |

### 8.2 集成测试

1. 小规模测试群扫描（100-500 条）
2. 去重逻辑验证（人为制造重复）
3. 断点续扫验证
4. 下载功能验证

---

## 九、实施步骤

1. **数据库层**：扩展 `DownloadDB`，添加新表和迁移逻辑
2. **核心引擎**：实现 `Deduplicator` 类
3. **API 层**：添加去重相关端点
4. **前端**：React + TypeScript 重构，含去重页面
5. **测试**：单元测试和集成测试
6. **部署**：更新远程服务器

---

## 十、注意事项

- 所有新增代码必须有单元测试
- 保留旧版 Dashboard 作为备份
- 使用现有的 `FloodWaitCoordinator` 进行限流
- 扫描进度每 1000 条消息保存一次

