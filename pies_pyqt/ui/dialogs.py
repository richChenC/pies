from __future__ import annotations

from typing import Callable, Iterable

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QHeaderView,
    QAbstractItemView,
    QFrame,
)


def _apply_dialog_style(dialog: QDialog) -> None:
    dialog.setStyleSheet(
        """
        QDialog { background: #F7F9FC; }
        QLabel[dialogTitle="true"] { color: #174A7E; font-size: 18px; font-weight: 700; }
    QTextEdit, QTableWidget {
        background: #FFFFFF;
        border: none;
        border-radius: 0px;
        color: #1F2937;
        }
        QHeaderView::section {
            background: #FFFFFF;
            color: #1F2937;
            padding: 7px;
            border: none;
            border-bottom: 1px solid #D8E3F0;
            font-weight: 700;
        }
        QTableWidget::item { border: none; }
        QTableWidget::item:focus { border: none; outline: none; }
        QAbstractItemView { outline: none; }
        QPushButton {
            border: 1px solid #CBD5E1;
            border-radius: 7px;
            padding: 7px 14px;
            background: #F8FAFC;
            color: #344054;
            font-weight: 600;
        }
        QPushButton:hover { background: #EEF4FB; }
        QPushButton[primary="true"] {
            background: #3F78C5;
            color: #FFFFFF;
            border: 1px solid #3F78C5;
        }
        QPushButton[primary="true"]:hover { background: #2F68B5; }
        """
    )



def show_text_dialog(parent, title: str, text: str, width: int = 1000, height: int = 680) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(width, height)
    dialog.setMinimumSize(800, 500)
    _apply_dialog_style(dialog)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(14)

    # 改进的标题
    title_label = QLabel(title, dialog)
    title_label.setProperty("dialogTitle", True)
    title_font = title_label.font()
    title_font.setPointSize(16)
    title_font.setBold(True)
    title_label.setFont(title_font)
    title_label.setStyleSheet("color: #174A7E; background: transparent;")
    layout.addWidget(title_label)

    editor = QTextEdit(dialog)
    editor.setReadOnly(True)
    editor.setPlainText(text)
    editor.setStyleSheet("""
        QTextEdit {
            background: #FFFFFF;
            border: 1px solid #E5E7EB;
            border-radius: 4px;
            color: #333333;
            padding: 12px;
            font-family: "Microsoft YaHei", "Consolas", monospace;
            font-size: 11px;
        }
    """)
    layout.addWidget(editor, 1)

    # 底部按钮区
    btn_layout = QHBoxLayout()
    btn_layout.addStretch(1)
    close_button = QPushButton("关闭", dialog)
    close_button.setProperty("primary", True)
    close_button.setMinimumHeight(36)
    close_button.setMinimumWidth(100)
    close_button.setStyleSheet("""
        QPushButton {
            background: #3F78C5;
            color: #FFFFFF;
            border: none;
            border-radius: 4px;
            padding: 8px 20px;
            font-weight: bold;
            font-size: 12px;
        }
        QPushButton:hover { background: #2F68B5; }
        QPushButton:pressed { background: #1F58A5; }
    """)
    close_button.clicked.connect(dialog.accept)
    btn_layout.addWidget(close_button)
    layout.addLayout(btn_layout)
    
    dialog.exec_()


def show_table_dialog(
    parent,
    title: str,
    headers: list[str],
    rows: Iterable[dict[str, object]],
    *,
    summary_text: str | None = None,
    export_label: str | None = None,
    on_export: Callable[[], None] | None = None,
    width: int = 1200,
    height: int = 750,
) -> None:
    data = list(rows)
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(width, height)
    dialog.setMinimumSize(900, 550)
    _apply_dialog_style(dialog)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(14)

    # 改进的标题区域
    title_label = QLabel(title, dialog)
    title_label.setProperty("dialogTitle", True)
    title_font = title_label.font()
    title_font.setPointSize(15)
    title_font.setBold(True)
    title_label.setFont(title_font)
    title_label.setStyleSheet("color: #174A7E; background: transparent;")
    layout.addWidget(title_label)

    # 摘要信息
    if summary_text:
        summary_label = QLabel(summary_text)
        summary_label.setStyleSheet("color: #4A5A6A; font-size: 12px; background: transparent;")
        summary_label.setWordWrap(True)
        layout.addWidget(summary_label)

    # 改进的表格样式
    table = QTableWidget(len(data), len(headers), dialog)
    table.setHorizontalHeaderLabels(headers)
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setFocusPolicy(Qt.NoFocus)
    table.setShowGrid(False)
    table.setFrameShape(QFrame.NoFrame)
    table.setStyleSheet("""
        QTableWidget { 
            background: #FFFFFF; 
            border: 1px solid #E5E7EB; 
            border-radius: 4px;
        }
        QHeaderView::section { 
            background: #F3F4F6; 
            color: #1F2937; 
            padding: 10px; 
            border: none; 
            border-bottom: 2px solid #D1D5DB;
            font-weight: bold;
            font-size: 12px;
        }
        QTableWidget::item { padding: 8px; border: none; }
        QTableWidget::item:selected { background: #DBE5F7; }
    """)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.verticalHeader().setVisible(False)

    for row_index, row in enumerate(data):
        for col_index, header in enumerate(headers):
            value = "" if row.get(header) is None else str(row.get(header))
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignCenter)
            if row_index % 2 == 0:
                item.setBackground(QColor("#FFFFFF"))
            else:
                item.setBackground(QColor("#F8FAFC"))
            table.setItem(row_index, col_index, item)

    layout.addWidget(table, 1)

    # 底部信息和按钮区
    footer_layout = QHBoxLayout()
    footer_layout.addWidget(QLabel(f"共 {len(data)} 条记录", 
        styleSheet="color: #6B7280; font-size: 12px; font-weight: 500;"))
    footer_layout.addStretch(1)
    
    if on_export and export_label:
        export_button = QPushButton(export_label, dialog)
        export_button.setProperty("primary", True)
        export_button.setMinimumHeight(34)
        export_button.setMinimumWidth(100)
        export_button.setStyleSheet("""
            QPushButton {
                background: #3F78C5;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background: #2F68B5; }
        """)
        export_button.clicked.connect(on_export)
        footer_layout.addWidget(export_button)
    
    close_button = QPushButton("关闭", dialog)
    close_button.setMinimumHeight(34)
    close_button.setMinimumWidth(100)
    close_button.setStyleSheet("""
        QPushButton {
            background: #E5E7EB;
            color: #374151;
            border: 1px solid #D1D5DB;
            border-radius: 4px;
            padding: 8px 16px;
            font-weight: bold;
            font-size: 12px;
        }
        QPushButton:hover { background: #D1D5DB; }
    """)
    close_button.clicked.connect(dialog.accept)
    footer_layout.addWidget(close_button)
    layout.addLayout(footer_layout)

    dialog.exec_()
