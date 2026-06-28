from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib

matplotlib.use("Agg")

from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox

from pies_pyqt.constants import CHART_GROUPS
from pies_pyqt.core.analyzer import ProbeAnalyzer
from pies_pyqt.core.extractor import SummaryFileExtractor
from pies_pyqt.ui.main_window import MainWindow


REAL_FILES = [
    PROJECT_ROOT / "ExcelDate" / "Result.xlsx",
    PROJECT_ROOT / "ExcelDate" / "Result（验证）.xlsx",
]


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def collect_chart_specs():
    specs = []
    for group, options in CHART_GROUPS.items():
        for label, chart_key in options:
            specs.append((group, label, chart_key))
    return specs


def wait_for(condition, timeout: float = 8.0, interval: float = 0.05) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(interval)
    QApplication.processEvents()
    return bool(condition())


def run_single_dataset(window: MainWindow, excel_path: Path, export_root: Path) -> dict:
    extractor = SummaryFileExtractor()
    analyzer = ProbeAnalyzer()

    records = extractor.extract_probe_records(str(excel_path))
    assert_true(len(records) > 0, f"{excel_path.name}: 未提取到记录")

    analyzer.add_records(records)
    statistics = analyzer.analyze()
    assert_true(len(statistics) > 0, f"{excel_path.name}: 未生成统计结果")

    window.session_records = list(analyzer.records)
    window.session_statistics = dict(statistics)
    window.session_deduplication_info = dict(analyzer.deduplication_info or {})
    window.session_error_records = list(extractor.error_records or [])
    window._current_scope = "current"
    window._apply_active_dataset(refresh_ui=True)
    rendered = wait_for(lambda: window._current_chart_figure is not None, timeout=10.0)

    assert_true(len(window.current_records) > 0, f"{excel_path.name}: 当前记录为空")
    assert_true(len(window.current_statistics) > 0, f"{excel_path.name}: 当前统计为空")
    assert_true(rendered and window._current_chart_figure is not None, f"{excel_path.name}: 默认图表未完成首次渲染")

    filtered_probe_types = sorted(
        {
            str(getattr(record, "probe_type_raw", None) or getattr(record, "probe_type", "")).strip()
            for record in window.current_records
            if (getattr(record, "probe_type_raw", None) or getattr(record, "probe_type", ""))
        }
    )
    if filtered_probe_types:
        first_type = filtered_probe_types[0]
        window._set_summary_filter("探头类型", first_type)
        filtered_records, filtered_stats = window._get_filtered_records_and_stats()
        assert_true(len(filtered_records) > 0, f"{excel_path.name}: 首个筛选条件后无记录")
        assert_true(len(filtered_stats) > 0, f"{excel_path.name}: 首个筛选条件后无统计")
        if len(filtered_probe_types) > 1:
            second_type = filtered_probe_types[1]
            window._set_summary_filter("探头类型", second_type)
            filtered_records_2, filtered_stats_2 = window._get_filtered_records_and_stats()
            assert_true(len(filtered_records_2) > 0, f"{excel_path.name}: 切换筛选条件后无记录")
            assert_true(len(filtered_stats_2) > 0, f"{excel_path.name}: 切换筛选条件后无统计")
        window._clear_all_filters()

    exported_chart_files = []
    chart_failures = []
    for group, label, chart_key in collect_chart_specs():
        records_src, stats_src, hidden = window._get_chart_source_data()
        fig = window._create_chart_figure(
            chart_key,
            records_src,
            stats_src,
            hidden,
            window._build_export_fig_kwargs(),
        )
        if fig is None:
            chart_failures.append((group, label, chart_key, "no-data"))
            continue
        file_stem = f"{excel_path.stem}_{group}_{label}".replace("/", "_").replace("\\", "_")
        output_path = export_root / f"{file_stem}.png"
        paths = window._save_chart_outputs(fig, output_path)
        exported_chart_files.extend(paths)
        assert_true(len(paths) >= 1, f"{excel_path.name}: 图表 {label} 未导出任何文件")
        if chart_key == "生产批次平均寿命图":
            assert_true(len(paths) >= 2, f"{excel_path.name}: 批次平均寿命图未导出子图")
        window.visualizer.close_all_figures()

    filtered_rows = window._build_summary_export_rows(window.current_records)
    assert_true(len(filtered_rows) > 0, f"{excel_path.name}: 表格导出行为空")

    return {
        "file": excel_path.name,
        "records": len(window.current_records),
        "statistics": len(window.current_statistics),
        "errors": len(window.session_error_records),
        "exported_chart_files": len(exported_chart_files),
        "chart_failures": chart_failures,
    }


