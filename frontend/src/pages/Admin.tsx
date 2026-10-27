import { useEffect, useState } from 'react'
import { Activity, BookOpen, Boxes, Link2, ScrollText, Users } from 'lucide-react'
import { api, patch, post } from '../lib/api'
import { useApp } from '../lib/context'
import { Heading, Notice, Spinner, Status, errorText, formatDate } from '../components/ui'

type Tab = 'Monitoring' | 'Users' | 'Assignments' | 'Model registry' | 'Knowledge base' | 'Audit log'
const TABS: [Tab, any][] = [['Monitoring', Activity], ['Users', Users], ['Assignments', Link2], ['Model registry', Boxes], ['Knowledge base', BookOpen], ['Audit log', ScrollText]]

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>('Monitoring')
  return <>
    <Heading eyebrow="ADMINISTRATION" title="Platform administration" description="System management, model change control, knowledge governance and audit — without access to clinical content." />
    <div className="tabs">{TABS.map(([t, I]) => <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}><I size={15} /> {t}</button>)}</div>
    {tab === 'Monitoring' && <Monitoring />}{tab === 'Users' && <UsersTab />}{tab === 'Assignments' && <Assignments />}
    {tab === 'Model registry' && <Registry />}{tab === 'Knowledge base' && <Knowledge />}{tab === 'Audit log' && <Audit />}
  </>
}

function Monitoring() {
  const [m, setM] = useState<any>(null)
  const [days, setDays] = useState(30)
  useEffect(() => { setM(null); api(`/admin/monitoring?days=${days}`).then(setM).catch(() => setM({ error: true })) }, [days])
  if (!m) return <div className="panel"><Spinner /></div>
  if (m.error) return <div className="panel">Unable to load monitoring.</div>
  const t = m.technical, ai = m.ai
  const max = Math.max(1, ...ai.confidence_distribution.map((d: any) => d.count))
  return <>
    <div className="inline-actions"><select className="select-field narrow" value={days} onChange={e => setDays(Number(e.target.value))}>{[1, 7, 30, 90].map(d => <option key={d} value={d}>Last {d} day{d > 1 ? 's' : ''}</option>)}</select></div>
    <div className="stat-row">{[['Uptime', `${Math.round(t.uptime_seconds / 60)} min`], ['Requests', t.requests], ['5xx errors', t.server_errors], ['p95 latency', `${t.latency_ms.p95} ms`], ['Rate limited', t.rate_limited], ['Database', t.database], ['Storage', t.storage]].map(([k, v]) => <div className="stat" key={k}><span>{k}</span><b>{v}</b></div>)}</div>
    <div className="two-column-cards">
      <section className="panel"><h3>AI quality signals</h3>
        <div className="stat-row">{[['Analyses', ai.analyses], ['Quality rejection', pct(ai.quality_rejection_rate)], ['Uncertain rate', pct(ai.uncertain_rate)], ['Dentist override', pct(ai.dentist_override_rate)], ['Pending reviews', ai.pending_reviews], ['Emergencies', ai.emergency_escalations]].map(([k, v]) => <div className="stat" key={k as string}><span>{k}</span><b>{v}</b></div>)}</div>
        <h4>Confidence distribution</h4><div className="histogram">{ai.confidence_distribution.map((d: any) => <div key={d.range} title={`${d.range}: ${d.count}`}><i style={{ height: `${(d.count / max) * 100}%` }} /><span>{d.range.split('-')[0]}</span></div>)}</div>
        <h4>Quality rejection reasons</h4><p className="muted-small">{Object.entries(ai.quality_rejection_reasons).map(([k, v]) => `${k.replaceAll('_', ' ')}: ${v}`).join(' · ') || 'None'}</p>
      </section>
      <section className="panel"><h3>Model version performance</h3>
        <table className="data-table"><thead><tr><th>Model</th><th>Findings</th><th>Reviewed</th><th>FP feedback</th><th>Override</th></tr></thead>
          <tbody>{Object.entries(ai.model_version_performance).map(([k, v]: any) => <tr key={k}><td>{k}</td><td>{v.findings}</td><td>{v.reviewed}</td><td>{pct(v.false_positive_feedback_rate)}</td><td>{pct(v.dentist_override_rate)}</td></tr>)}</tbody></table>
        <h3>Input drift</h3>
        {m.drift.models.map((d: any) => <div key={d.model + d.version} className="drift-row"><b>{d.model}@{d.version}</b><span>{d.samples} samples</span>{d.insufficient_data ? <span className="pill pill-grey">insufficient data</span> : d.drift_detected ? <span className="pill pill-red">drift</span> : <span className="pill pill-green">stable</span>}
          <small>{Object.entries(d.features).map(([f, v]: any) => `${f.replaceAll('_', ' ')} z=${v.shift_z}`).join(' · ')}</small></div>)}
        <p className="muted-small">Drift raises an alert for investigation; clinical models are never retrained or redeployed automatically.</p>
      </section>
    </div>
    <section className="panel"><h3>Configuration</h3><div className="stat-row">{Object.entries(m.configuration).map(([k, v]) => <div className="stat" key={k}><span>{k.replaceAll('_', ' ')}</span><b>{Array.isArray(v) ? v.join(', ') : String(v)}</b></div>)}</div></section>
  </>
}
const pct = (v: number | null | undefined) => v == null ? '—' : `${Math.round(v * 100)}%`

