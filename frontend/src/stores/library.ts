import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { useIdentityStore } from './identity'
import { usePairsStore } from './pairs'
import { libraryApi } from '../services/library'
import { ApiError } from '../services/http'
import {
  invalidResponse,
  type ScriptMetadata,
  type SaveEntry,
  type SaveSummary,
} from '../types/resources'

export const useLibraryStore = defineStore('library', () => {
  const identity = useIdentityStore(),
    pairs = usePairsStore()
  const pairId = ref<string | null>(null),
    scripts = ref<ScriptMetadata[]>([]),
    saves = ref<SaveSummary[]>([]),
    entry = ref<SaveEntry | null>(null)
  const loading = ref(false),
    busy = ref(false),
    error = ref<{ code: string; message: string } | null>(null)
  let epoch = 0,
    reading = 0
  function reset() {
    epoch++
    reading++
    pairId.value = null
    scripts.value = []
    saves.value = []
    entry.value = null
    loading.value = false
    busy.value = false
    error.value = null
  }
  watch(() => identity.sessionGeneration, reset, { flush: 'sync' })
  function fail(cause: unknown) {
    const problem = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', true)
    if (problem.status === 401) identity.expireSession()
    error.value = { code: problem.code, message: problem.message }
  }
  async function load(id: string) {
    reset()
    pairId.value = id
    if (!identity.authenticated) return
    const current = epoch
    loading.value = true
    try {
      const [catalog, progress] = await Promise.all([libraryApi.catalog(), libraryApi.saves(id)])
      if (current !== epoch) return
      if (
        progress.some((s) => s.pair_id !== id) ||
        new Set(progress.map((s) => s.script_id)).size !== progress.length
      )
        invalidResponse()
      const latest = new Map<string, ScriptMetadata>()
      for (const metadata of catalog) {
        const previous = latest.get(metadata.id)
        if (!previous || newerVersion(metadata.content_version, previous.content_version))
          latest.set(metadata.id, metadata)
      }
      scripts.value = [...latest.values()].sort((a, b) => a.id.localeCompare(b.id))
      saves.value = progress
    } catch (cause) {
      if (current === epoch) fail(cause)
    } finally {
      if (current === epoch) loading.value = false
    }
  }
  async function open(scriptId: string) {
    const id = pairId.value
    if (!identity.authenticated || !id || busy.value || loading.value) return null
    const old = saves.value.find((s) => s.script_id === scriptId),
      metadata = scripts.value.find((s) => s.id === scriptId)
    if (!old && pairs.pairs.find((p) => p.id === id)?.member_count !== 2) {
      fail(new ApiError(422, 'PAIR_NOT_READY', false))
      return null
    }
    if (!old && !metadata) return null
    const current = epoch
    busy.value = true
    error.value = null
    entry.value = null
    try {
      const result = old
        ? await libraryApi.read(old.id)
        : await libraryApi.create(id, scriptId, metadata!.content_version)
      if (current !== epoch) return null
      if (
        result.pair_id !== id ||
        result.script_id !== scriptId ||
        (!old && result.script_version !== metadata!.content_version) ||
        (old &&
          (result.id !== old.id ||
            result.script_version !== old.script_version ||
            result.version < old.version))
      )
        invalidResponse()
      entry.value = result
      return result.id
    } catch (cause) {
      if (current === epoch) fail(cause)
      return null
    } finally {
      if (current === epoch) busy.value = false
    }
  }
  async function read(id: string) {
    if (!identity.authenticated) return
    const current = ++reading,
      context = epoch
    entry.value = null
    loading.value = true
    error.value = null
    try {
      const result = await libraryApi.read(id)
      if (current === reading && context === epoch) {
        if (result.id !== id) invalidResponse()
        entry.value = result
      }
    } catch (cause) {
      if (current === reading && context === epoch) fail(cause)
    } finally {
      if (current === reading && context === epoch) loading.value = false
    }
  }
  return {
    pairId,
    scripts,
    saves,
    entry,
    loading,
    busy,
    error,
    load,
    open,
    read,
    cards: computed(() =>
      scripts.value.map((metadata) => ({
        script: metadata,
        save:
          saves.value.find((s) => s.pair_id === pairId.value && s.script_id === metadata.id) ??
          null,
      })),
    ),
    reset,
  }
})

function newerVersion(candidate: string, current: string): boolean {
  const left = candidate.split('.'),
    right = current.split('.')
  for (let index = 0; index < 3; index++) {
    const a = left[index]!,
      b = right[index]!
    if (a !== b) return a.length !== b.length ? a.length > b.length : a > b
  }
  return false
}
