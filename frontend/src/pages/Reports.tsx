import { useEffect, useState } from 'react'
import { ExternalLink, FileText, Printer } from 'lucide-react'
import { api, type AnalysisSummary } from '../lib/api'
import { useApp, type PatientRef } from '../lib/context'
import { PatientPicker, RequirePatient } from '../components/gates'
import { AuthedImage, Empty, Heading, Spinner, Status, errorText, formatDate, moduleName } from '../components/ui'

export default function ReportsPage() {
  return <>
    <Heading eyebrow="REPORT CENTER" title="Reports" description="Patient-friendly assessments and detailed dentist reports generated from structured, reviewed data." action={<PatientPicker compact />} />
    <RequirePatient>{p => <Reports patient={p} />}</RequirePatient>
  </>
}

function Reports({ patient }: { patient: PatientRef }) {
  const { user, focusAnalysisId, toast } = useApp()
  const [list, setList] = useState<AnalysisSummary[] | null>(null)
  const [sel, setSel] = useState<string | null>(focusAnalysisId)
  const [type, setType] = useState<'patient' | 'dentist'>(user.role === 'dentist' ? 'dentist' : 'patient')
  const [report, setReport] = useState<any>(null)
  useEffect(() => { api<AnalysisSummary[]>(`/analyses?patient_id=${patient.id}`).then(a => { setList(a); if (!sel && a[0]) setSel(a[0].id) }).catch(() => setList([])) }, [patient.id])
  useEffect(() => { if (!sel) return; setReport(null); api(`/analyses/${sel}/report?report_type=${type}`).then(setReport).catch(e => toast(errorText(e))) }, [sel, type])
  if (!list) return <div className="panel"><Spinner /></div>
  if (!list.length) return <div className="panel"><Empty icon={<FileText size={22} />} title="No reports yet" text="Complete an analysis to generate a report." /></div>
  return <div className="report-layout">
    <aside className="panel no-print"><div className="history-list">{list.map(a => <button key={a.id} className={`history-row ${sel === a.id ? 'active' : ''}`} onClick={() => setSel(a.id)}><span>{moduleName(a.module)}<br /><small>{formatDate(a.created_at, true)}</small></span><Status value={a.status} /></button>)}</div></aside>
    <section className="panel report-doc">
      <div className="inline-actions no-print">
        {user.role === 'dentist' && <div className="segmented">{(['patient', 'dentist'] as const).map(t => <button key={t} className={type === t ? 'selected' : ''} onClick={() => setType(t)}>{t === 'patient' ? 'Patient report' : 'Dentist report'}</button>)}</div>}
        <button className="button button-secondary" onClick={() => window.print()}><Printer size={15} /> Print / save PDF</button>
      </div>
      {!report ? <Spinner /> : type === 'patient' ? <PatientReport r={report} /> : <DentistReport r={report} />}
    </section>
  </div>
}

