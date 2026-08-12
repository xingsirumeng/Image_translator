"""翻译 API 门面模块。

本模块整合各翻译提供方的 API 接口，提供统一的配置管理、翻译调度、
以及图片翻译任务处理流程。

各 API 接口实现已拆分至独立子模块：
- core.baidu_ocr      — 百度 OCR 接口
- core.baidu_translate — 百度翻译接口
- core.deeplx          — DeepLX 翻译接口
- core.deepseek        — DeepSeek 翻译接口
"""

import concurrent.futures
import logging
import shutil
import sys
import time
from pathlib import Path

import requests
from PIL import Image
from dotenv import dotenv_values

from core import text_process
from core import inpainting
from core.baidu_ocr import (  # noqa: F401 — 重新导出，保持旧 import 兼容
    baidu_ocr_image_with_location,
    baidu_ocr_with_location,
    get_baidu_ocr_token,
)
from core.baidu_translate import (  # noqa: F401
    BAIDU_TRANSLATE_API_URL,
    BAIDU_TRANSLATE_MAX_WORKERS,
    BAIDU_TRANSLATE_TARGET_LANG_ALIASES,
    baidu_translate,
    build_baidu_translate_sign,
    map_baidu_translate_target_lang,
)
from core.deeplx import (  # noqa: F401
    DEFAULT_DEEPLX_ENDPOINT,
    DEEPLX_TARGET_LANG_ALIASES,
    build_deeplx_candidate_endpoints,
    detect_deeplx_endpoint,
    deeplx_translate,
    extract_deeplx_translation,
    map_deeplx_target_lang,
    normalize_deeplx_endpoint,
    probe_deeplx_endpoint,
    resolve_deeplx_endpoint,
)
from core.deepseek import deepseek_translate  # noqa: F401

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 共享常量
# ---------------------------------------------------------------------------

IMAGE_PROGRESS_STAGES = (
    (1, "OCR识别文字"),
    (2, "合并段落"),
    (3, "翻译段落"),
    (4, "LAMA背景填充"),
    (5, "覆盖文字"),
)
IMAGE_STAGE_COUNT = len(IMAGE_PROGRESS_STAGES)

OCR_PROVIDER_LABELS = {
    "baidu": "百度 OCR",
}

TRANSLATION_PROVIDER_LABELS = {
    "baidu": "百度翻译",
    "deepseek": "DeepSeek",
    "deeplx": "DeepLX",
}


# ---------------------------------------------------------------------------
# 配置管理
# ---------------------------------------------------------------------------


def get_default_config():
    """返回默认配置。"""
    return {
        "ocr_provider": "baidu",
        "translation_provider": "deepseek",
        "baidu_api_key": "",
        "baidu_secret_key": "",
        "baidu_translate_appid": "",
        "baidu_translate_appkey": "",
        "deepseek_api_key": "",
        "deeplx_endpoint": "",
        "translate_language": "中文",
        "enable_lama": False,
    }


