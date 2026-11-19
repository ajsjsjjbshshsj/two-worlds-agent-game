import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { createAppRouter } from './router'
import { clearLegacyIdentityStorage } from './services/legacy-identity-storage'
import { useIdentityStore } from './stores/identity'
import { usePairsStore } from './stores/pairs'
import './styles/main.css'
clearLegacyIdentityStorage()
const pinia = createPinia()
useIdentityStore(pinia).enableSessionSync()
// Remove capabilities from the browser URL before Vue Router observes it.
usePairsStore(pinia).captureInvite()
const router = createAppRouter(undefined, pinia)
createApp(App).use(pinia).use(router).mount('#app')
