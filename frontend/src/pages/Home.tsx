import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowRight, AudioLines, CalendarDays, ClipboardCheck, FileText, History, ImagePlus, ScanLine, ShieldCheck, Smile, Sparkles, Users } from 'lucide-react'
import { api, type AnalysisSummary } from '../lib/api'
import { useApp, type Page } from '../lib/context'
import { usePatients } from '../components/gates'
import { Empty, Spinner, Status, formatDate, moduleName } from '../components/ui'

export default function Overview() {
  const { user } = useApp()
  if (user.role === 'dentist') return <DentistDashboard />
  if (user.role === 'admin') return <AdminHome />
  return <PatientHome />
}

function Welcome({ title, text }: { title: string; text: string }) {
  return <div className="welcome-row"><div><div className="eyebrow"><Sparkles size={13} /> DENTEDGE AI ORAL HEALTH INTELLIGENCE</div><h1>{title}</h1><p>{text}</p></div>
    <div className="date-chip"><CalendarDays size={16} />{new Date().toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}</div></div>
}

function PatientHome() {
  const { user, navigate } = useApp()
  const [recent, setRecent] = useState<AnalysisSummary[] | null>(null)
  const [profile, setProfile] = useState<any>(null)
  useEffect(() => {
    api<AnalysisSummary[]>('/analyses').then(a => setRecent(a.slice(0, 5))).catch(() => setRecent([]))
    api(`/patients/${user.id}/oral-profile`).then(setProfile).catch(() => undefined)
  }, [user.id])
  const choices: { name: string; text: string; icon: any; color: string; page: Page; tag: string }[] = [
    { name: 'Check my teeth', text: 'Photos of your teeth and gums, checked for quality and reviewed by a dentist.', icon: ScanLine, color: 'mint', page: 'Oral Vision', tag: 'PHOTO' },
    { name: 'Analyze an X-ray', text: 'Upload a dental X-ray for annotated, dentist-reviewed observations.', icon: ImagePlus, color: 'blue', page: 'X-Ray AI', tag: 'X-RAY' },
    { name: 'Tell my symptoms', text: 'Speak or type what you feel; we structure it for your dentist.', icon: AudioLines, color: 'violet', page: 'Voice Assistant', tag: 'VOICE' },
    { name: 'Check my smile', text: 'A cosmetic Smile Score with symmetry, alignment and staining.', icon: Smile, color: 'peach', page: 'Smile Intelligence', tag: 'COSMETIC' },
  ]
  return <>
    <Welcome title={`Welcome back, ${user.full_name.split(' ')[0]}`} text="A clearer view of your oral health — with your dentist always making the decisions." />
    <section className="hero-banner"><div className="hero-content"><div className="hero-pill"><span className="hero-pulse" /> AI DETECTS · CLINICAL RULES CONSTRAIN · YOUR DENTIST DECIDES</div>
      <h2>Better understanding.<br /><em>More informed care.</em></h2><p>Bring photos, X-rays, symptoms and your history into one longitudinal oral-health profile.</p>
      <button className="button button-white" onClick={() => navigate('Oral Vision')}>Start an assessment <ArrowRight size={16} /></button>
      <div className="hero-footnote"><ShieldCheck size={14} /> Quality-gated, evidence-grounded and reviewed by a dentist</div></div></section>
    <div className="section-heading"><div><h2>What would you like to do?</h2><p>Choose a starting point.</p></div></div>
    <div className="module-grid">{choices.map(m => <button className="module-card" key={m.name} onClick={() => navigate(m.page)}><div className={`module-icon ${m.color}`}><m.icon size={21} strokeWidth={1.8} /></div><div className="module-tag">{m.tag}</div><h3>{m.name}</h3><p>{m.text}</p><div className="module-link">Open <ArrowRight size={15} /></div></button>)}</div>
    <div className="lower-grid">
      <section className="panel activity-panel"><div className="panel-heading"><div><h2>Recent activity</h2><p>Your latest analyses</p></div><button className="icon-button" onClick={() => navigate('Timeline')} aria-label="View timeline"><ArrowRight size={17} /></button></div>
        {!recent ? <Spinner /> : recent.length ? <div className="activity-list">{recent.map(a => <button className="activity-row" key={a.id} onClick={() => navigate('Reports', { analysisId: a.id })}><div className="activity-icon"><FileText size={17} /></div><div className="activity-main"><b>{moduleName(a.module)}</b><span>{a.summary}</span></div><div className="activity-end"><Status value={a.status} /><small>{formatDate(a.created_at)}</small></div></button>)}</div>
          : <Empty icon={<History size={22} />} title="No activity yet" text="Your analyses will appear here." action={<button className="text-button" onClick={() => navigate('Oral Vision')}>Start your first check <ArrowRight size={14} /></button>} />}
      </section>
      <section className="panel next-panel"><div className="panel-heading"><div><h2>Your oral health profile</h2><p>Combined across photos, X-rays, symptoms and visits</p></div></div>
        {profile ? <><div className="next-step big"><span>Next step</span><b>{profile.next_step}</b></div>
          <ul className="plain-list">{profile.smile && <li>Smile Score {profile.smile.score}/100 (cosmetic)</li>}{profile.photo && <li>Photo: {profile.photo.text}</li>}{profile.symptoms && <li>Symptoms: {profile.symptoms.text}</li>}<li>{profile.previous_examination}</li></ul>
          <button className="text-button" onClick={() => navigate('Oral Health Profile')}>Open full profile <ArrowRight size={14} /></button></> : <Spinner />}
        <div className="safety-note"><ShieldCheck size={16} /><span>DentEdge AI supports understanding. It does not diagnose or replace your dentist.</span></div>
      </section>
    </div>
  </>
}

