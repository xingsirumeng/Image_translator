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

# 3. 加载图片和掩码（都要是 numpy 格式，掩码白=修复，黑=保留）
img_pil = Image.open("your_image.png").convert("RGB")
mask_pil = Image.open("your_mask.png").convert("L")

image = np.array(img_pil)
mask = np.array(mask_pil)
if mask.max() > 1:
    mask = mask / 255.0  # 归一到0~1

# 4. Run 推理
with torch.no_grad():
    res = model({'image': image, 'mask': mask}, torch.tensor([1.0]))['inpainted']
    # 或用 refine_predict（可选步）

result_img = Image.fromarray(res.astype(np.uint8))
result_img.save("lama_result.png")