"""DeepLX 翻译 API 接口模块。

提供 DeepLX 地址规范化、自动检测、目标语言映射、以及文本翻译功能。
"""

import logging
from urllib.parse import urlparse, urlunparse

import requests

logger = logging.getLogger(__name__)

DEFAULT_DEEPLX_ENDPOINT = "http://localhost:1188/translate"

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
    logger.debug(
        "DeepLX 翻译请求完成，target_lang=%s, translated_length=%s",
        target_lang,
        len(translated),
    )
    return translated
