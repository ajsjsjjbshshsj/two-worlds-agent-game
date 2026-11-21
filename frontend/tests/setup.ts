import { IDBFactory } from 'fake-indexeddb'
import { beforeEach } from 'vitest'

beforeEach(() => {
  Object.defineProperty(globalThis, 'indexedDB', {
    configurable: true,
    writable: true,
    value: new IDBFactory(),
  })
})