function UsersTab() {
  const { toast } = useApp()
  const [rows, setRows] = useState<any[]>([])
  const [form, setForm] = useState({ full_name: '', email: '', password: '', role: 'dentist' })
  const load = () => api<any[]>('/admin/users').then(setRows).catch(e => toast(errorText(e)))
  useEffect(() => { void load() }, [])
  async function create(e: React.FormEvent) { e.preventDefault(); try { await post('/admin/users', form); toast('Account created'); setForm({ full_name: '', email: '', password: '', role: 'dentist' }); void load() } catch (err) { toast(errorText(err)) } }
  async function toggle(u: any) { try { await patch(`/admin/users/${u.id}`, { is_active: !u.is_active }); void load() } catch (e) { toast(errorText(e)) } }
  return <div className="two-column-cards">
    <section className="panel"><h3>Accounts</h3><table className="data-table"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th /></tr></thead>
      <tbody>{rows.map(u => <tr key={u.id}><td>{u.full_name}</td><td>{u.email}</td><td>{u.role}</td><td>{u.is_active ? 'active' : 'disabled'}</td><td><button className="text-button" onClick={() => toggle(u)}>{u.is_active ? 'Disable' : 'Enable'}</button></td></tr>)}</tbody></table></section>
    <form className="panel form-panel" onSubmit={create}><h3>Provision staff account</h3><p className="panel-copy">Dentist and administrator accounts are created here; patients self-register.</p>
      <label className="field-label">Full name</label><input className="text-field" required value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })} />
      <label className="field-label">Email</label><input className="text-field" type="email" required value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} />
      <label className="field-label">Temporary password</label><input className="text-field" type="password" required minLength={10} value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} />
      <label className="field-label">Role</label><select className="select-field" value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}><option value="dentist">Dentist</option><option value="admin">Administrator</option></select>
      <button className="button button-primary">Create account</button></form>
  </div>
}

function Assignments() {
  const { toast } = useApp()
  const [rows, setRows] = useState<any[]>([])
  const [users, setUsers] = useState<any[]>([])
  const [d, setD] = useState(''), [p, setP] = useState('')
  const load = () => { api<any[]>('/admin/assignments').then(setRows).catch(() => undefined); api<any[]>('/admin/users').then(setUsers).catch(() => undefined) }
  useEffect(load, [])
  async function add() { try { await post('/admin/assignments', { dentist_id: d, patient_id: p }); toast('Patient assigned'); load() } catch (e) { toast(errorText(e)) } }
  async function remove(id: string) { try { await api(`/admin/assignments/${id}`, { method: 'DELETE' }); load() } catch (e) { toast(errorText(e)) } }
  return <div className="two-column-cards">
    <section className="panel"><h3>Dentist ↔ patient access</h3><p className="panel-copy">Dentists can only see patients assigned here.</p>
      <table className="data-table"><thead><tr><th>Dentist</th><th>Patient</th><th>Since</th><th /></tr></thead><tbody>{rows.map(r => <tr key={r.id}><td>{r.dentist_name}</td><td>{r.patient_name}</td><td>{formatDate(r.created_at)}</td><td><button className="text-button" onClick={() => remove(r.id)}>Remove</button></td></tr>)}</tbody></table></section>
    <section className="panel form-panel"><h3>New assignment</h3>
      <label className="field-label">Dentist</label><select className="select-field" value={d} onChange={e => setD(e.target.value)}><option value="">Select…</option>{users.filter(u => u.role === 'dentist').map(u => <option key={u.id} value={u.id}>{u.full_name} · {u.email}</option>)}</select>
      <label className="field-label">Patient</label><select className="select-field" value={p} onChange={e => setP(e.target.value)}><option value="">Select…</option>{users.filter(u => u.role === 'patient').map(u => <option key={u.id} value={u.id}>{u.full_name} · {u.email}</option>)}</select>
      <button className="button button-primary" disabled={!d || !p} onClick={add}>Assign</button></section>
  </div>
}

