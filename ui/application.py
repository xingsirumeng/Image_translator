import os
import sys
import logging
import ctypes
import ctypes.wintypes
from pathlib import Path
from dotenv import dotenv_values
from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QObject,
    QPoint,
    QRect,
    Qt,
    QSettings,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.capture import capture_rect_with_screen_info, pil_to_qpixmap
from core import translate_api

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
logger = logging.getLogger(__name__)


WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
VK_T = 0x54
VK_F8 = 0x77


class GlobalHotkeyManager(QObject, QAbstractNativeEventFilter):
    """Windows 全局热键管理。"""

    hotkey_triggered = Signal()
    HOTKEY_CANDIDATES = (
        (1, MOD_CONTROL | MOD_ALT, VK_T, "Ctrl+Alt+T"),
        (2, MOD_CONTROL | MOD_SHIFT, VK_T, "Ctrl+Shift+T"),
        (3, MOD_ALT | MOD_SHIFT, VK_T, "Alt+Shift+T"),
        (4, MOD_CONTROL | MOD_ALT, VK_F8, "Ctrl+Alt+F8"),
    )

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self.parent = parent
        self._registered = False
        self._hotkey_id = None
        self._hotkey_label = None
        self._user32 = None

        if sys.platform == "win32":
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)

    @classmethod
    def default_hotkey_label(cls):
        return cls.HOTKEY_CANDIDATES[0][3]

    @property
    def hotkey_label(self):
        return self._hotkey_label

    def _describe_register_error(self, error_code):
        if error_code == 1409:
            return "已被其他程序占用"
        if error_code == 0:
            return "未知原因"
        return f"WinError {error_code}"

    def register(self):
        if sys.platform != "win32" or self._registered:
            return self._hotkey_label

        app = QGuiApplication.instance()
        if app is None:
            raise RuntimeError("QGuiApplication 尚未初始化，无法注册全局热键")

        for hotkey_id, modifiers, virtual_key, label in self.HOTKEY_CANDIDATES:
            ctypes.set_last_error(0)
            if self._user32.RegisterHotKey(None, hotkey_id, modifiers, virtual_key):
                app.installNativeEventFilter(self)
                self._registered = True
                self._hotkey_id = hotkey_id
                self._hotkey_label = label
                logger.info("全局热键已注册: %s", label)
                return label

            error_code = ctypes.get_last_error()
            logger.warning("全局热键注册失败: %s (%s)", label, self._describe_register_error(error_code))

        logger.error("所有候选全局热键均注册失败")
        return None

    def unregister(self):
        if sys.platform != "win32" or not self._registered:
            return

        try:
            app = QGuiApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self)
        finally:
            self._user32.UnregisterHotKey(None, self._hotkey_id)
            self._registered = False
            logger.info("全局热键已注销: %s", self._hotkey_label)
            self._hotkey_id = None
            self._hotkey_label = None

    def nativeEventFilter(self, event_type, message):
        if sys.platform != "win32":
            return False

        if event_type not in ("windows_generic_MSG", "windows_dispatcher_MSG"):
            return False

        msg = ctypes.wintypes.MSG.from_address(int(message))
        if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
            QTimer.singleShot(0, self.hotkey_triggered.emit)
            return True
        return False


class ConfigManager:
    """统一的配置管理器"""

    def __init__(self, config_path=None):
        self.config_path = Path(config_path) if config_path else translate_api.get_config_path()
        self.config = {}
        self.load()

    def load(self):
        """加载配置"""
        if self.config_path.exists():
            self.config = translate_api.normalize_config(dotenv_values(self.config_path))
            logger.info("已加载配置文件: %s", self.config_path)
        else:
            self.config = self._get_default_config()
            logger.warning("配置文件不存在，使用默认配置: %s", self.config_path)

    def _get_default_config(self):
        """获取默认配置"""
        return translate_api.get_default_config()

    def save(self, new_config=None):
        """保存配置"""
        if new_config:
            self.config.update(new_config)
        self.config = translate_api.normalize_config(self.config)

        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.config_path, "w", encoding="utf-8") as file:
            file.write("# API密钥配置 请勿分享此文件!\n")
            for key, value in self.config.items():
                file.write(f"{key}={value}\n")

        logger.info("已保存配置文件: %s", self.config_path)

    def get(self, key, default=None):
        """获取配置值"""
        return self.config.get(key, default)

    def to_dict(self):
        """返回可序列化配置"""
        return dict(self.config)


def run_single_image_task(payload):
    """单张图片处理入口"""
    return translate_api.process_image_task(**payload)


def build_batch_payloads(image_paths, config):
    """为批量任务构建唯一输出名，避免同名图片覆盖结果。"""
    stem_counts = {}
    payloads = []

    for image_path in image_paths:
        path = Path(image_path)
        stem = path.stem
        stem_counts[stem] = stem_counts.get(stem, 0) + 1

        output_base_name = stem
        if stem_counts[stem] > 1:
            output_base_name = f"{stem}_{path.parent.name}_{stem_counts[stem]}"

        payloads.append(
            {
                "image_path": image_path,
                "config": config,
                "output_dir": str(translate_api.get_result_dir()),
                "output_base_name": output_base_name,
            }
        )

    logger.debug("已构建批量任务载荷，数量=%s", len(payloads))
    return payloads


