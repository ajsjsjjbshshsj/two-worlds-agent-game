import { createPinia } from 'pinia'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import Identity from '../../src/views/Identity.vue'
import { deferred, fail, json, me, noContent, password } from '../fixtures'

function page(...responses: (Response | Error | Promise<Response>)[]) {
  const fetch = vi.fn().mockResolvedValue(fail(401))
  for (const response of responses.length ? responses : [fail(401)]) {
    if (response instanceof Error) fetch.mockRejectedValueOnce(response)
    else fetch.mockImplementationOnce(() => Promise.resolve(response))
  }
  vi.stubGlobal('fetch', fetch)
  const wrapper = mount(Identity, {
    global: { plugins: [createPinia()], stubs: { RouterLink: RouterLinkStub } },
  })
  return { wrapper, fetch }
}
type Wrapper = ReturnType<typeof page>['wrapper']
const wrappers: Wrapper[] = []
async function open(...responses: (Response | Error | Promise<Response>)[]) {
  const result = page(...responses)
  wrappers.push(result.wrapper)
  await flushPromises()
  return result
}
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.useRealTimers()
})
async function choose(w: Wrapper, text: string) {
  const button = w.findAll('button').find((candidate) => candidate.text() === text)
  expect(button).toBeDefined()
  await button!.trigger('click')
}
async function fill(w: Wrapper, mode: 'login' | 'register' | 'reset') {
  await w.get('#email').setValue(me.account.email)
  await w.get('#password').setValue(password)
  if (mode !== 'login') {
    await w.get('#verification-code').setValue('123456')
    await w.get('#confirm-password').setValue(password)
  }
  if (mode === 'register') await w.get('#display-name').setValue(me.account.display_name)
}

it('defaults to labeled email login with the correct autocomplete and native form controls', async () => {
  const { wrapper } = await open()
  expect(wrapper.get('h2').text()).toBe('邮箱登录')
  expect(wrapper.get('label[for=email]').text()).toBe('邮箱')
  expect(wrapper.get('#email').attributes('type')).toBe('email')
  expect(wrapper.get('#email').attributes('autocomplete')).toBe('username')
  expect(wrapper.get('#password').attributes('autocomplete')).toBe('current-password')
  expect(wrapper.get('button[type=submit]').text()).toBe('登录')
  expect(wrapper.find('#verification-code').exists()).toBe(false)
})

it('toggles password visibility without changing the value or submitting', async () => {
  const { wrapper, fetch } = await open()
  await wrapper.get('#password').setValue(password)
  await choose(wrapper, '显示密码')
  expect(wrapper.get('#password').attributes('type')).toBe('text')
  expect(wrapper.get('[aria-controls=password]').attributes('aria-pressed')).toBe('true')
  await choose(wrapper, '隐藏密码')
  expect(wrapper.get('#password').attributes('type')).toBe('password')
  expect((wrapper.get('#password').element as HTMLInputElement).value).toBe(password)
  expect(fetch).toHaveBeenCalledTimes(1)
})

it('register presents a nickname, numeric code, new password and confirmation', async () => {
  const { wrapper } = await open()
  await choose(wrapper, '立即注册')
  expect(wrapper.get('#display-name').attributes('autocomplete')).toBe('nickname')
  expect(wrapper.get('#verification-code').attributes()).toMatchObject({
    inputmode: 'numeric',
    maxlength: '6',
    autocomplete: 'one-time-code',
  })
  expect(wrapper.get('label[for=confirm-password]').text()).toBe('确认密码')
  expect(wrapper.get('#password').attributes('autocomplete')).toBe('new-password')
})

it.each([
  ['display-name', '', '显示名称'],
  ['display-name', '旅'.repeat(41), '显示名称'],
  ['email', 'invalid', '邮箱'],
  ['verification-code', '', '验证码'],
  ['verification-code', '12e456', '验证码'],
  ['password', 'short', '10–128'],
  ['password', '旅'.repeat(129), '10–128'],
  ['confirm-password', 'different-password', '不一致'],
])('rejects invalid register field %s before POST', async (field, value, message) => {
  const { wrapper, fetch } = await open()
  await choose(wrapper, '立即注册')
  await fill(wrapper, 'register')
  await wrapper.get(`#${field}`).setValue(value)
  await wrapper.get('form').trigger('submit')
  expect(wrapper.get('[role=alert]').text()).toContain(message)
  expect(wrapper.get(`#${field}`).attributes('aria-invalid')).toBe('true')
  expect(fetch).toHaveBeenCalledTimes(1)
})

