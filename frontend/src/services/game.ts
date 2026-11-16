import { createHttpClient } from './http'
import { identifier, invalidResponse } from '../types/resources'
import { object, parseGame } from '../types/game'
export interface Command {
  request_id: string
  expected_version: number
  kind: string
  args: Record<string, unknown>
}
const http = createHttpClient()
export const gameApi = {
  async read(token: string, id: string) {
    return parseGame(await http.request(`/api/saves/${identifier(id)}`, { token }))
  },
  async submit(token: string, id: string, command: Command) {
    const r = object(
        await http.request(`/api/saves/${identifier(id)}/commands`, {
          method: 'POST',
          token,
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
    return save
  },
}
