import { useEffect, useState } from 'react'
import { Activity, Check, Mic, MicOff, Pause, Play, Plus, RotateCcw, Send, Volume2 } from 'lucide-react'
import { api, post, type ApiError } from '../lib/api'
import { useApp, type PatientRef } from '../lib/context'
import { useDictation } from '../lib/speech'
import { PatientPicker, RequirePatient } from '../components/gates'
import { Empty, Heading, Notice, Spinner, Status, errorText, formatDate } from '../components/ui'

type Site = { probing_depth?: number; bleeding?: number; plaque?: number; recession?: number; suppuration?: number }
type Tooth = { sites: Record<string, Site>; mobility: number | null; furcation: number | null; missing: boolean }
type Chart = {
  id: string; status: string; state: { status: string; position: { tooth: string | null; pass: string; site: string | null }; missing: string[]; warnings: string[]; can_undo: boolean; last?: any }
  chart: { teeth: Record<string, Tooth>; summary: any }; messages?: string[]; patient_report?: any; created_at: string
}
const UPPER = ['18', '17', '16', '15', '14', '13', '12', '11', '21', '22', '23', '24', '25', '26', '27', '28']
const LOWER = ['48', '47', '46', '45', '44', '43', '42', '41', '31', '32', '33', '34', '35', '36', '37', '38']

export default function PerioPage() {
  const { user } = useApp()
  return <>
    <Heading eyebrow="DENTEDGE PERIO" title="Periodontal charting" description={user.role === 'dentist' ? 'Hands-free voice charting with a tooth/site state machine, validation and confirmation.' : 'Gum measurements recorded and confirmed by your dentist.'} action={<PatientPicker compact />} />
    <RequirePatient>{p => user.role === 'dentist' ? <PerioDentist patient={p} /> : <PerioPatient patient={p} />}</RequirePatient>
  </>
}

function speak(text: string) { try { const u = new SpeechSynthesisUtterance(text); u.rate = 1.05; window.speechSynthesis.cancel(); window.speechSynthesis.speak(u) } catch { /* optional */ } }

function PerioDentist({ patient }: { patient: PatientRef }) {
  const { toast } = useApp()
  const [chart, setChart] = useState<Chart | null>(null)
  const [cmd, setCmd] = useState('')
  const [log, setLog] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [readback, setReadback] = useState(true)
  const [list, setList] = useState<any[]>([])
  const loadList = () => api<any[]>(`/perio/sessions?patient_id=${patient.id}`).then(setList).catch(() => undefined)
  useEffect(() => { void loadList(); setChart(null); setLog([]) }, [patient.id])
  async function send(command: string) {
    if (!chart || !command.trim()) return
    setBusy(true)
    try {
      const r = await post<Chart>('/perio/measurements', { session_id: chart.id, command })
      setChart(r); setLog(l => [`› ${command}`, ...(r.messages ?? []), ...l].slice(0, 60)); setCmd('')
      if (readback && r.messages?.length) speak(r.messages.join(' '))
    } catch (e) { const m = errorText(e); setLog(l => [`› ${command}`, `⚠ ${m}`, ...l]); if (readback) speak(m) } finally { setBusy(false) }
  }
  const dict = useDictation(t => { void send(t) })
  async function create() { try { const c = await post<Chart>('/perio/session', { patient_id: patient.id }); setChart(c); setLog(['New chart created. Say “start” to begin at tooth 18.']); void loadList() } catch (e) { toast(errorText(e)) } }
  async function open(id: string) { try { setChart(await api<Chart>(`/perio/session/${id}`)) } catch (e) { toast(errorText(e)) } }
  async function confirm() { if (!chart) return; try { setChart(await post<Chart>(`/perio/session/${chart.id}/confirm`)); toast('Chart confirmed and added to the patient record'); void loadList() } catch (e) { toast(errorText(e as ApiError)) } }
  if (!chart) return <div className="panel form-panel">
    <h2>Charts for {patient.full_name}</h2>
    <button className="button button-primary" onClick={create}><Plus size={16} /> New periodontal chart</button>
    {list.length ? <div className="history-list">{list.map(c => <button className="history-row" key={c.id} onClick={() => open(c.id)}><span>{formatDate(c.created_at, true)} · {c.summary.sites_recorded} sites</span><Status value={c.status} /></button>)}</div> : <p className="panel-copy">No charts yet.</p>}
  </div>
  const pos = chart.state.position
  const locked = chart.status === 'confirmed'
  return <>
    <div className="perio-layout">
      <section className="panel form-panel">
        <div className="panel-heading"><div><h2>Voice control</h2><p>Position: <b>tooth {pos.tooth ?? '—'}</b> · {pos.pass} · site {pos.site ?? '—'}</p></div><Status value={chart.status} /></div>
        {!locked && <>
          <div className="mic">
            <button className={`mic-button ${dict.listening ? 'live' : ''}`} onClick={dict.listening ? dict.stop : dict.start} disabled={!dict.supported} aria-label="Toggle voice charting">{dict.listening ? <MicOff size={20} /> : <Mic size={20} />}</button>
            <span className="muted-small">{dict.supported ? (dict.listening ? dict.interim || 'Listening — say “3 2 3”, “bleeding”, “jump to 26”…' : 'Hands-free voice charting') : 'Browser voice input unavailable — type commands below'}</span>
          </div>
          <form className="command-row" onSubmit={e => { e.preventDefault(); void send(cmd) }}>
            <input className="text-field" value={cmd} onChange={e => setCmd(e.target.value)} placeholder="e.g. 3 2 3 · bleeding · mobility 1 · furcation 2 · recession 2 · jump to 26 lingual · 17 missing" aria-label="Perio command" />
            <button className="button button-primary" disabled={busy || !cmd.trim()}>{busy ? <Spinner /> : <Send size={15} />}</button>
          </form>
          <div className="chip-row">
            {[['start', <Play size={13} key="p" />], ['pause', <Pause size={13} key="pa" />], ['resume', <Play size={13} key="r" />], ['repeat', <Volume2 size={13} key="re" />], ['undo', <RotateCcw size={13} key="u" />], ['bleeding', null], ['plaque', null], ['next tooth', null], ['complete', <Check size={13} key="c" />]].map(([c, icon]) =>
              <button key={c as string} className="chip" disabled={busy} onClick={() => send(c as string)}>{icon}{c as string}</button>)}
          </div>
          <label className="switch"><input type="checkbox" checked={readback} onChange={e => setReadback(e.target.checked)} /> Spoken read-back</label>
        </>}
        {chart.state.warnings?.length > 0 && <Notice tone="warning" title="Please verify">{chart.state.warnings.slice(-3).join(' ')}</Notice>}
        <div className="command-log">{log.map((l, i) => <div key={i} className={l.startsWith('⚠') ? 'bad' : l.startsWith('›') ? 'cmd' : ''}>{l}</div>)}</div>
      </section>
      <section className="panel">
        <div className="panel-heading"><div><h2>Chart</h2><p>Probing depth (mm) per site · red = bleeding · ● = plaque</p></div><button className="text-button" onClick={() => setChart(null)}>All charts</button></div>
        <PerioGrid teeth={chart.chart.teeth} current={pos} onPick={t => !locked && send(`jump to ${t}`)} />
        <PerioSummary s={chart.chart.summary} />
        {!locked ? <button className="button button-primary" onClick={confirm}><Check size={16} /> Confirm chart</button> :
          chart.patient_report && <div className="result-box result-success"><b>Patient summary</b><p>{chart.patient_report.summary}</p></div>}
      </section>
    </div>
  </>
}

