import { isRecord } from '../services/http'
import { date, identifier, invalidResponse, list, parseEntry, type SaveEntry } from './resources'
export type Scalar = string | number | boolean
export interface Parameter {
  id: string
  value_type: 'boolean' | 'integer' | 'string'
  choices: Scalar[]
  max_length: number | null
}
export interface Action {
  id: string
  kind: string
  parameters: Parameter[]
}
export interface ImageRef {
  asset_id: string
  kind: 'image' | 'ambience' | 'sfx' | 'narration'
  alt_text: string
  transcript: string | null
}
export interface OperationAudioEvent {
  accepted_version: number
  cue_id: string
  asset_id: string
}
export interface GameSnapshot extends SaveEntry {
  // Ephemeral, validated command-response metadata; GET parsing never restores it.
  audio_events?: OperationAudioEvent[]
  // Set by the store after accepting a socket snapshot, never read from the wire.
  from_realtime?: true
  public: {
    clues: { id: string; text: string }[]
    ending: string | null
    events: { version: number; ordinal: number; kind: string; text: string }[]
    recap: {
      milestones: {
        version: number
        ordinal: number
        kind: string
        subject_id: string
        text: string
      }[]
      ending_id: string | null
      summary: string | null
    }
  }
  personal: {
    clues: { id: string; text: string }[]
    dialogue: never[]
    devices: Record<string, Record<string, Scalar>>
    observations: { topic: string; text: string }[]
  }
  available_actions: Action[]
  presentation: {
    operation_sfx?: string[]
    background: ImageRef | null
    cues: { id: string; alt_text: string; assets: ImageRef[] }[]
    visual_state?: { id: string; value: Scalar }[]
  }
}
export function object(v: unknown) {
  return isRecord(v) ? v : invalidResponse()
}
export function text(v: unknown): string {
  return typeof v === 'string' && v.trim() && v.length <= 2000 ? v : invalidResponse()
}
function integer(v: unknown, min = 0): number {
  return typeof v === 'number' && Number.isSafeInteger(v) && v >= min ? v : invalidResponse()
}
export function scalar(v: unknown): Scalar {
  return typeof v === 'string' ||
    typeof v === 'boolean' ||
    (typeof v === 'number' && Number.isSafeInteger(v))
    ? v
    : invalidResponse()
}
const nullableId = (v: unknown) => (v === null ? null : identifier(v))
const nullableText = (v: unknown) => (v === null ? null : text(v))
const clues = (v: unknown) =>
  list(v, (x) => {
    const r = object(x)
    return { id: identifier(r.id), text: text(r.text) }
  })
