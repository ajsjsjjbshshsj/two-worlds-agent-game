<script setup lang="ts">
import { reactive, watch } from 'vue'
import { validParameter, type Action, type Scalar } from '../../types/game'
const props = defineProps<{ actions: Action[]; disabled: boolean }>(),
  emit = defineEmits<{ command: [id: string, args: Record<string, unknown>] }>()
const drafts = reactive<Record<string, Record<string, Scalar>>>({})
const names: Record<string, string> = {
  inspect: '检查物件',
  set_emitter: '调节发射器',
  set_filter: '切换滤镜',
  lock_signal: '锁定信号',
  route_power: '调整供电',
  repair_clock: '维修时钟',
  confirm_route: '确认航道',
  set_echo_gate: '调整回声闸',
  allocate_power: '分配设备能源',
  scan_track: '扫描轨道',
  install_rail: '安装导轨',
  confirm_signal: '确认信号',
  set_platform: '选择接车轨道',
  dispatch_train: '启动接车',
  vote_ending: '共同决定',
  share_clue: '分享已发现线索',
}
watch(
  () => props.actions,
  (actions) => {
    for (const key of Object.keys(drafts)) delete drafts[key]
    for (const a of actions)
      drafts[a.id] = Object.fromEntries(
        a.parameters.map((p) => [
          p.id,
          p.choices[0] ??
            (p.value_type === 'boolean' ? false : p.value_type === 'integer' ? 0 : ''),
        ]),
      )
  },
  { immediate: true },
)
function send(a: Action) {
  const args = drafts[a.id]!
  if (!props.disabled && a.parameters.every((p) => validParameter(p, args[p.id])))
    emit('command', a.id, { ...args })
}
</script>
<template>
  <section class="resource-panel" aria-label="当前可用行动">
    <h2>我能做什么</h2>
    <p class="help">行动和参数由当前角色快照提供；点击后等待服务端确认。</p>
    <p v-if="!actions.length">当前没有可提交的行动，请与搭档交流或刷新进度。</p>
    <form
      v-for="a in actions"
      :key="a.id"
      class="game-action"
      :data-kind="a.kind"
      :data-action="a.id"
      @submit.prevent="send(a)"
    >
      <h3>{{ names[a.kind] ?? a.kind }}</h3>
      <label v-for="p in a.parameters" :key="p.id"
        >{{ p.id
        }}<select
          v-if="p.choices.length"
          :name="p.id"
          :disabled="disabled"
          :value="p.choices.indexOf(drafts[a.id]![p.id]!)"
          @change="
            drafts[a.id]![p.id] = p.choices[Number(($event.target as HTMLSelectElement).value)]!
          "
        >
          <option v-for="(choice, index) in p.choices" :key="index" :value="index">
            {{ choice }}
          </option></select
        ><input
          v-else-if="p.value_type === 'boolean'"
          v-model="drafts[a.id]![p.id]"
          :name="p.id"
          type="checkbox"
          :disabled="disabled" /><input
          v-else-if="p.value_type === 'integer'"
          v-model.number="drafts[a.id]![p.id]"
          :name="p.id"
          type="number"
          step="1"
          :disabled="disabled" /><input
          v-else
          v-model="drafts[a.id]![p.id]"
          :name="p.id"
          :maxlength="p.max_length ?? undefined"
          :disabled="disabled" /></label
      ><button
        class="secondary"
        type="submit"
        :disabled="disabled || !a.parameters.every((p) => validParameter(p, drafts[a.id]?.[p.id]))"
      >
        确认 {{ names[a.kind] ?? a.kind }}
      </button>
    </form>
  </section>
</template>
