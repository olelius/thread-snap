/**
 * 基于 React Bits CountUp 的 Motion 数值驱动思路适配项目统计语义。
 * Copyright (c) 2026 David Haz；许可及来源见 /third-party/react-bits.txt。
 */
import { useEffect, useRef } from 'react'
import { animate, useInView, useReducedMotion } from 'motion/react'

/** 首次可见且取得真实数字时短计数；后续刷新直接更新，不重复从零播放。 */
export function CountUp({ value }: { value?: number }) {
  const ref = useRef<HTMLSpanElement>(null)
  const started = useRef(false)
  const inView = useInView(ref)
  const reduceMotion = useReducedMotion()
  const known = value !== undefined && Number.isFinite(value)
  const finalText = known ? String(value) : '—'

  useEffect(() => {
    const node = ref.current
    if (!node) return
    const write = (text: string) => { if (node.textContent !== text) node.textContent = text }
    write(finalText)
    if (!known || value === undefined) return
    if (started.current || reduceMotion || value === 0 || document.hidden) {
      started.current = true
      return
    }
    if (!inView) return

    let playback: ReturnType<typeof animate> | undefined
    // 延后一帧再标记开始，React StrictMode 的试运行清理不会吞掉首次动画。
    const frame = requestAnimationFrame(() => {
      started.current = true
      node.dataset.countAnimating = 'true'
      playback = animate(0, value, {
        duration: .65, ease: 'easeOut',
        onUpdate: (latest) => write(String(Math.round(latest))),
        onComplete: () => { write(finalText); node.dataset.countAnimating = 'false' },
      })
    })
    const finish = () => {
      cancelAnimationFrame(frame)
      playback?.stop()
      write(finalText)
      node.dataset.countAnimating = 'false'
    }
    const visibility = () => { if (document.hidden) finish() }
    document.addEventListener('visibilitychange', visibility)
    return () => { finish(); document.removeEventListener('visibilitychange', visibility) }
  }, [finalText, inView, known, reduceMotion, value])

  // 辅助技术始终读取真实值，不播报动画经过的中间数；预留末值宽度避免布局跳动。
  return <span className='bits-count' style={{ minWidth: `${finalText.length}ch` }}>
    <span className='sr-only'>{finalText}</span>
    <span ref={ref} data-count-value aria-hidden='true'>{finalText}</span>
  </span>
}
