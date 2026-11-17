export type AudioChannel = 'ambient' | 'sfx' | 'voice'
export interface AudioCue {
  key: string
  cue_id: string
  asset_id: string
  channel: AudioChannel
  text: string
  // The current content protocol has no speaker or timed caption segments.
  speaker: string | null
  start_time: number
  duration: number | null
  language: 'zh-CN'
  subtitle_type: 'environment' | 'effect' | 'narration'
}
export interface AudioPreferences {
  volumes: Record<AudioChannel, number>
  muted: boolean
}
export interface AudioState {
  enabled: boolean
  paused: boolean
  status: 'off' | 'ready' | 'playing' | 'paused' | 'blocked' | 'error'
  message: string
  voiceKey: string | null
  time: number
}
