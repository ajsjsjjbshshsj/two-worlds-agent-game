import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { transformWithEsbuild, type Plugin } from 'vite'

const digest = (bytes: string | Uint8Array) => createHash('sha256').update(bytes).digest('base64')
const icons = [
  'pwa/icon-192.png',
  'pwa/icon-512.png',
  'pwa/maskable-512.png',
  'pwa/apple-touch-icon.png',
]

export function safePwa(): Plugin {
  let root: string, base: string
  return {
    name: 'twoworlds-safe-pwa',
    apply: 'build',
    enforce: 'post',
    configResolved(config) {
      root = config.root
      base = config.base
      if (
        !/^\/(?:[a-zA-Z0-9_-]+\/)*$/.test(base) ||
        base.split('/').some((p) => p === 'api' || p === 'ws')
      )
        throw new Error('PWA requires an explicit same-origin absolute deployment base')
    },
    transformIndexHtml() {
      return [
        {
          tag: 'link',
          attrs: { rel: 'manifest', href: base + 'manifest.webmanifest' },
          injectTo: 'head',
        },
      ]
    },
    async generateBundle(_options, bundle) {
      const manifest = JSON.stringify(
        {
          id: base,
          name: 'TwoWorlds',
          short_name: 'TwoWorlds',
          start_url: base,
          scope: base,
          display: 'standalone',
          theme_color: '#091725',
          background_color: '#091725',
          description: '两个人、两个世界。与搭档合作探索，在线确认并继续共同的故事。',
          lang: 'zh-CN',
          icons: [
            { src: base + icons[0], sizes: '192x192', type: 'image/png', purpose: 'any' },
            { src: base + icons[1], sizes: '512x512', type: 'image/png', purpose: 'any' },
            { src: base + icons[2], sizes: '512x512', type: 'image/png', purpose: 'maskable' },
          ],
        },
        null,
        2,
      )
      const offline = readFileSync(resolve(root, 'pwa/offline.html'), 'utf8').replaceAll(
        '__BASE__',
        base,
      )
      this.emitFile({ type: 'asset', fileName: 'manifest.webmanifest', source: manifest })
      this.emitFile({ type: 'asset', fileName: 'offline.html', source: offline })
      const files = new Map<string, string | Uint8Array>([
        ['manifest.webmanifest', manifest],
        ['offline.html', offline],
      ])
      for (const file of [...icons, 'pwa/offline.css', 'pwa/offline.js'])
        files.set(file, readFileSync(resolve(root, 'public', file)))
      for (const [file, asset] of Object.entries(bundle)) {
        if (/^assets\/[a-zA-Z0-9_-]+\.(?:js|css)$/.test(file))
          files.set(file, asset.type === 'chunk' ? asset.code : asset.source)
      }
      const resources = [...files]
        .sort(([a], [b]) => a.localeCompare(b, 'en'))
        .map(([path, source]) => ({ path, integrity: 'sha256-' + digest(source) }))
      const source = readFileSync(resolve(root, 'src/pwa/worker.ts'), 'utf8')
      const worker = await transformWithEsbuild(source, 'worker.ts', {
        target: 'es2022',
        format: 'iife',
        globalName: 'TwoWorldsWorker',
      })
      const version = digest(JSON.stringify(resources) + source)
        .replaceAll(/[+/=]/g, '')
        .slice(0, 24)
      const prefix = 'twoworlds-shell-' + digest(base).replaceAll(/[+/=]/g, '').slice(0, 8) + '-'
      this.emitFile({
        type: 'asset',
        fileName: 'sw.js',
        source: `${worker.code}\nconst config = ${JSON.stringify({ prefix, version, resources })};\nTwoWorldsWorker.attachWorker(self, config);\n`,
      })
    },
  }
}
