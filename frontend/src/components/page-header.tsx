import type { ReactNode } from 'react'

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description: string
  actions?: ReactNode
}) {
  return (
    <div className='flex flex-col gap-4 border-b border-border/70 pb-5 sm:flex-row sm:items-end sm:justify-between'>
      <div>
        <p className='mb-1 text-xs font-semibold tracking-[0.22em] text-primary uppercase'>ThreadSnap</p>
        <h1 className='text-2xl font-semibold tracking-tight sm:text-3xl'>{title}</h1>
        <p className='mt-2 max-w-3xl text-sm text-muted-foreground'>{description}</p>
      </div>
      {actions && <div className='flex shrink-0 items-center gap-2'>{actions}</div>}
    </div>
  )
}
