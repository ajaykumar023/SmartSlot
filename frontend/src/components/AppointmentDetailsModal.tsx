import { useEffect, useId } from 'react'
import { CalendarClock, ClipboardCopy, Clock3, MapPin, QrCode, ShieldCheck, UserRound, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { Appointment } from '../types'
import StatusBadge from './StatusBadge'

function formatAt(value: string, zone: string) {
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'full', timeStyle: 'short', timeZone: zone || undefined,
    }).format(new Date(value))
  } catch {
    return new Date(value).toLocaleString()
  }
}

export default function AppointmentDetailsModal({ appointment, onClose }:{appointment:Appointment;onClose:()=>void}) {
  const heading = useId()
  const navigate = useNavigate()
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('keydown', keydown)
    return () => document.removeEventListener('keydown', keydown)
  }, [onClose])
  const checkInEligible = ['confirmed','at_risk'].includes(appointment.status)
  return <div className="modal-backdrop detail-backdrop" role="presentation" onMouseDown={e => {if(e.target===e.currentTarget)onClose()}}>
    <section className="modal appointment-detail-modal" role="dialog" aria-modal="true" aria-labelledby={heading}>
      <button type="button" className="modal-close" onClick={onClose} aria-label="Close appointment details"><X size={18}/></button>
      <div className="detail-kicker">BOOKING OVERVIEW</div>
      <div className="detail-title-row"><div><h2 id={heading}>{appointment.customer_name}</h2><div className="small-text muted">Reference {appointment.reference}</div></div><StatusBadge status={appointment.status}/></div>
      <div className="detail-grid">
        <div className="detail-field"><span><CalendarClock size={15}/> Service</span><strong>{appointment.service_name}</strong></div>
        <div className="detail-field"><span><UserRound size={15}/> Professional</span><strong>{appointment.staff_name}</strong><small>{appointment.staff_title}</small></div>
        <div className="detail-field detail-span"><span><Clock3 size={15}/> Scheduled appointment</span><strong>{formatAt(appointment.starts_at,appointment.business_timezone)}</strong><small>Ends {new Intl.DateTimeFormat(undefined,{timeStyle:'short',timeZone:appointment.business_timezone||undefined}).format(new Date(appointment.ends_at))}</small></div>
        <div className="detail-field detail-span"><span><MapPin size={15}/> Branch</span><strong>{appointment.business_name}</strong><small>{appointment.customer_email}</small></div>
      </div>
      <div className="detail-pass-note"><ShieldCheck size={19}/><div><strong>QR credential protected</strong><p>The original QR secret is never returned to administrators. Scan the customer's pass at reception, or verify their identity before using the reference.</p></div></div>
      <div className="detail-actions">
        <button type="button" className="button ghost" onClick={() => navigator.clipboard?.writeText(appointment.reference)}><ClipboardCopy size={15}/> Copy reference</button>
        <button type="button" className="button" disabled={!checkInEligible} onClick={() => { onClose(); navigate(`/admin/check-in?reference=${encodeURIComponent(appointment.reference)}`) }}><QrCode size={15}/> Open check-in desk</button>
      </div>
      {!checkInEligible&&<p className="footer-note">Only confirmed or at-risk bookings can proceed to check-in.</p>}
    </section>
  </div>
}
