# -*- coding: utf-8 -*-
"""LAMA 背景填充模块。

使用 litelama 包 + big-lama.safetensors 模型对图片中的指定区域进行智能
背景修复。所有待修复区域合并为一张遮罩，一次模型调用完成整张图片的处理。
"""

import logging
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 模型可用性检测（模块加载时执行一次）
# ---------------------------------------------------------------------------

LAMA_AVAILABLE = False
_LiteLama = None

try:
    from litelama import LiteLama as _LiteLamaClass

    _LiteLama = _LiteLamaClass

    # 检查模型文件是否存在
    _project_root = Path(__file__).resolve().parent.parent
    _model_path = _project_root / "models" / "lama" / "big-lama.safetensors"
    if _model_path.exists():
        LAMA_AVAILABLE = True
        logger.info("LAMA 背景填充可用: litelama + big-lama.safetensors")
    else:
        logger.warning("LAMA 模型文件不存在: %s", _model_path)

except ImportError:
    logger.warning("litelama 库不可用，LAMA 背景填充已禁用")
except Exception:
    logger.exception("LAMA 初始化失败")


def is_lama_available():
    """检查 LAMA 背景填充是否可用。"""
    return LAMA_AVAILABLE


# ---------------------------------------------------------------------------
# LiteLama 修复器单例
# ---------------------------------------------------------------------------


