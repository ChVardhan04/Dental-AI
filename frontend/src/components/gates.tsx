import { useEffect, useState } from 'react'
import { ShieldCheck, Stethoscope, UserRound } from 'lucide-react'
import { api, post } from '../lib/api'
import { useApp, type PatientRef } from '../lib/context'
import { Empty, Spinner, errorText } from './ui'

type ConsentStatus = { missing: string[]; version: string; texts: Record<string, string> }

export function ConsentGate({ children }: { children: React.ReactNode }) {
  const { user, consentMissing, refreshConsent, toast } = useApp()
  const [status, setStatus] = useState<ConsentStatus | null>(null)
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)
  const [loadError, setLoadError] = useState('')
  const loadStatus = () => { setLoadError(''); api<ConsentStatus>('/consents/status').then(s => { setStatus(s); if (!s.missing.length) refreshConsent() }).catch(e => setLoadError(errorText(e))) }
  useEffect(() => { if (user.role === 'patient' && consentMissing.length) loadStatus() }, [user.role, consentMissing.join(',')])
  if (user.role !== 'patient' || consentMissing.length === 0) return <>{children}</>
  if (loadError) return <div className="panel consent-panel"><p className="auth-error">{loadError}</p><button className="button button-primary" onClick={loadStatus}>Try again</button></div>
  if (!status) return <div className="panel"><Spinner /></div>
  const all = status.missing.every(t => checked[t])
  async function accept() {
    setBusy(true)
    try {
      await post('/consents', { consents: status!.missing.map(t => ({ consent_type: t, version: status!.version, accepted: true })) })
      toast('Thank you — your consent has been recorded'); setChecked({}); setStatus(null); refreshConsent()
    } catch (e) { toast(errorText(e)) } finally { setBusy(false) }
  }
  return <div className="panel consent-panel">
    <div className="guidance-symbol mint"><ShieldCheck size={23} /></div>
    <h2>Before we analyse your information</h2>
    <p className="panel-copy">DentEdge AI needs your permission before processing images, X-rays or voice. You can withdraw consent or delete your data at any time in Settings.</p>
    {status.missing.map(t => <label className="consent-line" key={t}><input type="checkbox" checked={!!checked[t]} onChange={e => setChecked(c => ({ ...c, [t]: e.target.checked }))} /><span>{status.texts[t]}</span></label>)}
    <p className="muted-small">Consent version {status.version}</p>
    <button className="button button-primary" disabled={!all || busy} onClick={accept}>{busy && <Spinner />} Agree and continue</button>
  </div>
}

type PatientRow = { id: string; full_name: string; email: string; pending_review: number; emergency_flags: number; consent_complete: boolean; last_activity: string | null }

export function usePatients() {
  const { user } = useApp()
  const [rows, setRows] = useState<PatientRow[] | null>(null)
  const [error, setError] = useState('')
  const load = () => { if (user.role === 'dentist') api<PatientRow[]>('/patients').then(setRows).catch(e => setError(errorText(e))) }
  useEffect(load, [user.role])
  return { rows, error, reload: load }
}

export function PatientPicker({ compact = false }: { compact?: boolean }) {
  const { user, patient, setPatient } = useApp()
  const { rows } = usePatients()
  if (user.role !== 'dentist') return null
  return <div className={`patient-picker ${compact ? 'compact' : ''}`}>
    <Stethoscope size={16} />
    <select className="select-field" value={patient?.id ?? ''} onChange={e => { const r = rows?.find(x => x.id === e.target.value); setPatient(r ? { id: r.id, full_name: r.full_name } : null) }} aria-label="Active patient">
      <option value="">Select an assigned patient…</option>
      {rows?.map(r => <option key={r.id} value={r.id}>{r.full_name}{r.pending_review ? ` · ${r.pending_review} to review` : ''}{r.emergency_flags ? ' · ⚠ urgent' : ''}</option>)}
    </select>
  </div>
}

/** Renders children only when a patient context exists (dentists must pick an assigned patient). */
export function RequirePatient({ children }: { children: (p: PatientRef) => React.ReactNode }) {
  const { user, patient } = useApp()
  if (user.role === 'admin') return <div className="panel"><Empty icon={<ShieldCheck size={22} />} title="Clinical content is restricted" text="Administrators manage the platform without access to patient clinical data." /></div>
  if (!patient) return <div className="panel"><Empty icon={<UserRound size={22} />} title="Choose a patient" text="Select one of your assigned patients to continue." action={<PatientPicker />} /></div>
  return <ConsentGate><div key={patient.id} className="patient-scope">{children(patient)}</div></ConsentGate>
}
