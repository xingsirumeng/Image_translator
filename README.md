# 图片翻译工具 (Image Translator)

一个基于 PySide6 的桌面图片翻译工具，支持 OCR 文字识别 → 翻译 → 将译文覆写回图片，保留原图版式和风格。

## ✨ 功能特性

- **OCR 文字识别** — 使用百度 OCR API 识别图片中的文字，支持位置信息提取
- **多翻译引擎** — 支持三种翻译服务：
  - **DeepSeek** — DeepSeek Chat API，翻译质量高（推荐）
  - **百度翻译** — 百度翻译 API，支持 30+ 语言
  - **DeepLX** — 本地部署的 DeepL 兼容服务，免费无限制
- **智能文字覆写** — 自动检测原图背景色和文字色，用 K-means 聚类算法提取配色
- **竖排文字支持** — 自动识别竖排文字区域并正确排版
- **批量处理** — 支持一次加载多张图片，按顺序逐张处理
- **截图翻译** — 两种截图模式：
  - **框选截图** — 拖拽选择屏幕区域进行翻译，结果以浮窗覆盖显示
  - **一键截图** — 使用上次截图区域或全屏快速翻译
- **全局热键** — Windows 下支持 `Ctrl+Alt+T` 框选截图和 `Ctrl+Shift+Q` 一键截图
- **LAMA 背景填充**（可选）— 使用深度学习模型智能修复文字移除后的背景，需要 GPU 和 `litelama` 库
- **多语言目标** — 支持中文、英文、日文、韩文、法文、德文等数十种目标语言

## 📸 工作流程

```
图片/截图 → OCR识别文字 → 合并段落 → 翻译段落 → 背景填充 → 覆写文字 → 输出结果
```

## 🚀 快速开始

### 环境要求

- Python 3.10+
- Windows / macOS / Linux
- （可选）NVIDIA GPU + CUDA，用于 LAMA 背景填充

### 安装

```bash
cd Image_translator
pip install -r requirements.txt
```

### 运行

```bash
python -m ui.application
```

首次运行会自动引导你配置 API 密钥，也可以随时通过「打开设置」修改。

### 配置 API 密钥

在设置对话框中填写以下信息（按需选择）：

| 服务 | 所需配置 | 获取地址 |
|------|---------|---------|
| 百度 OCR | API Key + Secret Key | [百度智能云控制台](https://console.bce.baidu.com/ai/#/ai/ocr/overview/index) |
| DeepSeek 翻译 | API Key | [DeepSeek 开放平台](https://platform.deepseek.com/) |
| 百度翻译 | APP ID + 密钥 | [百度翻译开放平台](https://fanyi-api.baidu.com/) |
| DeepLX | 服务地址 | 本地 Docker 部署 `ghcr.io/owo-network/deeplx:latest` |

> 💡 推荐组合：**百度 OCR** + **DeepSeek 翻译**，识别准确且翻译自然。

## 📁 项目结构

```
Image_translator/
├── core/                       # 核心模块
│   ├── baidu_ocr.py            # 百度 OCR 接口（令牌获取、图片/内存 OCR 识别）
│   ├── baidu_translate.py      # 百度翻译接口（签名生成、多语言支持）
│   ├── deepseek.py             # DeepSeek Chat 翻译接口
│   ├── deeplx.py               # DeepLX 翻译接口（自动检测/部署引导）
│   ├── color_process.py        # 颜色检测（K-means 背景/文字色提取）
│   ├── text_process.py         # 文字处理（段落合并、字体加载、图片覆写）
│   ├── inpainting.py           # LAMA 背景填充（liteLama 模型封装）
│   ├── capture.py              # 屏幕截图（QImage/PIL 互转、跨屏处理）
│   └── translate_api.py        # API 门面（配置管理、翻译调度、图片任务编排）
├── ui/
│   └── application.py          # PySide6 GUI 主程序
├── tests/
│   └── test_translate_api.py   # 图片处理流程测试
├── models/                     # 模型文件目录
│   └── lama/
│       └── big-lama.safetensors  # LAMA 模型（需自行下载）
├── output/                     # 翻译结果输出目录
├── requirements.txt
└── README.md
```

## 🔧 配置说明

配置文件保存在 `api-data.env`，包含以下字段：

```ini
ocr_provider=baidu              # OCR 提供方
translation_provider=deepseek   # 翻译提供方：deepseek / baidu / deeplx
baidu_api_key=                  # 百度 OCR API Key
baidu_secret_key=               # 百度 OCR Secret Key
baidu_translate_appid=          # 百度翻译 APP ID
baidu_translate_appkey=         # 百度翻译密钥
deepseek_api_key=               # DeepSeek API Key
deeplx_endpoint=                # DeepLX 服务地址（默认 http://localhost:1188/translate）
translate_language=中文          # 目标语言
enable_lama=False               # 是否启用 LAMA 背景填充
```

## 🧪 运行测试

```bash
pytest tests/ -v
```

## 📝 支持的翻译语言

### DeepSeek
支持任意语言目标（由 LLM 理解，直接输入如 "English"、"日本語" 等）

### 百度翻译
中文、英文、日文、韩文、法文、西班牙文、泰文、阿拉伯文、俄文、葡萄牙文、德文、意大利文、希腊文、荷兰文、波兰文、保加利亚文、爱沙尼亚文、丹麦文、芬兰文、捷克文、罗马尼亚文、斯洛文尼亚文、瑞典文、匈牙利文、越南文、粤语、文言文

### DeepLX
中文、英文、日文、韩文、德文、法文、西班牙文、俄文、葡萄牙文、意大利文、荷兰文、波兰文、保加利亚文、捷克文、丹麦文、希腊文、芬兰文、匈牙利文、印尼文、立陶宛文、拉脱维亚文、罗马尼亚文、斯洛伐克文、斯洛文尼亚文、瑞典文、土耳其文、乌克兰文、阿拉伯文

## ⚠️ 注意事项

- 百度 OCR 每天提供免费额度，超量需付费
- DeepSeek API 按 token 计费，费用较低
- LAMA 背景填充需要下载模型文件并存放在 `models/lama/` 目录
- 截图翻译不支持跨多显示器选区
- 首次运行需要联网配置 API 密钥