class BatchTranslationWorker(QThread):
    """批量翻译工作线程"""

    finished = Signal(list)
    error = Signal(str)
    progress = Signal(str)
    overall_progress = Signal(int, int, str)
    item_finished = Signal(dict)

    def __init__(self, image_paths, config_manager):
        super().__init__()
        self.image_paths = image_paths
        self.config = config_manager.to_dict()
        self._results = []
        self._cancel_requested = False

    def request_cancel(self):
        """请求取消执行"""
        self._cancel_requested = True
        logger.warning("收到批量任务取消请求")

    def run(self):
        """执行批量任务"""
        try:
            translate_api.validate_config(self.config)

            payloads = build_batch_payloads(self.image_paths, self.config)

            total = len(payloads)
            if total == 0:
                logger.info("批量任务没有可处理图片")
                self.finished.emit([])
                return

            logger.info("批量任务开始，图片数量=%s", total)
            self.progress.emit(f"开始批量处理，共 {total} 张图片，按顺序逐张处理")
            self.overall_progress.emit(0, total * translate_api.IMAGE_STAGE_COUNT, "准备开始")

            completed = 0
            for index, payload in enumerate(payloads):
                if self._cancel_requested:
                    logger.warning("批量任务在处理前被取消，已完成=%s/%s", completed, total)
                    break

                image_path = payload["image_path"]
                logger.info("开始处理图片 %s (%s/%s)", Path(image_path).name, completed + 1, total)
                try:
                    def stage_callback(stage_index, stage_name):
                        overall = index * translate_api.IMAGE_STAGE_COUNT + stage_index
                        self.overall_progress.emit(
                            overall,
                            total * translate_api.IMAGE_STAGE_COUNT,
                            f"{Path(image_path).name} - {stage_name}",
                        )

                    task_payload = dict(payload)
                    task_payload["progress_callback"] = stage_callback
                    result = run_single_image_task(task_payload)
                except Exception as exc:
                    logger.exception("处理图片时出现未捕获异常: %s", image_path)
                    result = {
                        "image_path": image_path,
                        "success": False,
                        "output_path": "",
                        "text_output_path": "",
                        "paragraph_count": 0,
                        "ocr_region_count": 0,
                        "elapsed_seconds": 0.0,
                        "message": "",
                        "error": str(exc),
                    }

                self._results.append(result)
                completed += 1
                self.item_finished.emit(result)
                self.progress.emit(f"已完成 {completed}/{total}: {Path(image_path).name}")
                self.overall_progress.emit(
                    completed * translate_api.IMAGE_STAGE_COUNT,
                    total * translate_api.IMAGE_STAGE_COUNT,
                    f"已完成 {Path(image_path).name}",
                )

            if self._cancel_requested:
                self.progress.emit("批量处理已取消")
                logger.warning("批量任务已取消，完成=%s/%s", completed, total)
            else:
                logger.info("批量任务完成，成功提交结果数量=%s", len(self._results))

            self.finished.emit(self._results)

        except Exception as exc:
            logger.exception("批量任务执行失败")
            self.error.emit(str(exc))


class ScreenshotTranslationWorker(QThread):
    """截图翻译工作线程。"""

    finished = Signal(dict)
    error = Signal(str)
    overall_progress = Signal(int, int, str)

    def __init__(self, image, config_manager, image_name="截图"):
        super().__init__()
        self.image = image
        self.image_name = image_name
        self.config = config_manager.to_dict()

    def run(self):
        try:
            translate_api.validate_config(self.config)

            def stage_callback(stage_index, stage_name):
                self.overall_progress.emit(stage_index, translate_api.IMAGE_STAGE_COUNT, stage_name)

            result = translate_api.process_pil_image_task(
                self.image,
                self.config,
                progress_callback=stage_callback,
                image_name=self.image_name,
            )
            self.finished.emit(result)
        except Exception as exc:
            logger.exception("截图翻译工作线程失败")
            self.error.emit(str(exc))


class SelectionOverlay(QWidget):
    """全屏透明选区层。"""

    region_selected = Signal(QRect)
    canceled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dragging = False
        self._start_pos = QPoint()
        self._current_pos = QPoint()
        self._anchor_rect = QRect()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self._brush = QBrush(QColor(0, 0, 0, 110))
        self._border_pen = QPen(QColor(0, 200, 255, 220), 2)
        self._hint_pen = QPen(QColor(255, 255, 255, 220), 1)

    def begin(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("未找到可用屏幕")

        geometry = screen.virtualGeometry() if hasattr(screen, "virtualGeometry") else screen.geometry()
        self._anchor_rect = QRect(geometry)
        self.setGeometry(self._anchor_rect)
        self.show()
        self.raise_()
        self.activateWindow()
        self.grabMouse()
        self.grabKeyboard()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._start_pos = event.position().toPoint()
            self._current_pos = self._start_pos
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.cancel()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._current_pos = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            end_pos = event.position().toPoint()
            local_rect = QRect(self._start_pos, end_pos).normalized()
            if local_rect.width() < 5 or local_rect.height() < 5:
                self.hide()
                self.releaseMouse()
                self.releaseKeyboard()
                self.canceled.emit()
                return

            global_rect = QRect(local_rect)
            global_rect.moveTo(local_rect.topLeft() + self._anchor_rect.topLeft())
            self.hide()
            self.releaseMouse()
            self.releaseKeyboard()
            self.region_selected.emit(global_rect)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()

    def cancel(self):
        self.hide()
        self.releaseMouse()
        self.releaseKeyboard()
        self.canceled.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._brush)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self._dragging:
            rect = QRect(self._start_pos, self._current_pos).normalized()
            painter.setPen(self._border_pen)
            painter.drawRect(rect)
            painter.setPen(self._hint_pen)
            painter.drawText(rect.adjusted(8, 8, -8, -8), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, "拖拽选择截图区域，右键或 Esc 取消")


