import { snapshot } from './resource-fixtures'
export const game = () => ({
  ...snapshot,
  personal: {
    clues: [{ id: 'own', text: 'TEST-ONLY 私人线索' }],
    dialogue: [],
    devices: { emitter: { angle: 0, pattern: 'steady' } },
    observations: [{ topic: 'own', text: 'TEST-ONLY 本人观察' }],
  },
  public: {
    clues: [],
    ending: null,
    events: [],
    recap: { milestones: [], ending_id: null, summary: null },
  },
  available_actions: [
    {
      id: 'adjust',
      kind: 'set_emitter',
      parameters: [
        { id: 'angle', value_type: 'integer', choices: [0, 90], max_length: null },
        { id: 'pattern', value_type: 'string', choices: ['steady', 'pulse'], max_length: 12 },
      ],
    },
  ],
})
