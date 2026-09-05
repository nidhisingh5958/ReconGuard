import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Money, ReasonCode, StatusBadge } from './primitives'
import { INFORMATIONAL_CODES, statusStyle } from '@/lib/status'

describe('StatusBadge', () => {
  it('labels each status and carries its meaning as a tooltip', () => {
    render(<StatusBadge status="MATCHED" />)
    const badge = screen.getByText('Matched')
    expect(badge).toBeInTheDocument()
    expect(badge.closest('span')).toHaveAttribute(
      'title',
      statusStyle('MATCHED').meaning,
    )
  })

  it('falls back safely on an unknown status rather than rendering blank', () => {
    render(<StatusBadge status="SOMETHING_NEW" />)
    expect(screen.getByText('Unresolved')).toBeInTheDocument()
  })
})

describe('Money', () => {
  it('renders a plain amount without a sign', () => {
    render(<Money paisa={9_762_000} />)
    expect(screen.getByText('₹97,620.00')).toBeInTheDocument()
  })

  it('renders a zero variance as a neutral zero, not a signed one', () => {
    render(<Money paisa={0} variance />)
    expect(screen.getByText('0.00')).toBeInTheDocument()
  })

  it('signs a non-zero variance so direction is unambiguous', () => {
    const { rerender } = render(<Money paisa={15_000} variance />)
    expect(screen.getByText('+₹150.00')).toBeInTheDocument()
    rerender(<Money paisa={-15_000} variance />)
    expect(screen.getByText('-₹150.00')).toBeInTheDocument()
  })
})

describe('ReasonCode', () => {
  it('tones informational codes differently from blocking ones', () => {
    // This distinction is load-bearing: an informational code explains HOW a
    // match was proved and must not read as a problem.
    expect(INFORMATIONAL_CODES.has('ROUNDING_TOLERANCE_APPLIED')).toBe(true)
    expect(INFORMATIONAL_CODES.has('TDS_MISMATCH')).toBe(false)

    const { container } = render(<ReasonCode code="ROUNDING_TOLERANCE_APPLIED" />)
    expect(container.firstChild).toHaveClass('text-ink-2')

    const blocking = render(<ReasonCode code="TDS_MISMATCH" />)
    expect(blocking.container.firstChild).toHaveClass('text-exception')
  })

  it('humanises the code for display but keeps the raw value in the tooltip', () => {
    render(<ReasonCode code="MISSING_SETTLEMENT" />)
    const chip = screen.getByTitle('MISSING_SETTLEMENT')
    expect(chip).toHaveTextContent('missing settlement')
  })
})
