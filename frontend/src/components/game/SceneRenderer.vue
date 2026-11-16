<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { GameSnapshot } from '../../types/game'
import { protectedImage } from '../../services/media'
const props = defineProps<{ snapshot: GameSnapshot; token?: string }>(),
  emit = defineEmits<{ focusDevice: [id: string] }>()
const images = ref<{ id: string; url: string; alt: string }[]>([]),
  failed = ref(false)
let generation = 0,
  controller: AbortController | null = null,
  disposals: (() => void)[] = []
function clear() {
  generation++
  controller?.abort()
  disposals.forEach((f) => f())
  disposals = []
  images.value = []
}
watch(
  () => [props.snapshot, props.token],
  async () => {
    clear()
    failed.value = false
    const current = generation
    controller = new AbortController()
    if (!props.token) return
    const refs = [
      props.snapshot.presentation.background,
      ...props.snapshot.presentation.cues.flatMap((c) => c.assets),
    ].filter((r) => r?.kind === 'image')
    for (const asset of new Map(refs.map((r) => [r!.asset_id, r!])).values()) {
      if (current !== generation) return
      try {
        const image = await protectedImage(
          props.token,
          props.snapshot.id,
          asset.asset_id,
          controller.signal,
        )
        if (current !== generation) {
          image.dispose()
          return
        }
        disposals.push(image.dispose)
        images.value.push({ id: asset.asset_id, url: image.url, alt: asset.alt_text })
      } catch {
        if (current === generation) failed.value = true
      }
    }
  },
  { immediate: true },
)
onBeforeUnmount(clear)
const angle = computed(() => {
  const v = props.snapshot.personal.devices.emitter?.angle
  return typeof v === 'number' ? v : 0
})
const power = computed(() =>
  Object.values(props.snapshot.personal.devices).some((d) => Object.values(d).includes(true)),
)
</script>
<template>
  <section
    class="scene-world"
    :class="[snapshot.script_id, snapshot.role, snapshot.scene_id, { energized: power }]"
    :aria-label="`角色 ${snapshot.role.toUpperCase()} · ${snapshot.scene_id}`"
  >
    <p class="scene-caption">原创 SVG/CSS 原型 · 非正式美术 · {{ snapshot.scene_id }}</p>
    <svg
      viewBox="0 0 800 430"
      role="img"
      :aria-label="`${snapshot.script_id} ${snapshot.role} 原型场景`"
    >
      <defs>
        <linearGradient id="sky" x2="0" y2="1">
          <stop stop-color="#102b46" />
          <stop offset="1" stop-color="#3e6576" />
        </linearGradient>
      </defs>
      <rect width="800" height="430" fill="url(#sky)" />
      <circle :cx="snapshot.role === 'a' ? 640 : 160" cy="75" r="35" fill="#e3bd7a" opacity=".7" />
      <path d="M0 285 Q190 235 390 285 T800 280 V430 H0Z" fill="#0d2537" />
      <template v-if="snapshot.script_id === 'lighthouse'">
        <path v-if="snapshot.role === 'a'" d="M290 340 L320 130 H410 L440 340Z" fill="#b0bec3" />
        <path v-else d="M215 335V210L365 140L515 210V335Z" fill="#69899b" />
        <rect x="310" y="105" width="115" height="35" rx="8" fill="#dfbd78" />
        <g
          v-if="snapshot.personal.devices.emitter"
          class="beam"
          :class="{ pulsed: snapshot.personal.devices.emitter?.pattern === 'pulse' }"
          :style="{ transform: `rotate(${angle}deg)` }"
        >
          <path d="M365 122L770 50V195Z" fill="#ffe0a0" opacity=".25" />
          <line x1="365" y1="122" x2="750" y2="122" stroke="#f8d68b" stroke-width="3" />
        </g>
        <path
          d="M0 360 Q100 340 200 360T400 360T600 360T800 360"
          fill="none"
          stroke="#6f9fae"
          stroke-width="4"
        />
      </template>
      <template v-else-if="snapshot.script_id === 'starline'">
        <path
          d="M30 425L360 260M770 425L440 260M125 425L380 260M675 425L420 260"
          stroke="#8faeba"
          stroke-width="8"
        />
        <path
          v-for="y in [290, 325, 370, 415]"
          :key="y"
          :d="`M${400 - (y - 240)} ${y}H${400 + (y - 240)}`"
          stroke="#bba27b"
          stroke-width="7"
        />
        <g :transform="snapshot.role === 'b' ? 'translate(155 0)' : 'translate(-80 0)'">
          <rect x="260" y="155" width="230" height="150" rx="20" fill="#597b90" />
          <rect x="280" y="180" width="80" height="60" fill="#acc6d1" />
          <circle cx="300" cy="300" r="18" fill="#152b3d" />
          <circle cx="450" cy="300" r="18" fill="#152b3d" />
        </g>
        <rect
          v-if="snapshot.personal.devices.echo_gate"
          :x="
            snapshot.personal.devices.echo_gate.position === 'east'
              ? 590
              : snapshot.personal.devices.echo_gate.position === 'west'
                ? 90
                : 340
          "
          y="95"
          width="70"
          height="80"
          fill="#c4b087"
          class="gate-panel"
        />
        <g
          v-if="snapshot.personal.devices.platform"
          class="rail-selector"
          :style="{
            transform: `rotate(${({ track_1: -15, track_2: 0, track_3: 15 } as Record<string, number>)[String(snapshot.personal.devices.platform.track)] ?? 0}deg)`,
          }"
        >
          <path d="M400 410V320" stroke="#e3bd7a" stroke-width="7" />
        </g>
      </template>
      <path class="circuit" d="M30 390H170V315H220" fill="none" stroke-width="5" />
      <circle class="power-lamp" cx="220" cy="315" r="11" />
    </svg>
    <div class="scene-hotspots">
      <button
        v-for="(fields, id) in snapshot.personal.devices"
        :key="id"
        class="device-hotspot"
        @click="emit('focusDevice', String(id))"
      >
        {{ id }}<span v-for="(value, key) in fields" :key="key">{{ key }}：{{ value }}</span>
      </button>
    </div>
    <p class="help">仅描绘本人获准设备；未提供的状态不推测。请以设备读数与观察文字为准。</p>
    <p v-if="failed" class="notice" role="status">
      图片暂不可用，仍可使用原型设备、观察文字与行动操作。
    </p>
    <figure v-for="image in images" :key="image.id">
      <img :src="image.url" :alt="image.alt" @error="failed = true" />
      <figcaption>{{ image.alt }}</figcaption>
    </figure>
  </section>
</template>
