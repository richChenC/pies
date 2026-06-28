"""
SUM文件解析器
用于解析XML格式的Summary文件并转换为标准数据格式
"""
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import logging
from dataclasses import dataclass
import re

logger = logging.getLogger(__name__)


class MissingGroupMarkerError(Exception):
    """数据组缺少 999 标记 ECT 文件。"""

    def __init__(self, group_dir: Path):
        self.group_dir = Path(group_dir)
        super().__init__(f"数据组 {self.group_dir} 未找到 999 标记 ECT 文件，已按异常跳过")

@dataclass
class SumRecord:
    """SUM文件记录数据模型"""
    probe_sn: str = ""              # 探头编码
    model: str = ""                 # 探头型号
    probe_type: str = ""            # 探头类型
    operator_id: str = ""           # 操作员ID（拼音缩写）
    operator_name: str = ""         # 操作员名称（兼容旧批量处理逻辑）
    outage: str = ""                # 大修标识（从路径或SUM文件）
    sg_id: str = ""                 # 蒸汽发生器编号（从路径或SUM文件）
    data_group: str = ""            # 数据组（从路径提取）
    start_time: Optional[datetime] = None    # 开始时间
    end_time: Optional[datetime] = None      # 结束时间（暂时未知来源）
    tube_count: str = ""            # 管道数量（暂时未知来源）
    file_path: str = ""             # 源文件路径

    @property
    def speed(self) -> float:
        """兼容旧批量处理逻辑：按管道数量/小时返回检测速度。"""
        if not self.start_time or not self.end_time:
            return 0.0

        duration_seconds = (self.end_time - self.start_time).total_seconds()
        if duration_seconds <= 0:
            return 0.0

        try:
            tube_count = int(self.tube_count or 0)
        except (TypeError, ValueError):
            return 0.0

        return tube_count / (duration_seconds / 3600.0)

