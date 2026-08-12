# -*- coding: utf-8 -*-
import logging
from PIL import Image, ImageDraw, ImageFont  # 用于图片文字替换
from pathlib import Path
from core import color_process

logger = logging.getLogger(__name__)


def merge_text_lines(ocr_results, max_line_gap=0.9, max_x_diff=0.1):
    # 基于位置信息合并属于同一句子的文本行
    # :param ocr_results: OCR识别结果列表
    # :param max_line_gap: 最大行间距（相对于行高的比例）
    # :param max_x_diff: 最大水平偏移（相对于行宽的比例）
    # :return: 合并后的文本段落列表
    from typing import List, Dict, Any
    paragraphs: List[Dict[str, Any]] = []
    if not ocr_results:
        logger.info("OCR 结果为空，无需合并段落")
        return []

    def get_bounds(loc):
        left = loc["left"]
        top = loc["top"]
        width = loc["width"]
        height = loc["height"]
        right = loc.get("right", left + width)
        bottom = loc.get("bottom", top + height)
        return left, top, right, bottom, width, height

    # 排序
    sorted_results = sorted(ocr_results, key=lambda x: (x['location']['top'], x['location']['left']))
    paragraphs = []
    vertical_results = []

    for res in sorted_results:
        loc = res['location']
        top, left, height, width = loc['top'], loc['left'], loc['height'], loc['width']
        if height > width * 2:
            vertical_results.append(res)
            continue
        flag = True
        for para in paragraphs:
            if not para:
                continue
            last_left, last_top, last_right, last_bottom, last_width, last_height = get_bounds(
                para['res'][-1]['location']
            )
            last_mid = (last_left * 2 + last_width) / 2
            mid = (left * 2 + width) / 2
            if (top - last_bottom) <= height * max_line_gap and (abs(left - last_left) <= max_x_diff * width or abs(mid - last_mid) <= max_x_diff * width) and para['end'] is False:
                if abs(left - last_left) <= max_x_diff * width and not abs(mid - last_mid) <= max_x_diff * width and para['left'] + para['width'] < (left + width * 0.9):
                    continue
                para['res'].append(res)
                flag = False
                para['width'] = max(para['width'], left + width - left)
                para['height'] = para['top'] + para['height'] - top
                break

        if flag:
            paragraphs.append({
                'res': [res],
                'direction': 'horizontal',
                'left': left,
                'top': top,
                'width': width,
                'height': height,
                'end': False
            })

    vertical_paragraphs = []
    sorted_vertical_results = sorted(
        vertical_results,
        key=lambda x: (
            -(x['location'].get('right', x['location']['left'] + x['location']['width'])),
            x['location']['top'],
        ),
    )
    for res in sorted_vertical_results:
        left, top, right, bottom, width, height = get_bounds(res['location'])

        flag = True
        for para in vertical_paragraphs:
            if not para:
                continue
            last_left, last_top, last_right, last_bottom, last_width, last_height = get_bounds(
                para['res'][-1]['location']
            )
            last_mid = (last_top * 2 + last_height) / 2
            mid = (top * 2 + height) / 2
            if (last_left - right) <= width and (
                            abs(top - last_top) <= max_x_diff * height or abs(mid - last_mid) <= max_x_diff * height):
                para['res'].append(res)
                flag = False
                break

        if flag:
            vertical_paragraphs.append({
                'res': [res],
                'direction': 'vertical',
                'left': left,
                'top': top,
                'width': width,
                'height': height,
                'end': False
            })

    paragraphs.extend(vertical_paragraphs)

    for para in paragraphs:
        words = ""
        left = min(r['location']['left'] for r in para['res'])
        top = min(r['location']['top'] for r in para['res'])
        right = max(r['location']['left'] + r['location']['width'] for r in para['res'])
        bottom = max(r['location']['top'] + r['location']['height'] for r in para['res'])
        for res in para['res']:
            words += res['words'] + ' '
        para['words'] = words
        para['left'] = left
        para['top'] = top
        para['right'] = right
        para['bottom'] = bottom

    logger.info("OCR 文本合并完成: input=%s, paragraphs=%s", len(ocr_results), len(paragraphs))
    return paragraphs


def load_font_path():
    """查找系统中的中文字体，返回第一个存在的路径，否则抛出异常"""
    font_paths = [
        "C:/Windows/Fonts/simhei.ttf",          # Windows
        "/System/Library/Fonts/PingFang.ttc",   # macOS
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",  # Linux
    ]
    for path in font_paths:
        if Path(path).exists():
            return path
    raise FileNotFoundError("未找到任何中文字体文件，请安装中文字体或指定正确路径。")


