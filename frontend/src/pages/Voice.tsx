import { useEffect, useState } from 'react'
import { AudioLines, Check, ClipboardCheck, Mic, MicOff, Send, Square, X } from 'lucide-react'
import { api, patch, post } from '../lib/api'
import { useApp, type PatientRef } from '../lib/context'
import { useDictation, useServerRecorder } from '../lib/speech'
import { PatientPicker, RequirePatient } from '../components/gates'
import { BookingCta, Heading, Notice, Spinner, Status, errorText, formatDate } from '../components/ui'

type Session = { id: string; status: string; transcript: string; structured: any; emergency: boolean; created_at: string; message?: string; session_type: string }

function MicButton({ patientId, purpose, onText }: { patientId?: string; purpose: string; onText: (t: string, seg?: any[]) => void }) {
  const [server, setServer] = useState(false)
  useEffect(() => { api<{ server_transcription: boolean }>('/voice/capabilities').then(c => setServer(c.server_transcription)).catch(() => undefined) }, [])
  const dict = useDictation(t => onText(t))
  const rec = useServerRecorder(patientId, purpose, onText)
  if (dict.supported) return <div className="mic">
    <button type="button" className={`mic-button ${dict.listening ? 'live' : ''}`} onClick={dict.listening ? dict.stop : dict.start} aria-label={dict.listening ? 'Stop dictation' : 'Start dictation'}>{dict.listening ? <MicOff size={20} /> : <Mic size={20} />}</button>
    <span className="muted-small">{dict.listening ? (dict.interim || 'Listening…') : 'Tap to speak'}</span>{dict.error && <span className="auth-error">{dict.error}</span>}
  </div>
  if (server) return <div className="mic">
    <button type="button" className={`mic-button ${rec.recording ? 'live' : ''}`} onClick={rec.recording ? rec.stop : rec.start} disabled={rec.busy}>{rec.busy ? <Spinner /> : rec.recording ? <Square size={18} /> : <Mic size={20} />}</button>
    <span className="muted-small">{rec.recording ? 'Recording… tap to stop' : rec.busy ? 'Transcribing…' : 'Record'}</span>{rec.error && <span className="auth-error">{rec.error}</span>}
  </div>
  return <span className="muted-small">Voice input is unavailable in this browser — type instead.</span>
}

export default function VoicePage() {
  return <>
    <Heading eyebrow="DENTEDGE VOICE" title="Tell us your symptoms" description="Describe what you are experiencing by voice or text. DentEdge structures it for your dentist and asks follow-up questions when something important is missing." action={<PatientPicker compact />} />
    <RequirePatient>{p => <SymptomIntake patient={p} />}</RequirePatient>
  </>
}

