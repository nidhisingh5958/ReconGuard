/**
 * ReconGuard design tokens.
 *
 * The visual target is an accounting terminal / operations control room:
 * graphite panels, hairline rules, tabular figures, and a single amber accent
 * doing the work that a pile of gradients would otherwise do badly.
 *
 * Rules this palette enforces:
 *  - status colour is semantic and reserved: never decorative
 *  - the accent is amber and is used sparingly, for focus and active state
 *  - no shadow except on genuinely floating surfaces (the drawer)
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: '#0A0C0F',
        panel: '#12151A',
        raised: '#171B21',
        hover: '#1C222A',
        line: '#232830',
        'line-strong': '#2F3641',
        ink: '#E8EBEF',
        'ink-2': '#99A2AD',
        'ink-3': '#69727E',
        accent: '#F0B429',
        'accent-dim': '#8A6A1C',
        matched: '#3FCF8E',
        partial: '#56A8F5',
        review: '#F0B429',
        duplicate: '#B98AFF',
        exception: '#FF6B6B',
        unresolved: '#FF9A62',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      fontSize: {
        '2xs': ['10px', { lineHeight: '14px' }],
        xs: ['11px', { lineHeight: '16px' }],
        sm: ['12px', { lineHeight: '18px' }],
        base: ['13px', { lineHeight: '20px' }],
        md: ['14px', { lineHeight: '21px' }],
        lg: ['16px', { lineHeight: '24px' }],
        xl: ['20px', { lineHeight: '28px' }],
        '2xl': ['26px', { lineHeight: '32px' }],
        '3xl': ['32px', { lineHeight: '38px' }],
      },
      borderRadius: {
        DEFAULT: '3px',
        sm: '2px',
        md: '4px',
      },
      spacing: {
        row: '34px',
      },
    },
  },
  plugins: [],
}
