import { createContext, useContext } from 'react'
import type { User } from './api'

export type Page = 'Overview' | 'Oral Vision' | 'X-Ray AI' | 'Voice Assistant' | 'AI Scribe' | 'Perio Charting' | 'Smile Intelligence'
  | 'Patient Education' | 'Oral Health Profile' | 'Timeline' | 'Clinical Review' | 'Patients' | 'Reports' | 'Administration' | 'Settings'

export type PatientRef = { id: string; full_name: string }

export type AppCtx = {
  user: User
  patient: PatientRef | null            // patient whose data is being viewed (self for patients)
  setPatient: (p: PatientRef | null) => void
  navigate: (p: Page, opts?: { analysisId?: string }) => void
  toast: (msg: string) => void
  consentMissing: string[]
  refreshConsent: () => void
  focusAnalysisId: string | null
  bookingUrl: string
  updateUser: (u: User) => void
}

export const Ctx = createContext<AppCtx | null>(null)
export function useApp() {
  const c = useContext(Ctx)
  if (!c) throw new Error('App context missing')
  return c
}
