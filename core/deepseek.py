"""DeepSeek 翻译 API 接口模块。

使用 DeepSeek Chat API 进行文本翻译。
"""

import logging

import requests

logger = logging.getLogger(__name__)


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

    logger.debug(
        "翻译请求完成，target_lang=%s, translated_length=%s",
        target_lang,
        len(result["choices"][0]["message"]["content"]),
    )
    return result["choices"][0]["message"]["content"].strip()
