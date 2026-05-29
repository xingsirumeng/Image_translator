import base64
import concurrent.futures
import logging
import shutil
import sys
import os
import time
from pathlib import Path

import requests
from PIL import Image
from dotenv import dotenv_values

from core import text_process

logger = logging.getLogger(__name__)

IMAGE_PROGRESS_STAGES = (
    (1, "OCR识别文字"),
    (2, "合并段落"),
    (3, "翻译段落"),
    (4, "覆盖文字"),
)
IMAGE_STAGE_COUNT = len(IMAGE_PROGRESS_STAGES)


def get_runtime_dir():
    """返回运行目录。源码模式下为 src，打包后为可执行文件所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_config_path():
    """返回配置文件路径。"""
    if getattr(sys, "frozen", False):
        return get_runtime_dir() / "api-data.env"
    return get_runtime_dir().parent / "api-data.env"


def get_result_dir():
    """返回结果输出目录。"""
    return get_runtime_dir() / "output"


def load_config():
    """加载或创建配置文件。"""
    env_file = get_config_path()

    if env_file.exists():
        logger.info("加载配置文件: %s", env_file)
        return dotenv_values(env_file)

    logger.warning("未找到配置文件，将创建: %s", env_file)
    print(f"未找到环境文件，将在本地创建: {env_file}")
    print("\n请提供以下 API 密钥（输入后将保存到本地文件）:")

    baidu_api_key = input("百度 OCR API Key: ").strip()
    baidu_secret_key = input("百度 OCR Secret Key: ").strip()
    deepseek_api_key = input("DeepSeek API Key: ").strip()
    translate_language = input("目标语言（默认 中文）: ").strip() or "中文"

    env_file.parent.mkdir(parents=True, exist_ok=True)
    with open(env_file, "w", encoding="utf-8") as file:
        file.write("# API 密钥配置 请勿分享此文件!\n")
        file.write(f"baidu_api_key={baidu_api_key}\n")
        file.write(f"baidu_secret_key={baidu_secret_key}\n")
        file.write(f"deepseek_api_key={deepseek_api_key}\n")
        file.write(f"translate_language={translate_language}\n")

    return {
        "baidu_api_key": baidu_api_key,
        "baidu_secret_key": baidu_secret_key,
        "deepseek_api_key": deepseek_api_key,
        "translate_language": translate_language,
    }


def validate_config(config):
    """校验运行所需配置。"""
    required_keys = ["baidu_api_key", "baidu_secret_key", "deepseek_api_key"]
    missing = [key for key in required_keys if not config.get(key)]
    if missing:
        logger.error("配置校验失败，缺少字段: %s", ", ".join(missing))
        raise ValueError(f"缺少必要配置: {', '.join(missing)}")


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
    """获取带位置信息的 OCR 结果。"""
    try:
        logger.info("开始 OCR 识别: %s", Path(image_path).name)
        with open(image_path, "rb") as file:
            img_base64 = base64.b64encode(file.read()).decode()

        url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/accurate?access_token={access_token}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "image": img_base64,
            "recognize_granularity": "big",
            "language_type": "auto_detect"
        }

        response = requests.post(url, headers=headers, data=data, timeout=60)
        result = response.json()

        if "words_result" not in result:
            error_msg = result.get("error_msg", "未知错误")
            error_code = result.get("error_code", "未知")
            raise RuntimeError(f"OCR 识别失败: {error_msg} (错误码: {error_code})")

        logger.info("OCR 识别完成: %s, region_count=%s", Path(image_path).name, len(result["words_result"]))
        return result["words_result"]

    except FileNotFoundError as exc:
        raise RuntimeError(f"图片文件不存在: {image_path}") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"OCR 网络请求失败: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"OCR 处理错误: {exc}") from exc


def deepseek_translate(text, api_key, target_lang="中文"):
    """使用 DeepSeek API 进行文本翻译。"""
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    prompt = (
        f"请将以下非{target_lang}内容准确翻译成{target_lang}\n\n"
        f"文本内容：\n\n{text}\n\n"
        "翻译要求：\n"
        "1. 仅返回翻译结果\n"
    )

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 4000,
    }

    try:
        logger.debug("开始翻译请求，target_lang=%s, text_length=%s", target_lang, len(text))
        response = requests.post(url, headers=headers, json=payload, timeout=60)
    except requests.exceptions.Timeout as exc:
        raise RuntimeError("翻译请求超时，请重试") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"翻译请求失败: {exc}") from exc

    try:
        result = response.json()
    except ValueError as exc:
        response.raise_for_status()
        raise RuntimeError("翻译服务返回了无法解析的响应") from exc

    if response.status_code >= 400:
        error = result.get("error", {})
        error_msg = error.get("message", "未知错误")
        error_code = error.get("code", "未知")
        raise RuntimeError(f"翻译失败 [{error_code}]: {error_msg}")

    if "choices" not in result:
        error = result.get("error", {})
        error_msg = error.get("message", "未知错误")
        error_code = error.get("code", "未知")
        raise RuntimeError(f"翻译失败 [{error_code}]: {error_msg}")

    logger.debug("翻译请求完成，target_lang=%s, translated_length=%s", target_lang, len(result["choices"][0]["message"]["content"]))
    return result["choices"][0]["message"]["content"].strip()


def parallel_translate(paragraphs, api_key, target_lang, max_workers=3):
    """并行翻译多个段落，并保持原始顺序。"""

    if not paragraphs:
        logger.info("没有可翻译段落")
        return []

    max_workers = max(1, min(max_workers, len(paragraphs)))
    logger.info("开始并行翻译，段落数=%s, worker数=%s", len(paragraphs), max_workers)

    def translate_single(paragraph):
        try:
            return deepseek_translate(paragraph["words"], api_key, target_lang)
        except Exception as exc:
            raise RuntimeError(f"段落翻译失败: {exc}") from exc

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        translations = list(executor.map(translate_single, paragraphs))
        logger.info("并行翻译完成，段落数=%s", len(translations))
        return translations


def build_output_paths(image_path, output_dir=None, output_base_name=None):
    """根据输入图片生成输出文件路径。"""
    image_path = Path(image_path)
    result_dir = Path(output_dir) if output_dir else get_result_dir()
    result_dir.mkdir(parents=True, exist_ok=True)

    base_name = output_base_name or image_path.stem
    image_output_path = result_dir / f"{base_name}_translated{image_path.suffix}"
    text_output_path = result_dir / f"{base_name}_translation.txt"
    return image_output_path, text_output_path


def report_image_progress(progress_callback, stage_index, stage_name):
    """通知外层当前图片的阶段进度。"""
    if not progress_callback:
        return

    try:
        progress_callback(stage_index, stage_name)
    except Exception:
        logger.exception("图片阶段进度回调失败: stage=%s %s", stage_index, stage_name)


def process_image_task(image_path, config, output_dir=None, output_base_name=None, progress_callback=None):
    """处理单张图片。适合在子进程中直接调用。"""
    started_at = time.time()
    image_path = str(Path(image_path))

    result = {
        "image_path": image_path,
        "success": False,
        "output_path": "",
        "text_output_path": "",
        "paragraph_count": 0,
        "ocr_region_count": 0,
        "elapsed_seconds": 0.0,
        "message": "",
        "error": "",
    }

    try:
        logger.info("开始处理图片任务: %s", image_path)
        config = dict(config or load_config())
        validate_config(config)
        translations = []

        target_lang = config.get("translate_language") or "中文"
        output_path, text_output_path = build_output_paths(
            image_path,
            output_dir=output_dir,
            output_base_name=output_base_name,
        )
        logger.debug("输出路径已生成: image=%s, text=%s", output_path, text_output_path)

        baidu_token = get_baidu_ocr_token(
            config["baidu_api_key"],
            config["baidu_secret_key"],
        )
        ocr_results = baidu_ocr_with_location(image_path, baidu_token)
        report_image_progress(progress_callback, 1, "OCR识别文字")

        original_paragraphs = text_process.merge_text_lines(ocr_results)
        report_image_progress(progress_callback, 2, "合并段落")

        image = Image.open(image_path).convert("RGB")

        result["ocr_region_count"] = len(ocr_results)
        result["paragraph_count"] = len(original_paragraphs)
        logger.info(
            "图片预处理完成: %s, ocr_regions=%s, paragraphs=%s",
            Path(image_path).name,
            len(ocr_results),
            len(original_paragraphs),
        )

        if original_paragraphs:
            translations = parallel_translate(
                original_paragraphs,
                config["deepseek_api_key"],
                target_lang,
                max_workers=min(5, len(original_paragraphs)),
            )
            report_image_progress(progress_callback, 3, "翻译段落")

            success = text_process.replace_text_in_image(
                image,
                str(output_path),
                original_paragraphs,
                translations,
            )
            if not success:
                raise RuntimeError("图片文字替换失败")
            report_image_progress(progress_callback, 4, "覆盖文字")

            result["message"] = f"识别到 {len(original_paragraphs)} 个文本段落并完成翻译"
        else:
            report_image_progress(progress_callback, 3, "翻译段落（无可翻译文本）")
            shutil.copy2(image_path, output_path)
            report_image_progress(progress_callback, 4, "覆盖文字（已复制原图）")
            result["message"] = "未识别到可翻译文本，已复制原图"
            logger.info("未识别到可翻译文本，已复制原图: %s", image_path)

        with open(text_output_path, "w", encoding="utf-8") as file:
            file.write("原始文本:\n")
            file.write("\n".join([paragraph["words"] for paragraph in original_paragraphs]))
            file.write("\n\n翻译结果:\n")
            file.write("\n".join(translations))

        result.update(
            success=True,
            output_path=str(output_path),
            text_output_path=str(text_output_path),
        )
        logger.info(
            "图片任务处理成功: %s, elapsed=%ss, output=%s",
            image_path,
            round(time.time() - started_at, 2),
            output_path,
        )

    except Exception as exc:
        result["error"] = str(exc)
        logger.exception("图片任务处理失败: %s", image_path)

    result["elapsed_seconds"] = round(time.time() - started_at, 2)
    return result


def process_image(image_path, config=None, output_dir=None, output_base_name=None):
    """兼容旧接口：处理单张图片并返回输出图片路径。"""
    result = process_image_task(
        image_path,
        config or load_config(),
        output_dir=output_dir,
        output_base_name=output_base_name,
    )
    if not result["success"]:
        raise RuntimeError(result["error"])
    return result["output_path"]
