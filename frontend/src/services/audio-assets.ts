import type { GameSnapshot } from '../types/game'
import type { AudioCue, AudioChannel } from '../types/audio'
const channels = { ambience: 'ambient', sfx: 'sfx', narration: 'voice' } as const
// Both stories use their versioned, server-authorized scene declarations. No
// hidden script, device-to-sound table, prose matching, or external URL is read.
export function audioCues(snapshot: GameSnapshot): AudioCue[] {
  return snapshot.presentation.cues.flatMap((cue) =>
    cue.assets
      .filter((a) => a.kind !== 'image')
      .map((a) => {
        const channel: AudioChannel = channels[a.kind as keyof typeof channels]
        return {
          key: `${cue.id}:${a.asset_id}`,
          cue_id: cue.id,
          asset_id: a.asset_id,
          channel,
          text: a.transcript ?? a.alt_text,
          speaker: null,
          start_time: 0,
          duration: null,
          language: 'zh-CN',
          subtitle_type:
            channel === 'ambient' ? 'environment' : channel === 'sfx' ? 'effect' : 'narration',
        }
      }),
  )
}
