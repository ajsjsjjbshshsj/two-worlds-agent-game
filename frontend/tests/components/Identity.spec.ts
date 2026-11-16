import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Identity from '../../src/views/Identity.vue'
import { created, fail, json, recovered } from '../fixtures'

const wrappers: ReturnType<typeof mount>[] = []
function page() {
  const wrapper = mount(Identity, { global: { plugins: [createPinia()] } })
  wrappers.push(wrapper)
  return wrapper
}
beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
})
afterEach(() => {
  wrappers.forEach((w) => w.unmount())
  wrappers.length = 0
  vi.unstubAllGlobals()
})

it('validates blank and overlong names before sending requests', async () => {
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  const wrapper = page()
  await flushPromises()
  await wrapper.get('[data-test=create-form]').trigger('submit')
  expect(wrapper.text()).toContain('1–40')
  await wrapper.get('#display-name').setValue('字'.repeat(41))
  await wrapper.get('[data-test=create-form]').trigger('submit')
  expect(fetch).not.toHaveBeenCalled()
})
it.each(['', 'x'.repeat(129)])(
  'validates recovery input and offers a reveal toggle (%i)',
  async (input) => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const wrapper = page()
    await flushPromises()
    await wrapper.get('[data-test=restore-tab]').trigger('click')
    await wrapper.get('#recovery-key').setValue(input)
    await wrapper.get('[data-test=recover-form]').trigger('submit')
    expect(wrapper.text()).toContain('1–128')
    await wrapper.get('[data-test=toggle-key]').trigger('click')
    expect(wrapper.get('#recovery-key').attributes('type')).toBe('text')
    expect(fetch).not.toHaveBeenCalled()
  },
)
it('shows one-time key, copies it, clears it on confirmation and never renders token', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(created)))
  const writeText = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  const wrapper = page()
  await flushPromises()
  await wrapper.get('#display-name').setValue('旅人')
  await wrapper.get('[data-test=create-form]').trigger('submit')
  await flushPromises()
  expect((wrapper.get('[data-test=one-time-key]').element as HTMLTextAreaElement).value).toBe(
    created.recovery_key,
  )
  expect(wrapper.text()).toContain('只展示一次')
  await wrapper.get('[data-test=copy-key]').trigger('click')
  await flushPromises()
  expect(writeText).toHaveBeenCalledWith(created.recovery_key)
  expect(wrapper.text()).toContain('已复制')
  expect(wrapper.html()).not.toContain(created.session.token)
  await wrapper.get('[data-test=confirm-key]').trigger('click')
  expect(wrapper.find('[data-test=one-time-key]').exists()).toBe(false)
  expect(wrapper.text()).toContain('身份已验证')
  expect(JSON.stringify(sessionStorage)).not.toContain(created.recovery_key)
})
it('offers manual copy when clipboard permission is unavailable', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(created)))
  vi.stubGlobal('navigator', {
    clipboard: { writeText: vi.fn().mockRejectedValue(new Error('blocked')) },
  })
  const wrapper = page()
  await flushPromises()
  await wrapper.get('#display-name').setValue('旅人')
  await wrapper.get('[data-test=create-form]').trigger('submit')
  await flushPromises()
  await wrapper.get('[data-test=copy-key]').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('手动复制')
  expect(wrapper.get('[data-test=one-time-key]').attributes('readonly')).toBeDefined()
})
it('prevents duplicate create while loading and shows unknown-result warning', async () => {
  let reject!: (reason: Error) => void
  const fetch = vi.fn().mockImplementation(
    () =>
      new Promise((_resolve, fail) => {
        reject = fail
      }),
  )
  vi.stubGlobal('fetch', fetch)
  const wrapper = page()
  await flushPromises()
  await wrapper.get('#display-name').setValue('旅人')
  await wrapper.get('[data-test=create-form]').trigger('submit')
  expect(wrapper.get('[data-test=create-button]').attributes('disabled')).toBeDefined()
  await wrapper.get('[data-test=create-form]').trigger('submit')
  expect(fetch).toHaveBeenCalledTimes(1)
  reject(new Error('offline'))
  await flushPromises()
  expect(wrapper.text()).toContain('可能已创建')
})
it('restores identity and removes entered recovery key', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(recovered)))
  const wrapper = page()
  await flushPromises()
  await wrapper.get('[data-test=restore-tab]').trigger('click')
  await wrapper.get('#recovery-key').setValue('PRIVATE_RECOVERY')
  await wrapper.get('[data-test=recover-form]').trigger('submit')
  await flushPromises()
  expect(wrapper.text()).toContain('身份已验证')
  expect(wrapper.html()).not.toContain('PRIVATE_RECOVERY')
})
it.each([401, 422, 429, 503])('displays safe feedback for recovery failure %i', async (status) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fail(status)))
  const wrapper = page()
  await flushPromises()
  await wrapper.get('[data-test=restore-tab]').trigger('click')
  await wrapper.get('#recovery-key').setValue('PRIVATE_RECOVERY')
  await wrapper.get('[data-test=recover-form]').trigger('submit')
  await flushPromises()
  expect(wrapper.find('[role=alert]').exists()).toBe(true)
  expect((wrapper.get('#recovery-key').element as HTMLInputElement).value).toBe('')
  expect(wrapper.html()).not.toContain('PRIVATE_RECOVERY')
})
it('accepts forty Unicode code points consistently with the backend name limit', async () => {
  const fetch = vi.fn().mockResolvedValue(json(created))
  vi.stubGlobal('fetch', fetch)
  const wrapper = page()
  await flushPromises()
  const name = '🌌'.repeat(40)
  await wrapper.get('#display-name').setValue(name)
  await wrapper.get('[data-test=create-form]').trigger('submit')
  await flushPromises()
  expect(JSON.parse(fetch.mock.calls[0]![1].body).display_name).toBe(name)
  expect(wrapper.find('[data-test=one-time-key]').exists()).toBe(true)
})
it('refresh verifies the token without redisplaying the one-time recovery key', async () => {
  sessionStorage.setItem('twoworlds.session.token', created.session.token)
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(
        json({ account: created.account, session: { expires_at: created.session.expires_at } }),
      ),
  )
  const wrapper = page()
  await flushPromises()
  expect(wrapper.text()).toContain('身份已验证')
  expect(wrapper.find('[data-test=one-time-key]').exists()).toBe(false)
  expect(wrapper.html()).not.toContain(created.recovery_key)
})