def run_save_all_check(window: MainWindow, save_dir: Path) -> Path:
    captured = {"info": [], "warning": []}

    original_get_dir = QFileDialog.getExistingDirectory
    original_info = QMessageBox.information
    original_warning = QMessageBox.warning

    def fake_get_dir(*args, **kwargs):
        return str(save_dir)

    def fake_info(*args, **kwargs):
        captured["info"].append((args, kwargs))
        return QMessageBox.Ok

    def fake_warning(*args, **kwargs):
        captured["warning"].append((args, kwargs))
        return QMessageBox.Ok

    QFileDialog.getExistingDirectory = fake_get_dir
    QMessageBox.information = fake_info
    QMessageBox.warning = fake_warning
    try:
        before = {p for p in save_dir.iterdir()} if save_dir.exists() else set()
        window._save_all()
        QApplication.processEvents()
        after = {p for p in save_dir.iterdir()} if save_dir.exists() else set()
    finally:
        QFileDialog.getExistingDirectory = original_get_dir
        QMessageBox.information = original_info
        QMessageBox.warning = original_warning

    new_dirs = [p for p in (after - before) if p.is_dir()]
    assert_true(new_dirs, "一键保存未生成导出目录")
    export_dir = max(new_dirs, key=lambda p: p.stat().st_mtime)
    exported_files = list(export_dir.rglob("*"))
    assert_true(any(p.suffix.lower() == ".xlsx" for p in exported_files), "一键保存未导出 Excel")
    assert_true(any(p.suffix.lower() == ".png" for p in exported_files), "一键保存未导出图表")
    return export_dir


def run_source_protection_check(window: MainWindow, source_root: Path) -> None:
    warning_calls = []
    original_warning = QMessageBox.warning

    def fake_warning(*args, **kwargs):
        warning_calls.append((args, kwargs))
        return QMessageBox.Ok

    QMessageBox.warning = fake_warning
    try:
        blocked_path = source_root / "should_not_write.xlsx"
        allowed = window._ensure_output_path_allowed(blocked_path)
    finally:
        QMessageBox.warning = original_warning

    assert_true(not allowed, "源目录写保护未生效")
    assert_true(bool(warning_calls), "源目录写保护未提示用户")
    assert_true(not blocked_path.exists(), "源目录中出现了不应写入的文件")


def main() -> int:
    for excel_path in REAL_FILES:
        assert_true(excel_path.exists(), f"缺少真实数据文件: {excel_path}")

    app = QApplication([])
    window = MainWindow()
    window.show()
    QApplication.processEvents()

    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_root = Path(tmp_dir)
        reports = []

        for excel_path in REAL_FILES:
            window._file_edit.setText(str(excel_path))
            window._folder_edit.setText(str(excel_path.parent))
            dataset_export_dir = temp_root / excel_path.stem
            dataset_export_dir.mkdir(parents=True, exist_ok=True)
            report = run_single_dataset(window, excel_path, dataset_export_dir)
            reports.append(report)
            run_source_protection_check(window, excel_path.parent)

        save_all_dir = temp_root / "save_all"
        save_all_dir.mkdir(parents=True, exist_ok=True)
        final_export_dir = run_save_all_check(window, save_all_dir)

        print("=== REAL DATA END TO END CHECK ===")
        for report in reports:
            print(
                f"{report['file']}: records={report['records']}, stats={report['statistics']}, "
                f"errors={report['errors']}, chart_exports={report['exported_chart_files']}, "
                f"chart_failures={len(report['chart_failures'])}"
            )
            for failure in report["chart_failures"]:
                print(f"  skipped: group={failure[0]} label={failure[1]} key={failure[2]} reason={failure[3]}")
        print(f"save_all_dir={final_export_dir}")

    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
