"""可预测的规则拒绝，不携带原始命令、私密线索或完整世界。"""

_MESSAGES = {
    "INVALID_STATE": "当前世界状态无效，不能执行操作。",
    "INVALID_SCRIPT": "剧本定义与当前规则不兼容。",
    "SCRIPT_UNSUPPORTED": "当前规则尚不支持此剧本。",
    "SCRIPT_MISMATCH": "当前状态与剧本版本不匹配。",
    "INVALID_COMMAND": "命令格式无效。",
    "UNKNOWN_ACTION": "当前规则不支持此操作。",
    "INVALID_ARGUMENTS": "操作参数无效。",
    "ROLE_FORBIDDEN": "当前角色不能执行此操作。",
    "ACTION_UNAVAILABLE": "当前阶段不能执行此操作。",
    "CLUE_NOT_DISCOVERED": "请先检查自己一侧的记录。",
    "CLUE_NOT_SHAREABLE": "这条线索不可分享。",
    "INVALID_PUBLIC_EVENT": "公共事件无效。",
    "INVALID_PUBLIC_HISTORY": "公共历史无效或不完整。",
    "PUBLIC_HISTORY_VERSION": "公共历史版本无法接受此次记录。",
    "PUBLIC_MILESTONE_LIMIT": "公共里程碑已达上限。",
    "ALREADY_DISCOVERED": "你已经检查过这条线索。",
    "SIGNAL_UNSTABLE": "当前信号还不能稳定锁定。",
    "SIGNAL_NOT_LOCKED": "请先锁定跨时信号。",
    "CLOCK_UNPOWERED": "灯塔时钟当前无电。",
    "TOOLS_NOT_READY": "请先检查齿轮并取得检修工具。",
    "REPAIR_MODE_UNSAFE": "快速维修不安全，请按已取得的说明操作。",
    "CLOCK_NOT_REPAIRED": "时钟尚未修复，不能确认航道。",
    "ENDING_UNAVAILABLE": "当前还不能进行共同选择。",
    "PRECONDITION_NOT_MET": "当前还不满足操作条件。",
    "NO_STATE_CHANGE": "当前设置或选择没有变化。",
    "SAVE_COMPLETED": "本次故事已经完成，不能再修改结果。",
    "POWER_BUDGET_EXCEEDED": "能源方案超过5单位预算，整组配置未改变。",
    "WRONG_TRACK": "接车轨道尚未与已确认的列车信号对位。",
    "SCAN_UNAVAILABLE": "声呐扫描需要东侧回声通道、声呐供电并关闭引擎。",
    "TRACK_NOT_SCANNED": "请先由列车端实际扫描定位缺轨段。",
    "SIGNAL_UNAVAILABLE": "信号灯当前无电，不能确认灯号。",
    "SIGNAL_NOT_CONFIRMED": "请先由列车端确认真实灯号。",
    "DISPATCH_NOT_READY": "接车需要导轨安装、信号确认以及引擎和灯开启、声呐关闭。",
}


class DomainError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(_MESSAGES.get(code, _MESSAGES["PRECONDITION_NOT_MET"]))
