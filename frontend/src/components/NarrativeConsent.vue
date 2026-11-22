<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { createHttpClient, isRecord } from '../services/http'

interface Consent {
  available: boolean
  allowed: boolean
  has_consent: boolean
  destination: string | null
  model: string | null
  disclosure: string | null
}

const client = createHttpClient()
const endpoint = '/api/narrative_consent'
const status = ref<Consent | null>(null)
const opened = ref(false)
const busy = ref(false)
const error = ref('')
let request: AbortController | undefined
let active = true
onBeforeUnmount(() => {
  active = false
  request?.abort()
})

function parse(raw: unknown): Consent {
  if (
    !isRecord(raw) ||
    typeof raw.available !== 'boolean' ||
    typeof raw.allowed !== 'boolean' ||
    typeof raw.has_consent !== 'boolean' ||
    (raw.available
      ? typeof raw.destination !== 'string' ||
        typeof raw.model !== 'string' ||
        typeof raw.disclosure !== 'string' ||
        !/^[0-9a-f]{64}$/.test(raw.disclosure)
      : raw.destination !== null || raw.model !== null || raw.disclosure !== null || raw.allowed)
  )
    throw Error('Invalid consent state')
  return raw as unknown as Consent
}

async function update(allow?: boolean) {
  if (busy.value || (allow === true && !status.value?.disclosure)) return
  const controller = new AbortController()
  request = controller
  error.value = ''
  opened.value = true
  busy.value = true
  try {
    const raw = await client.request(endpoint, {
      privateSession: true,
      signal: controller.signal,
      ...(allow === undefined
        ? {}
        : { method: 'POST', body: { allow, disclosure: allow ? status.value?.disclosure : null } }),
    })
    if (active) status.value = parse(raw)
  } catch {
    if (active) {
      status.value = null
      error.value = '暂时无法确认外部 AI 授权，请重新读取。'
    }
  } finally {
    if (active) busy.value = false
  }
}
</script>

<template>
  <section aria-label="外部 AI 隐私设置" :aria-busy="busy">
    <button type="button" class="secondary" :disabled="busy" @click="update()">
      {{ opened ? '刷新外部 AI 设置' : '外部 AI 隐私设置' }}
    </button>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="status">
      <template v-if="status.available">
        <p>
          同意后，NPC 提问、你有权查看的线索和设备、当前场景及你最近的 NPC 对话会发送至
          {{ status.destination }}，由模型 {{ status.model }} 生成回复。
          授权适用于此账号的存档，可随时撤回。已经发送的请求无法撤回。
        </p>
        <p role="status">{{ status.allowed ? '已同意使用外部 AI' : '当前使用本地演示回复' }}</p>
        <button
          v-if="!status.allowed"
          type="button"
          class="secondary"
          :disabled="busy"
          @click="update(true)"
        >
          同意发送并使用外部 AI
        </button>
      </template>
      <p v-else role="status">服务器当前使用本地演示回复。</p>
      <button
        v-if="status.has_consent"
        type="button"
        class="secondary"
        :disabled="busy"
        @click="update(false)"
      >
        撤回外部 AI 授权
      </button>
    </template>
  </section>
</template>
