import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Identity from '../../src/views/Identity.vue'
import { created, fail, json, recovered, pendingMetadata, pendingA, pendingB } from '../fixtures'

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

const pendingKey = 'twoworlds.recovery.pending.v1.' + created.account.id
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
  expect(JSON.parse(localStorage.getItem(pendingKey)!)).toEqual({
    account_id: created.account.id,
    display_name: created.account.display_name,
    created_at: expect.any(String),
    pending: true,
  })
  expect(JSON.stringify(sessionStorage)).not.toContain(created.recovery_key)
  expect(localStorage.length).toBe(1)
  expect(JSON.stringify(localStorage)).not.toContain(created.recovery_key)
  expect(JSON.stringify(localStorage)).not.toContain(created.session.token)
  expect(beforeUnload()).toBe(true)
  await wrapper.get('[data-test=confirm-key]').trigger('click')
  expect(localStorage.getItem(pendingKey)).toBeNull()
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
  expect(JSON.parse(localStorage.getItem(pendingKey)!)).toEqual({
    account_id: created.account.id,
    display_name: created.account.display_name,
    created_at: expect.any(String),
    pending: true,
  })
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
  localStorage.setItem(pendingKey, JSON.stringify(pendingMetadata(created.account)))
  sessionStorage.setItem('twoworlds.session.token', created.session.token)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fail(401)))
  const wrapper = page()
  await flushPromises()
  expect(wrapper.get('[data-test=pending-recovery-warning]').text()).toContain('尚未确认保存')
  expect(wrapper.find('[data-test=one-time-key]').exists()).toBe(false)
  expect(sessionStorage.getItem('twoworlds.session.token')).toBeNull()
  expect(localStorage.getItem(pendingKey)).toBe(JSON.stringify(pendingMetadata(created.account)))
})
it('shows all reminders independently of the authenticated account and confirms only A', async () => {
  for (const item of [pendingA, pendingB])
    localStorage.setItem(
      'twoworlds.recovery.pending.v1.' + item.account.id,
      JSON.stringify(pendingMetadata(item.account)),
    )
  sessionStorage.setItem('twoworlds.session.token', pendingB.session.token)
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(
        json({ account: pendingB.account, session: { expires_at: pendingB.session.expires_at } }),
      ),
  )
  const wrapper = page()
  await flushPromises()
  expect(wrapper.findAll('[data-test=pending-reminder]')).toHaveLength(2)
  expect(wrapper.text()).toContain('旅人甲')
  expect(wrapper.text()).toContain('旅人乙')
  await wrapper.get('[data-account-id=account_a] [data-test=acknowledge-pending]').trigger('click')
  expect(wrapper.find('[data-account-id=account_a]').exists()).toBe(false)
  expect(wrapper.find('[data-account-id=account_b]').exists()).toBe(true)
  expect(localStorage.getItem('twoworlds.recovery.pending.v1.account_b')).toBe(
    JSON.stringify(pendingMetadata(pendingB.account)),
  )
})
it('recovering B leaves the reminder for A visible', async () => {
  localStorage.setItem(
    'twoworlds.recovery.pending.v1.account_a',
    JSON.stringify(pendingMetadata(pendingA.account)),
  )
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(pendingB)))
  const wrapper = page()
  await flushPromises()
  await wrapper.get('[data-test=restore-tab]').trigger('click')
  await wrapper.get('#recovery-key').setValue(pendingB.recovery_key)
  await wrapper.get('[data-test=recover-form]').trigger('submit')
  await flushPromises()
  expect(wrapper.text()).toContain('旅人乙')
  expect(wrapper.get('[data-account-id=account_a]').text()).toContain('旅人甲')
  expect(wrapper.find('[data-test=one-time-key]').exists()).toBe(false)
})
it('logout and reopening without a token retain A reminder and do not recreate the key', async () => {
  localStorage.setItem(pendingKey, JSON.stringify(pendingMetadata(created.account)))
  sessionStorage.setItem('twoworlds.session.token', created.session.token)
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(
        json({ account: created.account, session: { expires_at: created.session.expires_at } }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 })),
  )
  const wrapper = page()
  await flushPromises()
  const logout = wrapper.findAll('button').find((button) => button.text() === '登出此设备')!
  await logout.trigger('click')
  await flushPromises()
  expect(localStorage.getItem(pendingKey)).toBe(JSON.stringify(pendingMetadata(created.account)))
  wrapper.unmount()
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  const reopened = page()
  await flushPromises()
  expect(reopened.get('[data-test=pending-recovery-warning]').text()).toContain(
    created.account.display_name,
  )
  expect(reopened.find('[data-test=one-time-key]').exists()).toBe(false)
  expect(fetch).not.toHaveBeenCalled()
})
it('abandoning a reminder requires a second explicit confirmation and leaves B intact', async () => {
  for (const item of [pendingA, pendingB])
    localStorage.setItem(
      'twoworlds.recovery.pending.v1.' + item.account.id,
      JSON.stringify(pendingMetadata(item.account)),
    )
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  const wrapper = page()
  await flushPromises()
  await wrapper.get('[data-account-id=account_a] [data-test=abandon-pending]').trigger('click')
  expect(wrapper.get('[role=alertdialog]').text()).toContain('可能永久无法恢复')
  expect(localStorage.getItem('twoworlds.recovery.pending.v1.account_a')).not.toBeNull()
  await wrapper.get('[data-test=cancel-abandon]').trigger('click')
  expect(wrapper.find('[role=alertdialog]').exists()).toBe(false)
  await wrapper.get('[data-account-id=account_a] [data-test=abandon-pending]').trigger('click')
  await wrapper.get('[data-test=confirm-abandon]').trigger('click')
  expect(localStorage.getItem('twoworlds.recovery.pending.v1.account_a')).toBeNull()
  expect(localStorage.getItem('twoworlds.recovery.pending.v1.account_b')).not.toBeNull()
  expect(fetch).not.toHaveBeenCalled()
})
it('blocked localStorage preserves the visible key, memory reminder and leave guard', async () => {
  const storage = localStorage
  vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
    throw new Error('blocked')
  })
  const wrapper = await createdPage()
  expect(wrapper.text()).toContain('本页仍保留内存提醒')
  expect((wrapper.get('[data-test=one-time-key]').element as HTMLTextAreaElement).value).toBe(
    created.recovery_key,
  )
  expect(beforeUnload()).toBe(true)
  expect(storage.length).toBe(0)
  expect(sessionStorage.getItem('twoworlds.session.token')).toBe(created.session.token)
  await wrapper.get('[data-test=confirm-key]').trigger('click')
  expect(beforeUnload()).toBe(false)
})
it('legacy unassigned marker is warned about rather than guessed or cleared by recovery', async () => {
  sessionStorage.setItem('twoworlds.recovery.pending', '1')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(pendingB)))
  const wrapper = page()
  await flushPromises()
  expect(wrapper.text()).toContain('旧版未关联身份')
  await wrapper.get('[data-test=restore-tab]').trigger('click')
  await wrapper.get('#recovery-key').setValue(pendingB.recovery_key)
  await wrapper.get('[data-test=recover-form]').trigger('submit')
  await flushPromises()
  expect(wrapper.text()).toContain('旧版未关联身份')
  expect(wrapper.findAll('[data-test=pending-reminder]')).toHaveLength(0)
  expect(sessionStorage.getItem('twoworlds.recovery.pending')).toBe('1')
})