const pendingKey = 'twoworlds.recovery.pending'
function beforeUnload() {
  const event = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(event)
  return event.defaultPrevented
}
async function createdPage() {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(created)))
  const wrapper = page()
  await flushPromises()
  await wrapper.get('#display-name').setValue('旅人')
  await wrapper.get('[data-test=create-form]').trigger('submit')
  await flushPromises()
  return wrapper
}
it('marks pending without storing the secret and protects leaving until confirmation', async () => {
  expect(beforeUnload()).toBe(false)
  const wrapper = await createdPage()
  expect(sessionStorage.getItem(pendingKey)).toBe('1')
  expect(JSON.stringify(sessionStorage)).not.toContain(created.recovery_key)
  expect(localStorage.length).toBe(0)
  expect(beforeUnload()).toBe(true)
  await wrapper.get('[data-test=confirm-key]').trigger('click')
  expect(sessionStorage.getItem(pendingKey)).toBeNull()
  expect(wrapper.find('[data-test=one-time-key]').exists()).toBe(false)
  expect(beforeUnload()).toBe(false)
})
it('refresh detects unconfirmed recovery and never redisplays or regenerates the lost secret', async () => {
  const original = await createdPage()
  original.unmount()
  const fetch = vi
    .fn()
    .mockResolvedValue(
      json({ account: created.account, session: { expires_at: created.session.expires_at } }),
    )
  vi.stubGlobal('fetch', fetch)
  const refreshed = page()
  await flushPromises()
  expect(refreshed.get('[data-test=pending-recovery-warning]').text()).toContain('尚未确认保存')
  expect(refreshed.text()).toContain('无法在其他设备恢复')
  expect(refreshed.find('[data-test=one-time-key]').exists()).toBe(false)
  expect(refreshed.html()).not.toContain(created.recovery_key)
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch.mock.calls[0]![0]).toBe('/api/me')
  expect(beforeUnload()).toBe(false)
})
it('removes the exact unload listener on unmount while retaining the pending marker', async () => {
  const added = vi.spyOn(window, 'addEventListener')
  const removed = vi.spyOn(window, 'removeEventListener')
  const wrapper = await createdPage()
  const callback = added.mock.calls.find(([event]) => event === 'beforeunload')?.[1]
  expect(callback).toBeTypeOf('function')
  wrapper.unmount()
  expect(removed).toHaveBeenCalledWith('beforeunload', callback)
  expect(beforeUnload()).toBe(false)
  expect(sessionStorage.getItem(pendingKey)).toBe('1')
})
it('keeps an in-memory safety state and unload warning when sessionStorage is blocked', async () => {
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  const wrapper = await createdPage()
  expect(wrapper.text()).toContain('无法保存会话')
  expect((wrapper.get('[data-test=one-time-key]').element as HTMLTextAreaElement).value).toBe(
    created.recovery_key,
  )
  expect(beforeUnload()).toBe(true)
  expect(sessionStorage.length).toBe(0)
  await wrapper.get('[data-test=confirm-key]').trigger('click')
  expect(beforeUnload()).toBe(false)
})
it('retains the unconfirmed warning even when the refreshed session is invalid', async () => {
  sessionStorage.setItem(pendingKey, '1')
  sessionStorage.setItem('twoworlds.session.token', created.session.token)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fail(401)))
  const wrapper = page()
  await flushPromises()
  expect(wrapper.get('[data-test=pending-recovery-warning]').text()).toContain('尚未确认保存')
  expect(wrapper.find('[data-test=one-time-key]').exists()).toBe(false)
  expect(sessionStorage.getItem('twoworlds.session.token')).toBeNull()
  expect(sessionStorage.getItem(pendingKey)).toBe('1')
})
