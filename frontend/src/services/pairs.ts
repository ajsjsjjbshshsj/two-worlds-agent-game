import { createHttpClient } from './http'
import { identifier, list, parseInvitation, parseJoined, parsePair } from '../types/resources'
const http = createHttpClient()
export const pairApi = {
  async list() {
    return list(await http.request('/api/pairs'), parsePair)
  },
  async create() {
    return parseInvitation(await http.request('/api/pairs', { method: 'POST' }))
  },
  async refresh(id: string) {
    return parseInvitation(
      await http.request(`/api/pairs/${identifier(id)}/invite`, { method: 'POST' }),
    )
  },
  async join(invite_token: string) {
    return parseJoined(
      await http.request('/api/pairs/join', { method: 'POST', body: { invite_token } }),
    )
  },
}
