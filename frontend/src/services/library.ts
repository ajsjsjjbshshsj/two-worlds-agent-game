import { createHttpClient } from './http'
import {
  identifier,
  list,
  parseSaveSummary,
  parseScript,
  parseSnapshotEntry,
} from '../types/resources'
const http = createHttpClient()
export const libraryApi = {
  async catalog() {
    return list(await http.request('/api/scripts'), parseScript)
  },
  async saves(pair_id: string) {
    return list(await http.request('/api/saves', { query: { pair_id } }), parseSaveSummary)
  },
  async create(pair_id: string, script_id: string, script_version: string) {
    return parseSnapshotEntry(
      await http.request('/api/saves', {
        method: 'POST',
        body: { pair_id, script_id, script_version },
      }),
    )
  },
  async read(id: string) {
    return parseSnapshotEntry(await http.request(`/api/saves/${identifier(id)}`))
  },
}
