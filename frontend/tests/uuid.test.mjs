import assert from 'node:assert/strict'
import { webcrypto } from 'node:crypto'
import test from 'node:test'
import { createUuid } from '../src/lib/uuid.ts'

const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

function useCrypto(t, value) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value })
  t.after(() => {
    if (descriptor) Object.defineProperty(globalThis, 'crypto', descriptor)
    else delete globalThis.crypto
  })
}

test('优先使用原生 UUID 并保持 Crypto 方法接收者', (t) => {
  const expected = '12345678-1234-4123-8123-123456789abc'
  const crypto = {
    randomUUID() { assert.equal(this, crypto); return expected },
    getRandomValues() { assert.fail('原生 UUID 可用时不进入回退') },
  }
  useCrypto(t, crypto)
  assert.equal(createUuid(), expected)
  assert.match(createUuid(), uuidV4)
})

test('普通 HTTP 回退生成 1000 个格式正确且互不重复的 UUID v4', (t) => {
  useCrypto(t, { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) })
  const values = Array.from({ length: 1000 }, () => createUuid())
  values.forEach((value) => assert.match(value, uuidV4))
  assert.equal(new Set(values).size, values.length)
})

test('回退正确设置版本和变体位，不依赖随机字节原始值', (t) => {
  let fill = 0
  const crypto = { getRandomValues(bytes) { assert.equal(this, crypto); return bytes.fill(fill) } }
  useCrypto(t, crypto)
  assert.equal(createUuid(), '00000000-0000-4000-8000-000000000000')
  fill = 255
  assert.equal(createUuid(), 'ffffffff-ffff-4fff-bfff-ffffffffffff')
})

test('缺少 Crypto 或随机数 API 时明确报错，不生成弱随机编号', (t) => {
  useCrypto(t, undefined)
  assert.throws(createUuid, /浏览器缺少随机数生成能力/)
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: {} })
  assert.throws(createUuid, /浏览器缺少随机数生成能力/)
})