def replace_text_in_image(img, output_path, paragraphs, translations,
                          debug_output_path=None, skip_background_fill=False,
                          original_image=None):
    """在图片上替换文字。

    Args:
        img: PIL Image (RGB) — 待处理的图片（可能已被 LAMA 等工具预处理过）
        output_path: str — 输出图片路径
        paragraphs: list — 段落列表
        translations: list — 翻译后的文本列表
        debug_output_path: str | None — 调试输出路径
        skip_background_fill: bool — 若为 True，跳过纯色背景填充（当外部已用 LAMA
                               等工具预先清理背景时使用）
        original_image: PIL Image | None — 原始图片，用于颜色检测。
                        当 skip_background_fill=True 时应传入，确保颜色基于原图。
    """
    # 用于颜色检测的图像：优先使用原图
    color_ref_img = original_image if original_image is not None else img
    # img1 = img.copy()
    try:
        logger.info("开始回写图片文字: output=%s, paragraphs=%s", output_path, len(paragraphs))
        # 打开原始图片
        draw = ImageDraw.Draw(img)
        # draw1 = ImageDraw.Draw(img1)
        # 尝试加载中文字体，如果失败则使用默认字体
        try:
            # 尝试常见中文字体路径
            font_path = load_font_path()
        except Exception as e:
            logger.error("加载字体失败: %s", e)
            raise

        # 处理每个段落
        for i, para1 in enumerate(paragraphs):
            para = para1['res']
            # 计算整个段落的边界
            left = min(r['location']['left'] for r in para)
            top = min(r['location']['top'] for r in para)
            right = max(r['location']['left'] + r['location']['width'] for r in para)
            bottom = max(r['location']['top'] + r['location']['height'] for r in para)
            width = right - left
            height = bottom - top

            # 创建合并后的位置信息
            merged_location = {
                'left': left,
                'top': top,
                'width': width,
                'height': height
            }
            # draw1.rectangle((left, top, left + width, top + height), outline='red', width=3)

            # 检测背景颜色和文字颜色（基于原图，确保颜色识别准确）
            bg_color, text_color = color_process.detect_bg_and_text_color_kmeans(color_ref_img, merged_location)

            if not skip_background_fill:
                # 绘制纯色背景覆盖原始文本
                draw.rectangle(
                    [(left, top), (right, bottom)],
                    fill=bg_color
                )
            # 绘制翻译后的文本
            text = translations[i]

            def get_font(horizontal: bool, count: float):
                count = max(1.0, count)
                if horizontal is True:
                    avg_size = height / count
                    f_size = max(1, int(avg_size))
                    return ImageFont.truetype(font_path, f_size), f_size
                else:
                    avg_size = width / count
                    f_size = max(1, int(avg_size))
                    return ImageFont.truetype(font_path, f_size), f_size

            if para1['direction'] == "horizontal":
                font, font_size = get_font(True, len(para1['res']))
                cnt, l = 1, 0
                for c in text:
                    bbox = font.getbbox(c)
                    char_width = bbox[2] - bbox[0]
                    if l + char_width > width:
                        cnt += 1
                        l = 0
                    l += char_width
                if cnt > len(para1['res']):
                    font, font_size = get_font(True, cnt)
                x, y = left, top
                line_height = font_size + 0.5
                draw_text = ""
                for c in text:
                    bbox = font.getbbox(c)
                    char_width = bbox[2] - bbox[0]
                    if x + char_width > right:
                        x = left
                        y += line_height
                        draw_text += '\n'
                    draw_text += c
                    x += char_width
                draw.text((left, top), draw_text, fill=text_color, font=font)
            else:
                font, font_size = get_font(False, len(para1['res']))
                cnt, l = 1, 0
                for c in text:
                    bbox = font.getbbox(c)
                    char_height = max(bbox[3] - bbox[1], bbox[2] - bbox[0])
                    if l + char_height > height:
                        cnt += 1
                        l = 0
                    l += char_height
                if cnt > len(para1['res']):
                    font, font_size = get_font(False, cnt)
                x, y = right, top
                line_height = font_size + 0.5
                for c in text:
                    bbox = font.getbbox(c)
                    char_height = max(bbox[3] - bbox[1], bbox[2] - bbox[0])
                    if y + char_height > bottom:
                        y = top
                        x -= line_height
                    draw.text((x - font_size, y), c, fill=text_color, font=font)
                    y += char_height

        # 保存结果
        if debug_output_path:
            img1.save(debug_output_path)
        img.save(output_path)
        logger.info("图片文字回写完成: %s", output_path)
        return True
    except Exception as e:
        logger.exception("图片文字回写失败: %s", output_path)
        return False
