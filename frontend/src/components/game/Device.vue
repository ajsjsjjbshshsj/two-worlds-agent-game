<script setup lang="ts">
import type { Scalar } from '../../types/game'
defineProps<{ id: string; fields: Record<string, Scalar> }>()
</script>
<template>
  <article :id="'device-' + id" tabindex="-1" class="confirmed-device">
    <h3>{{ id }}</h3>
    <div class="device-dials">
      <div v-for="(value, key) in fields" :key="key" class="device-reading">
        <span
          v-if="typeof value === 'boolean'"
          class="reading-light"
          :class="{ lit: value }"
          aria-hidden="true"
        ></span
        ><svg v-else-if="typeof value === 'number'" viewBox="0 0 60 60" aria-hidden="true">
          <circle cx="30" cy="30" r="24" fill="none" stroke="currentColor" />
          <path
            d="M30 30V10"
            stroke="currentColor"
            stroke-width="3"
            :style="{
              transform: `rotate(${value}deg)`,
              transformOrigin: '30px 30px',
              transition: 'transform .6s',
            }"
          /></svg
        ><strong>{{ key }}</strong
        ><span>{{ value }}</span>
      </div>
    </div>
  </article>
</template>
