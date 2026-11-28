<script setup lang="ts">
// Build-time flag exists only in the isolated local Demo image. It labels the
// synthetic bundle; it never changes API permissions or publication approval.
const visible = import.meta.env.VITE_DEMO_MODE === 'true'
</script>

<template>
  <div v-if="visible" class="local-demo-banner" role="note" data-test="local-demo-banner">
    本地试玩版 · 合成占位素材 · 非正式发布内容
  </div>
</template>

<style scoped>
.local-demo-banner {
  padding: 8px 16px;
  background: #3b2c16;
  color: #ffe2a8;
  border-bottom: 1px solid #80602f;
  font-size: 13px;
  line-height: 1.5;
  text-align: center;
  letter-spacing: 0.02em;
}
</style>
