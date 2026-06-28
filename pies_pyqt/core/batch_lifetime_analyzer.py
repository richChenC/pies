#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
探头批次寿命分析器
根据探头编号分析不同生产批次的探头寿命统计。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

from .models import MODEL_ALIASES, ProbeStatistics

logger = logging.getLogger(__name__)


class BatchLifetimeAnalyzer:
    """探头批次寿命分析器。

    业务口径：探头寿命按累计检测管道数量衡量，不按使用时长衡量。
    """

    EXCLUDED_MODELS = {"ZRPF-FH/2C", "ZRPC-FH/2C"}
    EXCLUDED_MODELS_TEXT = "、".join(sorted(EXCLUDED_MODELS))
    UNSUPPORTED_TUBE_COUNT_MODELS = {"ZRPF-FH/2C", "ZRPC-FH/2C"}
    UNSUPPORTED_TUBE_COUNT_MODELS_TEXT = "、".join(sorted(UNSUPPORTED_TUBE_COUNT_MODELS))
    REASON_LABELS = {
        "excluded_model": "老型号已屏蔽",
        "unrecognized_probe_sn": "编号未识别",
        "empty_probe_sn": "探头编号为空",
        "non_positive_tube_count": "检测管道数量无效",
    }

    def __init__(self):
        self.batch_data: Dict[str, Dict[str, List[float]]] = {}
        self.probe_data: List[Dict] = []
        self.skipped_records: List[Dict] = []
        self.special_case_records: List[Dict] = []
        self.include_excluded_models = False
        self._series_palette = [
            '#4E79A7',
            '#6E8FB3',
            '#8FA8C4',
            '#9BB4D1',
            '#B2C3D5',
            '#96A0AA',
            '#C5D5E6',
            '#D4E0EC',
        ]
        self._series_color_cache: Dict[str, str] = {}

    def reset(self):
        """重置分析缓存。"""
        self.batch_data = {}
        self.probe_data = []
        self.skipped_records = []
        self.special_case_records = []
        self.include_excluded_models = False

    def _parse_mrpc_zrpf_fh_2c_batch(self, probe_sn: str) -> Optional[Tuple[int, int]]:
        """
        ZRPF-FH/2C 型号 MRPC 探头批次解析预留接口。

        这里先只保留空实现，后续拿到明确编号规则后，
        直接在这个函数里补充 year/month 解析逻辑即可。
        """
        _ = probe_sn
        return None

    def _parse_myy_prefix(self, digits: str) -> Optional[Tuple[int, int]]:
        """按 MYY 规则解析前三位，例如 121 -> 2021-01，923 -> 2023-09。"""
        if len(digits) < 3 or not digits[:3].isdigit():
            return None

        month = int(digits[0])
        year_suffix = int(digits[1:3])
        if not 1 <= month <= 12:
            return None
        if not 0 <= year_suffix <= 99:
            return None
        return 2000 + year_suffix, month

    def parse_probe_number(
        self,
        probe_sn: str,
        probe_type: str = "",
        model: str = "",
    ) -> Optional[Tuple[int, int]]:
        """
        解析探头编号，提取生产年月。

        规则：
        - 8 位编号: 前两位月份，第三四位年份后两位
        - MRPC 6/7 位编号: 仅取前三位按 MYY 解析
        - 其他 7 位编号:
          1) 优先按 8 位规则左补 0 解析
          2) 若不成立，则按前 3 位为 MYY 解析
        - 其他 6 位编号: 按前 3 位为 MYY 解析
        """
        if not probe_sn or not isinstance(probe_sn, str):
            return None

        normalized_type = self._normalize_probe_type(probe_type)
        normalized_model = self._normalize_model(model)

        if normalized_type == "MRPC" and normalized_model == "ZRPF-FH/2C":
            return self._parse_mrpc_zrpf_fh_2c_batch(probe_sn)

        clean_sn = re.sub(r"[^\d]", "", str(probe_sn).strip())
        if normalized_type == "MRPC" and len(clean_sn) in {6, 7}:
            mrpc_batch = self._parse_myy_prefix(clean_sn[:3])
            if mrpc_batch:
                return mrpc_batch

        candidates = []

        if len(clean_sn) == 8:
            candidates.append((clean_sn[:2], clean_sn[2:4]))
        elif len(clean_sn) == 7:
            padded_sn = "0" + clean_sn
            candidates.append((padded_sn[:2], padded_sn[2:4]))
            candidates.append((clean_sn[:1], clean_sn[1:3]))
        elif len(clean_sn) == 6:
            candidates.append((clean_sn[:1], clean_sn[1:3]))
        else:
            return None

        for month_str, year_str in candidates:
            try:
                month = int(month_str)
                year_suffix = int(year_str)
            except (ValueError, IndexError):
                continue

            if month < 1 or month > 12:
                continue

            if 0 <= year_suffix <= 30:
                year = 2000 + year_suffix
                return year, month

        return None

    def _normalize_model(self, model: str) -> str:
        normalized = str(model or "").strip().upper()
        return MODEL_ALIASES.get(normalized, normalized)

    def _should_exclude_model(self, model: str) -> bool:
        return self._normalize_model(model) in self.EXCLUDED_MODELS

    def _is_unsupported_tube_count_model(self, model: str) -> bool:
        return self._normalize_model(model) in self.UNSUPPORTED_TUBE_COUNT_MODELS

    def _normalize_probe_type(self, probe_type: str) -> str:
        return str(probe_type or "").strip().upper()

    def _build_series_key(self, probe_type: str, model: str) -> str:
        normalized_type = self._normalize_probe_type(probe_type) or "UNKNOWN"
        normalized_model = self._normalize_model(model) or "UNKNOWN"
        return f"{normalized_type} / {normalized_model}"

    def _get_series_color(self, series_key: str) -> str:
        if series_key not in self._series_color_cache:
            self._series_color_cache[series_key] = self._series_palette[len(self._series_color_cache) % len(self._series_palette)]
        return self._series_color_cache[series_key]

    def _summarize_skipped_series(self) -> Dict[str, int]:
        summary: Dict[str, int] = {}
        for item in self.skipped_records:
            probe_type = self._normalize_probe_type(item.get("probe_type", ""))
            model = self._normalize_model(item.get("model", ""))
            reason = item.get("reason", "unknown")
            series_key = self._build_series_key(probe_type, model)
            label = f"{series_key} [{self.REASON_LABELS.get(reason, reason)}]"
            summary[label] = summary.get(label, 0) + 1
        return summary

    def _build_skipped_detail_lines(self, limit: int = 6) -> List[str]:
        detail_lines: List[str] = []
        grouped_items: Dict[str, List[Dict]] = {}
        for item in self.skipped_records[:limit]:
            probe_type = self._normalize_probe_type(item.get("probe_type", "")) or "UNKNOWN"
            model = self._normalize_model(item.get("model", "")) or "UNKNOWN"
            series_key = self._build_series_key(probe_type, model)
            grouped_items.setdefault(series_key, []).append(item)

        for series_key, items in sorted(grouped_items.items()):
            detail_lines.append(series_key)
            for item in items:
                probe_sn = str(item.get("probe_sn") or "待确认").strip() or "待确认"
                reason = str(item.get("reason_detail") or "").strip() or self.REASON_LABELS.get(item.get("reason", "unknown"), item.get("reason", "unknown"))
                outage = str(item.get("outage") or "待确认").strip() or "待确认"
                sg_id = str(item.get("sg_id") or "待确认").strip() or "待确认"
                data_group = str(item.get("data_group") or "待确认").strip() or "待确认"
                operator = str(item.get("operator") or "待确认").strip() or "待确认"
                tube_number = item.get("tube_number", None)
                tube_display = "待确认" if tube_number is None else str(tube_number)
                start_time = self._format_context_time(item.get("start_time"))
                end_time = self._format_context_time(item.get("end_time"))
                detail_lines.extend([
                    f"  {probe_sn} [{reason}]",
                    f"    大修 {outage} | SG {sg_id} | 组 {data_group} | 操作员 {operator} | 管道数量 {tube_display}",
                    f"    开始 {start_time} | 结束 {end_time}",
                ])
            detail_lines.append("")

        if len(self.skipped_records) > limit:
            remaining = len(self.skipped_records) - limit
            detail_lines.append(f"其余 {remaining} 条未展开")
        elif detail_lines and detail_lines[-1] == "":
            detail_lines.pop()
        return detail_lines

    def _format_context_time(self, value) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        text = str(value or "").strip()
        return text or "待确认"

    def _describe_non_positive_tube_count(self, stat: ProbeStatistics, records: List) -> Tuple[str, Optional[object]]:
        if not records:
            return "累计检测管道数量为0，检测管道数量无效", None

        for record in records:
            tube_number = getattr(record, "tube_number", None)
            if tube_number in (None, 0):
                return "管道数量为空或为0，检测管道数量无效", record

        return f"累计检测管道数量 {stat.unique_tube_count} 根，不满足批次统计条件", records[0]

    def _summarize_special_cases(self) -> Dict[str, int]:
        rule_labels = {
            "mrpc_myy_prefix": "MRPC 6/7位前三位批次规则",
        }
        summary: Dict[str, int] = {}
        for item in self.special_case_records:
            probe_type = self._normalize_probe_type(item.get("probe_type", ""))
            model = self._normalize_model(item.get("model", ""))
            rule = item.get("rule", "special_case")
            series_key = self._build_series_key(probe_type, model)
            label = f"{series_key} [{rule_labels.get(rule, rule)}]"
            summary[label] = summary.get(label, 0) + 1
        return summary

    def _parse_probe_number_with_rule(
        self,
        probe_sn: str,
        probe_type: str = "",
        model: str = "",
    ) -> Tuple[Optional[Tuple[int, int]], Optional[str]]:
        if not probe_sn or not isinstance(probe_sn, str):
            return None, None

        normalized_type = self._normalize_probe_type(probe_type)
        normalized_model = self._normalize_model(model)

        if normalized_type == "MRPC" and normalized_model == "ZRPF-FH/2C":
            return self._parse_mrpc_zrpf_fh_2c_batch(probe_sn), None

        clean_sn = re.sub(r"[^\d]", "", str(probe_sn).strip())
        if normalized_type == "MRPC" and len(clean_sn) in {6, 7}:
            mrpc_batch = self._parse_myy_prefix(clean_sn[:3])
            if mrpc_batch:
                return mrpc_batch, "mrpc_myy_prefix"

        return self.parse_probe_number(probe_sn, probe_type=probe_type, model=model), None

    def _add_probe_entry(
        self,
        probe_sn: str,
        probe_type: str,
        model: str,
        tube_count: float,
        *,
        operator: str = "",
        data_group: str = "",
        outage: str = "",
        sg_id: str = "",
        tube_number: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        reason_detail: str = "",
    ) -> bool:
        model = self._normalize_model(model)
        probe_type = self._normalize_probe_type(probe_type)
        probe_sn = str(probe_sn or "").strip()
        context = {
            "operator": str(operator or "").strip(),
            "data_group": str(data_group or "").strip(),
            "outage": str(outage or "").strip(),
            "sg_id": str(sg_id or "").strip(),
            "tube_number": tube_number,
            "start_time": start_time,
            "end_time": end_time,
            "reason_detail": str(reason_detail or "").strip(),
        }

        if not probe_sn:
            self.skipped_records.append({"probe_sn": probe_sn, "model": model, "reason": "empty_probe_sn", **context})
            return False

        if tube_count <= 0:
            self.skipped_records.append(
                {"probe_sn": probe_sn, "probe_type": probe_type, "model": model, "reason": "non_positive_tube_count", **context}
            )
            return False

        if self._is_unsupported_tube_count_model(model):
            self.skipped_records.append(
                {"probe_sn": probe_sn, "probe_type": probe_type, "model": model, "reason": "excluded_model", **context}
            )
            return False

        if self._should_exclude_model(model) and not self.include_excluded_models:
            self.skipped_records.append(
                {"probe_sn": probe_sn, "probe_type": probe_type, "model": model, "reason": "excluded_model", **context}
            )
            return False

        batch_info, special_rule = self._parse_probe_number_with_rule(probe_sn, probe_type=probe_type, model=model)
        if not batch_info:
            self.skipped_records.append(
                {"probe_sn": probe_sn, "probe_type": probe_type, "model": model, "reason": "unrecognized_probe_sn", **context}
            )
            return False

        year, month = batch_info
        batch_key = f"{year}-{month:02d}"
        series_key = self._build_series_key(probe_type, model)

        probe_info = {
            "probe_sn": probe_sn,
            "probe_type": probe_type,
            "model": model,
            "year": year,
            "month": month,
            "batch_key": batch_key,
            "series_key": series_key,
            "lifetime": tube_count,
            "tube_count": tube_count,
        }
        self.probe_data.append(probe_info)
        if special_rule:
            self.special_case_records.append(
                {
                    "probe_sn": probe_sn,
                    "probe_type": probe_type,
                    "model": model,
                    "batch_key": batch_key,
                    "rule": special_rule,
                }
            )
        self.batch_data.setdefault(series_key, {}).setdefault(batch_key, []).append(tube_count)
        return True

    def load_data_from_statistics(
        self,
        statistics: Dict[str, ProbeStatistics],
        include_excluded_models: bool = False,
    ) -> bool:
        """
        从当前 GUI 已计算好的探头统计结果中加载数据。
        每根探头以其累计检测管道数量参与批次统计。
        """
        self.reset()
        self.include_excluded_models = include_excluded_models

        if not statistics:
            return False

        for stat in statistics.values():
            model = getattr(stat, "model", "") or ""
            probe_type = getattr(stat, "probe_type", "") or ""
            tube_count = float(getattr(stat, "unique_tube_count", 0.0) or 0.0)
            records = list(getattr(stat, "records", []) or [])
            reason_detail = ""
            context_record = records[0] if records else None
            if tube_count <= 0:
                reason_detail, candidate_record = self._describe_non_positive_tube_count(stat, records)
                if candidate_record is not None:
                    context_record = candidate_record
            first_record = context_record
            self._add_probe_entry(
                stat.probe_sn,
                probe_type,
                model,
                tube_count,
                operator=getattr(first_record, "operator", "") if first_record else "",
                data_group=getattr(first_record, "data_group", "") if first_record else "",
                outage=getattr(first_record, "outage", "") if first_record else "",
                sg_id=getattr(first_record, "sg_id", "") if first_record else "",
                tube_number=getattr(first_record, "tube_number", None) if first_record else None,
                start_time=getattr(first_record, "start_time", None) if first_record else None,
                end_time=getattr(first_record, "end_time", None) if first_record else None,
                reason_detail=reason_detail,
            )

        logger.info(
            "批次寿命分析加载完成: 有效探头 %s 个, 批次 %s 个, 跳过 %s 个",
            len(self.probe_data),
            len(self.batch_data),
            len(self.skipped_records),
        )
        return len(self.probe_data) > 0

    def load_data_from_excel(self, excel_path: str, model_filter: str = None) -> bool:
        """
        从 Excel 文件加载数据。
        保留原有离线能力，同时复用统一规则。
        """
        self.reset()

        try:
            df = pd.read_excel(excel_path)

            required_columns = ["Probe SN", "Model"]
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                logger.error(f"Excel文件缺少必要的列: {missing_columns}")
                return False

            lifetime_column = None
            possible_lifetime_columns = [
                "累计检测管道数量",
                "管道数量",
                "Tube Count",
                "Tube Number",
            ]
            for col in possible_lifetime_columns:
                if col in df.columns:
                    lifetime_column = col
                    break

            if not lifetime_column:
                logger.error("未找到管道数量相关的列")
                return False

            if model_filter:
                df = df[df["Model"].astype(str).str.contains(model_filter, na=False, case=False)]

            for _, row in df.iterrows():
                probe_sn = str(row["Probe SN"]).strip()
                model = str(row["Model"]).strip()
                probe_type = str(row["Probe Type"]).strip() if "Probe Type" in df.columns else ""
                try:
                    lifetime = float(row[lifetime_column])
                except (ValueError, TypeError):
                    continue
                self._add_probe_entry(probe_sn, probe_type, model, lifetime)

            return len(self.probe_data) > 0

        except Exception as e:
            logger.error(f"加载Excel文件失败: {e}")
            return False

    def calculate_batch_statistics(self) -> Dict[str, Dict[str, Dict]]:
        """计算各类型/型号下各批次的检测管道数量统计信息。"""
        batch_stats: Dict[str, Dict[str, Dict]] = {}

        for series_key, series_batches in self.batch_data.items():
            batch_stats[series_key] = {}
            for batch_key, tube_counts in series_batches.items():
                if not tube_counts:
                    continue

                total_tube_count = float(sum(tube_counts))
                count = len(tube_counts)
                mean_tube_count = total_tube_count / count if count else 0.0

                stats = {
                    "series_key": series_key,
                    "batch_key": batch_key,
                    "count": count,
                    "total_tube_count": total_tube_count,
                    "mean_tube_count": mean_tube_count,
                    "median_tube_count": float(np.median(tube_counts)),
                    "std_tube_count": float(np.std(tube_counts)),
                    "min_tube_count": float(np.min(tube_counts)),
                    "max_tube_count": float(np.max(tube_counts)),
                    "tube_counts": tube_counts,
                }
                stats.update({
                    "total_lifetime": total_tube_count,
                    "mean_lifetime": mean_tube_count,
                    "median_lifetime": stats["median_tube_count"],
                    "std_lifetime": stats["std_tube_count"],
                    "min_lifetime": stats["min_tube_count"],
                    "max_lifetime": stats["max_tube_count"],
                    "lifetimes": tube_counts,
                })
                batch_stats[series_key][batch_key] = stats

        return batch_stats

    def create_batch_lifetime_chart(
        self,
        save_path: str = None,
        figsize: Tuple[int, int] = (14, 6),
        excluded_probe_count: int = 0,
        show_excluded_note: bool = True,
    ) -> plt.Figure:
        """创建按探头类型/型号区分的生产批次平均寿命图。"""
        if not self.batch_data:
            raise ValueError("没有可用于批次寿命分析的数据")

        batch_stats = self.calculate_batch_statistics()
        all_batch_labels = sorted(
            {batch_key for series_stats in batch_stats.values() for batch_key in series_stats.keys()}
        )
        if not all_batch_labels:
            raise ValueError("没有可用于批次寿命分析的数据")

        sorted_series_keys = sorted(batch_stats.keys())
        series_count = max(1, len(sorted_series_keys))
        batch_count = max(1, len(all_batch_labels))
        auto_width = max(figsize[0], min(30, 11 + batch_count * 0.78))
        auto_height = max(figsize[1], min(18, 4.4 + series_count * 2.35))
        fig = plt.figure(figsize=(auto_width, auto_height), facecolor="white")
        grid = fig.add_gridspec(
            nrows=series_count,
            ncols=2,
            width_ratios=[5.2, 2.2],
            left=0.06,
            right=0.99,
            top=0.91,
            bottom=0.14,
            wspace=0.10,
            hspace=0.42,
        )
        axes = []
        for row_index in range(series_count):
            if row_index == 0:
                axes.append(fig.add_subplot(grid[row_index, 0]))
            else:
                axes.append(fig.add_subplot(grid[row_index, 0], sharex=axes[0]))
        side_ax = fig.add_subplot(grid[:, 1])
        side_ax.axis("off")

        x_pos = np.arange(len(all_batch_labels))
        max_mean = 0.0
        export_specs = []

        for axis in axes:
            axis.set_facecolor("white")

        for ax, series_key in zip(axes, sorted_series_keys):
            series_stats = batch_stats[series_key]
            series_x = []
            series_y = []
            for batch_index, batch_key in enumerate(all_batch_labels):
                stats = series_stats.get(batch_key)
                if not stats:
                    continue
                series_x.append(batch_index)
                series_y.append(stats["mean_tube_count"])
                max_mean = max(max_mean, stats["mean_tube_count"])

            if not series_x:
                continue

            color = self._get_series_color(series_key)
            ax.plot(
                series_x,
                series_y,
                linewidth=2.1,
                marker="o",
                markersize=5.8,
                color=color,
                label=series_key,
            )
            ax.scatter(series_x, series_y, color=color, s=38, zorder=3)

            for point_x, point_y in zip(series_x, series_y):
                ax.text(
                    point_x,
                    point_y + max(0.22, point_y * 0.03),
                    f"{point_y:.0f}根",
                    ha="center",
                    va="bottom",
                    fontsize=8.0,
                    color=color,
                )

            export_specs.append(
                {
                    "series_key": series_key,
                    "batch_labels": list(all_batch_labels),
                    "series_x": list(series_x),
                    "series_y": list(series_y),
                }
            )

        upper_margin = max(1.0, max_mean * 0.12)
        for idx, ax in enumerate(axes):
            ax.set_ylim(0, max_mean + upper_margin)
            ax.tick_params(axis="both", labelsize=9.3)
            ax.grid(True, axis="y", alpha=0.24, linestyle="--", color="#C7D3DF")
            ax.set_axisbelow(True)
            for spine in ax.spines.values():
                spine.set_color("#D7E0E9")
                spine.set_linewidth(1.0)
            ax.set_ylabel("平均寿命（检测管数）/ 根", fontsize=11, fontweight="bold", labelpad=10)
            ax.set_title(sorted_series_keys[idx], fontsize=11.0, fontweight="bold", pad=10, loc="center", color="#314456", y=1.01)
            ax.set_xticks(x_pos)
            ax.set_xticklabels(all_batch_labels, rotation=38, ha="right")
            ax.set_xlabel("生产批次（年-月）", fontsize=10.0, fontweight="bold", labelpad=4)

        fig.suptitle("按探头类型/型号区分的生产批次平均寿命", fontsize=15, fontweight="bold", y=0.985)
        fig._pies_export_mode = "batch_lifetime"
        fig._pies_export_specs = export_specs
        fig._pies_export_chart_title = "按探头类型/型号区分的生产批次平均寿命"

        legend_handles = [
            Line2D(
                [0],
                [0],
                color=self._get_series_color(series_key),
                marker="o",
                linestyle="-",
                linewidth=2.1,
                markersize=6.2,
            )
            for series_key in sorted_series_keys
        ]
        legend = side_ax.legend(
            legend_handles,
            sorted_series_keys,
            title="探头类型 / 型号",
            loc="upper left",
            frameon=True,
            fontsize=8.8,
            title_fontsize=9.8,
            borderpad=0.7,
            labelspacing=0.58,
            handlelength=2.0,
            handletextpad=0.7,
        )
        legend.get_frame().set_facecolor("#F8FAFD")
        legend.get_frame().set_edgecolor("#D7DEE8")
        legend.get_frame().set_linewidth(1.0)

        skipped_summary = self._summarize_skipped_series()
        skipped_detail_lines = self._build_skipped_detail_lines()
        if show_excluded_note:
            side_ax.text(
                0.02,
                0.70,
                "已屏蔽型号提示",
                transform=side_ax.transAxes,
                ha="left",
                va="top",
                fontsize=9.6,
                fontweight="bold",
                color="#4A5A6A",
            )
            excluded_note_lines = [
                f"{self.UNSUPPORTED_TUBE_COUNT_MODELS_TEXT}",
                "以上型号当前没有批次规则，",
                "仅保留提示，不纳入管道数量统计。",
            ]
            if excluded_probe_count:
                excluded_note_lines.append(f"当前范围已屏蔽 {excluded_probe_count} 个探头")
            side_ax.text(
                0.02,
                0.64,
                "\n".join(excluded_note_lines),
                transform=side_ax.transAxes,
                ha="left",
                va="top",
                fontsize=8.4,
                color="#5A6573",
                linespacing=1.45,
                bbox={
                    "boxstyle": "round,pad=0.45",
                    "facecolor": "#F7F9FC",
                    "edgecolor": "#D7DEE8",
                },
            )
            skipped_title_y = 0.38
            skipped_body_y = 0.32
        else:
            skipped_title_y = 0.70
            skipped_body_y = 0.64
        side_ax.text(
            0.02,
            skipped_title_y,
            "未纳入批次统计",
            transform=side_ax.transAxes,
            ha="left",
            va="top",
            fontsize=9.6,
            fontweight="bold",
            color="#4A5A6A",
        )
        if skipped_summary:
            skipped_lines = [f"{label} x{count}" for label, count in sorted(skipped_summary.items())]
            if skipped_detail_lines:
                skipped_lines.append("")
                skipped_lines.extend(skipped_detail_lines)
            side_ax.text(
                0.02,
                skipped_body_y,
                "\n".join(skipped_lines),
                transform=side_ax.transAxes,
                ha="left",
                va="top",
                fontsize=8.0,
                color="#5A6573",
                linespacing=1.45,
                bbox={
                    "boxstyle": "round,pad=0.45",
                    "facecolor": "#F7F9FC",
                    "edgecolor": "#D7DEE8",
                },
            )
        else:
            side_ax.text(
                0.02,
                skipped_body_y,
                "当前没有未识别的批次型号",
                transform=side_ax.transAxes,
                ha="left",
                va="top",
                fontsize=8.4,
                color="#6A7684",
                bbox={
                    "boxstyle": "round,pad=0.45",
                    "facecolor": "#F7F9FC",
                    "edgecolor": "#D7DEE8",
                },
            )

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches="tight")
            logger.info(f"图表已保存到: {save_path}")

        return fig

    def get_batch_lifetime_export_specs(self, fig) -> list[dict]:
        if getattr(fig, '_pies_export_mode', '') != 'batch_lifetime':
            return []
        return [dict(spec) for spec in (getattr(fig, '_pies_export_specs', []) or [])]

    def export_batch_report(self, output_path: str) -> bool:
        """导出批次分析报告到 Excel。"""
        try:
            batch_stats = self.calculate_batch_statistics()
            report_data = []
            for series_key, series_stats in sorted(batch_stats.items()):
                for batch_key, stats in sorted(series_stats.items()):
                    report_data.append(
                        {
                            "探头类型/型号": series_key,
                            "生产批次": batch_key,
                            "样本数量": stats["count"],
                            "平均寿命(检测管数)": round(stats["mean_tube_count"], 2),
                            "中位寿命(检测管数)": round(stats["median_tube_count"], 2),
                            "标准差(根)": round(stats["std_tube_count"], 2),
                            "最小寿命(检测管数)": round(stats["min_tube_count"], 2),
                            "最大寿命(检测管数)": round(stats["max_tube_count"], 2),
                        }
                    )

            df_report = pd.DataFrame(report_data)
            df_detail = pd.DataFrame(self.probe_data)
            df_skipped = pd.DataFrame(self.skipped_records)
            df_special = pd.DataFrame(self.special_case_records)

            with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
                df_report.to_excel(writer, sheet_name="批次统计", index=False)
                df_detail.to_excel(writer, sheet_name="有效探头明细", index=False)
                if not df_special.empty:
                    df_special.to_excel(writer, sheet_name="特殊规则批次", index=False)
                if not df_skipped.empty:
                    df_skipped.to_excel(writer, sheet_name="跳过记录", index=False)

            logger.info(f"批次分析报告已导出到: {output_path}")
            return True

        except Exception as e:
            logger.error(f"导出报告失败: {e}")
            return False

    def get_summary_info(self) -> str:
        """获取分析摘要信息。"""
        if not self.batch_data:
            return "暂无可用于批次管道数量分析的数据"

        batch_stats = self.calculate_batch_statistics()
        flat_batch_stats = [
            {
                "series_key": series_key,
                "batch_key": batch_key,
                **stats,
            }
            for series_key, series_batches in batch_stats.items()
            for batch_key, stats in series_batches.items()
        ]
        if not flat_batch_stats:
            return "暂无可用于批次管道数量分析的数据"

        total_probes = len(self.probe_data)
        total_batches = len(flat_batch_stats)

        all_tube_counts = [float(item["tube_count"]) for item in self.probe_data if item.get("tube_count") is not None]
        if not all_tube_counts:
            return "暂无可用于批次管道数量分析的数据"

        overall_mean = float(np.mean(all_tube_counts))
        overall_std = float(np.std(all_tube_counts))
        special_case_count = len(self.special_case_records)

        best_batch = max(flat_batch_stats, key=lambda item: item["mean_tube_count"])
        worst_batch = min(flat_batch_stats, key=lambda item: item["mean_tube_count"])
        batch_keys = sorted({item["batch_key"] for item in flat_batch_stats})

        return (
            "批次寿命分析摘要:\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"总探头数量: {total_probes} 个\n"
            f"生产批次数: {total_batches} 个\n"
            f"特殊规则批次命中: {special_case_count} 条\n"
            f"未纳入批次统计: {len(self.skipped_records)} 条\n"
            f"整体平均寿命(检测管数): {overall_mean:.2f} ± {overall_std:.2f} 根\n"
            f"最佳批次: {best_batch['series_key']} / {best_batch['batch_key']} (平均寿命: {best_batch['mean_tube_count']:.2f}根, 样本数: {best_batch['count']})\n"
            f"最差批次: {worst_batch['series_key']} / {worst_batch['batch_key']} (平均寿命: {worst_batch['mean_tube_count']:.2f}根, 样本数: {worst_batch['count']})\n"
            f"批次时间跨度: {batch_keys[0]} 至 {batch_keys[-1]}\n"
            f"跳过记录数: {len(self.skipped_records)}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )


