<script setup lang="ts">
import type { Scalar } from '../../types/game'
defineProps<{
  stage: string
  role: string
  visual: Record<string, Scalar>
  ending: string | null
}>()
</script>
<template>
  <g>
    <path d="M30 425L360 260M770 425L440 260" stroke="#8faeba" stroke-width="8" />
    <g v-if="stage === 'survey'" data-visual="survey-gap">
      <path d="M200 375H600" stroke="#102b46" stroke-width="45" />
      <rect
        v-if="role === 'a' && visual.gate_position !== undefined"
        :x="visual.gate_position === 'east' ? 610 : visual.gate_position === 'west' ? 90 : 350"
        y="100"
        width="70"
        height="90"
        fill="#c4b087"
        class="gate-panel"
        data-visual="gate"
        :data-position="visual.gate_position"
      />
      <g v-else data-visual="sonar" :data-available="visual.echo_available"
        ><circle
          v-for="r in [35, 65, 95]"
          :key="r"
          cx="390"
          cy="165"
          :r="r"
          fill="none"
          :stroke="visual.echo_available ? '#91d4c5' : '#455e72'"
          stroke-width="4"
      /></g>
      <g v-if="visual.scanned_segment" data-visual="scan-result"
        ><path
          d="M290 340H510V390H290Z"
          fill="none"
          stroke="#e3bd7a"
          stroke-dasharray="8"
          stroke-width="5"
        /><text x="310" y="370" fill="#ffe0a0">{{ visual.scanned_segment }}</text></g
      >
    </g>
    <g v-if="visual.rail_connected" data-visual="connected-rail"
      ><path d="M190 375H610M240 350H560" stroke="#e3bd7a" stroke-width="9" /><path
        v-for="x in [250, 310, 370, 430, 490, 550]"
        :key="x"
        :d="`M${x} 340V385`"
        stroke="#bba27b"
        stroke-width="7"
    /></g>
    <g v-if="stage === 'boarding'" data-visual="boarding-signal">
      <path d="M650 130V320" stroke="#76929f" stroke-width="9" /><circle
        cx="650"
        cy="155"
        r="25"
        :fill="visual.signal_confirmed ? '#9ccfea' : '#465b6d'"
        data-visual="confirmed-signal"
        :data-confirmed="visual.signal_confirmed"
      />
      <g
        v-if="
          role === 'a' && visual.platform_track !== undefined && visual.platform_track !== 'unset'
        "
        class="rail-selector"
        :style="{
          transform: `rotate(${({ track_1: -15, track_2: 0, track_3: 15 } as Record<string, number>)[String(visual.platform_track)] ?? 0}deg)`,
        }"
        data-visual="platform"
        :data-track="visual.platform_track"
        ><path d="M400 410V320" stroke="#e3bd7a" stroke-width="7"
      /></g>
    </g>
    <g
      data-visual="train"
      :data-arrived="visual.train_arrived"
      :transform="
        stage === 'completed' && ending === 'return_station'
          ? 'translate(220 -40) scale(.8)'
          : visual.train_arrived
            ? 'translate(-40 50)'
            : 'translate(60 -35)'
      "
    >
      <rect x="250" y="160" width="240" height="145" rx="20" fill="#597b90" /><rect
        x="270"
        y="180"
        width="80"
        height="60"
        fill="#acc6d1"
      /><rect x="380" y="180" width="85" height="60" fill="#acc6d1" /><circle
        cx="290"
        cy="300"
        r="18"
        fill="#152b3d"
      /><circle cx="450" cy="300" r="18" fill="#152b3d" />
    </g>
    <g
      v-if="role === 'b' && (stage === 'survey' || stage === 'boarding')"
      data-visual="power-panel"
    >
      <g
        v-for="(device, index) in ['engine', 'sonar', 'lamp']"
        :key="device"
        :data-device="device"
        :data-on="visual[device + '_on']"
        ><circle
          :cx="110 + index * 95"
          cy="80"
          r="16"
          :fill="visual[device + '_on'] === true ? '#ffe0a0' : '#394f61'"
        /><text :x="80 + index * 95" y="120" fill="#dbe7ee" font-size="16">{{ device }}</text></g
      >
    </g>
    <g v-if="stage === 'decision' || stage === 'completed'" data-visual="arrival-platform"
      ><path d="M60 340H740V390H60Z" fill="#5e7d88" /><path
        d="M60 340H740"
        stroke="#e3bd7a"
        stroke-width="7"
    /></g>
  </g>
</template>
