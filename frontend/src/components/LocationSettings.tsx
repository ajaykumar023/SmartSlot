import { useEffect,useState } from 'react'
import { api } from '../api'
import Panel from './Panel'
import { ErrorBox } from './Feedback'

type Location={name:string;latitude:number|null;longitude:number|null;configured:boolean}
export default function LocationSettings(){
 const [lat,setLat]=useState(''),[lon,setLon]=useState(''),[msg,setMsg]=useState(''),[error,setError]=useState('')
 useEffect(()=>{api<Location>(`/businesses/${localStorage.getItem('smartslot_business_id')}/location`).then(d=>{setLat(d.latitude==null?'':String(d.latitude));setLon(d.longitude==null?'':String(d.longitude))}).catch(e=>setError((e as Error).message))},[])
 const save=async(e:React.FormEvent)=>{e.preventDefault();setError('');setMsg('');try{await api('/admin/location',{method:'PUT',body:JSON.stringify({latitude:Number(lat),longitude:Number(lon)})});setMsg('Destination saved. Customer GPS tracking is now available.')}catch(e){setError((e as Error).message)}}
 return <Panel title="GPS destination for this business"><p className="small-text muted">Set this branch's actual latitude and longitude to enable ETA. GPS estimates stay disabled until you configure a destination. Example coordinates should only be used for a demo.</p>{error&&<ErrorBox message={error}/>}<form className="form-grid" onSubmit={save}><div className="field"><label htmlFor="gps-lat">Latitude</label><input id="gps-lat" type="number" step="any" min="-90" max="90" required value={lat} onChange={e=>setLat(e.target.value)} placeholder="12.9716"/></div><div className="field"><label htmlFor="gps-lon">Longitude</label><input id="gps-lon" type="number" step="any" min="-180" max="180" required value={lon} onChange={e=>setLon(e.target.value)} placeholder="77.5946"/></div><button className="button" type="submit">Save branch destination</button></form>{msg&&<div className="success-box">{msg}</div>}</Panel>
}
