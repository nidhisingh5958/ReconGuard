/**
 * Display formatting.
 *
 * Money arrives as an integer number of paise and is formatted with Indian
 * lakh/crore grouping. The integer is split with integer arithmetic, never
 * divided into a float, so a large amount cannot lose its last paisa to
 * floating-point representation on the way to the screen.
 */

const INR_GROUPER = new Intl.NumberFormat('en-IN', { useGrouping: true })

/** 9762000 -> "97,620.00" */
export function formatPaisa(paisa: number, opts: { sign?: boolean } = {}): string {
  const negative = paisa < 0
  const abs = Math.abs(Math.trunc(paisa))
  const whole = Math.trunc(abs / 100)
  const frac = abs % 100
  const body = `${INR_GROUPER.format(whole)}.${String(frac).padStart(2, '0')}`
  if (negative) return `-${body}`
  return opts.sign && paisa > 0 ? `+${body}` : body
}

/** 9762000 -> "₹97,620.00" */
export function formatINR(paisa: number, opts: { sign?: boolean } = {}): string {
  const formatted = formatPaisa(paisa, opts)
  return formatted.startsWith('-')
    ? `-₹${formatted.slice(1)}`
    : formatted.startsWith('+')
      ? `+₹${formatted.slice(1)}`
      : `₹${formatted}`
}

/**
 * Compact form for headline tiles only. Never used where an operator might
 * need to reconcile the figure by eye.
 */
export function formatINRCompact(paisa: number): string {
  const abs = Math.abs(paisa)
  const sign = paisa < 0 ? '-' : ''
  if (abs >= 1_00_00_000_00) return `${sign}₹${(abs / 1_00_00_000_00).toFixed(2)} Cr`
  if (abs >= 1_00_000_00) return `${sign}₹${(abs / 1_00_000_00).toFixed(2)} L`
  // Below a lakh, drop the paise but keep lakh/crore grouping: an ungrouped
  // "48407" is materially harder to read at a glance than "48,407".
  if (abs >= 1_000_00) return `${sign}₹${INR_GROUPER.format(Math.round(abs / 100))}`
  return formatINR(paisa)
}

export function formatPercent(value: number, digits = 2): string {
  return `${(value * 100).toFixed(digits)}%`
}

export function formatSignedPercent(value: number, digits = 2): string {
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(digits)}%`
}

export function formatNumber(value: number): string {
  return INR_GROUPER.format(value)
}

export function formatMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`
  return `${ms.toFixed(0)} ms`
}

export function formatThroughput(rps: number): string {
  return `${INR_GROUPER.format(Math.round(rps))}/s`
}

export function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

export function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  return `${formatDate(iso)} ${formatTime(iso)}`
}

/** REASON_CODE -> "Reason code" for display, keeping the raw value available. */
export function humanise(code: string): string {
  const lower = code.toLowerCase().replace(/_/g, ' ')
  return lower.charAt(0).toUpperCase() + lower.slice(1)
}

export function confidenceLabel(confidence: number): string {
  if (confidence >= 1) return '1.00'
  return confidence.toFixed(2)
}
