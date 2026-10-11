import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { ErrorBox, Loading } from '../components/Feedback'

type Assigned = { reference: string; name: string; service_id: number; starts_at: string; ends_at: string; status: string }
type Presence = 'on_site' | 'break' | 'away'

export default function EmployeeWorkspace() {
 const [appointments,setAppointments]=useState<Assigned[]>([])
 const [busy,setBusy]=useState(true)
 const [updating,setUpdating]=useState(false)
 const [presence,setPresence]=useState<Presence|null>(null)
 const [error,setError]=useState('')
 const load=useCallback(async()=>{
  setBusy(true); setError('')
  try{setAppointments(await api<Assigned[]>('/employee/my-appointments'))}
  catch(e){setError((e as Error).message)}finally{setBusy(false)}
 },[])
 useEffect(()=>{void load()},[load])
 const setStatus=async(status:Presence)=>{
  setUpdating(true);setError('')
  try{
   const response=await api<{status:Presence}>('/employee/my-presence',{method:'PUT',body:JSON.stringify({status})})
   setPresence(response.status)
  }catch(e){setError((e as Error).message)}finally{setUpdating(false)}
 }
 return <div>
  <h1 className="page-title">My appointments</h1>
  <p className="page-subtitle">Your assigned services and availability for this branch.</p>
  {error&&<ErrorBox message={error}/>}
  <section className="panel" style={{marginBottom:20}}>
   <h2>My presence</h2>
   <p className="small-text muted">Update your status for reception. An active appointment is not automatically moved just because you click Break.</p>
   <div style={{display:'flex',gap:10,flexWrap:'wrap'}}>
    {(['on_site','break','away'] as const).map(status=><button type="button" key={status} disabled={updating} aria-pressed={presence===status} className={`button ${presence===status?'':'ghost'} small`} onClick={()=>void setStatus(status)}>{status==='on_site'?'On site':status==='break'?'On break':'Away'}</button>)}
   </div>
   {presence&&<p className="small-text">Current submitted status: {presence.replace('_',' ')}</p>}
  </section>
  <section className="panel"><div style={{display:'flex',justifyContent:'space-between',gap:12,alignItems:'center'}}><h2>Upcoming assignments</h2><button type="button" className="button ghost small" onClick={()=>void load()}>Refresh</button></div>
   {busy?<Loading label="Loading assignments…"/>:appointments.length===0?<p className="muted">No current assignments for this branch.</p>:<div style={{overflowX:'auto'}}><table className="table"><thead><tr><th>Reference</th><th>Customer</th><th>Start</th><th>Status</th></tr></thead><tbody>
    {appointments.map(a=><tr key={a.reference}><td>{a.reference}</td><td>{a.name}</td><td>{new Date(a.starts_at).toLocaleString()}</td><td>{a.status}</td></tr>)}
   </tbody></table></div>}
  </section>
 </div>
}
