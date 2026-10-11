import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Bell, CalendarDays, CheckCircle2, Clock3, QrCode, RefreshCw, Settings2 } from 'lucide-react'
import { api } from '../api'
import type { Appointment } from '../types'
import { Empty, ErrorBox, Loading } from '../components/Feedback'
import StatusBadge from '../components/StatusBadge'
import { routes } from '../routes'

type OverviewData = {
  today: number; upcoming: number; checked_in: number; at_risk: number
  weekly_counts: number[]; weekly_labels: string[]; appointments: Appointment[]
}
const metrics=[
  {label:'Appointments today',key:'today',icon:CalendarDays},
  {label:'Upcoming bookings',key:'upcoming',icon:Clock3},
  {label:'Checked in',key:'checked_in',icon:CheckCircle2},
  {label:'Needs attention',key:'at_risk',icon:Bell},
] as const
export default function Overview(){
  const [data,setData]=useState<OverviewData|null>(null)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(true)
  const load=async()=>{setBusy(true);try{setData(await api<OverviewData>('/admin/dashboard'));setError('')}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  useEffect(()=>{void load()},[])
  const max=Math.max(1,...(data?.weekly_counts||[]))
  return <div className="overview-page">
    <div className="overview-heading"><div><div className="eyebrow">WORKSPACE / OVERVIEW</div><h1 className="page-title">Reception overview</h1><p className="page-subtitle">Your schedule, arrivals and anything that needs a decision.</p></div><button className="button ghost" onClick={()=>void load()} disabled={busy}><RefreshCw size={15}/> Refresh</button></div>
    {error&&<ErrorBox message={error}/>}
    {busy&&!data?<Loading/>:<>
      <div className="overview-metrics">{metrics.map(m=>{const Icon=m.icon;return <div className="overview-metric" key={m.key}><div className="overview-metric-top"><span>{m.label}</span><Icon size={18}/></div><strong>{data?.[m.key]??'—'}</strong></div>})}</div>
      <div className="overview-content">
        <div className="overview-left">
          <section className="panel overview-bookings"><div className="overview-section-head"><div><h2>Recent bookings</h2><p>Latest appointments in your workspace</p></div><Link className="text-link" to={routes.appointments}>View all <ArrowRight size={14}/></Link></div>
            {data?.appointments?.length?<div className="overview-booking-list">{data.appointments.slice(0,6).map(a=><div className="overview-booking" key={a.id}><div className="overview-booking-icon"><CalendarDays size={17}/></div><div className="overview-booking-copy"><strong>{a.customer_name}</strong><span>{a.service_name} · {new Date(a.starts_at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZone:a.business_timezone})}</span></div><StatusBadge status={a.status}/></div>)}</div>:<Empty title="No appointments yet" detail="New bookings will appear here as they come in."/>}
          </section>
          <section className="panel overview-bookings"><div className="overview-section-head"><div><h2>Coming up this week</h2><p>Confirmed arrivals over the next seven days</p></div></div><div className="overview-bars">{data?.weekly_counts?.map((v,i)=><div className="overview-bar-column" key={i}><strong>{v}</strong><div className="overview-bar-track"><span style={{height:`${Math.max(6,(v/max)*100)}%`}}/></div><small>{data.weekly_labels[i]||`D${i+1}`}</small></div>)}</div></section>
        </div>
        <aside className="overview-right"><section className="panel overview-actions"><div className="overview-section-head"><div><h2>Quick actions</h2><p>The tools you use most</p></div></div>
        {[{name:'Reception check-in',sub:'Scan or verify a booking',to:routes.scanner,icon:QrCode},{name:'Manage services',sub:'Availability and service status',to:routes.services,icon:Settings2},{name:'Automation & alerts',sub:'Review scheduler activity',to:routes.automation,icon:Bell}].map(action=>{const Icon=action.icon;return <Link key={action.name} className="overview-action" to={action.to}><span className="overview-action-icon"><Icon size={18}/></span><span><strong>{action.name}</strong><small>{action.sub}</small></span><ArrowRight size={17}/></Link>})}
        </section><div className="overview-help"><CheckCircle2 size={18}/><div><strong>Automatic scheduling is available</strong><p>Customers can choose the best open appointment without reception assigning staff manually.</p></div></div></aside>
      </div>
    </>}
  </div>
}
