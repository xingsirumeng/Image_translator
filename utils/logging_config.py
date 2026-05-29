import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s"


def get_runtime_dir():
    """返回运行目录。源码模式下为项目根目录，打包后为可执行文件所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_log_dir():
    """返回日志目录。"""
    return get_runtime_dir() / "output" / "logs"


def _get_console_level():
    level_name = os.getenv("IMAGE_TRANSLATOR_LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_name, logging.INFO)


def _install_excepthook():
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logging.getLogger(__name__).exception(
            "捕获到未处理异常",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = handle_exception


def setup_logging():
    """初始化全局日志，输出到控制台和滚动文件。"""
    root_logger = logging.getLogger()
    if getattr(root_logger, "_image_translator_logging_ready", False):
        for handler in root_logger.handlers:
            if isinstance(handler, RotatingFileHandler):
                return Path(handler.baseFilename)
        return get_log_dir() / "app.log"

    log_dir = get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    formatter = logging.Formatter(LOG_FORMAT)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(_get_console_level())
    console_handler.setFormatter(formatter)

    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    root_logger._image_translator_logging_ready = True

    _install_excepthook()
    logging.getLogger(__name__).info("日志系统已初始化，日志文件: %s", log_file)
    return log_file