class OverlayPreviewWindow(QDialog):
    """展示翻译结果的无边框覆盖窗。"""

    overlay_closed = Signal()

    def __init__(self, pixmap, rect: QRect, parent=None):
        super().__init__(parent)
        self._content_pixmap = pixmap
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setGeometry(rect)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._label.setStyleSheet("background: transparent; border: none;")
        self._label.setGeometry(0, 0, rect.width(), rect.height())
        self._label.setScaledContents(True)
        self._update_pixmap()

    def resizeEvent(self, event):
        self._label.setGeometry(self.rect())
        self._update_pixmap()
        super().resizeEvent(event)

    def _update_pixmap(self):
        if not self._content_pixmap.isNull():
            self._label.setPixmap(self._content_pixmap)

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.overlay_closed.emit()
        super().closeEvent(event)


class SettingsDialog(QDialog):
    """设置对话框"""

    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.setWindowTitle("参数设置")
        self.resize(560, 520)

        layout = QVBoxLayout(self)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)

        content_layout = QVBoxLayout(scroll_content)
        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        content_layout.addLayout(form_layout)

        self.ocr_provider_combo = QComboBox()
        self.translation_provider_combo = QComboBox()
        for key, label in translate_api.OCR_PROVIDER_LABELS.items():
            self.ocr_provider_combo.addItem(label, key)
        for key, label in translate_api.TRANSLATION_PROVIDER_LABELS.items():
            self.translation_provider_combo.addItem(label, key)

        self.translate_language_input = QLineEdit()
        self.translate_language_input.setPlaceholderText("例如：中文、English、JA")

        self.baidu_api_key_input = QLineEdit()
        self.baidu_secret_key_input = QLineEdit()
        self.baidu_secret_key_input.setEchoMode(QLineEdit.Password)
        self.baidu_translate_appid_input = QLineEdit()
        self.baidu_translate_appkey_input = QLineEdit()
        self.baidu_translate_appkey_input.setEchoMode(QLineEdit.Password)
        self.deepseek_api_key_input = QLineEdit()
        self.deepseek_api_key_input.setEchoMode(QLineEdit.Password)
        self.deeplx_endpoint_input = QLineEdit()
        self.deeplx_endpoint_input.setPlaceholderText("http://localhost:1188/translate")

        form_layout.addRow("OCR 提供方:", self.ocr_provider_combo)
        form_layout.addRow("翻译提供方:", self.translation_provider_combo)
        form_layout.addRow("目标语言:", self.translate_language_input)

        self.baidu_group = QWidget()
        baidu_layout = QFormLayout(self.baidu_group)
        baidu_layout.setContentsMargins(0, 0, 0, 0)
        baidu_layout.addRow("百度 OCR API Key:", self.baidu_api_key_input)
        baidu_layout.addRow("百度 OCR Secret Key:", self.baidu_secret_key_input)
        content_layout.addWidget(self.baidu_group)

        self.baidu_translate_group = QWidget()
        baidu_translate_layout = QFormLayout(self.baidu_translate_group)
        baidu_translate_layout.setContentsMargins(0, 0, 0, 0)
        baidu_translate_layout.addRow("百度翻译 APP ID:", self.baidu_translate_appid_input)
        baidu_translate_layout.addRow("百度翻译密钥:", self.baidu_translate_appkey_input)
        content_layout.addWidget(self.baidu_translate_group)

        self.deepseek_group = QWidget()
        deepseek_layout = QFormLayout(self.deepseek_group)
        deepseek_layout.setContentsMargins(0, 0, 0, 0)
        deepseek_layout.addRow("DeepSeek API Key:", self.deepseek_api_key_input)
        content_layout.addWidget(self.deepseek_group)

        self.deeplx_group = QWidget()
        deeplx_layout = QVBoxLayout(self.deeplx_group)
        deeplx_layout.setContentsMargins(0, 0, 0, 0)
        deeplx_intro = QLabel(
            "DeepLX 部署方案：\n"
            "1. 本地启动 DeepLX 服务。\n"
            "2. 默认会自动探测 http://localhost:1188/translate。\n"
            "3. 如果自动探测失败，可手动填写自定义服务地址。"
        )
        deeplx_intro.setWordWrap(True)
        deeplx_intro.setStyleSheet("color: #444;")
        deeplx_layout.addWidget(deeplx_intro)

        command_label = QLabel("可参考命令：`docker run -p 1188:1188 ghcr.io/owo-network/deeplx:latest`")
        command_label.setWordWrap(True)
        command_label.setTextFormat(Qt.TextFormat.MarkdownText)
        deeplx_layout.addWidget(command_label)

        deeplx_form = QFormLayout()
        deeplx_form.setContentsMargins(0, 0, 0, 0)
        deeplx_form.addRow("服务地址:", self.deeplx_endpoint_input)
        deeplx_layout.addLayout(deeplx_form)

        deeplx_button_row = QHBoxLayout()
        self.deeplx_detect_btn = QPushButton("检测 DeepLX")
        self.deeplx_autofill_btn = QPushButton("填入默认地址")
        deeplx_button_row.addWidget(self.deeplx_detect_btn)
        deeplx_button_row.addWidget(self.deeplx_autofill_btn)
        deeplx_button_row.addStretch(1)
        deeplx_layout.addLayout(deeplx_button_row)

        self.deeplx_status_label = QLabel("状态：未检测")
        self.deeplx_status_label.setWordWrap(True)
        deeplx_layout.addWidget(self.deeplx_status_label)
        content_layout.addWidget(self.deeplx_group)

        info_label = QLabel("提示：API 密钥、百度翻译凭证和 DeepLX 地址将保存在本地配置文件中。")
        info_label.setStyleSheet("color: gray; font-size: 10px;")
        info_label.setWordWrap(True)
        content_layout.addWidget(info_label)
        content_layout.addStretch(1)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.translation_provider_combo.currentIndexChanged.connect(self.update_provider_sections)
        self.ocr_provider_combo.currentIndexChanged.connect(self.update_provider_sections)
        self.deeplx_detect_btn.clicked.connect(self.detect_deeplx)
        self.deeplx_autofill_btn.clicked.connect(self.fill_default_deeplx_endpoint)

        self._load_values()
        self.update_provider_sections()

    def get_values(self):
        """获取输入值"""
        return {
            "ocr_provider": self.ocr_provider_combo.currentData(),
            "translation_provider": self.translation_provider_combo.currentData(),
            "baidu_api_key": self.baidu_api_key_input.text().strip(),
            "baidu_secret_key": self.baidu_secret_key_input.text().strip(),
            "baidu_translate_appid": self.baidu_translate_appid_input.text().strip(),
            "baidu_translate_appkey": self.baidu_translate_appkey_input.text().strip(),
            "deepseek_api_key": self.deepseek_api_key_input.text().strip(),
            "deeplx_endpoint": self.deeplx_endpoint_input.text().strip(),
            "translate_language": self.translate_language_input.text().strip() or "中文",
        }

    def _load_values(self):
        config = self.config_manager.to_dict()
        self._set_combo_value(self.ocr_provider_combo, config.get("ocr_provider", "baidu"))
        self._set_combo_value(
            self.translation_provider_combo,
            config.get("translation_provider", "deepseek"),
        )
        self.translate_language_input.setText(config.get("translate_language", "中文"))
        self.baidu_api_key_input.setText(config.get("baidu_api_key", ""))
        self.baidu_secret_key_input.setText(config.get("baidu_secret_key", ""))
        self.baidu_translate_appid_input.setText(config.get("baidu_translate_appid", ""))
        self.baidu_translate_appkey_input.setText(config.get("baidu_translate_appkey", ""))
        self.deepseek_api_key_input.setText(config.get("deepseek_api_key", ""))
        self.deeplx_endpoint_input.setText(config.get("deeplx_endpoint", ""))

    def _set_combo_value(self, combo_box, value):
        index = combo_box.findData(value)
        combo_box.setCurrentIndex(index if index >= 0 else 0)

    def update_provider_sections(self):
        ocr_provider = self.ocr_provider_combo.currentData()
        translation_provider = self.translation_provider_combo.currentData()
        self.baidu_group.setVisible(ocr_provider == "baidu")
        self.baidu_translate_group.setVisible(translation_provider == "baidu")
        self.deepseek_group.setVisible(translation_provider == "deepseek")
        self.deeplx_group.setVisible(translation_provider == "deeplx")

    def fill_default_deeplx_endpoint(self):
        self.deeplx_endpoint_input.setText(translate_api.DEFAULT_DEEPLX_ENDPOINT)
        self.deeplx_status_label.setText("状态：已填入默认地址，保存后可直接使用。")

    def detect_deeplx(self):
        endpoint = self.deeplx_endpoint_input.text().strip() or None
        self.deeplx_status_label.setText("状态：检测中...")
        QApplication.processEvents()
        try:
            detected = translate_api.detect_deeplx_endpoint(endpoint)
        except Exception as exc:
            logger.warning("DeepLX 检测失败: %s", exc)
            self.deeplx_status_label.setText(f"状态：检测失败，{exc}")
            QMessageBox.warning(self, "检测失败", f"未检测到可用 DeepLX 服务：\n{exc}")
            return

        self.deeplx_endpoint_input.setText(detected)
        self.deeplx_status_label.setText(f"状态：已检测到可用服务 {detected}")
        QMessageBox.information(self, "检测成功", f"已检测到 DeepLX 服务：\n{detected}")


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("图片翻译工具")
        self.resize(620, 420)

        self.settings = QSettings("MyApp", "ImageTranslator")
        self.config_manager = ConfigManager()
        self.image_paths = []
        self.worker = None
        self.capture_worker = None
        self.selection_overlay = None
        self.preview_window = None
        self._pending_capture_rect = None
        self._capture_result_rect = None
        self._capture_metadata = None
        self.hotkey_manager = GlobalHotkeyManager(self)

        self.init_ui()
        self.update_current_display()
        self._init_hotkey()
        logger.info("主窗口初始化完成")

    def init_ui(self):
        """初始化界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        self.current_label = QLabel()
        self.current_label.setStyleSheet("font-weight: bold; padding: 5px;")
        layout.addWidget(self.current_label)

        button_layout = QHBoxLayout()
        self.load_btn = QPushButton("📁 加载图片")
        self.capture_btn = QPushButton("🖼️ 截图翻译")
        self.process_btn = QPushButton("🚀 批量处理")
        self.settings_btn = QPushButton("⚙️ 打开设置")
        self.clear_btn = QPushButton("🗑️ 清除日志")

        self.process_btn.setEnabled(False)
        self.settings_btn.clicked.connect(self.open_settings)
        self.capture_btn.clicked.connect(self.start_screenshot_translation)
        self.load_btn.clicked.connect(self.load_images)
        self.process_btn.clicked.connect(self.process_images)
        self.clear_btn.clicked.connect(self.clear_log)

        button_layout.addWidget(self.load_btn)
        button_layout.addWidget(self.capture_btn)
        button_layout.addWidget(self.process_btn)
        button_layout.addWidget(self.settings_btn)
        button_layout.addWidget(self.clear_btn)
        layout.addLayout(button_layout)

        self.selection_label = QLabel("当前未选择图片")
        self.selection_label.setStyleSheet("padding: 3px 5px; color: #555;")
        layout.addWidget(self.selection_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        layout.addWidget(QLabel("📝 操作日志:"))
        self.result_display = QTextEdit()
        self.result_display.setReadOnly(True)
        layout.addWidget(self.result_display)

        self.statusBar().showMessage("就绪")

    def _init_hotkey(self):
        """初始化全局热键。"""
        if sys.platform != "win32":
            logger.info("当前平台不是 Windows，跳过全局热键注册")
            return

        self.hotkey_manager.hotkey_triggered.connect(self._handle_hotkey_triggered)
        registered_label = self.hotkey_manager.register()
        if registered_label:
            if registered_label == self.hotkey_manager.default_hotkey_label():
                self.result_display.append(f"⌨️ 已启用全局热键: {registered_label}")
            else:
                self.result_display.append(
                    f"⌨️ 默认热键 {self.hotkey_manager.default_hotkey_label()} 被占用，已回退到: {registered_label}"
                )
        else:
            self.result_display.append("⚠️ 所有候选全局热键都注册失败，仍可通过按钮使用截图翻译")

    def _handle_hotkey_triggered(self):
        """响应全局热键。"""
        if self.isHidden() and self.preview_window is not None and self.preview_window.isVisible():
            logger.info("覆盖窗口显示中，忽略新的截图热键")
            return
        logger.info("收到全局热键，准备进入截图翻译")
        self.start_screenshot_translation()

    def update_current_display(self):
        """更新当前设置显示"""
        config = self.config_manager.to_dict()
        target_lang = config.get("translate_language", "未设置")
        ocr_provider = config.get("ocr_provider", "baidu")
        translation_provider = config.get("translation_provider", "deepseek")
        ocr_label = translate_api.OCR_PROVIDER_LABELS.get(ocr_provider, ocr_provider)
        translation_label = translate_api.TRANSLATION_PROVIDER_LABELS.get(
            translation_provider,
            translation_provider,
        )

        missing = []
        if ocr_provider == "baidu":
            if not config.get("baidu_api_key"):
                missing.append("百度 OCR API Key")
            if not config.get("baidu_secret_key"):
                missing.append("百度 OCR Secret Key")

        if translation_provider == "deepseek":
            if not config.get("deepseek_api_key"):
                missing.append("DeepSeek API Key")
            status = "✅ 已配置" if not missing else "⚠️ 未完整配置"
        elif translation_provider == "baidu":
            if not config.get("baidu_translate_appid"):
                missing.append("百度翻译 APP ID")
            if not config.get("baidu_translate_appkey"):
                missing.append("百度翻译密钥")
            status = "✅ 已配置" if not missing else "⚠️ 未完整配置"
        elif translation_provider == "deeplx":
            if missing:
                status = "⚠️ 未完整配置"
            elif config.get("deeplx_endpoint"):
                status = "✅ 已配置"
            else:
                status = "🟡 待检测"
        else:
            status = "⚠️ 未完整配置"

        self.current_label.setText(
            f"目标语言: {target_lang}  |  OCR: {ocr_label}  |  翻译: {translation_label}  |  状态: {status}"
        )

    def update_selection_display(self):
        """更新已选图片显示"""
        count = len(self.image_paths)
        if count == 0:
            self.selection_label.setText("当前未选择图片")
            self.process_btn.setEnabled(False)
            return

        preview_names = ", ".join(Path(path).name for path in self.image_paths[:3])
        if count > 3:
            preview_names += f" 等 {count} 张"
        self.selection_label.setText(f"已选择 {count} 张图片: {preview_names}")
        self.process_btn.setEnabled(True)

    def _set_controls_enabled(self, enabled):
        self.load_btn.setEnabled(enabled)
        self.capture_btn.setEnabled(enabled)
        self.process_btn.setEnabled(enabled and bool(self.image_paths))
        self.settings_btn.setEnabled(enabled)
        self.clear_btn.setEnabled(enabled)

    def ensure_runtime_config_ready(self):
        """校验当前运行配置。"""
        try:
            validated = translate_api.validate_config(self.config_manager.to_dict())
        except Exception as exc:
            logger.warning("运行前配置校验失败: %s", exc)
            reply = QMessageBox.question(
                self,
                "配置不完整",
                f"{exc}\n\n是否现在打开设置？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.open_settings()
            return None

        self.config_manager.config = dict(validated)
        return validated

    def start_screenshot_translation(self):
        """进入截图翻译模式。"""
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "提示", "批量处理正在进行中，请先等待完成。")
            return
        if self.capture_worker and self.capture_worker.isRunning():
            QMessageBox.warning(self, "提示", "截图翻译正在进行中，请稍后。")
            return
        if not self.ensure_runtime_config_ready():
            return

        self._set_controls_enabled(False)
        if self.preview_window is not None:
            self.preview_window.close()
            self.preview_window = None
        self._capture_result_rect = None
        self._capture_metadata = None
        self._pending_capture_rect = None
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, translate_api.IMAGE_STAGE_COUNT)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        self.result_display.append("🖼️ 进入截图翻译模式，拖拽选择区域，右键或 Esc 取消")
        self.statusBar().showMessage("请选择截图区域")
        logger.info("进入截图翻译模式")

        self.hide()
        self.selection_overlay = SelectionOverlay()
        self.selection_overlay.region_selected.connect(self.on_capture_region_selected)
        self.selection_overlay.canceled.connect(self.on_capture_canceled)
        self.selection_overlay.begin()

    def on_capture_canceled(self):
        """取消截图模式。"""
        logger.info("截图翻译已取消")
        self.progress_bar.setVisible(False)
        self.selection_overlay = None
        self._set_controls_enabled(True)
        self.show()
        self.raise_()
        self.activateWindow()
        self.statusBar().showMessage("截图翻译已取消", 2000)
        self.result_display.append("ℹ️ 截图翻译已取消")

    def on_capture_region_selected(self, rect):
        """记录截图选区并延迟抓取，避免把遮罩层截进去。"""
        self._pending_capture_rect = QRect(rect)
        self.result_display.append(
            f"📌 已选择区域: x={rect.x()}, y={rect.y()}, w={rect.width()}, h={rect.height()}"
        )
        logger.info("截图区域已选择: %s", rect)

        def do_capture():
            try:
                capture_rect = QRect(self._pending_capture_rect)
                image, capture_info = capture_rect_with_screen_info(capture_rect)
                self._capture_metadata = capture_info
                logger.info("截图捕获完成: %s", capture_info)
            except Exception as exc:
                logger.exception("截图捕获失败")
                self.progress_bar.setVisible(False)
                self._set_controls_enabled(True)
                self.show()
                self.raise_()
                self.activateWindow()
                QMessageBox.critical(self, "错误", f"截图失败: {exc}")
                self.result_display.append(f"❌ 截图失败: {exc}")
                self.statusBar().showMessage("截图失败", 3000)
                self._pending_capture_rect = None
                self._capture_metadata = None
                self.selection_overlay = None
                return

            self._capture_result_rect = capture_rect
            self._start_capture_worker(image, capture_rect)
            self._pending_capture_rect = None
            self.selection_overlay = None

        QTimer.singleShot(80, do_capture)

    def _start_capture_worker(self, image, rect):
        """启动截图翻译线程。"""
        self.capture_worker = ScreenshotTranslationWorker(image, self.config_manager, image_name="截图")
        self.capture_worker.overall_progress.connect(self.on_overall_progress)
        self.capture_worker.finished.connect(self.on_capture_finished)
        self.capture_worker.error.connect(self.on_capture_error)
        self.result_display.append("⏳ 正在识别并翻译截图...")
        self.statusBar().showMessage("处理中...")
        self.capture_worker.start()
        logger.info("截图翻译线程已启动: rect=%s", rect)

    def on_capture_finished(self, result):
        """截图翻译完成。"""
        self.progress_bar.setVisible(False)
        self.capture_worker = None

        if not result.get("success"):
            self._set_controls_enabled(True)
            self.show()
            self.raise_()
            self.activateWindow()
            self.result_display.append(f"❌ 截图翻译失败: {result.get('error', '未知错误')}")
            QMessageBox.critical(self, "错误", f"截图翻译失败: {result.get('error', '未知错误')}")
            self.statusBar().showMessage("截图翻译失败", 3000)
            logger.error("截图翻译失败: %s", result.get("error"))
            return

        image_rect = self._capture_result_rect or QRect(100, 100, 800, 600)
        try:
            pixmap = pil_to_qpixmap(self._build_overlay_image(result["output_path"], image_rect))
        except Exception:
            logger.exception("构建覆盖层图片失败")
            self.result_display.append("❌ 结果图片加载失败")
            self._set_controls_enabled(True)
            self.show()
            self.raise_()
            self.activateWindow()
            QMessageBox.warning(self, "警告", "结果图片加载失败")
            return

        self._set_controls_enabled(True)
        self.preview_window = OverlayPreviewWindow(pixmap, image_rect)
        self.preview_window.overlay_closed.connect(self.on_preview_closed)
        self.preview_window.show()
        self.preview_window.raise_()
        self.preview_window.activateWindow()

        self.result_display.append(f"✅ 截图翻译完成: {result['output_path']}")
        self.result_display.append(f"📝 文本已保存: {result['text_output_path']}")
        if self._capture_metadata:
            self.result_display.append(
                "ℹ️ 截图信息: "
                f"screen={self._capture_metadata['screen_name']}, "
                f"dpr={self._capture_metadata['device_pixel_ratio']}, "
                f"image={self._capture_metadata['image_size'][0]}x{self._capture_metadata['image_size'][1]}"
            )
        self.statusBar().showMessage("截图翻译完成", 3000)
        logger.info("截图翻译完成: output=%s", result["output_path"])

    def on_capture_error(self, error_msg):
        """截图翻译线程错误。"""
        self.progress_bar.setVisible(False)
        self.capture_worker = None
        self._set_controls_enabled(True)
        self.show()
        self.raise_()
        self.activateWindow()
        QMessageBox.critical(self, "错误", f"截图翻译失败: {error_msg}")
        self.result_display.append(f"❌ 截图翻译失败: {error_msg}")
        self.statusBar().showMessage("截图翻译失败", 3000)
        logger.error("截图翻译错误信号: %s", error_msg)

    def _build_overlay_image(self, image_path, rect):
        """构建与选区尺寸一致的覆盖层图片。"""
        from PIL import Image

        image = Image.open(image_path).convert("RGBA")
        target_size = (max(1, rect.width()), max(1, rect.height()))
        if image.size != target_size:
            logger.warning("译后图片尺寸与选区不一致，执行重采样: image=%s target=%s", image.size, target_size)
            image = image.resize(target_size, Image.Resampling.LANCZOS)
        return image

    def on_preview_closed(self):
        """覆盖层关闭后恢复主窗口。"""
        logger.info("译文覆盖层已关闭，恢复主窗口")
        if self.preview_window is not None:
            self.preview_window.deleteLater()
            self.preview_window = None
        self._capture_result_rect = None
        self._capture_metadata = None
        self.show()
        self.raise_()
        self.activateWindow()
        self.statusBar().showMessage("已关闭截图覆盖层", 2000)
        self.result_display.append("ℹ️ 已关闭截图覆盖层")

    def open_settings(self):
        """打开设置对话框"""
        logger.info("打开设置对话框")
        dialog = SettingsDialog(self.config_manager, self)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                new_values = translate_api.normalize_config(dialog.get_values())
            except Exception as exc:
                QMessageBox.warning(self, "配置无效", f"设置未保存：\n{exc}")
                self.result_display.append(f"⚠️ 设置未保存: {exc}")
                logger.warning("设置保存被拒绝: %s", exc)
                return

            missing = []
            if new_values.get("ocr_provider") == "baidu":
                if not new_values.get("baidu_api_key"):
                    missing.append("百度 OCR API Key")
                if not new_values.get("baidu_secret_key"):
                    missing.append("百度 OCR Secret Key")

            if new_values.get("translation_provider") == "deepseek":
                if not new_values.get("deepseek_api_key"):
                    missing.append("DeepSeek API Key")
            elif new_values.get("translation_provider") == "baidu":
                if not new_values.get("baidu_translate_appid"):
                    missing.append("百度翻译 APP ID")
                if not new_values.get("baidu_translate_appkey"):
                    missing.append("百度翻译密钥")
                if (
                    new_values.get("baidu_translate_appid")
                    and new_values.get("baidu_translate_appid") == new_values.get("baidu_api_key")
                ):
                    missing.append("百度翻译 APP ID 不能填写为百度 OCR API Key")
                if (
                    new_values.get("baidu_translate_appkey")
                    and new_values.get("baidu_translate_appkey") == new_values.get("baidu_secret_key")
                ):
                    missing.append("百度翻译密钥不能填写为百度 OCR Secret Key")

            if missing:
                message = "缺少必要配置：\n" + "\n".join(missing)
                QMessageBox.warning(self, "配置不完整", message)
                self.result_display.append(f"⚠️ 设置未保存: {', '.join(missing)}")
                logger.warning("设置保存被拒绝，缺少字段: %s", ", ".join(missing))
                return

            self.config_manager.save(new_values)
            self.update_current_display()
            self.result_display.append("✅ 设置已保存")
            self.statusBar().showMessage("设置已保存", 2000)
            logger.info("设置已更新")

    def load_images(self):
        """加载多个图片文件"""
        last_path = self.settings.value("last_image_path", "")

        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择图片文件",
            last_path,
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif)",
        )

        if not file_paths:
            logger.info("用户取消了图片选择")
            return

        valid_files = []
        invalid_messages = []

        for file_path in file_paths:
            if not os.path.exists(file_path):
                invalid_messages.append(f"{Path(file_path).name}: 文件不存在")
                continue

            file_size = os.path.getsize(file_path)
            if file_size > 50 * 1024 * 1024:
                invalid_messages.append(f"{Path(file_path).name}: 文件过大（超过50MB）")
                continue

            valid_files.append(file_path)

        if not valid_files:
            logger.warning("选择的图片均无效，数量=%s", len(file_paths))
            QMessageBox.warning(self, "错误", "没有可处理的图片文件")
            return

        self.image_paths = valid_files
        self.settings.setValue("last_image_path", os.path.dirname(valid_files[0]))
        self.update_selection_display()
        logger.info(
            "已加载图片，有效=%s，无效=%s",
            len(valid_files),
            len(invalid_messages),
        )

        self.result_display.append(f"✅ 已加载 {len(valid_files)} 张图片")
        for file_path in valid_files[:5]:
            file_size = os.path.getsize(file_path) / 1024
            self.result_display.append(f"   - {Path(file_path).name} ({file_size:.1f}KB)")
        if len(valid_files) > 5:
            self.result_display.append(f"   - ... 还有 {len(valid_files) - 5} 张")

        for message in invalid_messages:
            self.result_display.append(f"⚠️ {message}")

        self.statusBar().showMessage(f"已加载 {len(valid_files)} 张图片", 2000)

    def process_images(self):
        """批量处理图片"""
        if not self.image_paths:
            logger.warning("未选择图片时尝试开始处理")
            QMessageBox.warning(self, "警告", "请先加载图片")
            return

        if not self.ensure_runtime_config_ready():
            return

        self.process_btn.setEnabled(False)
        self.load_btn.setEnabled(False)
        self.settings_btn.setEnabled(False)

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(self.image_paths) * translate_api.IMAGE_STAGE_COUNT)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        self.result_display.append(f"⏳ 开始批量处理 {len(self.image_paths)} 张图片...")
        self.statusBar().showMessage("批处理中...")
        logger.info("UI 已发起批量处理，图片数量=%s", len(self.image_paths))

        self.worker = BatchTranslationWorker(self.image_paths, self.config_manager)
        self.worker.progress.connect(self.on_progress)
        self.worker.overall_progress.connect(self.on_overall_progress)
        self.worker.item_finished.connect(self.on_item_finished)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_overall_progress(self, current, total, message):
        """更新确定进度条。"""
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"%p% ({current}/{total})")
        self.statusBar().showMessage(message)
        logger.info("总体进度: %s/%s %s", current, total, message)

    def on_progress(self, message):
        """处理进度更新"""
        self.result_display.append(f"📌 {message}")
        logger.info("进度更新: %s", message)

    def on_item_finished(self, result):
        """处理单个图片完成事件"""
        image_name = Path(result["image_path"]).name
        if result["success"]:
            self.result_display.append(
                f"✅ {image_name} 处理完成，用时 {result['elapsed_seconds']} 秒，输出: {result['output_path']}"
            )
            logger.info(
                "单张图片处理完成: %s, output=%s, elapsed=%ss",
                image_name,
                result["output_path"],
                result["elapsed_seconds"],
            )
        else:
            self.result_display.append(f"❌ {image_name} 处理失败: {result['error']}")
            logger.error("单张图片处理失败: %s, error=%s", image_name, result["error"])

    def on_finished(self, results):
        """处理全部完成"""
        self.progress_bar.setVisible(False)

        success_count = sum(1 for item in results if item.get("success"))
        fail_count = len(results) - success_count
        self.result_display.append(
            f"🏁 批量处理完成: 成功 {success_count} 张，失败 {fail_count} 张"
        )
        self.statusBar().showMessage("批量处理完成", 3000)
        logger.info("批量处理完成: success=%s, fail=%s", success_count, fail_count)

        self._set_controls_enabled(True)
        self.worker = None

        if success_count > 0:
            reply = QMessageBox.question(
                self,
                "完成",
                "批量处理完成，是否打开结果文件夹？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                result_dir = translate_api.get_result_dir()
                if result_dir.exists() and sys.platform == "win32":
                    os.startfile(str(result_dir))

    def on_error(self, error_msg):
        """处理错误"""
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "错误", f"处理失败: {error_msg}")
        self.result_display.append(f"❌ 批量处理失败: {error_msg}")
        self.statusBar().showMessage("处理失败", 3000)
        logger.error("批量处理错误信号: %s", error_msg)

        self._set_controls_enabled(True)
        self.worker = None

    def clear_log(self):
        """清除日志"""
        self.result_display.clear()
        self.result_display.append("日志已清除")
        self.statusBar().showMessage("日志已清除", 2000)
        logger.info("界面日志已清除")

    def closeEvent(self, event):
        """关闭事件 - 清理资源"""
        if self.worker and self.worker.isRunning():
            logger.warning("应用关闭时仍有批量任务在运行")
            reply = QMessageBox.question(
                self,
                "确认退出",
                "正在批量处理中，确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.worker.request_cancel()
                self.worker.wait()
                logger.info("用户确认退出，已等待工作线程结束")
                event.accept()
            else:
                logger.info("用户取消退出")
                event.ignore()
            return

        if self.capture_worker and self.capture_worker.isRunning():
            logger.warning("应用关闭时仍有截图任务在运行")
            reply = QMessageBox.question(
                self,
                "确认退出",
                "正在截图翻译中，确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.capture_worker.wait()
                event.accept()
            else:
                event.ignore()
            return

        self.hotkey_manager.unregister()
        logger.info("应用窗口正常关闭")
        event.accept()
