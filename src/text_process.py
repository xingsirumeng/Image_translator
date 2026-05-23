# -*- coding: utf-8 -*-
from PIL import Image, ImageDraw, ImageFont  # 用于图片文字替换
from pathlib import Path
import color_process
import image_inpainting


def merge_text_lines(ocr_results, max_line_gap=1, max_x_diff=0.1):
    # 基于位置信息合并属于同一句子的文本行
    # :param ocr_results: OCR识别结果列表
    # :param max_line_gap: 最大行间距（相对于行高的比例）
    # :param max_x_diff: 最大水平偏移（相对于行宽的比例）
    # :return: 合并后的文本段落列表
    from typing import List, Dict, Any
    paragraphs: List[Dict[str, Any]] = []
    if not ocr_results:
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
            if top > last_bottom and (top - last_bottom) <= height * max_line_gap and (abs(left - last_left) <= max_x_diff * width or abs(mid - last_mid) <= max_x_diff * width):
                para['res'].append(res)
                flag = False
                break

        if flag:
            paragraphs.append({'res': [res], 'direction': 'horizontal'})

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
            if right <= last_left and (last_left - right) <= width * max_line_gap and (
                abs(top - last_top) <= max_x_diff * height or abs(mid - last_mid) <= max_x_diff * height
            ):
                para['res'].append(res)
                flag = False
                break

        if flag:
            vertical_paragraphs.append({'res': [res], 'direction': 'vertical'})

    paragraphs.extend(vertical_paragraphs)

    for para in paragraphs:
        words = ""
        left = min(r['location']['left'] for r in para['res'])
        top = min(r['location']['top'] for r in para['res'])
        right = max(r['location']['left'] + r['location']['width'] for r in para['res'])
        bottom = max(r['location']['top'] + r['location']['height'] for r in para['res'])
        for res in para['res']:
            words += res['words'] + '\n'
        para['words'] = words
        para['left'] = left
        para['top'] = top
        para['right'] = right
        para['bottom'] = bottom

    return paragraphs


def replace_text_in_image(img, output_path, paragraphs, translations):
    img = image_inpainting.image_inpainting(img, paragraphs)
    # 在图片上替换文字
    try:
        # 打开原始图片
        draw = ImageDraw.Draw(img)

        # 尝试加载中文字体，如果失败则使用默认字体
        try:
            # 尝试常见中文字体路径
            font_paths = [
                "C:/Windows/Fonts/simhei.ttf",  # Windows
                "/System/Library/Fonts/PingFang.ttc",  # macOS
                "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"  # Linux
            ]

            font = None
            for path in font_paths:
                if Path(path).exists():
                    font = ImageFont.truetype(path, 20)  # 初始大小，后续会调整
                    break

            if font is None:
                font = ImageFont.load_default()
        except:
            font = ImageFont.load_default()

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

            # 检测文字区域的背景颜色
            bg_color = color_process.get_text_background_color(img, merged_location)
            # bg_color = "white"
            # 检测文字颜色（使用第一个文字块的颜色作为参考）
            text_color = color_process.get_text_color(img, para[0]['location'], bg_color)
            # text_color = "black"

            # 绘制背景覆盖原始文本
            draw.rectangle(
                [(left, top), (right, bottom)],
                fill=bg_color
            )

            # 绘制翻译后的文本
            text = translations[i]
            font_size = para[0]['location']['height']
            if para1['direction'] == 'vertical':
                font_size = para[0]['location']['width']

            # 更新字体大小
            if hasattr(font, "path"):  # 如果是truetype字体
                try:
                    font = ImageFont.truetype(font.path, font_size)
                except:
                    pass
            # if para1['direction'] == 'vertical':
            #     # 创建临时图像，旋转后绘制
            #     # 或者逐字绘制
            #     for res in para:
            #         x, y = res['location']['left'], res['location']['top']
            #         for j, char in enumerate(text):
            #             char_y = y + j * font_size
            #             draw.text((x, char_y), char, fill=text_color, font=font)
            # else:
            x = merged_location["left"]
            y = merged_location["top"]

            draw.text((x, y), text, fill=text_color, font=font)

        # 保存结果
        img.save(output_path)
        return True
    except Exception as e:
        print(f"图片处理错误: {str(e)}")
        return False
