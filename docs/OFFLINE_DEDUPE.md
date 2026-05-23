# 离线高精度去重方案

适用于：生产环境服务器无 GPU，但有 GPU 的 Windows 机器可用于离线计算的场景。

---

## 🎯 为你的 RTX 2070 Ti 定制方案

| 项目 | 推荐配置 |
|------|---------|
| **GPU** | RTX 2070 Ti (8GB VRAM) |
| **推荐模型** | **DINOv2-Base** (`dinov2_base`) |
| **特征维度** | 768 |
| **显存占用** | ~3-4GB |
| **推荐阈值** | 0.85 |
| **预计速度** | 10万张约 10-15 分钟 |

---

## 📦 完整流程

### 1️⃣ 在生产服务器上导出数据

```bash
# 进入项目目录
cd /path/to/tg_download

# 导出指定任务的数据
python scripts/export_for_offline.py --task-id <你的任务ID>
```

参数说明：
- `--task-id`: 要去重的任务 ID（必填）
- `--output`: 输出目录（默认：`offline_data`）
- `--db`: 数据库路径（默认：`downloads.db`）

输出：
- 生成 `offline_data/task_<id>_offline.zip` 文件
- 包含缩略图和元数据

---

### 2️⃣ 将压缩包传输到 Windows 机器

使用你喜欢的方式传输：
- SCP / SFTP
- 共享文件夹
- 云盘（如百度网盘等）

---

### 3️⃣ 在 Windows 机器上安装依赖

#### 基础依赖（必须）
```powershell
pip install numpy pillow tqdm
```

#### DINOv2 + PyTorch（推荐，精度最高）

**方案 A：GPU 版本（RTX 2070 Ti 用这个）**
```powershell
# 先安装 PyTorch（GPU 版本）- 注意不需要 torchaudio！
pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# DINOv2 会自动下载，无需额外安装
```

**方案 B：CPU 版本（没有 GPU 可用）**
```powershell
pip3 install torch torchvision
```

#### FAISS 加速（可选，推荐安装）
```powershell
# CPU FAISS（大部分情况够用）
pip install faiss-cpu

# 或者 GPU FAISS（更快，但需要 CUDA 编译正确）
# 注意：faiss-gpu 在 Windows 上较难安装，建议用 faiss-cpu
```

#### CLIP 方案（可选）
如果你想用 CLIP 而不是 DINOv2：
```powershell
pip install git+https://github.com/openai/clip.git
```

#### 降级方案（完全无 GPU）
```powershell
pip install imagehash
```

---

### 4️⃣ 在 Windows 机器上运行去重

#### 🚀 推荐：DINOv2-Base（适合 RTX 2070 Ti）
```powershell
# 进入存放压缩包的目录
cd C:\path\to\data

# 第一次运行：解压并处理，同时保留临时目录避免下次重复解压
python scripts/offline_dedupe.py --input task_123_offline.zip --keep-temp

# 后续运行：自动跳过解压，直接处理（如果之前用了 --keep-temp）
python scripts/offline_dedupe.py --input task_123_offline.zip

# 如果想更快，用 DINOv2-Small（精度略降）
python scripts/offline_dedupe.py --input task_123_offline.zip --model dinov2_small

# 调整相似度阈值（DINOv2 默认 0.85）
python scripts/offline_dedupe.py --input task_123_offline.zip --threshold 0.82
```

#### 其他模型选项
```powershell
# CLIP
python scripts/offline_dedupe.py --input task_123_offline.zip --model clip_vit_b32 --threshold 0.95

# 多哈希组合（无 GPU）
python scripts/offline_dedupe.py --input task_123_offline.zip --model hash

# 强制用 CPU（即使有 GPU）
python scripts/offline_dedupe.py --input task_123_offline.zip --device cpu
```

输出：
- `offline_results/dedupe_results.json` - 去重结果
- `offline_results/dedupe_results.zip` - 打包好的结果

---

### 5️⃣ 将结果传输回生产服务器

将 `dedupe_results.zip` 传回生产服务器。

---

### 6️⃣ 在生产服务器上导入结果

```bash
# 进入项目目录
cd /path/to/tg_download

# 先试运行看看（不实际写入数据库）
python scripts/import_results.py --task-id <任务ID> --input dedupe_results.zip --dry-run

# 确认没问题后，正式导入
python scripts/import_results.py --task-id <任务ID> --input dedupe_results.zip
```

---

## 📊 模型选择指南

| 模型 | 精度 | 速度 | VRAM | 特征维度 | 推荐阈值 | 适用场景 |
|------|------|------|------|---------|---------|---------|
| **DINOv2-Small** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ~2GB | 384 | 0.82 | 数据量大，要速度快 |
| **DINOv2-Base** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ~3-4GB | 768 | 0.85 | **推荐（RTX 2070 Ti）** |
| **CLIP ViT-B/32** | ⭐⭐⭐ | ⭐⭐⭐ | ~2GB | 512 | 0.95 | 通用场景 |
| **多哈希组合** | ⭐⭐ | ⭐⭐⭐⭐⭐ | 0 | 192 | - | 完全无 GPU |

---

## 🎨 DINOv2 是什么？

**DINOv2** 是 Meta 发布的自监督视觉模型，专门为图像特征学习设计：
- ✅ 不需要图像-文本对，纯图像训练（自监督）
- ✅ 在 ImageNet 1.4 亿张图上训练
- ✅ 对图像细节更敏感，特别适合去重
- ✅ 特征质量比 CLIP 更高（针对纯视觉任务）

---

## ⚙️ 参数调优

### 调整相似度阈值

**DINOv2 建议范围：0.80-0.90**

| 阈值 | 严格度 | 说明 |
|------|--------|------|
| 0.90+ | 极高 | 只匹配几乎完全相同的，可能漏检 |
| **0.85** | 高 | **推荐（默认）** |
| 0.82 | 中高 | 略宽松 |
| 0.80 | 中 | 比较宽松 |
| 0.75 | 低 | 可能误报 |

**如何选择：**
1. 先用 0.85 运行
2. 看分组结果中的缩略图
3. 如果发现不同的图分到同一组 → 调高阈值（如 0.87）
4. 如果发现漏检 → 调低阈值（如 0.82）

---

## 🔍 结果验证

导入完成后，在 Web 界面查看去重结果：
1. 访问 Dashboard
2. 进入去重任务
3. 查看第二层去重分组
4. 点击查看分组详情
5. 确认缩略图是否真的相似

---

## 💡 常见问题

### Q: DINOv2 第一次运行很慢？
A: 第一次会自动下载模型（~300MB for Base，~100MB for Small），之后就快了。

### Q: 显存不够怎么办？
A: 用 `--model dinov2_small`，显存只需要 ~2GB。

### Q: DINOv2 和 CLIP 有什么区别？
A: DINOv2 是纯视觉自监督模型，特征更适合去重；CLIP 是多模态模型，需要图像-文本对训练。DINOv2 对纯视觉相似度任务更准确。

### Q: 提示「CUDA 不可用，使用 CPU」怎么办？
A: 按以下步骤排查：

1. **确认在 Windows 机器上运行**（当前是 macOS 环境没有 NVIDIA GPU）
2. **验证 PyTorch 和 CUDA 安装**：
   ```powershell
   python -c "import torch; print(f'CUDA 可用: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"
   ```
3. **重新安装带 CUDA 支持的 PyTorch**：
   ```powershell
   pip uninstall torch torchvision
   pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
   ```
4. **强制指定 GPU 设备**（如果 CUDA 可用但脚本没检测到）：
   ```powershell
   python scripts/offline_dedupe.py --input task_123_offline.zip --device cuda
   ```

### Q: 如何确认是否真的在用 GPU？
A: 运行脚本时会显示：
- ✅ 显示 `💻 运行设备: cuda` 或 `💻 运行设备: cuda:0` 表示正在用 GPU
- ✅ 显示 `✅ DINOv2 模型已加载到 cuda` 表示模型已加载到 GPU
- ✅ 显示 `⚡ 使用 GPU FAISS 加速` 表示 FAISS 也在使用 GPU

你也可以在运行时打开任务管理器 → 性能 → GPU，看 GPU 利用率是否上升。

---

## 📈 性能预估（RTX 2070 Ti）

| 媒体数量 | DINOv2-Base | DINOv2-Small |
|---------|------------|-------------|
| 1万张 | ~1-2分钟 | ~30-60秒 |
| 5万张 | ~5-8分钟 | ~3-4分钟 |
| 10万张 | ~10-15分钟 | ~6-8分钟 |

---

## 🎉 总结

这个方案完美解决了：
✅ 生产环境不需要 GPU
✅ Windows RTX 2070 Ti 可以充分利用 GPU
✅ DINOv2 提供业界领先的图像特征
✅ 完整的端到端流程，易于使用

**你的 RTX 2070 Ti 已经准备好了！🚀**
