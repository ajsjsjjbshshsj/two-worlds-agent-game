import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'
import type { Pinia } from 'pinia'
import { useIdentityStore } from '../stores/identity'
import { usePairsStore } from '../stores/pairs'
import Identity from '../views/Identity.vue'
import Pairs from '../views/Pairs.vue'
import PairRoom from '../views/PairRoom.vue'
import Library from '../views/Library.vue'
import Game from '../views/Game.vue'
export function createAppRouter(
  history: RouterHistory = createWebHistory(import.meta.env.BASE_URL),
  pinia?: Pinia,
) {
  const router = createRouter({
    history,
    routes: [
      { path: '/', component: Identity },
      { path: '/pairs', component: Pairs, meta: { requiresAuth: true } },
      { path: '/pairs/:pairId', component: PairRoom, meta: { requiresAuth: true } },
      { path: '/pairs/:pairId/library', component: Library, meta: { requiresAuth: true } },
      { path: '/saves/:saveId', name: 'game', component: Game, meta: { requiresAuth: true } },
      { path: '/:pathMatch(.*)*', redirect: '/' },
    ],
  })
  router.beforeEach(async (to) => {
    if (to.hash.startsWith('#invite=')) {
      usePairsStore(pinia).captureInvite(to.hash)
      return { path: to.path, replace: true, hash: '', query: {} }
    }
    if (to.meta.requiresAuth) {
      const identity = useIdentityStore(pinia)
      await identity.initialize()
      if (!identity.authenticated && !identity.sessionSuspended) return '/'
    }
    return true
  })
  return router
}
