/** Shared display primitives. Dense, hairline-ruled, no decoration. */

import type { ReactNode } from 'react'

import { formatINR, formatPercent } from '@/lib/format'
import { reasonCodeTone, statusStyle } from '@/lib/status'

export function StatusBadge({
  status,
  size = 'sm',
}: {
  status: string
  size?: 'sm' | 'md'
}) {
  const style = statusStyle(status)
  return (
    <span
      className={`chip ${style.bg} ${style.border} ${style.text} ${
        size === 'md' ? 'h-5 px-2 text-xs' : ''
      }`}
      title={style.meaning}
    >
      <span className={`mr-1.5 h-1.5 w-1.5 rounded-full ${style.dot}`} />
      {style.label}
    </span>
  )
}

export function ReasonCode({ code }: { code: string }) {
  return (
    <span className={`chip font-mono ${reasonCodeTone(code)}`} title={code}>
      {code.replace(/_/g, ' ').toLowerCase()}
    </span>
  )
}

/** Right-aligned monospace money cell. Variance gets a sign and a colour. */
export function Money({
  paisa,
  variance = false,
  muted = false,
  className = '',
}: {
  paisa: number
  variance?: boolean
  muted?: boolean
  className?: string
}) {
  const tone = variance
    ? paisa === 0
      ? 'text-ink-3'
      : paisa > 0
        ? 'text-review'
        : 'text-exception'
    : muted
      ? 'text-ink-2'
      : 'text-ink'
  return (
    <span className={`num ${tone} ${className}`}>
      {variance && paisa === 0 ? '0.00' : formatINR(paisa, { sign: variance })}
    </span>
  )
}

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100
  const tone =
    value >= 1
      ? 'bg-matched'
      : value >= 0.95
        ? 'bg-partial'
        : value > 0
          ? 'bg-review'
          : 'bg-line-strong'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1 w-10 rounded-sm bg-line">
        <div className={`h-1 rounded-sm ${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="num text-xs text-ink-2">{value.toFixed(2)}</span>
    </div>
  )
}

export function Metric({
  label,
  value,
  sub,
  tone = 'default',
  formula,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: 'default' | 'good' | 'warn' | 'bad' | 'accent'
  formula?: string
}) {
  const toneClass = {
    default: 'text-ink',
    good: 'text-matched',
    warn: 'text-review',
    bad: 'text-exception',
    accent: 'text-accent',
  }[tone]
  return (
    <div className="flex flex-1 flex-col px-4 py-3" title={formula}>
      {/* Fixed two-line label box. Without it a wrapping label pushes its own
          value down and the figures stop sharing a baseline across the row,
          which is exactly the misalignment a metrics strip must not have. */}
      <div className="label flex h-7 items-start">{label}</div>
      <div className={`num text-xl font-semibold ${toneClass}`}>{value}</div>
      {sub ? <div className="mt-0.5 text-xs text-ink-3">{sub}</div> : null}
    </div>
  )
}

export function Panel({
  title,
  actions,
  children,
  note,
  className = '',
  bodyClassName = '',
}: {
  title?: string
  actions?: ReactNode
  children: ReactNode
  note?: string
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={`panel flex flex-col ${className}`}>
      {title ? (
        <header className="flex h-9 shrink-0 items-center justify-between border-b border-line px-3">
          <h2 className="label">{title}</h2>
          {actions}
        </header>
      ) : null}
      <div className={`min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
      {note ? (
        <footer className="border-t border-line px-3 py-2 text-xs text-ink-3">
          {note}
        </footer>
      ) : null}
    </section>
  )
}

export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string
  detail?: string
  action?: ReactNode
}) {
  return (
    <div className="flex h-full min-h-[180px] flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      <p className="text-md font-medium text-ink-2">{title}</p>
      {detail ? <p className="max-w-md text-sm text-ink-3">{detail}</p> : null}
      {action}
    </div>
  )
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex h-full min-h-[120px] items-center justify-center gap-2 text-sm text-ink-3">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
      {label}
    </div>
  )
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex h-full min-h-[120px] flex-col items-center justify-center gap-1 px-6 text-center">
      <p className="text-sm font-medium text-exception">Request failed</p>
      <p className="text-xs text-ink-3">{message}</p>
    </div>
  )
}

/** Label/value row used throughout the detail drawer. */
export function Field({
  label,
  children,
  mono = false,
}: {
  label: string
  children: ReactNode
  mono?: boolean
}) {
  return (
    <div className="flex items-baseline gap-3 py-1">
      <div className="w-36 shrink-0 text-xs text-ink-3">{label}</div>
      <div className={`min-w-0 flex-1 text-sm ${mono ? 'num break-all' : ''}`}>
        {children}
      </div>
    </div>
  )
}

export function PercentDelta({ value }: { value: number }) {
  const tone = value > 0 ? 'text-matched' : value < 0 ? 'text-exception' : 'text-ink-3'
  const sign = value > 0 ? '+' : ''
  return (
    <span className={`num ${tone}`}>
      {sign}
      {value.toFixed(2)}%
    </span>
  )
}

export function Ratio({ value }: { value: number }) {
  return <span className="num">{formatPercent(value)}</span>
}
