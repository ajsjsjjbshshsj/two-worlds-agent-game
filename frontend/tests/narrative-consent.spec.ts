import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import NarrativeConsent from '../src/components/NarrativeConsent.vue'
import { deferred, fail, json } from './fixtures'

const disclosure = 'a'.repeat(64)
const available = {
  available: true,
  allowed: false,
  has_consent: false,
  destination: 'https://gateway.test',
  model: 'fixture-model',
  disclosure,
}

afterEach(() => vi.unstubAllGlobals())

it('discloses the external data and only saves after explicit consent or revocation', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(json(available))
    .mockResolvedValueOnce(json({ ...available, allowed: true, has_consent: true }))
    .mockResolvedValueOnce(json(available))
  vi.stubGlobal('fetch', fetch)
  const wrapper = mount(NarrativeConsent)
  expect(fetch).not.toHaveBeenCalled()
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('https://gateway.test')
  expect(wrapper.text()).toContain('你最近的 NPC 对话')
  expect(wrapper.text()).toContain('可随时撤回')
  expect(fetch.mock.calls[0]![1].method).toBe('GET')
  await wrapper.findAll('button')[1]!.trigger('click')
  await flushPromises()
  expect(JSON.parse(fetch.mock.calls[1]![1].body)).toEqual({ allow: true, disclosure })
  expect(fetch.mock.calls[1]![1]).toMatchObject({ method: 'POST', credentials: 'include' })
  expect(wrapper.text()).toContain('已同意使用外部 AI')
  await wrapper.findAll('button')[1]!.trigger('click')
  await flushPromises()
  expect(JSON.parse(fetch.mock.calls[2]![1].body)).toEqual({ allow: false, disclosure: null })
  expect(wrapper.text()).toContain('当前使用本地演示回复')
  wrapper.unmount()
})

it('permits revocation when the administrator has disabled the provider', async () => {
  const disabled = {
    ...available,
    available: false,
    has_consent: true,
    destination: null,
    model: null,
    disclosure: null,
  }
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(json(disabled))
    .mockResolvedValueOnce(json({ ...disabled, has_consent: false }))
  vi.stubGlobal('fetch', fetch)
  const wrapper = mount(NarrativeConsent)
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.text()).not.toContain('同意发送并使用外部 AI')
  expect(wrapper.text()).toContain('当前使用本地演示')
  await wrapper.findAll('button')[1]!.trigger('click')
  await flushPromises()
  expect(JSON.parse(fetch.mock.calls[1]![1].body)).toEqual({ allow: false, disclosure: null })
  expect(wrapper.text()).not.toContain('撤回外部 AI 授权')
  wrapper.unmount()
})

it('fails closed on an error and aborts the outstanding request when the account view is removed', async () => {
  const delayed = deferred<Response>()
  const fetch = vi.fn().mockResolvedValueOnce(fail(503)).mockReturnValueOnce(delayed.promise)
  vi.stubGlobal('fetch', fetch)
  const wrapper = mount(NarrativeConsent)
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.get('[role=alert]').text()).toContain('暂时无法确认')
  expect(wrapper.findAll('button')).toHaveLength(1)
  await wrapper.get('button').trigger('click')
  const signal = fetch.mock.calls[1]![1].signal as AbortSignal
  wrapper.unmount()
  expect(signal.aborted).toBe(true)
  delayed.resolve(json(available))
  await flushPromises()
})
