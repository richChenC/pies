"""
数据模型定义模块
定义系统的核心数据结构：探头记录、使用段、统计信息等
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict
import re

MODEL_ALIASES = {
    "CPRS/DH3/MR/16.87": "CRPS/DH3/MR/16.87",
}


def normalize_model_name(model: str) -> str:
    normalized = (model or "").strip().upper()
    normalized = normalized.replace("\\", "/")
    normalized = normalized.replace("／", "/")
    normalized = normalized.replace("—", "-").replace("–", "-").replace("－", "-")
    normalized = re.sub(r"\s+", "", normalized)
    normalized = MODEL_ALIASES.get(normalized, normalized)
    return normalized


@dataclass
class ProbeEvent:
    """
    探头事件
    表示探头使用过程中的重要事件
    """
    event_type: str  # 事件类型（如"开始检测"、"结束检测"等）
    timestamp: datetime  # 事件发生时间
    details: str = ""  # 事件详情


@dataclass
class ProbeRecord:
    """
    探头使用记录
    表示单次探头使用的完整信息
    """
    probe_sn: str  # 探头序列号
    probe_type: str  # 探头类型（直接使用文件中的 Probe Type 值，如 BOBBIN、MRPC 等）
    start_time: datetime  # 开始使用时间
    end_time: datetime  # 结束使用时间
    tube_number: int  # 管道数量
    operator: str  # 操作员
    data_group: str  # 数据组标识
    model: str  # 探头型号
    probe_type_raw: str = ""  # 原始探头类型字符串（如 "BOBBIN"、"MRPC" 等），用于保持原始数据显示
    outage: str = ""  # 大修标识（如 "D223"）
    sg_id: str = ""  # 蒸汽发生器编号
    warnings: List[str] = field(default_factory=list)  # 该记录的警告信息列表
    warning_line_number: str = ""  # 异常占位记录对应的原始行号，仅用于表格展示和去重
    
    @property
    def normalized_probe_type(self) -> str:
        return (self.probe_type_raw or self.probe_type or "").strip().upper()

    @property
    def normalized_model(self) -> str:
        return normalize_model_name(self.model)

    @property
    def stat_key(self) -> str:
        return f"{self.probe_sn.strip()}|{self.normalized_probe_type}|{self.normalized_model}"

    @property
    def display_name(self) -> str:
        probe_type = self.normalized_probe_type or "UNKNOWN"
        model = self.normalized_model or "UNKNOWN"
        return f"{self.probe_sn} [{probe_type}/{model}]"

    @property
    def duration_minutes(self) -> float:
        """
        计算使用时长（分钟）
        
        Returns:
            float: 使用时长（分钟），如果时间无效则返回 0.0
        """
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time).total_seconds() / 60.0
        return 0.0


@dataclass
class UsageSession:
    """
    使用段
    表示一次连续使用或更换后再次使用的周期
    实际划分规则由 ProbeAnalyzer._identify_usage_sessions 综合时间间隔、
    数据组编号（Data_Group）和蒸汽发生器编号（SG_ID）共同决定，不再简单只看“间隔是否大于30分钟”
    """
    session_id: int  # 使用段编号（从1开始）
    start_time: datetime  # 使用段开始时间
    end_time: datetime  # 使用段结束时间
    records: List[ProbeRecord] = field(default_factory=list)  # 该使用段内的所有记录
    is_continuous: bool = True  # 是否为连续使用（默认True，表示段内记录连续）
    
    @property
    def duration_minutes(self) -> float:
        """
        计算使用段持续时间（分钟）
        
        Returns:
            float: 使用段持续时间（分钟），如果时间无效则返回 0.0
        """
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time).total_seconds() / 60.0
        return 0.0
    
    @property
    def use_count(self) -> int:
        """
        获取使用段内的使用次数
        
        Returns:
            int: 该使用段内的记录数量
        """
        return len(self.records)


@dataclass
class ProbeStatistics:
    """
    探头统计信息
    汇总单个探头的所有使用记录和统计指标
    """
    probe_sn: str  # 探头序列号
    probe_type: str  # 探头类型（直接使用文件中的 Probe Type 值，如 BOBBIN、MRPC 等）
    model: str
    stat_key: str
    total_uses: int  # 总使用次数
    total_duration_minutes: float  # 总使用时长（分钟）
    first_use_time: Optional[datetime]  # 首次使用时间
    last_use_time: Optional[datetime]  # 末次使用时间
    records: List[ProbeRecord]  # 所有使用记录列表
    usage_sessions: List[UsageSession] = field(default_factory=list)  # 所有使用段列表
    reuse_details: List[Dict] = field(default_factory=list)  # 更换后再次使用的中间占用详情
    continuous_gap_threshold_minutes: float = 30.0  # 连续使用间隔阈值（分钟），超过此值视为更换后再次使用
    
    @property
    def display_name(self) -> str:
        probe_type = (self.probe_type or "").strip().upper() or "UNKNOWN"
        model = normalize_model_name(self.model) or "UNKNOWN"
        return f"{self.probe_sn} [{probe_type}/{model}]"

    @property
    def lifetime_hours(self) -> float:
        """
        计算总使用寿命（小时）
        
        Returns:
            float: 总使用时长转换为小时
        """
        return self.total_duration_minutes / 60.0
    
    @property
    def is_continuous_use(self) -> bool:
        """
        判断是否完全连续使用（无更换后再次使用的情况）
        
        Returns:
            bool: True表示完全连续使用（使用段数 <= 1），False表示有更换后再次使用
        """
        return len(self.usage_sessions) <= 1
    
    @property
    def continuous_use_count(self) -> int:
        """
        获取使用段数（连续使用段的数量）
        
        Returns:
            int: 使用段数，> 1 表示探头有更换后再次使用的情况
        """
        return len(self.usage_sessions)
    
    @property
    def longest_continuous_duration_minutes(self) -> float:
        """
        计算最长连续使用时长（分钟）
        
        Returns:
            float: 所有使用段中最长的持续时间（分钟），如果没有使用段则返回 0.0
        """
        if not self.usage_sessions:
            return 0.0
        return max(session.duration_minutes for session in self.usage_sessions)
    
    @property
    def longest_continuous_duration_hours(self) -> float:
        """
        计算最长连续使用时长（小时）
        
        Returns:
            float: 最长连续使用时长转换为小时
        """
        return self.longest_continuous_duration_minutes / 60.0
    
    @property
    def unique_tube_count(self) -> int:
        """
        计算累计检测管道数量（所有记录中tube_number的总和）
        
        Returns:
            int: 该探头累计检测的管道数量总和
        """
        return sum(r.tube_number for r in self.records if r.tube_number is not None and r.tube_number > 0)
    
    @property
    def detection_speed(self) -> float:
        """
        计算探头检测速度（管道数量/小时）
        
        Returns:
            float: 检测速度，单位为管道数量/小时。如果总时间为0则返回0.0
        """
        if self.total_duration_minutes <= 0:
            return 0.0
        total_hours = self.total_duration_minutes / 60.0
        return self.unique_tube_count / total_hours
