import { apiBaseUrl } from './http'
import { object, parseGame, type GameSnapshot } from '../types/game'
import { identifier } from '../types/resources'

export function connectSaveSocket(
  id: string,
  current: () => boolean,
  onSnapshot: (snapshot: GameSnapshot) => void,
  onClose: (code: number) => void,
) {
  const url = new URL(`${apiBaseUrl()}/api/ws/saves/${identifier(id)}`, window.location.href)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  const socket = new WebSocket(url)
  socket.onmessage = ({ data }) => {
    if (!current() || typeof data !== 'string') return
    try {
      const message = object(JSON.parse(data))
      if (Object.keys(message).length !== 2) return
      if (message.type === 'snapshot') onSnapshot(parseGame(message.save))
      if (
        message.type === 'ping' &&
        typeof message.id === 'number' &&
        Number.isSafeInteger(message.id) &&
        message.id > 0 &&
        socket.readyState === WebSocket.OPEN
      )
        socket.send(JSON.stringify({ type: 'pong', id: message.id }))
    } catch {
      // Malformed messages and a socket closing during a pong cannot update game state.
    }
  }
  socket.onclose = ({ code }) => {
    if (current()) onClose(code)
  }
  return () => {
    socket.onmessage = null
    socket.onclose = null
    socket.close()
  }
}
