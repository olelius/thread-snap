/** 生成 UUID v4，兼容普通 HTTP 页面未开放 randomUUID 的浏览器。 */
export function createUuid(): string {
  const browserCrypto = globalThis.crypto
  if (typeof browserCrypto?.randomUUID === 'function') return browserCrypto.randomUUID()
  if (typeof browserCrypto?.getRandomValues !== 'function') {
    throw new Error('浏览器缺少随机数生成能力，请使用新版浏览器。')
  }

  const bytes = browserCrypto.getRandomValues(new Uint8Array(16))
  // RFC 9562：固定版本为 4，变体高两位为 10，其余位保留随机值。
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
