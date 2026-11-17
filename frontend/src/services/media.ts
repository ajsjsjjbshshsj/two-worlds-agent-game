import { ApiError, createHttpClient } from './http'
import { identifier } from '../types/resources'
async function protectedMedia(
  token: string,
  saveId: string,
  assetId: string,
  signal: AbortSignal,
  types: readonly string[],
) {
  createHttpClient() // Reuse the configured origin validation; binary parsing stays here.
  const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
  const r = await fetch(`${base}/api/saves/${identifier(saveId)}/media/${identifier(assetId)}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
    credentials: 'omit',
    redirect: 'error',
    signal,
  })
  if (!r.ok) throw new ApiError(r.status, 'MEDIA_UNAVAILABLE', false)
  if (!types.includes(r.headers.get('Content-Type')?.split(';')[0] ?? ''))
    throw new ApiError(200, 'INVALID_RESPONSE', false)
  const reader = r.body?.getReader()
  if (!reader) throw new ApiError(200, 'INVALID_RESPONSE', false)
  const chunks: ArrayBuffer[] = []
  let size = 0
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      size += value.byteLength
      if (signal.aborted || size > 32 * 1024 * 1024)
        throw new ApiError(0, 'MEDIA_UNAVAILABLE', false)
      chunks.push(new Uint8Array(value).buffer)
    }
  } finally {
    await reader.cancel()
  }
  if (signal.aborted) throw new ApiError(0, 'MEDIA_UNAVAILABLE', false)
  const blob = new Blob(chunks, { type: r.headers.get('Content-Type')! })
  const url = URL.createObjectURL(blob)
  return { url, dispose: () => URL.revokeObjectURL(url) }
}

export const protectedImage = (
  token: string,
  saveId: string,
  assetId: string,
  signal: AbortSignal,
) => protectedMedia(token, saveId, assetId, signal, ['image/png', 'image/jpeg', 'image/webp'])
export const protectedAudio = (
  token: string,
  saveId: string,
  assetId: string,
  signal: AbortSignal,
) =>
  protectedMedia(token, saveId, assetId, signal, [
    'audio/mpeg',
    'audio/ogg',
    'audio/wav',
    'audio/mp4',
  ])
