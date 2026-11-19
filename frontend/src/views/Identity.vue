<template>
  <div class="identity-shell">
    <header class="brand">
      <span class="brand-symbol" aria-hidden="true">↔</span
      ><span>TwoWorlds<small>两个人 · 两个世界</small></span>
    </header>
    <main class="entry-layout">
      <section class="intro" aria-labelledby="welcome-title">
        <p class="eyebrow">我们的平行宇宙</p>
        <h1 id="welcome-title">一起，进入<br /><em>另一种可能。</em></h1>
        <p class="intro-copy">
          你看见的光，或许正是对方等待的答案。<br />用邮箱登录，继续你和搭档的旅程。
        </p>
        <div class="world-mark" aria-hidden="true">
          <span class="orbit orbit-one"></span><span class="orbit orbit-two"></span
          ><span class="connection"></span><span class="world-label label-one">你的世界</span
          ><span class="world-label label-two">另一个世界</span>
        </div>
        <p class="privacy-note">
          不需要手机号，也不需要分享真实关系。<br />换一台设备，也能用同一个邮箱继续。
        </p>
      </section>
      <section class="identity-panel" aria-label="邮箱账号" :aria-busy="pending">
        <template
          v-if="
            !identity.initialized ||
            identity.initializing ||
            (identity.sessionSuspended && !identity.verificationUnavailable && !identity.busy)
          "
        >
          <h2>正在验证身份</h2>
          <p role="status">正在确认此设备的会话。</p>
        </template>
        <template v-else-if="identity.authenticated">
          <p class="verified">已登录</p>
          <h2 class="account-name">{{ identity.account?.display_name }}</h2>
          <p>{{ identity.account?.email }}</p>
          <p v-if="identity.error" class="error" role="alert">{{ identity.error.message }}</p>
          <RouterLink class="action-link" to="/pairs">进入我的房间 →</RouterLink>
          <button class="secondary" type="button" :disabled="pending" @click="identity.logout()">
            {{ pending ? '正在登出…' : '登出' }}
          </button>
        </template>
        <template v-else-if="identity.verificationUnavailable && !identity.busy">
          <h2>暂时无法验证身份</h2>
          <p class="error" role="alert">请检查网络或服务地址后重试。</p>
          <button class="primary" type="button" @click="identity.verifySession()">重试验证</button>
        </template>
        <template v-else>
          <h2>{{ titles[mode] }}</h2>
          <p v-if="pairs.hasIncomingInvite" class="notice" role="status">
            已收到搭档邀请。登录后可前往房间确认加入。
          </p>
          <p v-if="notice" class="notice" role="status">{{ notice }}</p>
          <form class="identity-form" novalidate @submit.prevent="submit">
            <fieldset :disabled="pending">
              <div v-if="mode === 'register'">
                <label for="display-name">显示名称</label>
                <input
                  id="display-name"
                  v-model="displayName"
                  autocomplete="nickname"
                  required
                  :aria-invalid="invalidField === 'display-name'"
                  aria-describedby="identity-feedback"
                />
              </div>
              <div>
                <label for="email">邮箱</label>
                <input
                  id="email"
                  v-model="email"
                  type="email"
                  autocomplete="username"
                  maxlength="254"
                  required
                  :aria-invalid="invalidField === 'email'"
                  aria-describedby="identity-feedback"
                />
              </div>
              <div v-if="mode !== 'login'">
                <label for="verification-code">邮箱验证码</label>
                <div class="code-field">
                  <input
                    id="verification-code"
                    v-model="code"
                    inputmode="numeric"
                    autocomplete="one-time-code"
                    maxlength="6"
                    pattern="[0-9]{6}"
                    required
                    :aria-invalid="invalidField === 'verification-code'"
                    aria-describedby="identity-feedback"
                  />
                  <button
                    class="secondary"
                    data-test="send-code"
                    type="button"
                    :disabled="codeWait > 0"
                    @click="sendCode"
                  >
                    {{
                      codeWait
                        ? `重新发送（${codeWait}s）`
                        : sendingCode
                          ? '正在申请…'
                          : '发送验证码'
                    }}
                  </button>
                </div>
                <p v-if="codeNotice" class="help" role="status">{{ codeNotice }}</p>
              </div>
              <div>
                <label for="password">{{ mode === 'reset' ? '新密码' : '密码' }}</label>
                <div class="password-field">
                  <input
                    id="password"
                    v-model="password"
                    :type="reveal ? 'text' : 'password'"
                    :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
                    required
                    :aria-invalid="invalidField === 'password'"
                    aria-describedby="identity-feedback"
                  />
                  <button
                    type="button"
                    class="reveal"
                    :aria-pressed="reveal"
                    aria-controls="password"
                    @click="reveal = !reveal"
                  >
                    {{ reveal ? '隐藏密码' : '显示密码' }}
                  </button>
                </div>
              </div>
              <div v-if="mode !== 'login'">
                <label for="confirm-password">确认{{ mode === 'reset' ? '新密码' : '密码' }}</label>
                <input
                  id="confirm-password"
                  v-model="confirmation"
                  type="password"
                  autocomplete="new-password"
                  required
                  :aria-invalid="invalidField === 'confirm-password'"
                  aria-describedby="identity-feedback"
                />
              </div>
              <div id="identity-feedback">
                <p v-if="validation || visibleError" class="error" role="alert">
                  {{ validation || visibleError }}
                </p>
                <p v-if="submitWait" class="notice" role="status">
                  请在 {{ submitWait }}s 后再试。
                </p>
              </div>
              <button class="primary" type="submit" :disabled="submitWait > 0">
                {{ pending && !sendingCode ? '正在提交…' : submitLabels[mode] }}
              </button>
            </fieldset>
          </form>
          <div class="account-actions" aria-label="账号操作">
            <template v-if="mode === 'login'">
              <button class="reveal" type="button" :disabled="pending" @click="choose('register')">
                立即注册
              </button>
              <button class="reveal" type="button" :disabled="pending" @click="choose('reset')">
                忘记密码？
              </button>
            </template>
            <button
              v-else
              class="reveal"
              type="button"
              :disabled="pending"
              @click="choose('login')"
            >
              返回登录
            </button>
          </div>
        </template>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, routerKey } from 'vue-router'