def _to_bool(value):
    """将配置值规范化为 bool。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def normalize_config(config=None):
    """合并默认值并规范化配置。"""
    normalized = get_default_config()
    for key, value in (config or {}).items():
        if value is None:
            continue
        normalized[key] = value

    def clean_secret(value):
        value = str(value or "").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1].strip()
        return value

    normalized["ocr_provider"] = str(normalized.get("ocr_provider") or "baidu").strip().lower()
    normalized["translation_provider"] = (
        str(normalized.get("translation_provider") or "deepseek").strip().lower()
    )
    normalized["baidu_api_key"] = clean_secret(normalized.get("baidu_api_key"))
    normalized["baidu_secret_key"] = clean_secret(normalized.get("baidu_secret_key"))
    normalized["baidu_translate_appid"] = clean_secret(normalized.get("baidu_translate_appid"))
    normalized["baidu_translate_appkey"] = clean_secret(normalized.get("baidu_translate_appkey"))
    normalized["deepseek_api_key"] = clean_secret(normalized.get("deepseek_api_key"))
    normalized["translate_language"] = str(
        normalized.get("translate_language") or "中文"
    ).strip() or "中文"
    normalized["enable_lama"] = _to_bool(normalized.get("enable_lama", False))
    normalized["deeplx_endpoint"] = normalize_deeplx_endpoint(
        normalized.get("deeplx_endpoint", ""),
        add_default_path=False,
    )
    return normalized


def get_main_script_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    else:
        import __main__
        return Path(__main__.__file__).resolve().parent


def get_runtime_dir():
    return get_main_script_dir()


def get_config_path():
    return get_runtime_dir() / "api-data.env"


def get_result_dir():
    return get_runtime_dir() / "output"


def load_config():
    """加载或创建配置文件。"""
    env_file = get_config_path()

    if env_file.exists():
        logger.info("加载配置文件: %s", env_file)
        return normalize_config(dotenv_values(env_file))

    logger.warning("未找到配置文件，将创建: %s", env_file)
    print(f"未找到环境文件，将在本地创建: {env_file}")
    print("\n请提供以下配置（输入后将保存到本地文件）:")

    config = get_default_config()
    config["ocr_provider"] = input("OCR 提供方（默认 baidu）: ").strip().lower() or "baidu"
    config["translation_provider"] = (
        input("翻译提供方（deepseek/baidu/deeplx，默认 deepseek）: ").strip().lower() or "deepseek"
    )
    config["baidu_api_key"] = input("百度 OCR API Key: ").strip()
    config["baidu_secret_key"] = input("百度 OCR Secret Key: ").strip()
    if config["translation_provider"] == "deepseek":
        config["deepseek_api_key"] = input("DeepSeek API Key: ").strip()
    elif config["translation_provider"] == "baidu":
        config["baidu_translate_appid"] = input("百度翻译 APP ID: ").strip()
        config["baidu_translate_appkey"] = input("百度翻译密钥: ").strip()
    else:
        config["deeplx_endpoint"] = input(
            "DeepLX 地址（默认自动检测 localhost:1188）: "
        ).strip()
    config["translate_language"] = input("目标语言（默认 中文）: ").strip() or "中文"
    config = normalize_config(config)

    env_file.parent.mkdir(parents=True, exist_ok=True)
    with open(env_file, "w", encoding="utf-8") as file:
        file.write("# API 密钥配置 请勿分享此文件!\n")
        for key, value in config.items():
            file.write(f"{key}={value}\n")

    return config


def validate_config(config):
    """校验运行所需配置。"""
    normalized = normalize_config(config)
    missing = []

    if normalized["ocr_provider"] == "baidu":
        for key in ("baidu_api_key", "baidu_secret_key"):
            if not normalized.get(key):
                missing.append(key)
    else:
        raise ValueError(f"不支持的 OCR 提供方: {normalized['ocr_provider']}")

    if normalized["translation_provider"] == "deepseek":
        if not normalized.get("deepseek_api_key"):
            missing.append("deepseek_api_key")
    elif normalized["translation_provider"] == "baidu":
        for key in ("baidu_translate_appid", "baidu_translate_appkey"):
            if not normalized.get(key):
                missing.append(key)
    elif normalized["translation_provider"] == "deeplx":
        normalized["deeplx_endpoint"] = resolve_deeplx_endpoint(
            normalized,
            auto_detect=not bool(normalized.get("deeplx_endpoint")),
        )
    else:
        raise ValueError(f"不支持的翻译提供方: {normalized['translation_provider']}")

    if missing:
        logger.error("配置校验失败，缺少字段: %s", ", ".join(missing))
        raise ValueError(f"缺少必要配置: {', '.join(missing)}")

    if isinstance(config, dict):
        config.clear()
        config.update(normalized)
    return normalized


# ---------------------------------------------------------------------------
# 翻译调度
# ---------------------------------------------------------------------------


def translate_text(text, config, target_lang):
    """按配置选择翻译服务。"""
    provider = config.get("translation_provider", "deepseek")
    if provider == "deepseek":
        return deepseek_translate(text, config["deepseek_api_key"], target_lang)
    if provider == "baidu":
        return baidu_translate(
            text,
            config["baidu_translate_appid"],
            config["baidu_translate_appkey"],
            target_lang,
        )
    if provider == "deeplx":
        endpoint = config.get("deeplx_endpoint") or resolve_deeplx_endpoint(config)
        config["deeplx_endpoint"] = endpoint
        return deeplx_translate(text, endpoint, target_lang)
    raise RuntimeError(f"不支持的翻译提供方: {provider}")


def parallel_translate(paragraphs, config, target_lang, max_workers=3):
    """并行翻译多个段落，并保持原始顺序。"""

    if not paragraphs:
        logger.info("没有可翻译段落")
        return []

    provider = config.get("translation_provider")
    if provider == "baidu":
        max_workers = min(max_workers, BAIDU_TRANSLATE_MAX_WORKERS)

    max_workers = max(1, min(max_workers, len(paragraphs)))
    logger.info(
        "开始并行翻译，provider=%s, 段落数=%s, worker数=%s",
        provider,
        len(paragraphs),
        max_workers,
    )

    def translate_single(paragraph):
        try:
            return translate_text(paragraph["words"], config, target_lang)
        except Exception as exc:
            raise RuntimeError(f"段落翻译失败: {exc}") from exc

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        translations = list(executor.map(translate_single, paragraphs))
        logger.info("并行翻译完成，段落数=%s", len(translations))
        return translations


# ---------------------------------------------------------------------------
# 图片处理
# ---------------------------------------------------------------------------


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


def log_stage_elapsed(task_name, stage_name, started_at):
    """记录单个处理阶段耗时。"""
    elapsed = round(time.time() - started_at, 2)
    logger.info("%s阶段完成: %s, elapsed=%ss", task_name, stage_name, elapsed)
    return elapsed


def log_stage_summary(task_name, stage_timings):
    """汇总记录各阶段耗时。"""
    logger.info(
        "%s阶段耗时汇总: OCR=%ss, 合并=%ss, 翻译=%ss, 填充=%ss, 覆盖=%ss",
        task_name,
        stage_timings.get("ocr", 0.0),
        stage_timings.get("merge", 0.0),
        stage_timings.get("translate", 0.0),
        stage_timings.get("inpaint", 0.0),
        stage_timings.get("render", 0.0),
    )


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
        config = validate_config(dict(config or load_config()))
        translations = []
        stage_timings = {"ocr": 0.0, "merge": 0.0, "translate": 0.0, "render": 0.0}
        task_name = f"图片任务[{Path(image_path).name}]"

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
        ocr_started_at = time.time()
        ocr_results = baidu_ocr_with_location(image_path, baidu_token)
        stage_timings["ocr"] = log_stage_elapsed(task_name, "OCR识别文字", ocr_started_at)
        report_image_progress(progress_callback, 1, "OCR识别文字")

        merge_started_at = time.time()
        original_paragraphs = text_process.merge_text_lines(ocr_results)
        stage_timings["merge"] = log_stage_elapsed(task_name, "合并段落", merge_started_at)
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
            translate_started_at = time.time()
            translations = parallel_translate(
                original_paragraphs,
                config,
                target_lang,
                max_workers=min(5, len(original_paragraphs)),
            )
            stage_timings["translate"] = log_stage_elapsed(task_name, "翻译段落", translate_started_at)
            report_image_progress(progress_callback, 3, "翻译段落")

            # LAMA 背景填充（可选）
            skip_background_fill = False
            original_image = image.copy()  # 保存原图，供后续颜色检测使用
            if config.get("enable_lama") and inpainting.is_lama_available():
                inpaint_started_at = time.time()
                inpainted = inpainting.inpaint_image_regions(image, original_paragraphs)
                if inpainted is not None:
                    image = inpainted
                    skip_background_fill = True
                    stage_timings["inpaint"] = log_stage_elapsed(task_name, "LAMA背景填充", inpaint_started_at)
                    report_image_progress(progress_callback, 4, "LAMA背景填充")
                else:
                    logger.warning("LAMA 背景填充失败，降级为纯色填充")
                    report_image_progress(progress_callback, 4, "LAMA背景填充（跳过）")
            elif config.get("enable_lama"):
                logger.warning("LAMA 不可用，使用纯色背景填充")
                report_image_progress(progress_callback, 4, "LAMA背景填充（不可用）")
            else:
                report_image_progress(progress_callback, 4, "LAMA背景填充（未启用）")

            render_started_at = time.time()
            success = text_process.replace_text_in_image(
                image,
                str(output_path),
                original_paragraphs,
                translations,
                skip_background_fill=skip_background_fill,
                original_image=original_image if skip_background_fill else None,
            )
            if not success:
                raise RuntimeError("图片文字替换失败")
            stage_timings["render"] = log_stage_elapsed(task_name, "覆盖文字", render_started_at)
            report_image_progress(progress_callback, 5, "覆盖文字")

            result["message"] = f"识别到 {len(original_paragraphs)} 个文本段落并完成翻译"
        else:
            stage_timings["translate"] = 0.0
            report_image_progress(progress_callback, 3, "翻译段落（无可翻译文本）")
            report_image_progress(progress_callback, 4, "LAMA背景填充（无文本）")
            render_started_at = time.time()
            shutil.copy2(image_path, output_path)
            stage_timings["render"] = log_stage_elapsed(task_name, "覆盖文字（已复制原图）", render_started_at)
            report_image_progress(progress_callback, 5, "覆盖文字（已复制原图）")
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
        log_stage_summary(task_name, stage_timings)
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


def build_capture_output_paths(output_dir=None):
    """为截图翻译生成输出路径。"""
    result_dir = Path(output_dir) if output_dir else get_result_dir()
    result_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int((time.time() % 1) * 1000):03d}"
    image_output_path = result_dir / f"screenshot_{stamp}_translated.png"
    text_output_path = result_dir / f"screenshot_{stamp}_translation.txt"
    source_output_path = result_dir / f"screenshot_{stamp}_source.png"
    return image_output_path, text_output_path, source_output_path


def process_pil_image_task(
    image,
    config,
    output_dir=None,
    output_base_name=None,
    progress_callback=None,
    image_name="截图",
):
    """处理内存图片，主要用于截图翻译。"""
    started_at = time.time()
    result = {
        "image_path": image_name,
        "success": False,
        "output_path": "",
        "text_output_path": "",
        "source_output_path": "",
        "paragraph_count": 0,
        "ocr_region_count": 0,
        "elapsed_seconds": 0.0,
        "message": "",
        "error": "",
    }

    try:
        logger.info("开始处理内存图片任务: %s", image_name)
        config = validate_config(dict(config or load_config()))
        translations = []
        stage_timings = {"ocr": 0.0, "merge": 0.0, "translate": 0.0, "render": 0.0}
        task_name = f"截图任务[{image_name}]"
        target_lang = config.get("translate_language") or "中文"

        if output_base_name:
            source_name = f"{output_base_name}.png"
            output_path, text_output_path = build_output_paths(
                source_name,
                output_dir=output_dir,
                output_base_name=output_base_name,
            )
            source_output_path = Path(output_dir or get_result_dir()) / source_name
        else:
            output_path, text_output_path, source_output_path = build_capture_output_paths(output_dir)

        image = image.convert("RGB")
        image.save(source_output_path)
        logger.debug("截图输出路径已生成: image=%s, text=%s", output_path, text_output_path)

        baidu_token = get_baidu_ocr_token(
            config["baidu_api_key"],
            config["baidu_secret_key"],
        )
        ocr_started_at = time.time()
        ocr_results = baidu_ocr_image_with_location(image, baidu_token, image_name=image_name)
        stage_timings["ocr"] = log_stage_elapsed(task_name, "OCR识别文字", ocr_started_at)
        report_image_progress(progress_callback, 1, "OCR识别文字")

        merge_started_at = time.time()
        original_paragraphs = text_process.merge_text_lines(ocr_results)
        stage_timings["merge"] = log_stage_elapsed(task_name, "合并段落", merge_started_at)
        report_image_progress(progress_callback, 2, "合并段落")

        result["ocr_region_count"] = len(ocr_results)
        result["paragraph_count"] = len(original_paragraphs)
        logger.info(
            "内存图片预处理完成: %s, ocr_regions=%s, paragraphs=%s",
            image_name,
            len(ocr_results),
            len(original_paragraphs),
        )

        if original_paragraphs:
            translate_started_at = time.time()
            translations = parallel_translate(
                original_paragraphs,
                config,
                target_lang,
                max_workers=min(5, len(original_paragraphs)),
            )
            stage_timings["translate"] = log_stage_elapsed(task_name, "翻译段落", translate_started_at)
            report_image_progress(progress_callback, 3, "翻译段落")

            # LAMA 背景填充（可选）
            skip_background_fill = False
            original_image = image.copy()  # 保存原图，供后续颜色检测使用
            if config.get("enable_lama") and inpainting.is_lama_available():
                inpaint_started_at = time.time()
                inpainted = inpainting.inpaint_image_regions(image, original_paragraphs)
                if inpainted is not None:
                    image = inpainted
                    skip_background_fill = True
                    stage_timings["inpaint"] = log_stage_elapsed(task_name, "LAMA背景填充", inpaint_started_at)
                    report_image_progress(progress_callback, 4, "LAMA背景填充")
                else:
                    logger.warning("LAMA 背景填充失败，降级为纯色填充")
                    report_image_progress(progress_callback, 4, "LAMA背景填充（跳过）")
            elif config.get("enable_lama"):
                logger.warning("LAMA 不可用，使用纯色背景填充")
                report_image_progress(progress_callback, 4, "LAMA背景填充（不可用）")
            else:
                report_image_progress(progress_callback, 4, "LAMA背景填充（未启用）")

            render_started_at = time.time()
            success = text_process.replace_text_in_image(
                image,
                str(output_path),
                original_paragraphs,
                translations,
                skip_background_fill=skip_background_fill,
                original_image=original_image if skip_background_fill else None,
            )
            if not success:
                raise RuntimeError("图片文字替换失败")
            stage_timings["render"] = log_stage_elapsed(task_name, "覆盖文字", render_started_at)
            report_image_progress(progress_callback, 5, "覆盖文字")
            result["message"] = f"识别到 {len(original_paragraphs)} 个文本段落并完成翻译"
        else:
            stage_timings["translate"] = 0.0
            report_image_progress(progress_callback, 3, "翻译段落（无可翻译文本）")
            report_image_progress(progress_callback, 4, "LAMA背景填充（无文本）")
            render_started_at = time.time()
            image.save(output_path)
            stage_timings["render"] = log_stage_elapsed(task_name, "覆盖文字（已复制原图）", render_started_at)
            report_image_progress(progress_callback, 5, "覆盖文字（已复制原图）")
            result["message"] = "未识别到可翻译文本，已显示原截图"
            logger.info("未识别到可翻译文本，已复制原截图: %s", image_name)

        with open(text_output_path, "w", encoding="utf-8") as file:
            file.write("原始文本:\n")
            file.write("\n".join([paragraph["words"] for paragraph in original_paragraphs]))
            file.write("\n\n翻译结果:\n")
            file.write("\n".join(translations))

        result.update(
            success=True,
            output_path=str(output_path),
            text_output_path=str(text_output_path),
            source_output_path=str(source_output_path),
        )
        log_stage_summary(task_name, stage_timings)
        logger.info(
            "内存图片任务处理成功: %s, elapsed=%ss, output=%s",
            image_name,
            round(time.time() - started_at, 2),
            output_path,
        )

    except Exception as exc:
        result["error"] = str(exc)
        logger.exception("内存图片任务处理失败: %s", image_name)

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
