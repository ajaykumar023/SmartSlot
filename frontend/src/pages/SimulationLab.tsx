import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, ArrowRight, CarFront, CheckCircle2, Clock3, MapPin, Route, ShieldCheck, Users } from 'lucide-react'
import { api } from '../api'
import './simulation-lab.css'

type Scenario = 'gap' | 'fully_booked' | 'near_on_time' | 'nearest_unqualified' | 'nearest_full'
type Customer = {customer: string; role: string; time: string | null; original_time: string | null; status: string; kind: string; branch: string}
type Choice = {branch: string; branch_id: string; staff: string; time: string; arrival: string; travel_minutes: number; delay_minutes: number; reason: string}
type Checked = {branch: string; travel_minutes: number; predicted_arrival: string; available_time: string | null; eligible: boolean; reason: string}
type Result = {
  simulation_only: boolean; scenario: Scenario; clock: string; original_branch: string; original_time: string
  original_travel_minutes: number; predicted_arrival: string; max_delay_minutes: number; auto_reroute_opt_in: boolean
  decision: string; outcome: string; selected: Choice | null; branches_checked: Checked[]
  confirmed_customers_displaced: number; waitlist_offer_created_in_demo: boolean
  customers: Customer[]; events: string[]; traffic_provider: string; policy: string
}

const choices: {id: Scenario; label: string; description: string; initialTraffic: number}[] = [
  {id: 'gap', label: 'Traffic jam + reachable clinic', description: 'Auto-transfer Rahul to a qualified, nearer branch', initialTraffic: 25},
  {id: 'nearest_full', label: 'Nearest branch is full', description: 'Select another reachable clinic without bumping people', initialTraffic: 25},
  {id: 'nearest_unqualified', label: 'Nearest doctor not qualified', description: 'Do not assign the wrong specialist just to save distance', initialTraffic: 25},
  {id: 'fully_booked', label: 'All safe slots booked', description: 'No transfer; flag for human review', initialTraffic: 25},
  {id: 'near_on_time', label: 'Customer can arrive on time', description: 'Keep the original appointment; no unnecessary reroute', initialTraffic: 3},
]