class _LiteLamaInpainter:
    """LiteLama 修复器封装类 — 单例模式，模型加载后保持在设备上。"""

    _instance = None
    _model = None
    _device = None
    _loaded = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.model_path = str(_model_path) if LAMA_AVAILABLE else None

    def load(self, device=None):
        """加载模型到指定设备。"""
        import torch

        if _LiteLama is None:
            raise RuntimeError("litelama 库不可用")

        if self._loaded and self._model is not None:
            if device and device != self._device:
                logger.info("litelama 切换设备: %s -> %s", self._device, device)
                self._model.to(device)
                self._device = device
            return

        if device is None:
            device = "cuda:0" if torch.cuda.is_available() else "cpu"

        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"LAMA 模型文件不存在: {self.model_path}")

        logger.info("加载 litelama 模型: %s (device=%s)", self.model_path, device)

        # 尝试获取 litelama 的默认配置文件
        config_path = None
        try:
            import litelama
            pkg_dir = os.path.dirname(litelama.__file__)
            default_cfg = os.path.join(pkg_dir, "config.yaml")
            if os.path.exists(default_cfg):
                config_path = default_cfg
        except Exception:
            pass

        self._model = _LiteLama(self.model_path, config_path)
        self._model.to(device)
        self._device = device
        self._loaded = True
        logger.info("litelama 模型加载完成")

    def unload(self):
        """卸载模型释放显存。"""
        import torch
        import gc

        if self._model is not None:
            self._model.to("cpu")
            del self._model
            self._model = None
            self._loaded = False
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
            logger.info("litelama 模型已卸载")

    def inpaint(self, image, mask):
        """
        执行图像修复。

        Args:
            image: PIL Image (RGB) — 原始图像
            mask: PIL Image (L) — 遮罩，白色(>=127)=需修复区域

        Returns:
            修复后的 PIL Image (RGB)，失败返回 None
        """
        import torch
        import cv2
        import gc

        if not self._loaded:
            self.load()

        try:
            init_image = image.convert("RGB")
            mask_image = mask.convert("L")

            # 原始尺寸
            original_size = init_image.size
            width, height = original_size

            # 二值化掩码
            mask_original = np.array(mask_image)
            mask_original = (mask_original >= 127).astype(np.float32)
            mask_original = mask_original[:, :, np.newaxis]

            img_original = np.array(init_image)

            # 等比缩放到 max 1024px（与 Saber 一致）
            max_dim = max(width, height)
            inpainting_size = 1024
            processed_width, processed_height = width, height

            if max_dim > inpainting_size:
                scale = inpainting_size / max_dim
                new_width = int(width * scale)
                new_height = int(height * scale)
                processed_width, processed_height = new_width, new_height

                logger.info("LAMA: 缩放图像 %sx%s -> %sx%s", width, height, new_width, new_height)

                img_np = np.array(init_image)
                mask_np = np.array(mask_image)
                img_np = cv2.resize(img_np, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
                mask_np = cv2.resize(mask_np, (new_width, new_height), interpolation=cv2.INTER_NEAREST)

                init_image = Image.fromarray(img_np)
                mask_image = Image.fromarray(mask_np)

            # litelama 需要 RGB 格式的 mask
            mask_rgb = mask_image.convert("RGB")

            # 执行修复
            result = self._model.predict(init_image, mask_rgb)

            if result is None:
                self._cleanup_memory()
                return None

            result_np = np.array(result.convert("RGB"))

            # 裁剪 litelama 内部的 8 倍数 padding
            if result_np.shape[:2] != (processed_height, processed_width):
                if result_np.shape[0] >= processed_height and result_np.shape[1] >= processed_width:
                    result_np = result_np[:processed_height, :processed_width]
                else:
                    result_np = cv2.resize(
                        result_np, (processed_width, processed_height),
                        interpolation=cv2.INTER_LINEAR,
                    )

            # 恢复到原始尺寸
            if (processed_width, processed_height) != (width, height):
                result_np = cv2.resize(result_np, (width, height), interpolation=cv2.INTER_LINEAR)

            # 混合：只在掩码区域应用修复结果
            if result_np.shape[:2] != img_original.shape[:2]:
                result_np = cv2.resize(
                    result_np,
                    (img_original.shape[1], img_original.shape[0]),
                    interpolation=cv2.INTER_LINEAR,
                )

            blended = (result_np * mask_original + img_original * (1 - mask_original)).astype(np.uint8)
            result = Image.fromarray(blended)

            self._cleanup_memory()
            return result

        except Exception:
            logger.exception("LAMA 修复过程中出错")
            self._cleanup_memory()
            return None

    def _cleanup_memory(self):
        """推理后清理 GPU 内存。"""
        import torch
        import gc

        for _ in range(3):
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        if torch.cuda.is_available():
            torch.cuda.synchronize()


# 全局单例
_inpainter = None


def _get_inpainter():
    """获取 litelama 修复器单例。"""
    global _inpainter
    if _inpainter is None:
        _inpainter = _LiteLamaInpainter()
    return _inpainter


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


def inpaint_image_regions(image, paragraphs, expand=8):
    """
    一次性修复图片中所有段落区域。

    将所有段落的 bbox 合并为一张全图遮罩，调用 LAMA 模型一次完成全部修复。

    Args:
        image: PIL Image (RGB) — 原始图像
        paragraphs: list[dict] — 段落列表，每项需包含 left/top/right/bottom
        expand: int — bbox 向外扩展像素数，确保完全覆盖文字（默认 8）

    Returns:
        PIL Image (RGB) — 修复后的图像，失败返回 None
    """
    if not LAMA_AVAILABLE:
        logger.error("LAMA 不可用，无法进行背景修复")
        return None

    if not paragraphs:
        logger.info("没有需要修复的区域")
        return image.copy()

    # 创建遮罩：黑色=保留，白色=需修复
    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)

    for para in paragraphs:
        left = max(0, para["left"] - expand)
        top = max(0, para["top"] - expand)
        right = min(image.width, para["right"] + expand)
        bottom = min(image.height, para["bottom"] + expand)
        draw.rectangle([(left, top), (right, bottom)], fill=255)

    logger.info(
        "LAMA 背景修复开始: 区域数=%s, 图片尺寸=%sx%s",
        len(paragraphs),
        image.width,
        image.height,
    )

    inpainter = _get_inpainter()
    result = inpainter.inpaint(image, mask)

    if result:
        logger.info("LAMA 背景修复完成")
    else:
        logger.error("LAMA 背景修复失败")

    return result
