import { useEffect, useState } from 'react'
import { Camera, Smile, Sparkles, UploadCloud } from 'lucide-react'
import { api, post, type ImageAsset } from '../lib/api'
import { useApp, type PatientRef } from '../lib/context'
import { PatientPicker, RequirePatient } from '../components/gates'
import { AuthedImage, CameraCapture, Heading, Notice, QualityResult, Spinner, errorText, formatDate } from '../components/ui'

type SmileResult = { id: string; image_id: string; status: string; overall: number | null; metrics: Record<string, number>; descriptions?: Record<string, string>; progress?: any; reason?: string; disclaimer: string; created_at: string }
const LABELS: Record<string, string> = { symmetry: 'Symmetry', alignment: 'Alignment', staining: 'Staining', tooth_visibility: 'Tooth visibility', gum_display: 'Gum display', smile_balance: 'Smile balance' }

export default function SmilePage() {
  return <>
    <Heading eyebrow="DENTEDGE SMILE" title="Check my smile" description="A cosmetic, visual assessment of your smile photo — symmetry, alignment, visible staining and balance. It is not a medical score." action={<PatientPicker compact />} />
    <RequirePatient>{p => <SmileWorkflow patient={p} />}</RequirePatient>
  </>
}

function Ring({ value }: { value: number }) {
  const r = 52, c = 2 * Math.PI * r
  return <svg className="score-ring" viewBox="0 0 128 128" role="img" aria-label={`Smile score ${value} out of 100`}>
    <circle cx="64" cy="64" r={r} className="ring-bg" /><circle cx="64" cy="64" r={r} className="ring-fg" strokeDasharray={`${(value / 100) * c} ${c}`} transform="rotate(-90 64 64)" />
    <text x="64" y="62" textAnchor="middle" className="ring-value">{value}</text><text x="64" y="82" textAnchor="middle" className="ring-sub">/ 100</text>
  </svg>
}

function SmileWorkflow({ patient }: { patient: PatientRef }) {
  const { user, toast } = useApp()
  const [file, setFile] = useState<File | null>(null)
  const [camera, setCamera] = useState(false)
  const [asset, setAsset] = useState<ImageAsset | null>(null)
  const [result, setResult] = useState<SmileResult | null>(null)
  const [history, setHistory] = useState<SmileResult[]>([])
  const [busy, setBusy] = useState(false)
  const load = () => api<SmileResult[]>(`/smile-analysis?patient_id=${patient.id}`).then(setHistory).catch(() => undefined)
  useEffect(() => { void load() }, [patient.id])
  async function run() {
    if (!file) return
    setBusy(true); setResult(null)
    try {
      const body = new FormData(); body.append('file', file); body.append('view', 'front_smile'); body.append('image_kind', 'smile')
      if (user.role === 'dentist') body.append('patient_id', patient.id)
      const a = await post<ImageAsset>('/oral-images', body); setAsset(a)
      if (a.quality.accepted) { setResult(await post<SmileResult>('/smile-analysis', { image_id: a.id })); void load() }
    } catch (e) { toast(errorText(e)) } finally { setBusy(false) }
  }
  return <>
    <div className="workflow-layout">
      <section className="panel upload-panel">
        <div className="panel-heading"><div><h2>Front-facing smile photo</h2><p>Natural smile, face the camera, even lighting.</p></div></div>
        {camera ? <CameraCapture onCapture={f => { setFile(f); setCamera(false); setAsset(null) }} onClose={() => setCamera(false)} /> :
          <label className={`dropzone ${file ? 'has-file' : ''}`}><input type="file" accept="image/jpeg,image/png,image/webp" onChange={e => { setFile(e.target.files?.[0] ?? null); setAsset(null) }} />
            {file ? <><img className="dropzone-preview" src={URL.createObjectURL(file)} alt="Selected smile" /><b>{file.name}</b></> : <><div className="upload-cloud"><UploadCloud size={26} /></div><b>Drop your smile photo</b><span>or <strong>browse</strong></span></>}
          </label>}
        <div className="inline-actions"><button className="button button-secondary" onClick={() => setCamera(c => !c)}><Camera size={16} /> Camera</button>
          <button className="button button-primary" disabled={!file || busy} onClick={run}>{busy ? <Spinner /> : <Sparkles size={16} />} Get my Smile Score</button></div>
        {asset && !asset.quality.accepted && <QualityResult quality={asset.quality} />}
      </section>
      <section className="panel smile-panel">
        {!result ? <div className="smile-empty"><div className="guidance-symbol peach"><Smile size={23} /></div><h3>Your Smile Score</h3><p>Upload a photo to see your cosmetic smile metrics.</p></div>
          : result.status !== 'scored' ? <Notice tone="warning" title="We could not score this photo">{result.reason}</Notice> : <>
            <div className="smile-score"><Ring value={result.overall!} /><div><h3>DentEdge Smile Score</h3><p className="muted-small">{result.disclaimer}</p>
              {result.progress && <p className={result.progress.overall_change >= 0 ? 'delta-up' : 'delta-down'}>{result.progress.overall_change >= 0 ? '▲' : '▼'} {Math.abs(result.progress.overall_change)} since last photo</p>}</div></div>
            {Object.entries(result.metrics).map(([k, v]) => <div className="metric-bar" key={k} title={result.descriptions?.[k]}><span>{LABELS[k] ?? k}</span><div className="confidence-track"><div className="confidence-fill band-high" style={{ width: `${v}%` }} /></div><b>{v}</b>
              {result.progress?.metric_changes?.[k] ? <small className={result.progress.metric_changes[k] >= 0 ? 'delta-up' : 'delta-down'}>{result.progress.metric_changes[k] > 0 ? '+' : ''}{result.progress.metric_changes[k]}</small> : null}</div>)}
            {result.progress?.note && <p className="muted-small">{result.progress.note}</p>}
          </>}
      </section>
    </div>
    {history.filter(h => h.status === 'scored').length > 0 && <section className="panel"><h2>Progress</h2><div className="smile-history">{history.filter(h => h.status === 'scored').map(h => <div key={h.id} className="smile-history-item">
      <AuthedImage path={`/images/${h.image_id}`} alt="Smile photo" className="thumb" /><b>{h.overall}/100</b><span className="muted-small">{formatDate(h.created_at)}</span></div>)}</div></section>}
  </>
}