function Section({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return <section className="report-section"><h3><span>{n}</span>{title}</h3>{children}</section>
}

function PatientReport({ r }: { r: any }) {
  const obs = [...(r.visual_observations ?? []), ...(r.xray_observations ?? [])]
  return <article>
    <header className="report-header"><div><div className="eyebrow">DENTEDGE AI</div><h2>{r.title}</h2><p>{r.patient} · {formatDate(r.date, true)} · {moduleName(r.module)}</p></div><Status value={r.urgency} /></header>
    <Section n={1} title="Images analysed"><p>{r.images_analyzed.length ? r.images_analyzed.map((i: any) => i.view?.replaceAll('_', ' ') ?? 'image').join(', ') : '—'}</p>
      <div className="report-thumbs">{r.images_analyzed.map((i: any) => i.image_id && <AuthedImage key={i.image_id} path={`/images/${i.image_id}`} alt={i.view ?? 'image'} className="thumb" />)}</div></Section>
    <Section n={2} title="Image quality"><ul className="plain-list">{r.image_quality.map((q: any, i: number) => <li key={i}>{q.accepted ? '✓ Passed' : '✗ Not usable'} — {q.note}</li>)}</ul></Section>
    <Section n={3} title={r.module.startsWith('xray') ? 'X-ray observations' : 'Visual observations'}>{obs.length ? <table className="data-table"><thead><tr><th>Code</th><th>Observation</th><th>Where</th><th>AI confidence</th><th>Dentist review</th></tr></thead><tbody>{obs.map((o: any) => <tr key={o.finding_code}><td><code>{o.finding_code}</code></td><td>{o.observation}</td><td>{o.location}</td><td>{o.ai_confidence}</td><td>{o.review_status}</td></tr>)}</tbody></table> : <p>No observations were generated.</p>}</Section>
    <Section n={4} title="Your symptoms"><p>{r.patient_symptoms || 'None reported.'}</p></Section>
    <Section n={5} title="About AI confidence"><p>{r.ai_confidence_note}</p></Section>
    <Section n={6} title="Explanation"><p>{r.patient_friendly_explanation}</p>{r.possible_explanations?.length > 0 && <ul className="plain-list">{r.possible_explanations.map((x: string) => <li key={x}>{x}</li>)}</ul>}</Section>
    <Section n={7} title="Recommended follow-up"><p>{r.recommended_follow_up}</p></Section>
    <Section n={8} title="Questions for your dentist"><ul className="plain-list">{r.questions_for_dentist.map((q: string) => <li key={q}>{q}</li>)}</ul></Section>
    {r.warning_signs?.length > 0 && <Section n={9} title="Seek prompt care if you notice"><ul className="plain-list">{r.warning_signs.map((q: string) => <li key={q}>{q}</li>)}</ul></Section>}
    <Section n={10} title="Important limitations"><ul className="plain-list">{r.important_limitations.map((q: string) => <li key={q}>{q}</li>)}</ul></Section>
    <Section n={11} title="Next step"><a className="button button-primary" href={r.appointment_cta.url} target="_blank" rel="noopener noreferrer">{r.appointment_cta.label} <ExternalLink size={14} /></a></Section>
    <footer className="report-foot">Model {r.model.name}@{r.model.version} · rules {r.model.rules_version}{r.sources?.length ? ` · Sources: ${r.sources.map((s: any) => `${s.title} v${s.version}`).join('; ')}` : ''}</footer>
  </article>
}

function DentistReport({ r }: { r: any }) {
  const a = r.ai_analysis_summary
  return <article>
    <header className="report-header"><div><div className="eyebrow">DENTEDGE AI · CLINICAL</div><h2>{r.title}</h2><p>{r.patient_information.name} · {r.patient_information.email} · DOB {r.patient_information.date_of_birth ?? '—'}</p></div><Status value={a.status} /></header>
    <Section n={1} title="AI analysis summary"><p>{a.summary}</p><p className="muted-small">{moduleName(a.module)} · {a.model}@{a.model_version} · rules {a.rules_version} · prompt {a.prompt_version} · {formatDate(a.created_at, true)}</p></Section>
    {r.xray_type && <Section n={2} title="X-ray type"><p>{r.xray_type.detected_type} ({Math.round(r.xray_type.confidence * 100)}%) · declared {r.xray_type.declared_type ?? '—'} {r.xray_type.warning ? `· ${r.xray_type.warning}` : ''}</p></Section>}
    <Section n={3} title="Findings"><table className="data-table"><thead><tr><th>Code</th><th>Finding</th><th>Tooth / region</th><th>Conf.</th><th>Evidence</th><th>Review</th></tr></thead>
      <tbody>{r.findings.map((f: any) => <tr key={f.id}><td><code>{f.finding_code}</code></td><td>{f.label}</td><td>{f.location?.tooth ? `${f.location.tooth} · ` : ''}{f.location?.region}</td><td>{Math.round(f.confidence * 100)}%</td><td>{f.evidence}</td><td><Status value={f.review_status} /></td></tr>)}</tbody></table></Section>
    <Section n={4} title="Annotations"><div className="report-thumbs">{r.annotations.map((x: any) => <AuthedImage key={x.image_id} path={x.url} alt="Annotated" className="thumb wide" />)}</div></Section>
    <Section n={5} title="Evidence sources"><ul className="plain-list">{r.evidence.map((e: any) => <li key={e.slug}>{e.title} v{e.version} — {e.reviewer} (review by {e.review_date})</li>)}</ul></Section>
    <Section n={6} title="Historical comparison"><p>{r.historical_comparison ? `${r.historical_comparison.current} ${r.historical_comparison.region ? '· ' + r.historical_comparison.region : ''}` : 'No comparison on record.'}</p></Section>
    <Section n={7} title="Patient symptoms"><p>{r.patient_symptoms?.summary ?? 'None recorded.'}</p></Section>
    <Section n={8} title="Perio data"><p>{r.perio_data ? `${r.perio_data.sites_recorded} sites · mean PD ${r.perio_data.mean_probing_depth ?? '—'} · ≥4 mm ${r.perio_data.sites_4mm_or_more} · BOP ${r.perio_data.bleeding_on_probing_percent ?? '—'}% (${r.perio_data.status})` : 'No chart.'}</p></Section>
    <Section n={9} title="AI-generated draft notes"><pre className="note-pre">{r.ai_generated_draft_notes?.note_text ?? 'No scribe notes.'}</pre></Section>
    <Section n={10} title="Dentist review"><ul className="plain-list">{r.dentist_review.map((d: any) => <li key={d.finding_code}><code>{d.finding_code}</code> {d.decision} — {d.note ?? ''} <span className="muted-small">{formatDate(d.reviewed_at, true)}</span></li>)}</ul></Section>
    <Section n={11} title="Final clinical findings"><ul className="plain-list">{r.final_clinical_findings.map((c: any, i: number) => <li key={i}><b>{c.label}</b> {c.location?.tooth ? `· tooth ${c.location.tooth}` : ''} · {c.status} {c.notes ? `— ${c.notes}` : ''}</li>)}</ul></Section>
  </article>
}
