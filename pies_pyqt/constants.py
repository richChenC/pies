from __future__ import annotations

from pathlib import Path

APP_TITLE = "涡流检测探头信息提取软件"
SINGLE_INSTANCE_PORT = 54321
DEFAULT_WINDOW_SIZE = (1520, 900)
MIN_WINDOW_SIZE = (1280, 760)

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
LOGO_PATH = PACKAGE_ROOT / "assets" / "PIES设计软件图标.png"
SOFTWARE_MANUAL_PATH = PACKAGE_ROOT / "resources" / "software_manual.md"
LEGACY_HISTORY_STORE_PATH = PACKAGE_ROOT / "probe_history.json"
HISTORY_STORE_PATH = PROJECT_ROOT / "SaveDate" / "probe_history.json"

RAW_TABLE_HEADERS = [
    "序号",
    "大修",
    "蒸汽发生器编号",
    "数据组",
    "操作员",
    "探头类型",
    "探头编码",
    "探头型号",
    "管道数量",
    "累计管道数量",
    "开始时间",
    "结束时间",
]

SUMMARY_TABLE_HEADERS = [
    "序号",
    "大修",
    "蒸汽发生器编号",
    "数据组",
    "操作员",
    "探头类型",
    "探头编码",
    "探头型号",
    "管道数量",
    "累计管道数量",
    "开始时间",
    "结束时间",
    "单次使用时间(小时)",
    "单次使用时间(分钟)",
    "总使用次数",
    "总使用时间(小时)",
    "最长连续使用(小时)",
    "检测速度(管道/小时)",
    "首次使用日期",
    "末次使用日期",
]

FILTER_FIELDS = [
    ("probe", "探头编码"),
    ("type", "探头类型"),
    ("group", "数据组"),
    ("operator", "操作员"),
    ("model", "探头型号"),
    ("keyword", "全局关键字"),
]

CHART_GROUPS = {
    "按探头编号统计": [
        ("使用时间", "总使用时间折线图"),
        ("使用次数", "总使用次数折线图"),
        ("检测管道数量", "管道数量折线图"),
        ("检测速度", "探头检测速度折线图"),
    ],
    "按探头类型统计": [
        ("探头类型分布", "探头类型分布图"),
        ("探头型号分布", "探头型号分布饼图"),
        ("型号平均检测速度", "探头型号平均检测速度图"),
        ("批次平均寿命", "生产批次平均寿命图"),
    ],
}

SOFTWARE_NOTES = [
    "可直接读取本地文件夹或网络共享目录中的 SUM 数据，读取过程只读，不会修改源文件。",
    "单个最小数据文件夹处理完成后生成一份对应 Excel，批量导入时会自动遍历满足条件的子文件夹。",
    "探头寿命以累计检测管道数量为主，时间信息仅用于记录班次过程与异常核对。",
    "Start Time 与 End Time 优先取同组 999 标记文件的最后修改时间；缺失 999 时会提示异常，不回填伪造时间。",
    "Tube Number 只统计真实检测管道，不计 999、888 开头等标记类文件；表格中的累计管道数量会持续累加。",
    "所有图表、表格和异常提醒都会跟随当前筛选条件同步刷新。",
]

SAFETY_REMINDERS = [
    "支持直接读取网络服务器或共享目录中的数据文件，程序只读访问，不会修改源文件。",
    "分析结果、导出文件和历史记录仅写入本机工作目录或你选择的保存位置，不回写源目录。",
    "导入网络路径时，请确保当前账号只有读取权限或至少不要在源目录中执行人工编辑。",
    "历史记录与缓存仅用于本机统计分析，不会覆盖、重命名或删除原始数据。",
]

WARNING_TIPS = [
    "建议优先核对大修编号、SG、数据组、时间字段和管道数量等上下文信息。",
    "若警告与源数据不一致，建议重新导入或修正源数据后再分析。",
]
