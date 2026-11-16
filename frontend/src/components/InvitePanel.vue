<script setup lang="ts">
import { computed, ref } from 'vue'
import { usePairsStore } from '../stores/pairs'
const props = defineProps<{ pairId: string }>(),
  pairs = usePairsStore(),
  copyStatus = ref('')
const invitation = computed(() => (pairs.invitation?.id === props.pairId ? pairs.invitation : null))
const link = computed(() =>
  invitation.value
    ? `${window.location.origin}${import.meta.env.BASE_URL}#invite=${invitation.value.invite_token}`
    : '',
)
async function copy() {
  try {
    await navigator.clipboard.writeText(link.value)
    copyStatus.value = '邀请链接已复制。请仅交给你想邀请的搭档。'
  } catch {
    copyStatus.value = '无法自动复制，请手动选择下方链接。'
  }
}
async function refresh() {
  copyStatus.value = ''
  await pairs.refresh(props.pairId)
}
</script>
<template>
  <section class="resource-panel" aria-label="邀请搭档">
    <p class="eyebrow">交给另一个世界的入口</p>
    <h2>邀请搭档</h2>
    <template v-if="invitation"
      ><label for="invite-link">邀请链接（请勿公开）</label
      ><textarea
        id="invite-link"
        data-test="invite-link"
        :value="link"
        readonly
        rows="3"
        spellcheck="false"
      ></textarea>
      <p class="help">
        有效期至 {{ invitation.invite_expires_at }}。是否仍可加入以服务端验证为准。
      </p>
      <button class="primary" data-test="copy-invite" @click="copy">复制邀请链接</button></template
    >
    <p v-else class="help">
      邀请只在生成它的页面会话中暂存，刷新后无法找回原链接。可以重新生成，旧邀请会立即失效。
    </p>
    <button class="secondary" data-test="refresh-invite" :disabled="pairs.busy" @click="refresh">
      {{ pairs.busy ? '正在生成…' : invitation ? '刷新邀请，替换旧链接' : '生成新的邀请' }}
    </button>
    <p v-if="copyStatus" role="status">{{ copyStatus }}</p>
  </section>
</template>
