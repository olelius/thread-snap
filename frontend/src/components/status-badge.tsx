import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

const tones: Record<string, string> = {
  success: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  partial_success: 'border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300',
  failed: 'border-red-500/25 bg-red-500/10 text-red-700 dark:text-red-300',
  waiting_for_auth: 'border-cyan-500/25 bg-cyan-500/10 text-cyan-700 dark:text-cyan-300',
  running: 'border-indigo-500/25 bg-indigo-500/10 text-indigo-700 dark:text-indigo-300',
  queued: 'border-slate-500/25 bg-slate-500/10 text-slate-700 dark:text-slate-300',
  visible: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  hidden: 'border-red-500/25 bg-red-500/10 text-red-700 dark:text-red-300',
  unknown: 'border-slate-500/25 bg-slate-500/10 text-slate-700 dark:text-slate-300',
}

export function StatusBadge({ value, label }: { value: string; label?: string }) {
  return (
    <Badge variant='outline' className={cn('whitespace-nowrap font-medium', tones[value])}>
      {label ?? value}
    </Badge>
  )
}
