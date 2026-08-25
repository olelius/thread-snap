import { cn } from '@/lib/utils'

export function ReputationRoleLabel({ role, position }: { role: 'focus' | 'competitor'; position?: number }) {
  return <span className='inline-flex items-center gap-2 text-sm whitespace-nowrap'><span aria-hidden className={cn('size-1.5 rounded-full', role === 'focus' ? 'bg-primary' : 'bg-muted-foreground/45')} /><span className='font-medium'>{role === 'focus' ? '重点' : '竞品'}</span>{position !== undefined && <span className='tabular-nums text-muted-foreground'>{position}</span>}</span>
}
