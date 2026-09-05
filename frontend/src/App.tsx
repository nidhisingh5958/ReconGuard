import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from '@/components/Layout'
import { RunProvider } from '@/hooks/useRunContext'
import { AuditTrail } from '@/pages/AuditTrail'
import { CashPosition } from '@/pages/CashPosition'
import { Copilot } from '@/pages/Copilot'
import { Exceptions } from '@/pages/Exceptions'
import { Journal } from '@/pages/Journal'
import { Overview } from '@/pages/Overview'
import { Reconciliation } from '@/pages/Reconciliation'
import { Rules } from '@/pages/Rules'

export default function App() {
  return (
    <RunProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="reconciliation" element={<Reconciliation />} />
          <Route path="exceptions" element={<Exceptions />} />
          <Route path="audit" element={<AuditTrail />} />
          <Route path="journal" element={<Journal />} />
          <Route path="rules" element={<Rules />} />
          <Route path="cash" element={<CashPosition />} />
          <Route path="copilot" element={<Copilot />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </RunProvider>
  )
}