export default function SimulationLab() {
  const [scenario, setScenario] = useState<Scenario>('gap')
  const [traffic, setTraffic] = useState(25)
  const [cap, setCap] = useState<15 | 30>(30)
  const [optIn, setOptIn] = useState(true)
  const [result, setResult] = useState<Result | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const run = useCallback(async (s: Scenario, t: number, c: 15 | 30, allowed: boolean) => {
    setBusy(true); setError('')
    try {
      const response = await api<Result>('/admin/simulation/geo-reroute', {
        method: 'POST', body: JSON.stringify({scenario:s, traffic_delay_minutes:t, max_delay_minutes:c, auto_reroute_opt_in:allowed})
      })
      setResult(response)
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }, [])
  useEffect(() => { void run(scenario, traffic, cap, optIn) }, [scenario, traffic, cap, optIn, run])
  const setScenarioChoice = (s: Scenario) => {
    setScenario(s)
    setTraffic(choices.find(item => item.id === s)?.initialTraffic ?? 25)
  }
  const badgeText = (r: Result) => r.outcome === 'auto_rerouted' ? 'Automatically rerouted'
    : r.outcome === 'on_time' ? 'Original slot retained'
    : r.outcome === 'opt_in_required' ? 'Prior permission missing' : 'Staff review needed'
  return <div className="simlab">
    <header className="simlab-head">
      <div><div className="simlab-kicker">AETHERX GEOSMART / MEMBER 4</div>
        <h1 className="page-title">Auto-Reroute Simulation Lab</h1>
        <p className="page-subtitle">Preview automatic traffic-aware appointment recovery across qualified branches in one clinic network — without moving other patients.</p>
      </div>
      <span className="simlab-pill"><ShieldCheck size={16}/> Read-only demo</span>
    </header>
    <div className="simlab-notice"><AlertTriangle size={17}/><span><strong>Fictional demonstration only.</strong> Locations, traffic estimates, available branches and customers are simulated. This screen does not use live Google Maps traffic, track a device or modify PostgreSQL bookings.</span></div>
    <section className="simlab-panel">
      <div className="simlab-section-title"><CarFront size={18}/><h2>Choose a customer situation</h2></div>
      <div className="simlab-scenarios simlab-scenarios-five">
        {choices.map(item => <button type="button" key={item.id} className={`simlab-scenario ${scenario===item.id?'selected':''}`} onClick={()=>setScenarioChoice(item.id)}>
          <strong>{item.label}</strong><span>{item.description}</span>
        </button>)}
      </div>
      <div className="simlab-controls">
        <label>Extra fictional traffic to original clinic <strong>+{traffic} minutes</strong>
          <input type="range" min="0" max="75" step="1" value={traffic} onChange={e=>setTraffic(Number(e.target.value))}/>
        </label>
        <label>Latest allowed replacement <strong>Within {cap} min of original</strong>
          <select value={cap} onChange={e=>setCap(Number(e.target.value) as 15|30)}><option value={15}>15 minutes</option><option value={30}>30 minutes</option></select>
        </label>
      </div>
      <label className="simlab-optin"><input type="checkbox" checked={optIn} onChange={e=>setOptIn(e.target.checked)}/><span><strong>Auto-reroute authorized at booking (demo setting)</strong><small>No separate acceptance screen when eligible. In a real app, customers must explicitly enable this preference first and receive an immediate notification of any transfer.</small></span></label>
    </section>
    {error&&<div className="simlab-error" role="alert">{error}. Sign in as the clinic demo admin, and check FastAPI is running with the update installed.</div>}
    {result&&<>
      <section className="simlab-stats" aria-label="Simulation overview">
        <div><span>Simulated clock</span><strong>{result.clock}</strong></div>
        <div><span>Arrival at original clinic</span><strong>{result.predicted_arrival}</strong></div>
        <div><span>Original appointment</span><strong>{result.original_time}</strong></div>
        <div><span>Confirmed patients displaced</span><strong>{result.confirmed_customers_displaced}</strong></div>
      </section>
      <section className="simlab-panel">
        <div className="simlab-row simlab-response-head"><div><div className="simlab-section-title"><Route size={18}/><h2>GeoSmart decision</h2></div>
          <p className="simlab-subtitle">{result.selected ? `Auto-selected ${result.selected.branch} at ${result.selected.time} — ${result.selected.travel_minutes}-minute journey; ${result.selected.delay_minutes} min change in appointment time.` : result.outcome==='on_time' ? 'Still reachable on time — no reroute needed.' : 'No safe automatic change was made. Original appointment stays reserved.'}</p></div>
          <span className={`simlab-state ${result.outcome}`}>{badgeText(result)}</span></div>
        {result.selected&&<div className="simlab-best"><CheckCircle2 size={20}/><div><strong>Best reachable appointment: {result.selected.branch}</strong><div>New time {result.selected.time} · Predicted arrival {result.selected.arrival} · {result.selected.staff} · Same initial consultation</div></div></div>}
        {busy&&<div className="small-text muted">Recalculating fictional traffic and appointment availability…</div>}
        <div className="simlab-customer-header"><MapPin size={17}/><h3>Branches checked</h3></div>
        <div className="simlab-branches">
          {result.branches_checked.map(branch=><div className={`simlab-branch ${branch.eligible?'eligible':'ineligible'} ${result.selected?.branch===branch.branch?'chosen':''}`} key={branch.branch}>
            <div className="simlab-branch-top"><strong>{branch.branch}</strong>{result.selected?.branch===branch.branch&&<span className="simlab-chosen">Selected</span>}</div>
            <div className="simlab-branch-stat">Drive {branch.travel_minutes} min · ETA {branch.predicted_arrival} · {branch.available_time ? `Available ${branch.available_time}` : 'No eligible time'}</div>
            <div className="simlab-branch-note">{branch.reason}</div>
          </div>)}
        </div>
        <div className="simlab-customer-header"><Users size={17}/><h3>Customers after the decision</h3></div>
        <div className="simlab-customer-list">
          {result.customers.map(customer=><div className="simlab-customer" key={customer.customer}>
            <div className="simlab-person"><div className="simlab-avatar">{customer.customer.charAt(0)}</div><div><strong>{customer.customer}</strong><small>{customer.branch} · {customer.role}</small></div></div>
            <div className="simlab-time">{customer.time ?? 'Waitlist'}</div>
            <span className={`simlab-status ${customer.status}`}>{customer.status.replaceAll('_',' ')}</span>
          </div>)}
        </div>
        <div className="simlab-trace"><h3><Clock3 size={16}/> Why the engine decided this</h3>{result.events.map((line,i)=><div key={i} className="simlab-event"><ArrowRight size={15}/><span>{line}</span></div>)}</div>
      </section>
      <p className="simlab-footnote"><strong>Rule:</strong> {result.policy} ETA source: {result.traffic_provider}.</p>
    </>}
  </div>
}
