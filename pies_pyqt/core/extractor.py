#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
探头数据提取器模块
"""

import os
import re
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any, Callable

import pandas as pd

from .models import ProbeRecord, ProbeEvent

# 模块级日志记录器
logger = logging.getLogger(__name__)

# 检查pandas是否可用
PANDAS_AVAILABLE = False
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    logger.warning("pandas not available, some features will be limited")


class SummaryFileExtractor:
    """摘要文件提取器"""
    
    def __init__(self):
        """初始化提取器"""
        self.probe_records: List[ProbeRecord] = []
        self.error_records: List[Dict[str, Any]] = []
    
    @staticmethod
    def _emit_progress(
        progress_callback: Optional[Callable[[int, int, str], None]],
        current: int,
        total: int,
        message: str,
    ) -> None:
        if not progress_callback:
            return
        try:
            progress_callback(current, total, message)
        except Exception:
            pass

    def extract(
        self,
        file_path: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[ProbeRecord]:
        """
        从文件中提取探头记录
        
        Args:
            file_path: 文件路径
            
        Returns:
            探头记录列表
        """
        if not os.path.exists(file_path):
            logger.error(f"文件不存在: {file_path}")
            return []
        
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext in ['.xlsx', '.xls']:
            return self._parse_excel(file_path, progress_callback=progress_callback)
        elif file_ext == '.txt':
            return self._parse_content(file_path)
        else:
            logger.error(f"不支持的文件格式: {file_ext}")
            return []
    
    def extract_probe_records(
        self,
        file_path: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[ProbeRecord]:
        """
        从文件中提取探头记录（向后兼容方法）
        
        Args:
            file_path: 文件路径
            
        Returns:
            探头记录列表
        """
        return self.extract(file_path, progress_callback=progress_callback)
    
    def _parse_content(self, file_path: str) -> List[ProbeRecord]:
        """
        解析文本文件内容
        
        Args:
            file_path: 文件路径
            
        Returns:
            探头记录列表
        """
        records = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 提取文件头部信息
            outage_match = re.search(r'大修编号\s*[:：]\s*(\S+)', content)
            outage = outage_match.group(1) if outage_match else ""
            
            sg_id_match = re.search(r'SG\s*ID\s*[:：]\s*(\S+)', content)
            sg_id = sg_id_match.group(1) if sg_id_match else ""
            
            operator_match = re.search(r'操作员\s*[:：]\s*(\S+)', content)
            operator = operator_match.group(1) if operator_match else ""
            
            data_group_match = re.search(r'数据组\s*[:：]\s*(\S+)', content)
            data_group = data_group_match.group(1) if data_group_match else ""
            
            # 提取探头记录
            probe_pattern = re.compile(r'\d+\s+([A-Z0-9-]+)\s+([A-Z0-9-]+)\s+([A-Z]+)\s+([\d.]+)\s+([\d:]+)\s+([\d:]+)', re.MULTILINE)
            matches = probe_pattern.findall(content)
            
            for idx, match in enumerate(matches):
                probe_sn, model, probe_type_raw, tube_number, start_time_str, end_time_str = match
                
                line_num = idx + 1  # 简化行号计算
                
                # 转换管道数量
                try:
                    tube_number = int(tube_number)
                except ValueError:
                    tube_number = 0
                
                # 检查管道数量是否为0
                if tube_number == 0:
                    logger.warning(f"管道数量为0 (行 {line_num}): "
                                 f"探头={probe_sn}, 管道数量={tube_number}, "
                                 f"操作员={operator}, 数据组={data_group}")
                    error_record = {
                        '行号': line_num,
                        '大修编号': outage,
                        'SG ID': sg_id,
                        '数据组': data_group,
                        '操作员': operator,
                        '探头类型': probe_type_raw,
                        '探头编号': probe_sn,
                        '探头型号': model,
                        '管道数量': tube_number,
                        '错误类型': '管道数量为0',
                        '原始数据': f"管道数量={tube_number}, 数据组={data_group}"
                    }
                    self.error_records.append(error_record)
                
                # 解析时间 - 确保精确解析
                start_time = None
                end_time = None
                time_warnings = []
                
                try:
                    start_time = self._parse_datetime(start_time_str)
                    end_time = self._parse_datetime(end_time_str)
                    
                    # 检查开始时间是否为None
                    if start_time is None:
                        time_warnings.append(f"开始时间为空")
                        logger.warning(f"开始时间为空 (行 {line_num}): "
                                     f"探头={probe_sn}, 原始开始时间={start_time_str}, "
                                     f"管道数量={tube_number}, 操作员={operator}")
                        error_record = {
                            '行号': line_num,
                            '大修编号': outage,
                            'SG ID': sg_id,
                            '数据组': data_group,
                            '操作员': operator,
                            '探头类型': probe_type_raw,
                            '探头编号': probe_sn,
                            '探头型号': model,
                            '管道数量': tube_number,
                            '开始时间': start_time_str,
                            '错误类型': '开始时间为空',
                            '原始数据': f"原始开始时间={start_time_str}"
                        }
                        self.error_records.append(error_record)
                    
                    # 检查结束时间是否为None
                    if end_time is None:
                        time_warnings.append(f"结束时间为空")
                        logger.warning(f"结束时间为空 (行 {line_num}): "
                                     f"探头={probe_sn}, 原始结束时间={end_time_str}, "
                                     f"管道数量={tube_number}, 操作员={operator}")
                        error_record = {
                            '行号': line_num,
                            '大修编号': outage,
                            'SG ID': sg_id,
                            '数据组': data_group,
                            '操作员': operator,
                            '探头类型': probe_type_raw,
                            '探头编号': probe_sn,
                            '探头型号': model,
                            '管道数量': tube_number,
                            '结束时间': end_time_str,
                            '错误类型': '结束时间为空',
                            '原始数据': f"原始结束时间={end_time_str}"
                        }
                        self.error_records.append(error_record)
                    
                    # 如果两个时间都为None，仍然创建记录但记录警告
                    if start_time is None and end_time is None:
                        logger.warning(f"开始时间和结束时间均为空 (行 {line_num}): "
                                     f"探头={probe_sn}, 管道数量={tube_number}, 操作员={operator}, "
                                     f"原始开始={start_time_str}, 原始结束={end_time_str}")
                        error_record = {
                            '行号': line_num,
                            '大修编号': outage,
                            'SG ID': sg_id,
                            '数据组': data_group,
                            '操作员': operator,
                            '探头类型': probe_type_raw,
                            '探头编号': probe_sn,
                            '探头型号': model,
                            '管道数量': tube_number,
                            '开始时间': start_time_str,
                            '结束时间': end_time_str,
                            '错误类型': '开始时间和结束时间均为空',
                            '原始数据': f"原始开始={start_time_str}, 原始结束={end_time_str}"
                        }
                        self.error_records.append(error_record)
                        # 使用默认时间值，避免后续处理出错
                    #    from datetime import datetime
                    #   start_time = datetime(1900, 1, 1, 0, 0, 0)
                    #   end_time = datetime(1900, 1, 1, 0, 0, 0)
                    elif start_time is None:
                        # 只有开始时间为None，使用结束时间作为开始时间
                        logger.warning(f"开始时间为空，使用结束时间作为开始时间 (行 {line_num}): "
                                     f"探头={probe_sn}, 结束时间={end_time}")
                        error_record = {
                            '行号': line_num,
                            '大修编号': outage,
                            'SG ID': sg_id,
                            '数据组': data_group,
                            '操作员': operator,
                            '探头类型': probe_type_raw,
                            '探头编号': probe_sn,
                            '探头型号': model,
                            '管道数量': tube_number,
                            '开始时间': start_time_str,
                            '结束时间': end_time,
                            '错误类型': '开始时间为空，使用结束时间作为开始时间',
                            '原始数据': f"原始开始时间={start_time_str}, 结束时间={end_time}"
                        }
                        self.error_records.append(error_record)
                        start_time = end_time
                    elif end_time is None:
                        # 结束时间为空，保持为None，不要自动填充
                        logger.warning(f"结束时间为空 (行 {line_num}): "
                                     f"探头={probe_sn}, 开始时间={start_time}")
                        error_record = {
                            '行号': line_num,
                            '大修编号': outage,
                            'SG ID': sg_id,
                            '数据组': data_group,
                            '操作员': operator,
                            '探头类型': probe_type_raw,
                            '探头编号': probe_sn,
                            '探头型号': model,
                            '管道数量': tube_number,
                            '开始时间': start_time,
                            '错误类型': '结束时间为空',
                            '原始数据': f"开始时间={start_time}, 结束时间=空"
                        }
                        self.error_records.append(error_record)
                        # end_time保持为None
                    else:
                        # 两个时间都有效，检查时间顺序
                        if end_time < start_time:
                            logger.warning(f"结束时间早于开始时间，跳过该条记录 (行 {line_num}): "
                                         f"探头={probe_sn}, 管道数量={tube_number}, 操作员={operator}, "
                                         f"原始开始={start_time}, 原始结束={end_time}")
                            error_record = {
                                '行号': line_num,
                                '大修编号': outage,
                                'SG ID': sg_id,
                                '数据组': data_group,
                                '操作员': operator,
                                '探头类型': probe_type_raw,
                                '探头编号': probe_sn,
                                '探头型号': model,
                                '管道数量': tube_number,
                                '开始时间': start_time,
                                '结束时间': end_time,
                                '错误类型': '结束时间早于开始时间',
                                '原始数据': f"开始时间={start_time}, 结束时间={end_time}"
                            }
                            self.error_records.append(error_record)
                            return None
                    
                    # 验证时间差：如果时间相同，记录警告（只在两个时间都不为空时检查）
                    if start_time and end_time and start_time == end_time:
                        delta_seconds = (end_time - start_time).total_seconds()
                        if delta_seconds < 0:
                            logger.warning(f"结束时间早于开始时间 (行 {line_num}): "
                                         f"探头={probe_sn}, 开始时间={start_time}, 结束时间={end_time}")
                            # 结束时间早于开始时间，跳过该条记录
                            continue
                        elif delta_seconds == 0:
                            logger.warning(f"开始时间和结束时间相同 (行 {line_num}): "
                                         f"探头={probe_sn}, 开始时间={start_time}, 结束时间={end_time}, "
                                         f"管道数量={tube_number}, 操作员={operator}, 数据组={data_group}, "
                                         f"大修编号={outage}, SG ID={sg_id}")
                            error_record = {
                                '行号': line_num,
                                '大修编号': outage,
                                'SG ID': sg_id,
                                '数据组': data_group,
                                '操作员': operator,
                                '探头类型': probe_type_raw,
                                '探头编号': probe_sn,
                                '探头型号': model,
                                '管道数量': tube_number,
                                '开始时间': start_time,
                                '结束时间': end_time,
                                '错误类型': '开始时间和结束时间相同',
                                '原始数据': f"开始时间={start_time}, 结束时间={end_time}"
                            }
                            self.error_records.append(error_record)
                        elif delta_seconds < 60:
                            logger.warning(f"时间差小于1分钟 (行 {line_num}): "
                                         f"探头={probe_sn}, 时间差={delta_seconds}秒, 开始时间={start_time}, 结束时间={end_time}, "
                                         f"管道数量={tube_number}, 操作员={operator}, 数据组={data_group}, "
                                         f"大修编号={outage}, SG ID={sg_id}")
                            error_record = {
                                '行号': line_num,
                                '大修编号': outage,
                                'SG ID': sg_id,
                                '数据组': data_group,
                                '操作员': operator,
                                '探头类型': probe_type_raw,
                                '探头编号': probe_sn,
                                '探头型号': model,
                                '管道数量': tube_number,
                                '开始时间': start_time,
                                '结束时间': end_time,
                                '错误类型': '时间差小于1分钟',
                                '原始数据': f"时间差={delta_seconds}秒, 开始时间={start_time}, 结束时间={end_time}"
                            }
                            self.error_records.append(error_record)
                    
                    # 探头类型：直接使用文件中的 Probe Type 值（如 BOBBIN、MRPC 等），不再区分检测/参考
                    # 为了保持数据结构兼容性，使用默认值（实际显示使用 probe_type_raw）
                    probe_type = probe_type_raw if probe_type_raw else ""
                    
                    # 计算检测时长（秒）
                    if start_time and end_time:
                        duration_seconds = (end_time - start_time).total_seconds()
                    else:
                        duration_seconds = 0
                    
                    # 构建事件
                    events = []
                    if start_time:
                        events.append(ProbeEvent(
                            event_type="开始检测",
                            timestamp=start_time,
                            details=f"开始检测 - 管道数量: {tube_number}"
                        ))
                    if end_time:
                        events.append(ProbeEvent(
                            event_type="结束检测",
                            timestamp=end_time,
                            details=f"结束检测 - 耗时: {duration_seconds:.1f}秒"
                        ))
                    
                    # 构建探头记录
                    record = ProbeRecord(
                        probe_sn=probe_sn,
                        model=model,
                        probe_type=probe_type,
                        probe_type_raw=probe_type_raw,
                        tube_number=tube_number,
                        start_time=start_time,
                        end_time=end_time,
                        operator=operator,
                        data_group=data_group,
                        outage=outage,
                        sg_id=sg_id
                    )
                    
                    records.append(record)
                    
                except Exception as e:
                    logger.error(f"解析探头记录失败 (行 {line_num}): {str(e)}")
                    continue
            
            self.probe_records = records
            return records
            
        except Exception as e:
            logger.error(f"解析文件失败: {str(e)}")
            return []
    
    def _parse_excel(
        self,
        file_path: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[ProbeRecord]:
        """
        解析Excel文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            探头记录列表
        """
        records = []
        
        try:
            # 读取Excel文件
            df = pd.read_excel(file_path)
            
            # 提取文件头部信息（如果存在）
            outage = ""
            sg_id = ""
            
            # 检查前几行是否包含头部信息
            for i in range(min(10, len(df))):
                row = df.iloc[i]
                for col in row.index:
                    if isinstance(col, str) and '大修编号' in col:
                        outage = str(row[col]) if pd.notna(row[col]) else ""
                    elif isinstance(col, str) and 'SG ID' in col:
                        sg_id = str(row[col]) if pd.notna(row[col]) else ""
            
            # 确定数据开始行（跳过头部信息）
            data_start_row = 0
            for i in range(len(df)):
                row = df.iloc[i]
                # 检查是否包含探头编号列
                has_probe_sn = False
                for col in row.index:
                    if isinstance(col, str) and any(keyword in col.lower() for keyword in ['probe', 'sn', '编号', '探头']):
                        if pd.notna(row[col]):
                            has_probe_sn = True
                            break
                if has_probe_sn:
                    data_start_row = i
                    break
            
            total_rows = max(len(df) - data_start_row, 1)
            report_interval = max(1, (total_rows + 59) // 60)
            self._emit_progress(progress_callback, 0, total_rows, "Excel文件已读取，正在解析数据行...")

            # 解析数据行
            for idx in range(data_start_row, len(df)):
                row = df.iloc[idx]
                processed_rows = idx - data_start_row + 1
                if (
                    processed_rows == 1
                    or processed_rows == total_rows
                    or processed_rows % report_interval == 0
                ):
                    self._emit_progress(
                        progress_callback,
                        processed_rows,
                        total_rows,
                        f"正在解析Excel数据 {processed_rows}/{total_rows}",
                    )
                
                # 提取关键字段
                probe_sn = ""
                model = ""
                probe_type_raw = ""
                tube_number = 0
                start_time = ""
                end_time = ""
                operator = ""
                data_group = ""
                
                for col in row.index:
                    col_str = str(col)
                    value = row[col]
                    
                    # 处理空值
                    if pd.isna(value):
                        continue
                    
                    col_lower = col_str.lower()

                    # Prefer specific identifiers before generic "编号" matching.
                    if any(keyword in col_lower for keyword in ['outage', '大修']):
                        outage = str(value)
                    elif any(keyword in col_lower for keyword in ['sg_id', 'sg id', '蒸汽发生器', '蒸发器']):
                        sg_id = str(value)
                    # 提取探头类型
                    elif any(keyword in col_lower for keyword in ['type', '类型']):
                        probe_type_raw = str(value)
                    # 提取探头编号
                    elif any(keyword in col_lower for keyword in ['probe', 'sn', '探头编号', '探头编码']):
                        probe_sn = str(value)
                    # 提取探头型号
                    elif any(keyword in col_lower for keyword in ['model', '型号']):
                        model = str(value)
                    # 提取管道数量
                    elif any(keyword in col_lower for keyword in ['tube', '管道', '数量']):
                        try:
                            tube_number = int(value)
                        except ValueError:
                            tube_number = 0
                    # 提取开始时间
                    elif any(keyword in col_lower for keyword in ['start', '开始']):
                        start_time = value
                    # 提取结束时间
                    elif any(keyword in col_lower for keyword in ['end', '结束']):
                        end_time = value
                    # 提取操作员
                    elif any(keyword in col_lower for keyword in ['operator', '操作']):
                        operator = str(value)
                    # 提取数据组
                    elif any(keyword in col_lower for keyword in ['data', 'group', '数据', '组']):
                        data_group = str(value)
                
                # 跳过空行（探头编码为空）
                if pd.isna(probe_sn) or probe_sn == "":
                    continue
                
                # 检查管道数量是否为0
                if tube_number == 0:
                    logger.warning(f"管道数量为0 (行 {idx+2}): "
                                 f"探头={probe_sn}, 管道数量={tube_number}, "
                                 f"操作员={operator}, 数据组={data_group}")
                    error_record = {
                        '行号': idx + 2,
                        '大修编号': outage,
                        'SG ID': sg_id,
                        '数据组': data_group,
                        '操作员': operator,
                        '探头类型': probe_type_raw,
                        '探头编号': probe_sn,
                        '探头型号': model,
                        '管道数量': tube_number,
                        '错误类型': '管道数量为0',
                        '原始数据': f"管道数量={tube_number}, 数据组={data_group}"
                    }
                    self.error_records.append(error_record)
                
                # 探头类型：直接使用文件中的 Probe Type 值（如 BOBBIN、MRPC 等），不再区分检测/参考
                # 为了保持数据结构兼容性，使用默认值（实际显示使用 probe_type_raw）
                probe_type = probe_type_raw if probe_type_raw else ""
                
                # 记录原始值（用于调试）
                start_time_raw = start_time
                end_time_raw = end_time
                
                # 初始化时间变量
                start_time_dt = None
                end_time_dt = None
                
                # 检查开始时间是否为空
                if pd.isna(start_time) or start_time == "":
                    logger.warning(f"开始时间为空 (行 {idx+2}): "
                                 f"探头={probe_sn}, 原始开始时间={start_time_raw}, "
                                 f"管道数量={tube_number}, 操作员={operator}")
                    error_record = {
                        '行号': idx + 2,
                        '大修编号': outage,
                        'SG ID': sg_id,
                        '数据组': data_group,
                        '操作员': operator,
                        '探头类型': probe_type_raw,
                        '探头编号': probe_sn,
                        '探头型号': model,
                        '管道数量': tube_number,
                        '开始时间': start_time_raw,
                        '错误类型': '开始时间为空',
                        '原始数据': f"原始开始时间={start_time_raw}"
                    }
                    self.error_records.append(error_record)
                else:
                    start_time_dt = self._parse_datetime(start_time)
                    if start_time_dt is None:
                        logger.warning(f"开始时间解析失败 (行 {idx+2}): "
                                     f"探头={probe_sn}, 原始开始时间={start_time_raw} (类型={type(start_time_raw)}), "
                                     f"管道数量={tube_number}, 操作员={operator}")
                        error_record = {
                            '行号': idx + 2,
                            '大修编号': outage,
                            'SG ID': sg_id,
                            '数据组': data_group,
                            '操作员': operator,
                            '探头类型': probe_type_raw,
                            '探头编号': probe_sn,
                            '探头型号': model,
                            '管道数量': tube_number,
                            '开始时间': start_time_raw,
                            '错误类型': '开始时间解析失败',
                            '原始数据': f"原始开始时间={start_time_raw}"
                        }
                        self.error_records.append(error_record)
                
                # 检查结束时间是否为空
                if pd.isna(end_time) or end_time == "":
                    logger.warning(f"结束时间为空 (行 {idx+2}): "
                                 f"探头={probe_sn}, 原始结束时间={end_time_raw}, "
                                 f"管道数量={tube_number}, 操作员={operator}")
                    error_record = {
                        '行号': idx + 2,
                        '大修编号': outage,
                        'SG ID': sg_id,
                        '数据组': data_group,
                        '操作员': operator,
                        '探头类型': probe_type_raw,
                        '探头编号': probe_sn,
                        '探头型号': model,
                        '管道数量': tube_number,
                        '结束时间': end_time_raw,
                        '错误类型': '结束时间为空',
                        '原始数据': f"原始结束时间={end_time_raw}"
                    }
                    self.error_records.append(error_record)
                else:
                    end_time_dt = self._parse_datetime(end_time)
                    if end_time_dt is None:
                        logger.warning(f"结束时间解析失败 (行 {idx+2}): "
                                     f"探头={probe_sn}, 原始结束时间={end_time_raw} (类型={type(end_time_raw)}), "
                                     f"管道数量={tube_number}, 操作员={operator}")
                        error_record = {
                            '行号': idx + 2,
                            '大修编号': outage,
                            'SG ID': sg_id,
                            '数据组': data_group,
                            '操作员': operator,
                            '探头类型': probe_type_raw,
                            '探头编号': probe_sn,
                            '探头型号': model,
                            '管道数量': tube_number,
                            '结束时间': end_time_raw,
                            '错误类型': '结束时间解析失败',
                            '原始数据': f"原始结束时间={end_time_raw}"
                        }
                        self.error_records.append(error_record)
                
                # 如果两个时间都为None，记录错误但不再伪造 1900-01-01 时间，
                # 避免后续分析器把占位时间当成真实异常数据。
                if start_time_dt is None and end_time_dt is None:
                    logger.warning(f"开始时间和结束时间均为空 (行 {idx+2}): "
                                 f"探头={probe_sn}, 管道数量={tube_number}, 操作员={operator}, "
                                 f"原始开始={start_time_raw}, 原始结束={end_time_raw}")
                    error_record = {
                        '行号': idx + 2,
                        '大修编号': outage,
                        'SG ID': sg_id,
                        '数据组': data_group,
                        '操作员': operator,
                        '探头类型': probe_type_raw,
                        '探头编号': probe_sn,
                        '探头型号': model,
                        '管道数量': tube_number,
                        '开始时间': start_time_raw,
                        '结束时间': end_time_raw,
                        '错误类型': '开始时间和结束时间均为空',
                        '原始数据': f"原始开始={start_time_raw}, 原始结束={end_time_raw}"
                    }
                    self.error_records.append(error_record)
                    # 对于导出的 SUM 原始表，如果时间和管道数都缺失，直接跳过，
                    # 不将这类无效行继续送入寿命分析。
                    if tube_number == 0:
                        continue
                elif start_time_dt is None:
                    # 只有开始时间为None，使用结束时间作为开始时间
                    logger.warning(f"开始时间为空，使用结束时间作为开始时间 (行 {idx+2}): "
                                 f"探头={probe_sn}, 结束时间={end_time_dt}, 管道数量={tube_number}")
                    error_record = {
                        '行号': idx + 2,
                        '大修编号': outage,
                        'SG ID': sg_id,
                        '数据组': data_group,
                        '操作员': operator,
                        '探头类型': probe_type_raw,
                        '探头编号': probe_sn,
                        '探头型号': model,
                        '管道数量': tube_number,
                        '开始时间': start_time_raw,
                        '结束时间': end_time_dt,
                        '错误类型': '开始时间为空，使用结束时间作为开始时间',
                        '原始数据': f"原始开始时间={start_time_raw}, 结束时间={end_time_dt}"
                    }
                    self.error_records.append(error_record)
                    start_time_dt = end_time_dt
                elif end_time_dt is None:
                    # 结束时间为空，保持为None，不要自动填充
                    logger.warning(f"结束时间为空 (行 {idx+2}): "
                                 f"探头={probe_sn}, 开始时间={start_time_dt}, 管道数量={tube_number}")
                    error_record = {
                        '行号': idx + 2,
                        '大修编号': outage,
                        'SG ID': sg_id,
                        '数据组': data_group,
                        '操作员': operator,
                        '探头类型': probe_type_raw,
                        '探头编号': probe_sn,
                        '探头型号': model,
                        '管道数量': tube_number,
                        '开始时间': start_time_dt,
                        '错误类型': '结束时间为空',
                        '原始数据': f"开始时间={start_time_dt}, 结束时间=空"
                    }
                    self.error_records.append(error_record)
                    # end_time_dt保持为None
                else:
                    # 两个时间都有效，检查时间顺序
                    if end_time_dt < start_time_dt:
                        logger.warning(f"结束时间早于开始时间，跳过该条记录 (行 {idx+2}): "
                                     f"探头={probe_sn}, 管道数量={tube_number}, 操作员={operator}, "
                                     f"原始开始={start_time_dt}, 原始结束={end_time_dt}")
                        error_record = {
                            '行号': idx + 2,
                            '大修编号': outage,
                            'SG ID': sg_id,
                            '数据组': data_group,
                            '操作员': operator,
                            '探头类型': probe_type_raw,
                            '探头编号': probe_sn,
                            '探头型号': model,
                            '管道数量': tube_number,
                            '开始时间': start_time_dt,
                            '结束时间': end_time_dt,
                            '错误类型': '结束时间早于开始时间',
                            '原始数据': f"开始时间={start_time_dt}, 结束时间={end_time_dt}"
                        }
                        self.error_records.append(error_record)
                        continue
                
                # 如果时间仍不完整且管道数量为0，说明这一行缺少完整分析条件，直接跳过
                if tube_number == 0 and (start_time_dt is None or end_time_dt is None):
                    continue

                # 验证时间差：如果时间相同，记录警告（只在两个时间都不为空时检查）
                if start_time_dt and end_time_dt and start_time_dt == end_time_dt:
                    delta_seconds = (end_time_dt - start_time_dt).total_seconds()
                    if delta_seconds < 0:
                        logger.warning(f"结束时间早于开始时间 (行 {idx+2}): "
                                     f"探头={probe_sn}, 开始时间={start_time_dt}, 结束时间={end_time_dt}")
                        # 结束时间早于开始时间，跳过该条记录
                        continue
                    elif delta_seconds == 0:
                        logger.warning(f"开始时间和结束时间相同 (行 {idx+2}): "
                                     f"探头={probe_sn}, 开始时间={start_time_dt}, 结束时间={end_time_dt}, "
                                     f"管道数量={tube_number}, 操作员={operator}, 数据组={data_group}, "
                                     f"大修编号={outage}, SG ID={sg_id}")
                        error_record = {
                            '行号': idx + 2,
                            '大修编号': outage,
                            'SG ID': sg_id,
                            '数据组': data_group,
                            '操作员': operator,
                            '探头类型': probe_type_raw,
                            '探头编号': probe_sn,
                            '探头型号': model,
                            '管道数量': tube_number,
                            '开始时间': start_time_dt,
                            '结束时间': end_time_dt,
                            '错误类型': '开始时间和结束时间相同',
                            '原始数据': f"开始时间={start_time_dt}, 结束时间={end_time_dt}"
                        }
                        self.error_records.append(error_record)
                    elif delta_seconds < 60:
                        logger.warning(f"时间差小于1分钟 (行 {idx+2}): "
                                     f"探头={probe_sn}, 时间差={delta_seconds}秒, 开始时间={start_time_dt}, 结束时间={end_time_dt}, "
                                     f"管道数量={tube_number}, 操作员={operator}, 数据组={data_group}, "
                                     f"大修编号={outage}, SG ID={sg_id}")
                        error_record = {
                            '行号': idx + 2,
                            '大修编号': outage,
                            'SG ID': sg_id,
                            '数据组': data_group,
                            '操作员': operator,
                            '探头类型': probe_type_raw,
                            '探头编号': probe_sn,
                            '探头型号': model,
                            '管道数量': tube_number,
                            '开始时间': start_time_dt,
                            '结束时间': end_time_dt,
                            '错误类型': '时间差小于1分钟',
                            '原始数据': f"时间差={delta_seconds}秒, 开始时间={start_time_dt}, 结束时间={end_time_dt}"
                        }
                        self.error_records.append(error_record)
                
                # 计算检测时长（秒）
                if start_time_dt and end_time_dt:
                    duration_seconds = (end_time_dt - start_time_dt).total_seconds()
                else:
                    duration_seconds = 0
                
                # 构建事件
                events = []
                if start_time_dt:
                    events.append(ProbeEvent(
                        event_type="开始检测",
                        timestamp=start_time_dt,
                        details=f"开始检测 - 管道数量: {tube_number}"
                    ))
                if end_time_dt:
                    events.append(ProbeEvent(
                        event_type="结束检测",
                        timestamp=end_time_dt,
                        details=f"结束检测 - 耗时: {duration_seconds:.1f}秒"
                    ))
                
                # 构建探头记录
                record = ProbeRecord(
                    probe_sn=probe_sn,
                    model=model,
                    probe_type=probe_type,
                    probe_type_raw=probe_type_raw,
                    tube_number=tube_number,
                    start_time=start_time_dt,
                    end_time=end_time_dt,
                    operator=operator,
                    data_group=data_group,
                    outage=outage,
                    sg_id=sg_id
                )
                
                records.append(record)
            
            self.probe_records = records
            self._emit_progress(progress_callback, total_rows, total_rows, "Excel数据解析完成")
            return records
            
        except Exception as e:
            logger.error(f"解析Excel文件失败: {str(e)}")
            return []
    
    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """
        解析时间字符串为datetime对象
        
        Args:
            value: 时间值（字符串或其他类型）
            
        Returns:
            datetime对象，解析失败返回None
        """
        if value is None:
            return None
        
        if isinstance(value, datetime):
            return value
        
        if not isinstance(value, str):
            try:
                # 尝试转换为字符串
                value = str(value)
            except:
                return None
        
        # 去除空白字符
        value = value.strip()
        if not value:
            return None
        
        # 尝试多种时间格式
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y/%m/%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
            '%Y/%m/%d %H:%M',
            '%H:%M:%S',
            '%H:%M',
            '%Y-%m-%d',
            '%Y/%m/%d'
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        
        return None
    
    def export_error_records(self, output_path: str = None) -> str:
        """
        导出错误记录到Excel文件
        
        Args:
            output_path: 输出文件路径，如果为None则使用默认路径
            
        Returns:
            导出文件的路径
        """
        if not self.error_records:
            logger.info("没有错误记录需要导出")
            return None
        
        if not PANDAS_AVAILABLE:
            raise ImportError("需要安装pandas和openpyxl来导出错误记录: pip install pandas openpyxl")
        
        if output_path is None:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"error_records_{timestamp}.xlsx"
        
        try:
            # 构建符合源文件格式的错误记录
            formatted_records = []
            for record in self.error_records:
                # 按照源文件格式构建记录
                formatted_record = {
                    '行号': record.get('行号', ''),
                    '大修编号': record.get('大修编号', ''),
                    'SG ID': record.get('SG ID', ''),
                    '数据组': record.get('数据组', ''),
                    '操作员': record.get('操作员', ''),
                    '探头类型': record.get('探头类型', ''),
                    '探头编号': record.get('探头编号', ''),
                    '探头型号': record.get('探头型号', ''),
                    '管道数量': record.get('管道数量', ''),
                    '开始时间': record.get('开始时间', ''),
                    '结束时间': record.get('结束时间', ''),
                    '错误类型': record.get('错误类型', ''),
                    '原始数据': record.get('原始数据', '')
                }
                formatted_records.append(formatted_record)
            
            df = pd.DataFrame(formatted_records)
            df.to_excel(output_path, index=False, engine='openpyxl')
            logger.info(f"已导出 {len(self.error_records)} 条错误记录到 {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"导出错误记录失败: {str(e)}")
            raise
