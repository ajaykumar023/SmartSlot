import { useCallback, useEffect, useRef, useState } from 'react'
import { BrowserMultiFormatReader, type IScannerControls } from '@zxing/browser'
import { AlertCircle, Camera, CheckCircle2, Clock3, QrCode, RefreshCw, ScanLine, ShieldCheck, Users, X } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { confirmCheckIn, validateQr } from '../member4-api'
import type { Appointment } from '../types'
import StatusBadge from '../components/StatusBadge'
import Panel from '../components/Panel'
import { Empty, ErrorBox, Loading } from '../components/Feedback'

type Preview = Awaited<ReturnType<typeof validateQr>>
const formatTime = (date: string, zone?: string) => new Intl.DateTimeFormat(undefined, {hour:'numeric', minute:'2-digit', timeZone:zone||undefined}).format(new Date(date))
const businessDate = (zone: string) => {
  const parts = new Intl.DateTimeFormat('en-US', {timeZone:zone, year:'numeric', month:'2-digit', day:'2-digit'}).formatToParts(new Date())
  const value = (type:string) => parts.find(part=>part.type===type)?.value || ''
  return `${value('year')}-${value('month')}-${value('day')}`
}

export default function ReceptionDesk() {
  const [params] = useSearchParams()
  const [code,setCode] = useState(() => params.get('reference') || '')
  const [preview,setPreview] = useState<Preview|null>(null)
  const [camera,setCamera] = useState(false)
  const [busy,setBusy] = useState(false)
  const [error,setError] = useState('')
  const [result,setResult] = useState<Appointment|null>(null)
  const [manualVerified,setManualVerified] = useState(false)
  const [isScanned,setIsScanned] = useState(false)
  const [arrivals,setArrivals] = useState<Appointment[]>([])
  const [arrivalsError,setArrivalsError] = useState('')
  const [arrivalsLoading,setArrivalsLoading] = useState(true)
  const [zone,setZone] = useState('UTC')
  const video = useRef<HTMLVideoElement>(null)
  const controls = useRef<IScannerControls>()
  const pending = useRef(false)

  const refreshArrivals = useCallback(async () => {
    setArrivalsLoading(true)
    setArrivalsError('')
    try {
      const settings = await api<{timezone:string}>('/admin/settings')
      const localZone = settings.timezone || 'UTC'
      setZone(localZone)
      const day = businessDate(localZone)
      const rows = await api<Appointment[]>(`/admin/appointments?date_from=${day}&date_to=${day}`)
      setArrivals(rows.sort((a,b)=>a.starts_at.localeCompare(b.starts_at)))
    } catch (e) { setArrivalsError((e as Error).message) }
    finally { setArrivalsLoading(false) }
  }, [])
  useEffect(() => { void refreshArrivals() }, [refreshArrivals])
  useEffect(() => {
    const reference = params.get('reference')
    if (reference) {setCode(reference);setPreview(null);setManualVerified(false);setIsScanned(false)}
  }, [params])
  const stop = useCallback(() => {controls.current?.stop(); controls.current=undefined;setCamera(false)},[])
  const previewCode = useCallback(async (value:string, scanned:boolean) => {
    if (!value.trim() || pending.current) return
    pending.current=true
    setBusy(true);setError('');setResult(null);setPreview(null)
    setCode(value.trim());setIsScanned(scanned);setManualVerified(false)
    try { setPreview(await validateQr(value.trim())) }
    catch(e) {setError((e as Error).message)}
    finally {setBusy(false);pending.current=false}
  },[])
  useEffect(() => {
    if (!camera || !video.current) return
    const reader = new BrowserMultiFormatReader()
    let active=true
    reader.decodeFromVideoDevice(undefined,video.current,(found)=>{
      if (found&&active) {
        active=false
        controls.current?.stop()
        setCamera(false)
        void previewCode(found.getText(),true)
      }
    }).then(control=>{if (active) controls.current=control; else control.stop()})
      .catch(()=>{if(active){setCamera(false);setError('Camera access was blocked or unavailable. Allow permission or use the manual reference field.')}})
    return ()=>{active=false;controls.current?.stop();controls.current=undefined}
  },[camera,previewCode])
  const confirm = async () => {
    if (!preview || (!isScanned && !manualVerified) || pending.current) return
    setBusy(true);setError('');pending.current=true
    try {
      const checked = await confirmCheckIn(code)
      setResult(checked as unknown as Appointment)
      setPreview(null);setCode('');setManualVerified(false);setIsScanned(false)
      await refreshArrivals()
    } catch(e) {setError((e as Error).message);setPreview(null)}
    finally {setBusy(false);pending.current=false}
  }
  const expected = arrivals.filter(a=>a.status==='confirmed').length
  const checkedIn = arrivals.filter(a=>a.status==='checked_in').length
  const atRisk = arrivals.filter(a=>a.status==='at_risk').length
  return <div className="reception-page">
    <div className="reception-heading"><div><div className="detail-kicker">AETHERX RECEPTION WORKSPACE</div><h1 className="page-title">Check-in desk</h1><p className="page-subtitle">Scan a guest pass, verify the booking, and check them in safely.</p></div><span className="reception-online"><span/> Scanner workspace</span></div>
    <div className="reception-metrics">
      <div><span>Expected today</span><strong>{arrivalsLoading?'—':expected}</strong><small>Confirmed bookings</small></div>
      <div><span>Checked in</span><strong>{arrivalsLoading?'—':checkedIn}</strong><small>Completed arrivals</small></div>
      <div><span>Needs review</span><strong>{arrivalsLoading?'—':atRisk}</strong><small>At-risk bookings</small></div>
    </div>
    {error&&<ErrorBox message={error}/>}
    <div className="reception-columns">
      <Panel className="reception-scan-panel">
        <div className="reception-panel-title"><h2><ScanLine size={18}/> QR scanner</h2><span className="small-text muted">Secure two-step check-in</span></div>
        <div className={`reception-camera ${camera?'is-live':''}`}>
          {camera ? <video className="reception-video" ref={video} aria-label="QR camera preview" playsInline muted/> : <div className="reception-camera-empty"><QrCode size={52}/><strong>Ready to scan</strong><span>Present the customer's booking QR in front of the camera</span></div>}
          <div className="camera-outline" aria-hidden="true"/>
        </div>
        <button type="button" className={`button ${camera?'ghost':'secondary'}`} onClick={()=>camera?stop():(setError(''),setPreview(null),setCamera(true))}><Camera size={16}/>{camera?'Stop camera':'Start camera scanner'}</button>
        <div className="reception-separator"><span>OR ENTER A REFERENCE</span></div>
        <form onSubmit={e=>{e.preventDefault();stop();void previewCode(code,false)}}>
          <label className="field" htmlFor="reception-code">Booking reference / QR token
            <input id="reception-code" value={code} onChange={e=>{setCode(e.target.value);setPreview(null);setError('');setResult(null);setIsScanned(false);setManualVerified(false)}} placeholder="SS-ABC123" autoComplete="off" spellCheck={false}/>
          </label>
          <button className="button reception-full" type="submit" disabled={busy||!code.trim()}>Preview check-in</button>
        </form>
        <p className="reception-note"><ShieldCheck size={15}/> QR secrets travel in a protected request body, not in the URL.</p>
      </Panel>
      <div className="reception-right">
        <Panel className="reception-result-panel">
          <div className="reception-panel-title"><h2><CheckCircle2 size={18}/> Verification</h2></div>
          {busy&&!preview&&!result&&<Loading label="Verifying booking"/>}
          {preview&&<div className="reception-preview"><span className="reception-success-icon"><ShieldCheck size={25}/></span><h3>Booking verified</h3><p>Confirm the customer's identity before completing their check-in.</p><div className="reception-key-values"><div><span>Customer</span><strong>{preview.customer_name}</strong></div><div><span>Reference</span><strong>{preview.reference}</strong></div><div><span>Service</span><strong>{preview.service_name} · {preview.staff_name}</strong></div><div><span>Appointment</span><strong>{new Date(preview.starts_at).toLocaleString()}</strong></div><div><span>Status</span><StatusBadge status={preview.status}/></div></div>{!isScanned&&<label className="reception-verify"><input type="checkbox" checked={manualVerified} onChange={e=>setManualVerified(e.target.checked)}/><span>I verified the customer's identity for manual reference check-in.</span></label>}<div className="reception-action-row"><button type="button" className="button ghost" onClick={()=>{setPreview(null);setManualVerified(false)}}><X size={14}/> Cancel</button><button type="button" className="button" onClick={confirm} disabled={busy||(!isScanned&&!manualVerified)}><CheckCircle2 size={15}/> Confirm check-in</button></div></div>}
          {result&&<div className="reception-success"><span className="reception-success-icon"><CheckCircle2 size={32}/></span><h3>Checked in successfully</h3><p>{result.customer_name} · {result.service_name}</p><strong>{result.reference}</strong><span className="small-text muted">The booking status was updated in the database.</span></div>}
          {!busy&&!preview&&!result&&<div className="reception-empty"><ScanLine size={38}/><strong>Awaiting a booking</strong><p>Scan a QR or enter a reference to preview and confirm check-in here.</p></div>}
        </Panel>
        <Panel className="reception-arrivals-panel">
          <div className="reception-panel-title"><h2><Users size={18}/> Today's arrivals</h2><button type="button" className="button ghost small" onClick={()=>void refreshArrivals()} disabled={arrivalsLoading}><RefreshCw size={14}/> Refresh</button></div>
          <p className="small-text muted">Live records for {businessDate(zone)} · {zone}. Up to 100 bookings.</p>
          {arrivalsError&&<ErrorBox message={arrivalsError}/>}
          {arrivalsLoading?<Loading label="Loading appointments"/>:arrivals.length ? <div className="reception-arrival-list">{arrivals.slice(0,8).map(item=><div className="reception-arrival" key={item.reference}><div className="reception-initials">{item.customer_name.split(' ').slice(0,2).map(x=>x[0]).join('').toUpperCase()}</div><div className="reception-arrival-person"><strong>{item.customer_name}</strong><span>{item.service_name} · {item.reference}</span></div><time>{formatTime(item.starts_at,zone)}</time><StatusBadge status={item.status}/></div>)}</div> : <Empty title="No arrivals scheduled today" detail="Newly booked appointments for this date will appear here."/>}
        </Panel>
      </div>
    </div>
    <div className="reception-disclaimer"><AlertCircle size={17}/> Check-in is restricted to the permitted appointment window. Duplicate, expired and cancelled passes are rejected by the backend.</div>
  </div>
}
