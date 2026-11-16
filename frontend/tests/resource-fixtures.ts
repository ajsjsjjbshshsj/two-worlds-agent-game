// Explicit HTTP response fixtures, never production catalog content.
export const pairA = { id: 'pair_one', role: 'a' as const, member_count: 1 as const }
export const pairB = { id: 'pair_one', role: 'b' as const, member_count: 2 as const }
export const invitation = {
  id: pairA.id,
  role: 'a',
  invite_token: 'tw_invite_TEST_ONLY',
  invite_expires_at: '2027-01-01T00:00:00Z',
}
export const script = {
  id: 'story_test',
  content_version: '2.0.0',
  title: '测试故事',
  summary: '仅供自动化测试',
  roles: [
    { id: 'a', name: '记录员', description: '观察站台' },
    { id: 'b', name: '驾驶员', description: '观察列车' },
  ],
  difficulty: 'medium',
  estimated_minutes: 15,
}
export const summary = {
  id: 'save_one',
  pair_id: pairA.id,
  script_id: script.id,
  script_version: '1.0.0',
  version: 7,
  scene_id: 'boarding',
  completed: false,
  role: 'a',
  created_at: '2026-11-16T00:00:00Z',
  updated_at: '2026-11-16T01:00:00Z',
}
export const snapshot = {
  ...summary,
  public: { clues: [], ending: null, events: [], recap: {} },
  personal: { clues: [], devices: {}, observations: [], dialogue: [] },
  available_actions: [],
  presentation: { background: null, cues: [] },
}
