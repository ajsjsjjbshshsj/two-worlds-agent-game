import { createHttpClient } from './http'
import { identifier, invalidResponse, list } from '../types/resources'
import { object, parseGame } from '../types/game'
import { isRequestId } from './pending'
export interface Command {
  request_id: string
  expected_version: number
  kind: string
  args: Record<string, unknown>
}
const http = createHttpClient()
export const gameApi = {
  async read(id: string, signal?: AbortSignal) {
    return parseGame(
      await http.request(`/api/saves/${identifier(id)}`, { privateSession: true, signal }),
    )
  },
  async receipt(id: string, command: Command, signal: AbortSignal): Promise<number | null> {
    if (!isRequestId(command.request_id)) return invalidResponse()
    const r = object(
      await http.request(`/api/saves/${identifier(id)}/receipts/${command.request_id}`, {
        privateSession: true,
        expectedStatus: 200,
        signal,
      }),
    )
    if (r.accepted === false && Object.keys(r).length === 1) return null
    if (
      r.accepted !== true ||
      !Object.hasOwn(r, 'request_id') ||
      r.request_id !== command.request_id ||
      r.accepted_version !== command.expected_version + 1 ||
      typeof r.accepted_version !== 'number' ||
      !Number.isSafeInteger(r.accepted_version) ||
      Object.keys(r).length !== 3
    )
      return invalidResponse()
    return r.accepted_version
  },
  async submit(id: string, command: Command) {
    const r = object(
        await http.request(`/api/saves/${identifier(id)}/commands`, {
          method: 'POST',
          privateSession: true,
          body: command,
        }),
      ),
      receipt = object(r.receipt),
      save = parseGame(r.save)
    if (
      receipt.request_id !== command.request_id ||
      receipt.status !== 'accepted' ||
      typeof receipt.duplicate !== 'boolean' ||
      typeof receipt.accepted_version !== 'number' ||
      !Number.isSafeInteger(receipt.accepted_version) ||
      receipt.accepted_version !== command.expected_version + 1 ||
      receipt.accepted_version > save.version
    )
      return invalidResponse()
    const events = list(r.audio_events ?? [], (x) => {
      const e = object(x)
      const cueId = identifier(e.cue_id),
        assetId = identifier(e.asset_id)
      if (
        e.accepted_version !== receipt.accepted_version ||
        receipt.duplicate ||
        !save.presentation.operation_sfx?.includes(assetId) ||
        !save.presentation.cues.some(
          (c) => c.id === cueId && c.assets.some((a) => a.asset_id === assetId && a.kind === 'sfx'),
        )
      )
        return invalidResponse()
      return { accepted_version: e.accepted_version as number, cue_id: cueId, asset_id: assetId }
    })
    if (new Set(events.map((e) => `${e.cue_id}:${e.asset_id}`)).size !== events.length)
      return invalidResponse()
    return events.length ? { ...save, audio_events: events } : save
  },
}
