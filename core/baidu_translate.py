"""百度翻译 API 接口模块。

提供百度翻译 API 签名生成、目标语言映射、以及文本翻译功能。
"""

import hashlib
import logging
import time

import requests

logger = logging.getLogger(__name__)

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
                    "百度翻译签名无效 [54001]：请检查'百度翻译 APP ID / 密钥'是否填写正确，"
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

    logger.debug(
        "百度翻译请求完成，target_lang=%s, translated_length=%s",
        target_lang,
        len(translated),
    )
    return translated
