import { parseGame } from '../src/types/game'
import { game } from './game-fixture'
export function performanceSnapshot(
  story = 'lighthouse',
  role = 'a',
  version = 10,
  enabled = false,
) {
  return parseGame({
    ...game(),
    script_id: story,
    scene_id: story === 'lighthouse' ? 'repair' : 'survey',
    role,
    version,
    presentation: {
      background: null,
      cues: [],
      visual_state: [
        { id: story === 'lighthouse' ? 'clock_powered' : 'echo_available', value: enabled },
      ],
    },
  })
}
