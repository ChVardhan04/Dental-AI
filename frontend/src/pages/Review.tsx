import { useEffect, useState } from 'react'
import { Check, ClipboardCheck, HelpCircle, Pencil, Search, X } from 'lucide-react'
import { api, post, type Finding } from '../lib/api'
import { useApp } from '../lib/context'
import { AnnotatedViewer, ConfidenceBar, Empty, Heading, Notice, Spinner, Status, errorText, formatDate } from '../components/ui'

const TYPES = ['visible_plaque', 'visible_staining', 'apparent_discoloration', 'visible_gingival_changes', 'apparent_recession', 'visible_chip', 'visible_fracture', 'visible_crowding', 'visible_spacing', 'alignment_characteristics', 'cosmetic_characteristics', 'radiolucent_area_for_review', 'possible_caries', 'possible_periapical_radiolucency', 'possible_bone_level_change', 'restoration_present', 'potential_change_for_review']

export default function ReviewPage() {
  const { toast, setPatient } = useApp()
  const [filter, setFilter] = useState('open')
  const [items, setItems] = useState<(Finding & { patient_name?: string })[] | null>(null)
  const [sel, setSel] = useState<Finding | null>(null)
  const [note, setNote] = useState('')
  const [edit, setEdit] = useState<{ finding_type: string; tooth: string; region: string; severity: string } | null>(null)
  const [history, setHistory] = useState<any[]>([])
  const [busy, setBusy] = useState(false)
  const load = () => api<{ items: Finding[] }>(`/clinical-review/queue?status=${filter}`).then(r => setItems(r.items)).catch(e => toast(errorText(e)))
  useEffect(() => { setItems(null); void load() }, [filter])
  useEffect(() => { if (sel) api<any>(`/findings/${sel.id}/history`).then(h => setHistory(h.history)).catch(() => setHistory([])) }, [sel?.id])
  function pick(f: Finding) { setSel(f); setNote(''); setEdit(null); if (f.patient_id) setPatient({ id: f.patient_id, full_name: f.patient_name ?? 'Patient' }) }
  async function decide(decision: string) {
    if (!sel) return
    setBusy(true)
    try {
      const body: any = { finding_id: sel.id, decision, note: note || undefined }
      if (decision === 'edit' && edit) body.edited_finding = { finding_type: edit.finding_type, severity: edit.severity, location: { tooth: edit.tooth || null, region: edit.region } }
      const r = await post<Finding>('/clinical-review', body)
      toast(`Decision recorded: ${decision.replace('_', ' ')}`)
      setSel(r); setEdit(null); void load()
    } catch (e) { toast(errorText(e)) } finally { setBusy(false) }
  }
  return <>
    <Heading eyebrow="DENTIST PORTAL" title="Clinical review" description="AI findings never become clinical findings automatically. Confirm, edit, reject, mark uncertain or request further examination." />
    <Notice title="Human review is mandatory">Review the source image and evidence before confirming. Confirmed and edited findings enter the patient's clinical record; every decision is audited.</Notice>
    <div className="review-layout">
      <section className="panel review-queue">
        <div className="segmented">{[['open', 'Open'], ['confirm', 'Confirmed'], ['reject', 'Rejected'], ['all', 'All']].map(([v, l]) => <button key={v} className={filter === v ? 'selected' : ''} onClick={() => setFilter(v)}>{l}</button>)}</div>
        {!items ? <Spinner /> : !items.length ? <Empty icon={<ClipboardCheck size={22} />} title="Queue is clear" text="New AI findings for your assigned patients will appear here." /> :
          items.map(f => <button key={f.id} className={`queue-item ${sel?.id === f.id ? 'active' : ''} ${f.urgency === 'soon' ? 'soon' : ''}`} onClick={() => pick(f)}>
            <div><b>{f.label}</b><span>{f.patient_name} · {formatDate(f.created_at)}</span></div>
            <div className="queue-meta"><code>{f.finding_code}</code><Status value={f.review_status} /></div>
          </button>)}
      </section>
      <section className="panel">
        {!sel ? <Empty icon={<Search size={22} />} title="Select a finding" text="Choose a finding from the queue to review its image, evidence and confidence." /> : <>
          <div className="panel-heading"><div><h2>{sel.label} <code>{sel.finding_code}</code></h2><p>{sel.patient_name} · {sel.module} · {sel.model}@{sel.model_version}</p></div><Status value={sel.review_status} /></div>
          {sel.image_asset_id && <AnnotatedViewer imagePath={`/images/${sel.image_asset_id}`} findings={[sel]} selected={sel.id} serverAnnotatedPath={sel.annotated_url ?? undefined} />}
          <dl className="kv">
            <dt>Location</dt><dd>{sel.location?.description || sel.location?.region} {sel.location?.tooth ? `· tooth ${sel.location.tooth}` : ''}</dd>
            <dt>AI confidence</dt><dd><ConfidenceBar value={sel.confidence} band={sel.confidence_band} /></dd>
            <dt>Severity (visual extent)</dt><dd>{sel.severity}</dd>
            <dt>Evidence</dt><dd>{sel.evidence}</dd>
          </dl>
          <label className="field-label">Clinical note (required for reject, edit and further examination)</label>
          <textarea className="large-textarea" rows={3} value={note} onChange={e => setNote(e.target.value)} placeholder="Document your reasoning…" />
          {edit && <div className="edit-grid">
            <label>Finding type<select className="select-field" value={edit.finding_type} onChange={e => setEdit({ ...edit, finding_type: e.target.value })}>{TYPES.map(t => <option key={t} value={t}>{t.replaceAll('_', ' ')}</option>)}</select></label>
            <label>Tooth (FDI)<input className="text-field" value={edit.tooth} onChange={e => setEdit({ ...edit, tooth: e.target.value })} placeholder="e.g. 16" /></label>
            <label>Region / surface<input className="text-field" value={edit.region} onChange={e => setEdit({ ...edit, region: e.target.value })} /></label>
            <label>Severity<select className="select-field" value={edit.severity} onChange={e => setEdit({ ...edit, severity: e.target.value })}>{['low', 'moderate', 'high', 'uncertain'].map(s => <option key={s}>{s}</option>)}</select></label>
          </div>}
          <div className="decision-row">
            <button className="button button-primary" disabled={busy} onClick={() => decide('confirm')}><Check size={15} /> Confirm</button>
            {edit ? <button className="button button-secondary" disabled={busy || !note} onClick={() => decide('edit')}><Pencil size={15} /> Save edit</button>
              : <button className="button button-secondary" disabled={busy} onClick={() => setEdit({ finding_type: sel.finding_type, tooth: (sel.location?.tooth as string) ?? '', region: sel.location?.region ?? '', severity: sel.severity })}><Pencil size={15} /> Edit</button>}
            <button className="button button-secondary" disabled={busy} onClick={() => decide('uncertain')}><HelpCircle size={15} /> Mark uncertain</button>
            <button className="button button-secondary" disabled={busy || !note} onClick={() => decide('further_evaluation')}>Needs further examination</button>
            <button className="button button-danger" disabled={busy || !note} onClick={() => decide('reject')}><X size={15} /> Reject</button>
          </div>
          {history.length > 0 && <div className="history-list"><h4>Decision history</h4>{history.map((h, i) => <div key={i} className="history-row static"><span>{formatDate(h.created_at, true)} · {h.note || 'no note'}</span><Status value={h.decision} /></div>)}</div>}
        </>}
      </section>
    </div>
  </>
}
