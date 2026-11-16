"""Starline-specific power/track guards, personal feedback and world invariants.

Ordinary prerequisites, effects, scene transitions and votes stay in common.py.
No wall clock, filesystem, database or model participates in the rules.
"""

from twoworlds.content.schema import ActionDefinition, ScriptVersion

from ..errors import DomainError
from ..models import GameState, Observation

POWER_BUDGET = 5


def power_used(engine: bool, sonar: bool, lamp: bool) -> int:
    return 3 * engine + 3 * sonar + lamp


def check_action(state: GameState, definition: ActionDefinition, args: dict) -> None:
    # Validate the whole proposed group BEFORE common.apply_effect changes even
    # one field. Never repair an over-budget proposal by disabling another switch.
    if definition.kind == "allocate_power" and power_used(**args) > POWER_BUDGET:
        raise DomainError("POWER_BUDGET_EXCEEDED")
    if (
        definition.kind == "dispatch_train"
        and state.device("platform", "track") != "track_2"
    ):
        raise DomainError("WRONG_TRACK")


def _power(state: GameState) -> tuple[bool, bool, bool]:
    return tuple(
        state.device("power_panel", key) for key in ("engine", "sonar", "lamp")
    )


def observations(state: GameState, script: ScriptVersion) -> tuple[Observation, ...]:
    if state.scene_id in {"decision", "completed"}:
        text = (
            "接车已经完成；绕行救援与直接归站都可选择，一致前可以修改本人投票。"
            if state.scene_id == "decision"
            else next(
                e.summary_template for e in script.endings if e.id == state.ending_id
            )
        )
        return tuple(
            Observation(
                audience=role,
                topic="joint_decision" if state.scene_id == "decision" else "ending",
                text=text,
            )
            for role in ("a", "b")
        )
    engine, sonar, lamp = _power(state)
    b_power = Observation(
        audience="b",
        topic="power",
        text=f"本人能源配置：engine={engine}、sonar={sonar}、lamp={lamp}，使用{power_used(engine, sonar, lamp)}/{POWER_BUDGET}。"
        if "b_power_board" in state.discovered_clues
        else "请先检查本人功率板，再确认能源设备与预算。",
    )
    if state.scene_id == "survey":
        scanned = state.fact("track_scanned")
        can_scan = (
            state.device("echo_gate", "position") == "east" and sonar and not engine
        )
        return (
            Observation(
                audience="a",
                topic="echo_gate",
                text=f"本人回声闸位置：{state.device('echo_gate', 'position')}。",
            ),
            Observation(
                audience="a",
                topic="rail_location",
                text="列车声呐已公开定位bridge_2，可以安装对应导轨。"
                if scanned
                else "缺轨段尚未由列车声呐定位，不能猜装。",
            ),
            b_power,
            Observation(
                audience="b",
                topic="echo_path",
                text="回声通道畅通，声呐具备勘测条件。"
                if can_scan
                else "声呐不可扫描；需要搭档打开回声通道、声呐供电并关闭引擎。",
            ),
            Observation(
                audience="b",
                topic="scan_result",
                text="扫描已定位bridge_2，工程结果已公开给站台端。"
                if scanned
                else "尚无实际扫描结果。",
            ),
        )
    ready = (
        state.fact("signal_confirmed")
        and state.device("platform", "track") == "track_2"
        and engine
        and lamp
        and not sonar
    )
    return (
        Observation(
            audience="a",
            topic="platform",
            text=f"本人接车轨道：{state.device('platform', 'track')}；回声闸已随导轨安装锁定。",
        ),
        Observation(
            audience="a",
            topic="confirmed_signal",
            text="列车端已确认蓝色双闪，请按本人的站台标识选择轨道。"
            if state.fact("signal_confirmed")
            else "等待列车端确认灯号，尚不能设置接车轨道。",
        ),
        b_power,
        Observation(
            audience="b",
            topic="signal_panel",
            text="本人列车面板显示蓝色双闪；确认后该信号才对双方公开。"
            if lamp
            else "信号灯未供电，请先开启再确认灯号。",
        ),
        Observation(
            audience="b",
            topic="dispatch_ready",
            text="导轨就绪、站台已对位、能源正确，可以接车。"
            if ready
            else "导轨已安装；接车仍需确认灯号、等待站台对位并核对本人能源配置。",
        ),
    )


def validate_invariants(state: GameState, script: ScriptVersion) -> None:
    engine, sonar, lamp = _power(state)
    scanned = state.fact("track_scanned")
    installed = state.fact("rail_installed")
    confirmed = state.fact("signal_confirmed")
    dispatched = state.fact("train_dispatched")
    gate = state.device("echo_gate", "position")
    track = state.device("platform", "track")
    a_read = "a_station_log" in state.discovered_clues
    b_read = "b_power_board" in state.discovered_clues
    if (
        any(
            type(value) is not bool
            for value in (
                engine,
                sonar,
                lamp,
                scanned,
                installed,
                confirmed,
                dispatched,
            )
        )
        or power_used(engine, sonar, lamp) > POWER_BUDGET
        or gate not in {"west", "east", "closed"}
        or track not in {"unset", "track_1", "track_2", "track_3"}
        or installed is not (state.scene_id in {"boarding", "decision", "completed"})
        or dispatched is not (state.scene_id in {"decision", "completed"})
        or state.fact("scanned_segment") != ("bridge_2" if scanned else "unknown")
        or state.fact("confirmed_signal")
        != ("blue_double_flash" if confirmed else "unknown")
        or (scanned and not (a_read and b_read))
        or (installed and not scanned)
        or (confirmed and not installed)
        or (track != "unset" and not confirmed)
        or (gate != "closed" and not a_read)
        or ((engine or sonar or lamp) and not b_read)
        or (state.votes and state.scene_id not in {"decision", "completed"})
        or (
            dispatched
            and not (confirmed and track == "track_2" and engine and lamp and not sonar)
        )
    ):
        raise DomainError("INVALID_STATE")
