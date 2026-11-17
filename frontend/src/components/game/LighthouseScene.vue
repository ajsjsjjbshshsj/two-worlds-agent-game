<script setup lang="ts">
import { computed } from 'vue'
import type { Scalar } from '../../types/game'
const props = defineProps<{
  stage: string
  role: string
  visual: Record<string, Scalar>
  ending: string | null
}>()
const angle = computed(() =>
  typeof props.visual.emitter_angle === 'number' ? props.visual.emitter_angle : 0,
)
// Symbolic, already-authorized destinations map to drawing coordinates, not puzzle answers.
const point = computed(
  () =>
    (
      ({
        reef: [170, 330],
        inner_bay: [390, 320],
        observatory: [600, 180],
        outer_harbor: [700, 340],
      }) as Record<string, number[]>
    )[String(props.visual.beam_destination)],
)
</script>
<template>
  <g>
    <g v-if="stage === 'calibration'" data-visual="calibration-station">
      <path v-if="role === 'a'" d="M290 340L320 130H410L440 340Z" fill="#b0bec3" />
      <path v-else d="M215 335V210L365 140L515 210V335Z" fill="#69899b" />
      <rect x="310" y="105" width="115" height="35" rx="8" fill="#dfbd78" />
      <g
        v-if="role === 'a' && visual.emitter_angle !== undefined"
        class="beam"
        :class="{ pulsed: visual.emitter_pattern === 'pulse' }"
        :style="{ transform: `rotate(${angle}deg)` }"
        data-visual="emitter"
      >
        <path d="M365 122L770 50V195Z" fill="#ffe0a0" opacity=".25" /><line
          x1="365"
          y1="122"
          x2="750"
          y2="122"
          stroke="#f8d68b"
          stroke-width="3"
        /><path d="M365 122H410M365 122V145" stroke="white" stroke-width="4" />
      </g>
      <g
        v-if="role === 'b'"
        data-visual="received-beam"
        :data-quality="visual.beam_quality ?? 'unknown'"
        :data-destination="visual.beam_destination"
        :data-filter="visual.filter_tint"
      >
        <circle
          cx="365"
          cy="220"
          r="60"
          :fill="visual.filter_tint === 'amber' ? '#dfad55' : '#9fb8ce'"
          opacity=".4"
        />
        <line
          v-if="point"
          x1="365"
          y1="220"
          :x2="point[0]"
          :y2="point[1]"
          stroke="#ffe0a0"
          stroke-width="8"
        /><circle v-if="point" :cx="point[0]" :cy="point[1]" r="16" fill="#ffe0a0" />
        <path
          v-else
          d="M270 245q90-90 180 0"
          fill="none"
          stroke="#aaa"
          stroke-dasharray="4 14"
          stroke-width="10"
        />
      </g>
    </g>
    <g v-else-if="stage === 'repair'" data-visual="repair-workshop">
      <rect x="145" y="105" width="380" height="245" rx="15" fill="#526d7b" />
      <g
        data-visual="clock"
        :data-powered="visual.clock_powered"
        :data-repaired="visual.clock_repaired"
      >
        <circle
          data-causal-part="clock-feedback"
          cx="330"
          cy="220"
          r="80"
          fill="#142a3b"
          stroke="#c5ab79"
          stroke-width="10"
        />
        <g class="clock-hands" :class="{ running: visual.clock_repaired === true }"
          ><path
            d="M330 155V220L375 245"
            fill="none"
            :stroke="visual.clock_repaired ? '#f8df9f' : '#70818b'"
            stroke-width="8"
        /></g>
        <path
          v-if="role === 'a'"
          data-causal-part="clock-circuit"
          pathLength="1"
          d="M75 340H160V290H220"
          fill="none"
          :stroke="visual.clock_powered ? '#f6cf72' : '#465b6d'"
          stroke-width="8"
        /><circle
          v-if="role === 'a'"
          cx="220"
          cy="290"
          r="12"
          :fill="visual.clock_powered ? '#ffde8a' : '#465b6d'"
        />
      </g>
      <g
        v-if="role === 'b'"
        data-visual="power-router"
        :data-target="visual.power_target"
        :data-ready="visual.route_ready"
      >
        <path
          d="M610 220V115M610 220L720 300M610 220L540 330"
          fill="none"
          stroke="#65899a"
          stroke-width="5"
        />
        <circle
          v-for="(target, index) in ['tower', 'shore', 'observatory']"
          :key="target"
          :cx="[610, 720, 540][index]"
          :cy="[115, 300, 330][index]"
          r="18"
          :fill="visual.power_target === target ? '#ffe0a0' : '#394f61'"
        />
        <path
          v-if="visual.route_ready"
          d="M570 205l25 25 50-60"
          fill="none"
          stroke="#91d4c5"
          stroke-width="10"
        />
      </g>
      <rect
        v-if="visual.signal_locked"
        x="95"
        y="120"
        width="20"
        height="60"
        rx="10"
        fill="#91d4c5"
        data-visual="stable-signal"
      />
    </g>
    <g v-else-if="stage === 'decision' || stage === 'completed'" data-visual="restored-lighthouse">
      <path d="M330 340L355 110H425L450 340Z" fill="#c0cbc8" /><circle
        cx="390"
        cy="120"
        r="35"
        fill="#ffe0a0"
      />
      <path
        v-if="stage === 'decision' || ending === 'guide_now'"
        d="M390 120L80 270M390 120L730 260"
        stroke="#f6cf72"
        stroke-width="24"
        opacity=".35"
      />
      <g v-else data-visual="waiting-tide"
        ><path
          d="M40 350q100-45 200 0t200 0t200 0"
          stroke="#98d2d9"
          fill="none"
          stroke-width="8" /><circle
          cx="650"
          cy="180"
          r="50"
          stroke="#e3bd7a"
          fill="none"
          stroke-width="3"
      /></g>
    </g>
    <path
      d="M0 370Q100 350 200 370T400 370T600 370T800 370"
      fill="none"
      stroke="#6f9fae"
      stroke-width="4"
    />
  </g>
</template>
<style scoped>
.clock-hands {
  transform-origin: 330px 220px;
}
.clock-hands.running {
  animation: clock-turn 8s linear infinite;
}
@keyframes clock-turn {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .clock-hands.running {
    animation: none;
  }
}
</style>
