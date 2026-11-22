export interface InstallPrompt extends Event {
  prompt(): Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

export async function registerPwa(onWaiting: () => void) {
  if (!import.meta.env.PROD || !window.isSecureContext || !('serviceWorker' in navigator))
    return null
  const registration = await navigator.serviceWorker.register(import.meta.env.BASE_URL + 'sw.js', {
    scope: import.meta.env.BASE_URL,
    updateViaCache: 'none',
  })
  if (registration.waiting) onWaiting()
  registration.addEventListener('updatefound', () => {
    const worker = registration.installing
    worker?.addEventListener('statechange', () => {
      if (worker.state === 'installed' && navigator.serviceWorker.controller) onWaiting()
    })
  })
  // No controllerchange reload or skipWaiting message: users close all windows
  // after resolving commands; IndexedDB stays owned by the existing game service.
  return registration
}
