<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useIdentityStore } from '../stores/identity'
const identity = useIdentityStore()
const mode = ref<'create' | 'recover'>('create')
const displayName = ref('')
const recoveryInput = ref('')
const reveal = ref(false)
// Page memory only: never enter Pinia, storage, URL or automatic sharing.
const oneTimeKey = ref('')
const validation = ref('')
const copyStatus = ref('')
const expiration = computed(() =>
  identity.expiresAt
    ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(
        new Date(identity.expiresAt),
      )
    : '',
)
onMounted(() => {
  void identity.initialize()
})
onBeforeUnmount(() => {
  oneTimeKey.value = ''
  recoveryInput.value = ''
})
function choose(next: 'create' | 'recover') {
  if (identity.busy) return
  mode.value = next
  validation.value = ''
  identity.error = null
  recoveryInput.value = ''
  reveal.value = false
}
async function create() {
  if (identity.busy) return
  const name = displayName.value.trim()
  if (!name || Array.from(name).length > 40) {
    validation.value = '显示名称需为 1–40 个字符，不能只含空白。'
    return
  }
  validation.value = ''
  const key = await identity.create(name)
  if (key) oneTimeKey.value = key
}
async function recover() {
  if (identity.busy) return
  const key = recoveryInput.value.trim()
  if (!key || key.length > 128) {
    validation.value = '请填写 1–128 个字符的恢复密钥。'
    return
  }
  validation.value = ''
  try {
    await identity.recover(key)
  } finally {
    recoveryInput.value = ''
    reveal.value = false
  }
}
async function copyKey() {
  try {
    await navigator.clipboard.writeText(oneTimeKey.value)
    copyStatus.value = '已复制。请保存到你信任的位置。'
  } catch {
    copyStatus.value = '无法自动复制，请选择下方密钥手动复制。'
  }
}
function confirmKey() {
  oneTimeKey.value = ''
  copyStatus.value = ''
}
</script>
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
          你看见的光，或许正是对方等待的答案。<br />先为自己留一个名字，让下一次相遇有迹可循。
        </p>
        <div class="world-mark" aria-hidden="true">
          <span class="orbit orbit-one"></span><span class="orbit orbit-two"></span
          ><span class="connection"></span><span class="world-label label-one">你的世界</span
          ><span class="world-label label-two">另一个世界</span>
        </div>
        <p class="privacy-note">
          不需要手机号，也不需要分享真实关系。<br />用恢复密钥，在另一台设备找回同一个你。
        </p>
      </section>
      <section
        class="identity-panel"
        aria-label="个人身份"
        :aria-busy="identity.busy || identity.initializing"
      >
        <p class="panel-kicker">旅程，从你开始</p>
        <template v-if="!identity.initialized || identity.initializing">
          <h2>正在验证身份</h2>
          <p role="status">请稍候，正在确认此设备的会话。</p>
        </template>
        <template v-else-if="oneTimeKey">
          <h2>保存你的恢复密钥</h2>
          <p class="notice">
            恢复密钥只展示一次。丢失后无法通过 account_id 找回，请保存在你信任的位置，不要发给他人。
          </p>
          <label for="one-time-key">你的恢复密钥</label>
          <textarea
            id="one-time-key"
            data-test="one-time-key"
            class="secret"
            readonly
            :value="oneTimeKey"
            rows="3"
            spellcheck="false"
            @focus="($event.target as HTMLTextAreaElement).select()"
          ></textarea>
          <button data-test="copy-key" class="secondary" @click="copyKey">复制密钥</button>
          <p class="help">也可以选中上方密钥手动复制。此页面不会替你备份。</p>
          <p v-if="copyStatus" role="status">{{ copyStatus }}</p>
          <button data-test="confirm-key" class="primary" @click="confirmKey">
            我已保存，继续
          </button>
        </template>
        <template v-else-if="identity.authenticated">
          <p class="verified">身份已验证</p>
          <h2 class="account-name">你好，{{ identity.account?.display_name }}</h2>
          <dl class="session-details">
            <dt>此设备的会话到期时间</dt>
            <dd>{{ expiration }}</dd>
          </dl>
          <p>身份已就绪。双人房间与剧本书架将在下一阶段接入。</p>
          <button class="secondary" :disabled="identity.busy" @click="identity.logout">
            {{ identity.busy ? '正在撤销会话…' : '登出此设备' }}
          </button>
        </template>
        <template v-else-if="identity.token">
          <h2>暂时无法验证身份</h2>
          <p>已保留此设备的会话信息。请检查连接后重试，暂不创建另一个身份。</p>
          <button class="primary" @click="identity.verifySession">重新验证</button>
        </template>
        <template v-else>
          <h2>{{ mode === 'create' ? '为旅程留个名字' : '欢迎回到这里' }}</h2>
          <p class="panel-intro">
            {{
              mode === 'create'
                ? '一个名字，一把密钥。下一次，继续做你。'
                : '输入曾保存的恢复密钥，回到原来的身份。'
            }}
          </p>
          <div class="mode-switch" role="group" aria-label="选择身份操作">
            <button
              :aria-pressed="mode === 'create'"
              :disabled="identity.busy"
              @click="choose('create')"
            >
              创建新身份
            </button>
            <button
              data-test="restore-tab"
              :aria-pressed="mode === 'recover'"
              :disabled="identity.busy"
              @click="choose('recover')"
            >
              恢复已有身份
            </button>
          </div>
          <form
            v-if="mode === 'create'"
            data-test="create-form"
            novalidate
            @submit.prevent="create"
          >
            <label for="display-name">显示名称</label>
            <input
              id="display-name"
              v-model="displayName"
              autocomplete="nickname"
              placeholder="你希望被怎样称呼？"
              :disabled="identity.busy"
              :aria-invalid="!!validation"
              aria-describedby="name-help form-error"
            />
            <p id="name-help" class="help">1–40 个字符，可以使用昵称。</p>
            <button
              data-test="create-button"
              class="primary"
              type="submit"
              :disabled="identity.busy"
            >
              {{ identity.busy ? '正在创建，请稍候…' : '创建我的身份' }}
            </button>
          </form>
          <form v-else data-test="recover-form" novalidate @submit.prevent="recover">
            <label for="recovery-key">恢复密钥</label>
            <input
              id="recovery-key"
              v-model="recoveryInput"
              :type="reveal ? 'text' : 'password'"
              autocomplete="off"
              autocapitalize="off"
              spellcheck="false"
              :disabled="identity.busy"
              :aria-invalid="!!validation"
              aria-describedby="recovery-help form-error"
            />
            <button
              data-test="toggle-key"
              class="reveal"
              type="button"
              :disabled="identity.busy"
              :aria-pressed="reveal"
              @click="reveal = !reveal"
            >
              {{ reveal ? '隐藏密钥' : '显示密钥' }}
            </button>
            <p id="recovery-help" class="help">使用创建身份时保存的密钥，不是显示名称或账号 ID。</p>
            <button class="primary" type="submit" :disabled="identity.busy">
              {{ identity.busy ? '正在恢复，请稍候…' : '恢复我的身份' }}
            </button>
          </form>
        </template>
        <p v-if="validation || identity.error" id="form-error" class="error" role="alert">
          {{ validation || identity.error?.message }}
        </p>
        <p v-if="identity.storageWarning" class="notice" role="status">
          {{ identity.storageWarning }}
        </p>
        <footer class="panel-foot">你的身份属于你，恢复密钥请自行保管。</footer>
      </section>
    </main>
    <footer class="site-foot">TwoWorlds <span>留一束光，给另一个世界。</span></footer>
  </div>
</template>
