/**
 * 改编自 React Bits SpotlightCard，Copyright (c) 2026 David Haz。
 * 来源版本与完整 MIT + Commons Clause 许可见 /third-party/react-bits.txt。
 */
import { useRef, type FocusEvent, type PointerEvent, type ReactNode, type RefObject } from 'react'
import { useReducedMotion } from 'motion/react'
import { cn } from '@/lib/utils'
import './react-bits.css'

type SpotlightCardProps = {
  children: ReactNode
  className?: string
  disabled?: boolean
  ref?: RefObject<HTMLDivElement | null>
  'data-playing'?: boolean
}

/** 局部指针光晕：仅在交互时更新CSS变量，不重渲染子树、不创建常驻动画循环。 */
export function SpotlightCard({ children, className, disabled = false, ref: outerRef, 'data-playing': playing }: SpotlightCardProps) {
  const ownRef = useRef<HTMLDivElement>(null)
  const ref = outerRef ?? ownRef
  const reduceMotion = useReducedMotion()
  const focused = useRef(false)
  const enabled = !disabled && !reduceMotion

  function move(event: PointerEvent<HTMLDivElement>) {
    if (!enabled || event.pointerType !== 'mouse' || !window.matchMedia('(hover: hover) and (pointer: fine)').matches) return
    const node = event.currentTarget
    const rect = node.getBoundingClientRect()
    node.style.setProperty('--spotlight-x', `${event.clientX - rect.left}px`)
    node.style.setProperty('--spotlight-y', `${event.clientY - rect.top}px`)
    node.dataset.spotlightActive = 'true'
  }

  function focus(event: FocusEvent<HTMLDivElement>) {
    if (!enabled || !(event.target instanceof HTMLElement) || !event.target.matches(':focus-visible')) return
    focused.current = true
    event.currentTarget.style.setProperty('--spotlight-x', '50%')
    event.currentTarget.style.setProperty('--spotlight-y', '50%')
    event.currentTarget.dataset.spotlightActive = 'true'
  }

  return <div ref={ref} className={cn('bits-spotlight', className)} data-spotlight-enabled={enabled} data-playing={playing}
    onPointerMove={move}
    onPointerLeave={(event) => { if (!focused.current) event.currentTarget.dataset.spotlightActive = 'false' }}
    onFocusCapture={focus}
    onBlurCapture={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) { focused.current = false; event.currentTarget.dataset.spotlightActive = 'false' } }}>
    <div className='bits-spotlight-layer' data-spotlight-layer aria-hidden='true' />
    {children}
  </div>
}
