import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'
import { safePwa } from './pwa/build'

export default defineConfig({
  plugins: [vue(), safePwa()],
  test: {
    environment: 'jsdom',
    setupFiles: ['tests/setup.ts'],
    clearMocks: true,
    restoreMocks: true,
  },
})
