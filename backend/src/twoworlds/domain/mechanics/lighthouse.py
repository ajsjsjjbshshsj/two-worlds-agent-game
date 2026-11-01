"""灯塔的当前反馈与阶段不变量；只依据确定事实，不读取文件或调用模型。"""

from twoworlds.content.schema import ScriptVersion

from ..errors import DomainError
from ..models import GameState, Observation
from .common import conditions_met

_DIRECTIONS = {0: "暗礁", 90: "内湾航道", 180: "观测山", 270: "外海港"}


def observations(state: GameState, script: ScriptVersion) -> tuple[Observation, ...]:
    if state.scene_id == "calibration":
        angle = state.device("emitter", "angle")
        pattern = state.device("emitter", "pattern")
        filter_value = state.device("filter", "filter")
        a = f"发射器当前角度{angle}°，光型{pattern}。请询问另一端的实际观察。"
        if "b_sea_chart" not in state.discovered_clues:
            b = "光束仍需辨认；请先检查本人航道图，再与另一端交流。"
        elif pattern == "pulse" and filter_value == "amber":
            b = f"光束稳定，当前落向{_DIRECTIONS[angle]}。"
        else:
            b = f"光束模糊，当前滤镜{filter_value}，尚不能稳定识别航道。"
        return (
            Observation(audience="a", topic="emitter", text=a),
            Observation(audience="b", topic="beam", text=b),
        )
    if state.scene_id == "repair":
        powered = state.device("power_router", "target") == "tower"
        repaired = state.fact("clock_repaired")
        scan = (
            "内湾信号稳定，可确认航道。"
            if powered and repaired
            else "扫描不可用，请等待时钟修复并保持灯塔供电。"
        )
        clock = "时钟已修复，维修记录保留。" if repaired else "时钟尚未修复。"
        return (
            Observation(
                audience="a",
                topic="clock_power",
                text="时钟箱有电，可以检查齿轮。"
                if powered
                else "时钟箱无电，请与搭档核对供电。",
            ),
            Observation(audience="a", topic="clock_status", text=clock),
            Observation(
                audience="b",
                topic="power_route",
                text=f"当前能源去向：{state.device('power_router', 'target')}。",
            ),
            Observation(audience="b", topic="route_scan", text=scan),
        )
    if state.scene_id == "decision":
        return tuple(
            Observation(
                audience=role,
                topic="joint_decision",
                text="航路已通过共同验证；两种结局均可选择，一致前允许修改本人选择。",
            )
            for role in ("a", "b")
        )
    ending = next(item for item in script.endings if item.id == state.ending_id)
    return tuple(
        Observation(audience=role, topic="ending", text=ending.summary_template)
        for role in ("a", "b")
    )


def validate_invariants(state: GameState, script: ScriptVersion) -> None:
    locked = state.fact("signal_locked")
    repaired = state.fact("clock_repaired")
    route = state.fact("route_confirmed")
    gears = "a_clock_gears" in state.discovered_clues
    if (
        locked is not (state.scene_id != "calibration")
        or state.fact("repair_tools_ready") is not gears
        or (gears and not locked)
        or (repaired and not gears)
        or (route is not (state.scene_id in {"decision", "completed"}))
        or (route and not repaired)
        or (state.votes and state.scene_id not in {"decision", "completed"})
    ):
        raise DomainError("INVALID_STATE")
    if locked:
        lock = next(item for item in script.actions if item.kind == "lock_signal")
        if not conditions_met(state, lock.preconditions):
            raise DomainError("INVALID_STATE")
