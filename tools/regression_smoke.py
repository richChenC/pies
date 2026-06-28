from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib

matplotlib.use("Agg")

from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox

from pies_pyqt.core.models import ProbeRecord
from pies_pyqt.ui.main_window import MainWindow


def _build_probe_statistics():
    statistics = {}
    sample = [
        ("BOBBIN", "CF155NAF32WB-", [("72114602", 28.4), ("10223693", 27.6), ("10223534", 24.6)]),
        ("BOBBIN", "CF145PAF32WB-", [("10236557", 14.4), ("10236558", 11.7), ("12204198", 11.7)]),
        ("MRPC", "CRPS/DH3/MR/16.87", [("121865", 12.1), ("9231574", 12.1), ("9231540", 8.3)]),
    ]
    for probe_type, model, rows in sample:
        for idx, (probe_sn, value) in enumerate(rows, 1):
            key = f"{probe_type}_{model}_{idx}"
            statistics[key] = SimpleNamespace(
                probe_type=probe_type,
                model=model,
                probe_sn=probe_sn,
                total_uses=int(round(value)),
                total_duration_minutes=float(value) * 60.0,
                unique_tube_count=int(round(value * 10)),
                records=[],
            )
    return statistics


def _build_batch_statistics():
    statistics = {}
    sample = [
        ("BOBBIN", "CF145PAF32WB-", "2020-12", 602),
        ("BOBBIN", "CF145PAF32WB-", "2022-12", 291),
        ("BOBBIN", "CF145PAF32WB-", "2023-10", 324),
        ("BOBBIN", "CF15SNAF32WB-", "2020-02", 145),
        ("BOBBIN", "CF15SNAF32WB-", "2021-07", 1102),
        ("BOBBIN", "CF15SNAF32WB-", "2022-10", 746),
        ("MRPC", "CRPS/DH3/MR/16.87", "2021-01", 282),
        ("MRPC", "CRPS/DH3/MR/16.87", "2023-09", 242),
    ]
    for idx, (probe_type, model, batch, tube_count) in enumerate(sample, 1):
        year, month = batch.split("-")
        probe_sn = f"{int(month)}{int(year[2:]):02d}{idx:04d}"
        statistics[f"batch_{idx}"] = SimpleNamespace(
            probe_type=probe_type,
            model=model,
            probe_sn=probe_sn,
            unique_tube_count=tube_count,
            records=[],
        )
    return statistics


def _build_records():
    return [
        ProbeRecord(
            probe_sn="P1",
            probe_type="BOBBIN",
            probe_type_raw="BOBBIN",
            start_time=None,
            end_time=None,
            tube_number=10,
            operator="A",
            data_group="G1",
            model="M1",
            outage="O1",
            sg_id="SG1",
            warnings=[],
        ),
        ProbeRecord(
            probe_sn="P2",
            probe_type="MRPC",
            probe_type_raw="MRPC",
            start_time=None,
            end_time=None,
            tube_number=20,
            operator="B",
            data_group="G2",
            model="M2",
            outage="O1",
            sg_id="SG2",
            warnings=[],
        ),
    ]


def _build_many_records():
    records = []
    for idx in range(1, 241):
        probe_type = "BOBBIN" if idx % 2 else "MRPC"
        model = "M1" if idx % 3 else "M2"
        records.append(
            ProbeRecord(
                probe_sn=f"P{idx:03d}",
                probe_type=probe_type,
                probe_type_raw=probe_type,
                start_time=None,
                end_time=None,
                tube_number=(idx % 50) + 1,
                operator=f"O{idx % 7}",
                data_group=f"G{idx % 11}",
                model=model,
                outage=f"OT{idx % 5}",
                sg_id=f"SG{idx % 4}",
                warnings=[],
            )
        )
    return records


