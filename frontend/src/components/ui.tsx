import { useEffect, useRef, useState, type ReactNode } from 'react'
import { AlertTriangle, Camera, Check, CircleHelp, ExternalLink, ImageOff, Info, ShieldCheck, X } from 'lucide-react'
import { fetchBlobUrl, type Explanation, type Finding, type TraceStep } from '../lib/api'

export function Heading({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description: string; action?: ReactNode }) {
  return <div className="page-heading"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h1>{title}</h1><p>{description}</p></div>{action && <div className="heading-action">{action}</div>}</div>
}

export function Notice({ title, children, tone = 'info', icon }: { title: string; children?: ReactNode; tone?: 'info' | 'warning' | 'danger' | 'success'; icon?: ReactNode }) {
  return <div className={`notice-banner tone-${tone}`} role={tone === 'danger' ? 'alert' : undefined}>
    {icon ?? (tone === 'danger' || tone === 'warning' ? <AlertTriangle size={18} /> : tone === 'success' ? <Check size={18} /> : <ShieldCheck size={18} />)}
    <div><b>{title}</b>{children && <div className="notice-body">{children}</div>}</div>
  </div>
}

export function Spinner() { return <span className="spinner" aria-label="Loading" /> }

export function Empty({ icon, title, text, action }: { icon: ReactNode; title: string; text: string; action?: ReactNode }) {
  return <div className="empty-activity"><div className="empty-icon">{icon}</div><b>{title}</b><p>{text}</p>{action}</div>
}

const STATUS_TONE: Record<string, string> = {
  review_required: 'amber', pending: 'blue', uncertain: 'amber', confirm: 'green', confirmed: 'green', edit: 'violet', reject: 'grey',
  further_evaluation: 'red', blocked_quality_gate: 'red', emergency_escalation: 'red', model_not_permitted: 'grey', complete: 'green',
  needs_more_information: 'amber', approved: 'green', draft: 'blue', rejected: 'grey', in_progress: 'blue', paused: 'amber', completed: 'violet',
  scored: 'green', not_scored: 'grey', comparison_unreliable: 'amber', passed: 'green', urgent: 'red', soon: 'amber', routine: 'green',
  research: 'amber', production: 'green', staging: 'blue', disabled: 'grey', retired: 'grey', requested: 'blue',
}
const STATUS_TEXT: Record<string, string> = {
  confirm: 'Confirmed', edit: 'Edited', reject: 'Rejected', further_evaluation: 'Further exam', pending: 'Awaiting review', uncertain: 'Uncertain',
  review_required: 'Dentist review required', blocked_quality_gate: 'Better image needed', emergency_escalation: 'Urgent care advised',
  model_not_permitted: 'Model disabled', needs_more_information: 'More detail needed',
}
export function Status({ value }: { value: string }) {
  return <span className={`pill pill-${STATUS_TONE[value] ?? 'grey'}`}>{STATUS_TEXT[value] ?? value.replaceAll('_', ' ')}</span>
}

export function ConfidenceBar({ value, band }: { value: number; band?: string }) {
  const pct = Math.round(value * 100)
  return <div className="confidence" title="How strongly the model detected the visual pattern — not the probability of disease">
    <div className="confidence-track"><div className={`confidence-fill band-${band ?? 'moderate'}`} style={{ width: `${pct}%` }} /></div>
    <span>{pct}%</span>
  </div>
}

export function QualityResult({ quality }: { quality: Record<string, any> }) {
  if (!quality) return null
  const ok = quality.accepted
  return <div className={`result-box ${ok ? 'result-success' : 'result-warning'}`}>
    <div className="result-heading">{ok ? <Check size={18} /> : <AlertTriangle size={18} />}<b>{ok ? 'Image quality checks passed' : quality.status === 'not_dental' ? 'This does not look like the right kind of image' : 'Please provide a better image'}</b></div>
    {!ok && (quality.messages?.length ? <ul className="plain-list">{quality.messages.map((m: string) => <li key={m}>{m}</li>)}</ul> : <p>{quality.reason}</p>)}
    {quality.checks && <div className="quality-checks">{Object.entries(quality.checks).map(([k, v]) => <span key={k} className={v ? 'check-pass' : 'check-fail'}>{v ? <Check size={12} /> : <X size={12} />} {k.replaceAll('_', ' ')}</span>)}</div>}
    {quality.warnings?.map((w: string) => <p className="muted-small" key={w}><Info size={12} /> {w}</p>)}
  </div>
}

