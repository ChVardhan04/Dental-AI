import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity, ArrowRight, AudioLines, Bell, Check, ChevronDown, CircleHelp, ClipboardCheck, FileText, HeartPulse, History, ImagePlus,
  LayoutDashboard, Menu, NotebookPen, ScanLine, Search, Settings2, ShieldCheck, Smile, Stethoscope, UserRound, Wrench, X,
} from 'lucide-react'
import { api, getSavedUser, login, logout, register, setUnauthorizedHandler, setConsentRequiredHandler, clearSession, updateSavedUser, type User } from './lib/api'
import { Ctx, type Page, type PatientRef } from './lib/context'
import Overview from './pages/Home'
import OralVisionPage from './pages/OralVision'
import XRayPage from './pages/XRay'
import VoicePage, { ScribePage } from './pages/Voice'
import PerioPage from './pages/Perio'
import SmilePage from './pages/Smile'
import { EducationPage, ProfilePage, TimelinePage } from './pages/Insight'
import ReviewPage from './pages/Review'
import ReportsPage from './pages/Reports'
import AdminPage from './pages/Admin'
import SettingsPage from './pages/Settings'

type NavItem = { label: Page; icon: any; section?: string }
const NAV: Record<User['role'], NavItem[]> = {
  patient: [
    { label: 'Overview', icon: LayoutDashboard, section: 'WORKSPACE' }, { label: 'Oral Vision', icon: ScanLine }, { label: 'X-Ray AI', icon: ImagePlus },
    { label: 'Voice Assistant', icon: AudioLines }, { label: 'Smile Intelligence', icon: Smile }, { label: 'Patient Education', icon: HeartPulse },
    { label: 'Oral Health Profile', icon: Activity, section: 'YOUR HEALTH' }, { label: 'Timeline', icon: History }, { label: 'Perio Charting', icon: Stethoscope },
    { label: 'Reports', icon: FileText }, { label: 'Settings', icon: Settings2, section: 'PREFERENCES' },
  ],
  dentist: [
    { label: 'Overview', icon: LayoutDashboard, section: 'WORKSPACE' }, { label: 'Clinical Review', icon: ClipboardCheck }, { label: 'Oral Vision', icon: ScanLine },
    { label: 'X-Ray AI', icon: ImagePlus }, { label: 'AI Scribe', icon: NotebookPen }, { label: 'Perio Charting', icon: Activity }, { label: 'Voice Assistant', icon: AudioLines },
    { label: 'Smile Intelligence', icon: Smile }, { label: 'Oral Health Profile', icon: HeartPulse, section: 'PATIENT CARE' }, { label: 'Timeline', icon: History },
    { label: 'Patient Education', icon: HeartPulse }, { label: 'Reports', icon: FileText }, { label: 'Settings', icon: Settings2, section: 'PREFERENCES' },
  ],
  admin: [{ label: 'Overview', icon: LayoutDashboard, section: 'WORKSPACE' }, { label: 'Administration', icon: Wrench }, { label: 'Settings', icon: Settings2, section: 'PREFERENCES' }],
}

