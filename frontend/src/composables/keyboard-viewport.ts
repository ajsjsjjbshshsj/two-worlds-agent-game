import { onMounted, onBeforeUnmount } from 'vue'

// Browsers with a floating keyboard report its usable area through VisualViewport.
// Keep native focus/scroll behavior unless the focused form field is actually hidden.
export function useKeyboardViewport() {
  let frame = 0
  const viewport = window.visualViewport
  function reveal() {
    cancelAnimationFrame(frame)
    frame = requestAnimationFrame(() => {
      const field = document.activeElement
      if (!(field instanceof HTMLElement) || !field.matches('input, textarea, select')) return
      const top = viewport?.offsetTop ?? 0
      const bottom = top + (viewport?.height ?? window.innerHeight)
      const rect = field.getBoundingClientRect()
      if (rect.top < top + 12 || rect.bottom > bottom - 12)
        field.scrollIntoView({ block: 'center', behavior: 'instant' })
    })
  }
  onMounted(() => {
    document.addEventListener('focusin', reveal)
    viewport?.addEventListener('resize', reveal)
  })
  onBeforeUnmount(() => {
    cancelAnimationFrame(frame)
    document.removeEventListener('focusin', reveal)
    viewport?.removeEventListener('resize', reveal)
  })
}
