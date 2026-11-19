import { createPinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
import { createAppRouter } from '../src/router'
import { useIdentityStore } from '../src/stores/identity'
import { deferred, fail, json, me, password } from './fixtures'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function setup() {
  const fetch = vi.fn().mockResolvedValueOnce(fail(401))
  vi.stubGlobal('fetch', fetch)
  const pinia = createPinia()
  const router = createAppRouter(createMemoryHistory(), pinia)
  const wrapper = mount(App, { global: { plugins: [pinia, router] } })
  wrappers.push(wrapper)
  await router.push('/')
  await flushPromises()
  return { wrapper, router, fetch, identity: useIdentityStore(pinia) }
}

async function submit(wrapper: Awaited<ReturnType<typeof setup>>['wrapper']) {
  await wrapper.get('#email').setValue(me.account.email)
  await wrapper.get('#password').setValue(password)
  await wrapper.get('form').trigger('submit')
}

it('successful native form submission reaches the rooms route without a legacy prompt', async () => {
  const { wrapper, fetch, router } = await setup()
  const confirm = vi.spyOn(window, 'confirm')
  fetch.mockResolvedValueOnce(json(me)).mockResolvedValueOnce(json([]))
  await submit(wrapper)
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/pairs')
  expect(wrapper.text()).toContain('我的双人房间')
  expect(confirm).not.toHaveBeenCalled()
  expect(wrapper.text()).not.toContain(password)
})

it('unmounted form cannot navigate or put late validation feedback in the document', async () => {
  const { wrapper, router, fetch } = await setup()
  const late = deferred<Response>()
  fetch.mockReturnValueOnce(late.promise)
  await submit(wrapper)
  wrapper.unmount()
  wrappers.splice(wrappers.indexOf(wrapper), 1)
  late.resolve(json(me))
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/')
  expect(document.body.textContent).not.toContain(password)
})

it('direct private navigation waits for the shared startup check without loading private data on 503', async () => {
  const { wrapper, router, fetch, identity } = await setup()
  fetch.mockResolvedValueOnce(fail(503))
  await identity.verifySession()
  await router.push('/saves/save_one')
  expect(router.currentRoute.value.path).toBe('/')
  expect(wrapper.text()).toContain('暂时无法验证身份')
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/me', '/api/me'])
})

it('expired session on a protected page redirects and cannot return with browser history', async () => {
  const { wrapper, router, fetch, identity } = await setup()
  fetch.mockResolvedValueOnce(json(me)).mockResolvedValueOnce(json([]))
  await submit(wrapper)
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/pairs')
  identity.expireSession()
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/')
  await router.push('/pairs')
  expect(router.currentRoute.value.path).toBe('/')
  expect(wrapper.find('#password').exists()).toBe(true)
})
