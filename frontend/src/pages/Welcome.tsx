import { useEffect, useState } from 'react'
import { ArrowRight, Building2, CalendarCheck2, Check, UserRound } from 'lucide-react'
import { api } from '../api'
import type { Business, Role } from '../types'
import { ErrorBox, Loading } from '../components/Feedback'

export default function Welcome({onLogin}:{onLogin:(role:Role,businessId:number)=>void}) {
 const [businesses,setBusinesses]=useState<Business[]>([])
 const [selected,setSelected]=useState<number>(()=>Number(localStorage.getItem('smartslot_business_id'))||0)
 const [error,setError]=useState('')
 useEffect(()=>{api<Business[]>('/businesses').then(rows=>{setBusinesses(rows);if(!rows.some(b=>b.id===selected)){setSelected(0);localStorage.removeItem('smartslot_business_id')}}).catch(e=>setError((e as Error).message))},[])
 const choose=(id:number)=>{setSelected(id);localStorage.setItem('smartslot_business_id',String(id));sessionStorage.removeItem('smartslot_latest')}
 return <div className="workspace-entry"><header className="workspace-entry-top"><div className="brand"><span className="brand-mark">S</span> SmartSlot</div><span>Appointments, without the extra work.</span></header>
 <div className="workspace-entry-content"><div className="eyebrow">WELCOME TO SMARTSLOT</div><h1>Choose your workspace</h1><p>Book as a customer, or manage daily operations from reception.</p>
 {error&&<ErrorBox message={error}/>}
 <section className="workspace-chooser"><div className="workspace-section-head"><h2>Select a business</h2><span>{businesses.length} demo workspaces</span></div>
 {!businesses.length&&!error?<Loading label="Loading businesses…"/>:<div className="workspace-options">{businesses.map(b=><button type="button" key={b.id} className={`workspace-option ${selected===b.id?'selected':''}`} onClick={()=>choose(b.id)} aria-pressed={selected===b.id}><span className="workspace-option-icon"><Building2 size={20}/></span><span className="workspace-option-text"><strong>{b.name}</strong><small>{b.category_label} · {b.timezone}</small></span><span className="workspace-option-check">{selected===b.id?<Check size={16}/>:null}</span></button>)}</div>}
 </section>
 <div className="workspace-entry-actions"><button className="button" disabled={!selected} onClick={()=>onLogin('customer',selected)}><UserRound size={16}/> Continue as customer <ArrowRight size={16}/></button><button className="button ghost" disabled={!selected} onClick={()=>onLogin('admin',selected)}><CalendarCheck2 size={16}/> Reception workspace</button></div><p className="workspace-entry-note">Demo accounts and fictional bookings · No real customer records</p>
 </div></div>
}