it('registration accepts 40 Unicode characters and automatically authenticates', async () => {
  const { wrapper, fetch } = await open(fail(401), json(me))
  await choose(wrapper, '立即注册')
  await fill(wrapper, 'register')
  await wrapper.get('#display-name').setValue('旅'.repeat(40))
  await wrapper.get('#email').setValue(' PLAYER@EXAMPLE.TEST ')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(fetch.mock.calls[1]![0]).toBe('/api/accounts')
  expect(JSON.parse(fetch.mock.calls[1]![1].body)).toMatchObject({
    display_name: '旅'.repeat(40),
    email: me.account.email,
  })
  expect(wrapper.text()).toContain('已登录')
  expect(wrapper.text()).not.toMatch(/恢复密钥|123456|example-password/)
})

it('successful login replaces the form with the verified account and room link', async () => {
  const { wrapper, fetch } = await open(fail(401), json(me))
  await fill(wrapper, 'login')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(fetch.mock.calls[1]![0]).toBe('/api/sessions')
  expect(wrapper.text()).toContain(me.account.email)
  expect(wrapper.text()).toContain('进入我的房间')
  expect(wrapper.find('#password').exists()).toBe(false)
})

it('unknown email and wrong password share one localized 401 response', async () => {
  const { wrapper } = await open(fail(401), fail(401, 'INVALID_CREDENTIALS'))
  await fill(wrapper, 'login')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('[role=alert]').text()).toBe('邮箱或密码错误。')
  expect(wrapper.text()).not.toContain('PRIVATE_TEST_RESPONSE')
})

it('loading disables form controls and duplicate submits do not repeat the password', async () => {
  const response = deferred<Response>()
  const { wrapper, fetch } = await open(fail(401), response.promise)
  await fill(wrapper, 'login')
  await wrapper.get('form').trigger('submit')
  await wrapper.get('form').trigger('submit')
  expect(wrapper.get('fieldset').attributes('disabled')).toBeDefined()
  expect(wrapper.get('button[type=submit]').text()).toBe('正在提交…')
  expect(fetch).toHaveBeenCalledTimes(2)
  response.resolve(json(me))
  await flushPromises()
})

