import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { createHttpClient } from '../src/services/http'
import { createSaveRecovery } from '../src/services/save-recovery'
import NetworkGate from '../src/components/NetworkGate.vue'
import { deferred } from './fixtures'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it.each(['POST', 'DELETE'] as const)('offline %s never reaches fetch', async (method) => {
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  await expect(createHttpClient().request('/api/pairs', { method })).rejects.toMatchObject({
    code: 'OFFLINE',
  })
  expect(fetch).not.toHaveBeenCalled()
})

it('network UI disables native business controls without deleting page content', async () => {
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
  const w = mount(NetworkGate, {
    slots: { default: '<button>Action</button><p>Existing in-memory text</p>' },
    global: { plugins: [createPinia()] },
  })
  expect(w.get('fieldset').attributes('disabled')).toBeDefined()
  expect(w.get('[role=status]').text()).toContain('离线')
  expect(w.text()).toContain('Existing in-memory text')
  w.unmount()
})

it('game local audio and reading controls remain usable offline', () => {
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
  const w = mount(NetworkGate, {
    props: { localControls: true },
    slots: { default: '<button>Mute local audio</button>' },
  })
  expect(w.get('fieldset').attributes('disabled')).toBeUndefined()
  expect(w.get('[role=status]').text()).toContain('离线')
  w.unmount()
})

it('actual offline/online cycle verifies the account before reading or connecting', async () => {
  const clock = vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
  const verification = deferred<boolean>()
  const read = vi.fn().mockResolvedValue(true)
  const verify = vi.fn(() => verification.promise)
  const status = vi.fn()
  const recovery = createSaveRecovery('save_one', {
    current: () => true,
    hasSnapshot: () => false,
    read,
    verify,
    status,
    accept: () => false,
    denied: vi.fn(),
  })
  await recovery.open()
  clock.mockReturnValue(false)
  window.dispatchEvent(new Event('offline'))
  read.mockClear()
  clock.mockReturnValue(true)
  window.dispatchEvent(new Event('online'))
  expect(verify).toHaveBeenCalledOnce()
  expect(read).not.toHaveBeenCalled()
  verification.resolve(true)
  await flushPromises()
  expect(read).toHaveBeenCalledOnce()
  recovery.stop()
})
