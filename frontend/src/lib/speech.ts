import { useEffect, useRef, useState } from 'react'
import { post } from './api'

/** Browser speech recognition (Web Speech API). Audio stays on the device/browser vendor; no audio is sent to DentEdge. */
export function useDictation(onFinal: (text: string) => void, lang = 'en-IN') {
  const Rec: any = typeof window !== 'undefined' ? ((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition) : null
  const rec = useRef<any>(null)
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState('')
  const [error, setError] = useState('')
  const cb = useRef(onFinal)
  cb.current = onFinal
  useEffect(() => () => rec.current?.abort?.(), [])
  function start() {
    if (!Rec) { setError('Voice input is not supported in this browser. Please type instead.'); return }
    setError('')
    const r = new Rec()
    r.lang = lang; r.continuous = true; r.interimResults = true
    r.onresult = (e: any) => {
      let tmp = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i]
        if (res.isFinal) cb.current(res[0].transcript.trim())
        else tmp += res[0].transcript
      }
      setInterim(tmp)
    }
    r.onerror = (e: any) => { setError(e.error === 'not-allowed' ? 'Microphone permission was denied.' : 'Voice input stopped.'); setListening(false) }
    r.onend = () => { setListening(false); setInterim('') }
    rec.current = r
    r.start(); setListening(true)
  }
  function stop() { rec.current?.stop(); setListening(false) }
  return { supported: !!Rec, listening, interim, error, start, stop }
}

/** Records audio and sends it to the server speech-to-text provider (when configured). */
export function useServerRecorder(patientId: string | undefined, purpose: string, onText: (t: string, segments: any[]) => void) {
  const mr = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const [recording, setRecording] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function start() {
    setError('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const m = new MediaRecorder(stream)
      chunks.current = []
      m.ondataavailable = e => e.data.size && chunks.current.push(e.data)
      m.onstop = async () => {
        stream.getTracks().forEach(t => t.stop())
        const blob = new Blob(chunks.current, { type: m.mimeType || 'audio/webm' })
        const body = new FormData()
        body.append('file', new File([blob], 'recording.webm', { type: (m.mimeType || 'audio/webm').split(';')[0] }))
        body.append('purpose', purpose)
        if (patientId) body.append('patient_id', patientId)
        setBusy(true)
        try { const r = await post<{ text: string; segments: any[] }>('/voice/transcribe', body); onText(r.text, r.segments) }
        catch (e) { setError(e instanceof Error ? e.message : 'Transcription failed') }
        finally { setBusy(false) }
      }
      m.start(); mr.current = m; setRecording(true)
    } catch { setError('Microphone permission was denied or unavailable.') }
  }
  function stop() { mr.current?.stop(); setRecording(false) }
  return { recording, busy, error, start, stop }
}
