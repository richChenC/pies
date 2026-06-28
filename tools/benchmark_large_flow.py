from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib

matplotlib.use("Agg")

from PyQt5.QtWidgets import QApplication

from pies_pyqt.core.models import ProbeRecord
from pies_pyqt.ui.main_window import MainWindow


def build_records(count: int = 2000):
    records = []
    for idx in range(1, count + 1):
        probe_type = "BOBBIN" if idx % 2 else "MRPC"
        model = f"M{(idx % 5) + 1}"
        record = ProbeRecord(
            probe_sn=f"P{idx:05d}",
            probe_type=probe_type,
            probe_type_raw=probe_type,
            start_time=None,
            end_time=None,
            tube_number=(idx % 80) + 1,
            operator=f"O{idx % 9}",
            data_group=f"G{idx % 15}",
            model=model,
            outage=f"OT{idx % 6}",
            sg_id=f"SG{idx % 4}",
            warnings=[],
        )
        records.append(record)
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


def timed(label, fn):
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    print(f"{label}: {elapsed:.3f}s")
    return result, elapsed


def main():
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()

    records = build_records()
    statistics = build_statistics(records)
    window.current_records = records
    window.current_statistics = statistics
    window.session_records = list(records)
    window.session_statistics = dict(statistics)
    window._current_view = "chart"
    window._chart_panel.show()
    app.processEvents()

    _, t_filter_first = timed("filter first build", lambda: window._set_summary_filter("探头类型", "BOBBIN"))
    _, t_chart_source = timed("chart source cached", lambda: window._get_chart_source_data())
    _, t_metric_source = timed("metric source cached", lambda: window._get_metric_source_data())
    _, t_filter_second = timed("filter switch", lambda: window._set_summary_filter("探头型号", "M2"))

    with tempfile.TemporaryDirectory() as tmp:
        fig, t_create_1 = timed(
            "create chart figure",
            lambda: window._create_chart_figure("管道数量折线图", *window._get_chart_source_data()),
        )
        if fig:
            _, t_export = timed(
                "export chart outputs",
                lambda: window._save_chart_outputs(fig, Path(tmp) / "benchmark_chart.png"),
            )
        else:
            t_export = -1.0

    print("--- summary ---")
    print(f"records={len(records)}")
    print(f"filter first build={t_filter_first:.3f}s")
    print(f"chart source cached={t_chart_source:.3f}s")
    print(f"metric source cached={t_metric_source:.3f}s")
    print(f"filter switch={t_filter_second:.3f}s")
    print(f"export={t_export:.3f}s")

    window.close()
    app.quit()


if __name__ == "__main__":
    main()
