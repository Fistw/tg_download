#!/usr/bin/env python3
"""
离线高精度去重计算脚本（Windows/GPU 版本，支持多种模型）

支持的模型：
- DINOv2 (推荐)：dinov2_small, dinov2_base
- CLIP：clip_vit_b32
- 多哈希组合：hash

依赖安装（完整）：
    pip install torch torchvision numpy pillow tqdm
    # DINOv2：自动下载
    # CLIP：pip install git+https://github.com/openai/clip.git
    # FAISS 加速：pip install faiss-cpu
    # GPU FAISS：pip install faiss-gpu

使用：
    # 默认用 DINOv2-Base（适合 RTX 2070 Ti）
    python scripts/offline_dedupe.py --input task_123_offline.zip

    # 用 DINOv2-Small（更快）
    python scripts/offline_dedupe.py --input task_123_offline.zip --model dinov2_small

    # 用 CLIP
    python scripts/offline_dedupe.py --input task_123_offline.zip --model clip_vit_b32

    # 用多哈希组合（无 GPU）
    python scripts/offline_dedupe.py --input task_123_offline.zip --model hash

    # 调整阈值
    python scripts/offline_dedupe.py --input task_123_offline.zip --threshold 0.85
"""

import argparse
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Dict, List, Optional
import sys

try:
    import numpy as np
    from PIL import Image
    from tqdm import tqdm
except ImportError as e:
    print(f"⚠️  缺少基础依赖: {e}")
    print("请安装: pip install numpy pillow tqdm")
    sys.exit(1)

# =============================================================================
# 特征提取基类
# =============================================================================

class BaseFeatureExtractor:
    """特征提取基类"""
    def extract(self, img: Image.Image) -> np.ndarray:
        raise NotImplementedError

    @property
    def feature_dim(self) -> int:
        raise NotImplementedError


class HashFeatureExtractor(BaseFeatureExtractor):
    """多哈希组合方案（pHash+dHash+wHash）"""
    def __init__(self):
        try:
            import imagehash
            self.imagehash = imagehash
            self.enabled = True
        except ImportError:
            self.enabled = False
        print("🔗 使用方案：多哈希组合 (pHash + dHash + wHash)")

    @property
    def feature_dim(self) -> int:
        return 64 * 3  # 每种哈希 64 位

    def extract(self, img: Image.Image) -> np.ndarray:
        if not self.enabled:
            return np.zeros(self.feature_dim)

        img_gray = img.convert("L")
        phash = np.array(self.imagehash.phash(img_gray).hash.flatten().astype(float))
        dhash = np.array(self.imagehash.dhash(img_gray).hash.flatten().astype(float))
        whash = np.array(self.imagehash.whash(img_gray).hash.flatten().astype(float))

        return np.concatenate([phash, dhash, whash])


class DINOv2FeatureExtractor(BaseFeatureExtractor):
    """DINOv2 特征提取器（Meta 自监督视觉模型）"""

    MODELS = {
        "dinov2_small": "facebookresearch/dinov2/dinov2_vits14",
        "dinov2_base": "facebookresearch/dinov2/dinov2_vitb14"
    }

    MODEL_DIMS = {
        "dinov2_small": 384,
        "dinov2_base": 768
    }

    def __init__(self, model_name: str = "dinov2_base", device: str = "cuda"):
        self.device = device
        self.model_name = model_name
        self.model = None
        self.transform = None
        self._initialized = False
        self._load_model()

    @property
    def feature_dim(self) -> int:
        return self.MODEL_DIMS[self.model_name]

    def _load_model(self):
        try:
            import torch
            from torchvision import transforms

            print(f"🚀 正在加载 DINOv2 模型: {self.model_name}")

            # 图像预处理
            self.transform = transforms.Compose([
                transforms.Resize(256),
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                     std=[0.229, 0.224, 0.225]),
            ])

            # 自动下载并加载模型
            repo, model_name = self.MODELS[self.model_name].rsplit('/', 1)
            self.model = torch.hub.load(repo, model_name, pretrained=True)
            self.model.to(self.device)
            self.model.eval()

            self._initialized = True
            print(f"✅ DINOv2 模型已加载到 {self.device}")
            print(f"   特征维度: {self.feature_dim}")

        except Exception as e:
            print(f"⚠️  无法加载 DINOv2: {e}")
            print("💡 提示：需要 PyTorch 和网络连接")

    def extract(self, img: Image.Image) -> np.ndarray:
        if not self._initialized:
            return np.zeros(self.feature_dim)

        try:
            import torch

            img_tensor = self.transform(img).unsqueeze(0).to(self.device)

            with torch.no_grad():
                features = self.model(img_tensor)

            return features.cpu().numpy().flatten()
        except Exception as e:
            print(f"⚠️  特征提取失败: {e}")
            return np.zeros(self.feature_dim)


