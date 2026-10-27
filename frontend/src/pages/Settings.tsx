import { useEffect, useState } from 'react'
import { Download, LogOut, Pencil, ShieldCheck, Trash2 } from 'lucide-react'
import { api, patch, post, type User } from '../lib/api'
import { useApp } from '../lib/context'
import { Heading, Status, errorText, formatDate } from '../components/ui'

export default function SettingsPage({ onSignOut }: { onSignOut: () => void }) {
  const { user, toast, refreshConsent, updateUser } = useApp()
  const [profile, setProfile] = useState<{ full_name: string; phone: string; date_of_birth: string }>({ full_name: user.full_name, phone: '', date_of_birth: '' })
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  useEffect(() => { api<any>('/auth/profile').then(p => setProfile({ full_name: p.full_name, phone: p.phone ?? '', date_of_birth: p.date_of_birth ?? '' })).catch(() => undefined) }, [])
  async function saveProfile(e: React.FormEvent) {
    e.preventDefault(); setSaving(true)
    try {
      const body: Record<string, string> = { full_name: profile.full_name.trim() }
      if (user.role === 'patient') { body.phone = profile.phone; body.date_of_birth = profile.date_of_birth }
      const p = await patch<User & { phone: string | null; date_of_birth: string | null }>('/auth/profile', body)
      updateUser({ id: p.id, full_name: p.full_name, email: p.email, role: p.role })
      setProfile({ full_name: p.full_name, phone: p.phone ?? '', date_of_birth: p.date_of_birth ?? '' })
      setEditing(false); toast('Profile updated')
    } catch (err) { toast(errorText(err)) } finally { setSaving(false) }
  }
  const [consents, setConsents] = useState<any[]>([])
  const [info, setInfo] = useState<any>(null)
  const [pw, setPw] = useState({ current: '', next: '' })
  const [del, setDel] = useState({ confirm: '', password: '' })
  useEffect(() => { api<any[]>('/consents').then(setConsents).catch(() => undefined); api('/system/info').then(setInfo).catch(() => undefined) }, [])
  async function changePassword(e: React.FormEvent) {
    e.preventDefault()
    try { await post('/auth/change-password', { current_password: pw.current, new_password: pw.next }); toast('Password changed — please sign in again'); onSignOut() } catch (err) { toast(errorText(err)) }
  }
  async function exportData() {
    try {
      const data = await api('/me/export')
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
      const a = document.createElement('a'); a.href = url; a.download = 'dentedge-my-data.json'; a.click(); URL.revokeObjectURL(url)
    } catch (e) { toast(errorText(e)) }
  }
  async function withdraw(type: string, version: string) {
    try { await post('/consents', { consent_type: type, version, accepted: false }); toast('Consent withdrawn. AI processing is paused until you consent again.'); refreshConsent(); setConsents(await api<any[]>('/consents')) } catch (e) { toast(errorText(e)) }
  }
  async function deleteAccount() {
    try { await post('/me/delete', del); toast('Your account and data have been deleted'); onSignOut() } catch (e) { toast(errorText(e)) }
  }
  const latest = Object.values(consents.reduce((acc: any, c) => (acc[c.consent_type] ??= c, acc), {})) as any[]
  return <>
    <Heading eyebrow="PREFERENCES" title="Account, privacy & settings" description="Manage your session, consents and data." />
    <div className="settings-grid">
      <div className="panel settings-profile">
        <div className="profile-avatar large-avatar">{user.full_name.split(/\s+/).slice(0, 2).map(x => x[0]).join('').toUpperCase()}</div>
        {editing ? <form className="form-stack profile-form" onSubmit={saveProfile}>
          <label className="field-label" htmlFor="pf-name">Full name</label>
          <input id="pf-name" className="text-field" value={profile.full_name} minLength={2} maxLength={160} required onChange={e => setProfile({ ...profile, full_name: e.target.value })} />
          {user.role === 'patient' && <>
            <label className="field-label" htmlFor="pf-phone">Phone</label>
            <input id="pf-phone" className="text-field" type="tel" maxLength={32} value={profile.phone} onChange={e => setProfile({ ...profile, phone: e.target.value })} placeholder="Optional" />
            <label className="field-label" htmlFor="pf-dob">Date of birth</label>
            <input id="pf-dob" className="text-field" type="date" value={profile.date_of_birth} onChange={e => setProfile({ ...profile, date_of_birth: e.target.value })} />
          </>}
          <div className="inline-actions"><button type="button" className="button button-secondary" onClick={() => { setEditing(false); setProfile(p => ({ ...p, full_name: user.full_name })) }}>Cancel</button>
            <button className="button button-primary" disabled={saving}>{saving ? 'Saving…' : 'Save changes'}</button></div>
        </form> : <>
          <h2>{user.full_name}</h2><p>{user.email}</p><span className="role-badge">{user.role} account</span>
          {user.role === 'patient' && (profile.phone || profile.date_of_birth) && <div className="settings-divider" />}
          {user.role === 'patient' && profile.phone && <div className="settings-detail"><span>Phone</span><b>{profile.phone}</b></div>}
          {user.role === 'patient' && profile.date_of_birth && <div className="settings-detail"><span>Date of birth</span><b>{formatDate(profile.date_of_birth)}</b></div>}
          <button className="button button-secondary" onClick={() => setEditing(true)}><Pencil size={15} /> Edit profile</button>
        </>}
        <div className="settings-divider" />
        {info && <div className="settings-detail"><span>Version</span><b>{info.version}</b></div>}
        <button className="button button-danger" onClick={onSignOut}><LogOut size={16} /> Sign out everywhere</button>
      </div>
      <div className="panel settings-info">
        <h3>Change password</h3>
        <form className="form-stack" onSubmit={changePassword}>
          <input className="text-field" type="password" autoComplete="current-password" placeholder="Current password" value={pw.current} onChange={e => setPw({ ...pw, current: e.target.value })} required />
          <input className="text-field" type="password" autoComplete="new-password" placeholder="New password (10+ characters, letters and numbers)" minLength={10} value={pw.next} onChange={e => setPw({ ...pw, next: e.target.value })} required />
          <button className="button button-secondary">Update password</button>
        </form>
        {user.role === 'patient' && <>
          <div className="settings-divider" />
          <h3><ShieldCheck size={17} /> Consent</h3>
          {latest.length ? latest.map(c => <div className="config-row" key={c.id}><div><b>{c.consent_type.replaceAll('_', ' ')}</b><span>v{c.version} · {formatDate(c.created_at, true)}</span></div>
            <Status value={c.accepted ? 'approved' : 'rejected'} />{c.accepted && <button className="text-button" onClick={() => withdraw(c.consent_type, c.version)}>Withdraw</button>}</div>) : <p className="panel-copy">No consents recorded.</p>}
          <div className="settings-divider" />
          <h3>Your data</h3>
          <button className="button button-secondary" onClick={exportData}><Download size={16} /> Export my data (JSON)</button>
          <details className="danger-zone"><summary><Trash2 size={15} /> Delete my account and data</summary>
            <p className="panel-copy">This permanently deletes your images, audio and AI results and closes your account. An anonymised audit record is kept as required for clinical governance.</p>
            <input className="text-field" placeholder='Type "DELETE" to confirm' value={del.confirm} onChange={e => setDel({ ...del, confirm: e.target.value })} />
            <input className="text-field" type="password" placeholder="Password" value={del.password} onChange={e => setDel({ ...del, password: e.target.value })} />
            <button className="button button-danger" disabled={del.confirm !== 'DELETE' || !del.password} onClick={deleteAccount}>Delete permanently</button>
          </details>
        </>}
      </div>
    </div>
  </>
}