export function useAuthedImage(path: string | null | undefined) {
  const [src, setSrc] = useState<string | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    let alive = true, current: string | null = null
    setSrc(null); setError(false)
    if (path) fetchBlobUrl(path).then(u => { current = u; if (alive) setSrc(u); else URL.revokeObjectURL(u) }).catch(() => alive && setError(true))
    return () => { alive = false; if (current) URL.revokeObjectURL(current) }
  }, [path])
  return { src, error }
}

export function AuthedImage({ path, alt, className }: { path: string; alt: string; className?: string }) {
  const { src, error } = useAuthedImage(path)
  if (error) return <div className={`image-placeholder ${className ?? ''}`}><ImageOff size={22} /><span>Image unavailable</span></div>
  if (!src) return <div className={`image-placeholder ${className ?? ''}`}><Spinner /></div>
  return <img src={src} alt={alt} className={className} />
}

const REVIEW_COLORS: Record<string, string> = { pending: '#0ea5e9', uncertain: '#f59e0b', confirm: '#10b981', edit: '#8b5cf6', reject: '#94a3b8', further_evaluation: '#ef4444' }

/** Original image with an interactive SVG overlay of AI-detected regions. */
export function AnnotatedViewer({ imagePath, findings, width, height, selected, onSelect, serverAnnotatedPath }: {
  imagePath: string; findings: Finding[]; width?: number | null; height?: number | null; selected?: string | null
  onSelect?: (id: string) => void; serverAnnotatedPath?: string
}) {
  const [overlay, setOverlay] = useState(true)
  const [enhanced, setEnhanced] = useState(false)
  const { src, error } = useAuthedImage(enhanced && serverAnnotatedPath ? serverAnnotatedPath : imagePath)
  const [dims, setDims] = useState<{ w: number; h: number } | null>(width && height ? { w: width, h: height } : null)
  const boxes = findings.filter(f => f.bbox)
  return <div className="viewer">
    <div className="viewer-toolbar">
      <label className="switch"><input type="checkbox" checked={overlay} onChange={e => setOverlay(e.target.checked)} disabled={enhanced} /> AI overlay</label>
      {serverAnnotatedPath && <label className="switch"><input type="checkbox" checked={enhanced} onChange={e => setEnhanced(e.target.checked)} /> Annotated export</label>}
      <span className="muted-small">{boxes.length} region{boxes.length === 1 ? '' : 's'}</span>
    </div>
    <div className="viewer-stage">
      {error ? <div className="image-placeholder"><ImageOff size={22} /><span>Image unavailable</span></div>
        : !src ? <div className="image-placeholder"><Spinner /></div>
          : <>
            <img src={src} alt="Dental image under review" onLoad={e => { const i = e.currentTarget; if (!dims) setDims({ w: i.naturalWidth, h: i.naturalHeight }) }} />
            {overlay && !enhanced && dims && <svg className="viewer-overlay" viewBox={`0 0 ${dims.w} ${dims.h}`} preserveAspectRatio="none" aria-hidden="true">
              {boxes.map(f => {
                const [x, y, w, h] = f.bbox!
                const c = REVIEW_COLORS[f.review_status] ?? '#0ea5e9'
                const active = selected === f.id
                return <g key={f.id} onClick={() => onSelect?.(f.id)} style={{ cursor: onSelect ? 'pointer' : 'default' }}>
                  <rect x={x} y={y} width={w} height={h} fill={c} fillOpacity={active ? 0.28 : 0.12} stroke={c} strokeWidth={Math.max(2, dims.w / 300) * (active ? 1.8 : 1)} rx={4} />
                  <text x={x + 4} y={Math.max(14, y - 6)} fontSize={Math.max(12, dims.w / 55)} fill={c} fontWeight={700} paintOrder="stroke" stroke="#fff" strokeWidth={3}>{f.finding_code}</text>
                </g>
              })}
            </svg>}
          </>}
    </div>
  </div>
}

