import type { Performance } from './causal-performance'

// Temporary Web Animations never commit styles: Vue's confirmed SVG is always
// the authoritative final image, including after cancellation or animation errors.
export async function animatePerformance(
  root: SVGSVGElement,
  effect: Performance,
  signal: AbortSignal,
) {
  if (signal.aborted) return
  const animations: Animation[] = []
  const finished: Promise<Animation>[] = []
  const cancel = () => animations.forEach((a) => a.cancel())
  signal.addEventListener('abort', cancel, { once: true })
  try {
    const start = (selector: string, frames: Keyframe[], options: KeyframeAnimationOptions) => {
      const targets = root.querySelectorAll(selector)
      if (!targets.length) throw new Error('Performance target unavailable')
      targets.forEach((target, index) => {
        if (signal.aborted) return
        const animation = target.animate(frames, { ...options, delay: index * 140, fill: 'none' })
        animations.push(animation)
        const completion = animation.finished
        void completion.catch(() => {}) // A later target may fail before Promise.all below.
        finished.push(completion)
      })
    }
    if (effect.id === 'clock-power-on') {
      start(
        '[data-causal-part="clock-circuit"]',
        [
          { strokeDasharray: '1', strokeDashoffset: '1', stroke: '#465b6d' },
          { strokeDasharray: '1', strokeDashoffset: '0', stroke: '#f6cf72' },
        ],
        { duration: 1000, easing: 'ease-out' },
      )
      start(
        '[data-causal-part="clock-feedback"]',
        [
          { filter: 'brightness(.55)' },
          { filter: 'brightness(1.4)', offset: 0.65 },
          { filter: 'brightness(1)' },
        ],
        { duration: 1100, easing: 'ease-out' },
      )
    } else {
      start(
        '[data-causal-part="sonar-wave"]',
        [
          { transform: 'scale(.25)', opacity: 0.85 },
          { transform: 'scale(1.35)', opacity: 0 },
        ],
        { duration: 1200, easing: 'ease-out' },
      )
      start('[data-causal-part="sonar-core"]', [{ opacity: 0.3 }, { opacity: 1 }], {
        duration: 900,
        easing: 'ease-out',
      })
    }
    await Promise.all(finished)
  } finally {
    signal.removeEventListener('abort', cancel)
    cancel() // On partial failure too: never leave an overlay or animated style behind.
  }
}