function media(v: unknown): ImageRef {
  const r = object(v)
  if (!['image', 'ambience', 'sfx', 'narration'].includes(String(r.kind))) return invalidResponse()
  return {
    asset_id: identifier(r.asset_id),
    kind: r.kind as ImageRef['kind'],
    alt_text: text(r.alt_text),
    transcript: nullableText(r.transcript),
  }
}
export function validParameter(p: Parameter, v: unknown): v is Scalar {
  return (
    (p.value_type === 'boolean'
      ? typeof v === 'boolean'
      : p.value_type === 'integer'
        ? typeof v === 'number' && Number.isSafeInteger(v)
        : typeof v === 'string' && (!p.max_length || Array.from(v).length <= p.max_length)) &&
    (!p.choices.length || p.choices.includes(v as Scalar))
  )
}
export function parseGame(v: unknown): GameSnapshot {
  const r = object(v),
    entry = parseEntry(r),
    pub = object(r.public),
    personal = object(r.personal),
    recap = object(pub.recap),
    presentation = object(r.presentation)
  const devices: Record<string, Record<string, Scalar>> = Object.create(null)
  for (const [id, fields] of Object.entries(object(personal.devices))) {
    devices[identifier(id)] = Object.create(null)
    for (const [key, value] of Object.entries(object(fields)))
      devices[id]![identifier(key)] = scalar(value)
  }
  // The server can project the owner's demo turns. Game does not render them yet.
  list(personal.dialogue, (value) => {
    const turn = object(value)
    if (turn.mode !== 'demo' && turn.mode !== 'provider' && turn.mode !== 'fallback')
      return invalidResponse()
    text(turn.question)
    text(turn.answer)
    date(turn.created_at)
  })
  const actions = list(r.available_actions, (x) => {
    const a = object(x)
    return {
      id: identifier(a.id),
      kind: identifier(a.kind),
      parameters: list(a.parameters, (x) => {
        const p = object(x)
        if (!['boolean', 'integer', 'string'].includes(String(p.value_type)))
          return invalidResponse()
        const parameter: Parameter = {
          id: identifier(p.id),
          value_type: p.value_type as Parameter['value_type'],
          choices: list(p.choices, scalar),
          max_length: p.max_length === null ? null : integer(p.max_length, 1),
        }
        if (parameter.choices.some((c) => !validParameter(parameter, c))) return invalidResponse()
        return parameter
      }),
    }
  })
  if (
    new Set(actions.map((a) => a.id)).size !== actions.length ||
    actions.some((a) => new Set(a.parameters.map((p) => p.id)).size !== a.parameters.length)
  )
    return invalidResponse()
  const operationSfx = list(presentation.operation_sfx ?? [], identifier)
  const authorizedSfx = new Set(
    list(presentation.cues, (x) => object(x)).flatMap((c) =>
      list(c.assets, media)
        .filter((a) => a.kind === 'sfx')
        .map((a) => a.asset_id),
    ),
  )
  if (
    new Set(operationSfx).size !== operationSfx.length ||
    operationSfx.some((id) => !authorizedSfx.has(id))
  )
    return invalidResponse()
  return {
    ...entry,
    public: {
      clues: clues(pub.clues),
      ending: nullableId(pub.ending),
      events: list(pub.events, (x) => {
        const e = object(x)
        return {
          version: integer(e.version, 1),
          ordinal: integer(e.ordinal, 1),
          kind: [
            'clue_shared',
            'scene_changed',
            'fact_changed',
            'vote_changed',
            'observation',
            'game_completed',
          ].includes(String(e.kind))
            ? identifier(e.kind)
            : invalidResponse(),
          text: text(e.text),
        }
      }),
      recap: {
        milestones: list(recap.milestones ?? [], (x) => {
          const m = object(x)
          return {
            version: integer(m.version, 1),
            ordinal: integer(m.ordinal, 1),
            kind: [
              'clue_shared',
              'scene_entered',
              'signal_locked',
              'clock_repaired',
              'route_confirmed',
              'track_scanned',
              'rail_installed',
              'signal_confirmed',
              'train_dispatched',
              'game_completed',
            ].includes(String(m.kind))
              ? identifier(m.kind)
              : invalidResponse(),
            subject_id: identifier(m.subject_id),
            text: text(m.text),
          }
        }),
        ending_id: nullableId(recap.ending_id ?? null),
        summary: nullableText(recap.summary ?? null),
      },
    },
    personal: {
      clues: clues(personal.clues),
      dialogue: [],
      devices,
      observations: list(personal.observations, (x) => {
        const o = object(x)
        return { topic: identifier(o.topic), text: text(o.text) }
      }),
    },
    available_actions: actions,
    presentation: {
      operation_sfx: operationSfx,
      visual_state: list(presentation.visual_state ?? [], (x) => {
        const effect = object(x)
        return { id: identifier(effect.id), value: scalar(effect.value) }
      }),
      background: presentation.background === null ? null : media(presentation.background),
      cues: list(presentation.cues, (x) => {
        const c = object(x)
        return { id: identifier(c.id), alt_text: text(c.alt_text), assets: list(c.assets, media) }
      }),
    },
  }
}