export function ExplanationPanel({ explanation, citations, provider, safety }: { explanation?: Explanation; citations?: any[]; provider?: string; safety?: any }) {
  if (!explanation) return null
  const e = explanation
  return <div className="explanation">
    {e.urgency === 'urgent' ? <Notice tone="danger" title="Please seek urgent professional care">{e.summary}</Notice>
      : <p className="explanation-summary">{e.summary}</p>}
    {e.observations?.length > 0 && <section><h4>What we observed</h4><ul className="plain-list">{e.observations.map((o, i) => <li key={i}>{o.finding_code && <code>{o.finding_code}</code>} {o.text}</li>)}</ul></section>}
    {e.why_it_matters && <section><h4>Why it matters</h4><p>{e.why_it_matters}</p></section>}
    {e.possible_explanations?.length > 0 && <section><h4>Possible contributing factors</h4><ul className="plain-list">{e.possible_explanations.map(x => <li key={x}>{x}</li>)}</ul></section>}
    {e.recommended_next_step && <section><h4>What happens next</h4><p>{e.recommended_next_step}</p></section>}
    {e.questions_for_dentist?.length > 0 && <section><h4>Questions for your dentist</h4><ul className="plain-list">{e.questions_for_dentist.map(x => <li key={x}><CircleHelp size={13} /> {x}</li>)}</ul></section>}
    {e.warning_signs?.length > 0 && <section className="warning-signs"><h4>Seek prompt care if you notice</h4><ul className="plain-list">{e.warning_signs.map(x => <li key={x}>{x}</li>)}</ul></section>}
    {e.limitations?.length > 0 && <section className="limitations"><h4>Important limitations</h4><ul className="plain-list">{e.limitations.map(x => <li key={x}>{x}</li>)}</ul></section>}
    <div className="explanation-meta">
      {provider && <span>Explanation: {provider === 'template' ? 'DentEdge approved templates' : provider}</span>}
      {safety && <span className={safety.passed ? 'ok' : 'bad'}><ShieldCheck size={12} /> Safety gateway {safety.passed ? 'passed' : 'flagged'}</span>}
      {citations && citations.length > 0 && <span>Sources: {citations.map(c => `${c.title} v${c.version}`).join(' · ')}</span>}
    </div>
  </div>
}

export function FindingList({ findings, selected, onSelect, renderActions }: { findings: Finding[]; selected?: string | null; onSelect?: (id: string) => void; renderActions?: (f: Finding) => ReactNode }) {
  if (!findings.length) return null
  return <div className="finding-list">{findings.map(f => <div key={f.id} className={`finding-card ${selected === f.id ? 'selected' : ''}`} onClick={() => onSelect?.(f.id)}>
    <div className="finding-top"><code>{f.finding_code}</code><b>{f.label}</b><Status value={f.review_status} /></div>
    <div className="finding-meta">
      <span>{f.location?.description || f.location?.region || 'Location not specified'}{f.location?.tooth ? ` · tooth ${f.location.tooth}${f.location.tooth_approximate ? ' (approx.)' : ''}` : ''}</span>
      <ConfidenceBar value={f.confidence} band={f.confidence_band} />
    </div>
    {f.evidence && <p className="finding-evidence">{f.evidence}</p>}
    <div className="finding-foot"><span>{f.model}@{f.model_version}</span>{f.review_note && <span>Dentist note: {f.review_note}</span>}</div>
    {renderActions && <div onClick={e => e.stopPropagation()}>{renderActions(f)}</div>}
  </div>)}</div>
}