def run() -> int:
    app = QApplication([])
    window = MainWindow()

    probe_statistics = _build_probe_statistics()
    fig = window.visualizer.create_tube_count_chart(probe_statistics, figure_width=12, figure_height=8)
    assert fig is not None, "tube count figure should exist"

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "chart_export.png"
        paths = window._save_chart_outputs(fig, out)
        assert len(paths) == 4, f"expected 4 files, got {len(paths)}"
        assert any("探头类型_BOBBIN_探头型号_CF155NAF32WB-" in p.name for p in paths), "missing precise export name"

    batch_statistics = _build_batch_statistics()
    assert window.batch_lifetime_analyzer.load_data_from_statistics(batch_statistics, include_excluded_models=True)
    batch_fig = window.batch_lifetime_analyzer.create_batch_lifetime_chart(
        figsize=(12, 8),
        excluded_probe_count=0,
        show_excluded_note=True,
    )
    assert batch_fig is not None, "batch lifetime figure should exist"

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "batch_lifetime.png"
        paths = window._save_chart_outputs(batch_fig, out)
        assert len(paths) == 4, f"expected 4 files, got {len(paths)}"
        stems = [p.stem for p in paths[1:]]
        assert len(set(stems)) == 3, "batch lifetime sub-exports should be distinct"
        assert all("批次平均寿命_" in p.name for p in paths[1:]), "batch lifetime sub-export name should be precise"

    records = _build_records()
    window.current_records = records
    window.current_statistics = {
        "f1": SimpleNamespace(
            probe_type="BOBBIN",
            model="M1",
            probe_sn="P1",
            stat_key=records[0].stat_key,
            records=[records[0]],
            unique_tube_count=10,
            total_uses=1,
            total_duration_minutes=0.0,
            longest_continuous_duration_minutes=0.0,
            detection_speed=0.0,
            first_use_time=None,
            last_use_time=None,
        ),
        "f2": SimpleNamespace(
            probe_type="MRPC",
            model="M2",
            probe_sn="P2",
            stat_key=records[1].stat_key,
            records=[records[1]],
            unique_tube_count=20,
            total_uses=1,
            total_duration_minutes=0.0,
            longest_continuous_duration_minutes=0.0,
            detection_speed=0.0,
            first_use_time=None,
            last_use_time=None,
        ),
    }
    window.summary_filter_values = {}
    window.filter_values = {}

    window._set_summary_filter("探头类型", "BOBBIN")
    assert [r.probe_sn for r in window.current_records if window._summary_record_matches_filters(r)] == ["P1"]
    window._set_summary_filter("探头类型", "MRPC")
    assert [r.probe_sn for r in window.current_records if window._summary_record_matches_filters(r)] == ["P2"]
    window._set_summary_filter("探头类型", ("BOBBIN", "MRPC"))
    assert [r.probe_sn for r in window.current_records if window._summary_record_matches_filters(r)] == ["P1", "P2"]
    window._set_summary_filter("探头型号", "M2")
    assert [r.probe_sn for r in window.current_records if window._summary_record_matches_filters(r)] == ["P2"]
    window._clear_all_filters()
    assert len([r for r in window.current_records if window._summary_record_matches_filters(r)]) == 2

    # filtered stats cache smoke
    rebuild_counter = {"count": 0}
    original_rebuild = window._rebuild_statistics_from_records
    def _wrapped_rebuild(records_arg):
        rebuild_counter["count"] += 1
        return original_rebuild(records_arg)
    window._rebuild_statistics_from_records = _wrapped_rebuild
    try:
        window._set_summary_filter("探头类型", "MRPC")
        window._get_chart_source_data()
        window._get_metric_source_data()
        assert rebuild_counter["count"] == 1, f"filtered stats should be reused, got {rebuild_counter['count']}"
    finally:
        window._rebuild_statistics_from_records = original_rebuild
    window._clear_all_filters()

    window._update_summary_table(window.current_statistics)
    assert window._summary_table.rowCount() == 2

    # high-frequency chart/filter path smoke
    many_records = _build_many_records()
    many_stats = {}
    for record in many_records:
        many_stats[record.stat_key] = SimpleNamespace(
            probe_type=record.probe_type,
            model=record.model,
            probe_sn=record.probe_sn,
            stat_key=record.stat_key,
            records=[record],
            unique_tube_count=record.tube_number,
            total_uses=1,
            total_duration_minutes=0.0,
            longest_continuous_duration_minutes=0.0,
            detection_speed=0.0,
            first_use_time=None,
            last_use_time=None,
        )
    window.current_records = many_records
    window.current_statistics = many_stats
    window.show()
    app.processEvents()
    window._current_view = "chart"
    window._chart_panel.show()
    initial_token = window._chart_request_token
    for filter_value in ("BOBBIN", "MRPC", ("BOBBIN", "MRPC")):
        window._set_summary_filter("探头类型", filter_value)
        window._schedule_chart_refresh(1)
    app.processEvents()
    assert window._chart_request_token > initial_token or window._pending_chart_refresh
    window._clear_all_filters()

    window._show_software_notes()
    app.processEvents()
    first_dialog = window._modeless_dialogs.get("software_notes")
    assert first_dialog is not None
    window._show_software_notes()
    app.processEvents()
    second_dialog = window._modeless_dialogs.get("software_notes")
    assert second_dialog is not None
    assert second_dialog is not first_dialog, "dialog should be recreated so content can refresh"

    with tempfile.TemporaryDirectory() as tmp:
        source_root = Path(tmp) / "source"
        source_root.mkdir()
        window._folder_edit.setText(str(source_root))
        original_warning = QMessageBox.warning
        try:
            QMessageBox.warning = staticmethod(lambda *args, **kwargs: 0)
            assert window._ensure_output_path_allowed(source_root / "output.xlsx") is False
            assert window._ensure_output_path_allowed(Path(tmp) / "export.xlsx") is True
        finally:
            QMessageBox.warning = original_warning

    window.session_error_records = [{"探头编号": "P1", "错误信息": "测试错误"}]
    with tempfile.TemporaryDirectory() as tmp:
        target = str(Path(tmp) / "error_records.xlsx")
        original_getsave = QFileDialog.getSaveFileName
        original_info = QMessageBox.information
        original_critical = QMessageBox.critical
        original_warning = QMessageBox.warning
        try:
            QFileDialog.getSaveFileName = staticmethod(lambda *args, **kwargs: (target, ""))
            QMessageBox.information = staticmethod(lambda *args, **kwargs: 0)
            QMessageBox.critical = staticmethod(lambda *args, **kwargs: 0)
            QMessageBox.warning = staticmethod(lambda *args, **kwargs: 0)
            window._export_error_records()
            assert Path(target).exists(), "error record export file should exist"
        finally:
            QFileDialog.getSaveFileName = original_getsave
            QMessageBox.information = original_info
            QMessageBox.critical = original_critical
            QMessageBox.warning = original_warning

    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