function SymptomIntake({ patient }: { patient: PatientRef }) {
  const { user, toast, bookingUrl } = useApp()
  const [text, setText] = useState('')
  const [session, setSession] = useState<Session | null>(null)
  const [turns, setTurns] = useState<{ who: 'you' | 'ai'; text: string }[]>([])
  const [busy, setBusy] = useState(false)
  async function send() {
    if (!text.trim()) return
    setBusy(true)
    const said = text.trim()
    try {
      const r = await post<Session>('/voice/symptoms', { transcript: said, session_id: session?.id, patient_id: user.role === 'dentist' ? patient.id : undefined, source: 'text' })
      setSession(r); setText('')
      const s = r.structured
      const reply = r.emergency ? r.message! : (s.reply || (s.follow_up_questions?.length ? s.follow_up_questions.join(' ') : r.message!))
      setTurns(t => [...t, { who: 'you', text: said }, { who: 'ai', text: reply }])
    } catch (e) { toast(errorText(e)) } finally { setBusy(false) }
  }
  function reset() { setSession(null); setTurns([]); setText('') }
  const s = session?.structured
  return <>
    {session?.emergency && <Notice tone="danger" title="Please seek urgent professional care now">{session.message}<div className="emergency-signals">{s?.emergency?.signals?.map((x: any) => <span key={x.code} className="pill pill-red">{x.label}</span>)}</div></Notice>}
    <div className="workflow-layout">
      <section className="panel form-panel">
        <div className="panel-heading"><div><h2>Describe what is happening</h2><p>Where it is, what triggers it, how long it has lasted and how strong it feels.</p></div><div className="module-icon violet"><AudioLines size={21} /></div></div>
        {turns.length > 0 && <div className="chat">{turns.map((t, i) => <div key={i} className={`chat-bubble ${t.who}`}>{t.text}</div>)}</div>}
        {!session?.emergency && session?.status !== 'complete' && <>
          <textarea className="large-textarea" rows={4} maxLength={20000} value={text} onChange={e => setText(e.target.value)} placeholder="For example: my upper left back tooth hurts when I drink something cold…"
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void send() }} />
          <div className="inline-actions"><MicButton patientId={user.role === 'dentist' ? patient.id : undefined} purpose="symptom_intake" onText={t => setText(x => (x ? x + ' ' : '') + t)} />
            <button className="button button-primary" disabled={!text.trim() || busy} onClick={send}>{busy ? <Spinner /> : <Send size={16} />} {session ? 'Answer' : 'Send'}</button></div>
          <p className="muted-small">Avoid sharing unnecessary personal details. If you have severe swelling, difficulty breathing or swallowing, uncontrolled bleeding or a facial injury, seek emergency care now.</p>
        </>}
        {session && <button className="text-button" onClick={reset}>Start a new report</button>}
      </section>
      <aside className="panel guidance-panel">
        <h3>Structured for your dentist</h3>
        {!s ? <p>As you describe your symptoms, the structured summary appears here.</p> : <>
          <Status value={session!.status} />
          <dl className="kv">
            <dt>Complaint</dt><dd>{s.complaints?.join(', ') || '—'}</dd>
            <dt>Trigger</dt><dd>{Array.isArray(s.trigger) ? s.trigger.join(', ') : s.trigger || '—'}</dd>
            <dt>Location</dt><dd>{s.location ? Object.entries(s.location).map(([k, v]) => `${k}: ${v}`).join(', ') : '—'}</dd>
            <dt>Duration</dt><dd>{s.duration || '—'}</dd>
            <dt>Severity</dt><dd>{s.severity ? (s.severity.score != null ? `${s.severity.score}/10` : s.severity.label) : '—'}</dd>
            <dt>Character</dt><dd>{s.character?.join(', ') || '—'}</dd>
          </dl>
          {s.terminology?.length > 0 && <p className="muted-small">Dental terms: {s.terminology.map((t: any) => `${t.phrase} → ${t.term}`).join('; ')}</p>}
          {s.missing_information?.length > 0 && !session!.emergency && <p className="muted-small">Still needed: {s.missing_information.join(', ')}</p>}
          {s.education?.map((e: any) => <div className="mini-card" key={e.title}><b>{e.title}</b><p>{e.what_it_is}</p><p className="muted-small">{e.next_step}</p></div>)}
        </>}
      </aside>
    </div>
    {session?.status === 'complete' && user.role === 'patient' && <BookingCta url={bookingUrl} onRequest={async () => { try { await post('/appointments', { reason: s.summary, source_type: 'voice_session', source_id: session.id }); toast('Appointment request recorded') } catch (e) { toast(errorText(e)) } }} />}
  </>
}

// ----------------------------------------------------------------------------- dentist scribe
export function ScribePage() {
  return <>
    <Heading eyebrow="DENTEDGE VOICE · DENTIST" title="AI clinical scribe" description="Capture the conversation, identify speakers and generate an editable SOAP draft. Nothing enters the record until you approve it." action={<PatientPicker compact />} />
    <RequirePatient>{p => <Scribe patient={p} />}</RequirePatient>
  </>
}