function DentistDashboard() {
  const { user, navigate, setPatient } = useApp()
  const { rows } = usePatients()
  const [queue, setQueue] = useState<number | null>(null)
  useEffect(() => { api<{ counts: { open: number } }>('/clinical-review/queue').then(q => setQueue(q.counts.open)).catch(() => setQueue(0)) }, [])
  const urgent = rows?.filter(r => r.emergency_flags) ?? []
  return <>
    <Welcome title={`Good day, Dr. ${user.full_name.split(' ').slice(-1)[0]}`} text="AI-assisted findings, scribe drafts and charts — waiting for your clinical judgement." />
    {urgent.length > 0 && <div className="notice-banner tone-danger"><AlertTriangle size={18} /><div><b>Urgent symptom reports</b><div className="notice-body">{urgent.map(u => u.full_name).join(', ')} reported symptoms that triggered emergency guidance.</div></div></div>}
    <div className="stat-row">
      <button className="stat clickable" onClick={() => navigate('Clinical Review')}><span>Findings awaiting review</span><b>{queue ?? '…'}</b></button>
      <div className="stat"><span>Assigned patients</span><b>{rows?.length ?? '…'}</b></div>
      <div className="stat"><span>Consent incomplete</span><b>{rows?.filter(r => !r.consent_complete).length ?? '…'}</b></div>
    </div>
    <section className="panel"><div className="panel-heading"><div><h2>Your patients</h2><p>Sorted by urgency and pending review</p></div><Users size={20} className="muted" /></div>
      {!rows ? <Spinner /> : !rows.length ? <Empty icon={<Users size={22} />} title="No assigned patients" text="An administrator assigns patients to your workspace." /> :
        <table className="data-table"><thead><tr><th>Patient</th><th>Pending review</th><th>Last activity</th><th>Consent</th><th /></tr></thead><tbody>{rows.map(r => <tr key={r.id}>
          <td><b>{r.full_name}</b>{r.emergency_flags ? <span className="pill pill-red">urgent</span> : null}<br /><small className="muted">{r.email}</small></td><td>{r.pending_review}</td><td>{formatDate(r.last_activity)}</td><td>{r.consent_complete ? '✓' : 'missing'}</td>
          <td className="row-actions"><button className="text-button" onClick={() => { setPatient({ id: r.id, full_name: r.full_name }); navigate('Oral Health Profile') }}>Profile</button><button className="text-button" onClick={() => { setPatient({ id: r.id, full_name: r.full_name }); navigate('Perio Charting') }}>Perio</button><button className="text-button" onClick={() => { setPatient({ id: r.id, full_name: r.full_name }); navigate('AI Scribe') }}>Scribe</button></td></tr>)}</tbody></table>}
    </section>
    <div className="safety-note"><ClipboardCheck size={16} /><span>AI detects. The system validates. Clinical rules constrain. The LLM explains. The dentist decides.</span></div>
  </>
}

function AdminHome() {
  const { navigate } = useApp()
  return <>
    <Welcome title="Platform administration" text="Monitor the system, manage staff access, models and approved knowledge." />
    <div className="module-grid">{([['Monitoring & drift', 'Administration'], ['Users & assignments', 'Administration'], ['Model registry', 'Administration'], ['Audit log', 'Administration']] as [string, Page][]).map(([n, p]) => <button key={n} className="module-card" onClick={() => navigate(p)}><h3>{n}</h3><div className="module-link">Open <ArrowRight size={15} /></div></button>)}</div>
  </>
}
