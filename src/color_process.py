import numpy as np



import numpy as np


def detect_bg_and_text_color_kmeans(
    image,
    location,
    k=3,
    sample_size=6000,
    max_iter=30,
    n_init=3,
    distance_threshold=40.0,
    seed=0,
):
    """
    用K-means在ROI里聚类，估计背景色和文字色。

    参数:
      image: PIL Image
      location: dict {left, top, width, height}
      k: 聚类数。常用 2~4。背景+文字+抗锯齿/阴影 => 3 比较合适
      sample_size: 从ROI随机采样的像素数（太大慢，太小不稳）
      max_iter: k-means迭代上限
      n_init: 不同随机初始化次数，取最好的一次
      distance_threshold: 文字色与背景色最小距离阈值（太小容易把抗锯齿当文字/背景混掉）
      seed: 随机种子

    返回:
      (bg_color, text_color): 都是 (R,G,B) int 元组
    """
    # ---------- 1) 裁剪ROI ----------
    img = np.array(image)
    h, w = img.shape[0], img.shape[1]

    left = max(0, int(location["left"]))
    top = max(0, int(location["top"]))
    width = int(location["width"])
    height = int(location["height"])

    right = min(w, left + max(0, width))
    bottom = min(h, top + max(0, height))

    if right <= left or bottom <= top:
        return (255, 255, 255), (0, 0, 0)

    roi = img[top:bottom, left:right]
    if roi.size == 0:
        return (255, 255, 255), (0, 0, 0)

    # 只取RGB（如果是RGBA也OK）
    roi_rgb = roi[..., :3].reshape(-1, 3).astype(np.float32)
    n_pixels = roi_rgb.shape[0]
    if n_pixels == 0:
        return (255, 255, 255), (0, 0, 0)

    # ---------- 2) 随机采样减少计算量 ----------
    rng = np.random.default_rng(seed)
    if sample_size is not None and n_pixels > sample_size:
        idx = rng.choice(n_pixels, size=sample_size, replace=False)
        X = roi_rgb[idx]
    else:
        X = roi_rgb

    # ---------- 3) 轻量K-means实现 ----------
    def kmeans_once(X, k, max_iter, rng):
        # 随机选k个点做初始化中心（你也可以换成k-means++，这里先简单）
        centers = X[rng.choice(X.shape[0], size=k, replace=False)].copy()

        for _ in range(max_iter):
            # 计算距离并分配簇
            # distances: [N, k]
            distances = ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
            labels = distances.argmin(axis=1)

            new_centers = centers.copy()
            for j in range(k):
                mask = labels == j
                if mask.any():
                    new_centers[j] = X[mask].mean(axis=0)
                else:
                    # 空簇：重新随机一个点
                    new_centers[j] = X[rng.integers(0, X.shape[0])]

            # 收敛判断
            if np.allclose(new_centers, centers, atol=1e-3):
                centers = new_centers
                break
            centers = new_centers

        # inertia（越小越好）
        inertia = ((X - centers[labels]) ** 2).sum()
        return centers, labels, inertia

    best = None
    for i in range(max(1, n_init)):
        centers, labels, inertia = kmeans_once(X, k, max_iter, rng)
        if best is None or inertia < best[2]:
            best = (centers, labels, inertia)

    centers, labels, _ = best

    # ---------- 4) 选背景簇：像素占比最大 ----------
    counts = np.bincount(labels, minlength=k).astype(np.float32)
    probs = counts / max(1.0, counts.sum())
    bg_idx = int(np.argmax(probs))
    bg = centers[bg_idx]

    # ---------- 5) 选文字簇：与背景距离最大（且最好不是很小的噪声簇） ----------
    def euclid(a, b):
        d = a - b
        return float(np.sqrt(np.dot(d, d)))

    # 候选：除背景外的簇，按“与背景距离”降序
    candidates = []
    for j in range(k):
        if j == bg_idx:
            continue
        dist = euclid(centers[j], bg)
        candidates.append((dist, probs[j], j))
    candidates.sort(reverse=True)  # dist优先

    # 默认取距离最大的；但如果它占比太小且距离也不够，可以退化为对比色
    text_idx = candidates[0][2] if candidates else bg_idx
    text = centers[text_idx]
    if euclid(text, bg) < distance_threshold:
        # 退化：用对比色（黑/白）
        brightness = (bg[0] * 299 + bg[1] * 587 + bg[2] * 114) / 1000.0
        text = np.array([0, 0, 0], dtype=np.float32) if brightness > 128 else np.array([255, 255, 255], dtype=np.float32)

    bg_color = tuple(int(np.clip(c, 0, 255)) for c in bg)
    text_color = tuple(int(np.clip(c, 0, 255)) for c in text)
    return bg_color, text_color


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
        sample_margin = 0
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
            pixel = img_array[y, x]
            background_samples.append(tuple(pixel[:3]))  # 取RGB通道

        # 取所有采样点的中位数
        background_samples = np.array(background_samples)
        median_color = np.median(background_samples, axis=0)

        return tuple(int(c) for c in median_color)

    except Exception as e:
        print(f"背景颜色检测错误: {str(e)}")
        return (255, 255, 255)  # 默认白色


def get_text_color(image, location, bg_color=None, color_threshold=100):
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
            diff = np.array(color1, dtype=np.int32) - np.array(color2, dtype=np.int32)
            return np.sqrt(np.sum(diff ** 2))

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
        if color_distance(text_color, bg_color) < color_threshold:  # 如果颜色太接近背景
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