import { describe, expect, it } from 'vitest'

import {
  confidenceLabel,
  formatINR,
  formatINRCompact,
  formatMs,
  formatPaisa,
  formatPercent,
  formatThroughput,
} from './format'

describe('paise formatting', () => {
  it('renders paise as rupees with two decimal places', () => {
    expect(formatPaisa(9_762_000)).toBe('97,620.00')
    expect(formatPaisa(1)).toBe('0.01')
    expect(formatPaisa(0)).toBe('0.00')
    expect(formatPaisa(100_025)).toBe('1,000.25')
  })

  it('uses Indian lakh/crore grouping, not thousands grouping', () => {
    // 12345678901 paise = Rs.12,34,56,789.01
    expect(formatINR(12_345_678_901)).toBe('₹12,34,56,789.01')
    expect(formatINR(10_000_000)).toBe('₹1,00,000.00')
  })

  it('never loses the last paisa on a large amount', () => {
    // The classic float failure: dividing by 100 in binary would drop this.
    expect(formatPaisa(2_136_392_163)).toBe('2,13,63,921.63')
    expect(formatPaisa(999_999_999_99)).toBe('99,99,99,999.99')
  })

  it('keeps the sign on the outside of the currency symbol', () => {
    expect(formatINR(-100_025)).toBe('-₹1,000.25')
  })

  it('adds an explicit plus only when asked, for variance columns', () => {
    expect(formatINR(500, { sign: true })).toBe('+₹5.00')
    expect(formatINR(-500, { sign: true })).toBe('-₹5.00')
    expect(formatINR(500)).toBe('₹5.00')
  })

  it('compacts only for headline tiles', () => {
    expect(formatINRCompact(2_136_392_163)).toBe('₹2.14 Cr')
    expect(formatINRCompact(10_142_806_7)).toBe('₹10.14 L')
  })

  it('keeps grouping below a lakh rather than printing a bare run of digits', () => {
    expect(formatINRCompact(4_840_714)).toBe('₹48,407')
    expect(formatINRCompact(-4_840_714)).toBe('-₹48,407')
    // Small amounts keep their paise; there is nothing to compact.
    expect(formatINRCompact(50_000)).toBe('₹500.00')
  })
})

describe('metric formatting', () => {
  it('formats a match rate as a percentage', () => {
    expect(formatPercent(0.9306)).toBe('93.06%')
    expect(formatPercent(1)).toBe('100.00%')
  })

  it('switches from milliseconds to seconds above one second', () => {
    expect(formatMs(72.3)).toBe('72 ms')
    expect(formatMs(1498)).toBe('1.50 s')
  })

  it('formats throughput as whole records per second', () => {
    expect(formatThroughput(6968.4)).toBe('6,968/s')
  })

  it('always shows confidence to two decimals', () => {
    expect(confidenceLabel(1)).toBe('1.00')
    expect(confidenceLabel(0.95)).toBe('0.95')
    expect(confidenceLabel(0)).toBe('0.00')
  })
})
