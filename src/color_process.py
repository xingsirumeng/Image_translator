import numpy as np


def get_text_background_color(image, location):
    """
    检测文字区域的背景颜色
    :param image: PIL Image对象
    :param location: 文字位置信息 {left, top, width, height}
    :return: RGB背景颜色元组
    """
    try:
        # 转换为numpy数组以便处理
        img_array = np.array(image)

        left = int(location['left'])
        top = int(location['top'])
        width = int(location['width'])
        height = int(location['height'])

        # 确保坐标在图像范围内
        left = max(0, left)
        top = max(0, top)
        right = min(image.width, left + width)
        bottom = min(image.height, top + height)

        if right <= left or bottom <= top:
            return (255, 255, 255)  # 默认白色

        # 获取文字区域
        text_region = img_array[top:bottom, left:right]

        if text_region.size == 0:
            return (255, 255, 255)  # 默认白色

        # 采样边缘像素（通常背景在文字周围）
        background_samples = []

        # 采样边缘像素
        sample_margin = 2
        sample_points = [
            # 上边缘
            (left + sample_margin, top + sample_margin),
            (left + width // 2, top + sample_margin),
            (left + width - sample_margin, top + sample_margin),
            # 下边缘
            (left + sample_margin, top + height - sample_margin),
            (left + width // 2, top + height - sample_margin),
            (left + width - sample_margin, top + height - sample_margin),
            # 左边缘
            (left + sample_margin, top + height // 2),
            # 右边缘
            (left + width - sample_margin, top + height // 2)
        ]

        for x, y in sample_points:
            if 0 <= x < image.width and 0 <= y < image.height:
                pixel = img_array[y, x]
                background_samples.append(tuple(pixel[:3]))  # 取RGB通道

        # 如果没有采样到点，使用整个区域的平均值
        if not background_samples:
            avg_color = np.mean(text_region, axis=(0, 1))
            return tuple(int(c) for c in avg_color[:3])

        # 取所有采样点的中位数
        background_samples = np.array(background_samples)
        median_color = np.median(background_samples, axis=0)

        return tuple(int(c) for c in median_color)

    except Exception as e:
        print(f"背景颜色检测错误: {str(e)}")
        return (255, 255, 255)  # 默认白色


def get_text_color(image, location, bg_color=None, color_threshold=30):
    """
    检测文字颜色（基于背景颜色对比）
    :param image: PIL Image对象
    :param location: 文字位置信息 {left, top, width, height}
    :param bg_color: 已知的背景颜色RGB元组
    :param color_threshold: 颜色差异阈值，值越大越容易区分文字和背景
    :return: RGB文字颜色元组
    """
    try:
        # 转换为numpy数组以便处理
        img_array = np.array(image)

        left = int(location['left'])
        top = int(location['top'])
        width = int(location['width'])
        height = int(location['height'])

        # 确保坐标在图像范围内
        left = max(0, left)
        top = max(0, top)
        right = min(image.width, left + width)
        bottom = min(image.height, top + height)

        if right <= left or bottom <= top:
            return (0, 0, 0)  # 默认黑色

        # 获取文字区域
        text_region = img_array[top:bottom, left:right]

        if text_region.size == 0:
            return (0, 0, 0)  # 默认黑色

        # 如果没有提供背景颜色，使用简单方法检测
        if bg_color is None:
            bg_color = get_text_background_color(image, location)

        # 计算颜色差异函数
        def color_distance(color1, color2):
            """计算两个颜色之间的欧氏距离"""
            return np.linalg.norm(np.array(color1) - np.array(color2))

        # 收集与背景颜色明显不同的像素
        text_pixels = []

        # 遍历整个文字区域
        for y in range(text_region.shape[0]):
            for x in range(text_region.shape[1]):
                pixel_color = tuple(text_region[y, x][:3])
                # 如果像素颜色与背景颜色差异足够大，认为是文字像素
                if color_distance(pixel_color, bg_color) > color_threshold:
                    text_pixels.append(pixel_color)

        # 如果没有找到明显不同的像素，使用备选方案
        if not text_pixels:
            return get_text_color_fallback(text_region, bg_color)

        # 使用中位数作为文字颜色
        text_pixels_array = np.array(text_pixels)
        median_color = np.median(text_pixels_array, axis=0)
        text_color = tuple(map(int, median_color))

        # 最终验证
        if color_distance(text_color, bg_color) < 10:  # 如果颜色太接近背景
            return get_contrasting_color(bg_color)  # 使用对比色

        return text_color

    except Exception as e:
        print(f"文字颜色检测错误: {str(e)}")
        return (0, 0, 0)  # 默认黑色


def get_text_color_fallback(text_region, bg_color):
    """备用的文字颜色检测方法"""
    # 方法1: 使用整个区域的中位数，但与背景不同
    pixels = text_region.reshape(-1, 3)
    median_color = tuple(map(int, np.median(pixels, axis=0)))

    # 检查与背景的差异
    def color_distance(color1, color2):
        return np.sqrt(sum((c1 - c2) ** 2 for c1, c2 in zip(color1, color2)))

    if color_distance(median_color, bg_color) > 20:
        return median_color

    # 方法2: 使用与背景对比的颜色
    return get_contrasting_color(bg_color)


def get_contrasting_color(bg_color):
    """根据背景颜色返回一个对比色"""
    # 计算背景亮度
    brightness = (bg_color[0] * 299 + bg_color[1] * 587 + bg_color[2] * 114) / 1000

    # 如果背景较亮，返回暗色；如果背景较暗，返回亮色
    if brightness > 128:
        return (0, 0, 0)  # 黑色
    else:
        return (255, 255, 255)  # 白色

