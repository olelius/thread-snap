import type { ReactNode } from 'react'

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string
  description: string
  actions?: ReactNode
  eyebrow?: ReactNode
}) {
  return (
    <div className='flex flex-col gap-3 border-b border-border/70 pb-3 sm:flex-row sm:items-end sm:justify-between'>
      <div>
        {eyebrow ?? <p className='mb-0.5 text-xs font-semibold tracking-[0.22em] text-primary uppercase'>ThreadSnap</p>}
        <h1 className='text-2xl font-semibold tracking-tight'>{title}</h1>
        <p className='mt-1 max-w-3xl text-sm text-muted-foreground'>{description}</p>
      </div>
      {actions && <div className='flex shrink-0 flex-wrap items-center justify-end gap-2'>{actions}</div>}
    </div>
  )
}
