import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Identity from '../src/views/Identity.vue'
import { created, json } from './fixtures'

const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(created)))
})
afterEach(() => {
  wrappers.forEach((w) => w.unmount())
  wrappers.length = 0
  vi.unstubAllGlobals()
})
async function setup() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: Identity },
      { path: '/destination', component: { template: '<p>目的地</p>' } },
    ],
  })
  await router.push('/destination')
  await router.push('/')
  const wrapper = mount(RouterView, { global: { plugins: [createPinia(), router] } })
  wrappers.push(wrapper)
  await router.isReady()
  await flushPromises()
  await wrapper.get('#display-name').setValue('旅人')
  await wrapper.get('[data-test=create-form]').trigger('submit')
  await flushPromises()
  return { router, wrapper }
}
it('canceling SPA leave retains key and Pending; accepting clears page key only on unmount', async () => {
  const { router, wrapper } = await setup()
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  await router.push('/destination')
  expect(confirm).toHaveBeenCalledTimes(1)
  expect(router.currentRoute.value.path).toBe('/')
  expect((wrapper.get('[data-test=one-time-key]').element as HTMLTextAreaElement).value).toBe(
    created.recovery_key,
  )
  expect(localStorage.getItem('twoworlds.recovery.pending.v1.' + created.account.id)).not.toBeNull()
  confirm.mockReturnValue(true)
  await router.push('/destination')
  await flushPromises()
  expect(wrapper.find('[data-test=one-time-key]').exists()).toBe(false)
  expect(localStorage.getItem('twoworlds.recovery.pending.v1.' + created.account.id)).not.toBeNull()
  const unload = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(unload)
  expect(unload.defaultPrevented).toBe(false)
})
it('later navigation cancellation does not clear the key after leave confirmation', async () => {
  const { router, wrapper } = await setup()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  router.beforeResolve((to) => (to.path === '/destination' ? false : true))
  await router.push('/destination')
  expect(router.currentRoute.value.path).toBe('/')
  expect((wrapper.get('[data-test=one-time-key]').element as HTMLTextAreaElement).value).toBe(
    created.recovery_key,
  )
  const unload = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(unload)
  expect(unload.defaultPrevented).toBe(true)
})
it('saving the key permits navigation without confirmation', async () => {
  const { router, wrapper } = await setup()
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  await wrapper.get('[data-test=confirm-key]').trigger('click')
  await router.push('/destination')
  expect(router.currentRoute.value.path).toBe('/destination')
  expect(confirm).not.toHaveBeenCalled()
})
it('history back uses the same protection and preserves key after cancel', async () => {
  const { router, wrapper } = await setup()
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  router.back()
  await flushPromises()
  expect(confirm).toHaveBeenCalledOnce()
  expect(router.currentRoute.value.path).toBe('/')
  expect(wrapper.find('[data-test=one-time-key]').exists()).toBe(true)
})
