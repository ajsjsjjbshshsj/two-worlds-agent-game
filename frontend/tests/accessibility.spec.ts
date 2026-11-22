import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, expect, it, vi } from 'vitest'
import { useKeyboardViewport } from '../src/composables/keyboard-viewport'
import SpaceShell from '../src/components/SpaceShell.vue'
import Device from '../src/components/game/Device.vue'
import Identity from '../src/views/Identity.vue'
import { fail } from './fixtures'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

it('only scrolls a focused form field when the visual viewport obscures it and cleans up', () => {
  const viewport = new EventTarget()
  const remove = vi.spyOn(viewport, 'removeEventListener')
  Object.assign(viewport, { height: 300, offsetTop: 0 })
  vi.stubGlobal('visualViewport', viewport)
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    callback(0)
    return 1
  })
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  const w = mount(
    {
      setup() {
        useKeyboardViewport()
        return {}
      },
      template: '<input aria-label="test" />',
    },
    { attachTo: document.body },
  )
  const input = w.get('input').element
  const scroll = vi.fn()
  input.scrollIntoView = scroll
  vi.spyOn(input, 'getBoundingClientRect').mockReturnValue({ top: 400, bottom: 448 } as DOMRect)
  input.focus()
  expect(scroll).toHaveBeenCalledWith({ block: 'center', behavior: 'instant' })
  scroll.mockClear()
  vi.spyOn(input, 'getBoundingClientRect').mockReturnValue({ top: 40, bottom: 88 } as DOMRect)
  viewport.dispatchEvent(new Event('resize'))
  expect(scroll).not.toHaveBeenCalled()
  w.unmount()
  expect(remove).toHaveBeenCalledWith('resize', expect.any(Function))
  viewport.dispatchEvent(new Event('resize'))
  expect(scroll).not.toHaveBeenCalled()
})

it('keeps native behavior for visible fields and non-form focus without VisualViewport', () => {
  vi.stubGlobal('visualViewport', undefined)
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    callback(0)
    return 1
  })
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  const w = mount(
    {
      setup() {
        useKeyboardViewport()
        return {}
      },
      template: '<div><input aria-label="test" /><button>Continue</button></div>',
    },
    { attachTo: document.body },
  )
  const field = w.get('input').element
  const scroll = vi.fn()
  field.scrollIntoView = scroll
  vi.spyOn(field, 'getBoundingClientRect').mockReturnValue({ top: 40, bottom: 88 } as DOMRect)
  field.focus()
  expect(scroll).not.toHaveBeenCalled()
  w.get('button').element.focus()
  expect(scroll).not.toHaveBeenCalled()
  w.unmount()
})

it('cancels queued viewport work on unmount', () => {
  vi.stubGlobal(
    'requestAnimationFrame',
    vi.fn(() => 17),
  )
  const cancel = vi.fn()
  vi.stubGlobal('cancelAnimationFrame', cancel)
  const w = mount(
    {
      setup() {
        useKeyboardViewport()
        return {}
      },
      template: '<input aria-label="test" />',
    },
    { attachTo: document.body },
  )
  w.get('input').element.focus()
  w.unmount()
  expect(cancel).toHaveBeenLastCalledWith(17)
})

it('provides keyboard skip navigation to the main content', () => {
  const w = mount(SpaceShell, {
    global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  expect(w.get('.skip-link').attributes('href')).toBe('#main-content')
  w.unmount()
})

it('device detail is a named, focusable target with textual boolean status', () => {
  const w = mount(Device, { props: { id: 'engine', fields: { enabled: false } } })
  expect(w.get('article').attributes('aria-labelledby')).toBe('device-heading-engine')
  expect(w.get('article').attributes('tabindex')).toBe('-1')
  expect(w.text()).toContain('关闭')
  w.unmount()
})

it('email keyboard disables capitalization and spelling while preserving login autocomplete', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fail(401)))
  const w = mount(Identity, { global: { plugins: [createPinia()] } })
  await flushPromises()
  expect(w.get('#email').attributes()).toMatchObject({
    inputmode: 'email',
    autocapitalize: 'none',
    spellcheck: 'false',
    autocomplete: 'username',
  })
  w.unmount()
})
