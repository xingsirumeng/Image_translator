from PIL import Image, ImageDraw
import sys
import torch
from omegaconf import OmegaConf
from PIL import Image
import numpy as np
import cv2
import os

# 1. 加载 config.yaml
CFG_PATH = "models/big-lama/config.yaml"
MODEL_PATH = "models/big-lama/models/best.ckpt"

cfg = OmegaConf.load(CFG_PATH)

# 修改import（import时候要保证“src”在sys.path里）
sys.path.insert(0, os.path.abspath("src"))  # 保证能import lama.*
# 2. 加载模型
from lama.saicinpainting.training.trainers import load_checkpoint
from lama.saicinpainting.evaluation.refinement import refine_predict
from lama.saicinpainting.evaluation.utils import move_to_device

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
train_config = cfg
predict_config = cfg.get("predictor", None)

model = load_checkpoint(train_config, MODEL_PATH, map_location='cpu')
model = move_to_device(model, device)
model.eval()


def create_mask(image, paragraphs):
    w, h = image.size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    for paragraph in paragraphs:
        x1, y1, x2, y2 = paragraph['left'], paragraph['top'], paragraph['right'], paragraph['bottom']
        draw.rectangle([x1, y1, x2, y2], fill=255)
    return np.array(mask)


def image_inpainting(image, paragraphs):
    image = np.array(image)
    mask = create_mask(image, paragraphs)
    if mask.max() > 1:
        mask = mask / 255.0  # 归一到0~1

    # 4. Run 推理
    with torch.no_grad():
        res = model({'image': image, 'mask': mask}, torch.tensor([1.0]))['inpainted']
        # 或用 refine_predict（可选步）

    result_img = Image.fromarray(res.astype(np.uint8))
    result_img.save("lama_result.png")
    return result_img