export function PipelineTrace({ steps }: { steps?: TraceStep[] }) {
  if (!steps?.length) return null
  return <details className="trace"><summary>Processing pipeline ({steps.length} steps)</summary>
    <ol>{steps.map((s, i) => <li key={i} className={`trace-${s.status}`}><b>{s.step.replaceAll('_', ' ')}</b><span>{s.status}{s.ms ? ` · ${s.ms} ms` : ''}{s.reason ? ` · ${s.reason}` : ''}{s.model ? ` · ${s.model}@${s.version}` : ''}</span></li>)}</ol>
  </details>
}

export function CameraCapture({ onCapture, onClose }: { onCapture: (f: File) => void; onClose: () => void }) {
  const video = useRef<HTMLVideoElement>(null)
  const [error, setError] = useState('')
  const [facing, setFacing] = useState<'user' | 'environment'>('environment')
  useEffect(() => {
    let stream: MediaStream | null = null
    if (!navigator.mediaDevices?.getUserMedia) { setError('Camera access is not supported in this browser.'); return }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: facing, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false })
      .then(s => { stream = s; if (video.current) { video.current.srcObject = s; void video.current.play() } })
      .catch(() => setError('Camera permission was denied or no camera is available.'))
    return () => stream?.getTracks().forEach(t => t.stop())
  }, [facing])
  function snap() {
    const v = video.current
    if (!v || !v.videoWidth) return
    const c = document.createElement('canvas')
    c.width = v.videoWidth; c.height = v.videoHeight
    c.getContext('2d')!.drawImage(v, 0, 0)
    c.toBlob(b => { if (b) onCapture(new File([b], `camera-${Date.now()}.jpg`, { type: 'image/jpeg' })) }, 'image/jpeg', 0.92)
  }
  return <div className="camera">
    {error ? <p className="auth-error">{error}</p> : <video ref={video} playsInline muted />}
    <div className="camera-guide">Bright, even light · teeth in focus · fill the frame</div>
    <div className="inline-actions">
      <button type="button" className="button button-primary" onClick={snap} disabled={!!error}><Camera size={16} /> Capture</button>
      <button type="button" className="button button-secondary" onClick={() => setFacing(f => f === 'user' ? 'environment' : 'user')}>Switch camera</button>
      <button type="button" className="button button-secondary" onClick={onClose}>Close</button>
    </div>
  </div>
}

export function BookingCta({ url, urgency, onRequest }: { url?: string; urgency?: string; onRequest?: () => void }) {
  return <div className={`booking-cta ${urgency === 'soon' || urgency === 'urgent' ? 'booking-urgent' : ''}`}>
    <div><b>{urgency === 'urgent' ? 'Get urgent care' : urgency === 'soon' ? 'Book a dental visit soon' : 'Talk it through with your dentist'}</b>
      <p>Your dentist reviews every AI observation and decides what it means for you.</p></div>
    <div className="inline-actions">
      {onRequest && <button className="button button-secondary" onClick={onRequest}>Request appointment</button>}
      {url && <a className="button button-primary" href={url} target="_blank" rel="noopener noreferrer">Book on DentEdge <ExternalLink size={14} /></a>}
    </div>
  </div>
}

export function formatDate(s?: string | null, withTime = false) {
  if (!s) return '—'
  try {
    const d = new Date(s.endsWith('Z') || s.includes('+') ? s : s + 'Z')
    return withTime ? d.toLocaleString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
      : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
  } catch { return '—' }
}

export function moduleName(m: string) {
  return ({ vision: 'Oral photo analysis', xray: 'X-ray analysis', xray_comparison: 'X-ray comparison', voice: 'Voice', perio: 'Periodontal chart', smile: 'Smile analysis' } as Record<string, string>)[m] || m
}

export function errorText(e: unknown) { return e instanceof Error ? e.message : 'Something went wrong' }
