"""
数据可视化模块
生成统计图表
"""
import matplotlib.pyplot as plt
import matplotlib
from matplotlib.backends.backend_agg import FigureCanvasAgg
from typing import Dict, List, Callable
import logging
import re
import weakref
import numpy as np

from .models import ProbeStatistics, ProbeRecord, normalize_model_name
from collections import Counter, defaultdict
from datetime import datetime

# 设置中文字体
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
matplotlib.rcParams['axes.unicode_minus'] = False

logger = logging.getLogger(__name__)


class _FigureRegistry(list):
    def append(self, fig):
        try:
            super().append(weakref.ref(fig))
        except TypeError:
            pass

    def iter_live(self):
        alive = []
        kept = []
        for item in self:
            fig = item() if callable(item) else item
            if fig is not None:
                alive.append(fig)
                kept.append(item)
        self[:] = kept
        return alive


def _generate_gradient_colors(values, base_color='#366092', num_colors=None):
    """

    
    Args:
        values: 数值列表
        base_color: 基础颜色（最深的颜色，十六进制格式）
        num_colors: 颜色数量（如果为None，则使用values的长度）
    
    Returns:
        颜色列表
    """
    if not values:
        return []
    
    num_colors = num_colors or len(values)
    if num_colors == 0:
        return []
    
    # 将十六进制颜色转换为RGB
    def hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    # 将RGB转换为十六进制
    def rgb_to_hex(rgb):
        return '#{:02x}{:02x}{:02x}'.format(int(rgb[0]), int(rgb[1]), int(rgb[2]))
    
    # 获取基础颜色的RGB值
    base_rgb = hex_to_rgb(base_color)
    
    # 计算值的范围
    min_val = min(values)
    max_val = max(values)
    val_range = max_val - min_val if max_val != min_val else 1
    
    # 计算值的相对差异（变异系数，用于判断差异大小）
    # 如果所有值都相同，则使用最小变化
    if val_range == 0:
        # 所有值相同，使用轻微的颜色变化
        variation_factor = 0.1
    else:
        # 计算变异系数（标准差/均值），用于判断相对差异
        mean_val = sum(values) / len(values)
        if mean_val > 0:
            # 使用相对范围（范围/均值）来判断差异大小
            relative_range = val_range / mean_val
            # 将相对范围映射到0.15到0.5的变化幅度
            # 差异大（relative_range > 1）时，变化幅度接近0.5
            # 差异小（relative_range < 0.1）时，变化幅度接近0.15
            variation_factor = min(0.5, max(0.15, 0.15 + 0.35 * min(1.0, relative_range / 1.0)))
        else:
            variation_factor = 0.3
    
    # 生成渐变色：值越大，颜色越深（接近base_color）；值越小，颜色越浅
    colors = []
    for val in values:
        # 计算归一化的位置（0到1之间，1表示最大值，0表示最小值）
        normalized = (val - min_val) / val_range
        
        # 从浅色（白色+基础色混合）到深色（基础色）的渐变
        # 根据variation_factor调整变化幅度：
        # variation_factor小（差异小）时，所有颜色都接近基础色，变化小
        # variation_factor大（差异大）时，颜色从很浅到很深，变化大
        # 最浅的颜色混合比例：1 - variation_factor（差异小时接近1，即接近基础色）
        # 最深的颜色混合比例：1（纯基础色）
        min_mix = 1 - variation_factor  # 最浅颜色的混合比例
        mix_factor = min_mix + variation_factor * normalized  # 根据归一化值计算混合比例
        
        # 计算混合后的RGB值
        # 浅色端：白色(255,255,255)与基础色混合
        # 深色端：纯基础色
        white = (255, 255, 255)
        r = int(white[0] * (1 - mix_factor) + base_rgb[0] * mix_factor)
        g = int(white[1] * (1 - mix_factor) + base_rgb[1] * mix_factor)
        b = int(white[2] * (1 - mix_factor) + base_rgb[2] * mix_factor)
        
        colors.append(rgb_to_hex((r, g, b)))
    
    return colors


def _generate_rank_gradient_colors(count, base_color='#4E79A7', min_mix=0.18, max_mix=0.92):
    """按排名生成更明显的渐变色，避免数值接近时颜色过于相似。"""
    if count <= 0:
        return []

    def hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def rgb_to_hex(rgb):
        return '#{:02x}{:02x}{:02x}'.format(int(rgb[0]), int(rgb[1]), int(rgb[2]))

    base_rgb = hex_to_rgb(base_color)
    white = (255, 255, 255)
    if count == 1:
        mix_values = [max_mix]
    else:
        mix_values = [
            max_mix - (max_mix - min_mix) * (idx / (count - 1))
            for idx in range(count)
        ]

    colors = []
    for mix_factor in mix_values:
        r = int(white[0] * (1 - mix_factor) + base_rgb[0] * mix_factor)
        g = int(white[1] * (1 - mix_factor) + base_rgb[1] * mix_factor)
        b = int(white[2] * (1 - mix_factor) + base_rgb[2] * mix_factor)
        colors.append(rgb_to_hex((r, g, b)))
    return colors