class CLIPFeatureExtractor(BaseFeatureExtractor):
    """CLIP 图像特征提取器"""

    def __init__(self, model_name: str = "clip_vit_b32", device: str = "cuda"):
        self.device = device
        self.model_name = model_name
        self.model = None
        self.preprocess = None
        self._initialized = False
        self._load_model()

    @property
    def feature_dim(self) -> int:
        return 512

    def _load_model(self):
        try:
            import clip
            import torch

            print(f"🚀 正在加载 CLIP 模型: {self.model_name}")

            clip_model_map = {
                "clip_vit_b32": "ViT-B/32",
                "clip_vit_b16": "ViT-B/16"
            }

            self.model, self.preprocess = clip.load(
                clip_model_map.get(self.model_name, "ViT-B/32"),
                device=self.device
            )
            self.model.eval()

            self._initialized = True
            print(f"✅ CLIP 模型已加载到 {self.device}")

        except Exception as e:
            print(f"⚠️  无法加载 CLIP: {e}")
            print("💡 提示：pip install git+https://github.com/openai/clip.git")

    def extract(self, img: Image.Image) -> np.ndarray:
        if not self._initialized:
            return np.zeros(512)

        try:
            import clip
            import torch

            img_tensor = self.preprocess(img).unsqueeze(0).to(self.device)

            with torch.no_grad():
                features = self.model.encode_image(img_tensor)

            return features.cpu().numpy().flatten()
        except Exception as e:
            print(f"⚠️  特征提取失败: {e}")
            return np.zeros(512)

# =============================================================================
# FAISS 加速检索
# =============================================================================

def build_faiss_index(features_np: np.ndarray, use_gpu: bool = True):
    """
    构建 FAISS 索引加速相似度搜索

    Args:
        features_np: 特征矩阵 (N, D)
        use_gpu: 是否使用 GPU FAISS

    Returns:
        faiss index 对象
    """
    try:
        import faiss

        # 归一化特征（用于余弦相似度）
        faiss.normalize_L2(features_np)

        # 构建索引
        dim = features_np.shape[1]
        index = faiss.IndexFlatIP(dim)  # 内积（等价于归一化后的余弦相似度）

        if use_gpu:
            try:
                res = faiss.StandardGpuResources()
                index = faiss.index_cpu_to_gpu(res, 0, index)
                print("⚡ 使用 GPU FAISS 加速")
            except Exception as e:
                print(f"⚠️  GPU FAISS 不可用，使用 CPU: {e}")

        index.add(features_np)
        return index
    except ImportError:
        print("⚠️  FAISS 未安装，使用暴力搜索（较慢）")
        return None
    except Exception as e:
        print(f"⚠️  FAISS 初始化失败，使用暴力搜索: {e}")
        return None


def search_with_faiss(index, query_vec: np.ndarray, k: int = 100):
    """用 FAISS 搜索最相似的向量"""
    import faiss

    query_np = query_vec.reshape(1, -1).astype('float32')
    faiss.normalize_L2(query_np)

    distances, indices = index.search(query_np, k)
    return indices[0], distances[0]


# =============================================================================
# 相似度和去重逻辑
# =============================================================================

def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """计算余弦相似度"""
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


