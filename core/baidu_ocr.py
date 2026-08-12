"""百度 OCR API 接口模块。

提供百度 OCR 访问令牌获取、基于文件路径的 OCR 识别、
以及基于内存 PIL 图片的 OCR 识别（含位置信息）。
"""

import base64
import logging
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

logger = logging.getLogger(__name__)


def get_baidu_ocr_token(api_key, secret_key):
    """获取百度 OCR 的访问令牌。"""
    url = (
        "https://aip.baidubce.com/oauth/2.0/token"
        f"?grant_type=client_credentials&client_id={api_key}&client_secret={secret_key}"
    )

    try:
        logger.debug("开始请求 OCR 令牌")
        response = requests.post(url, timeout=30)
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"获取 OCR 令牌失败: {exc}") from exc

    access_token = result.get("access_token")
    if not access_token:
        error_msg = result.get("error_description") or result.get("error_msg") or "未知错误"
        raise RuntimeError(f"获取 OCR 令牌失败: {error_msg}")

    logger.debug("OCR 令牌请求成功")
    return access_token


def baidu_ocr_with_location(image_path, access_token):
    """获取带位置信息的 OCR 结果（从文件路径读取图片）。"""
    try:
        logger.info("开始 OCR 识别: %s", Path(image_path).name)
        with open(image_path, "rb") as file:
            img_base64 = base64.b64encode(file.read()).decode()

        url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/accurate?access_token={access_token}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "image": img_base64,
            "recognize_granularity": "big",
            "language_type": "auto_detect",
        }

        response = requests.post(url, headers=headers, data=data, timeout=60)
        result = response.json()

        if "words_result" not in result:
            error_msg = result.get("error_msg", "未知错误")
            error_code = result.get("error_code", "未知")
            raise RuntimeError(f"OCR 识别失败: {error_msg} (错误码: {error_code})")

        logger.info(
            "OCR 识别完成: %s, region_count=%s",
            Path(image_path).name,
            len(result["words_result"]),
        )
        return result["words_result"]

    except FileNotFoundError as exc:
        raise RuntimeError(f"图片文件不存在: {image_path}") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"OCR 网络请求失败: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"OCR 处理错误: {exc}") from exc


def baidu_ocr_image_with_location(image, access_token, image_name="截图"):
    """对内存中的 PIL 图片执行带位置信息 OCR。"""
    try:
        logger.info("开始 OCR 识别: %s", image_name)
        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        img_base64 = base64.b64encode(buffer.getvalue()).decode()

        url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/accurate?access_token={access_token}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "image": img_base64,
            "recognize_granularity": "big",
            "language_type": "auto_detect",
        }

        response = requests.post(url, headers=headers, data=data, timeout=60)
        result = response.json()

        if "words_result" not in result:
            error_msg = result.get("error_msg", "未知错误")
            error_code = result.get("error_code", "未知")
            raise RuntimeError(f"OCR 识别失败: {error_msg} (错误码: {error_code})")

        logger.info("OCR 识别完成: %s, region_count=%s", image_name, len(result["words_result"]))
        return result["words_result"]
    except requests.RequestException as exc:
        raise RuntimeError(f"OCR 网络请求失败: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"OCR 处理错误: {exc}") from exc
