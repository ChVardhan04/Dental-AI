import { useState } from 'react'
import { ArrowRight, Camera, FileText, Plus, ScanLine, Sparkles, Trash2, UploadCloud } from 'lucide-react'
import { post, type Analysis, type ImageAsset } from '../lib/api'
import { useApp, type PatientRef } from '../lib/context'
import { PatientPicker, RequirePatient } from '../components/gates'
import { AnnotatedViewer, BookingCta, CameraCapture, ExplanationPanel, FindingList, Heading, Notice, PipelineTrace, QualityResult, Spinner, Status, errorText } from '../components/ui'

export const PHOTO_VIEWS: [string, string][] = [['front_smile', 'Front smile'], ['upper_teeth', 'Upper teeth'], ['lower_teeth', 'Lower teeth'], ['left_side', 'Left side'], ['right_side', 'Right side'], ['close_up', 'Close-up'], ['problem_area', 'Problem area']]
type Slot = { key: string; file: File; view: string; preview: string; uploaded?: ImageAsset; error?: string }

export default function OralVisionPage() {
  return <>
    <Heading eyebrow="DENTEDGE VISION" title="Check my teeth" description="Upload or capture oral photographs. Every image passes a quality gate before AI analysis, and every observation is reviewed by a dentist." action={<PatientPicker compact />} />
    <RequirePatient>{p => <VisionWorkflow patient={p} />}</RequirePatient>
  </>
}