function PerioGrid({ teeth, current, onPick }: { teeth: Record<string, Tooth>; current?: { tooth: string | null; pass: string }; onPick?: (t: string) => void }) {
  const row = (ids: string[], label: string) => <div className="perio-row"><div className="perio-row-label">{label}</div>{ids.map(t => {
    const d = teeth[t]
    const cell = (sites: string[]) => <div className="perio-sites">{sites.map(s => { const v = d?.sites?.[s] ?? {}; const pd = v.probing_depth; return <span key={s} className={`pd ${pd == null ? '' : pd >= 6 ? 'pd-high' : pd >= 4 ? 'pd-mid' : 'pd-ok'} ${v.bleeding ? 'bop' : ''}`} title={`${t} ${s}`}>{pd ?? '·'}{v.plaque ? '●' : ''}</span> })}</div>
    return <button key={t} className={`perio-tooth ${d?.missing ? 'missing' : ''} ${current?.tooth === t ? 'current' : ''}`} onClick={() => onPick?.(t)} title={`Tooth ${t}`}>
      {cell(['DB', 'B', 'MB'])}<div className="tooth-id">{t}{d?.mobility ? <sup>M{d.mobility}</sup> : null}{d?.furcation ? <sup>F{d.furcation}</sup> : null}</div>{cell(['DL', 'L', 'ML'])}
    </button>
  })}</div>
  return <div className="perio-grid">{row(UPPER, 'Upper')}{row(LOWER, 'Lower')}</div>
}

function PerioSummary({ s }: { s: any }) {
  return <div className="stat-row">
    {[['Sites', s.sites_recorded], ['Mean PD', s.mean_probing_depth ?? '—'], ['≥4 mm', s.sites_4mm_or_more], ['≥6 mm', s.sites_6mm_or_more], ['BOP', s.bleeding_on_probing_percent != null ? `${s.bleeding_on_probing_percent}%` : '—'], ['Plaque', s.plaque_percent != null ? `${s.plaque_percent}%` : '—'], ['Missing', s.missing_teeth?.length ?? 0]].map(([k, v]) => <div className="stat" key={k as string}><span>{k}</span><b>{v}</b></div>)}
  </div>
}

function PerioPatient({ patient }: { patient: PatientRef }) {
  const [list, setList] = useState<any[] | null>(null)
  const [open, setOpen] = useState<Chart | null>(null)
  useEffect(() => { api<any[]>(`/perio/sessions?patient_id=${patient.id}`).then(setList).catch(() => setList([])) }, [patient.id])
  if (!list) return <div className="panel"><Spinner /></div>
  if (!list.length) return <div className="panel"><Empty icon={<Activity size={22} />} title="No confirmed gum charts yet" text="Your dentist records gum measurements during your visit. Confirmed charts appear here." /></div>
  return <div className="panel">
    <div className="history-list">{list.map(c => <button key={c.id} className="history-row" onClick={() => api<Chart>(`/perio/session/${c.id}`).then(setOpen)}><span>{formatDate(c.confirmed_at || c.created_at)} · {c.summary.sites_recorded} sites measured</span><Status value={c.status} /></button>)}</div>
    {open && <><PerioGrid teeth={open.chart.teeth} /><PerioSummary s={open.chart.summary} />{open.patient_report && <div className="result-box result-success"><p>{open.patient_report.summary}</p><p className="muted-small">{open.patient_report.note}</p><ul className="plain-list">{open.patient_report.questions_for_dentist.map((q: string) => <li key={q}>{q}</li>)}</ul></div>}</>}
  </div>
}
