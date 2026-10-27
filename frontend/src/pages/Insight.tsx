import { useEffect, useState } from 'react'
import { Activity, AudioLines, CalendarDays, ClipboardCheck, FileText, HeartPulse, History, ImagePlus, ScanLine, Smile, Stethoscope } from 'lucide-react'
import { api, post, type AnalysisSummary } from '../lib/api'
import { useApp, type PatientRef } from '../lib/context'
import { PatientPicker, RequirePatient } from '../components/gates'
import { BookingCta, Empty, Heading, Spinner, Status, errorText, formatDate, moduleName } from '../components/ui'

// ----------------------------------------------------------------------------- Oral health profile
export function ProfilePage() {
  return <>
    <Heading eyebrow="DENTEDGE INSIGHT" title="Oral health profile" description="Photos, X-rays, symptoms, gum charts, smile and dentist-confirmed findings combined into one view." action={<PatientPicker compact />} />
    <RequirePatient>{p => <Profile patient={p} />}</RequirePatient>
  </>
}

function Profile({ patient }: { patient: PatientRef }) {
  const { navigate, bookingUrl, user } = useApp()
  const [p, setP] = useState<any>(null)
  const [error, setError] = useState('')
  useEffect(() => { setP(null); api(`/patients/${patient.id}/oral-profile`).then(setP).catch(e => setError(errorText(e))) }, [patient.id])
  if (error) return <div className="panel"><p className="auth-error">{error}</p></div>
  if (!p) return <div className="panel"><Spinner /></div>
  const rows: [string, any, any, () => void][] = [
    ['Photo', ScanLine, p.photo ? `${p.photo.text}${p.photo.pending_review ? ` · ${p.photo.pending_review} awaiting review` : ''}` : null, () => navigate('Oral Vision')],
    ['X-ray', ImagePlus, p.xray ? `${p.xray.text}${p.xray.pending_review ? ` · ${p.xray.pending_review} awaiting review` : ''}` : null, () => navigate('X-Ray AI')],
    ['Symptoms', AudioLines, p.symptoms ? p.symptoms.text + (p.symptoms.emergency ? ' · urgent care advised' : '') : null, () => navigate('Voice Assistant')],
    ['Perio', Activity, p.perio?.text ?? null, () => navigate('Perio Charting')],
    ['Smile', Smile, p.smile ? `${p.smile.score}/100 (cosmetic)` : null, () => navigate('Smile Intelligence')],
    ['Previous examination', History, p.previous_examination, () => navigate('Timeline')],
  ]
  return <>
    <section className="panel profile-card">
      <div className="profile-head"><div><div className="eyebrow">ORAL HEALTH PROFILE</div><h2>{p.patient_name}</h2><p className="muted-small">Updated {formatDate(p.generated_at, true)}</p></div>
        <div className="next-step"><span>Next step</span><b>{p.next_step}</b></div></div>
      <div className="profile-rows">{rows.map(([k, Icon, v, go]) => <button className="profile-row" key={k} onClick={go}><span className="profile-icon"><Icon size={17} /></span><span className="profile-key">{k}</span><span className="profile-val">{v ?? <i className="muted">No data yet</i>}</span></button>)}</div>
      {p.confirmed_findings?.length > 0 && <div className="confirmed"><h4><ClipboardCheck size={16} /> Dentist-confirmed findings</h4><ul className="plain-list">{p.confirmed_findings.map((c: any, i: number) => <li key={i}><b>{c.label}</b> · {c.location?.description || c.location?.region || ''} {c.location?.tooth ? `· tooth ${c.location.tooth}` : ''} <span className="muted-small">{formatDate(c.date)}</span> {c.status !== 'confirmed' && <Status value={c.status} />}</li>)}</ul></div>}
      <p className="muted-small">{p.disclaimer}</p>
    </section>
    {user.role === 'patient' && <BookingCta url={bookingUrl} urgency={p.pending_review_count ? 'soon' : 'routine'} />}
  </>
}

// ----------------------------------------------------------------------------- Timeline
const ICONS: Record<string, any> = { photo_analysis: ScanLine, xray_analysis: ImagePlus, xray_comparison: History, voice_complaint: AudioLines, dentist_review: Stethoscope, perio_chart: Activity, smile_analysis: Smile, clinical_note: FileText, appointment: CalendarDays }

export function TimelinePage() {
  return <>
    <Heading eyebrow="DENTEDGE TIMELINE" title="Oral health timeline" description="Every analysis, symptom report, dentist review and examination — building a longitudinal picture over the years." action={<PatientPicker compact />} />
    <RequirePatient>{p => <Timeline patient={p} />}</RequirePatient>
  </>
}

