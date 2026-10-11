const API = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || 'http://localhost:8000/api'
export class ApiError extends Error { constructor(message:string, public status:number) { super(message) } }
export async function api<T>(path:string, options:RequestInit = {}):Promise<T> {
  const token = localStorage.getItem('smartslot_token')
  const publicCatalog = path === '/businesses' || path.startsWith('/businesses/') || path.startsWith('/auth/')
  const businessId = localStorage.getItem('smartslot_business_id')
  const url = new URL(`${API}${path}`, window.location.origin)
  if (!publicCatalog && businessId && !url.searchParams.has('business_id')) url.searchParams.set('business_id', businessId)
  const response = await fetch(url.toString(), { ...options, headers: { 'Content-Type':'application/json', ...(token ? {Authorization:`Bearer ${token}`} : {}), ...options.headers } })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(data.detail || 'Something went wrong. Please try again.', response.status)
  return data as T
}
export const apiBase = API
