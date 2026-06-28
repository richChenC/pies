from __future__ import annotations

import gc
import os
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from PyQt5.QtWidgets import QApplication

from pies_pyqt.constants import CHART_GROUPS
from pies_pyqt.core.models import ProbeRecord
from pies_pyqt.ui.main_window import MainWindow


def build_records(count: int = 3000):
    records = []
    for idx in range(1, count + 1):
        probe_type = "BOBBIN" if idx % 2 else "MRPC"
        model = f"M{(idx % 6) + 1}"
        records.append(
            ProbeRecord(
                probe_sn=f"P{idx:05d}",
                probe_type=probe_type,
                probe_type_raw=probe_type,
                start_time=None,
                end_time=None,
                tube_number=(idx % 120) + 1,
                operator=f"O{idx % 11}",
                data_group=f"G{idx % 17}",
                model=model,
                outage=f"OT{idx % 7}",
                sg_id=f"SG{idx % 4}",
                warnings=[],
            )
        )
    return records


def build_statistics(records):
    statistics = {}
    for record in records:
        statistics[record.stat_key] = SimpleNamespace(
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
            continuous_use_count=1,
        )
    return statistics


def main():
    app = QApplication([])
    window = MainWindow()
    window.resize(1440, 900)
    window.show()
    app.processEvents()

    records = build_records()
    statistics = build_statistics(records)
    window.current_records = records
    window.current_statistics = statistics
    window.session_records = list(records)
    window.session_statistics = dict(statistics)
    window._switch_view("chart")
    app.processEvents()

    chart_keys = [
        CHART_GROUPS["按探头编号统计"][1][1],
        CHART_GROUPS["按探头编号统计"][2][1],
        CHART_GROUPS["按探头类型统计"][0][1],
        CHART_GROUPS["按探头类型统计"][1][1],
    ]
    filter_steps = [
        ("探头类型", "BOBBIN"),
        ("探头类型", "MRPC"),
        ("探头型号", "M2"),
        ("探头类型", ("BOBBIN", "MRPC")),
    ]

    tracemalloc.start()
    filter_durations = []
    export_durations = []
    peak_kib = 0.0
    exported = 0
    skipped = []

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for idx in range(4):
            col_name, value = filter_steps[idx % len(filter_steps)]
            chart_key = chart_keys[idx % len(chart_keys)]
            round_start = time.perf_counter()
            window._set_summary_filter(col_name, value)
            source = window._get_chart_source_data()
            fig = window._create_chart_figure(chart_key, *source)
            if fig is None:
                skipped.append((idx, col_name, value, chart_key))
                filter_durations.append(time.perf_counter() - round_start)
                continue
            filter_durations.append(time.perf_counter() - round_start)
            export_start = time.perf_counter()
            exported += len(window._save_chart_outputs(fig, tmpdir / f"stress_cycle_{idx}.png"))
            export_durations.append(time.perf_counter() - export_start)
            plt.close(fig)
            gc.collect()
            current, peak = tracemalloc.get_traced_memory()
            peak_kib = max(peak_kib, peak / 1024.0)

        base_records, base_stats, base_hidden = window._get_chart_source_data()
        base_fig = window._create_chart_figure(chart_keys[0], base_records, base_stats, base_hidden)
        if base_fig is not None:
            split_enabled = getattr(base_fig, "_pies_export_mode", "") == "probe_type_model"
            original_get_specs = window.visualizer.get_probe_type_model_export_specs
            try:
                split_start = time.perf_counter()
                window._save_chart_outputs(base_fig, tmpdir / "split_enabled.png")
                split_export_time = time.perf_counter() - split_start

                window.visualizer.get_probe_type_model_export_specs = lambda fig: []
                total_only_start = time.perf_counter()
                window._save_chart_outputs(base_fig, tmpdir / "total_only.png")
                total_only_time = time.perf_counter() - total_only_start
            finally:
                window.visualizer.get_probe_type_model_export_specs = original_get_specs
                plt.close(base_fig)
        else:
            split_enabled = False
            split_export_time = 0.0
            total_only_time = 0.0

    tracemalloc.stop()
    window._clear_all_filters()
    app.processEvents()
    window.close()
    app.quit()

    avg_filter = sum(filter_durations) / len(filter_durations)
    max_filter = max(filter_durations)
    avg_export = sum(export_durations) / len(export_durations) if export_durations else 0.0
    max_export = max(export_durations) if export_durations else 0.0
    print(f"stress-cycles={len(filter_durations)}")
    print(f"exported-files={exported}")
    print(f"avg-filter-round={avg_filter:.3f}s")
    print(f"max-filter-round={max_filter:.3f}s")
    print(f"avg-export-round={avg_export:.3f}s")
    print(f"max-export-round={max_export:.3f}s")
    print(f"split-export-enabled={split_enabled}")
    print(f"split-export-round={split_export_time:.3f}s")
    print(f"total-only-export-round={total_only_time:.3f}s")
    print(f"peak-tracemalloc={peak_kib:.1f} KiB")
    print(f"skipped-figures={len(skipped)}")
    for idx, col_name, value, chart_key in skipped[:5]:
        print(f"skipped[{idx}] filter={col_name}:{value} chart={chart_key}")


if __name__ == "__main__":
    main()
