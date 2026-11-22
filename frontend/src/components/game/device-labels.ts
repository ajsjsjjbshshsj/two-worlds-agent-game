const names: Record<string, string> = {
  emitter: '发射器',
  receiver: '观测接收器',
  filter: '滤镜',
  power_router: '供电路由器',
  clock_box: '时钟箱',
  echo_gate: '回声闸',
  power_panel: '能源面板',
  engine: '列车引擎',
  sonar: '声呐',
  lamp: '信号灯',
  platform: '接车轨道',
}

// Display names only; unknown identifiers remain readable without guessing state.
export const deviceLabel = (id: string) => (names[id] ? `${names[id]} · ${id}` : id)
