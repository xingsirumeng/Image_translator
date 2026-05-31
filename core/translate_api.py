import base64
import concurrent.futures
import hashlib
import logging
import shutil
import sys
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse, urlunparse

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
DEFAULT_DEEPLX_ENDPOINT = "http://localhost:1188/translate"
OCR_PROVIDER_LABELS = {
    "baidu": "百度 OCR",
}
TRANSLATION_PROVIDER_LABELS = {
    "baidu": "百度翻译",
    "deepseek": "DeepSeek",
    "deeplx": "DeepLX",
}
BAIDU_TRANSLATE_API_URL = "https://fanyi-api.baidu.com/api/trans/vip/translate"
BAIDU_TRANSLATE_MAX_WORKERS = 10
BAIDU_TRANSLATE_TARGET_LANG_ALIASES = {
    "zh": "zh",
    "中文": "zh",
    "简体中文": "zh",
    "繁体中文": "cht",
    "cht": "cht",
    "en": "en",
    "英文": "en",
    "英语": "en",
    "english": "en",
    "ja": "jp",
    "jp": "jp",
    "日文": "jp",
    "日语": "jp",
    "japanese": "jp",
    "ko": "kor",
    "kor": "kor",
    "韩文": "kor",
    "韩语": "kor",
    "korean": "kor",
    "fr": "fra",
    "fra": "fra",
    "法文": "fra",
    "法语": "fra",
    "french": "fra",
    "es": "spa",
    "spa": "spa",
    "西班牙文": "spa",
    "西班牙语": "spa",
    "spanish": "spa",
    "th": "th",
    "泰语": "th",
    "ar": "ara",
    "ara": "ara",
    "阿拉伯语": "ara",
    "ru": "ru",
    "俄文": "ru",
    "俄语": "ru",
    "russian": "ru",
    "pt": "pt",
    "葡萄牙文": "pt",
    "葡萄牙语": "pt",
    "portuguese": "pt",
    "de": "de",
    "德文": "de",
    "德语": "de",
    "german": "de",
    "it": "it",
    "意大利文": "it",
    "意大利语": "it",
    "italian": "it",
    "el": "el",
    "希腊语": "el",
    "nl": "nl",
    "荷兰文": "nl",
    "荷兰语": "nl",
    "dutch": "nl",
    "pl": "pl",
    "波兰文": "pl",
    "波兰语": "pl",
    "bg": "bul",
    "bul": "bul",
    "保加利亚语": "bul",
    "et": "est",
    "est": "est",
    "爱沙尼亚语": "est",
    "da": "dan",
    "dan": "dan",
    "丹麦语": "dan",
    "fi": "fin",
    "fin": "fin",
    "芬兰语": "fin",
    "cs": "cs",
    "捷克语": "cs",
    "ro": "rom",
    "rom": "rom",
    "罗马尼亚语": "rom",
    "sl": "slo",
    "slo": "slo",
    "斯洛文尼亚语": "slo",
    "sv": "swe",
    "swe": "swe",
    "瑞典语": "swe",
    "hu": "hu",
    "匈牙利语": "hu",
    "vi": "vie",
    "vie": "vie",
    "越南语": "vie",
    "yue": "yue",
    "粤语": "yue",
    "wyw": "wyw",
    "文言文": "wyw",
}
DEEPLX_TARGET_LANG_ALIASES = {
    "zh": "ZH",
    "中文": "ZH",
    "简体中文": "ZH",
    "繁体中文": "ZH",
    "en": "EN",
    "英文": "EN",
    "英语": "EN",
    "english": "EN",
    "ja": "JA",
    "日文": "JA",
    "日语": "JA",
    "japanese": "JA",
    "ko": "KO",
    "韩文": "KO",
    "韩语": "KO",
    "korean": "KO",
    "de": "DE",
    "德文": "DE",
    "德语": "DE",
    "german": "DE",
    "fr": "FR",
    "法文": "FR",
    "法语": "FR",
    "french": "FR",
    "es": "ES",
    "西班牙文": "ES",
    "西班牙语": "ES",
    "spanish": "ES",
    "ru": "RU",
    "俄文": "RU",
    "俄语": "RU",
    "russian": "RU",
    "pt": "PT",
    "葡萄牙文": "PT",
    "葡萄牙语": "PT",
    "portuguese": "PT",
    "it": "IT",
    "意大利文": "IT",
    "意大利语": "IT",
    "italian": "IT",
    "nl": "NL",
    "荷兰文": "NL",
    "荷兰语": "NL",
    "dutch": "NL",
    "pl": "PL",
    "波兰文": "PL",
    "波兰语": "PL",
    "bg": "BG",
    "保加利亚语": "BG",
    "cs": "CS",
    "捷克语": "CS",
    "da": "DA",
    "丹麦语": "DA",
    "el": "EL",
    "希腊语": "EL",
    "fi": "FI",
    "芬兰语": "FI",
    "hu": "HU",
    "匈牙利语": "HU",
    "id": "ID",
    "印尼语": "ID",
    "indonesian": "ID",
    "lt": "LT",
    "立陶宛语": "LT",
    "lv": "LV",
    "拉脱维亚语": "LV",
    "ro": "RO",
    "罗马尼亚语": "RO",
    "sk": "SK",
    "斯洛伐克语": "SK",
    "sl": "SL",
    "斯洛文尼亚语": "SL",
    "sv": "SV",
    "瑞典语": "SV",
    "tr": "TR",
    "土耳其语": "TR",
    "uk": "UK",
    "乌克兰语": "UK",
    "ar": "AR",
    "阿拉伯语": "AR",
}


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
    }


