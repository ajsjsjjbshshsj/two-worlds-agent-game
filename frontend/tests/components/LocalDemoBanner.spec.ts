import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import LocalDemoBanner from '../../src/components/LocalDemoBanner.vue'

afterEach(() => vi.unstubAllEnvs())

describe('LocalDemoBanner', () => {
  it('labels synthetic local demo content when the build flag is enabled', () => {
    vi.stubEnv('VITE_DEMO_MODE', 'true')
    const wrapper = mount(LocalDemoBanner)
    expect(wrapper.get('[data-test="local-demo-banner"]').text()).toBe(
      '本地试玩版 · 合成占位素材 · 非正式发布内容',
    )
  })

  it('does not label normal production builds', () => {
    vi.stubEnv('VITE_DEMO_MODE', 'false')
    const wrapper = mount(LocalDemoBanner)
    expect(wrapper.find('[data-test="local-demo-banner"]').exists()).toBe(false)
  })
})
