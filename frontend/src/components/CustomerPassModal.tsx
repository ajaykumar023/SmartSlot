import { useCallback, useEffect, useId, useState } from 'react'
import { CalendarDays, CheckCircle2, Clock3, Download, FlaskConical, QrCode, RefreshCw, X } from 'lucide-react'
import { api } from '../api'
import type { Appointment } from '../types'

type PassStatus = {
  reference: string
  available: boolean
  status: string
  business_timezone: string
  opens_at: string
  check_in_opens_at: string
  appointment_at: string
  reason: 'ready' | 'scheduled' | 'inactive'
}
type IssuedPass = { reference: string; qr_image: string }

/** QR mock-up only: no QR data, token, URL, or API mutation. */
function SimulatedQr() {
  const dark = (x: number, y: number) => {
    const finder = (left: number, top: number) => {
      const dx=x-left, dy=y-top
      if (dx<0||dx>=7||dy<0||dy>=7) return null
      return dx===0||dy===0||dx===6||dy===6||(dx>=2&&dx<=4&&dy>=2&&dy<=4)
    }
    const a=finder(0,0), b=finder(14,0), c=finder(0,14)
    if(a!==null)return a
    if(b!==null)return b
    if(c!==null)return c
    return (x*11+y*17+x*y*3)%9 < 4
  }
  return <div className="demo-qr-wrap"><svg viewBox="0 0 210 210" role="img" aria-label="Illustrative QR pattern, not scannable" className="mock-qr">
    <rect width="210" height="210" fill="white"/>
    {Array.from({length:441},(_,i)=>({x:i%21,y:Math.floor(i/21)})).filter(p=>dark(p.x,p.y)).map(p=><rect key={`${p.x}-${p.y}`} x={p.x*10} y={p.y*10} width="10" height="10" fill="#192c28"/>)}
  </svg><div className="demo-qr-stamp">DEMO ONLY<span>Not valid for check-in</span></div></div>
}

export default function CustomerPassModal({ appointment, onClose }:{appointment:Appointment;onClose:()=>void}) {
  const title=useId()
  const [status,setStatus]=useState<PassStatus|null>(null)
  const [error,setError]=useState('')
  const [loading,setLoading]=useState(true)
  const [busy,setBusy]=useState(false)
  const [preview,setPreview]=useState(false)
  const cacheKey=`smartslot_day_pass:${appointment.customer_email}:${appointment.reference}:${appointment.starts_at}`
  const [issued,setIssued]=useState<IssuedPass|null>(()=>{try{return JSON.parse(sessionStorage.getItem(cacheKey)||'null')}catch{return null}})
  const refresh=useCallback(async()=>{
    try{const data=await api<PassStatus>(`/appointments/${encodeURIComponent(appointment.reference)}/qr/status`);setStatus(data);setError('');if(!data.available){setIssued(null);sessionStorage.removeItem(cacheKey)}}
    catch(e){setError((e as Error).message)}finally{setLoading(false)}
  },[appointment.reference,cacheKey])
  useEffect(()=>{void refresh();const id=window.setInterval(()=>void refresh(),60000);return()=>window.clearInterval(id)},[refresh])
  useEffect(()=>{const handle=(event:KeyboardEvent)=>{if(event.key==='Escape')onClose()};document.addEventListener('keydown',handle);return()=>document.removeEventListener('keydown',handle)},[onClose])
  const issue=async()=>{
    if(issued && !window.confirm('Replace the currently displayed pass? The previous QR will stop working.'))return
    setBusy(true);setError('')
    try{
      const result=await api<IssuedPass>(`/appointments/${encodeURIComponent(appointment.reference)}/qr/activate`,{method:'POST'})
      if(!result.qr_image)throw new Error('QR was not returned by the server.')
      setIssued(result);sessionStorage.setItem(cacheKey,JSON.stringify(result));setPreview(false)
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  const date=new Intl.DateTimeFormat(undefined,{dateStyle:'full',timeZone:appointment.business_timezone}).format(new Date(appointment.starts_at))
  const time=new Intl.DateTimeFormat(undefined,{timeStyle:'short',timeZone:appointment.business_timezone}).format(new Date(appointment.starts_at))
  const checkIn=status?.check_in_opens_at?new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short',timeZone:appointment.business_timezone}).format(new Date(status.check_in_opens_at)):''
  return <div className="modal-backdrop" role="presentation" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}>
    <section className="modal pass-sheet" role="dialog" aria-modal="true" aria-labelledby={title}>
      <button className="modal-close" type="button" aria-label="Close pass" onClick={onClose}><X size={18}/></button>
      <div className="eyebrow">SMARTSLOT / CHECK-IN</div>
      <h2 id={title}>Your appointment pass</h2>
      <p className="pass-subtitle">{appointment.business_name}</p>
      <div className="pass-summary">
        <div><span>Service</span><strong>{appointment.service_name}</strong></div>
        <div><span>Appointment</span><strong>{date} · {time}</strong></div>
        <div><span>Professional</span><strong>{appointment.staff_name}</strong></div>
        <div><span>Booking reference</span><strong className="mono-ref">{appointment.reference}</strong></div>
      </div>
      {error&&<p className="error-box" role="alert">{error}</p>}
      {loading?<p className="small-text muted">Checking pass availability…</p>:status?.reason==='inactive'?<div className="pass-state"><Clock3/><strong>Pass is no longer active</strong><span>This booking cannot be checked in.</span></div>:issued&&status?.available&&!preview?<div className="pass-visual"><div className="pass-ready-label"><CheckCircle2 size={16}/> Check-in QR ready</div><img className="qr pass-real-qr" src={issued.qr_image} alt={`Active QR check-in pass for ${appointment.reference}`}/><p className="small-text muted">Show this code to reception. Check-in starts {checkIn}.</p><a className="button secondary" download={`SmartSlot-${appointment.reference}.png`} href={issued.qr_image}><Download size={16}/> Save pass</a></div>:preview?<div className="pass-visual"><div className="pass-ready-label demo-label"><FlaskConical size={16}/> Simulated appointment day</div><SimulatedQr/><p className="small-text muted">This is a visual demo. No real QR token was generated or activated.</p><button className="button ghost" onClick={()=>setPreview(false)}>Back to actual appointment</button></div>:status?.available?<div className="pass-state"><QrCode size={30}/><strong>Your QR is ready to issue</strong><span>A secure code will be created for today's appointment. Save it once displayed.</span><button className="button" disabled={busy} onClick={()=>void issue()}>{busy?'Creating QR…':'Show my check-in QR'}</button></div>:<div className="pass-state"><CalendarDays size={30}/><strong>QR available on appointment day</strong><span>You'll find your live check-in QR here from the start of {date} ({appointment.business_timezone}).</span><button className="button secondary" type="button" onClick={()=>setPreview(true)}><FlaskConical size={16}/> Simulate appointment day</button><p className="small-text muted">Preview only. Real check-in rules and appointment times remain unchanged.</p></div>}
      <div className="pass-sheet-footer"><span>Check-in window: {checkIn||'See booking time'}</span><button className="button ghost small" onClick={onClose}>Close</button></div>
    </section>
  </div>
}
