import { useEffect,useState } from 'react'
import { Bell, RefreshCw, Sparkles, CheckCheck, ShieldCheck } from 'lucide-react'
import Panel from '../components/Panel'
import { api } from '../api'
import { ErrorBox, Empty } from '../components/Feedback'

type Alert={id:number;message:string;kind:string;reference:string|null;created_at:string;read:boolean}
type AutomationResult={expired_offers:number;created_offers:number;strategy:string;offers:{offer_id:number;reference:string}[]}
export default function AutomationCenter(){
 const [alerts,setAlerts]=useState<Alert[]>([]),[error,setError]=useState(''),[run,setRun]=useState<AutomationResult|null>(null),[busy,setBusy]=useState(false)
 const load=()=>api<Alert[]>('/admin/alerts').then(setAlerts).catch(e=>setError((e as Error).message))
 useEffect(()=>{void load();const id=window.setInterval(()=>void load(),30000);return ()=>clearInterval(id)},[])
 const evaluate=async()=>{setBusy(true);setError('');try{setRun(await api<AutomationResult>('/admin/automation/run',{method:'POST'}));await load()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 const mark=async(a:Alert)=>{try{await api(`/admin/alerts/${a.id}/read`,{method:'POST'});await load()}catch(e){setError((e as Error).message)}}
 return <><h1 className="page-title">Smart Auto-Allocator</h1><p className="page-subtitle">Explainable scheduling automation, alerts and released-slot matching.</p>
 <div className="notice"><ShieldCheck size={18}/> The engine never steals a confirmed slot. It offers eligible released appointments to waitlisted customers in join-time order. Customers must accept waitlist offers before a booking is final.</div>
 {error&&<ErrorBox message={error}/>}<div className="grid grid-2"><Panel title="Allocation engine"><div className="inline"><Sparkles size={22}/><strong>Rule-based smart matching</strong></div><p className="small-text muted">The backend runs an automatic sweep every 60 seconds when enabled in .env. It also matches a waitlist immediately after a cancellation. Use the button to run a sweep now.</p><button disabled={busy} className="button" onClick={()=>void evaluate()}><RefreshCw size={15}/>{busy?'Checking…':'Run allocation now'}</button>{run&&<div className="success-box" style={{marginTop:12}}>Matched {run.created_offers} released slots. Expired {run.expired_offers} old offers. Strategy: {run.strategy}</div>}</Panel>
 <Panel title="How the algorithm chooses"><div className="geo-rule"><span>1</span> Freed and verified available slot</div><div className="geo-rule"><span>2</span> Same service and matching date</div><div className="geo-rule"><span>3</span> Qualified, active staff and no conflict</div><div className="geo-rule"><span>4</span> Earliest eligible waitlist join time</div><div className="geo-rule"><span>5</span> Send customer offer + reception alert</div><p className="footer-note">This is a transparent scheduling algorithm, not a trained AI model. Google GPS availability is independent.</p></Panel></div>
 <Panel title="Reception alerts"><div className="inline" style={{justifyContent:'space-between',marginBottom:12}}><strong><Bell size={16}/> {alerts.filter(a=>!a.read).length} unread alerts</strong><button className="button ghost small" onClick={()=>void load()}><RefreshCw size={14}/> Refresh</button></div>
 {alerts.length?alerts.map(a=><div key={a.id} className={`slot ${a.read?'':'geo-unread'}`}><div><strong>{a.kind.replaceAll('_',' ')}{a.reference?` · ${a.reference}`:''}</strong><div className="small-text">{a.message}</div><div className="small-text muted">{new Date(a.created_at).toLocaleString()}</div></div>{!a.read&&<button className="button ghost small" onClick={()=>void mark(a)}><CheckCheck size={15}/> Mark read</button>}</div>):<Empty title="No alerts yet" detail="Arrival warnings and automatic waitlist matches appear here."/>}
 </Panel></>
}
