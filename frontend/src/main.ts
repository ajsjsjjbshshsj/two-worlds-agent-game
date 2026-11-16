import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { createAppRouter } from './router'
import { usePairsStore } from './stores/pairs'
import './styles/main.css'
const pinia = createPinia()
// Remove capabilities from the browser URL before Vue Router observes it.
usePairsStore(pinia).captureInvite()
const router = createAppRouter(undefined, pinia)
createApp(App).use(pinia).use(router).mount('#app')