import { useIdentityStore } from '../stores/identity'
import { usePairsStore } from '../stores/pairs'
import { normalizeEmail, validEmail } from '../types/api'

type Mode = 'login' | 'register' | 'reset'
const titles = { login: '邮箱登录', register: '创建你的账号', reset: '找回密码' }
const submitLabels = { login: '登录', register: '注册并登录', reset: '重置密码' }
const identity = useIdentityStore()
const pairs = usePairsStore()
const router = inject(routerKey, null)
const mode = ref<Mode>('login')
const email = ref('')
const displayName = ref('')
const code = ref('')
const password = ref('')
const confirmation = ref('')
const reveal = ref(false)
const sendingCode = ref(false)
const invalidField = ref('')
const validation = ref('')
const notice = ref('')
const codeNotice = ref('')
const pending = computed(() => identity.busy || identity.initializing)
const codeWait = ref(0)
const submitWait = ref(0)
const codeDeadlines = new Map<string, number>()
function codeKey(address = normalizeEmail(email.value), purpose = mode.value) {
  return `${purpose}:${address}`
}
let submitDeadline = 0
let timer: number | undefined
let mounted = true
const visibleError = computed(() => identity.error?.message ?? '')

function stopTimer() {
  window.clearInterval(timer)
  timer = undefined
}

function tick() {
  const now = Date.now() / 1000
  codeWait.value = Math.max(0, Math.ceil((codeDeadlines.get(codeKey()) ?? 0) - now))
  submitWait.value = Math.max(0, Math.ceil(submitDeadline - now))
  if ((!codeWait.value || mode.value === 'login') && !submitWait.value) stopTimer()
}

