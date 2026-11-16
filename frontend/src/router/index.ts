import { createRouter, createWebHistory } from 'vue-router'
import Identity from '../views/Identity.vue'
export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [{ path: '/', component: Identity }],
})
