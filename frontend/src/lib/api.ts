export const API_BASE: string = import.meta.env.VITE_API_BASE_URL || '/api/v1'
const API_ORIGIN = API_BASE.replace(/\/api\/v1\/?$/, '')

export type Role = 'patient' | 'dentist' | 'admin'
export type User = { id: string; full_name: string; email: string; role: Role }

export type Finding = {
  id: string; finding_id: string; finding_code: string; finding_type: string; label: string
  location: { region?: string; description?: string; tooth?: string | null; arch?: string; side?: string; [k: string]: unknown }
  bbox: [number, number, number, number] | null; confidence: number; confidence_band: 'low' | 'moderate' | 'high'
  severity: string; evidence: string; model: string; model_version: string; requires_review: boolean
  review_status: string; review_note?: string | null; image_asset_id?: string | null; analysis_id: string; created_at: string
  patient_id?: string; patient_name?: string; module?: string; urgency?: string; annotated_url?: string | null; image_url?: string | null
}

export type Explanation = {
  summary: string; observations: { finding_code?: string; text: string }[]; possible_explanations: string[]; why_it_matters?: string
  recommended_next_step: string; urgency: string; limitations: string[]; questions_for_dentist: string[]; warning_signs: string[]
  requires_dentist_review: boolean
}

export type AnalysisSummary = {
  id: string; module: string; status: string; summary: string; urgency: string; created_at: string
  model_name?: string; model_version?: string; finding_count?: number; pending_review?: number
}

export type Analysis = AnalysisSummary & {
  patient_id: string; image_asset_id: string | null; rules_version: string; prompt_version: string; findings: Finding[]
  result: Record<string, any> & { explanation?: Explanation; pipeline_trace?: TraceStep[] }
  annotated_images: { image_id: string; url: string }[]; appointment_booking_url: string
}

export type TraceStep = { step: string; status: string; ms: number; [k: string]: unknown }

export type ImageAsset = {
  id: string; patient_id: string; image_kind: string; view: string | null; filename: string; width: number | null; height: number | null
  quality: Record<string, any>; duplicate: boolean; created_at: string; has_annotation: boolean; url: string
}

export class ApiError extends Error {
  status: number
  detail: any
  constructor(message: string, status: number, detail: any) { super(message); this.status = status; this.detail = detail }
}

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn }
let onConsentRequired: ((missing: string[]) => void) | null = null
export function setConsentRequiredHandler(fn: (missing: string[]) => void) { onConsentRequired = fn }

// Session token lives in sessionStorage (cleared when the browser tab closes) to limit exposure on shared devices.
const TOKEN_KEY = 'dentedge_token'
const USER_KEY = 'dentedge_user'
function store() { try { return window.sessionStorage } catch { return null } }
export function getToken() { return store()?.getItem(TOKEN_KEY) ?? null }
export function setSession(token: string, user: User) { store()?.setItem(TOKEN_KEY, token); store()?.setItem(USER_KEY, JSON.stringify(user)) }
export function clearSession() { store()?.removeItem(TOKEN_KEY); store()?.removeItem(USER_KEY) }
export function getSavedUser(): User | null {
  try { const raw = store()?.getItem(USER_KEY); return raw ? JSON.parse(raw) as User : null } catch { return null }
}

function messageFrom(data: any, status: number): string {
  const d = data?.detail
  if (typeof d === 'string') return d
  if (d?.message) return d.message
  if (Array.isArray(d) && d[0]?.msg) return `${d[0].loc?.slice(-1)[0] ?? 'Field'}: ${d[0].msg}`
  if (status === 429) return 'Too many requests. Please wait a moment.'
  return `Request failed (${status})`
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers = new Headers(init.headers)
  if (!(init.body instanceof FormData) && init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  let response: Response
  try { response = await fetch(`${API_BASE}${path}`, { ...init, headers }) }
  catch { throw new ApiError('Cannot reach the DentEdge AI service. Check your connection and try again.', 0, null) }
  if (response.status === 204) return undefined as T
  const data = await response.json().catch(() => ({}))
  if (response.status === 401 && token) onUnauthorized?.()
  if (response.status === 403 && data?.detail?.code === 'consent_required') onConsentRequired?.(Array.isArray(data.detail.missing) ? data.detail.missing : ['ai_analysis'])
  if (!response.ok) throw new ApiError(messageFrom(data, response.status), response.status, data?.detail)
  return data as T
}

export const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: 'POST', body: body instanceof FormData ? body : JSON.stringify(body ?? {}) })
export function updateSavedUser(user: User) { const t = getToken(); if (t) setSession(t, user) }
export const patch = <T,>(path: string, body?: unknown) => api<T>(path, { method: 'PATCH', body: JSON.stringify(body ?? {}) })

/** Fetch an authenticated binary (image) and return an object URL. */
export async function fetchBlobUrl(path: string): Promise<string> {
  const url = path.startsWith('/api/') ? `${API_ORIGIN}${path}` : `${API_BASE}${path}`
  const res = await fetch(url, { headers: { Authorization: `Bearer ${getToken() ?? ''}` } })
  if (!res.ok) throw new ApiError('Image unavailable', res.status, null)
  return URL.createObjectURL(await res.blob())
}

export async function login(email: string, password: string) {
  const body = new URLSearchParams({ username: email, password })
  let response: Response
  try { response = await fetch(`${API_BASE}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body }) }
  catch { throw new Error('Cannot reach the DentEdge AI service.') }
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(messageFrom(data, response.status))
  setSession(data.access_token, data.user)
  return data.user as User
}

export async function register(full_name: string, email: string, password: string) {
  const data = await post<{ access_token: string; user: User }>('/auth/register', { full_name, email, password })
  setSession(data.access_token, data.user)
  return data.user
}

export async function logout() {
  try { await api('/auth/logout', { method: 'POST' }) } catch { /* token may already be invalid */ }
  clearSession()
}