export default function App() {
  const [user, setUser] = useState<User | null>(getSavedUser())
  const [page, setPage] = useState<Page>('Overview')
  const [focusAnalysisId, setFocus] = useState<string | null>(null)
  const [patient, setPatient] = useState<PatientRef | null>(user?.role === 'patient' ? { id: user.id, full_name: user.full_name } : null)
  const [mobileNav, setMobileNav] = useState(false)
  const [search, setSearch] = useState('')
  const [toastMsg, setToast] = useState('')
  const [consentMissing, setConsentMissing] = useState<string[]>([])
  const [reviewCount, setReviewCount] = useState(0)
  const [bookingUrl, setBookingUrl] = useState('')
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login')
  const [authError, setAuthError] = useState('')
  const [authLoading, setAuthLoading] = useState(false)

  const signOut = useCallback(async (callServer = true) => {
    if (callServer) await logout(); else clearSession()
    setUser(null); setPatient(null); setPage('Overview')
  }, [])
  useEffect(() => { setUnauthorizedHandler(() => { void signOut(false); setAuthError('Your session has expired. Please sign in again.') }) }, [signOut])

  useEffect(() => { setConsentRequiredHandler(missing => setConsentMissing(missing.length ? missing : ['ai_analysis'])) }, [])
  const refreshConsent = useCallback(() => {
    if (user?.role !== 'patient') { setConsentMissing([]); return }
    let attempts = 0
    const load = () => api<{ missing: string[] }>('/consents/status').then(s => setConsentMissing(s.missing))
      .catch(() => { if (++attempts < 5) window.setTimeout(load, 2000) })  // backend may still be starting
    load()
  }, [user])
  useEffect(() => {
    if (!user) return
    refreshConsent()
    api<{ appointment_booking_url: string }>('/system/info').then(i => setBookingUrl(i.appointment_booking_url)).catch(() => undefined)
    if (user.role === 'dentist') {
      const tick = () => api<{ counts: { open: number } }>('/clinical-review/queue').then(q => setReviewCount(q.counts.open)).catch(() => undefined)
      tick(); const id = window.setInterval(tick, 60000); return () => window.clearInterval(id)
    }
  }, [user, refreshConsent])
  useEffect(() => { if (!toastMsg) return; const id = window.setTimeout(() => setToast(''), 4200); return () => window.clearTimeout(id) }, [toastMsg])

  const navigate = useCallback((p: Page, opts?: { analysisId?: string }) => { setFocus(opts?.analysisId ?? null); setPage(p); setMobileNav(false); window.scrollTo({ top: 0 }) }, [])
  const updateUser = useCallback((u: User) => {
    updateSavedUser(u); setUser(u)
    if (u.role === 'patient') setPatient({ id: u.id, full_name: u.full_name })
  }, [])
  const ctx = useMemo(() => user && ({ user, patient, setPatient, navigate, toast: setToast, consentMissing, refreshConsent, focusAnalysisId, bookingUrl, updateUser }), [user, patient, navigate, consentMissing, refreshConsent, focusAnalysisId, bookingUrl, updateUser])

  async function handleAuth(form: FormData) {
    setAuthError(''); setAuthLoading(true)
    try {
      const email = String(form.get('email') || '').trim()
      const password = String(form.get('password') || '')
      const u = authMode === 'login' ? await login(email, password) : await register(String(form.get('full_name') || ''), email, password)
      setUser(u); setPatient(u.role === 'patient' ? { id: u.id, full_name: u.full_name } : null); setPage('Overview')
      setToast(`Welcome, ${u.full_name.split(' ')[0]}`)
    } catch (e) { setAuthError(e instanceof Error ? e.message : 'Unable to authenticate') } finally { setAuthLoading(false) }
  }

  if (!user || !ctx) return <AuthScreen mode={authMode} setMode={setAuthMode} onSubmit={handleAuth} error={authError} loading={authLoading} />
  const nav = NAV[user.role].filter(n => n.label.toLowerCase().includes(search.toLowerCase()))
  const isDentist = user.role === 'dentist'
  return <Ctx.Provider value={ctx}>
    <div className="app-shell">
      {mobileNav && <button className="mobile-scrim" aria-label="Close menu" onClick={() => setMobileNav(false)} />}
      <aside className={`sidebar ${mobileNav ? 'sidebar-open' : ''}`}>
        <div className="brand"><div className="brand-mark"><HeartPulse size={22} /></div><div className="brand-copy"><strong>DentEdge<span> AI</span></strong><small>ORAL HEALTH INTELLIGENCE</small></div><button className="mobile-close icon-button" onClick={() => setMobileNav(false)} aria-label="Close navigation"><X size={18} /></button></div>
        <div className="workspace-switch"><div className="workspace-avatar">{isDentist ? <Stethoscope size={18} /> : user.role === 'admin' ? <Wrench size={18} /> : <UserRound size={18} />}</div><div className="workspace-meta"><strong>{isDentist ? 'Clinical workspace' : user.role === 'admin' ? 'Administration' : 'Patient workspace'}</strong><span>{isDentist ? (patient ? `Patient: ${patient.full_name}` : 'No patient selected') : user.role === 'admin' ? 'No clinical access' : 'Personal health'}</span></div><ChevronDown size={16} className="muted" /></div>
        <div className="nav-search"><Search size={15} /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Find a feature" aria-label="Find a feature" /></div>
        <nav className="main-nav">
          {nav.map(item => <div key={item.label}>{item.section && <div className="nav-section">{item.section}</div>}<button className={`nav-item ${page === item.label ? 'active' : ''}`} onClick={() => navigate(item.label)}><item.icon size={18} strokeWidth={1.8} /><span>{item.label}</span>{item.label === 'Clinical Review' && reviewCount > 0 && <span className="nav-count">{reviewCount}</span>}</button></div>)}
          {nav.length === 0 && <p className="nav-empty">No matching features</p>}
        </nav>
        <div className="sidebar-bottom"><div className="privacy-card"><div className="privacy-icon"><ShieldCheck size={17} /></div><div><strong>Privacy comes first</strong><p>Encrypted storage, role-based access and a full audit trail.</p></div></div>
          <button className="nav-item help-item" onClick={() => setToast('DentEdge AI provides AI-assisted observations, not diagnoses. Contact your clinic for help.')}><CircleHelp size={18} /><span>Help & safety</span><ArrowRight size={15} className="help-arrow" /></button></div>
      </aside>
      <main className="main-area">
        <header className="topbar"><div className="topbar-left"><button className="icon-button mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open navigation"><Menu size={20} /></button><div className="breadcrumb">Workspace <span>/</span> <strong>{page}</strong></div></div>
          <div className="topbar-right">{isDentist && <button className="icon-button notification-button" onClick={() => navigate('Clinical Review')} aria-label="Findings awaiting review"><Bell size={18} />{reviewCount > 0 && <i />}</button>}<div className="top-divider" />
            <button className="profile-menu" onClick={() => navigate('Settings')}><div className="profile-avatar">{user.full_name.split(/\s+/).slice(0, 2).map(x => x[0]).join('').toUpperCase()}</div><div className="profile-copy"><strong>{user.full_name}</strong><span>{user.role}</span></div><ChevronDown size={15} /></button></div></header>
        <div className="page-content" key={page}>
          {page === 'Overview' && <Overview />}
          {page === 'Oral Vision' && <OralVisionPage />}
          {page === 'X-Ray AI' && <XRayPage />}
          {page === 'Voice Assistant' && <VoicePage />}
          {page === 'AI Scribe' && <ScribePage />}
          {page === 'Perio Charting' && <PerioPage />}
          {page === 'Smile Intelligence' && <SmilePage />}
          {page === 'Patient Education' && <EducationPage />}
          {page === 'Oral Health Profile' && <ProfilePage />}
          {page === 'Timeline' && <TimelinePage />}
          {page === 'Clinical Review' && <ReviewPage />}
          {page === 'Reports' && <ReportsPage />}
          {page === 'Administration' && <AdminPage />}
          {page === 'Settings' && <SettingsPage onSignOut={() => void signOut()} />}
        </div>
        <footer className="app-footer"><span>© 2026 DentEdge AI</span><span><ShieldCheck size={13} /> AI-assisted information · Dentist review required · Not a diagnosis</span></footer>
      </main>
      {toastMsg && <div className="toast" role="status"><div className="toast-check"><Check size={15} /></div><span>{toastMsg}</span><button onClick={() => setToast('')} aria-label="Dismiss"><X size={15} /></button></div>}
    </div>
  </Ctx.Provider>
}