it.each(['立即注册', '忘记密码？'])(
  '202 feedback is neutral and the countdown has 60 seconds in %s',
  async (mode) => {
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
    const { wrapper, fetch } = await open(fail(401), json({ status: 'accepted' }, 202))
    await choose(wrapper, mode)
    await wrapper.get('#email').setValue(me.account.email)
    const send = wrapper.get('[data-test=send-code]')
    await send.trigger('click')
    await flushPromises()
    expect(send.text()).toContain('60s')
    expect(send.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('如果邮箱符合条件')
    expect(wrapper.text()).not.toMatch(/发送成功|邮箱未注册/)
    expect(JSON.parse(fetch.mock.calls[1]![1].body).purpose).toBe(
      mode === '立即注册' ? 'register' : 'reset',
    )
    await vi.advanceTimersByTimeAsync(1000)
    expect(send.text()).toContain('59s')
    await vi.advanceTimersByTimeAsync(59000)
    expect(send.attributes('disabled')).toBeUndefined()
  },
)

it('429 retains the server cooldown for the same normalized email and purpose without auto-resending', async () => {
  vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
  const { wrapper, fetch } = await open(fail(401), fail(429, 'RATE_LIMITED', '75'))
  await choose(wrapper, '立即注册')
  await wrapper.get('#email').setValue(me.account.email)
  await wrapper.get('[data-test=send-code]').trigger('click')
  await flushPromises()
  expect(wrapper.get('[data-test=send-code]').text()).toContain('75s')
  expect(wrapper.get('[role=alert]').text()).toContain('频繁')
  await choose(wrapper, '返回登录')
  expect(vi.getTimerCount()).toBe(0)
  await choose(wrapper, '忘记密码？')
  expect(wrapper.get('[data-test=send-code]').attributes('disabled')).toBeUndefined()
  await choose(wrapper, '返回登录')
  await choose(wrapper, '立即注册')
  await wrapper.get('#email').setValue(me.account.email.toUpperCase())
  expect(wrapper.get('[data-test=send-code]').text()).toContain('75s')
  await vi.advanceTimersByTimeAsync(75000)
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(wrapper.get('[data-test=send-code]').attributes('disabled')).toBeUndefined()
})

it('202 cooldown is scoped to email and purpose, and server throttling still applies to reset', async () => {
  vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
  const { wrapper, fetch } = await open(
    fail(401),
    json({ status: 'accepted' }, 202),
    fail(429, 'RATE_LIMITED', '45'),
  )
  await choose(wrapper, '立即注册')
  await wrapper.get('#email').setValue(me.account.email)
  await wrapper.get('[data-test=send-code]').trigger('click')
  await flushPromises()
  await wrapper.get('#email').setValue('another@example.test')
  expect(wrapper.get('[data-test=send-code]').attributes('disabled')).toBeUndefined()
  await wrapper.get('#email').setValue(me.account.email)
  expect(wrapper.get('[data-test=send-code]').text()).toContain('60s')
  await choose(wrapper, '返回登录')
  await choose(wrapper, '忘记密码？')
  await wrapper.get('[data-test=send-code]').trigger('click')
  await flushPromises()
  expect(JSON.parse(fetch.mock.calls[2]![1].body).purpose).toBe('reset')
  expect(wrapper.get('[data-test=send-code]').text()).toContain('45s')
})

it.each(['INVALID_CODE', 'CODE_EXPIRED', 'CODE_LOCKED'])(
  'reset shows %s as a safe verification error and preserves form input',
  async (error) => {
    const { wrapper } = await open(fail(401), fail(422, error))
    await choose(wrapper, '忘记密码？')
    await fill(wrapper, 'reset')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('验证码')
    expect(wrapper.get('[role=alert]').text()).not.toContain('PRIVATE')
    expect((wrapper.get('#password').element as HTMLInputElement).value).toBe(password)
    expect((wrapper.get('#verification-code').element as HTMLInputElement).value).toBe('123456')
  },
)

it('confirmed reset returns to login, clears secrets, retains the email and asks to sign in', async () => {
  const { wrapper } = await open(fail(401), noContent())
  await choose(wrapper, '忘记密码？')
  await fill(wrapper, 'reset')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('h2').text()).toBe('邮箱登录')
  expect(wrapper.get('[role=status]').text()).toContain('密码已重置')
  expect((wrapper.get('#email').element as HTMLInputElement).value).toBe(me.account.email)
  expect((wrapper.get('#password').element as HTMLInputElement).value).toBe('')
})

it('reset network uncertainty does not display success or repeat the request', async () => {
  const { wrapper, fetch } = await open(fail(401), new TypeError('PRIVATE'))
  await choose(wrapper, '忘记密码？')
  await fill(wrapper, 'reset')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('[role=alert]').text()).toContain('密码重置结果尚未确认')
  expect(wrapper.text()).not.toContain('密码已重置')
  expect(fetch).toHaveBeenCalledTimes(2)
})

it('temporary startup failure offers a retry before presenting the login form', async () => {
  const { wrapper, fetch } = await open(fail(503), fail(401))
  expect(wrapper.get('h2').text()).toBe('暂时无法验证身份')
  expect(wrapper.find('form').exists()).toBe(false)
  await choose(wrapper, '重试验证')
  await flushPromises()
  expect(wrapper.get('h2').text()).toBe('邮箱登录')
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/me', '/api/me'])
})

it('mode switch clears code, passwords, reveal state and active interval', async () => {
  vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
  const { wrapper } = await open(fail(401), json({ status: 'accepted' }, 202))
  await choose(wrapper, '立即注册')
  await fill(wrapper, 'register')
  await choose(wrapper, '显示密码')
  await wrapper.get('[data-test=send-code]').trigger('click')
  await flushPromises()
  expect(vi.getTimerCount()).toBe(1)
  await choose(wrapper, '返回登录')
  expect(vi.getTimerCount()).toBe(0)
  expect(wrapper.get('#password').attributes('type')).toBe('password')
  await choose(wrapper, '立即注册')
  for (const selector of ['#password', '#confirm-password', '#verification-code']) {
    expect((wrapper.get(selector).element as HTMLInputElement).value).toBe('')
  }
  wrapper.unmount()
  wrappers.splice(wrappers.indexOf(wrapper), 1)
  expect(vi.getTimerCount()).toBe(0)
})