def filter_by_metadata(item_a: Dict, item_b: Dict, threshold: float = 0.15) -> bool:
    """使用元数据快速过滤明显不相似的项目"""
    # 文件大小差异检查
    size_a = item_a.get("file_size", 0)
    size_b = item_b.get("file_size", 0)
    if size_a and size_b:
        size_ratio = min(size_a, size_b) / max(size_a, size_b)
        if size_ratio < (1 - threshold):
            return False

    # 时长差异检查
    dur_a = item_a.get("duration", 0)
    dur_b = item_b.get("duration", 0)
    if dur_a and dur_b:
        dur_ratio = min(dur_a, dur_b) / max(dur_a, dur_b)
        if dur_ratio < (1 - threshold):
            return False

    return True


def group_duplicates_bruteforce(
    features: Dict[str, np.ndarray],
    metadata: List[Dict],
    similarity_threshold: float = 0.95
) -> List[Dict]:
    """暴力搜索分组（用于无 FAISS 时）"""
    file_ids = list(features.keys())
    used = set()
    groups = []

    metadata_dict = {item["file_id"]: item for item in metadata}

    print(f"🔍 开始去重（暴力搜索），共 {len(file_ids)} 个媒体")

    for i, file_id in enumerate(tqdm(file_ids, desc="计算相似度")):
        if file_id in used:
            continue

        current_group = [file_id]
        used.add(file_id)
        current_meta = metadata_dict.get(file_id, {})

        for j in range(i + 1, len(file_ids)):
            other_id = file_ids[j]
            if other_id in used:
                continue

            other_meta = metadata_dict.get(other_id, {})

            if not filter_by_metadata(current_meta, other_meta):
                continue

            sim = cosine_similarity(features[file_id], features[other_id])

            if sim >= similarity_threshold:
                current_group.append(other_id)
                used.add(other_id)

        if len(current_group) > 1:
            groups.append({
                "primary_file_id": current_group[0],
                "file_ids": current_group,
                "size": len(current_group)
            })

    return groups


def group_duplicates_faiss(
    features: Dict[str, np.ndarray],
    metadata: List[Dict],
    similarity_threshold: float = 0.95,
    faiss_index=None
) -> List[Dict]:
    """FAISS 加速的分组"""
    if faiss_index is None:
        return group_duplicates_bruteforce(features, metadata, similarity_threshold)

    file_ids = list(features.keys())
    features_list = [features[ fid] for fid in file_ids]
    features_np = np.vstack(features_list).astype('float32')

    # 重新构建归一化的索引（如果之前没归一化）
    import faiss
    faiss.normalize_L2(features_np)

    index = faiss.IndexFlatIP(features_np.shape[1])
    try:
        res = faiss.StandardGpuResources()
        index = faiss.index_cpu_to_gpu(res, 0, index)
    except:
        pass

    index.add(features_np)

    used = set()
    groups = []
    metadata_dict = {item["file_id"]: item for item in metadata}

    print(f"🔍 开始去重（FAISS 加速），共 {len(file_ids)} 个媒体")

    for i, file_id in enumerate(tqdm(file_ids, desc="搜索相似项")):
        if file_id in used:
            continue

        # 用 FAISS 找前 100 个最相似的
        query_vec = features_np[i].reshape(1, -1)
        distances, indices = index.search(query_vec, min(100, len(file_ids)))

        current_group = [file_id]
        used.add(file_id)
        current_meta = metadata_dict.get(file_id, {})

        for j, dist in zip(indices[0], distances[0]):
            other_id = file_ids[j]

            if other_id in used or j == i:
                continue

            other_meta = metadata_dict.get(other_id, {})

            if not filter_by_metadata(current_meta, other_meta):
                continue

            if dist >= similarity_threshold:  # 归一化内积 = 余弦相似度
                current_group.append(other_id)
                used.add(other_id)

        if len(current_group) > 1:
            groups.append({
                "primary_file_id": current_group[0],
                "file_ids": current_group,
                "size": len(current_group)
            })

    return groups


# =============================================================================
# 主流程
# =============================================================================

