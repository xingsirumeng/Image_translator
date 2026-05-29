import logging
import sys
from ui.application import QApplication, MainWindow
from utils.logging_config import setup_logging


logger = logging.getLogger(__name__)


def main():
    log_file = setup_logging()
    logger.info("应用启动，日志文件: %s", log_file)
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    exit_code = app.exec()
    logger.info("应用退出，exit_code=%s", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("应用启动失败")
        raise
