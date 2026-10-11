export type Role = 'customer' | 'admin' | 'employee'
export type Business = { id:number; name:string; category:string; category_label:string; description:string; timezone:string; staff_label:string }
export type User = { role: Role; name: string; email: string; business_id:number }
export type Service = { id: number; name: string; description: string; duration_minutes: number; buffer_minutes?:number; price?: number | null; active?: boolean }
export type Slot = { staff_id: number; staff_name: string; staff_title:string; starts_at: string; ends_at: string }
export type Appointment = { id:number; reference:string; business_id:number; business_name:string; business_category:string; business_timezone:string; service_id:number; service_name:string; staff_id:number; staff_name:string; staff_title:string; customer_name:string; customer_email:string; starts_at:string; ends_at:string; status:string; qr_token?:string; qr_image?:string }
export type Offer = { id:number; kind:string; reference:string; starts_at:string; original_starts_at?:string; expires_at:string; business_timezone:string }
export type Notice = { id:number; message:string; simulated:boolean; read:boolean; created_at:string }
