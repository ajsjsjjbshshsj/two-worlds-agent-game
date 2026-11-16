import { createHttpClient } from './http'
import { identifier, list, parseInvitation, parseJoined, parsePair } from '../types/resources'
const http = createHttpClient()
export const pairApi = {
  async list(token: string) {
    return list(await http.request('/api/pairs', { token }), parsePair)
  },
  async create(token: string) {
    return parseInvitation(await http.request('/api/pairs', { method: 'POST', token }))
  },
  async refresh(token: string, id: string) {
    return parseInvitation(
      await http.request(`/api/pairs/${identifier(id)}/invite`, { method: 'POST', token }),
    )
  },
  async join(token: string, invite_token: string) {
    return parseJoined(
      await http.request('/api/pairs/join', { method: 'POST', token, body: { invite_token } }),
    )
  },
}
