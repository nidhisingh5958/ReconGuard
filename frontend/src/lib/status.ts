/**
 * Status and reason-code presentation.
 *
 * Colour here is semantic and reserved. A status colour always means the same
 * thing on every screen, and no decorative element is allowed to borrow one.
 */

import type { ReconciliationStatus } from '@/types'

export interface StatusStyle {
  label: string
  text: string
  bg: string
  border: string
  dot: string
  hex: string
  /** One line an operator can act on. */
  meaning: string
}

export const STATUS_STYLES: Record<ReconciliationStatus, StatusStyle> = {
  MATCHED: {
    label: 'Matched',
    text: 'text-matched',
    bg: 'bg-matched/10',
    border: 'border-matched/30',
    dot: 'bg-matched',
    hex: '#3FCF8E',
    meaning: 'Settlement proved by accounting invariant and cash located.',
  },
  PARTIAL_MATCH: {
    label: 'Partial',
    text: 'text-partial',
    bg: 'bg-partial/10',
    border: 'border-partial/30',
    dot: 'bg-partial',
    hex: '#56A8F5',
    meaning: 'Settlement arithmetic proved, but the cash has not been located.',
  },
  REVIEW_REQUIRED: {
    label: 'Review',
    text: 'text-review',
    bg: 'bg-review/10',
    border: 'border-review/30',
    dot: 'bg-review',
    hex: '#F0B429',
    meaning: 'A quantified discrepancy attributed to a specific component.',
  },
  DUPLICATE: {
    label: 'Duplicate',
    text: 'text-duplicate',
    bg: 'bg-duplicate/10',
    border: 'border-duplicate/30',
    dot: 'bg-duplicate',
    hex: '#B98AFF',
    meaning: 'The same payout appears more than once. Exposure is the excess.',
  },
  EXCEPTION: {
    label: 'Exception',
    text: 'text-exception',
    bg: 'bg-exception/10',
    border: 'border-exception/30',
    dot: 'bg-exception',
    hex: '#FF6B6B',
    meaning: 'No counterpart exists. Reported honestly, never inferred away.',
  },
  UNRESOLVED: {
    label: 'Unresolved',
    text: 'text-unresolved',
    bg: 'bg-unresolved/10',
    border: 'border-unresolved/30',
    dot: 'bg-unresolved',
    hex: '#FF9A62',
    meaning: 'Reached the end of the deterministic layers without explanation.',
  },
}

export const STATUS_ORDER: ReconciliationStatus[] = [
  'MATCHED',
  'PARTIAL_MATCH',
  'REVIEW_REQUIRED',
  'DUPLICATE',
  'EXCEPTION',
  'UNRESOLVED',
]

export function statusStyle(status: string): StatusStyle {
  return STATUS_STYLES[status as ReconciliationStatus] ?? STATUS_STYLES.UNRESOLVED
}

/**
 * Reason codes split into two families. Informational codes explain HOW a
 * match was achieved and never block it; blocking codes describe a problem.
 * Rendering them identically would be misleading.
 */
export const INFORMATIONAL_CODES = new Set([
  'ROUNDING_TOLERANCE_APPLIED',
  'AGGREGATED_SETTLEMENT',
  'SPLIT_SETTLEMENT',
  'REFUND_NETTED',
  'PARTIAL_REFUND',
  'DELAYED_SETTLEMENT',
  'TRUNCATED_BANK_REFERENCE',
  'BANK_REFERENCE_NORMALIZED',
  'COUNTERPARTY_ALIAS_RESOLVED',
  'DATE_FORMAT_NORMALIZED',
  'INVOICE_TYPO_RESOLVED',
])

export function reasonCodeTone(code: string): string {
  return INFORMATIONAL_CODES.has(code)
    ? 'border-line-strong bg-raised text-ink-2'
    : 'border-exception/30 bg-exception/10 text-exception'
}

export const MATCH_TYPE_LABELS: Record<string, string> = {
  EXACT_PAYMENT_ID: 'Exact payment id',
  EXACT_SETTLEMENT_ID: 'Exact settlement id',
  EXACT_INVOICE_ID: 'Exact invoice id',
  EXACT_BANK_REFERENCE: 'Exact bank reference',
  ACCOUNTING_INVARIANT: 'Accounting invariant',
  AGGREGATED_SETTLEMENT: 'Aggregated (N:1)',
  SPLIT_SETTLEMENT: 'Split (1:N)',
  NETTED_ADJUSTMENT: 'Netted adjustment',
  AMOUNT_DATE_WINDOW: 'Amount + date window',
  REFERENCE_PREFIX: 'Truncated reference',
  NONE: 'Not established',
}

export const CONFIDENCE_METHOD_NOTES: Record<string, string> = {
  EXACT_IDENTIFIER: 'An exact identifier matched. Nothing probabilistic remains.',
  ACCOUNTING_INVARIANT: 'The settlement equation closed to the paisa.',
  ACCOUNTING_INVARIANT_WITHIN_ROUNDING_TOLERANCE:
    'The equation closed inside the configured rounding tolerance.',
  AGGREGATED_INVARIANT: 'The summed equation closed across all covered payments.',
  REFERENCE_EXTRACTION_EXACT: 'The bank narration carried the settlement id verbatim.',
  REFERENCE_PREFIX_UNIQUE:
    'A truncated reference resolved to exactly one settlement once the payout amount was also required to agree.',
  AMOUNT_DATE_COUNTERPARTY_COMPOSITE:
    'No usable reference: matched on exact amount, inside the date window, against a gateway narration.',
  NOT_ESTABLISHED: 'No link could be proved.',
}
