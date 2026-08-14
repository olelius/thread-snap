import * as React from 'react'
import { cn } from '@/lib/utils'

function Progress({ className, value = 0, ...props }: React.ComponentProps<'div'> & { value?: number }) {
  return (
    <div role='progressbar' aria-valuemin={0} aria-valuemax={100} aria-valuenow={value} className={cn('relative h-2 w-full overflow-hidden rounded-full bg-primary/15', className)} {...props}>
      <div className='h-full rounded-full bg-gradient-to-r from-primary to-cyan-400 transition-[width] duration-500 ease-out' style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  )
}

export { Progress }