function Timeline({ patient }: { patient: PatientRef }) {
  const [data, setData] = useState<any>(null)
  useEffect(() => { setData(null); api(`/patients/${patient.id}/timeline`).then(setData).catch(() => setData({ by_year: [] })) }, [patient.id])
  if (!data) return <div className="panel"><Spinner /></div>
  if (!data.by_year.length) return <div className="panel"><Empty icon={<History size={22} />} title="Your timeline is ready" text="Analyses, symptom reports and dentist reviews will appear here over time." /></div>
  return <div className="panel timeline-panel">{data.by_year.map((y: any) => <div key={y.year}><h2 className="timeline-year">{y.year}</h2>
    <div className="timeline-list">{y.events.map((e: any) => { const Icon = ICONS[e.type] ?? FileText; return <div className="timeline-item" key={e.id}><div className="timeline-marker"><Icon size={15} /></div><div className="timeline-copy"><div className="timeline-top"><b>{e.title}</b><span>{formatDate(e.date, true)}</span></div><p>{e.summary}</p></div></div> })}</div></div>)}</div>
}

// ----------------------------------------------------------------------------- Education
export function EducationPage() {
  return <>
    <Heading eyebrow="DENTEDGE EDUCATE" title="Understand your results" description="Plain-language education built only from your structured findings and DentEdge-approved, versioned clinical content." action={<PatientPicker compact />} />
    <RequirePatient>{p => <Education patient={p} />}</RequirePatient>
  </>
}

function Education({ patient }: { patient: PatientRef }) {
  const { focusAnalysisId, toast, bookingUrl } = useApp()
  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([])
  const [selected, setSelected] = useState<string | null>(focusAnalysisId)
  const [report, setReport] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api<AnalysisSummary[]>(`/analyses?patient_id=${patient.id}`).then(a => { setAnalyses(a); if (!selected && a[0]) setSelected(a[0].id) }).catch(() => undefined) }, [patient.id])
  useEffect(() => { if (!selected) return; setBusy(true); setReport(null); post('/education/report', { analysis_id: selected }).then(setReport).catch(e => toast(errorText(e))).finally(() => setBusy(false)) }, [selected])
  if (!analyses.length) return <div className="panel"><Empty icon={<HeartPulse size={22} />} title="Nothing to explain yet" text="Complete a photo or X-ray analysis to receive personalised education." /></div>
  return <div className="workflow-layout">
    <aside className="panel"><h3>Your analyses</h3><div className="history-list">{analyses.map(a => <button key={a.id} className={`history-row ${selected === a.id ? 'active' : ''}`} onClick={() => setSelected(a.id)}><span>{moduleName(a.module)} · {formatDate(a.created_at)}</span><Status value={a.status} /></button>)}</div></aside>
    <section className="panel">
      {busy || !report ? <Spinner /> : <>
        <p className="explanation-summary">{report.summary}</p>
        {report.sections.length === 0 && <p className="panel-copy">No observations to explain for this analysis.</p>}
        <div className="education-grid">{report.sections.map((s: any) => <div className="panel education-card edu-detail" key={s.finding_code}>
          <span>{s.finding_code}</span><span className="pill pill-blue">{s.review_status}</span>
          <h3>What we observed</h3><p>{s.what_we_observed}</p>
          <h4>What it may indicate</h4><p>{s.what_it_may_indicate}</p>
          {s.why_it_matters && <><h4>Why it matters</h4><p>{s.why_it_matters}</p></>}
          {s.possible_contributing_factors?.length > 0 && <><h4>Possible contributing factors</h4><ul className="plain-list">{s.possible_contributing_factors.map((f: string) => <li key={f}>{f}</li>)}</ul></>}
          <h4>What happens next</h4><p>{s.what_happens_next}</p>
          {s.questions_for_your_dentist?.length > 0 && <><h4>Questions for your dentist</h4><ul className="plain-list">{s.questions_for_your_dentist.map((f: string) => <li key={f}>{f}</li>)}</ul></>}
          {s.urgent_warning_signs?.length > 0 && <div className="warning-signs"><h4>Urgent warning signs</h4><ul className="plain-list">{s.urgent_warning_signs.map((f: string) => <li key={f}>{f}</li>)}</ul></div>}
          {s.source && <p className="muted-small">Source: {s.source.title} v{s.source.version} · reviewed by {s.source.reviewer}</p>}
        </div>)}</div>
        <p className="muted-small">{report.disclaimer}</p>
        <BookingCta url={report.appointment_cta?.url || bookingUrl} urgency={report.urgency} />
      </>}
    </section>
  </div>
}