function AuthScreen({ mode, setMode, onSubmit, error, loading }: { mode: 'login' | 'register'; setMode: (m: 'login' | 'register') => void; onSubmit: (d: FormData) => void; error: string; loading: boolean }) {
  return <div className="auth-shell"><div className="auth-left"><div className="brand auth-brand"><div className="brand-mark"><HeartPulse size={22} /></div><div className="brand-copy"><strong>DentEdge<span> AI</span></strong><small>ORAL HEALTH INTELLIGENCE</small></div></div>
    <div className="auth-hero"><div className="hero-pill"><span className="hero-pulse" /> A MORE CONNECTED CARE EXPERIENCE</div><h1>Oral health,<br /><em>understood better.</em></h1><p>Photos, X-rays, symptoms and history in one place — with clear explanations and your dentist in control.</p>
      <div className="auth-feature"><span><ScanLine size={18} /></span><div><b>Multimodal intelligence</b><small>Vision, X-ray, voice, perio and smile — combined into one profile.</small></div></div>
      <div className="auth-feature"><span><ShieldCheck size={18} /></span><div><b>Safety by design</b><small>Quality gates, clinical rules, evidence grounding and dentist review.</small></div></div>
      <div className="auth-art"><div className="auth-orbit auth-orbit-a" /><div className="auth-orbit auth-orbit-b" /><div className="auth-tooth"><HeartPulse size={88} strokeWidth={1.1} /></div><div className="auth-art-tag tag-left"><Check size={14} /> Quality-first</div><div className="auth-art-tag tag-right"><ShieldCheck size={14} /> Human-led care</div></div></div>
    <div className="auth-bottom"><span>© 2026 DentEdge AI</span><span>AI-assisted · Not a diagnosis</span></div></div>
    <div className="auth-right"><form className="auth-form" onSubmit={e => { e.preventDefault(); void onSubmit(new FormData(e.currentTarget)) }}>
      <div className="auth-form-kicker">{mode === 'login' ? 'WELCOME BACK' : 'GET STARTED'}</div><h2>{mode === 'login' ? 'Sign in to DentEdge' : 'Create your account'}</h2><p>{mode === 'login' ? 'Continue to your oral health workspace.' : 'Patients can register here. Dentist accounts are provisioned by your clinic administrator.'}</p>
      {mode === 'register' && <><label className="field-label" htmlFor="full_name">Full name</label><input id="full_name" className="text-field" name="full_name" autoComplete="name" required minLength={2} placeholder="Your full name" /></>}
      <label className="field-label" htmlFor="email">Email address</label><input id="email" className="text-field" type="email" name="email" required autoComplete="email" placeholder="you@example.com" />
      <label className="field-label" htmlFor="password">Password</label><input id="password" className="text-field" type="password" name="password" required minLength={mode === 'register' ? 10 : 1} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} placeholder={mode === 'register' ? 'At least 10 characters with letters and numbers' : 'Enter your password'} />
      {error && <div className="auth-error" role="alert"><X size={15} />{error}</div>}
      <button className="button button-primary auth-submit" type="submit" disabled={loading}>{loading ? <span className="spinner" /> : null}{mode === 'login' ? 'Sign in' : 'Create account'} <ArrowRight size={16} /></button>
      <div className="auth-switch">{mode === 'login' ? "Don't have an account?" : 'Already have an account?'} <button type="button" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>{mode === 'login' ? 'Create one' : 'Sign in'}</button></div>
      <div className="auth-disclaimer"><ShieldCheck size={16} /><span>DentEdge AI provides AI-assisted observations reviewed by dentists. It does not diagnose or replace professional care.</span></div>
    </form></div></div>
}