class SumFileParser:
    """SUM文件解析器"""

    GROUP_MARKER_PATTERN = re.compile(r'^[A-Z]*999', re.IGNORECASE)
    AUXILIARY_ECT_PATTERN = re.compile(r'^[A-Z]*888', re.IGNORECASE)
    ECT_SEQUENCE_PATTERN = re.compile(r'I(\d+)$', re.IGNORECASE)
    
    def __init__(self):
        self.supported_extensions = {'.sum'}
        self.invalid_group_errors: List[Dict[str, str]] = []
    
    def parse_file(self, file_path: Path) -> Optional[SumRecord]:
        """
        解析单个SUM文件
        
        Args:
            file_path: SUM文件路径
            
        Returns:
            SumRecord对象，解析失败返回None
        """
        try:
            if file_path.suffix.lower() not in self.supported_extensions:
                logger.warning(f"不支持的文件格式: {file_path}")
                return None
            
            # 解析XML文件
            tree = ET.parse(file_path)
            root = tree.getroot()
            
            record = SumRecord()
            record.file_path = str(file_path)
            
            # 从文件路径提取信息
            path_info = self._extract_path_info(file_path)
            record.outage = path_info.get('outage', '')
            record.sg_id = path_info.get('sg_id', '')
            record.data_group = path_info.get('data_group', '')
            
            # 解析站点信息
            site = root.find('Site')
            if site is not None:
                # 如果路径中没有提取到，则从SUM文件读取
                if not record.outage:
                    record.outage = self._get_text(site, 'Outage')
                
                if not record.sg_id:
                    component = self._get_text(site, 'Component')
                    component_id = self._get_text(site, 'ComponentId')
                    if component == 'SG' and component_id:
                        record.sg_id = component_id.strip()
                
                # 解析开始时间
                datetime_str = self._get_text(site, 'DateTime')
                if datetime_str:
                    record.start_time = self._parse_datetime(datetime_str)
            
            # 解析操作员信息 - 只保留拼音缩写（Id字段）
            operator = root.find('Operator')
            if operator is not None:
                operator_id = self._get_text(operator, 'Id')
                operator_name = self._get_text(operator, 'Name')
                # 去除可能的空格
                record.operator_id = operator_id.strip()
                record.operator_name = operator_name.strip()
            
            # 解析探头信息
            probe = root.find('Probe')
            if probe is not None:
                record.probe_sn = self._get_text(probe, 'Sn')
                record.model = self._get_text(probe, 'Model')
                record.probe_type = self._get_text(probe, 'Type')
            
            ect_info = self._extract_ect_group_info(file_path.parent)
            record.tube_count = ect_info.get('tube_count', '')
            if ect_info.get('start_time'):
                record.start_time = ect_info['start_time']
            record.end_time = ect_info.get('end_time')
            
            logger.info(f"成功解析SUM文件: {file_path}")
            return record
            
        except MissingGroupMarkerError as e:
            logger.warning(str(e))
            self._register_invalid_group(file_path, str(e))
            return None
        except ET.ParseError as e:
            reason = f"XML解析错误: {e}"
            logger.error(f"{reason} {file_path}")
            self._register_invalid_sum_file(file_path, reason)
            return None
        except Exception as e:
            reason = f"解析SUM文件失败: {e}"
            logger.error(f"{reason} {file_path}")
            self._register_invalid_sum_file(file_path, reason)
            return None
    
    def parse_directory(self, directory_path: Path, progress_callback=None, recursive: bool = True) -> List[SumRecord]:
        """
        解析目录中的所有SUM文件
        
        Args:
            directory_path: 目录路径
            progress_callback: 进度回调函数，接收 (current, total, filename) 参数
            recursive: 是否递归解析子目录。批量处理多个数据组时应设为 False，避免重复解析。
            
        Returns:
            SumRecord对象列表
        """
        records = []
        self.invalid_group_errors = []
        
        if not directory_path.exists() or not directory_path.is_dir():
            logger.error(f"目录不存在或不是有效目录: {directory_path}")
            return records
        
        # 先收集所有SUM文件
        sum_files = []
        iterator = directory_path.rglob('*') if recursive else directory_path.iterdir()
        for file_path in iterator:
            if file_path.is_file() and file_path.suffix.lower() in self.supported_extensions:
                sum_files.append(file_path)
        
        total_files = len(sum_files)
        logger.info(f"找到 {total_files} 个SUM文件")
        
        # 解析每个文件并报告进度
        for index, file_path in enumerate(sum_files, 1):
            if progress_callback:
                progress_callback(index, total_files, file_path.name)
            
            record = self.parse_file(file_path)
            if record:
                records.append(record)
        
        logger.info(f"从目录 {directory_path} 解析到 {len(records)} 个SUM记录")
        return records

    def _register_invalid_group(self, file_path: Path, reason: str):
        group_dir = str(file_path.parent)
        for item in self.invalid_group_errors:
            if item.get('error_scope') == 'group' and item.get('group_dir') == group_dir:
                return

        self.invalid_group_errors.append({
            'sum_file': str(file_path),
            'group_dir': group_dir,
            'data_group': file_path.parent.name,
            'reason': reason,
            'error_scope': 'group',
            'error_type': '缺少999标记ECT文件',
        })

    def _register_invalid_sum_file(self, file_path: Path, reason: str):
        sum_file = str(file_path)
        for item in self.invalid_group_errors:
            if item.get('error_scope') == 'file' and item.get('sum_file') == sum_file:
                return

        self.invalid_group_errors.append({
            'sum_file': sum_file,
            'group_dir': str(file_path.parent),
            'data_group': file_path.parent.name,
            'reason': reason,
            'error_scope': 'file',
            'error_type': 'SUM文件解析失败',
        })
    
    def _get_text(self, parent: ET.Element, tag: str) -> str:
        """安全获取XML元素文本内容"""
        element = parent.find(tag)
        return element.text.strip() if element is not None and element.text else ""
    
    def _extract_path_info(self, file_path: Path) -> dict:
        """
        从文件路径提取信息
        路径示例: D123/BOBBIN/SG1/SG1C23CAL00101/SUR000C000I000.SUM
        """
        import re
        
        info = {}
        path_parts = file_path.parts
        
        # 遍历路径各部分
        for part in path_parts:
            # 提取大修信息（如D123、D224等）
            if re.match(r'^[Dd]\d{3,4}$', part):
                info['outage'] = part.upper()
            
            # 提取SG编号（如SG1、SG2、SG3等）
            if re.match(r'^[Ss][Gg](\d+)$', part):
                match = re.match(r'^[Ss][Gg](\d+)$', part)
                if match:
                    info['sg_id'] = match.group(1)
            
            # 提取数据组（如SG1C23CAL00101等，通常包含SG和CAL）
            if 'CAL' in part.upper() and re.search(r'[Ss][Gg]\d+', part):
                info['data_group'] = part
        
        return info
    
    def _parse_datetime(self, datetime_str: str) -> Optional[datetime]:
        """解析时间字符串"""
        try:
            # 处理带时区的ISO格式时间
            if '+' in datetime_str:
                datetime_str = datetime_str.split('+')[0]
            elif '-' in datetime_str and datetime_str.count('-') > 2:
                # 处理负时区的情况
                parts = datetime_str.rsplit('-', 1)
                if len(parts) == 2 and ':' in parts[1]:
                    datetime_str = parts[0]
            
            # 处理微秒部分
            if 'T' in datetime_str and '.' in datetime_str:
                datetime_str = datetime_str.split('.')[0]
            
            # 尝试不同的时间格式
            formats = [
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%d %H:%M:%S',
                '%Y/%m/%d %H:%M:%S',
                '%Y-%m-%d',
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(datetime_str, fmt)
                except ValueError:
                    continue
            
            logger.warning(f"无法解析时间格式: {datetime_str}")
            return None
            
        except Exception as e:
            logger.error(f"时间解析错误: {e}")
            return None

    def _extract_ect_group_info(self, group_dir: Path) -> Dict[str, Optional[datetime]]:
        """
        从同一数据组目录下的 ECT 文件属性中提取：
        1. 排除 999/888 开头后的真实 ECT 文件数量，作为 Tube Number
        2. 开组 999 ECT 文件的最后修改时间，作为 Start Time
        3. 结束 999 ECT 文件的最后修改时间，作为 End Time
        """
        ect_files = sorted(
            [
                path for path in group_dir.iterdir()
                if path.is_file() and path.suffix.lower() == '.ect'
            ],
            key=self._ect_sort_key,
        )
        marker_files = [path for path in ect_files if self._is_group_marker_ect(path)]
        real_tube_files = [
            path for path in ect_files
            if not self._is_group_marker_ect(path) and not self._is_auxiliary_non_tube_ect(path)
        ]

        start_time = self._get_file_timestamp(marker_files[0]) if marker_files else None
        end_time = self._get_file_timestamp(marker_files[-1]) if marker_files else None

        if not marker_files:
            raise MissingGroupMarkerError(group_dir)

        return {
            'tube_count': str(len(real_tube_files)) if real_tube_files else '',
            'start_time': start_time,
            'end_time': end_time,
        }

    def _is_group_marker_ect(self, ect_file: Path) -> bool:
        return bool(self.GROUP_MARKER_PATTERN.match(ect_file.stem.upper()))

    def _is_auxiliary_non_tube_ect(self, ect_file: Path) -> bool:
        return bool(self.AUXILIARY_ECT_PATTERN.match(ect_file.stem.upper()))

    def _ect_sort_key(self, ect_file: Path):
        stem = ect_file.stem.upper()
        seq_match = self.ECT_SEQUENCE_PATTERN.search(stem)
        sequence = int(seq_match.group(1)) if seq_match else 10**9
        return (sequence, stem)

    def _get_file_timestamp(self, ect_file: Path) -> Optional[datetime]:
        try:
            return datetime.fromtimestamp(ect_file.stat().st_mtime)
        except Exception as exc:
            logger.warning(f"ECT 文件时间读取失败 {ect_file}: {exc}")
            return None
    
    def records_to_dict_list(self, records: List[SumRecord]) -> List[Dict]:
        """
        将SumRecord列表转换为字典列表，便于导出到Excel
        
        Args:
            records: SumRecord对象列表
            
        Returns:
            字典列表，每个字典包含一行数据
        """
        dict_list = []
        
        for i, record in enumerate(records, 1):
            start_time_str = record.start_time.strftime('%Y/%m/%d %H:%M:%S') if record.start_time else ''
            end_time_str = record.end_time.strftime('%Y/%m/%d %H:%M:%S') if record.end_time else ''
            row_dict = {
                '序号': i,
                'Outage': record.outage,
                'SG_ID': record.sg_id,
                'Data Group': record.data_group,
                'Operator': record.operator_id,
                'Probe Type': record.probe_type,
                'Probe SN': record.probe_sn,
                'Model': record.model,
                'Tube Number': record.tube_count,
                'Start Time': start_time_str,
                'End Time': end_time_str,
                '源文件': record.file_path
            }
            
            dict_list.append(row_dict)
        
        return dict_list

# 使用示例
if __name__ == "__main__":
    # 测试解析单个文件
    parser = SumFileParser()
    
    # 解析单个SUM文件
    sum_file = Path("SUR000C000I000.SUM")
    if sum_file.exists():
        record = parser.parse_file(sum_file)
        if record:
            print("解析结果:")
            print(f"探头编码: {record.probe_sn}")
            print(f"探头型号: {record.model}")
            print(f"操作员: {record.operator_name}")
            print(f"开始时间: {record.start_time}")
            
            # 转换为字典格式
            dict_list = parser.records_to_dict_list([record])
            print("\n字典格式:")
            for key, value in dict_list[0].items():
                print(f"{key}: {value}")