function Scribe({ patient }: { patient: PatientRef }) {
  const { toast } = useApp()
  const [transcript, setTranscript] = useState('')
  const [segments, setSegments] = useState<any[] | undefined>()
  const [speaker, setSpeaker] = useState<'Dentist' | 'Patient'>('Dentist')
  const [draft, setDraft] = useState<Session | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState('')
  const [history, setHistory] = useState<Session[]>([])
  const load = () => api<Session[]>(`/voice/sessions?patient_id=${patient.id}&session_type=scribe`).then(setHistory).catch(() => undefined)
  useEffect(() => { void load() }, [patient.id])
  async function generate() {
    setBusy('gen')
    try { const r = await post<Session>('/voice/scribe', { transcript, patient_id: patient.id, segments }); setDraft(r); setNote(r.structured.note_text); void load() } catch (e) { toast(errorText(e)) } finally { setBusy('') }
  }
  async function act(action: 'save_edit' | 'approve' | 'reject') {
    if (!draft) return
    setBusy(action)
    try {
      const r = await patch<Session>(`/voice/scribe/${draft.id}`, { action, note_text: note !== draft.structured.note_text ? note : undefined, reason: action === 'reject' ? 'Rejected by dentist' : undefined })
      setDraft(r); toast(action === 'approve' ? 'Note approved and saved to the record' : action === 'reject' ? 'Draft rejected' : 'Edits saved'); void load()
    } catch (e) { toast(errorText(e)) } finally { setBusy('') }
  }
  return <div className="workflow-layout">
    <section className="panel form-panel">
      <div className="panel-heading"><div><h2>Conversation</h2><p>Dictate turn by turn, paste a transcript, or prefix lines with “Dentist:” / “Patient:”.</p></div></div>
      <div className="segmented">{(['Dentist', 'Patient'] as const).map(s => <button key={s} className={speaker === s ? 'selected' : ''} onClick={() => setSpeaker(s)}>{s} speaking</button>)}</div>
      <textarea className="large-textarea" rows={10} value={transcript} onChange={e => { setTranscript(e.target.value); setSegments(undefined) }} placeholder={'Patient: My lower right tooth hurts when I chew.\nDentist: I can see a fracture line on tooth 46…'} />
      <div className="inline-actions"><MicButton patientId={patient.id} purpose="scribe" onText={(t, seg) => { setTranscript(x => `${x}${x ? '\n' : ''}${speaker}: ${t}`); if (seg?.length) setSegments(undefined) }} />
        <button className="button button-primary" disabled={!transcript.trim() || !!busy} onClick={generate}>{busy === 'gen' ? <Spinner /> : <ClipboardCheck size={16} />} Generate SOAP draft</button></div>
      {history.length > 0 && <div className="history-list"><h4>Previous notes</h4>{history.map(h => <button key={h.id} className="history-row" onClick={() => { setDraft(h); setNote(h.structured.note_text ?? '') }}><span>{formatDate(h.created_at, true)}</span><Status value={h.status} /></button>)}</div>}
    </section>
    <section className="panel form-panel">
      <div className="panel-heading"><div><h2>Draft note</h2><p>Review, edit, then approve or reject.</p></div>{draft && <Status value={draft.status} />}</div>
      {!draft ? <p className="panel-copy">The generated SOAP note will appear here.</p> : <>
        {draft.structured.turns && <details className="trace"><summary>Speaker attribution ({draft.structured.turns.length} turns)</summary><ol>{draft.structured.turns.map((t: any, i: number) => <li key={i}><b>{t.speaker}</b><span>{t.text}</span></li>)}</ol></details>}
        {draft.structured.safety_warnings?.length > 0 && <Notice tone="warning" title="Please verify">{draft.structured.safety_warnings.map((w: any) => w.text).join(' ')}</Notice>}
        <textarea className="large-textarea mono" rows={18} value={note} onChange={e => setNote(e.target.value)} disabled={draft.status === 'approved' || draft.status === 'rejected'} />
        {draft.status === 'draft' && <div className="inline-actions">
          <button className="button button-secondary" disabled={!!busy} onClick={() => act('save_edit')}>Save edits</button>
          <button className="button button-danger" disabled={!!busy} onClick={() => act('reject')}><X size={15} /> Reject</button>
          <button className="button button-primary" disabled={!!busy} onClick={() => act('approve')}><Check size={15} /> Approve & save</button>
        </div>}
      </>}
    </section>
  </div>
}
