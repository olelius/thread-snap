import { Monitor, Moon, Sun } from 'lucide-react'
import { useTheme } from '@/context/theme-provider'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

const choices = [
  { value: 'system' as const, label: '跟随系统', icon: Monitor },
  { value: 'light' as const, label: '浅色主题', icon: Sun },
  { value: 'dark' as const, label: '深色主题', icon: Moon },
]

export function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme()
  const Icon = resolvedTheme === 'dark' ? Moon : Sun
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant='ghost' size='icon' aria-label='切换显示主题'>
          <Icon className='size-4' />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align='end'>
        {choices.map(({ value, label, icon: ChoiceIcon }) => (
          <DropdownMenuItem key={value} onClick={() => setTheme(value)}>
            <ChoiceIcon className='mr-2 size-4' />
            {label}
            {theme === value && <span className='ml-auto text-primary'>●</span>}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
