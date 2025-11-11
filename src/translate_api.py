import os
import sys
import time
import base64
import json
import requests
from pathlib import Path
from dotenv import dotenv_values
import text_process
import concurrent.futures
import threading


def get_project_root():
    """获取项目根目录"""
    current_file = Path(__file__).resolve()

    # 如果当前文件在src目录中，则根目录是父目录
    if "src" in current_file.parts:
        return current_file.parents[1]  # 上两级目录

    # 否则使用包含.git的目录作为根目录
    for path in [current_file.parent, *current_file.parents]:
        if (path / ".git").exists():
            return path

    # 最后使用当前工作目录
    return Path.cwd()


def load_config():
    """加载或创建配置文件"""
    PROJECT_ROOT = get_project_root()
    ENV_FILE = PROJECT_ROOT / "api-data.env"

    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"环境文件路径: {ENV_FILE}")

    if ENV_FILE.exists():
        print(f"找到环境文件: {ENV_FILE}")
        return dotenv_values(ENV_FILE)
    else:
        print(f"未找到环境文件，将在根目录创建: {ENV_FILE}")

        # 获取用户输入
        print("\n请提供以下API密钥 (输入后将保存到本地文件):")
        baidu_api_key = input("百度OCR API Key: ").strip()
        baidu_secret_key = input("百度OCR Secret Key: ").strip()
        deepseek_api_key = input("DeepSeek API Key: ").strip()

        # 确保目录存在
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)

        # 保存到文件
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.write(f"# API密钥配置 请勿分享此文件!\n")
            f.write(f"BAIDU_API_KEY={baidu_api_key}\n")
            f.write(f"BAIDU_SECRET_KEY={baidu_secret_key}\n")
            f.write(f"DEEPSEEK_API_KEY={deepseek_api_key}\n")

        print(f"\n配置已保存到 {ENV_FILE}")
        print("请确保将此文件添加到.gitignore避免泄露")

        return {
            "BAIDU_API_KEY": baidu_api_key,
            "BAIDU_SECRET_KEY": baidu_secret_key,
            "DEEPSEEK_API_KEY": deepseek_api_key
        }


def get_baidu_ocr_token(api_key, secret_key):
    """获取百度OCR的访问令牌"""
    url = f"https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={api_key}&client_secret={secret_key}"
    response = requests.post(url)
    return response.json().get("access_token")


def baidu_ocr_with_location(image_path, access_token):
    """获取带位置信息的OCR结果"""
    try:
        with open(image_path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode()

        # 使用高精度接口获取位置信息
        url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/accurate?access_token={access_token}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        # 优化参数：启用段落检测和方向检测
        data = {
            "image": img_base64,
            "recognize_granularity": "big",  # 返回行级别信息
            # "paragraph": "true",  # 尝试检测段落
            # "detect_direction": "true",  # 检测文本方向
            # "vertexes_location": "true"  # 获取更精确的顶点位置
        }
        response = requests.post(url, headers=headers, data=data)
        result = response.json()

        if "words_result" not in result:
            error_msg = result.get("error_msg", "未知错误")
            raise Exception(f"OCR识别失败: {error_msg} (错误码: {result.get('error_code', '未知')}")

        return result["words_result"]
    except FileNotFoundError:
        raise Exception(f"图片文件不存在: {image_path}")
    except Exception as e:
        raise Exception(f"OCR处理错误: {str(e)}")


def deepseek_translate(text, api_key, target_lang="中文"):
    """使用DeepSeek API进行文本翻译"""
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        prompt = (
            f"请将以下内容准确翻译成{target_lang}，严格保持原始格式：\n\n"
            f"文本内容：\n\n{text}\n\n"
            "翻译要求：\n"
            "1. 仅返回翻译结果，不要添加任何额外说明（包括引导句）\n"
            "2. 保留所有换行符、空格和标点\n"
        )

        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 4000
        }

        response = requests.post(url, headers=headers, json=payload, timeout=60)
        result = response.json()

        if "choices" in result:
            return result["choices"][0]["message"]["content"].strip()
        else:
            error_msg = result.get("error", {}).get("message", "未知错误")
            error_code = result.get("error", {}).get("code", "未知")
            raise Exception(f"翻译失败 [{error_code}]: {error_msg}")
    except requests.exceptions.Timeout:
        raise Exception("翻译请求超时，请重试")
    except Exception as e:
        raise Exception(f"翻译处理错误: {str(e)}")


