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