function VisionWorkflow({ patient }: { patient: PatientRef }) {
  const { user, toast, navigate, bookingUrl } = useApp()
  const [slots, setSlots] = useState<Slot[]>([])
  const [camera, setCamera] = useState(false)
  const [drag, setDrag] = useState(false)
  const [symptoms, setSymptoms] = useState('')
  const [busy, setBusy] = useState<'' | 'upload' | 'analyze'>('')
  const [result, setResult] = useState<Analysis | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const nextView = () => PHOTO_VIEWS.find(([v]) => !slots.some(s => s.view === v))?.[0] ?? 'problem_area'

  function add(files: FileList | File[]) {
    const list = Array.from(files).filter(f => /^image\/(jpeg|png|webp)$/.test(f.type))
    if (!list.length) { toast('Please choose JPEG, PNG or WebP images'); return }
    setSlots(old => {
      const next = [...old]
      for (const f of list.slice(0, 8 - old.length)) {
        const used = new Set(next.map(s => s.view))
        next.push({ key: crypto.randomUUID(), file: f, preview: URL.createObjectURL(f), view: PHOTO_VIEWS.find(([v]) => !used.has(v))?.[0] ?? 'problem_area' })
      }
      return next
    })
    setResult(null)
  }

  async function uploadAll() {
    setBusy('upload')
    const updated = [...slots]
    for (const s of updated) {
      if (s.uploaded) continue
      try {
        const body = new FormData()
        body.append('file', s.file); body.append('view', s.view); body.append('image_kind', 'oral_photo')
        if (user.role === 'dentist') body.append('patient_id', patient.id)
        s.uploaded = await post<ImageAsset>('/oral-images', body); s.error = undefined
      } catch (e) { s.error = errorText(e) }
    }
    setSlots(updated); setBusy('')
    const ok = updated.filter(s => s.uploaded?.quality?.accepted).length
    const firstError = updated.find(s => s.error)?.error
    toast(ok ? `${ok} image${ok === 1 ? '' : 's'} passed the quality gate` : firstError ? `Upload failed: ${firstError}` : 'No image passed the quality gate yet — see the quality notes on each photo')
  }

  async function analyze() {
    const ids = slots.filter(s => s.uploaded).map(s => s.uploaded!.id)
    setBusy('analyze')
    try {
      const r = await post<Analysis>('/oral-analysis', { image_ids: ids, symptoms: symptoms.trim() || undefined })
      setResult(r); setSelected(null)
      toast(r.findings.length ? `${r.findings.length} observation(s) sent for dentist review` : 'Analysis complete')
    } catch (e) { toast(errorText(e)) } finally { setBusy('') }
  }

  async function requestAppointment() {
    try { await post('/appointments', { reason: 'Follow-up on DentEdge AI photo observations', source_type: 'ai_analysis', source_id: result?.id, urgency: result?.urgency === 'soon' ? 'soon' : 'routine' }); toast('Appointment request recorded') }
    catch (e) { toast(errorText(e)) }
  }

  const pending = slots.some(s => !s.uploaded)
  const accepted = slots.filter(s => s.uploaded?.quality?.accepted)
  return <>
    <div className="workflow-layout">
      <section className="panel upload-panel">
        <div className="panel-heading"><div><h2>1 · Add photographs</h2><p>Up to 8 images · JPEG, PNG or WebP · 12 MB each. Multiple views help the AI associate observations across angles.</p></div><span className="step-chip">{slots.length}/8</span></div>
        {camera ? <CameraCapture onCapture={f => { add([f]); setCamera(false) }} onClose={() => setCamera(false)} /> :
          <label className={`dropzone ${drag ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)} onDrop={e => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files) }}>
            <input type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={e => e.target.files && add(e.target.files)} />
            <div className="upload-cloud"><UploadCloud size={26} /></div><b>Drop photos here</b><span>or <strong>browse files</strong></span><small>Front smile, upper, lower, left, right, close-up or problem area</small>
          </label>}
        <div className="inline-actions"><button className="button button-secondary" onClick={() => setCamera(c => !c)}><Camera size={16} /> {camera ? 'Hide camera' : 'Use camera'}</button><span className="muted-small">Next suggested view: {PHOTO_VIEWS.find(([v]) => v === nextView())?.[1]}</span></div>
        {slots.length > 0 && <div className="slot-grid">{slots.map(s => <div className="slot" key={s.key}>
          <img src={s.preview} alt={s.view} />
          <div className="slot-body">
            <select className="select-field" value={s.view} disabled={!!s.uploaded} onChange={e => setSlots(o => o.map(x => x.key === s.key ? { ...x, view: e.target.value } : x))} aria-label="Image view">{PHOTO_VIEWS.map(([v, l]) => <option value={v} key={v}>{l}</option>)}</select>
            {s.uploaded ? <div className="slot-status">{s.uploaded.duplicate && <span className="pill pill-grey">duplicate</span>}<Status value={s.uploaded.quality.accepted ? 'passed' : 'blocked_quality_gate'} /></div> : s.error ? <p className="auth-error">{s.error}</p> : <span className="muted-small">Not uploaded</span>}
            {s.uploaded && !s.uploaded.quality.accepted && <QualityResult quality={s.uploaded.quality} />}
          </div>
          <button className="icon-button slot-remove" aria-label="Remove image" onClick={() => setSlots(o => o.filter(x => x.key !== s.key))}><Trash2 size={15} /></button>
        </div>)}</div>}
        <button className="button button-primary full-button" disabled={!pending || busy !== ''} onClick={uploadAll}>{busy === 'upload' ? <Spinner /> : <UploadCloud size={17} />} Upload and check quality <ArrowRight size={16} /></button>
      </section>
      <aside className="workflow-side">
        <div className="panel guidance-panel"><div className="guidance-symbol"><ScanLine size={23} /></div><h3>How to capture a useful photo</h3><p>The quality gate rejects images that are too blurry, dark, small or not dental.</p>
          {['Use bright, even lighting (no flash glare)', 'Hold the camera steady; tap to focus', 'Fill the frame with the teeth and gums', 'Avoid filters, screenshots and edited images'].map(s => <div className="guidance-item" key={s}><span>✓</span>{s}</div>)}
        </div>
        <div className="panel form-panel">
          <h3>2 · Anything you have noticed? <span className="muted-small">(optional)</span></h3>
          <textarea className="large-textarea" rows={3} maxLength={1000} value={symptoms} onChange={e => setSymptoms(e.target.value)} placeholder="e.g. sensitivity to cold on the upper left" />
          <button className="button button-primary full-button" disabled={!accepted.length || pending || busy !== ''} onClick={analyze}>{busy === 'analyze' ? <Spinner /> : <Sparkles size={16} />} Analyse {accepted.length || ''} image{accepted.length === 1 ? '' : 's'}</button>
          {!accepted.length && slots.some(s => s.uploaded) && <p className="muted-small">At least one image must pass the quality gate.</p>}
        </div>
      </aside>
    </div>
    {result && <VisionResult result={result} selected={selected} setSelected={setSelected} slots={slots} onBook={user.role === 'patient' ? requestAppointment : undefined} bookingUrl={bookingUrl}
      onReport={() => navigate('Reports', { analysisId: result.id })} onEducate={() => navigate('Patient Education', { analysisId: result.id })} />}
  </>
}

export function VisionResult({ result, selected, setSelected, slots, onBook, bookingUrl, onReport, onEducate }: {
  result: Analysis; selected: string | null; setSelected: (s: string | null) => void; slots?: Slot[]; onBook?: () => void; bookingUrl: string; onReport: () => void; onEducate: () => void
}) {
  const images: { image_id: string; view?: string; status?: string }[] = result.result.images ?? []
  const fusion = result.result.fusion
  return <section className="panel analysis-result">
    <div className="panel-heading"><div><h2>Results</h2><p>Analysis {result.id.slice(0, 8)} · {result.model_name}@{result.model_version} · rules {result.rules_version}</p></div><Status value={result.status} /></div>
    {result.result.model?.deployment_status && result.result.model.deployment_status !== 'production' && <Notice tone="warning" title="Research-stage model">These observations come from a model that has not been clinically validated. They are held for dentist review and are not diagnoses.</Notice>}
    <div className="result-grid">
      <div>
        {images.filter(i => i.status === 'analyzed').map(img => {
          const w = slots?.find(s => s.uploaded?.id === img.image_id)?.uploaded
          return <div key={img.image_id} className="result-image"><div className="result-image-label">{img.view?.replaceAll('_', ' ')}</div>
            <AnnotatedViewer imagePath={`/images/${img.image_id}`} width={w?.width} height={w?.height} findings={result.findings.filter(f => f.image_asset_id === img.image_id)} selected={selected} onSelect={setSelected}
              serverAnnotatedPath={result.annotated_images.find(a => a.image_id === img.image_id)?.url} /></div>
        })}
        {images.filter(i => i.status !== 'analyzed').map(i => <p key={i.image_id} className="muted-small">{i.view}: {i.status?.replaceAll('_', ' ')}</p>)}
        {fusion?.regions?.length > 0 && <div className="fusion"><h4>Multi-image view</h4><table className="data-table"><thead><tr><th>Observation</th><th>Region</th><th>Views</th><th>Combined confidence</th></tr></thead>
          <tbody>{fusion.regions.map((r: any, i: number) => <tr key={i}><td>{r.label}</td><td>{r.region}</td><td>{r.supporting_views.join(', ')} <span className="muted-small">({r.consistency})</span></td><td>{Math.round(r.fused_confidence * 100)}%</td></tr>)}</tbody></table>
          {fusion.views_missing?.length > 0 && <p className="muted-small">Adding {fusion.views_missing.map((v: string) => v.replaceAll('_', ' ')).join(', ')} views would give more context.</p>}</div>}
      </div>
      <div>
        <FindingList findings={result.findings} selected={selected} onSelect={setSelected} />
        <ExplanationPanel explanation={result.result.explanation} citations={result.result.citations} provider={result.result.explanation_provider} safety={result.result.safety} />
      </div>
    </div>
    <PipelineTrace steps={result.result.pipeline_trace} />
    <div className="inline-actions"><button className="button button-secondary" onClick={onReport}><FileText size={16} /> Full report</button><button className="button button-secondary" onClick={onEducate}><Plus size={16} /> Learn more</button></div>
    <BookingCta url={bookingUrl || result.appointment_booking_url} urgency={result.urgency} onRequest={onBook} />
  </section>
}