def parallel_translate(paragraphs, api_key, target_lang, max_workers=3):
    """并行翻译多个段落（保持原始顺序）"""

    def translate_single(para):
        """单个段落的翻译任务"""
        try:
            result = deepseek_translate(para['words'], api_key, target_lang)
            return result
        except Exception as e:
            error_msg = f"翻译失败: {str(e)}"
            return error_msg

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 方法1: 使用map（最简单，保持顺序）
        translations = list(executor.map(
            lambda para: translate_single(para),
            paragraphs
        ))
    return translations


def main():

    try:
        # 安全警告
        print("安全提示: API密钥将保存到本地 .env 文件")
        print("请勿分享此文件或将其上传到公开仓库\n")

        # 加载配置
        config = load_config()

        # 用户输入
        print("\n图片翻译工具")
        image_path = input("请输入图片路径: ").strip()
        target_lang = input("目标语言(默认中文): ").strip() or "中文"

        # 执行流程
        print("\n正在获取百度OCR访问令牌...")
        baidu_token = get_baidu_ocr_token(
            config["BAIDU_API_KEY"],
            config["BAIDU_SECRET_KEY"]
        )

        print("正在进行文字识别...")
        ocr_results = baidu_ocr_with_location(image_path, baidu_token)
        original_texts = [item["words"] for item in ocr_results]
        print(f"\n识别到 {len(original_texts)} 个文字区域")

        # 合并文本行为有意义的段落
        original_paragraphs = text_process.merge_text_lines(ocr_results)
        print(f"识别到 {len(original_paragraphs)} 个有意义的文本段落")

        # 翻译所有文本
        print("\n正在翻译文本...")
        start_time = time.time()

        # 并行线程数
        max_workers = min(5, len(original_paragraphs))

        translations = parallel_translate(
            original_paragraphs,
            config["DEEPSEEK_API_KEY"],
            target_lang,
            max_workers
        )

        elapsed = time.time() - start_time
        print(f"\n翻译完成 ({elapsed:.2f}秒)")

        # 显示部分翻译结果
        print("\n部分翻译结果预览:")
        for i in range(min(3, len(original_paragraphs))):
            print(f"  {original_paragraphs[i]['words']} → {translations[i]}")
        if len(original_paragraphs) > 3:
            print(f"  ...共 {len(original_paragraphs)} 条翻译")

        # 图片文字替换
        print("\n正在替换图片文字...")
        output_path = "./result/" + Path(image_path).stem + "_translated.jpg"
        success = text_process.replace_text_in_image(image_path, output_path, original_paragraphs, translations)

        if success:
            print(f"\n图片处理完成，结果已保存到: {output_path}")
        else:
            print("\n图片处理失败，仅保存文本翻译结果")

        # 保存文本结果
        text_output_path = "./result/" + Path(image_path).stem + "_translation.txt"
        with open(text_output_path, "w", encoding="utf-8") as f:
            f.write("原始文本:\n")
            f.write("\n".join([para['words'] for para in original_paragraphs]))
            f.write("\n\n翻译结果:\n")
            f.write("\n".join(translations))
        print(f"文本翻译结果已保存到: {text_output_path}")

    except Exception as e:
        print(f"\n错误: {str(e)}")
        print("请检查: 1) API密钥是否正确 2) 网络连接 3) 图片路径")


if __name__ == "__main__":
    main()