function scheduleTimer() {
  stopTimer()
  tick()
  if ((mode.value !== 'login' && codeWait.value > 0) || submitWait.value > 0)
    timer = window.setInterval(tick, 250)
}

function clearSecrets() {
  password.value = ''
  confirmation.value = ''
  code.value = ''
  reveal.value = false
}

function choose(next: Mode) {
  if (pending.value) return
  mode.value = next
  clearSecrets()
  displayName.value = ''
  validation.value = ''
  invalidField.value = ''
  notice.value = ''
  codeNotice.value = ''
  identity.error = null
  scheduleTimer()
  void nextTick(() => {
    if (mounted) document.getElementById(next === 'register' ? 'display-name' : 'email')?.focus()
  })
}

watch([email, displayName, code, password, confirmation], () => {
  if (pending.value) return
  validation.value = ''
  invalidField.value = ''
})
watch(email, () => {
  codeNotice.value = ''
  scheduleTimer()
})

onMounted(() => void identity.initialize())
onBeforeUnmount(() => {
  mounted = false
  stopTimer()
  clearSecrets()
})

function invalid(field: string, message: string) {
  invalidField.value = field
  validation.value = message
  document.getElementById(field)?.focus()
}

async function sendCode() {
  const address = normalizeEmail(email.value)
  const key = codeKey(address)
  if (pending.value || mode.value === 'login' || Date.now() / 1000 < (codeDeadlines.get(key) ?? 0))
    return
  if (!validEmail(address)) return invalid('email', '请输入有效的邮箱地址。')
  validation.value = ''
  invalidField.value = ''
  codeNotice.value = ''
  sendingCode.value = true
  const accepted = await identity.requestVerificationCode(address, mode.value)
  if (!mounted) return
  sendingCode.value = false
  if (accepted) {
    codeNotice.value = '如果邮箱符合条件，验证码将发送至邮箱。请检查收件箱及垃圾邮件。'
    codeDeadlines.set(key, Date.now() / 1000 + 60)
  } else if (identity.error?.retryAfter !== undefined) {
    codeDeadlines.set(key, Date.now() / 1000 + identity.error.retryAfter)
  }
  scheduleTimer()
}

async function submit() {
  if (pending.value || Date.now() / 1000 < submitDeadline) return
  const address = normalizeEmail(email.value)
  const name = displayName.value.trim()
  const current = mode.value
  if (current === 'register' && (!name || Array.from(name).length > 40))
    return invalid('display-name', '显示名称需为 1–40 个字符。')
  if (!validEmail(address)) return invalid('email', '请输入有效的邮箱地址。')
  if (current !== 'login' && !/^[0-9]{6}$/.test(code.value))
    return invalid('verification-code', '请输入 6 位数字验证码。')
  const length = Array.from(password.value).length
  if (current === 'login' && (!length || length > 1024))
    return invalid('password', '请输入你的密码。')
  if (current !== 'login' && (length < 10 || length > 128))
    return invalid('password', '密码需为 10–128 个字符。')
  if (current !== 'login' && password.value !== confirmation.value)
    return invalid('confirm-password', '两次输入的密码不一致。')
  validation.value = ''
  invalidField.value = ''
  notice.value = ''
  const success =
    current === 'register'
      ? await identity.register({
          email: address,
          password: password.value,
          code: code.value,
          display_name: name,
        })
      : current === 'reset'
        ? await identity.resetPassword({
            email: address,
            code: code.value,
            new_password: password.value,
          })
        : await identity.login({ email: address, password: password.value })
  if (!mounted) return
  if (!success) {
    if (identity.error?.retryAfter !== undefined) {
      submitDeadline = Date.now() / 1000 + identity.error.retryAfter
      scheduleTimer()
    }
    return
  }
  if (current === 'reset') {
    choose('login')
    notice.value = '密码已重置，请使用新密码登录。'
  } else {
    clearSecrets()
    void router?.push('/pairs')
  }
}
</script>