def normalize_deeplx_endpoint(endpoint, add_default_path=True):
    """规范化 DeepLX 接口地址。"""
    endpoint = (endpoint or "").strip()
    if not endpoint:
        return ""

    if "://" not in endpoint:
        endpoint = f"http://{endpoint}"

    parsed = urlparse(endpoint)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc or parsed.path
    path = parsed.path if parsed.netloc else ""

    if not netloc:
        raise ValueError("DeepLX 地址格式不正确")

    if add_default_path and path in ("", "/"):
        path = "/translate"

    return urlunparse((scheme, netloc, path or "", "", "", "")).rstrip("/")


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


def map_deeplx_target_lang(target_lang):
    """将用户输入的目标语言映射为 DeepLX 支持的语言代码。"""
    target_lang = (target_lang or "中文").strip()
    if not target_lang:
        return "ZH"

    mapped = DEEPLX_TARGET_LANG_ALIASES.get(target_lang.lower())
    if mapped:
        return mapped

    if target_lang.isascii() and 2 <= len(target_lang) <= 8:
        return target_lang.upper()

    raise ValueError(f"DeepLX 暂不识别目标语言: {target_lang}")


def map_baidu_translate_target_lang(target_lang):
    """将用户输入的目标语言映射为百度翻译支持的语言代码。"""
    target_lang = (target_lang or "中文").strip()
    if not target_lang:
        return "zh"

    mapped = BAIDU_TRANSLATE_TARGET_LANG_ALIASES.get(target_lang.lower())
    if mapped:
        return mapped

    if target_lang.isascii() and 2 <= len(target_lang) <= 8:
        return target_lang.lower()

    raise ValueError(f"百度翻译暂不识别目标语言: {target_lang}")


def build_baidu_translate_sign(appid, text, salt, appkey):
    """生成百度翻译 API 签名。"""
    raw = f"{appid}{text}{salt}{appkey}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def build_deeplx_candidate_endpoints(configured_endpoint=None):
    """构建 DeepLX 自动检测候选地址。"""
    candidates = []
    seen = set()
    raw_candidates = [
        configured_endpoint,
        DEFAULT_DEEPLX_ENDPOINT,
        "http://127.0.0.1:1188/translate",
        "http://localhost:1188",
        "http://127.0.0.1:1188",
    ]

    for candidate in raw_candidates:
        if not candidate:
            continue
        normalized = normalize_deeplx_endpoint(candidate, add_default_path=True)
        if normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)

    return candidates


def extract_deeplx_translation(result):
    """从 DeepLX 响应中提取翻译文本。"""
    if isinstance(result.get("data"), str):
        return result["data"].strip()

    if isinstance(result.get("translation"), str):
        return result["translation"].strip()

    translations = result.get("translations")
    if isinstance(translations, list) and translations:
        first = translations[0]
        if isinstance(first, dict):
            for key in ("text", "translation", "data"):
                if isinstance(first.get(key), str):
                    return first[key].strip()

    return ""


