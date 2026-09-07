import { useEffect, useRef, useState } from 'react'
import { motion, useInView, useReducedMotion } from 'motion/react'
import { Pause, Play, Waves } from 'lucide-react'
import { useSidebar } from '@/components/ui/sidebar'
import { getCookie, setCookie } from '@/lib/cookies'

/** 低幅触感品牌形体；暂停、系统减弱、离屏、后台和折叠时不消耗连续动画。 */
export function TactileSculpture() {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref)
  const reduceMotion = useReducedMotion()
  const { state, isMobile, openMobile } = useSidebar()
  const [paused, setPaused] = useState(() => getCookie('threadsnap-sculpture-paused') === 'true')
  const [visible, setVisible] = useState(() => document.visibilityState === 'visible')
  const [pulse, setPulse] = useState(0)
  const play = !paused && !reduceMotion && visible && inView && (isMobile ? openMobile : state === 'expanded')
  useEffect(() => {
    const update = () => setVisible(document.visibilityState === 'visible')
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  return <div ref={ref} className='tactile-edition group-data-[collapsible=icon]:hidden' data-playing={play}>
    <span className='tactile-edition-caption'>有形的反馈。<br />轻盈的工作流。</span>
    <motion.button type='button' className='tactile-sculpture-control' aria-label='轻触形体，感受回弹' onClick={() => setPulse((value) => value + 1)} whileHover={reduceMotion ? undefined : { rotate: -4 }} whileTap={reduceMotion ? undefined : { scale: .92 }}>
      <motion.span key={pulse} className='tactile-sculpture' initial={reduceMotion || pulse === 0 ? false : { scale: .85, rotate: -12 }} animate={{ scale: 1, rotate: 0 }} transition={{ type: 'spring', stiffness: 210, damping: 12 }} aria-hidden='true'>
        {[0, 1, 2].map((index) => <motion.i key={index} data-sculpture-piece={index} animate={play ? { y: [0, -5 + index, 0], rotate: [0, index === 1 ? -8 : 7, 0], scale: [1, 1.04, 1] } : { y: 0, rotate: 0, scale: 1 }} transition={play ? { duration: 5.6 + index * .7, delay: index * .2, repeat: Infinity, ease: 'easeInOut' } : { duration: 0 }} />)}
      </motion.span>
    </motion.button>
    <div className='tactile-sculpture-footer'><span><Waves size={13} /> TACTILE EDITION</span><button type='button' disabled={Boolean(reduceMotion)} aria-label={reduceMotion ? '系统已减少动态效果' : paused ? '播放装饰动效' : '暂停装饰动效'} aria-pressed={paused || Boolean(reduceMotion)} title={reduceMotion ? '遵循系统减少动态效果' : paused ? '播放装饰动效' : '暂停装饰动效'} onClick={() => { setPaused(!paused); setCookie('threadsnap-sculpture-paused', String(!paused), 60 * 60 * 24 * 365) }}>{paused || reduceMotion ? <Play size={13} /> : <Pause size={13} />}</button></div>
  </div>
}