class DataVisualizer:
    """数据可视化器"""
    
    def __init__(self):
        self.figures = _FigureRegistry()
        self._ui_palette = {
            'blue': '#4E79A7',
            'blue_mid': '#6E8FB3',
            'blue_light': '#A9C0DA',
            'teal': '#6E8FB3',
            'teal_mid': '#8FA8C4',
            'teal_light': '#C5D5E6',
            'slate': '#7B8794',
            'slate_mid': '#96A0AA',
            'slate_light': '#B8C2CC',
            'sand': '#8FA8C4',
            'sand_light': '#D4E0EC',
            'ink': '#334155',
            'panel': '#FCFDFE',
        }
        self._chart_series_palette = [
            '#4E79A7',
            '#6E8FB3',
            '#8FA8C4',
            '#96A0AA',
            '#B2C3D5',
            '#7B8794',
            '#C5D5E6',
            '#D4E0EC',
        ]
        self._probe_type_color_families = {
            'BOBBIN': ['#4E79A7', '#6E8FB3', '#8FA8C4', '#B2C3D5'],
            'MRPC': ['#5D82AE', '#7B9ABF', '#9BB4D1', '#BCD0E3'],
            'UNKNOWN': ['#7B8794', '#96A0AA', '#B8C2CC'],
        }
        self._probe_type_base_colors = {
            'BOBBIN': '#4E79A7',
            'MRPC': '#5D82AE',
            'UNKNOWN': '#7B8794',
        }
    def _normalize_probe_type(self, probe_type: str) -> str:
        return (probe_type or '').strip().upper() or 'UNKNOWN'

    def _normalize_model(self, model: str) -> str:
        normalized = normalize_model_name(model)
        return normalized or 'UNKNOWN'

    def _build_dynamic_color_family(self, probe_type: str) -> List[str]:
        palette_pool = [
            ['#4E79A7', '#6E8FB3', '#8FA8C4', '#B2C3D5'],
            ['#5D82AE', '#7B9ABF', '#9BB4D1', '#BCD0E3'],
            ['#7B8794', '#96A0AA', '#B8C2CC', '#D4DCE3'],
            ['#6E8FB3', '#8FA8C4', '#B2C3D5', '#D4E0EC'],
        ]
        index = sum(ord(ch) for ch in probe_type) % len(palette_pool)
        return palette_pool[index]

    def _build_dynamic_base_color(self, probe_type: str) -> str:
        base_candidates = ['#4E79A7', '#5D82AE', '#6E8FB3', '#8FA8C4', '#96A0AA']
        index = sum(ord(ch) for ch in probe_type) % len(base_candidates)
        return base_candidates[index]

    def _get_series_color(self, probe_type: str, model: str) -> str:
        family = self._probe_type_color_families.get(probe_type)
        if not family:
            family = self._build_dynamic_color_family(probe_type)

        normalized_model = self._normalize_model(model)
        color_index = sum(ord(ch) for ch in normalized_model) % len(family)
        return family[color_index]

    def _get_probe_type_base_color(self, probe_type: str) -> str:
        return self._probe_type_base_colors.get(probe_type, self._build_dynamic_base_color(probe_type))

    def _normalize_outage_label(self, outage: str) -> str:
        return (outage or '').strip() or '未标注大修'

    def _outage_sort_key(self, outage: str):
        value = self._normalize_outage_label(outage)
        match = re.match(r'([A-Za-z]+)(\d+)$', value)
        if match:
            return (match.group(1).upper(), int(match.group(2)))
        return ('ZZZ', value)

    def _normalize_sg_ring_label(self, sg_id: str) -> str:
        value = (sg_id or '').strip()
        if not value:
            return ''
        match = re.search(r'(\d+)', value)
        if match:
            return f"{match.group(1)}环"
        return value

    def _sg_ring_sort_key(self, ring_label: str):
        match = re.search(r'(\d+)', ring_label or '')
        if match:
            return (0, int(match.group(1)))
        return (1, ring_label or '')

    def _model_color(self, model: str) -> str:
        palette = ['#4E79A7', '#5D82AE', '#6E8FB3', '#8FA8C4', '#9BB4D1', '#B2C3D5', '#96A0AA', '#D4E0EC']
        normalized = self._normalize_model(model)
        return palette[sum(ord(ch) for ch in normalized) % len(palette)]

    def _create_vertical_outage_axes(
        self,
        outage_count: int,
        base_width: float = 9.5,
        row_height: float = 4.5,
        max_width: float = 18.0,
        max_height: float = 24.0,
    ):
        fig_width = min(max_width, max(base_width, 9.5))
        fig_height = min(max_height, max(5.4, outage_count * row_height + 1.2))
        fig, axes = plt.subplots(outage_count, 1, figsize=(fig_width, fig_height), squeeze=False)
        return fig, [row[0] for row in axes]

    def _group_statistics_by_probe_type_and_model(
        self,
        statistics: Dict[str, ProbeStatistics],
        value_getter: Callable[[ProbeStatistics], float],
        keep_zero: bool = False,
    ) -> Dict[str, Dict[str, List[Dict]]]:
        groups = {}
        for stat in statistics.values():
            value = float(value_getter(stat))
            if value <= 0 and not keep_zero:
                continue

            probe_type = self._normalize_probe_type(stat.probe_type)
            model = self._normalize_model(stat.model)
            groups.setdefault(probe_type, {}).setdefault(model, []).append(
                {
                    'probe_sn': (stat.probe_sn or '').strip() or 'UNKNOWN',
                    'value': value,
                }
            )

        for model_map in groups.values():
            for items in model_map.values():
                items.sort(key=lambda item: item['value'], reverse=True)

        return dict(sorted(groups.items(), key=lambda kv: kv[0]))

    def _build_probe_type_subplot_specs(
        self,
        grouped_items: Dict[str, Dict[str, List[Dict]]],
    ) -> tuple[List[tuple[str, str, List[Dict]]], int]:
        subplot_specs = []
        max_items = 0
        for probe_type, model_map in grouped_items.items():
            for model, items in model_map.items():
                subplot_specs.append((probe_type, model, items))
                max_items = max(max_items, len(items))
        return subplot_specs, max_items

    def _draw_probe_type_model_axis(
        self,
        ax,
        probe_type: str,
        model: str,
        items: List[Dict],
        ylabel: str,
        formatter,
    ) -> None:
        labels = [item['probe_sn'] for item in items]
        values = [item['value'] for item in items]
        x = list(range(len(items)))
        color = self._get_series_color(probe_type, model)
        linestyle = '-' if len(items) > 1 else 'None'
        ax.set_facecolor('#FCFDFE')
        ax.plot(
            x,
            values,
            color=color,
            linewidth=1.9,
            marker='o',
            markersize=4.1,
            markeredgecolor='#1F1F1F',
            markeredgewidth=0.3,
            markerfacecolor=color,
            linestyle=linestyle,
            zorder=3,
        )

        title_y = 1.015
        probe_type_color = self._get_probe_type_base_color(probe_type)
        ax.text(
            0.485,
            title_y,
            probe_type,
            transform=ax.transAxes,
            ha='right',
            va='bottom',
            fontsize=10.0,
            fontweight='bold',
            color=probe_type_color,
        )
        ax.text(
            0.5,
            title_y,
            '  /  ',
            transform=ax.transAxes,
            ha='center',
            va='bottom',
            fontsize=10.0,
            fontweight='bold',
            color='#6B7280',
        )
        ax.text(
            0.515,
            title_y,
            model,
            transform=ax.transAxes,
            ha='left',
            va='bottom',
            fontsize=10.0,
            fontweight='bold',
            color=color,
        )
        ax.set_ylabel(ylabel, fontsize=9.5, color='#243447', labelpad=3)
        ax.set_xticks(x)
        if len(labels) <= 8:
            display_labels = labels
            rotation = 32
            label_fontsize = 8.4
        elif len(labels) <= 16:
            display_labels = labels
            rotation = 40
            label_fontsize = 7.3
        elif len(labels) <= 26:
            display_labels = labels
            rotation = 46
            label_fontsize = 6.9
        else:
            display_labels = labels
            rotation = 50
            label_fontsize = 6.4
        ax.set_xticklabels(display_labels, rotation=rotation, ha='right', fontsize=label_fontsize)
        ax.tick_params(axis='x', colors='#4C5A67', pad=4)
        ax.tick_params(axis='y', labelsize=9, colors='#4C5A67')
        ax.grid(axis='y', color='#D9E2EC', alpha=0.8, linestyle='--', linewidth=0.8)
        ax.set_axisbelow(True)
        ax.set_xlabel('探头编号', fontsize=9.5, color='#243447', labelpad=4, loc='center')
        max_val = max(values) if values else 0
        ax.set_ylim(0, max_val * 1.16 if max_val > 0 else 1)
        if all(isinstance(v, (int, np.integer)) for v in values):
            ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
        ax.margins(x=0.05)
        for label in ax.get_xticklabels():
            label.set_clip_on(False)
        for spine in ax.spines.values():
            spine.set_color('#D5DEE8')
            spine.set_linewidth(0.9)

        y_offset = max_val * 0.025 if max_val > 0 else 0.15
        for idx, (x_pos, value) in enumerate(zip(x, values)):
            offset = y_offset if idx % 2 == 0 else y_offset * 1.9
            ax.text(
                x_pos,
                value + offset,
                formatter(value),
                ha='center',
                va='bottom',
                fontsize=7.1,
                color=color,
            )

    def create_probe_type_model_single_figure(
        self,
        probe_type: str,
        model: str,
        items: List[Dict],
        chart_title: str,
        ylabel: str,
        value_formatter=None,
        figure_width: float = 12.0,
        figure_height: float = 7.0,
    ) -> plt.Figure:
        formatter = value_formatter or (lambda v: f'{v:.1f}')
        fig, ax = plt.subplots(figsize=(figure_width, figure_height))
        self._draw_probe_type_model_axis(ax, probe_type, model, items, ylabel, formatter)
        fig.suptitle(chart_title, fontsize=15, fontweight='bold', color='#1F2D3D', x=0.5, ha='center', y=0.965)
        fig.subplots_adjust(left=0.09, right=0.985, top=0.84, bottom=0.21)
        self.figures.append(fig)
        return fig

    def get_probe_type_model_export_specs(
        self,
        fig,
    ) -> list[dict]:
        if getattr(fig, '_pies_export_mode', '') != 'probe_type_model':
            return []
        return list(getattr(fig, '_pies_export_specs', []) or [])

    def _create_probe_type_model_subplots(
        self,
        grouped_items: Dict[str, Dict[str, List[Dict]]],
        title: str,
        ylabel: str,
        figure_width: float | None = None,
        figure_height: float | None = None,
        value_formatter=None,
    ) -> plt.Figure:
        if not grouped_items:
            return None

        subplot_specs, max_items = self._build_probe_type_subplot_specs(grouped_items)
        if not subplot_specs:
            return None

        wide_threshold = 18
        wide_specs = [spec for spec in subplot_specs if len(spec[2]) >= wide_threshold]
        normal_specs = [spec for spec in subplot_specs if len(spec[2]) < wide_threshold]
        normal_rows = (len(normal_specs) + 1) // 2 if normal_specs else 0
        total_rows = len(wide_specs) + normal_rows

        width_by_data = 12.0 + max_items * 0.42
        fig_width = figure_width or max(15.5, min(36, width_by_data))
        if max_items <= 8:
            row_height = 3.6
        elif max_items <= 18:
            row_height = 4.0
        else:
            row_height = 4.6
        fig_height = figure_height or max(6.4, min(22.0, row_height * max(1, total_rows) + 1.8))
        fig = plt.figure(figsize=(fig_width, fig_height))
        gs = fig.add_gridspec(total_rows, 2, hspace=0.86, wspace=0.22)

        subplot_meta: list[tuple[object, tuple[str, str, list[dict]]]] = []
        current_row = 0
        for spec in wide_specs:
            subplot_meta.append((fig.add_subplot(gs[current_row, :]), spec))
            current_row += 1

        for idx, spec in enumerate(normal_specs):
            col = idx % 2
            if col == 0 and idx > 0:
                current_row += 1
            row = current_row if normal_specs else 0
            subplot_meta.append((fig.add_subplot(gs[row, col]), spec))

        formatter = value_formatter or (lambda v: f'{v:.1f}')
        for ax, (probe_type, model, items) in subplot_meta:
            self._draw_probe_type_model_axis(ax, probe_type, model, items, ylabel, formatter)

        fig.suptitle(title, fontsize=15, fontweight='bold', color='#1F2D3D', x=0.5, ha='center', y=0.968)
        bottom_margin = 0.12 if max_items <= 14 else 0.16
        fig.subplots_adjust(left=0.09, right=0.985, top=0.81, bottom=bottom_margin, hspace=1.05, wspace=0.34)
        fig._pies_export_mode = 'probe_type_model'
        fig._pies_export_chart_title = title
        fig._pies_export_ylabel = ylabel
        fig._pies_export_specs = [
            {
                'probe_type': probe_type,
                'model': model,
                'items': items,
            }
            for probe_type, model, items in subplot_specs
        ]
        fig._pies_export_value_formatter = formatter
        self.figures.append(fig)
        return fig
    
    def create_usage_chart(self, statistics: Dict[str, ProbeStatistics], 
                          figure_width: float | None = None,
                          figure_height: float | None = None) -> plt.Figure:
        """创建使用次数统计图"""
        try:
            if not statistics:
                return None

            grouped_items = self._group_statistics_by_probe_type_and_model(
                statistics,
                lambda stat: stat.total_uses,
            )
            return self._create_probe_type_model_subplots(
                grouped_items,
                '按探头类型区分的使用次数图',
                '使用次数',
                figure_width=figure_width,
                figure_height=figure_height,
                value_formatter=lambda v: f'{int(v)}',
            )
            
        except Exception as e:
            logger.error(f"创建使用次数图表时出错: {str(e)}")
            return None
    
    def create_lifetime_chart(self, statistics: Dict[str, ProbeStatistics], 
                            figure_width: float | None = None,
                            figure_height: float | None = None) -> plt.Figure:
        """创建使用寿命统计图"""
        try:
            if not statistics:
                return None

            grouped_items = self._group_statistics_by_probe_type_and_model(
                statistics,
                lambda stat: stat.total_duration_minutes / 60.0,
                keep_zero=True,
            )
            return self._create_probe_type_model_subplots(
                grouped_items,
                '按探头类型区分的使用时长图',
                '使用时长 /h',
                figure_width=figure_width,
                figure_height=figure_height,
                value_formatter=lambda v: f'{v:.1f}',
            )
            
        except Exception as e:
            logger.error(f"创建使用寿命图表时出错: {str(e)}")
            return None

    def create_tube_count_chart(self, statistics: Dict[str, ProbeStatistics],
                                figure_width: float | None = None,
                                figure_height: float | None = None) -> plt.Figure:
        """创建管道数量统计图（每根探头采集的管道数量）"""
        try:
            if not statistics:
                return None

            grouped_items = self._group_statistics_by_probe_type_and_model(
                statistics,
                lambda stat: stat.unique_tube_count,
            )
            return self._create_probe_type_model_subplots(
                grouped_items,
                '按探头类型区分的累计管道数量图',
                '管道数量',
                figure_width=figure_width,
                figure_height=figure_height,
                value_formatter=lambda v: f'{int(v)}',
            )

        except Exception as e:
            logger.error(f"创建使用试管数图表时出错: {str(e)}")
            return None
    
    def create_type_distribution_chart(self, statistics: Dict[str, ProbeStatistics]) -> plt.Figure:
        """创建探头类型分布图（按表格中的实际探头类型分类）"""
        try:
            # 从统计信息中提取实际的探头类型（使用probe_type_raw）
            type_counts = {}
            for stat in statistics.values():
                # 从records中获取probe_type_raw，如果有多条记录，取第一条的类型
                if stat.records:
                    probe_type_raw = stat.records[0].probe_type_raw if stat.records[0].probe_type_raw else "未知"
                else:
                    # 如果没有records，使用统计中的probe_type字符串作为后备
                    probe_type_raw = stat.probe_type or "未知"
                
                # 统计每种类型的探头数量
                if probe_type_raw not in type_counts:
                    type_counts[probe_type_raw] = 0
                type_counts[probe_type_raw] += 1
            
            if not type_counts:
                return None
            
            # 按数量排序（从多到少）
            sorted_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
            labels = [t[0] for t in sorted_types]
            sizes = [t[1] for t in sorted_types]
            
            base_colors = ['#4E79A7', '#6B8BA8', '#8BA6BF', '#A6B8C8', '#C1CDD7']
            colors = [base_colors[i % len(base_colors)] for i in range(len(labels))]
            
            fig_width = max(7.8, min(12.5, 7.8 + len(labels) * 0.55))
            fig, ax1 = plt.subplots(figsize=(fig_width, 6.4))

            explode = [0.02] * len(labels)
            wedges, texts, autotexts = ax1.pie(
                sizes,
                explode=explode,
                labels=labels,
                colors=colors,
                autopct='%1.1f%%',
                shadow=False,
                startangle=90,
                wedgeprops=dict(edgecolor='white', linewidth=1.2),
            )
            ax1.set_title('探头类型分布', fontsize=14, fontweight='bold')
            ax1.set_aspect('equal')
            ax1._pie_wedges = wedges
            ax1._pie_labels = labels
            ax1._pie_values = sizes
            
            plt.tight_layout()
            self.figures.append(fig)
            return fig
            
        except Exception as e:
            logger.error(f"创建类型分布图表时出错: {str(e)}")
            return None
    
    def create_timeline_chart(self, statistics: Dict[str, ProbeStatistics], 
                            probe_sn: str) -> plt.Figure:
        """创建单个探头的时间线图"""
        try:
            if probe_sn not in statistics:
                return None
            
            stat = statistics[probe_sn]
            if not stat.records:
                return None
            
            fig, ax = plt.subplots(figsize=(12, 6))
            
            # 绘制每个使用时间段
            for i, record in enumerate(stat.records):
                start = record.start_time
                duration = record.duration_minutes / 60.0  # 转换为小时
                
                ax.barh(i, duration, left=start, height=0.6, 
                       color='#366092', alpha=0.7, edgecolor='black')
            
            ax.set_xlabel('时间', fontsize=12)
            ax.set_ylabel('使用记录序号', fontsize=12)
            ax.set_title(f'探头 {probe_sn} 使用时间线', fontsize=14, fontweight='bold')
            ax.grid(axis='x', alpha=0.3)
            
            # 格式化x轴时间
            fig.autofmt_xdate()
            
            plt.tight_layout()
            self.figures.append(fig)
            return fig
            
        except Exception as e:
            logger.error(f"创建时间线图表时出错: {str(e)}")
            return None
    
    def create_operator_workload_chart(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建操作员工作量分布柱状图"""
        try:
            if not records:
                return None
            
            # 统计每个操作员的工作量
            operator_counts = Counter(record.operator for record in records if record.operator)
            
            if not operator_counts:
                return None
            
            # 按工作量排序
            sorted_operators = sorted(operator_counts.items(), key=lambda x: x[1], reverse=True)
            operators = [op[0] for op in sorted_operators]
            counts = [op[1] for op in sorted_operators]
            
            fig, ax = plt.subplots(figsize=(12, 6))
            
            # 生成从深到浅的渐变色（值越大颜色越深）
            colors = _generate_rank_gradient_colors(len(counts), base_color=self._ui_palette['blue'])
            
            bars = ax.bar(range(len(operators)), counts, color=colors, alpha=0.8, edgecolor='#1976D2', linewidth=1.5)
            
            ax.set_xlabel('操作员', fontsize=12, fontweight='bold')
            ax.set_ylabel('操作次数', fontsize=12, fontweight='bold')
            ax.set_title('操作员工作量分布', fontsize=14, fontweight='bold', pad=20)
            ax.set_xticks(range(len(operators)))
            ax.set_xticklabels(operators, rotation=45, ha='right')
            ax.grid(axis='y', alpha=0.3, linestyle='--')
            
            # 添加数值标签
            for i, bar in enumerate(bars):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{int(height)}',
                       ha='center', va='bottom', fontsize=10, fontweight='bold')
            
            plt.tight_layout()
            self.figures.append(fig)
            return fig
            
        except Exception as e:
            logger.error(f"创建操作员工作量图表时出错: {str(e)}")
            return None
    
    def create_operator_workload_summary_chart(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建操作员工作量与检测时长综合图。"""
        try:
            if not records:
                return None

            operator_summary = defaultdict(lambda: {'count': 0, 'minutes': 0.0})
            for record in records:
                operator = (getattr(record, 'operator', '') or '').strip()
                if not operator:
                    continue
                operator_summary[operator]['count'] += 1
                operator_summary[operator]['minutes'] += float(getattr(record, 'duration_minutes', 0.0) or 0.0)

            if not operator_summary:
                return None

            sorted_items = sorted(
                operator_summary.items(),
                key=lambda item: (item[1]['count'], item[1]['minutes']),
                reverse=True,
            )
            operators = [item[0] for item in sorted_items]
            counts = [item[1]['count'] for item in sorted_items]
            hours = [item[1]['minutes'] / 60.0 for item in sorted_items]

            fig_width = max(10, min(16, len(operators) * 0.9))
            fig, ax1 = plt.subplots(figsize=(fig_width, 6.4))
            bar_colors = _generate_rank_gradient_colors(len(counts), base_color=self._ui_palette['blue'])
            bars = ax1.bar(range(len(operators)), counts, color=bar_colors, edgecolor='#1F4E79', linewidth=1.2, alpha=0.9)
            ax1.set_xlabel('操作员', fontsize=12, fontweight='bold')
            ax1.set_ylabel('工作量(次)', fontsize=12, fontweight='bold', color='#1F4E79')
            ax1.set_xticks(range(len(operators)))
            ax1.set_xticklabels(operators, rotation=35, ha='right')
            ax1.tick_params(axis='y', labelcolor='#1F4E79')
            ax1.grid(axis='y', alpha=0.25, linestyle='--')

            ax2 = ax1.twinx()
            ax2.plot(range(len(operators)), hours, color='#D97706', marker='o', linewidth=2.1, markersize=5.5)
            ax2.set_ylabel('检测时长(小时)', fontsize=12, fontweight='bold', color='#B45309')
            ax2.tick_params(axis='y', labelcolor='#B45309')

            max_count = max(counts) if counts else 0
            for bar, count in zip(bars, counts):
                ax1.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + (max_count * 0.02 if max_count > 0 else 0.1),
                    f'{int(count)}次',
                    ha='center',
                    va='bottom',
                    fontsize=9,
                    color='#1F2937',
                )

            max_hours = max(hours) if hours else 0
            for x_pos, hour in enumerate(hours):
                ax2.text(
                    x_pos,
                    hour + (max_hours * 0.03 if max_hours > 0 else 0.1),
                    f'{hour:.1f}h',
                    ha='center',
                    va='bottom',
                    fontsize=9,
                    color='#B45309',
                )

            fig.suptitle('操作员工作量与检测时长分析', fontsize=15, fontweight='bold', y=0.98)
            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建操作员工作量与检测时长综合图时出错: {str(e)}")
            return None

    def create_probe_type_duration_histogram(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建探针类型持续时间分布直方图"""
        try:
            if not records:
                return None
            
            # 按探头类型分组
            type_durations = defaultdict(list)
            for record in records:
                if record.probe_type_raw:  # 使用原始探头类型值
                    duration = record.duration_minutes
                    if duration > 0:
                        type_durations[record.probe_type_raw].append(duration)
            
            if not type_durations:
                return None
            
            # 创建子图
            n_types = len(type_durations)
            fig, axes = plt.subplots(1, n_types, figsize=(6 * n_types, 6))
            if n_types == 1:
                axes = [axes]
            
            colors = plt.cm.Set3(range(n_types))
            
            for idx, (probe_type, durations) in enumerate(type_durations.items()):
                ax = axes[idx]
                
                # 创建直方图
                n, bins, patches = ax.hist(durations, bins=20, color=colors[idx], alpha=0.7, 
                                         edgecolor='black', linewidth=1.2)
                
                # 设置颜色渐变
                for i, patch in enumerate(patches):
                    patch.set_facecolor(plt.cm.Blues(0.3 + 0.5 * i / len(patches)))
                
                # 在柱状图上添加数值标签
                for i, (patch, count) in enumerate(zip(patches, n)):
                    if count > 0:  # 只显示非零的柱子
                        # 获取柱子的位置和高度
                        x = patch.get_x() + patch.get_width() / 2
                        height = patch.get_height()
                        # 在柱子顶部添加标签
                        ax.text(x, height, f'{int(count)}',
                               ha='center', va='bottom', fontsize=8)
                
                ax.set_xlabel('持续时间（分钟）', fontsize=11, fontweight='bold')
                ax.set_ylabel('频次', fontsize=11, fontweight='bold')
                ax.set_title(f'{probe_type} 持续时间分布', fontsize=12, fontweight='bold')
                ax.grid(axis='y', alpha=0.3, linestyle='--')
                
                # 添加统计信息
                mean_duration = sum(durations) / len(durations)
                ax.axvline(mean_duration, color='red', linestyle='--', linewidth=2, 
                          label=f'平均值: {mean_duration:.1f}分钟')
                ax.legend()
            
            plt.tight_layout()
            self.figures.append(fig)
            return fig
            
        except Exception as e:
            logger.error(f"创建探针类型持续时间分布图表时出错: {str(e)}")
            return None
    
    
    
    def create_model_distribution_bar_chart(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建型号操作分布柱状图（纵向），展示全部型号"""
        try:
            if not records:
                return None
            model_counts = Counter(record.model for record in records if record.model)
            if not model_counts:
                return None
            # 展示全部型号，按次数从高到低排序
            sorted_models = sorted(model_counts.items(), key=lambda x: x[1], reverse=True)
            models = [m[0] for m in sorted_models]
            counts = [m[1] for m in sorted_models]
            total = sum(counts)
            percents = [c / total * 100 if total else 0 for c in counts]
            
            # 根据型号数量动态调整图表大小（整体相对缩小一些，避免过大）
            num_models = len(models)
            # 宽度：随型号数量变化，但上限调小
            fig_width = max(10, min(16, num_models * 0.6))
            # 高度：适当降低，避免过高
            fig_height = max(6, min(10, num_models * 0.25))
            
            fig, ax = plt.subplots(figsize=(fig_width, fig_height))
            colors = _generate_rank_gradient_colors(len(counts), base_color=self._ui_palette['blue'])
            bars = ax.bar(range(len(models)), counts, color=colors, edgecolor='#1E88E5', linewidth=1.2, alpha=0.9)
            ax.set_xlabel('型号', fontsize=12, fontweight='bold')
            ax.set_ylabel('次数', fontsize=12, fontweight='bold')
            ax.set_title('型号操作分布', fontsize=16, fontweight='bold', pad=18)
            ax.set_xticks(range(len(models)))
            ax.set_xticklabels(models, rotation=45, ha='right')
            max_val = max(counts) if counts else 0
            ax.set_ylim(0, max_val * 1.15 if max_val > 0 else 1)
            ax.grid(axis='y', alpha=0.3, linestyle='--')
            
            # 在柱状图顶部添加数值标签
            for i, bar in enumerate(bars):
                height = bar.get_height()
                label = f'{int(height)} 次\n{percents[i]:.1f}%'
                ax.text(bar.get_x() + bar.get_width() / 2, height + max_val * 0.02,
                        label, va='bottom', ha='center', fontsize=9, color='#424242')
            
            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建型号分布柱状图时出错: {str(e)}")
            return None
    
    def create_model_distribution_pie_chart(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建探头型号分布饼图。"""
        try:
            if not records:
                return None

            unique_probes = {}
            for record in records:
                stat_key = getattr(record, 'stat_key', '') or ''
                if not stat_key or stat_key in unique_probes:
                    continue
                model = normalize_model_name(getattr(record, 'model', '') or '')
                if model:
                    unique_probes[stat_key] = model

            model_counts = Counter(unique_probes.values())
            if not model_counts:
                return None

            sorted_models = sorted(model_counts.items(), key=lambda item: item[1], reverse=True)
            labels = [item[0] for item in sorted_models]
            sizes = [item[1] for item in sorted_models]
            gradient_stops = [
                '#4E79A7',
                '#7FA2C4',
                '#A9C0DA',
                '#D0DEEE',
                '#E7EEF7',
            ]
            colors = [gradient_stops[min(i, len(gradient_stops) - 1)] for i in range(len(labels))]

            fig_width = max(8.8, min(15.0, 8.8 + len(labels) * 0.35))
            fig, ax = plt.subplots(figsize=(fig_width, 6.6))
            wedges, texts, autotexts = ax.pie(
                sizes,
                labels=None,
                colors=colors,
                startangle=90,
                autopct=lambda pct: f'{pct:.1f}%',
                pctdistance=1.12,
                textprops=dict(fontsize=8.5, color='#111827'),
                wedgeprops=dict(edgecolor='white', linewidth=1.2),
            )
            for wedge, autotext in zip(wedges, autotexts):
                angle = (wedge.theta1 + wedge.theta2) / 2.0
                radius = 1.12
                x = radius * np.cos(np.deg2rad(angle))
                y = radius * np.sin(np.deg2rad(angle))
                autotext.set_position((x, y))
                autotext.set_ha('left' if x >= 0 else 'right')
                autotext.set_va('center')
            ax.legend(
                wedges,
                [f'{label} ({count})' for label, count in zip(labels, sizes)],
                title='探头型号',
                loc='center left',
                bbox_to_anchor=(1.02, 0.5),
                frameon=False,
                fontsize=9,
                title_fontsize=10,
            )
            ax.set_title('探头型号分布', fontsize=15, fontweight='bold', pad=16)
            ax.set_aspect('equal')
            ax._pie_wedges = wedges
            ax._pie_labels = labels
            ax._pie_values = sizes
            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建探头型号分布饼图时出错: {str(e)}")
            return None

    def create_sg_tube_workload_chart(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建蒸汽发生器检测量柱状图。"""
        try:
            if not records:
                return None

            sg_tube_counts = defaultdict(int)
            for record in records:
                sg_id = (getattr(record, 'sg_id', '') or '').strip()
                tube_number = int(getattr(record, 'tube_number', 0) or 0)
                if sg_id and tube_number > 0:
                    sg_tube_counts[sg_id] += tube_number

            if not sg_tube_counts:
                return None

            sorted_items = sorted(sg_tube_counts.items(), key=lambda item: item[1], reverse=True)
            sg_ids = [item[0] for item in sorted_items]
            counts = [item[1] for item in sorted_items]

            fig_width = max(10, min(16, len(sg_ids) * 1.1))
            fig, ax = plt.subplots(figsize=(fig_width, 6.2))
            colors = _generate_rank_gradient_colors(len(counts), base_color=self._ui_palette['blue'])
            bars = ax.bar(range(len(sg_ids)), counts, color=colors, edgecolor='#1F4E79', linewidth=1.2, alpha=0.9)

            ax.set_xlabel('蒸汽发生器编号', fontsize=12, fontweight='bold')
            ax.set_ylabel('检测管道数量', fontsize=12, fontweight='bold')
            ax.set_title('蒸汽发生器检测量分布', fontsize=15, fontweight='bold', pad=18)
            ax.set_xticks(range(len(sg_ids)))
            ax.set_xticklabels(sg_ids, rotation=30, ha='right')
            ax.grid(axis='y', alpha=0.3, linestyle='--')

            max_val = max(counts) if counts else 0
            for bar, count in zip(bars, counts):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max_val * 0.02, f'{int(count)}',
                        ha='center', va='bottom', fontsize=9, color='#334155')

            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建蒸汽发生器检测量柱状图时出错: {str(e)}")
            return None

    def create_outage_tube_workload_chart(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建大修检测量柱状图。"""
        try:
            if not records:
                return None

            outage_tube_counts = defaultdict(int)
            for record in records:
                outage = (getattr(record, 'outage', '') or '').strip()
                tube_number = int(getattr(record, 'tube_number', 0) or 0)
                if outage and tube_number > 0:
                    outage_tube_counts[outage] += tube_number

            if not outage_tube_counts:
                return None

            sorted_items = sorted(outage_tube_counts.items(), key=lambda item: item[1], reverse=True)
            outages = [item[0] for item in sorted_items]
            counts = [item[1] for item in sorted_items]

            fig_width = max(8, min(14, len(outages) * 1.2))
            fig, ax = plt.subplots(figsize=(fig_width, 6.0))
            colors = _generate_rank_gradient_colors(len(counts), base_color=self._ui_palette['sand'])
            bars = ax.bar(range(len(outages)), counts, color=colors, edgecolor='#B45309', linewidth=1.2, alpha=0.92)

            ax.set_xlabel('大修', fontsize=12, fontweight='bold')
            ax.set_ylabel('检测管道数量', fontsize=12, fontweight='bold')
            ax.set_title('大修检测量对比', fontsize=15, fontweight='bold', pad=18)
            ax.set_xticks(range(len(outages)))
            ax.set_xticklabels(outages, rotation=0, ha='center')
            ax.grid(axis='y', alpha=0.3, linestyle='--')

            max_val = max(counts) if counts else 0
            for bar, count in zip(bars, counts):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max_val * 0.025, f'{int(count)}',
                        ha='center', va='bottom', fontsize=9, color='#7C2D12')

            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建大修检测量柱状图时出错: {str(e)}")
            return None

    def create_operator_duration_chart(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建操作员检测时长柱状图。"""
        try:
            if not records:
                return None

            operator_minutes = defaultdict(float)
            for record in records:
                operator = (getattr(record, 'operator', '') or '').strip()
                duration_minutes = float(getattr(record, 'duration_minutes', 0.0) or 0.0)
                if operator and duration_minutes > 0:
                    operator_minutes[operator] += duration_minutes

            if not operator_minutes:
                return None

            sorted_items = sorted(operator_minutes.items(), key=lambda item: item[1], reverse=True)
            operators = [item[0] for item in sorted_items]
            hours = [item[1] / 60.0 for item in sorted_items]

            fig_width = max(10, min(16, len(operators) * 0.8))
            fig, ax = plt.subplots(figsize=(fig_width, 6.2))
            colors = _generate_rank_gradient_colors(len(hours), base_color=self._ui_palette['teal'])
            bars = ax.bar(range(len(operators)), hours, color=colors, edgecolor='#0F766E', linewidth=1.2, alpha=0.9)

            ax.set_xlabel('操作员', fontsize=12, fontweight='bold')
            ax.set_ylabel('检测时长(小时)', fontsize=12, fontweight='bold')
            ax.set_title('操作员检测时长分布', fontsize=15, fontweight='bold', pad=18)
            ax.set_xticks(range(len(operators)))
            ax.set_xticklabels(operators, rotation=35, ha='right')
            ax.grid(axis='y', alpha=0.3, linestyle='--')

            max_val = max(hours) if hours else 0
            for bar, hour in zip(bars, hours):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max_val * 0.02, f'{hour:.1f}h',
                        ha='center', va='bottom', fontsize=9, color='#134E4A')

            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建操作员检测时长柱状图时出错: {str(e)}")
            return None

    def create_sg_average_speed_chart(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建按蒸汽发生器分组的平均检测速度柱状图。"""
        try:
            if not records:
                return None

            sg_totals = defaultdict(lambda: {'tube': 0, 'minutes': 0.0})
            for record in records:
                sg_id = (getattr(record, 'sg_id', '') or '').strip()
                tube_number = int(getattr(record, 'tube_number', 0) or 0)
                duration_minutes = float(getattr(record, 'duration_minutes', 0.0) or 0.0)
                if sg_id and tube_number > 0 and duration_minutes > 0:
                    sg_totals[sg_id]['tube'] += tube_number
                    sg_totals[sg_id]['minutes'] += duration_minutes

            if not sg_totals:
                return None

            speed_items = []
            for sg_id, totals in sg_totals.items():
                hours = totals['minutes'] / 60.0
                if hours <= 0:
                    continue
                speed_items.append((sg_id, totals['tube'] / hours))

            if not speed_items:
                return None

            speed_items.sort(key=lambda item: item[1], reverse=True)
            sg_ids = [item[0] for item in speed_items]
            speeds = [item[1] for item in speed_items]

            fig_width = max(10, min(16, len(sg_ids) * 1.05))
            fig, ax = plt.subplots(figsize=(fig_width, 6.1))
            colors = _generate_rank_gradient_colors(len(speeds), base_color=self._ui_palette['blue'])
            bars = ax.bar(range(len(sg_ids)), speeds, color=colors, edgecolor='#1D4ED8', linewidth=1.2, alpha=0.9)

            ax.set_xlabel('蒸汽发生器编号', fontsize=12, fontweight='bold')
            ax.set_ylabel('平均检测速度(管道/小时)', fontsize=12, fontweight='bold')
            ax.set_title('蒸汽发生器平均检测速度对比', fontsize=15, fontweight='bold', pad=18)
            ax.set_xticks(range(len(sg_ids)))
            ax.set_xticklabels(sg_ids, rotation=30, ha='right')
            ax.grid(axis='y', alpha=0.3, linestyle='--')

            max_val = max(speeds) if speeds else 0
            for bar, speed in zip(bars, speeds):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max_val * 0.02, f'{speed:.1f}',
                        ha='center', va='bottom', fontsize=9, color='#1E3A8A')

            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建蒸汽发生器平均检测速度对比图时出错: {str(e)}")
            return None

    def create_outage_average_lifetime_chart(self, statistics: Dict[str, ProbeStatistics]) -> plt.Figure:
        """创建按大修分组的探头平均寿命对比图。"""
        try:
            if not statistics:
                return None

            outage_lifetimes = defaultdict(list)
            for stat in statistics.values():
                outage_values = {
                    (getattr(record, 'outage', '') or '').strip()
                    for record in getattr(stat, 'records', []) or []
                    if (getattr(record, 'outage', '') or '').strip()
                }
                if not outage_values:
                    continue
                lifetime_hours = float(getattr(stat, 'total_duration_minutes', 0.0) or 0.0) / 60.0
                if lifetime_hours <= 0:
                    continue
                for outage in outage_values:
                    outage_lifetimes[outage].append(lifetime_hours)

            if not outage_lifetimes:
                return None

            avg_items = []
            for outage, lifetimes in outage_lifetimes.items():
                if lifetimes:
                    avg_items.append((outage, sum(lifetimes) / len(lifetimes), len(lifetimes)))

            if not avg_items:
                return None

            avg_items.sort(key=lambda item: item[1], reverse=True)
            outages = [item[0] for item in avg_items]
            avg_hours = [item[1] for item in avg_items]
            sample_counts = [item[2] for item in avg_items]

            fig_width = max(8, min(14, len(outages) * 1.15))
            fig, ax = plt.subplots(figsize=(fig_width, 6.0))
            colors = _generate_rank_gradient_colors(len(avg_hours), base_color=self._ui_palette['slate'])
            bars = ax.bar(range(len(outages)), avg_hours, color=colors, edgecolor='#6D28D9', linewidth=1.2, alpha=0.92)

            ax.set_xlabel('大修', fontsize=12, fontweight='bold')
            ax.set_ylabel('平均探头寿命(小时)', fontsize=12, fontweight='bold')
            ax.set_title('大修平均探头寿命对比', fontsize=15, fontweight='bold', pad=18)
            ax.set_xticks(range(len(outages)))
            ax.set_xticklabels(outages, rotation=0, ha='center')
            ax.grid(axis='y', alpha=0.3, linestyle='--')

            max_val = max(avg_hours) if avg_hours else 0
            for bar, avg_hour, sample_count in zip(bars, avg_hours, sample_counts):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max_val * 0.025, f'{avg_hour:.1f}h\\nn={sample_count}',
                        ha='center', va='bottom', fontsize=8.5, color='#4C1D95')

            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建大修平均探头寿命对比图时出错: {str(e)}")
            return None

    def create_model_average_speed_chart(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建按型号分组的平均检测速度柱状图。"""
        try:
            if not records:
                return None

            model_totals = defaultdict(lambda: {'tube': 0, 'minutes': 0.0})
            for record in records:
                model = (getattr(record, 'model', '') or '').strip()
                tube_number = int(getattr(record, 'tube_number', 0) or 0)
                duration_minutes = float(getattr(record, 'duration_minutes', 0.0) or 0.0)
                if model and tube_number > 0 and duration_minutes > 0:
                    model_totals[model]['tube'] += tube_number
                    model_totals[model]['minutes'] += duration_minutes

            model_items = []
            for model, totals in model_totals.items():
                hours = totals['minutes'] / 60.0
                if hours > 0:
                    model_items.append((model, totals['tube'] / hours))

            if not model_items:
                return None

            model_items.sort(key=lambda item: item[1], reverse=True)
            models = [item[0] for item in model_items]
            speeds = [item[1] for item in model_items]

            fig_width = max(10, min(18, len(models) * 0.95))
            fig, ax = plt.subplots(figsize=(fig_width, 6.2))
            colors = _generate_rank_gradient_colors(len(speeds), base_color=self._ui_palette['teal'])
            bars = ax.bar(range(len(models)), speeds, color=colors, edgecolor='#115E59', linewidth=1.2, alpha=0.9)

            ax.set_xlabel('探头型号', fontsize=12, fontweight='bold')
            ax.set_ylabel('平均检测速度(管道/小时)', fontsize=12, fontweight='bold')
            ax.set_title('探头型号平均检测速度对比', fontsize=15, fontweight='bold', pad=18)
            ax.set_xticks(range(len(models)))
            ax.set_xticklabels(models, rotation=35, ha='right')
            ax.grid(axis='y', alpha=0.3, linestyle='--')

            max_val = max(speeds) if speeds else 0
            for bar, speed in zip(bars, speeds):
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max_val * 0.02,
                    f'{speed:.1f}',
                    ha='center',
                    va='bottom',
                    fontsize=9,
                    color='#134E4A',
                )

            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建探头型号平均检测速度对比图时出错: {str(e)}")
            return None

    def create_probe_type_average_duration_chart(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建按探头类型分组的平均单次时长柱状图。"""
        try:
            if not records:
                return None

            type_durations = defaultdict(list)
            for record in records:
                probe_type = (getattr(record, 'probe_type_raw', None) or getattr(record, 'probe_type', '') or '').strip()
                duration_minutes = float(getattr(record, 'duration_minutes', 0.0) or 0.0)
                if probe_type and duration_minutes > 0:
                    type_durations[probe_type].append(duration_minutes)

            if not type_durations:
                return None

            avg_items = sorted(
                ((probe_type, sum(values) / len(values), len(values)) for probe_type, values in type_durations.items()),
                key=lambda item: item[1],
                reverse=True,
            )
            probe_types = [item[0] for item in avg_items]
            avg_minutes = [item[1] for item in avg_items]
            counts = [item[2] for item in avg_items]

            fig_width = max(8, min(14, len(probe_types) * 1.3))
            fig, ax = plt.subplots(figsize=(fig_width, 6.0))
            colors = _generate_rank_gradient_colors(len(avg_minutes), base_color=self._ui_palette['slate'])
            bars = ax.bar(range(len(probe_types)), avg_minutes, color=colors, edgecolor='#7E22CE', linewidth=1.2, alpha=0.92)

            ax.set_xlabel('探头类型', fontsize=12, fontweight='bold')
            ax.set_ylabel('平均单次时长(分钟)', fontsize=12, fontweight='bold')
            ax.set_title('探头类型平均单次时长对比', fontsize=15, fontweight='bold', pad=18)
            ax.set_xticks(range(len(probe_types)))
            ax.set_xticklabels(probe_types, rotation=0, ha='center')
            ax.grid(axis='y', alpha=0.3, linestyle='--')

            max_val = max(avg_minutes) if avg_minutes else 0
            for bar, avg_minute, count in zip(bars, avg_minutes, counts):
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max_val * 0.025,
                    f'{avg_minute:.1f}m\nn={count}',
                    ha='center',
                    va='bottom',
                    fontsize=8.5,
                    color='#581C87',
                )

            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建探头类型平均单次时长对比图时出错: {str(e)}")
            return None

    def create_operator_outage_heatmap(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建操作员与大修覆盖热力图。"""
        try:
            if not records:
                return None

            matrix = defaultdict(lambda: defaultdict(int))
            operators = set()
            outages = set()
            for record in records:
                operator = (getattr(record, 'operator', '') or '').strip()
                outage = (getattr(record, 'outage', '') or '').strip()
                tube_number = int(getattr(record, 'tube_number', 0) or 0)
                if operator and outage and tube_number > 0:
                    matrix[operator][outage] += tube_number
                    operators.add(operator)
                    outages.add(outage)

            if not operators or not outages:
                return None

            operators = sorted(operators)
            outages = sorted(outages)
            data = [[matrix[operator].get(outage, 0) for outage in outages] for operator in operators]

            fig_width = max(8.5, min(18, len(outages) * 1.3))
            fig_height = max(5.5, min(12, len(operators) * 0.55 + 2.5))
            fig, ax = plt.subplots(figsize=(fig_width, fig_height))
            image = ax.imshow(data, cmap='YlGnBu', aspect='auto')

            ax.set_title('操作员与大修检测覆盖热力图', fontsize=15, fontweight='bold', pad=16)
            ax.set_xlabel('大修', fontsize=12, fontweight='bold')
            ax.set_ylabel('操作员', fontsize=12, fontweight='bold')
            ax.set_xticks(range(len(outages)))
            ax.set_xticklabels(outages, rotation=30, ha='right')
            ax.set_yticks(range(len(operators)))
            ax.set_yticklabels(operators)

            max_value = max(max(row) for row in data) if data else 0
            threshold = max_value * 0.55 if max_value else 0
            for row_index, row in enumerate(data):
                for col_index, value in enumerate(row):
                    if value <= 0:
                        continue
                    ax.text(
                        col_index,
                        row_index,
                        str(int(value)),
                        ha='center',
                        va='center',
                        fontsize=8,
                        color='white' if value >= threshold else '#0F172A',
                    )

            cbar = fig.colorbar(image, ax=ax, pad=0.02)
            cbar.set_label('检测管道数量', rotation=90)

            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建操作员与大修覆盖热力图时出错: {str(e)}")
            return None

    def create_daily_tube_trend_chart(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建按日期统计的检测量趋势图。"""
        try:
            if not records:
                return None

            daily_tubes = defaultdict(int)
            for record in records:
                start_time = getattr(record, 'start_time', None)
                tube_number = int(getattr(record, 'tube_number', 0) or 0)
                if start_time and tube_number > 0:
                    daily_tubes[start_time.strftime('%Y-%m-%d')] += tube_number

            if not daily_tubes:
                return None

            dates = sorted(daily_tubes.keys())
            values = [daily_tubes[date] for date in dates]

            fig_width = max(10, min(18, len(dates) * 0.55))
            fig, ax = plt.subplots(figsize=(fig_width, 5.8))
            ax.plot(dates, values, color='#2563EB', marker='o', linewidth=2.2, markersize=5.5)
            ax.fill_between(range(len(dates)), values, color='#93C5FD', alpha=0.22)
            ax.set_title('按日期的检测量趋势', fontsize=15, fontweight='bold', pad=16)
            ax.set_xlabel('日期', fontsize=12, fontweight='bold')
            ax.set_ylabel('检测管道数量', fontsize=12, fontweight='bold')
            ax.set_xticks(range(len(dates)))
            ax.set_xticklabels(dates, rotation=35, ha='right')
            ax.grid(axis='y', alpha=0.3, linestyle='--')
            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建按日期的检测量趋势图时出错: {str(e)}")
            return None

    def create_daily_duration_trend_chart(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建按日期统计的检测时长趋势图。"""
        try:
            if not records:
                return None

            daily_minutes = defaultdict(float)
            for record in records:
                start_time = getattr(record, 'start_time', None)
                duration_minutes = float(getattr(record, 'duration_minutes', 0.0) or 0.0)
                if start_time and duration_minutes > 0:
                    daily_minutes[start_time.strftime('%Y-%m-%d')] += duration_minutes

            if not daily_minutes:
                return None

            dates = sorted(daily_minutes.keys())
            hours = [daily_minutes[date] / 60.0 for date in dates]

            fig_width = max(10, min(18, len(dates) * 0.55))
            fig, ax = plt.subplots(figsize=(fig_width, 5.8))
            ax.plot(dates, hours, color=self._ui_palette['teal'], marker='o', linewidth=2.2, markersize=5.5)
            ax.fill_between(range(len(dates)), hours, color=self._ui_palette['teal_light'], alpha=0.24)
            ax.set_title('按日期的检测时长趋势', fontsize=15, fontweight='bold', pad=16)
            ax.set_xlabel('日期', fontsize=12, fontweight='bold')
            ax.set_ylabel('检测时长(小时)', fontsize=12, fontweight='bold')
            ax.set_xticks(range(len(dates)))
            ax.set_xticklabels(dates, rotation=35, ha='right')
            ax.grid(axis='y', alpha=0.3, linestyle='--')
            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建按日期的检测时长趋势图时出错: {str(e)}")
            return None

    def create_operator_daily_workload_trend_chart(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建操作员日工作量趋势图。"""
        try:
            if not records:
                return None

            matrix = defaultdict(lambda: defaultdict(int))
            operators = set()
            dates = set()
            for record in records:
                operator = (getattr(record, 'operator', '') or '').strip()
                start_time = getattr(record, 'start_time', None)
                tube_number = int(getattr(record, 'tube_number', 0) or 0)
                if operator and start_time and tube_number > 0:
                    date_key = start_time.strftime('%Y-%m-%d')
                    matrix[operator][date_key] += tube_number
                    operators.add(operator)
                    dates.add(date_key)

            if not operators or not dates:
                return None

            operators = sorted(operators)
            dates = sorted(dates)
            if len(operators) > 6:
                operator_totals = sorted(
                    ((operator, sum(matrix[operator].values())) for operator in operators),
                    key=lambda item: item[1],
                    reverse=True,
                )[:6]
                operators = [item[0] for item in operator_totals]

            fig_width = max(10, min(18, len(dates) * 0.55))
            fig, ax = plt.subplots(figsize=(fig_width, 6.0))
            palette = self._chart_series_palette

            for index, operator in enumerate(operators):
                values = [matrix[operator].get(date, 0) for date in dates]
                ax.plot(
                    dates,
                    values,
                    marker='o',
                    linewidth=2.0,
                    markersize=4.5,
                    label=operator,
                    color=palette[index % len(palette)],
                )

            ax.set_title('按操作员的日工作量趋势', fontsize=15, fontweight='bold', pad=16)
            ax.set_xlabel('日期', fontsize=12, fontweight='bold')
            ax.set_ylabel('检测管道数量', fontsize=12, fontweight='bold')
            ax.set_xticks(range(len(dates)))
            ax.set_xticklabels(dates, rotation=35, ha='right')
            ax.grid(axis='y', alpha=0.3, linestyle='--')
            ax.legend(loc='upper left', fontsize=9)
            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建按操作员的日工作量趋势图时出错: {str(e)}")
            return None

    def create_detection_speed_chart(self, statistics: dict, 
                                   figure_width: float | None = None,
                                   figure_height: float | None = None) -> plt.Figure:
        """创建探头检测速度统计图（管道数量/小时）"""
        try:
            if not statistics:
                return None

            grouped_items = self._group_statistics_by_probe_type_and_model(
                statistics,
                lambda stat: (stat.unique_tube_count / (stat.total_duration_minutes / 60.0))
                if stat.total_duration_minutes > 0 else 0.0,
            )
            return self._create_probe_type_model_subplots(
                grouped_items,
                '按探头类型区分的检测速度图',
                '检测速度（管道/小时）',
                figure_width=figure_width,
                figure_height=figure_height,
                value_formatter=lambda v: f'{v:.1f}',
            )
        except Exception as e:
            logger.error(f"创建探头检测速度图表时出错: {str(e)}")
            return None
    
    def create_sg_tube_workload_chart_by_outage(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建按大修拆分的蒸汽发生器检测量图。"""
        try:
            if not records:
                return None

            outage_sg_tube_counts = defaultdict(lambda: defaultdict(int))
            for record in records:
                outage = self._normalize_outage_label(getattr(record, 'outage', ''))
                ring_label = self._normalize_sg_ring_label(getattr(record, 'sg_id', ''))
                tube_number = int(getattr(record, 'tube_number', 0) or 0)
                if ring_label and tube_number > 0:
                    outage_sg_tube_counts[outage][ring_label] += tube_number

            if not outage_sg_tube_counts:
                return None

            outages = sorted(outage_sg_tube_counts.keys(), key=self._outage_sort_key)
            ring_count = max(len(ring_map) for ring_map in outage_sg_tube_counts.values())
            fig, axes = self._create_vertical_outage_axes(
                len(outages),
                base_width=max(9.8, min(15.0, ring_count * 1.7 + 5.4)),
                row_height=4.0 if len(outages) == 1 else 3.8,
                max_width=16.0,
                max_height=22.0,
            )
            ring_colors = {'1环': '#4E79A7', '2环': '#5E8C8A', '3环': '#7B8794'}
            global_max = max((max(ring_map.values(), default=0) for ring_map in outage_sg_tube_counts.values()), default=0)

            for ax, outage in zip(axes, outages):
                sorted_items = sorted(outage_sg_tube_counts[outage].items(), key=lambda item: self._sg_ring_sort_key(item[0]))
                ring_labels = [item[0] for item in sorted_items]
                counts = [item[1] for item in sorted_items]
                colors = [ring_colors.get(label, self._ui_palette['slate_mid']) for label in ring_labels]
                bars = ax.bar(range(len(ring_labels)), counts, color=colors, edgecolor=self._ui_palette['ink'], linewidth=1.0, alpha=0.92)

                ax.set_facecolor(self._ui_palette['panel'])
                ax.set_title(outage, fontsize=12.5, fontweight='bold', pad=10, color='#243447')
                ax.set_ylabel('检测量(根)', fontsize=11, fontweight='bold')
                ax.set_xticks(range(len(ring_labels)))
                ax.set_xticklabels(ring_labels, rotation=0, ha='center')
                ax.grid(axis='y', alpha=0.28, linestyle='--')
                ax.set_axisbelow(True)
                ax.set_ylim(0, global_max * 1.16 if global_max > 0 else 1)

                label_offset = global_max * 0.025 if global_max > 0 else 0.2
                for bar, count in zip(bars, counts):
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + label_offset,
                        f'{int(count)}',
                        ha='center',
                        va='bottom',
                        fontsize=9,
                        color=self._ui_palette['ink'],
                    )

            axes[-1].set_xlabel('蒸汽发生器环号', fontsize=12, fontweight='bold')
            fig.suptitle('蒸汽发生器检测量分布（按大修分组）', fontsize=15, fontweight='bold', y=0.99)
            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建按大修拆分的蒸汽发生器检测量图时出错: {str(e)}")
            return None

    def create_sg_average_speed_chart_by_outage(self, records: List[ProbeRecord]) -> plt.Figure:
        """创建按大修拆分的蒸汽发生器平均检测速度图。"""
        try:
            if not records:
                return None

            outage_sg_totals = defaultdict(lambda: defaultdict(lambda: {'tube': 0, 'minutes': 0.0}))
            for record in records:
                outage = self._normalize_outage_label(getattr(record, 'outage', ''))
                ring_label = self._normalize_sg_ring_label(getattr(record, 'sg_id', ''))
                tube_number = int(getattr(record, 'tube_number', 0) or 0)
                duration_minutes = float(getattr(record, 'duration_minutes', 0.0) or 0.0)
                if ring_label and tube_number > 0 and duration_minutes > 0:
                    outage_sg_totals[outage][ring_label]['tube'] += tube_number
                    outage_sg_totals[outage][ring_label]['minutes'] += duration_minutes

            outage_speed_items = {}
            for outage, ring_map in outage_sg_totals.items():
                items = []
                for ring_label, totals in ring_map.items():
                    hours = totals['minutes'] / 60.0
                    if hours > 0:
                        items.append((ring_label, totals['tube'] / hours))
                if items:
                    outage_speed_items[outage] = sorted(items, key=lambda item: self._sg_ring_sort_key(item[0]))

            if not outage_speed_items:
                return None

            outages = sorted(outage_speed_items.keys(), key=self._outage_sort_key)
            ring_count = max(len(items) for items in outage_speed_items.values())
            fig, axes = self._create_vertical_outage_axes(
                len(outages),
                base_width=max(9.8, min(15.0, ring_count * 1.7 + 5.6)),
                row_height=4.0 if len(outages) == 1 else 3.9,
                max_width=16.0,
                max_height=22.0,
            )
            ring_colors = {'1环': '#4E79A7', '2环': '#5E8C8A', '3环': '#7B8794'}
            global_max = max((max((speed for _, speed in items), default=0.0) for items in outage_speed_items.values()), default=0.0)

            for ax, outage in zip(axes, outages):
                items = outage_speed_items[outage]
                ring_labels = [item[0] for item in items]
                speeds = [item[1] for item in items]
                colors = [ring_colors.get(label, self._ui_palette['slate_mid']) for label in ring_labels]
                bars = ax.bar(range(len(ring_labels)), speeds, color=colors, edgecolor=self._ui_palette['ink'], linewidth=1.0, alpha=0.92)

                ax.set_facecolor(self._ui_palette['panel'])
                ax.set_title(outage, fontsize=12.5, fontweight='bold', pad=10, color='#243447')
                ax.set_ylabel('平均检测速度(根/小时)', fontsize=11, fontweight='bold')
                ax.set_xticks(range(len(ring_labels)))
                ax.set_xticklabels(ring_labels, rotation=0, ha='center')
                ax.grid(axis='y', alpha=0.28, linestyle='--')
                ax.set_axisbelow(True)
                ax.set_ylim(0, global_max * 1.16 if global_max > 0 else 1)

                label_offset = global_max * 0.025 if global_max > 0 else 0.2
                for bar, speed in zip(bars, speeds):
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + label_offset,
                        f'{speed:.1f}',
                        ha='center',
                        va='bottom',
                        fontsize=9,
                        color=self._ui_palette['ink'],
                    )

            axes[-1].set_xlabel('蒸汽发生器环号', fontsize=12, fontweight='bold')
            fig.suptitle('蒸汽发生器平均检测速度对比（按大修分组）', fontsize=15, fontweight='bold', y=0.99)
            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建按大修拆分的蒸汽发生器平均检测速度图时出错: {str(e)}")
            return None

    def create_outage_model_average_lifetime_chart(self, statistics: Dict[str, ProbeStatistics]) -> plt.Figure:
        """创建按大修和探头型号拆分的平均探头寿命图。"""
        try:
            if not statistics:
                return None

            outage_model_lifetimes = defaultdict(lambda: defaultdict(list))
            for stat in statistics.values():
                lifetime_hours = float(getattr(stat, 'total_duration_minutes', 0.0) or 0.0) / 60.0
                if lifetime_hours <= 0:
                    continue

                model = self._normalize_model(getattr(stat, 'model', ''))
                outage_values = {
                    self._normalize_outage_label(getattr(record, 'outage', ''))
                    for record in getattr(stat, 'records', []) or []
                }
                if not outage_values:
                    continue

                for outage in outage_values:
                    outage_model_lifetimes[outage][model].append(lifetime_hours)

            outage_avg_items = {}
            for outage, model_map in outage_model_lifetimes.items():
                items = []
                for model, lifetimes in model_map.items():
                    if lifetimes:
                        items.append((model, sum(lifetimes) / len(lifetimes), len(lifetimes)))
                if items:
                    outage_avg_items[outage] = sorted(items, key=lambda item: item[1], reverse=True)

            if not outage_avg_items:
                return None

            outages = sorted(outage_avg_items.keys(), key=self._outage_sort_key)
            model_count = max(len(items) for items in outage_avg_items.values())
            fig, axes = self._create_vertical_outage_axes(
                len(outages),
                base_width=max(10.0, min(17.5, model_count * 1.15 + 7.0)),
                row_height=4.3 if len(outages) == 1 else 4.0,
                max_width=18.0,
                max_height=24.0,
            )
            global_max = max((max((avg for _, avg, _ in items), default=0.0) for items in outage_avg_items.values()), default=0.0)

            for ax, outage in zip(axes, outages):
                items = outage_avg_items[outage]
                models = [item[0] for item in items]
                avg_hours = [item[1] for item in items]
                sample_counts = [item[2] for item in items]
                colors = [self._model_color(model) for model in models]
                bars = ax.bar(range(len(models)), avg_hours, color=colors, edgecolor=self._ui_palette['ink'], linewidth=1.0, alpha=0.92)

                ax.set_facecolor(self._ui_palette['panel'])
                ax.set_title(outage, fontsize=12.5, fontweight='bold', pad=10, color='#243447')
                ax.set_ylabel('平均探头寿命(小时)', fontsize=11, fontweight='bold')
                ax.set_xticks(range(len(models)))
                ax.set_xticklabels(models, rotation=25, ha='right')
                ax.grid(axis='y', alpha=0.28, linestyle='--')
                ax.set_axisbelow(True)
                ax.set_ylim(0, global_max * 1.18 if global_max > 0 else 1)

                label_offset = global_max * 0.03 if global_max > 0 else 0.2
                for bar, avg_hour, sample_count in zip(bars, avg_hours, sample_counts):
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + label_offset,
                        f'{avg_hour:.1f}h\nn={sample_count}',
                        ha='center',
                        va='bottom',
                        fontsize=8.3,
                        color=self._ui_palette['ink'],
                    )

            axes[-1].set_xlabel('探头型号', fontsize=12, fontweight='bold')
            fig.suptitle('大修平均探头寿命对比（按大修与型号分组）', fontsize=15, fontweight='bold', y=0.99)
            plt.tight_layout()
            self.figures.append(fig)
            return fig
        except Exception as e:
            logger.error(f"创建按大修和探头型号拆分的平均探头寿命图时出错: {str(e)}")
            return None

    def compose_figures_vertically(
        self,
        figure_specs: List[Dict[str, object]],
        title: str | None = None,
    ) -> plt.Figure:
        """将多张图按纵向拼接为一张总图。"""
        if not figure_specs:
            return None

        try:
            heights = []
            widths = []
            rendered = []
            for spec in figure_specs:
                fig = spec.get('figure')
                label = spec.get('label', '')
                if not fig:
                    continue
                canvas = FigureCanvasAgg(fig)
                canvas.draw()
                width, height = canvas.get_width_height()
                image = canvas.buffer_rgba()
                rendered.append({'image': image, 'width': width, 'height': height, 'label': label})
                widths.append(width)
                heights.append(height)

            if not rendered:
                return None

            total_height = sum(heights)
            max_width = max(widths)
            fig_width = min(20.0, max(9.0, max_width / 100.0))
            fig_height = min(40.0, max(6.0, total_height / 100.0 + 0.6))
            composed_fig, axes = plt.subplots(len(rendered), 1, figsize=(fig_width, fig_height), squeeze=False)
            flat_axes = [row[0] for row in axes]

            for ax, item in zip(flat_axes, rendered):
                ax.imshow(item['image'])
                ax.axis('off')
                if item['label']:
                    ax.set_title(str(item['label']), fontsize=11, fontweight='bold', loc='left', pad=8, color='#243447')

            if title:
                composed_fig.suptitle(title, fontsize=15, fontweight='bold', y=0.995)
            composed_fig.subplots_adjust(top=0.97 if title else 0.99, bottom=0.01, left=0.01, right=0.99, hspace=0.08)
            self.figures.append(composed_fig)
            return composed_fig
        except Exception as e:
            logger.error(f"拼接多张图表时出错: {str(e)}")
            return None

    def close_all_figures(self):
        """关闭所有图表"""
        for fig in self.figures.iter_live():
            plt.close(fig)
        self.figures.clear()