def probe_deeplx_endpoint(endpoint, timeout=4):
    """检测给定 DeepLX 地址是否可用。"""
    normalized_endpoint = normalize_deeplx_endpoint(endpoint, add_default_path=True)
    payload = {
        "text": "Hello",
        "source_lang": "EN",
        "target_lang": "ZH",
    }

    try:
        response = requests.post(
            normalized_endpoint,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"连接失败: {exc}") from exc

    try:
        result = response.json()
    except ValueError as exc:
        response.raise_for_status()
        raise RuntimeError("响应不是合法的 JSON") from exc

    if response.status_code >= 400:
        error_msg = result.get("message") or result.get("error") or response.text
        raise RuntimeError(f"服务返回错误: {error_msg}")

    translated = extract_deeplx_translation(result)
    if not translated:
        raise RuntimeError("响应中没有可用的翻译结果")

    return normalized_endpoint


def detect_deeplx_endpoint(configured_endpoint=None, timeout=4):
    """自动检测本地可用的 DeepLX 地址。"""
    errors = []
    for endpoint in build_deeplx_candidate_endpoints(configured_endpoint):
        try:
            detected = probe_deeplx_endpoint(endpoint, timeout=timeout)
            logger.info("已检测到可用 DeepLX 服务: %s", detected)
            return detected
        except Exception as exc:
            logger.warning("DeepLX 检测失败: %s, error=%s", endpoint, exc)
            errors.append(f"{endpoint}: {exc}")

    detail = "；".join(errors[:3]) if errors else "未找到候选地址"
    raise RuntimeError(f"未检测到可用的 DeepLX 服务。{detail}")


def resolve_deeplx_endpoint(config, auto_detect=True):
    """解析并验证 DeepLX 地址。"""
    configured_endpoint = config.get("deeplx_endpoint", "")
    if configured_endpoint:
        configured_endpoint = normalize_deeplx_endpoint(
            configured_endpoint,
            add_default_path=True,
        )

    if auto_detect:
        return detect_deeplx_endpoint(configured_endpoint)

    if configured_endpoint:
        return configured_endpoint

    raise ValueError("未配置 DeepLX 地址")


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


def baidu_translate(text, appid, appkey, target_lang="中文"):
    """使用百度翻译 API 进行文本翻译。"""
    target_code = map_baidu_translate_target_lang(target_lang)
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        salt = str(int(time.time() * 1000))
        payload = {
            "q": text,
            "from": "auto",
            "to": target_code,
            "appid": appid,
            "salt": salt,
            "sign": build_baidu_translate_sign(appid, text, salt, appkey),
        }

        try:
            logger.debug(
                "开始百度翻译请求，target_lang=%s, text_length=%s, attempt=%s/%s",
                target_lang,
                len(text),
                attempt,
                max_attempts,
            )
            response = requests.post(BAIDU_TRANSLATE_API_URL, data=payload, timeout=60)
        except requests.exceptions.Timeout as exc:
            raise RuntimeError("百度翻译请求超时，请重试") from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"百度翻译请求失败: {exc}") from exc

        try:
            result = response.json()
        except ValueError as exc:
            response.raise_for_status()
            raise RuntimeError("百度翻译返回了无法解析的响应") from exc

        if response.status_code >= 400:
            raise RuntimeError(f"百度翻译服务请求失败: HTTP {response.status_code}")

        if result.get("error_code"):
            error_code = str(result.get("error_code"))
            error_msg = result.get("error_msg", "未知错误")
            if error_code == "54001":
                raise RuntimeError(
                    "百度翻译签名无效 [54001]：请检查“百度翻译 APP ID / 密钥”是否填写正确，"
                    "不要填写百度 OCR 的 API Key / Secret Key"
                )
            if error_code == "54003":
                if attempt < max_attempts:
                    delay = 2 ** attempt
                    logger.warning(
                        "百度翻译命中频率限制，准备重试: attempt=%s/%s, delay=%ss",
                        attempt,
                        max_attempts,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                raise RuntimeError(
                    "百度翻译访问频率受限 [54003]：当前账号或套餐 QPS 不足，请稍后重试、减少并发，或切换其他翻译提供方"
                )
            raise RuntimeError(f"百度翻译失败 [{error_code}]: {error_msg}")

        break
    else:
        raise RuntimeError("百度翻译请求失败：重试后仍未成功")

    trans_result = result.get("trans_result")
    if not isinstance(trans_result, list) or not trans_result:
        raise RuntimeError("百度翻译响应中没有可用的翻译结果")

    translated_parts = []
    for item in trans_result:
        if isinstance(item, dict) and isinstance(item.get("dst"), str):
            translated_parts.append(item["dst"].strip())

    translated = "\n".join(part for part in translated_parts if part)
    if not translated:
        raise RuntimeError("百度翻译响应中没有可用的翻译文本")

    logger.debug("百度翻译请求完成，target_lang=%s, translated_length=%s", target_lang, len(translated))
    return translated


def deeplx_translate(text, endpoint, target_lang="中文"):
    """使用 DeepLX API 进行文本翻译。"""
    endpoint = normalize_deeplx_endpoint(endpoint, add_default_path=True)
    payload = {
        "text": text,
        "source_lang": "AUTO",
        "target_lang": map_deeplx_target_lang(target_lang),
    }

    try:
        logger.debug("开始 DeepLX 翻译请求，endpoint=%s, text_length=%s", endpoint, len(text))
        response = requests.post(
            endpoint,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
    except requests.exceptions.Timeout as exc:
        raise RuntimeError("DeepLX 翻译请求超时，请重试") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"DeepLX 翻译请求失败: {exc}") from exc

    try:
        result = response.json()
    except ValueError as exc:
        response.raise_for_status()
        raise RuntimeError("DeepLX 返回了无法解析的响应") from exc

    if response.status_code >= 400:
        error_msg = result.get("message") or result.get("error") or "未知错误"
        raise RuntimeError(f"DeepLX 翻译失败: {error_msg}")

    translated = extract_deeplx_translation(result)
    if not isinstance(translated, str) or not translated.strip():
        raise RuntimeError("DeepLX 响应中没有可用的翻译结果")

    translated = translated.strip()
    logger.debug("DeepLX 翻译请求完成，target_lang=%s, translated_length=%s", target_lang, len(translated))
    return translated


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
    """汇总记录四个主要阶段耗时。"""
    logger.info(
        "%s阶段耗时汇总: OCR=%ss, 合并=%ss, 翻译=%ss, 覆盖=%ss",
        task_name,
        stage_timings.get("ocr", 0.0),
        stage_timings.get("merge", 0.0),
        stage_timings.get("translate", 0.0),
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

            render_started_at = time.time()
            success = text_process.replace_text_in_image(
                image,
                str(output_path),
                original_paragraphs,
                translations,
            )
            if not success:
                raise RuntimeError("图片文字替换失败")
            stage_timings["render"] = log_stage_elapsed(task_name, "覆盖文字", render_started_at)
            report_image_progress(progress_callback, 4, "覆盖文字")

            result["message"] = f"识别到 {len(original_paragraphs)} 个文本段落并完成翻译"
        else:
            stage_timings["translate"] = 0.0
            report_image_progress(progress_callback, 3, "翻译段落（无可翻译文本）")
            render_started_at = time.time()
            shutil.copy2(image_path, output_path)
            stage_timings["render"] = log_stage_elapsed(task_name, "覆盖文字（已复制原图）", render_started_at)
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

            render_started_at = time.time()
            success = text_process.replace_text_in_image(
                image,
                str(output_path),
                original_paragraphs,
                translations,
            )
            if not success:
                raise RuntimeError("图片文字替换失败")
            stage_timings["render"] = log_stage_elapsed(task_name, "覆盖文字", render_started_at)
            report_image_progress(progress_callback, 4, "覆盖文字")
            result["message"] = f"识别到 {len(original_paragraphs)} 个文本段落并完成翻译"
        else:
            stage_timings["translate"] = 0.0
            report_image_progress(progress_callback, 3, "翻译段落（无可翻译文本）")
            render_started_at = time.time()
            image.save(output_path)
            stage_timings["render"] = log_stage_elapsed(task_name, "覆盖文字（已复制原图）", render_started_at)
            report_image_progress(progress_callback, 4, "覆盖文字（已复制原图）")
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