def process_offline_data(
    input_zip: Path,
    output_dir: Path,
    model_name: str = "dinov2_base",
    similarity_threshold: float = 0.85,
    device: Optional[str] = None,
    keep_temp: bool = False
):
    """处理离线数据的主流程"""
    output_dir.mkdir(parents=True, exist_ok=True)

    # 解压数据
    temp_dir = output_dir / "temp"
    metadata_file = temp_dir / "metadata.json"
    
    # 检查是否已经解压过
    if temp_dir.exists() and metadata_file.exists():
        print(f"📁 检测到已存在的解压目录，跳过解压: {temp_dir}")
    else:
        print(f"📤 正在解压: {input_zip}")
        temp_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(input_zip, "r") as zipf:
            zipf.extractall(temp_dir)

    # 读取元数据
    metadata_file = temp_dir / "metadata.json"
    with open(metadata_file, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    print(f"📊 读取到 {len(metadata)} 个媒体元数据")

    # 选择设备
    if device is None:
        device = "cuda"
        try:
            import torch
            if not torch.cuda.is_available():
                print("⚠️  CUDA 不可用，使用 CPU")
                device = "cpu"
        except:
            device = "cpu"

    print(f"💻 运行设备: {device}")

    # 选择特征提取器
    if model_name.startswith("dinov2"):
        extractor = DINOv2FeatureExtractor(model_name=model_name, device=device)
    elif model_name.startswith("clip"):
        extractor = CLIPFeatureExtractor(model_name=model_name, device=device)
    elif model_name == "hash":
        extractor = HashFeatureExtractor()
    else:
        raise ValueError(f"未知模型: {model_name}")

    # 提取特征
    features: Dict[str, np.ndarray] = {}
    thumbs_dir = temp_dir / "thumbnails"

    for item in tqdm(metadata, desc="提取特征"):
        if not item.get("has_thumbnail"):
            continue

        file_id = item["file_id"]
        thumb_filename = item["thumbnail_filename"]
        thumb_path = thumbs_dir / thumb_filename

        if not thumb_path.exists():
            continue

        try:
            img = Image.open(thumb_path).convert("RGB")
            feature = extractor.extract(img)
            features[file_id] = feature
        except Exception as e:
            print(f"⚠️  处理 {file_id} 失败: {e}")

    # 去重分组
    print(f"✨ 提取了 {len(features)} 个媒体特征，开始分组")

    groups = group_duplicates_faiss(
        features,
        metadata,
        similarity_threshold
    )

    # 保存结果
    results = {
        "model": model_name,
        "similarity_threshold": similarity_threshold,
        "total_media": len(metadata),
        "media_with_features": len(features),
        "duplicate_groups": len(groups),
        "groups": groups
    }

    result_file = output_dir / "dedupe_results.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 去重完成！")
    print(f"📄 结果保存到: {result_file}")
    print(f"📊 统计:")
    print(f"   - 使用模型: {model_name}")
    print(f"   - 总媒体数: {len(metadata)}")
    print(f"   - 有特征的媒体: {len(features)}")
    print(f"   - 发现重复组: {len(groups)}")

    # 清理临时目录
    if keep_temp:
        print(f"📁 保留临时目录: {temp_dir}")
    else:
        shutil.rmtree(temp_dir)
        print(f"🗑️  已清理临时目录")

    # 打包结果
    result_zip = output_dir / "dedupe_results.zip"
    with zipfile.ZipFile(result_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(result_file, result_file.name)

    print(f"\n📦 结果已打包: {result_zip}")


def main():
    parser = argparse.ArgumentParser(
        description="离线高精度去重计算（Windows/GPU 支持）"
    )
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="输入的 ZIP 文件路径"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="offline_results",
        help="输出目录（默认: offline_results）"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="dinov2_base",
        choices=["dinov2_small", "dinov2_base", "clip_vit_b32", "hash"],
        help="使用的模型（默认: dinov2_base）"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="相似度阈值（DINOv2 默认 0.85，CLIP 用 0.95）"
    )
    parser.add_argument(
        "--device",
        type=str,
        choices=["cuda", "cpu"],
        help="强制指定设备（cuda/cpu，默认自动检测）"
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="保留临时解压目录，避免重复解压"
    )

    args = parser.parse_args()

    process_offline_data(
        input_zip=Path(args.input),
        output_dir=Path(args.output),
        model_name=args.model,
        similarity_threshold=args.threshold,
        device=args.device,
        keep_temp=args.keep_temp
    )


if __name__ == "__main__":
    main()
