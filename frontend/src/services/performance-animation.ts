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
    } else if (effect.id === 'echo-ready') {
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
    if (effect.id === 'beam-focus') {
      start(
        '[data-causal-part="beam-focus"]',
        [
          { filter: 'blur(9px)', opacity: 0.4 },
          { filter: 'blur(0px)', opacity: 1 },
        ],
        { duration: 1200, easing: 'ease-out' },
      )
      start(
        '[data-causal-part="beam-destination"]',
        [
          { filter: 'brightness(.6)' },
          { filter: 'brightness(1.6)', offset: 0.6 },
          { filter: 'brightness(1)' },
        ],
        { duration: 1400 },
      )
    }
    if (effect.id === 'clock-repaired') {
      start(
        '[data-causal-part="clock-mechanism"]',
        [
          { transform: 'rotate(-25deg)', opacity: 0.4 },
          { transform: 'rotate(20deg)', opacity: 1, offset: 0.7 },
          { transform: 'rotate(0deg)', opacity: 1 },
        ],
        { duration: 1400, easing: 'ease-out' },
      )
      start(
        '[data-causal-part="clock-feedback"]',
        [
          { filter: 'brightness(.6)' },
          { filter: 'brightness(1.4)', offset: 0.6 },
          { filter: 'brightness(1)' },
        ],
        { duration: 1200 },
      )
    }
    if (effect.id === 'route-ready') {
      start(
        '[data-causal-part="route-ready"]',
        [
          { strokeDasharray: '1', strokeDashoffset: '1', opacity: 0.3 },
          { strokeDasharray: '1', strokeDashoffset: '0', opacity: 1 },
        ],
        { duration: 1300, easing: 'ease-out' },
      )
    }
    if (effect.id === 'track-scan') {
      if (effect.role === 'b')
        start(
          '[data-causal-part="sonar-wave"]',
          [
            { transform: 'scale(.25)', opacity: 0.85 },
            { transform: 'scale(1.35)', opacity: 0 },
          ],
          { duration: 1200, easing: 'ease-out' },
        )
      start(
        '[data-causal-part="track-sweep"]',
        [
          { transform: 'translateX(-30px)', opacity: 0.65 },
          { transform: 'translateX(30px)', opacity: 0 },
        ],
        { duration: 1200, easing: 'ease-in-out' },
      )
      start(
        '[data-causal-part="track-result"]',
        [
          { opacity: 0, transform: 'translateY(8px)' },
          { opacity: 1, transform: 'translateY(0px)' },
        ],
        { duration: 1500, easing: 'ease-out' },
      )
    }
    if (effect.id === 'rail-connected') {
      start(
        '[data-causal-part="rail-connection"]',
        [
          { strokeDasharray: '1', strokeDashoffset: '1' },
          { strokeDasharray: '1', strokeDashoffset: '0' },
        ],
        { duration: 1400, easing: 'ease-out' },
      )
      start(
        '[data-causal-part="rail-joint"]',
        [{ opacity: 0 }, { opacity: 0.9, offset: 0.5 }, { opacity: 0 }],
        { duration: 1600 },
      )
    }
    if (effect.id === 'lighthouse-ending') {
      start(
        '[data-causal-part="lighthouse-ending"]',
        [
          { filter: 'brightness(.6)' },
          { filter: 'brightness(1.2)', offset: 0.7 },
          { filter: 'brightness(1)' },
        ],
        { duration: 3200, easing: 'ease-in-out' },
      )
      start(
        '[data-causal-part="ending-sea"]',
        [
          { opacity: 0.3, transform: 'translateY(7px)' },
          { opacity: 1, transform: 'translateY(0px)' },
        ],
        { duration: 2700, easing: 'ease-out' },
      )
      if (effect.ending === 'guide_now')
        start(
          '[data-causal-part="ending-beam"]',
          [
            { filter: 'blur(8px)', opacity: 0 },
            { filter: 'blur(0px)', opacity: 0.35 },
          ],
          { duration: 2600, easing: 'ease-out' },
        )
      else
        start('[data-causal-part="ending-tide"]', [{ opacity: 0 }, { opacity: 1 }], {
          duration: 2800,
          easing: 'ease-in',
        })
    }
    if (effect.id === 'starline-ending') {
      start(
        '[data-causal-part="ending-train-motion"]',
        [
          {
            transform:
              effect.ending === 'return_station'
                ? 'translate(-160px, 20px)'
                : 'translate(110px, -20px)',
          },
          { transform: 'translate(0px, 0px)' },
        ],
        { duration: 3000, easing: 'ease-in-out' },
      )
      start(
        '[data-causal-part="ending-platform"]',
        [
          { filter: 'brightness(.5)' },
          { filter: 'brightness(1.3)', offset: 0.7 },
          { filter: 'brightness(1)' },
        ],
        { duration: 3200, easing: 'ease-in-out' },
      )
      start('[data-causal-part="ending-rail"]', [{ opacity: 0.4 }, { opacity: 1 }], {
        duration: 2600,
        easing: 'ease-out',
      })
    }
    await Promise.all(finished)
  } finally {
    signal.removeEventListener('abort', cancel)
    cancel() // On partial failure too: never leave an overlay or animated style behind.
  }
}