function Registry() {
  const { toast } = useApp()
  const [data, setData] = useState<any>(null)
  const load = () => api('/admin/models').then(setData).catch(e => toast(errorText(e)))
  useEffect(() => { void load() }, [])
  async function update(id: string, body: any) { try { await patch(`/admin/models/versions/${id}`, body); toast('Model version updated'); void load() } catch (e) { toast(errorText(e)) } }
  if (!data) return <div className="panel"><Spinner /></div>
  return <section className="panel">
    <Notice title="Model change control">Every AI result records the exact model and version. Production deployment requires approval and a documented clinical validation dataset. The orchestrator runs only statuses: <b>{data.allowed_statuses.join(', ')}</b>.</Notice>
    <table className="data-table"><thead><tr><th>Model</th><th>Version</th><th>Training / validation data</th><th>Deployment</th><th>Approval</th></tr></thead>
      <tbody>{data.models.flatMap((m: any) => m.versions.map((v: any) => <tr key={v.id}>
        <td><b>{m.name}</b><br /><small className="muted">{m.description}</small></td><td>{v.version}</td><td><small>{v.training_dataset}<br />{v.validation_dataset}</small></td>
        <td><select className="select-field narrow" value={v.deployment_status} onChange={e => update(v.id, { deployment_status: e.target.value })}>{data.deployment_statuses.map((s: string) => <option key={s}>{s}</option>)}</select></td>
        <td><select className="select-field narrow" value={v.approval_status} onChange={e => update(v.id, { approval_status: e.target.value })}>{data.approval_statuses.map((s: string) => <option key={s}>{s}</option>)}</select></td>
      </tr>))}</tbody></table>
  </section>
}

function Knowledge() {
  const { toast } = useApp()
  const [docs, setDocs] = useState<any[]>([])
  const [open, setOpen] = useState<string | null>(null)
  const load = () => api<any[]>('/admin/knowledge').then(setDocs).catch(e => toast(errorText(e)))
  useEffect(() => { void load() }, [])
  async function setStatus(id: string, status: string) { try { await patch(`/admin/knowledge/versions/${id}?status=${status}`); void load() } catch (e) { toast(errorText(e)) } }
  return <section className="panel">
    <Notice title="Evidence governance">Explanations may only use approved documents. Each version records source, publication date, review date, reviewer and status. Seed documents must be re-reviewed by DentEdge clinicians before launch.</Notice>
    {docs.map(d => <div key={d.id} className="kb-doc"><button className="history-row" onClick={() => setOpen(open === d.id ? null : d.id)}><span><b>{d.title}</b> <small className="muted">{d.topics.join(', ')}</small></span>{d.versions[0] && <Status value={d.versions[0].status} />}</button>
      {open === d.id && d.versions.map((v: any) => <div key={v.id} className="kb-version"><p><b>v{v.version}</b> · {v.source}<br /><small>Published {v.publication_date} · review by {v.review_date} · {v.reviewer}</small></p>
        <pre className="note-pre">{JSON.stringify(v.content, null, 2)}</pre>
        <div className="inline-actions">{['approved', 'draft', 'retired'].filter(s => s !== v.status).map(s => <button key={s} className="button button-secondary" onClick={() => setStatus(v.id, s)}>Mark {s}</button>)}</div></div>)}</div>)}
  </section>
}

function Audit() {
  const [rows, setRows] = useState<any[]>([])
  const [action, setAction] = useState('')
  useEffect(() => { api<any[]>(`/admin/audit-logs?limit=300${action ? `&action=${encodeURIComponent(action)}` : ''}`).then(setRows).catch(() => undefined) }, [action])
  return <section className="panel">
    <div className="inline-actions"><select className="select-field narrow" value={action} onChange={e => setAction(e.target.value)}><option value="">All events</option>{['analysis', 'clinical_finding', 'image', 'auth', 'consent', 'model', 'knowledge', 'perio', 'scribe', 'voice', 'privacy', 'report', 'admin'].map(a => <option key={a}>{a}</option>)}</select></div>
    <div className="table-scroll"><table className="data-table"><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Resource</th><th>Model</th><th>Conf.</th><th>Decision</th></tr></thead>
      <tbody>{rows.map(r => <tr key={r.id}><td>{formatDate(r.created_at, true)}</td><td>{r.actor_role} <small className="muted">{r.actor_user_id?.slice(0, 8)}</small></td><td>{r.action}</td><td>{r.resource_type} <small className="muted">{r.resource_id?.slice(0, 8)}</small></td><td>{r.model ? `${r.model}@${r.model_version}` : ''}</td><td>{r.confidence != null ? Math.round(r.confidence * 100) + '%' : ''}</td><td>{r.decision ?? ''}</td></tr>)}</tbody></table></div>
  </section>
}
