/** Member 4 API wrappers for Ajay's customer and the admin teammate's UIs.
 * Uses existing shared api() so business_id and bearer token are added automatically.
 * No UI state/components were changed.
 */
import { api } from './api'

export type QueueStatus = 'confirmed' | 'at_risk' | 'checked_in'
export type ArrivalStatus = 'on_the_way' | 'arrived'

export interface QueueItem {
  reference: string
  starts_at: string
  staff_id: number
  queue_position: number
  people_ahead: number
  status: QueueStatus
  arrival_status: ArrivalStatus | 'not_reported'
  eta_minutes: number | null
  note: string
}
export interface WaitlistItem {
  id: number
  service_id: number
  preferred_date: string
  status: string
  created_at: string
}
export interface SlotOffer {
  id: number
  kind: 'waitlist' | 'queue_shift'
  reference: string | null
  business_name: string
  business_timezone: string
  original_starts_at: string | null
  starts_at: string
  expires_at: string
}
export interface QueueSuggestion {
  reference: string
  customer_name: string
  current_starts_at: string
  staff_id: number
  suggestions: { advance_minutes: number; starts_at: string; ends_at: string; reason: string }[]
}

// Customer actions
export const listMyQueue = () => api<QueueItem[]>('/queue/mine')
export const listMyWaitlist = () => api<WaitlistItem[]>('/waitlist/mine')
export const withdrawWaitlist = (id: number) => api<{status: string}>(`/waitlist/${id}/withdraw`, {method:'POST'})
export const reportArrival = (reference: string, status: ArrivalStatus, eta_minutes?: number) =>
  api<{reference: string; status: ArrivalStatus; verified: boolean}>(`/appointments/${encodeURIComponent(reference)}/arrival`, {
    method: 'POST', body: JSON.stringify({status, eta_minutes: status === 'on_the_way' ? eta_minutes : null})
  })
export const listMyOffers = () => api<SlotOffer[]>('/offers')
export const acceptOffer = (id: number) => api<Record<string,unknown>>(`/offers/${id}/accept`, {method:'POST'})
export const declineOffer = (id: number) => api<{status:string}>(`/offers/${id}/decline`, {method:'POST'})

// Business/admin actions
export const validateQr = (code: string) =>
  api<{valid:boolean;reference:string;customer_name:string;starts_at:string;ends_at:string;service_name:string;staff_name:string;status:string}>(
    '/admin/check-in/preview', {method:'POST', body:JSON.stringify({code})})
export const confirmCheckIn = (code: string) =>
  api<Record<string, unknown>>('/admin/check-in/confirm', {method:'POST', body:JSON.stringify({code})})
export const getQueueRecommendations = () =>
  api<{strategy:string;recommendations:QueueSuggestion[]}>('/admin/queue/recommendations')
export const offerQueueShift = (reference: string, minutes?: number) =>
  api<{offer_id:number;status:string;offered_starts_at:string;reason:string}>(
    `/admin/queue-shift/${encodeURIComponent(reference)}${minutes != null ? '?advance_minutes='+minutes : ''}`, {method:'POST'})
export const evaluateQueue = () =>
  api<{business_id:number;marked_at_risk:string[];customer_eta_alerts:string[];staff_unavailable_ids:number[]}>(
    '/admin/queue-shift/evaluate',{method:'POST'})
export const expireStaleOffers = () => api<{count:number;expired_offer_ids:number[]}>('/admin/offers/expire',{method:'POST'})
export const setStaffPresence = (staffId: number, status: 'on_site'|'away'|'break') =>
  api<{staff_id:number;status:string;source:string}>(`/admin/staff/${staffId}/presence`,{
    method:'POST', body:JSON.stringify({status})
  })
export const reissueQrPass = (reference: string) =>
  api<{reference:string;qr_token:string;qr_image:string}>(
    `/appointments/${encodeURIComponent(reference)}/qr/reissue`, {method:'POST'})
export const getAdminQueueOverview = (date?: string) =>
  api<{date:string;business_id:number;staff_queues:unknown[]}>(
    `/admin/queue/overview${date ? '?date_on='+encodeURIComponent(date):''}`)
