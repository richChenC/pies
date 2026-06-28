from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

from matplotlib import rcParams
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QMessageBox

from .ui.main_window import MainWindow


def build_logger() -> logging.Logger:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "pies_pyqt.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("pies_pyqt")


def _configure_fonts(app: QApplication) -> None:
    preferred_fonts = [
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "SimHei",
        "SimSun",
        "Segoe UI",
    ]
    app.setFont(QFont(preferred_fonts[0], 9))
    rcParams["font.sans-serif"] = preferred_fonts
    rcParams["axes.unicode_minus"] = False


def main() -> int:
    logger = build_logger()
    app = QApplication(sys.argv)
    app.setApplicationName("PIES PyQt")
    app.setOrganizationName("PIES")
    _configure_fonts(app)
    # 把全局样式设置到 QApplication，确保所有子控件都能继承
    from .ui.main_window import STYLESHEET
    app.setStyleSheet(STYLESHEET)
    try:
        window = MainWindow(logger=logger)
        window.show()
        return app.exec_()
    except Exception as exc:
        logger.exception("PyQt 启动失败")
        detail = traceback.format_exc()
        QMessageBox.critical(
            None,
            "启动失败",
            f"PIES PyQt 启动失败：\n{exc}\n\n详细信息已写入日志。",
        )
        logger.error(detail)
        return 1
