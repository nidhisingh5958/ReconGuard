/**
 * Application shell: fixed sidebar, a status rail, and a dense content area.
 *
 * The rail is not decoration. It permanently answers the three questions an
 * operator asks before trusting a number on screen: which run am I looking at,
 * what engine produced it, and is an LLM anywhere in this path.
 */

import { NavLink, Outlet } from 'react-router-dom'

import { useRunContext } from '@/hooks/useRunContext'
import { formatDateTime, formatMs, formatPercent } from '@/lib/format'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/reconciliation', label: 'Reconciliation' },
  { to: '/exceptions', label: 'Exceptions' },
  { to: '/audit', label: 'Audit Trail' },
  { to: '/journal', label: 'Journal' },
  { to: '/rules', label: 'Rules' },
  { to: '/cash', label: 'Cash Position' },
  { to: '/copilot', label: 'Copilot' },
]

/** Sections that are architecture-ready rather than fully built. Marked, not
 *  hidden. Empty now that the intelligence layer is implemented; kept because
 *  the next capability added should be labelled honestly rather than shipped
 *  looking finished. */
const PREVIEW = new Set<string>([])

export function Layout() {
  const { runs, activeRunId, activeRun, health, running, startRun, setActiveRunId } =
    useRunContext()

  return (
    <div className="flex h-screen overflow-hidden bg-canvas">
      {/* ---- sidebar ---- */}
      <aside className="flex w-[212px] shrink-0 flex-col border-r border-line bg-panel">
        <div className="flex h-12 items-center gap-2 border-b border-line px-4">
          <div className="flex h-5 w-5 items-center justify-center rounded-sm border border-accent/50 bg-accent/10">
            <span className="text-2xs font-bold text-accent">R</span>
          </div>
          <div className="leading-none">
            <div className="text-md font-semibold tracking-tight">ReconGuard</div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto py-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                [
                  'group relative flex items-center justify-between px-4 py-1.5 text-sm transition-colors',
                  isActive
                    ? 'bg-accent/[0.07] text-ink'
                    : 'text-ink-2 hover:bg-hover hover:text-ink',
                ].join(' ')
              }
            >
              {({ isActive }) => (
                <>
                  {isActive ? (
                    <span className="absolute left-0 top-0 h-full w-[2px] bg-accent" />
                  ) : null}
                  <span>{item.label}</span>
                  {PREVIEW.has(item.to) ? (
                    <span className="chip border-line-strong bg-canvas text-ink-3">
                      next
                    </span>
                  ) : null}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-line px-4 py-3">
          <div className="label mb-2">Accounting config</div>
          <dl className="space-y-1 text-xs">
            <ConfigRow label="Gateway fee" value={pct(health?.accounting.gateway_fee_pct)} />
            <ConfigRow label="GST on fee" value={pct(health?.accounting.gst_on_fee_pct)} />
            <ConfigRow label="TDS" value={pct(health?.accounting.tds_pct)} />
          </dl>
        </div>

        <div className="border-t border-line px-4 py-3">
          <div
            className="chip w-full justify-center border-matched/30 bg-matched/10 text-matched"
            title="The deterministic engine produces every result on this screen. No language model is in the reconciliation path."
          >
            NO LLM IN PATH
          </div>
          <div className="mt-2 truncate text-2xs text-ink-3" title={health?.engine_version}>
            {health?.engine_version ?? 'engine offline'}
          </div>
        </div>
      </aside>

      {/* ---- main ---- */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-4 border-b border-line bg-panel px-4">
          <div className="flex items-center gap-2">
            <label className="label" htmlFor="run-select">
              Run
            </label>
            <select
              id="run-select"
              className="input num w-[152px]"
              value={activeRunId ?? ''}
              onChange={(event) => setActiveRunId(event.target.value)}
              disabled={runs.length === 0}
            >
              {runs.length === 0 ? <option value="">no runs</option> : null}
              {runs.map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  {run.run_id}
                  {run.label ? ` · ${run.label}` : ''}
                </option>
              ))}
            </select>
          </div>

          {activeRun ? (
            <div className="flex items-center gap-4 border-l border-line pl-4 text-xs text-ink-2">
              <RailStat label="Dataset" value={activeRun.dataset_id} />
              <RailStat label="Mode" value={activeRun.dataset_mode} />
              <RailStat
                label="Records"
                value={activeRun.records_processed.toLocaleString('en-IN')}
              />
              <RailStat label="Match" value={formatPercent(activeRun.match_rate)} />
              <RailStat label="Time" value={formatMs(activeRun.processing_time_ms)} />
              <RailStat label="Completed" value={formatDateTime(activeRun.completed_at)} />
            </div>
          ) : null}

          <div className="ml-auto flex items-center gap-2">
            <button
              className="btn-accent"
              onClick={() => void startRun()}
              disabled={running}
            >
              {running ? 'Running…' : 'Run reconciliation'}
            </button>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function RailStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="text-2xs uppercase tracking-wider text-ink-3">{label}</span>
      <span className="num text-ink">{value}</span>
    </div>
  )
}

function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between">
      <dt className="text-ink-3">{label}</dt>
      <dd className="num text-ink-2">{value}</dd>
    </div>
  )
}

function pct(value: number | string | undefined): string {
  if (value === undefined) return '—'
  return `${Number(value).toFixed(2)}%`
}
