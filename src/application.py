import os
import sys
from pathlib import Path

import translate_api
from dotenv import dotenv_values
from PySide6.QtCore import QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ConfigManager:
    """统一的配置管理器"""

    def __init__(self, config_path=None):
        self.config_path = Path(config_path) if config_path else translate_api.get_config_path()
        self.config = {}
        self.load()

    def load(self):
        """加载配置"""
        if self.config_path.exists():
            self.config = dict(dotenv_values(self.config_path))
        else:
            self.config = self._get_default_config()

    def _get_default_config(self):
        """获取默认配置"""
        return {
            "baidu_api_key": "",
            "baidu_secret_key": "",
            "deepseek_api_key": "",
            "translate_language": "中文",
        }

    def save(self, new_config=None):
        """保存配置"""
        if new_config:
            self.config.update(new_config)

        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.config_path, "w", encoding="utf-8") as file:
            file.write("# API密钥配置 请勿分享此文件!\n")
            for key, value in self.config.items():
                file.write(f"{key}={value}\n")

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

    return payloads


class BatchTranslationWorker(QThread):
    """批量翻译工作线程"""

    finished = Signal(list)
    error = Signal(str)
    progress = Signal(str)
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

    def run(self):
        """执行批量任务"""
        try:
            translate_api.validate_config(self.config)

            payloads = build_batch_payloads(self.image_paths, self.config)

            total = len(payloads)
            if total == 0:
                self.finished.emit([])
                return

            self.progress.emit(f"开始批量处理，共 {total} 张图片，按顺序逐张处理")

            completed = 0
            for payload in payloads:
                if self._cancel_requested:
                    break

                image_path = payload["image_path"]
                try:
                    result = run_single_image_task(payload)
                except Exception as exc:
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

            if self._cancel_requested:
                self.progress.emit("批量处理已取消")

            self.finished.emit(self._results)

        except Exception as exc:
            self.error.emit(str(exc))


class SettingsDialog(QDialog):
    """设置对话框"""

    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.setWindowTitle("参数设置")
        self.resize(400, 300)

        layout = QVBoxLayout(self)
        self.inputs = {}
        fields = [
            ("baidu_api_key", "百度OCR API Key", False),
            ("baidu_secret_key", "百度OCR Secret Key", True),
            ("deepseek_api_key", "DeepSeek API Key", True),
            ("translate_language", "目标语言", False),
        ]

        for key, label, is_password in fields:
            layout.addWidget(QLabel(label + ":"))
            input_widget = QLineEdit()
            if is_password:
                input_widget.setEchoMode(QLineEdit.Password)
            input_widget.setText(self.config_manager.get(key, ""))
            layout.addWidget(input_widget)
            self.inputs[key] = input_widget

        info_label = QLabel("提示: API密钥将保存在本地配置文件中")
        info_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(info_label)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_values(self):
        """获取输入值"""
        return {key: widget.text().strip() for key, widget in self.inputs.items()}


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

        self.init_ui()
        self.update_current_display()

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
        self.process_btn = QPushButton("🚀 批量处理")
        self.settings_btn = QPushButton("⚙️ 打开设置")
        self.clear_btn = QPushButton("🗑️ 清除日志")

        self.process_btn.setEnabled(False)
        self.settings_btn.clicked.connect(self.open_settings)
        self.load_btn.clicked.connect(self.load_images)
        self.process_btn.clicked.connect(self.process_images)
        self.clear_btn.clicked.connect(self.clear_log)

        button_layout.addWidget(self.load_btn)
        button_layout.addWidget(self.process_btn)
        button_layout.addWidget(self.settings_btn)
        button_layout.addWidget(self.clear_btn)
        layout.addLayout(button_layout)

        self.selection_label = QLabel("当前未选择图片")
        self.selection_label.setStyleSheet("padding: 3px 5px; color: #555;")
        layout.addWidget(self.selection_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        layout.addWidget(QLabel("📝 操作日志:"))
        self.result_display = QTextEdit()
        self.result_display.setReadOnly(True)
        layout.addWidget(self.result_display)

        self.statusBar().showMessage("就绪")

    def update_current_display(self):
        """更新当前设置显示"""
        target_lang = self.config_manager.get("translate_language", "未设置")
        has_keys = all(
            [
                self.config_manager.get("baidu_api_key"),
                self.config_manager.get("baidu_secret_key"),
                self.config_manager.get("deepseek_api_key"),
            ]
        )

        status = "✅ 已配置" if has_keys else "⚠️ 未完整配置"
        self.current_label.setText(f"目标语言: {target_lang}  |  API状态: {status}")

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

    def open_settings(self):
        """打开设置对话框"""
        dialog = SettingsDialog(self.config_manager, self)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_values = dialog.get_values()
            self.config_manager.save(new_values)
            self.update_current_display()
            self.result_display.append("✅ 设置已保存")
            self.statusBar().showMessage("设置已保存", 2000)

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
            QMessageBox.warning(self, "错误", "没有可处理的图片文件")
            return

        self.image_paths = valid_files
        self.settings.setValue("last_image_path", os.path.dirname(valid_files[0]))
        self.update_selection_display()

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
            QMessageBox.warning(self, "警告", "请先加载图片")
            return

        if not all(
            [
                self.config_manager.get("baidu_api_key"),
                self.config_manager.get("baidu_secret_key"),
                self.config_manager.get("deepseek_api_key"),
            ]
        ):
            reply = QMessageBox.question(
                self,
                "配置不完整",
                "API密钥未完整配置，是否现在设置？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.open_settings()
            return

        self.process_btn.setEnabled(False)
        self.load_btn.setEnabled(False)
        self.settings_btn.setEnabled(False)

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.result_display.append(f"⏳ 开始批量处理 {len(self.image_paths)} 张图片...")
        self.statusBar().showMessage("批处理中...")

        self.worker = BatchTranslationWorker(self.image_paths, self.config_manager)
        self.worker.progress.connect(self.on_progress)
        self.worker.item_finished.connect(self.on_item_finished)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_progress(self, message):
        """处理进度更新"""
        self.result_display.append(f"📌 {message}")

    def on_item_finished(self, result):
        """处理单个图片完成事件"""
        image_name = Path(result["image_path"]).name
        if result["success"]:
            self.result_display.append(
                f"✅ {image_name} 处理完成，用时 {result['elapsed_seconds']} 秒，输出: {result['output_path']}"
            )
        else:
            self.result_display.append(f"❌ {image_name} 处理失败: {result['error']}")

    def on_finished(self, results):
        """处理全部完成"""
        self.progress_bar.setVisible(False)

        success_count = sum(1 for item in results if item.get("success"))
        fail_count = len(results) - success_count
        self.result_display.append(
            f"🏁 批量处理完成: 成功 {success_count} 张，失败 {fail_count} 张"
        )
        self.statusBar().showMessage("批量处理完成", 3000)

        self.process_btn.setEnabled(True)
        self.load_btn.setEnabled(True)
        self.settings_btn.setEnabled(True)
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

        self.process_btn.setEnabled(True)
        self.load_btn.setEnabled(True)
        self.settings_btn.setEnabled(True)
        self.worker = None

    def clear_log(self):
        """清除日志"""
        self.result_display.clear()
        self.result_display.append("日志已清除")
        self.statusBar().showMessage("日志已清除", 2000)

    def closeEvent(self, event):
        """关闭事件 - 清理资源"""
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "确认退出",
                "正在批量处理中，确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.worker.request_cancel()
                self.worker.wait()
                event.accept()
            else:
                event.ignore()
            return

        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
