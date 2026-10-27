import { useEffect, useState } from 'react'
import { ArrowRight, GitCompareArrows, ImagePlus, Sparkles, UploadCloud } from 'lucide-react'
import { api, post, type Analysis, type ImageAsset } from '../lib/api'
import { useApp, type PatientRef } from '../lib/context'
import { PatientPicker, RequirePatient } from '../components/gates'
import { AnnotatedViewer, AuthedImage, ExplanationPanel, FindingList, Heading, Notice, PipelineTrace, QualityResult, Spinner, Status, errorText, formatDate } from '../components/ui'

const TYPES: [string, string][] = [['periapical', 'Periapical'], ['bitewing', 'Bitewing'], ['panoramic', 'Panoramic'], ['unknown', 'Not sure']]

export default function XRayPage() {
  return <>
    <Heading eyebrow="DENTEDGE X-RAY AI" title="Dental X-ray workspace" description="Upload a radiograph for type detection, enhancement, anatomy localisation and dentist-reviewed annotations. Compare with a previous X-ray to see what changed." action={<PatientPicker compact />} />
    <RequirePatient>{p => <XRayWorkflow patient={p} />}</RequirePatient>
  </>
}

function XRayWorkflow({ patient }: { patient: PatientRef }) {
  const { user, toast } = useApp()
  const [file, setFile] = useState<File | null>(null)
  const [type, setType] = useState('unknown')
  const [asset, setAsset] = useState<ImageAsset | null>(null)
  const [result, setResult] = useState<Analysis | null>(null)
  const [history, setHistory] = useState<ImageAsset[]>([])
  const [compareWith, setCompareWith] = useState('')
  const [comparison, setComparison] = useState<Analysis | null>(null)
  const [busy, setBusy] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const loadHistory = () => api<ImageAsset[]>(`/images?kind=xray&patient_id=${patient.id}`).then(setHistory).catch(() => undefined)
  useEffect(() => { void loadHistory() }, [patient.id])

  async function upload() {
    if (!file) return
    setBusy('upload'); setResult(null); setComparison(null)
    try {
      const body = new FormData(); body.append('file', file); body.append('xray_type', type)
      if (user.role === 'dentist') body.append('patient_id', patient.id)
      const a = await post<ImageAsset>('/xrays', body); setAsset(a); void loadHistory()
      toast(a.quality.accepted ? 'X-ray accepted' : 'X-ray needs attention')
    } catch (e) { toast(errorText(e)) } finally { setBusy('') }
  }
  async function analyze(id = asset?.id) {
    if (!id) return
    setBusy('analyze')
    try { setResult(await post<Analysis>('/xray-analysis', { image_id: id })); setSelected(null) } catch (e) { toast(errorText(e)) } finally { setBusy('') }
  }
  async function compare() {
    const current = asset?.id
    if (!current || !compareWith) return
    setBusy('compare')
    try { setComparison(await post<Analysis>('/xray-comparison', { previous_image_id: compareWith, current_image_id: current })) } catch (e) { toast(errorText(e)) } finally { setBusy('') }
  }
  const usable = history.filter(h => h.quality?.accepted)
  return <>
    <Notice title="Research-stage radiograph processing">Highlighted areas are candidates for dentist review — they are not diagnoses. Findings are only generated for X-ray types enabled in the model registry.</Notice>
    <div className="workflow-layout">
      <section className="panel upload-panel">
        <div className="panel-heading"><div><h2>Upload a radiograph</h2><p>Original image, PNG/JPEG/WebP · max 12 MB</p></div></div>
        <div className="field-label">X-ray type</div>
        <select className="select-field" value={type} onChange={e => setType(e.target.value)}>{TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <label className={`dropzone ${file ? 'has-file' : ''}`}><input type="file" accept="image/jpeg,image/png,image/webp" onChange={e => { setFile(e.target.files?.[0] ?? null); setAsset(null) }} />
          {file ? <><div className="file-preview-icon"><ImagePlus size={25} /></div><b>{file.name}</b><span>{(file.size / 1024 / 1024).toFixed(2)} MB</span></> : <><div className="upload-cloud"><UploadCloud size={26} /></div><b>Drop the X-ray here</b><span>or <strong>browse files</strong></span></>}
        </label>
        <button className="button button-primary full-button" disabled={!file || !!busy || !!asset} onClick={upload}>{busy === 'upload' ? <Spinner /> : <UploadCloud size={17} />} Upload and validate <ArrowRight size={16} /></button>
        {asset && <QualityResult quality={asset.quality} />}
        {asset?.quality.accepted && <button className="button button-secondary full-button" disabled={!!busy} onClick={() => analyze()}>{busy === 'analyze' ? <Spinner /> : <Sparkles size={16} />} Run X-ray analysis</button>}
      </section>
      <aside className="panel form-panel">
        <h3><GitCompareArrows size={18} /> Historical comparison</h3>
        <p className="panel-copy">Align a previous X-ray with the current one and highlight areas that look different. A difference does not by itself mean a condition has progressed.</p>
        <div className="field-label">Current X-ray</div>
        <select className="select-field" value={asset?.id ?? ''} onChange={e => setAsset(usable.find(h => h.id === e.target.value) ?? null)}><option value="">Select…</option>{usable.map(h => <option key={h.id} value={h.id}>{formatDate(h.created_at)} · {h.view} · {h.filename}</option>)}</select>
        <div className="field-label">Previous X-ray</div>
        <select className="select-field" value={compareWith} onChange={e => setCompareWith(e.target.value)}><option value="">Select…</option>{usable.filter(h => h.id !== asset?.id).map(h => <option key={h.id} value={h.id}>{formatDate(h.created_at)} · {h.view} · {h.filename}</option>)}</select>
        <div className="inline-actions">
          <button className="button button-secondary" disabled={!asset || !!busy} onClick={() => analyze()}>{busy === 'analyze' && <Spinner />} Analyse current</button>
          <button className="button button-primary" disabled={!asset || !compareWith || !!busy} onClick={compare}>{busy === 'compare' && <Spinner />} Compare</button>
        </div>
      </aside>
    </div>
    {result && <section className="panel analysis-result">
      <div className="panel-heading"><div><h2>X-ray analysis</h2><p>Detected type: <b>{result.result.xray_type?.detected_type}</b> ({Math.round((result.result.xray_type?.confidence ?? 0) * 100)}%) · {result.result.anatomy?.structure_count ?? 0} dental structures localised</p></div><Status value={result.status} /></div>
      {result.result.xray_type?.warning && <Notice tone="warning" title="Please confirm the X-ray type">{result.result.xray_type.warning}</Notice>}
      <div className="result-grid">
        <AnnotatedViewer imagePath={`/images/${result.image_asset_id}`} findings={result.findings} selected={selected} onSelect={setSelected} serverAnnotatedPath={result.annotated_images[0]?.url} />
        <div><FindingList findings={result.findings} selected={selected} onSelect={setSelected} /><ExplanationPanel explanation={result.result.explanation} citations={result.result.citations} provider={result.result.explanation_provider} safety={result.result.safety} /></div>
      </div>
      <PipelineTrace steps={result.result.pipeline_trace} />
    </section>}
    {comparison && <section className="panel analysis-result">
      <div className="panel-heading"><div><h2>Historical comparison</h2><p>Anatomy alignment: {comparison.result.alignment?.success ? `${comparison.result.alignment.inliers} landmark matches` : comparison.result.alignment?.reason}</p></div><Status value={comparison.status} /></div>
      <div className="compare-summary">
        {[['Previous examination', comparison.result.comparison?.previous], ['Current examination', comparison.result.comparison?.current], ['Region', comparison.result.comparison?.region ?? '—'], ['AI confidence', comparison.result.comparison?.ai_confidence ?? '—'], ['Dentist review', comparison.result.comparison?.dentist_review]].map(([k, v]) => <div key={k}><span>{k}</span><b>{v}</b></div>)}
      </div>
      <p className="muted-small">{comparison.result.comparison?.note}</p>
      <div className="compare-images">
        <div><div className="result-image-label">Previous</div><AuthedImage path={`/images/${comparison.result.previous_image_id}`} alt="Previous X-ray" className="compare-img" /></div>
        <div><div className="result-image-label">Current with changes</div><AnnotatedViewer imagePath={`/images/${comparison.result.current_image_id}`} findings={comparison.findings} /></div>
      </div>
      <FindingList findings={comparison.findings} />
    </section>}
  </>
}
