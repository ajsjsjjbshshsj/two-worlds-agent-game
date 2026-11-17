<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { GameSnapshot } from '../../types/game'
import { protectedImage } from '../../services/media'
import LighthouseScene from './LighthouseScene.vue'
import StarlineScene from './StarlineScene.vue'
const props = defineProps<{ snapshot: GameSnapshot; token?: string }>(),
  emit = defineEmits<{ focusDevice: [id: string] }>()
const images = ref<{ id: string; url: string; alt: string; layer: string | null }[]>([]),
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
    const background = props.snapshot.presentation.background
    const refs = [
      ...(background?.kind === 'image' ? [{ asset: background, layer: null }] : []),
      ...props.snapshot.presentation.cues.flatMap((cue) =>
        cue.assets
          .filter((asset) => asset.kind === 'image')
          .map((asset) => ({ asset, layer: cue.id })),
      ),
    ]
    // Fetch once per asset, preserving distinct background/cue placements.
    for (const asset of new Map(refs.map((r) => [r.asset.asset_id, r.asset])).values()) {
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
        for (const placement of refs.filter((r) => r.asset.asset_id === asset.asset_id))
          images.value.push({
            id: asset.asset_id,
            url: image.url,
            alt: placement.asset.alt_text,
            layer: placement.layer,
          })
      } catch {
        if (current === generation) failed.value = true
      }
    }
  },
  { immediate: true },
)
function imageFailed(id: string) {
  failed.value = true
  images.value = images.value.filter((image) => image.id !== id)
}
onBeforeUnmount(clear)
// Rendering receives effects, not partner devices, prose, conditions or puzzle rules.
const visual = computed(() =>
  Object.fromEntries((props.snapshot.presentation.visual_state ?? []).map((v) => [v.id, v.value])),
)
</script>
<template>
  <section
    class="scene-world"
    :class="[snapshot.script_id, snapshot.role, snapshot.scene_id]"
    :aria-label="`角色 ${snapshot.role.toUpperCase()} · ${snapshot.scene_id}`"
  >
    <p class="scene-caption">原创 SVG/CSS 原型 · 非正式美术 · {{ snapshot.scene_id }}</p>
    <div class="scene-stage" :data-stage="`${snapshot.script_id}-${snapshot.scene_id}`">
      <img
        v-for="image in images.filter((i) => i.layer === null)"
        :key="image.id"
        class="scene-background"
        :src="image.url"
        :alt="image.alt"
        @error="imageFailed(image.id)"
      />
      <svg
        viewBox="0 0 800 430"
        role="img"
        :aria-label="`${snapshot.script_id} ${snapshot.role} ${snapshot.scene_id} 原型场景`"
      >
        <rect class="prototype-sky" width="800" height="430" fill="#102b46" />
        <circle
          :cx="snapshot.role === 'a' ? 640 : 160"
          cy="75"
          r="35"
          fill="#e3bd7a"
          opacity=".7"
        />
        <path d="M0 285 Q190 235 390 285 T800 280 V430 H0Z" fill="#0d2537" />
        <LighthouseScene
          v-if="snapshot.script_id === 'lighthouse'"
          :stage="snapshot.scene_id"
          :role="snapshot.role"
          :visual="visual"
          :ending="snapshot.public.ending"
        />
        <StarlineScene
          v-else-if="snapshot.script_id === 'starline'"
          :stage="snapshot.scene_id"
          :role="snapshot.role"
          :visual="visual"
          :ending="snapshot.public.ending"
        />
        <g v-if="snapshot.scene_id === 'decision'" data-visual="joint-choice">
          <path
            d="M300 365L250 410M300 365L350 410M500 365L450 410M500 365L550 410"
            stroke="#e3bd7a"
            stroke-width="5"
          />
          <circle cx="300" cy="350" r="12" fill="#c7d9d9" />
          <circle cx="500" cy="350" r="12" fill="#c7d9d9" />
        </g>
        <g
          v-if="snapshot.scene_id === 'completed'"
          data-visual="ending"
          :data-ending="snapshot.public.ending"
        >
          <path d="M360 380l25 22 55-60" stroke="#91d4c5" stroke-width="9" fill="none" />
        </g>
      </svg>
      <img
        v-for="image in images.filter((i) => i.layer !== null)"
        :key="image.layer + image.id"
        class="scene-overlay"
        :data-cue="image.layer"
        :src="image.url"
        :alt="image.alt"
        @error="imageFailed(image.id)"
      />
    </div>
    <div v-if="!snapshot.completed" class="scene-hotspots">
      <button
        v-for="(fields, id) in snapshot.personal.devices"
        :key="id"
        class="device-hotspot"
        @click="emit('focusDevice', String(id))"
      >
        {{ id }}<span v-for="(value, key) in fields" :key="key">{{ key }}：{{ value }}</span>
      </button>
    </div>
    <p class="help">画面仅使用服务端确认的本人设备及授权视觉反馈；未知状态不推测。</p>
    <p v-if="failed" class="notice" role="status">
      图片暂不可用，仍可使用原型设备、观察文字与行动操作。
    </p>
  </section>
</template>
<style scoped>
.scene-stage {
  position: relative;
  isolation: isolate;
}
.scene-stage > svg {
  position: relative;
  z-index: 1;
}
.scene-background,
.scene-overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  max-height: none;
  pointer-events: none;
}
.scene-background {
  z-index: 0;
  object-fit: cover;
}
.scene-overlay {
  z-index: 2;
  object-fit: contain;
}
.scene-stage:has(.scene-background) .prototype-sky {
  opacity: 0.2;
}
</style>
