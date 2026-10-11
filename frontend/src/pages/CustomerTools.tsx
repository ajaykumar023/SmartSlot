import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { MapPin, Navigation, QrCode, RefreshCw, ShieldCheck, StopCircle } from 'lucide-react'
import type { Appointment } from '../types'
import CustomerPassModal from '../components/CustomerPassModal'
import Panel from '../components/Panel'
import { ErrorBox, Loading, Empty } from '../components/Feedback'

type Destination={name:string;latitude:number|null;longitude:number|null;configured:boolean}
type TravelReport={reference:string;eta_minutes:number;distance_km:number;arrival_at:string;appointment_at:string;status:string;source:string;traffic_aware:boolean;note:string}

export function CustomerPasses(){
 const [rows,setRows]=useState<Appointment[]>([]),[selected,setSelected]=useState<Appointment|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true)
 useEffect(()=>{api<Appointment[]>('/appointments/mine').then(setRows).catch(e=>setError((e as Error).message)).finally(()=>setLoading(false))},[])
 const active=rows.filter(x=>['confirmed','at_risk'].includes(x.status))
 const prettyDate=(a:Appointment)=>new Intl.DateTimeFormat(undefined,{weekday:'short',month:'short',day:'numeric',timeZone:a.business_timezone}).format(new Date(a.starts_at))
 const prettyTime=(a:Appointment)=>new Intl.DateTimeFormat(undefined,{hour:'numeric',minute:'2-digit',timeZone:a.business_timezone}).format(new Date(a.starts_at))
 return <div className="customer-passes-page"><div className="page-heading"><div><span className="eyebrow">YOUR APPOINTMENTS</span><h1 className="page-title">Check-in passes</h1><p className="page-subtitle">Everything you need for your visit, all in one place.</p></div></div>
 {error&&<ErrorBox message={error}/>}<div className="pass-list">{loading?<Loading/>:active.map(a=><article className="booking-pass-row" key={a.id}>
   <div className="booking-date"><span>{prettyDate(a).split(' ')[0]}</span><strong>{new Intl.DateTimeFormat(undefined,{day:'2-digit',timeZone:a.business_timezone}).format(new Date(a.starts_at))}</strong><span>{new Intl.DateTimeFormat(undefined,{month:'short',timeZone:a.business_timezone}).format(new Date(a.starts_at))}</span></div>
   <div className="booking-main"><span className="eyebrow">{a.business_name}</span><h2>{a.service_name}</h2><p>{prettyTime(a)} · {a.staff_name}</p><span className="booking-ref">{a.reference}</span></div>
   <button className="button" onClick={()=>setSelected(a)}><QrCode size={16}/> View pass</button>
 </article>)}{!loading&&!active.length&&<Empty title="No upcoming appointments" detail="Book a service to see your check-in pass here."/>}</div>
 <p className="pass-explainer"><QrCode size={16}/> Real QR codes are released on appointment day. Use the preview inside a pass to rehearse the demo without creating a valid credential.</p>
 {selected&&<CustomerPassModal appointment={selected} onClose={()=>setSelected(null)}/>}</div>
}
export function TravelTracker(){
 const [bookings,setBookings]=useState<Appointment[]>([]),[reference,setReference]=useState(''),[destination,setDestination]=useState<Destination|null>(null),[error,setError]=useState(''),[report,setReport]=useState<TravelReport|null>(null),[watching,setWatching]=useState(false),[position,setPosition]=useState<{latitude:number;longitude:number;accuracy:number;timestamp:number}|null>(null),[busy,setBusy]=useState(false)
 const watchId=useRef<number|null>(null),lastSent=useRef(0)
 useEffect(()=>{Promise.all([api<Appointment[]>('/appointments/mine'),api<Destination>(`/businesses/${localStorage.getItem('smartslot_business_id')}/location`)]).then(([b,d])=>{const active=b.filter(a=>['confirmed','at_risk'].includes(a.status));setBookings(active);setReference(active[0]?.reference||'');setDestination(d)}).catch(e=>setError((e as Error).message));return ()=>{if(watchId.current!==null)navigator.geolocation.clearWatch(watchId.current)}},[])
 const send=async(lat:number,lon:number,accuracy:number,timestamp:number)=>{
  if(!reference)return
  setBusy(true);setError('')
  try {const data=await api<TravelReport>(`/appointments/${reference}/travel-eta`,{method:'POST',body:JSON.stringify({latitude:lat,longitude:lon,accuracy_meters:accuracy,captured_at:new Date(timestamp).toISOString()})});setReport(data)}
  catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 const start=()=>{
  if(!navigator.geolocation){setError('Your browser does not support GPS location.');return}
  setError('');setReport(null)
  watchId.current=navigator.geolocation.watchPosition(p=>{
   const c={latitude:p.coords.latitude,longitude:p.coords.longitude,accuracy:p.coords.accuracy,timestamp:p.timestamp};setPosition(c)
   if(Date.now()-lastSent.current>=60000){lastSent.current=Date.now();void send(c.latitude,c.longitude,c.accuracy,c.timestamp)}
  },e=>{setError(e.message);setWatching(false)}, {enableHighAccuracy:true,maximumAge:15000,timeout:20000})
  setWatching(true)
 }
 const stop=()=>{if(watchId.current!==null)navigator.geolocation.clearWatch(watchId.current);watchId.current=null;setWatching(false);setPosition(null)}
 const directions=destination?.configured&&position?`https://www.google.com/maps/dir/?api=1&origin=${position.latitude},${position.longitude}&destination=${destination.latitude},${destination.longitude}&travelmode=driving`:null
 return <><h1 className="page-title">On my way · GPS tracker</h1><p className="page-subtitle">Optional live device location and travel estimates. We never retain your exact GPS coordinates in the backend.</p>
 {error&&<ErrorBox message={error}/>}<Panel title="Travel to appointment"><div className="field"><label htmlFor="travel-booking">Appointment</label><select id="travel-booking" value={reference} onChange={e=>{stop();setReference(e.target.value);setReport(null)}}>{bookings.map(b=><option key={b.reference} value={b.reference}>{b.service_name} · {b.reference} · {new Date(b.starts_at).toLocaleString()}</option>)}</select></div>
 <div className="spacer"/><div className="inline"><MapPin size={18}/><strong>{destination?.name||'Destination'}</strong></div><p className="small-text muted">{destination?.configured?'Branch coordinates configured.':'Admin must configure branch coordinates in Settings before tracking can start.'}</p>
 <div className="inline" style={{marginTop:12}}><button className="button" onClick={start} disabled={watching||!reference||!destination?.configured}><Navigation size={16}/> Start sharing location</button>{watching&&<button className="button ghost" onClick={stop}><StopCircle size={16}/> Stop</button>}{position&&<button className="button secondary" disabled={busy} onClick={()=>void send(position.latitude,position.longitude,position.accuracy,position.timestamp)}><RefreshCw size={16}/> Refresh ETA</button>}</div>
 <p className="footer-note">Location permission is requested by your browser. Updates are limited to once per minute while enabled; stop sharing at any time. GPS normally needs HTTPS, or localhost for development.</p>
 </Panel>
 {position&&<Panel title="Your current location"><div className="geo-map"><iframe title="Approximate current location map" src={`https://www.openstreetmap.org/export/embed.html?bbox=${position.longitude-.004}%2C${position.latitude-.004}%2C${position.longitude+.004}%2C${position.latitude+.004}&layer=mapnik&marker=${position.latitude}%2C${position.longitude}`} loading="lazy" referrerPolicy="no-referrer" /></div><p className="small-text muted">GPS accuracy: approximately {Math.round(position.accuracy)} m. Map display depends on internet connectivity.</p>{directions&&<a className="button secondary small" href={directions} target="_blank" rel="noopener noreferrer"><Navigation size={15}/> Open directions in Google Maps</a>}</Panel>}
 {report&&<Panel title="Arrival prediction"><div className="geo-result"><div><span className="small-text muted">Estimated drive</span><h2>{report.eta_minutes} min</h2></div><div><span className="small-text muted">Distance</span><h2>{report.distance_km} km</h2></div><div><span className="small-text muted">Status</span><h2>{report.status.replaceAll('_',' ')}</h2></div></div><div className={`notice ${!report.traffic_aware?'geo-demo':''}`}><ShieldCheck size={16}/> {report.traffic_aware?'Traffic-aware ETA from Google Routes':'DEMO ONLY: straight-line approximation, not road routing or real traffic'}.</div><p className="small-text muted">{report.note}</p></Panel>}
 </>
}
