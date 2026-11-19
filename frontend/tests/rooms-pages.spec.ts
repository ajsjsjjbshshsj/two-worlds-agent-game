import { createPinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
import { createAppRouter } from '../src/router'
import { usePairsStore } from '../src/stores/pairs'
import { fail, json, me, password } from './fixtures'
import { invitation, pairA, script, summary, snapshot } from './resource-fixtures'
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  window.history.replaceState({}, '', '/')
})
afterEach(() => {
  wrappers.forEach((w) => w.unmount())
  wrappers.length = 0
  vi.unstubAllGlobals()
})
function responses({
  catalog = [script],
  saves = [summary],
  member_count = 2,
  joinError = '',
}: { catalog?: unknown[]; saves?: unknown[]; member_count?: number; joinError?: string } = {}) {
  let loggedIn = true
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === '/api/me') return loggedIn ? json(me) : fail(401)
    if (url === '/api/sessions') {
      loggedIn = true
      return json(me)
    }
    if (url === '/api/pairs/join')
      return joinError
        ? json(
            { error: { code: joinError, message: 'PRIVATE_TEST', retryable: false } },
            joinError === 'PAIR_FULL' ? 409 : 404,
          )
        : json({ id: pairA.id, role: 'b' })
    if (url === '/api/pairs')
      return options?.method === 'POST' ? json(invitation) : json([{ ...pairA, member_count }])
    if (url.endsWith('/invite')) return json(invitation)
    if (url === '/api/scripts') return json(catalog)
    if (url.startsWith('/api/saves?')) return json(saves)
    if (url === '/api/saves') return json(snapshot)
    if (url === '/api/saves/save_one') return json(snapshot)
    throw Error('Unexpected test request')
  })
  vi.stubGlobal('fetch', fetch)
  return Object.assign(fetch, {
    setAuthenticated: (value: boolean) => {
      loggedIn = value
    },
  })
}
async function page(path: string) {
  const pinia = createPinia(),
    router = createAppRouter(createMemoryHistory(), pinia)
  const wrapper = mount(App, { global: { plugins: [pinia, router] } })
  wrappers.push(wrapper)
  await router.push(path)
  await router.isReady()
  await flushPromises()
  return { wrapper, router, pinia }
}
it('protects rooms, library and save entry without issuing private requests', async () => {
  const fetch = responses()
  fetch.setAuthenticated(false)
  const { router } = await page('/pairs')
  expect(router.currentRoute.value.path).toBe('/')
  for (const path of ['/pairs/pair_one', '/pairs/pair_one/library', '/saves/save_one']) {
    await router.push(path)
    expect(router.currentRoute.value.path).toBe('/')
  }
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/me'])
})
it('creates a room and copies a fragment invitation without putting it in the address bar', async () => {
  const fetch = responses({ member_count: 1 }),
    writeText = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  const { wrapper, router } = await page('/pairs')
  await wrapper.get('[data-test=create-pair]').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/pairs/pair_one')
  await wrapper.get('[data-test=copy-invite]').trigger('click')
  await flushPromises()
  expect(writeText.mock.calls[0]?.[0]).toMatch(/\/#invite=tw_invite_TEST_ONLY$/)
  expect(window.location.href).not.toContain(invitation.invite_token)
  expect(wrapper.text()).toContain('等待搭档加入')
  expect(
    fetch.mock.calls.filter(([url, opts]) => url === '/api/pairs' && opts?.method === 'POST'),
  ).toHaveLength(1)
})
it('requires explicit join after email login and removes fragment before joining', async () => {
  const fetch = responses()
  window.history.replaceState({}, '', '/#invite=tw_invite_TEST_ONLY')
  fetch.setAuthenticated(false)
  const { wrapper, router, pinia } = await page('/')
  usePairsStore(pinia).captureInvite()
  await flushPromises()
  expect(window.location.hash).toBe('')
  expect(wrapper.text()).toContain('邀请')
  await wrapper.get('#email').setValue(me.account.email)
  await wrapper.get('#password').setValue(password)
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/pairs')
  expect(fetch.mock.calls.some(([url]) => url === '/api/pairs/join')).toBe(false)
  await wrapper.get('[data-test=join-pair]').trigger('click')
  await flushPromises()
  expect(fetch.mock.calls.filter(([url]) => url === '/api/pairs/join')).toHaveLength(1)
  expect(router.currentRoute.value.path).toBe('/pairs/pair_one')
})
it.each([
  ['INVITE_INVALID', '过期'],
  ['PAIR_FULL', '满员'],
])('shows safe invitation error %s', async (code, text) => {
  responses({ joinError: code })
  const { wrapper, pinia } = await page('/pairs')
  usePairsStore(pinia).captureInvite('#invite=tw_invite_TEST_ONLY')
  await flushPromises()
  await wrapper.get('[data-test=join-pair]').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain(text)
  expect(wrapper.text()).not.toContain('PRIVATE_TEST')
})
it('real empty catalog displays empty state without fake story cards', async () => {
  responses({ catalog: [], saves: [] })
  const { wrapper } = await page('/pairs/pair_one/library')
  expect(wrapper.text()).toContain('暂时没有已发布剧本')
  expect(wrapper.findAll('[data-test=script-card]')).toHaveLength(0)
})
it('matches per-story progress and continues original version instead of creating', async () => {
  const fetch = responses({
    catalog: [script, { ...script, id: 'story_other', title: '未开始测试' }],
  })
  const { wrapper, router } = await page('/pairs/pair_one/library')
  expect(wrapper.findAll('[data-test=script-card]')).toHaveLength(2)
  expect(wrapper.text()).toContain('进行中')
  expect(wrapper.text()).toContain('尚未开始')
  expect(wrapper.text()).toContain('1.0.0')
  await wrapper.get('[data-test=continue-save]').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/saves/save_one')
  expect(wrapper.text()).toContain('T11')
  expect(
    fetch.mock.calls.some(([url, options]) => url === '/api/saves' && options?.method === 'POST'),
  ).toBe(false)
})
it('shows completed archives and waiting rooms cannot create a save', async () => {
  responses({
    saves: [{ ...summary, completed: true }],
    catalog: [script, { ...script, id: 'new_story' }],
    member_count: 1,
  })
  const { wrapper } = await page('/pairs/pair_one/library')
  expect(wrapper.text()).toContain('已完成')
  expect(wrapper.get('[data-test=start-save]').attributes('disabled')).toBeDefined()
  expect(wrapper.text()).toContain('等待搭档')
})
