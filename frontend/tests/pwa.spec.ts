import { describe, expect, it } from 'vitest'
import { classifyRequest } from '../src/pwa/worker'

const origin = 'https://twoworlds.example'
const scope = origin + '/app/'
const urls = new Set([origin + '/app/assets/app-HASH.js', origin + '/app/offline.html'])
const classify = (path: string, init?: RequestInit) =>
  classifyRequest(new Request(new URL(path, origin), init), scope, urls)

describe('explicit public cache policy', () => {
  it('allows only exact built static URLs without credentials', () => {
    expect(classify('/app/assets/app-HASH.js', { credentials: 'omit' })).toBe('static')
    expect(classify('/app/assets/app-HASH.js', { credentials: 'include' })).toBe('network')
  })
  it.each([
    '/api/me',
    '/api/saves/x',
    '/app/api/me',
    '/app/apiary',
    '/app/%61pi/me',
    '/app/assets/app-HASH.js?token=x',
    '/app/assets/%61pp-HASH.js',
    '/app/private.html',
    'https://other.example/app/assets/app-HASH.js',
  ])('never caches %s', (path) => expect(classify(path, { credentials: 'omit' })).toBe('network'))
  it.each(['POST', 'DELETE'])('never caches %s', (method) => {
    expect(classify('/app/assets/app-HASH.js', { method })).toBe('network')
  })
})
