"""
探头信息分析器
统计探头编号、使用寿命等信息
"""
from collections import defaultdict
from typing import List, Dict, Tuple, Callable, Optional
from datetime import datetime
import logging

from .models import ProbeRecord, ProbeStatistics, UsageSession

logger = logging.getLogger(__name__)


class ProbeAnalyzer:
    """探头分析器"""
    MAX_ZERO_DURATION_LOG_DETAILS = 8
    MAX_REMOVED_RECORD_DETAILS = 500
    
    def __init__(self):
        self.records: List[ProbeRecord] = []
        self.deduplication_info: dict = {}  # 存储去重信息：{'original_count': int, 'unique_count': int, 'removed_count': int}
        self.debug_info: Dict[str, dict] = {}  # 存储每个探头的详细调试信息

    @staticmethod
    def _get_probe_group_key(record: ProbeRecord) -> str:
        """按探头编号 + 探头类型 + 型号区分统计对象。"""
        return record.stat_key

    @staticmethod
    def _same_probe(record: ProbeRecord, probe_key: str) -> bool:
        return record.stat_key == probe_key

    @staticmethod
    def _record_dedup_key(record: ProbeRecord) -> tuple:
        """仅当表格原始列整行一致时，才判定为重复记录。"""
        def _norm_text(value) -> str:
            return str(value).strip() if value is not None else ""

        def _norm_time(value) -> str:
            if value is None:
                return ""
            if hasattr(value, "isoformat"):
                try:
                    return value.isoformat(sep=" ", timespec="seconds")
                except TypeError:
                    return value.isoformat()
            return _norm_text(value)

        return (
            _norm_text(record.outage),
            _norm_text(record.sg_id),
            _norm_text(record.data_group),
            _norm_text(record.operator),
            _norm_text(record.probe_type_raw or record.probe_type),
            _norm_text(record.probe_sn),
            _norm_text(record.model),
            record.tube_number if record.tube_number is not None else "",
            _norm_time(record.start_time),
            _norm_time(record.end_time),
        )

    @staticmethod
    def _record_sort_key(record: ProbeRecord) -> tuple:
        """为含空时间的记录提供稳定排序键，避免 datetime 与 None 比较报错。"""
        max_time = datetime.max
        start_time = record.start_time if record.start_time is not None else max_time
        end_time = record.end_time if record.end_time is not None else max_time
        return (
            start_time,
            end_time,
            str(getattr(record, "data_group", "") or ""),
            str(getattr(record, "operator", "") or ""),
        )

    @staticmethod
    def _get_record_loop_key(record: ProbeRecord) -> tuple[str, str] | None:
        """用 SG_ID + 数据组前缀识别同一环路。"""
        sg_id = str(getattr(record, 'sg_id', '') or '').strip()
        if not sg_id:
            return None
        data_group = str(getattr(record, 'data_group', '') or '').strip()
        if not data_group:
            return (sg_id, '')
        index = len(data_group) - 1
        while index >= 0 and data_group[index].isdigit():
            index -= 1
        prefix = data_group[:index + 1].upper().strip()
        return (sg_id, prefix)
    
    def add_records(self, records: List[ProbeRecord]):
        """添加记录"""
        self.records.extend(records)
        logger.info(f"添加了 {len(records)} 条记录，总计 {len(self.records)} 条")
    
    def clear_records(self):
        """清空记录"""
        self.records.clear()
        self.deduplication_info = {}
        self.debug_info = {}

    @staticmethod
    def _emit_progress(
        progress_callback: Optional[Callable[[str, int, int, str], None]],
        stage: str,
        current: int,
        total: int,
        message: str,
    ) -> None:
        if not progress_callback:
            return
        try:
            progress_callback(stage, current, total, message)
        except Exception:
            pass
    
    def analyze(
        self,
        progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
        *,
        skip_deduplication: bool = False,
        collect_debug_info: bool = True,
    ) -> Dict[str, ProbeStatistics]:
        """
        分析探头信息
        返回字典：{probe_key: ProbeStatistics}
        """
        if not self.records:
            logger.warning("没有可分析的记录")
        original_count = len(self.records)
        if skip_deduplication:
            unique_records = self.records
            removed_count = 0
            self.deduplication_info = {
                'original_count': original_count,
                'unique_count': len(unique_records),
                'removed_count': 0,
                'removed_records': [],
                'skipped': True,
            }
        else:
            seen = set()
            unique_records = []
            removed_records = []
            dedup_report_interval = max(1, (original_count + 59) // 60) if original_count else 1
            
            for index, record in enumerate(self.records, start=1):
                key = self._record_dedup_key(record)
                
                if key not in seen:
                    seen.add(key)
                    unique_records.append(record)
                elif len(removed_records) < self.MAX_REMOVED_RECORD_DETAILS:
                    removed_records.append(record)

                if (
                    index == 1
                    or index == original_count
                    or index % dedup_report_interval == 0
                ):
                    self._emit_progress(
                        progress_callback,
                        'deduplicate',
                        index,
                        max(original_count, 1),
                        f"正在整理记录 {index}/{max(original_count, 1)}",
                    )
            
            removed_count = original_count - len(unique_records)
            self.deduplication_info = {
                'original_count': original_count,
                'unique_count': len(unique_records),
                'removed_count': removed_count,
                'removed_records': removed_records,
                'removed_records_truncated': removed_count > len(removed_records),
            }

        self.records = unique_records
        
        if removed_count > 0:
            logger.info(f"去重完成：原始记录 {original_count} 条，去重后 {len(unique_records)} 条，移除重复记录 {removed_count} 条")
        
        # 按探头编号 + 探头类型 + 型号分组
        probe_groups = defaultdict(list)
        for record in self.records:
            probe_groups[self._get_probe_group_key(record)].append(record)
        records_by_loop = defaultdict(list)
        for record in self.records:
            loop_key = self._get_record_loop_key(record)
            if loop_key:
                records_by_loop[loop_key].append(record)
        
        statistics = {}
        total_groups = max(len(probe_groups), 1)
        group_report_interval = max(1, (total_groups + 59) // 60)
        
        for group_index, (probe_key, records) in enumerate(probe_groups.items(), start=1):
            try:
                sample_record = records[0]
                probe_sn = sample_record.probe_sn
                probe_type = sample_record.probe_type_raw or sample_record.probe_type
                model = sample_record.model
                # 按时间排序
                sorted_records = sorted(records, key=self._record_sort_key)
                
                # 计算统计信息 - 精确累加每条记录的使用时长
                record_details = [] if collect_debug_info else None  # 用于调试（包含所有原始记录）
                valid_records_for_stats: List[ProbeRecord] = []  # 仅包含真正参与统计/计次的记录
                total_duration = 0.0
                
                from datetime import datetime
                invalid_time = datetime(1900, 1, 1, 0, 0, 0)
                
                # 收集所有警告，但不在这里整合，让extractor的警告信息保持原样
                # analyzer只负责统计，不负责整合警告信息
                for r in sorted_records:
                    # 检查管道数量是否为0
                    if r.tube_number == 0:
                        warning_msg = f"管道数量为0: 探头={probe_sn}, 管道数量={r.tube_number}, 操作员={r.operator}, 数据组={r.data_group}"
                        logger.debug(warning_msg)
                        r.warnings.append("管道数量为0")
                    
                    # 检查开始时间是否为None或为空
                    start_time_invalid = r.start_time is None or (r.start_time == invalid_time)
                    # 检查结束时间是否为None或为空
                    end_time_invalid = r.end_time is None or (r.end_time == invalid_time)
                    
                    if start_time_invalid and end_time_invalid:
                        warning_msg = f"开始时间和结束时间均为空: 探头={probe_sn}, 管道数量={r.tube_number}, 操作员={r.operator}, 开始时间={r.start_time}, 结束时间={r.end_time}"
                        logger.debug(warning_msg)
                        r.warnings.append("开始时间和结束时间均为空")
                    elif start_time_invalid:
                        warning_msg = f"开始时间为空: 探头={probe_sn}, 开始时间={r.start_time}, 结束时间={r.end_time}, 管道数量={r.tube_number}, 操作员={r.operator}"
                        logger.debug(warning_msg)
                        r.warnings.append("开始时间为空")
                    elif end_time_invalid:
                        warning_msg = f"结束时间为空: 探头={probe_sn}, 开始时间={r.start_time}, 结束时间={r.end_time}, 管道数量={r.tube_number}, 操作员={r.operator}"
                        logger.debug(warning_msg)
                        r.warnings.append("结束时间为空")
                    
                    # 只有在时间都有效的情况下才计算时长
                    if not start_time_invalid and not end_time_invalid:
                        # 直接计算时间差，确保精确
                        delta = r.end_time - r.start_time
                        duration_seconds = delta.total_seconds()
                        duration_minutes = duration_seconds / 60.0
                        if record_details is not None:
                            record_details.append({
                                'start': r.start_time,
                                'end': r.end_time,
                                'seconds': duration_seconds,
                                'minutes': duration_minutes,
                                'tube': r.tube_number,
                                'operator': r.operator
                            })
                        
                        # 如果时间差为0或负数，记录警告
                        if duration_minutes <= 0:
                            logger.debug(
                            f"记录时间异常: 探头={probe_sn}, "
                            f"开始时间={r.start_time}, 结束时间={r.end_time}, "
                            f"时间差={duration_seconds}秒 ({duration_minutes:.4f}分钟), "
                            f"管道数量={r.tube_number}, 操作员={r.operator}"
                        )
                        else:
                            # 仅将“有效且时长>0”的记录纳入统计与使用段划分，
                            # 同时要求：管道数量不为0、时间不为占位时间（如1900年）
                            if (
                                r.tube_number is not None
                                and r.tube_number != 0
                                and r.start_time.year >= 2000
                                and r.end_time.year >= 2000
                            ):
                                valid_records_for_stats.append(r)
                                total_duration += duration_minutes
                
                # 如果没有任何有效记录，则回退为使用全部记录进行统计（避免全部被过滤导致完全没有数据）
                records_for_stats = valid_records_for_stats if valid_records_for_stats else sorted_records

                if total_duration == 0.0 and len(sorted_records) > 0:
                    logger.debug(f"探头 {probe_sn} 总使用时间为0分钟，但共有 {len(sorted_records)} 条记录")
                    if record_details:
                        for i, detail in enumerate(record_details[:self.MAX_ZERO_DURATION_LOG_DETAILS], 1):
                            logger.debug(
                                f"记录{i}: 开始={detail['start']}, 结束={detail['end']}, "
                                f"时间差={detail['seconds']}秒 ({detail['minutes']:.6f}分钟), "
                                f"管道数量={detail['tube']}, 操作员={detail['operator']}"
                            )
                        if all(d['minutes'] == 0.0 for d in record_details):
                            logger.debug("所有记录的时间差都是0，可能是时间解析或数据问题")
                
                # 首次/末次使用时间基于“参与统计的有效记录”来确定
                first_use = records_for_stats[0].start_time if records_for_stats else None
                last_use = records_for_stats[-1].end_time if records_for_stats else None
                
                # 确定探头类型/型号（取第一条记录）
                probe_type = sample_record.probe_type_raw or sample_record.probe_type
                
                # 识别使用段（连续使用和更换后再次使用）
                # 使用“有效记录集”进行使用段划分，避免无效时间（如1900-01-01）导致超长使用段
                usage_sessions, debug_details = self._identify_usage_sessions(
                    records_for_stats,
                    probe_key,
                    all_records=self.records,
                    records_by_loop=records_by_loop,
                    collect_debug_info=collect_debug_info,
                )
                if collect_debug_info:
                    reuse_details = [
                        {
                            'between': {
                                'from_data_group': detail.get('prev_record', {}).get('data_group'),
                                'to_data_group': detail.get('current_record', {}).get('data_group'),
                                'from_end_time': detail.get('prev_record', {}).get('end_time'),
                                'to_start_time': detail.get('current_record', {}).get('start_time'),
                                'gap_minutes': detail.get('gap_minutes', 0.0),
                            },
                            'decision': detail.get('decision', ''),
                            'occupying_probes': list(detail.get('other_probes_found', []) or []),
                        }
                        for detail in debug_details
                        if detail.get('other_probes_found')
                    ]
                    self.debug_info[probe_key] = {
                        'probe_key': probe_key,
                        'probe_sn': probe_sn,
                        'probe_type': probe_type,
                        'model': model,
                        'total_records': len(sorted_records),
                        'total_duration_minutes': total_duration,
                        'usage_sessions_count': len(usage_sessions),
                        'longest_continuous_minutes': max((s.duration_minutes for s in usage_sessions), default=0.0),
                        'session_details': debug_details,
                        'all_records': [
                            {
                                'data_group': r.data_group,
                                'sg_id': r.sg_id,
                                'start_time': r.start_time.strftime('%Y-%m-%d %H:%M:%S') if r.start_time else None,
                                'end_time': r.end_time.strftime('%Y-%m-%d %H:%M:%S') if r.end_time else None,
                                'duration_minutes': r.duration_minutes,
                                'tube_number': r.tube_number,
                                'operator': r.operator
                            }
                            for r in sorted_records
                        ]
                    }
                else:
                    reuse_details = []
                
                # 使用次数只统计“有效记录”的数量（忽略管道数量为0、时间无效等警告行）
                stat = ProbeStatistics(
                    probe_sn=probe_sn,
                    probe_type=probe_type,
                    model=model,
                    stat_key=probe_key,
                    total_uses=len(records_for_stats),
                    total_duration_minutes=total_duration,
                    first_use_time=first_use,
                    last_use_time=last_use,
                    records=sorted_records,
                    usage_sessions=usage_sessions,
                    reuse_details=reuse_details,
                )
                
                statistics[probe_key] = stat
                if (
                    group_index == 1
                    or group_index == total_groups
                    or group_index % group_report_interval == 0
                ):
                    self._emit_progress(
                        progress_callback,
                        'analyze',
                        group_index,
                        total_groups,
                        f"正在分析探头 {group_index}/{total_groups}: {probe_sn}",
                    )
            
            except Exception as e:
                logger.error(f"分析探头 {probe_key} 时出错: {str(e)}")
                continue
        
        logger.info(f"分析了 {len(statistics)} 个探头")
        return statistics
    
    def _identify_usage_sessions(self, sorted_records: List[ProbeRecord], probe_key: str,
                                  all_records: List[ProbeRecord] = None,
                                  records_by_loop: Optional[Dict[tuple[str, str], List[ProbeRecord]]] = None,
                                  gap_threshold_minutes: float = 30.0,
                                  collect_debug_info: bool = True) -> Tuple[List[UsageSession], List[dict]]:
        """
        识别使用段：区分连续使用和更换后再次使用
        
        判断逻辑：
        1. 最长连续时间：同一探头在同一个 SG_ID 下，数据组连续递增（单推+1，双推+2），
           且时间间隔合理（<=120分钟），则认为是连续使用。
           最长连续时间 = 所有使用段中最长的那一段的时长。
        
        2. 更换后再次使用：使用这个探头后不用了，在接下来的数据组中更换成其他探头了，
           使用几次其他探头后又给换回来了。
           判断方法：检查两个使用段之间，在同一个 SG_ID 下是否有其他探头被使用过。
           如果有其他探头被使用，则认为是"更换后再次使用"。
        
        Args:
            sorted_records: 当前探头的按时间排序的记录列表
            probe_key: 探头统计键（探头编号 + 类型 + 型号）
            all_records: 所有探头的记录列表（用于检查中间是否有其他探头被使用）
            gap_threshold_minutes: 连续使用的时间间隔阈值（分钟）
        
        Returns:
            使用段列表
        """
        if not sorted_records:
            return [], []
        
        # 如果没有提供所有记录，则只使用当前探头的记录（向后兼容）
        if all_records is None:
            all_records = sorted_records
        if records_by_loop is None:
            records_by_loop = defaultdict(list)
            for record in all_records:
                loop_key = self._get_record_loop_key(record)
                if loop_key:
                    records_by_loop[loop_key].append(record)
        max_idle_continuous_minutes = max(gap_threshold_minutes * 3, 90.0)
        
        # 辅助函数：解析数据组为整数，无法解析时返回None
        def _parse_data_group(record: ProbeRecord) -> int | None:
            try:
                if record.data_group is None:
                    return None
                s = str(record.data_group).strip()
                # 如果本身就是纯数字，直接解析
                if s.isdigit():
                    return int(s)
                # 否则提取末尾连续数字（适配类似 SG3H23CAL00101 这样的命名）
                i = len(s) - 1
                while i >= 0 and s[i].isdigit():
                    i -= 1
                tail = s[i+1:]
                if tail and tail.isdigit():
                    return int(tail)
                return None
            except (ValueError, TypeError):
                return None
        
        def _same_loop(record_a: ProbeRecord, record_b: ProbeRecord) -> bool:
            """判断两个记录是否属于同一个环路。"""
            if not record_a.sg_id or not record_b.sg_id:
                return False
            if record_a.sg_id != record_b.sg_id:
                return False
            key_a = self._get_record_loop_key(record_a)
            key_b = self._get_record_loop_key(record_b)
            if key_a and key_b:
                if key_a[1] and key_b[1]:
                    return key_a == key_b
            return record_a.sg_id == record_b.sg_id

        def _collect_other_probes_between(start_time: datetime, end_time: datetime,
                                          current_probe_key: str,
                                          reference_record: ProbeRecord) -> List[dict]:
            """收集同一环路时间缝隙内占用过该时间段的其他探头。"""
            loop_key = self._get_record_loop_key(reference_record)
            if not loop_key:
                return []

            found = []
            for record in records_by_loop.get(loop_key, []):
                if self._same_probe(record, current_probe_key):
                    continue
                if not record.start_time or not record.end_time:
                    continue
                if not _same_loop(record, reference_record):
                    continue
                if (
                    start_time < record.start_time < end_time
                    or start_time < record.end_time < end_time
                    or (record.start_time < start_time and record.end_time > end_time)
                ):
                    found.append({
                        'probe_sn': record.probe_sn,
                        'probe_type': record.probe_type_raw or record.probe_type,
                        'model': record.model,
                        'data_group': record.data_group,
                        'start_time': record.start_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'end_time': record.end_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'duration_minutes': record.duration_minutes,
                    })

            found.sort(key=lambda item: (item.get('start_time') or '', item.get('probe_sn') or ''))
            unique_found = []
            seen = set()
            for item in found:
                item_key = (
                    item.get('probe_sn', ''),
                    item.get('data_group', ''),
                    item.get('start_time', ''),
                    item.get('end_time', ''),
                )
                if item_key in seen:
                    continue
                seen.add(item_key)
                unique_found.append(item)
            return unique_found
        
        sessions: List[UsageSession] = []
        current_session_records: List[ProbeRecord] = [sorted_records[0]]
        session_id = 1
        debug_details = []  # 存储详细的判断过程
        
        for i in range(1, len(sorted_records)):
            prev_record = sorted_records[i - 1]
            current_record = sorted_records[i]
            
            # 记录判断过程
            decision_detail = {
                'record_index': i,
                'prev_record': {
                    'data_group': prev_record.data_group,
                    'sg_id': prev_record.sg_id,
                    'start_time': prev_record.start_time.strftime('%Y-%m-%d %H:%M:%S') if prev_record.start_time else None,
                    'end_time': prev_record.end_time.strftime('%Y-%m-%d %H:%M:%S') if prev_record.end_time else None,
                },
                'current_record': {
                    'data_group': current_record.data_group,
                    'sg_id': current_record.sg_id,
                    'start_time': current_record.start_time.strftime('%Y-%m-%d %H:%M:%S') if current_record.start_time else None,
                    'end_time': current_record.end_time.strftime('%Y-%m-%d %H:%M:%S') if current_record.end_time else None,
                },
                'decision': '',
                'reasoning': []
            }
            
            # 如果时间缺失，保守起见认为是新的使用段
            if prev_record.end_time is None or current_record.start_time is None:
                new_session = True
                decision_detail['decision'] = '新使用段（时间缺失）'
                decision_detail['reasoning'].append('前一条记录或当前记录的结束/开始时间为空，保守起见认为是新的使用段')
            else:
                # 计算时间间隔（分钟）
                gap_minutes = (current_record.start_time - prev_record.end_time).total_seconds() / 60.0
                decision_detail['gap_minutes'] = gap_minutes
                
                # 默认按照时间阈值判断（仅在缺少有效数据组信息时才起主要作用）
                continuous = gap_minutes <= gap_threshold_minutes
                decision_detail['reasoning'].append(f'时间间隔: {gap_minutes:.2f} 分钟，阈值: {gap_threshold_minutes} 分钟')
                decision_detail['reasoning'].append(f'初步判断（仅基于时间）: {"连续" if continuous else "不连续"}')
                
                # 如果同一 SG 且数据组能解析为整数，则结合数据组编号一起判断
                same_sg = (
                    bool(prev_record.sg_id)
                    and bool(current_record.sg_id)
                    and prev_record.sg_id == current_record.sg_id
                )
                prev_group = _parse_data_group(prev_record)
                curr_group = _parse_data_group(current_record)
                
                decision_detail['same_sg'] = same_sg
                decision_detail['prev_group'] = prev_group
                decision_detail['curr_group'] = curr_group
                
                # 重要：连续性判断只针对相同的SG_ID
                # 只有当前后记录的SG_ID相同时，才进行数据组连续性判断
                if same_sg and prev_group is not None and curr_group is not None:
                    delta_group = curr_group - prev_group
                    decision_detail['delta_group'] = delta_group
                    
                    if delta_group > 0:
                        # 典型情况：
                        # - 单推：数据组递增 1
                        # - 双推：两个探头交替，单个探头的数据组通常递增 2
                        #
                        # 判断逻辑（仅针对相同SG_ID）：
                        # 1. 如果数据组连续（delta_group <= 2），这是正常的双推模式，即使中间有其他探头也是连续使用
                        #    - 单推：数据组递增 1
                        #    - 双推：两个探头交替，单个探头的数据组通常递增 2
                        # 2. 如果数据组不连续（delta_group > 2），检查中间是否有其他探头（仅相同SG_ID）
                        #    - 如果有其他探头 → 更换后再次使用
                        #    - 如果没有其他探头 → 连续使用（可能是数据组跳跃）
                        if delta_group <= 2:
                            other_probes_found = _collect_other_probes_between(
                                prev_record.end_time,
                                current_record.start_time,
                                probe_key,
                                prev_record,
                            )
                            has_other_probes = bool(other_probes_found)
                            decision_detail['has_other_probes'] = has_other_probes
                            decision_detail['other_probes_found'] = other_probes_found
                            if has_other_probes:
                                continuous = False
                                decision_detail['decision'] = '疑似更换后再次使用（同一SG数据组连续，但间隔内有其他探头）'
                                decision_detail['reasoning'].append(
                                    f'同一SG且数据组正常小步递增: {prev_group} -> {curr_group} (Δ={delta_group}，<=2)，但间隔内检测到其他同环路探头，视为可能更换后再次使用'
                                )
                            elif gap_minutes > max_idle_continuous_minutes:
                                continuous = False
                                decision_detail['decision'] = '新使用段（间隔过长）'
                                decision_detail['reasoning'].append(
                                    f'同一SG且数据组连续，但空档 {gap_minutes:.2f} 分钟，超过连续使用允许的最长空档 {max_idle_continuous_minutes:.0f} 分钟'
                                )
                            else:
                                continuous = True
                                decision_detail['decision'] = '连续使用'
                                decision_detail['reasoning'].append(
                                    f'同一SG且数据组正常小步递增: {prev_group} -> {curr_group} (Δ={delta_group}，<=2)，且间隔内没有其他同环路探头，视为连续使用'
                                )
                            if gap_minutes > gap_threshold_minutes:
                                decision_detail['reasoning'].append(
                                    f'间隔 {gap_minutes:.2f} 分钟超过时间阈值，但时间阈值仅作为辅助判断，主要依据是否有其他探头在间隔内使用'
                                )
                        else:
                            # 数据组不连续（delta_group > 2），检查中间是否有同一环路的其他探头被使用
                            other_probes_found = _collect_other_probes_between(
                                prev_record.end_time,
                                current_record.start_time,
                                probe_key,
                                prev_record,
                            )
                            has_other_probes = bool(other_probes_found)
                            decision_detail['has_other_probes'] = has_other_probes
                            if has_other_probes:
                                for record in []:
                                    if (
                                        not self._same_probe(record, probe_key)
                                        and _same_loop(record, prev_record)
                                        and record.start_time
                                        and record.end_time
                                    ):
                                        # 使用与 _has_other_probes_between 相同的逻辑，排除边界情况
                                        if (
                                            prev_record.end_time < record.start_time < current_record.start_time
                                            or prev_record.end_time < record.end_time < current_record.start_time
                                            or (record.start_time < prev_record.end_time and record.end_time > current_record.start_time)
                                        ):
                                            other_probes_found.append(
                                                {
                                                    'probe_sn': record.probe_sn,
                                                    'data_group': record.data_group,
                                                    'start_time': record.start_time.strftime('%Y-%m-%d %H:%M:%S'),
                                                    'end_time': record.end_time.strftime('%Y-%m-%d %H:%M:%S'),
                                                }
                                            )
                            decision_detail['other_probes_found'] = other_probes_found
                            
                            if has_other_probes:
                                # 数据组不连续，且中间有其他探头被使用 → 更换后再次使用
                                continuous = False
                                decision_detail['decision'] = '更换后再次使用（数据组不连续且中间有其他探头）'
                                decision_detail['reasoning'].append(
                                    f'数据组不连续: {prev_group} -> {curr_group} (Δ={delta_group} > 2)，且中间时间段有其他探头被使用'
                                )
                            else:
                                # 数据组不连续，但中间没有其他探头被使用 → 连续使用（可能是数据组跳跃）
                                continuous = True
                                decision_detail['decision'] = '连续使用（数据组跳跃但中间无其他探头）'
                                decision_detail['reasoning'].append(
                                    f'数据组跳跃: {prev_group} -> {curr_group} (Δ={delta_group} > 2)，但中间时间段没有其他探头被使用，视为数据组跳跃，仍视作一段连续使用'
                                )
                        # 其它情况（例如 delta_group 小但间隔极大），保持时间阈值的判断结果
                    else:
                        # 数据组不递增（重复或倒退），检查中间是否有其他探头被使用
                        if same_sg:
                            other_probes_found = _collect_other_probes_between(
                                prev_record.end_time,
                                current_record.start_time,
                                probe_key,
                                prev_record,
                            )
                            has_other_probes = bool(other_probes_found)
                            decision_detail['has_other_probes'] = has_other_probes
                            decision_detail['other_probes_found'] = other_probes_found
                            
                            if has_other_probes:
                                continuous = False
                                decision_detail['decision'] = '更换后再次使用（数据组不递增，但中间有其他探头）'
                                decision_detail['reasoning'].append(f'数据组不递增（{prev_group} -> {curr_group}），且中间时间段有其他探头被使用')
                            else:
                                decision_detail['decision'] = '连续使用（数据组不递增，但无其他探头）'
                                decision_detail['reasoning'].append(f'数据组不递增（{prev_group} -> {curr_group}），但中间时间段没有其他探头被使用，保持时间阈值判断')
                        # 如果没有其他探头，保持时间阈值的判断结果
                elif same_sg:
                    # 同一 SG 但数据组无法解析，检查中间是否有同一环路的其他探头被使用
                    other_probes_found = _collect_other_probes_between(
                        prev_record.end_time,
                        current_record.start_time,
                        probe_key,
                        prev_record,
                    )
                    has_other_probes = bool(other_probes_found)
                    decision_detail['has_other_probes'] = has_other_probes
                    decision_detail['other_probes_found'] = other_probes_found
                    
                    if has_other_probes:
                        continuous = False
                        decision_detail['decision'] = '更换后再次使用（数据组无法解析，但中间有其他探头）'
                        decision_detail['reasoning'].append('数据组无法解析为整数，但中间时间段有其他探头被使用')
                    else:
                        decision_detail['decision'] = '连续使用（数据组无法解析，但无其他探头）'
                        decision_detail['reasoning'].append('数据组无法解析为整数，但中间时间段没有其他探头被使用，保持时间阈值判断')
                    # 如果没有其他探头，保持时间阈值的判断结果
                else:
                    decision_detail['decision'] = '连续使用（不同SG或仅基于时间）'
                    decision_detail['reasoning'].append('不同SG_ID，仅基于时间间隔判断')
                
                new_session = not continuous
            
            debug_details.append(decision_detail)
            
            if not new_session:
                # 仍然视为同一连续使用段
                current_session_records.append(current_record)
            else:
                # 结束当前段，开始新的使用段
                if current_session_records:
                    session = UsageSession(
                        session_id=session_id,
                        start_time=current_session_records[0].start_time,
                        end_time=current_session_records[-1].end_time,
                        records=current_session_records.copy(),
                        is_continuous=True
                    )
                    sessions.append(session)
                    session_id += 1
                
                current_session_records = [current_record]
        
        # 保存最后一个段
        if current_session_records:
            session = UsageSession(
                session_id=session_id,
                start_time=current_session_records[0].start_time,
                end_time=current_session_records[-1].end_time,
                records=current_session_records.copy(),
                is_continuous=True
            )
            sessions.append(session)
        
        logger.debug(f"探头 {probe_key} 识别出 {len(sessions)} 个使用段")
        return sessions, debug_details
    
    def get_detection_probes(self, statistics: Dict[str, ProbeStatistics]) -> Dict[str, ProbeStatistics]:
        """获取检测探头统计（已废弃：不再区分检测/参考探头，返回所有统计）"""
        # 不再区分检测/参考探头，直接返回所有统计信息
        return statistics
    
    def get_reference_probes(self, statistics: Dict[str, ProbeStatistics]) -> Dict[str, ProbeStatistics]:
        """获取参考探头统计（已废弃：不再区分检测/参考探头，返回所有统计）"""
        # 不再区分检测/参考探头，直接返回所有统计信息
        return statistics
    
    def get_top_probes_by_usage(self, statistics: Dict[str, ProbeStatistics], 
                                 top_n: int = 10) -> List[ProbeStatistics]:
        """获取使用次数最多的探头"""
        sorted_stats = sorted(statistics.values(), 
                            key=lambda x: x.total_uses, 
                            reverse=True)
        return sorted_stats[:top_n]
    
    def get_top_probes_by_lifetime(self, statistics: Dict[str, ProbeStatistics], 
                                   top_n: int = 10) -> List[ProbeStatistics]:
        """获取使用寿命最长的探头"""
        sorted_stats = sorted(statistics.values(), 
                            key=lambda x: x.lifetime_hours, 
                            reverse=True)
        return sorted_stats[:top_n]
