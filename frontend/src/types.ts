export type Role = 'mulberry_farm' | 'silkworm_farm' | 'reeler' | 'spinner'

export interface User {
  id: number; username: string; role: Role; display_name: string
  entity_id: number; entity_name: string; village: string
}

export interface Stock {
  product: string; on_hand: number; reserved: number; available: number
  safety_stock: number; reorder_point: number; sellable: number; daily_demand: number
  days_of_cover: number; degrades_in_days: number; unit_price: number
  is_finished: boolean; status: 'ok' | 'reorder' | 'critical' | 'degrading'
}

export interface Warehouse { name: string; village: string; capacity: number; used: number; utilisation: number; stores: string | null }

export interface EntityView {
  id: number; kind: Role; name: string; owner_name: string; village: string
  relation: string; balance: number; warehouse: Warehouse | null
  capacity: { capacity: number; load: number; utilisation: number; spare?: number }
  stock: Stock[]
  outlook?: any[]
}

export interface Dashboard {
  me: EntityView
  partners: EntityView[]
  summary: { n_buyers: number; n_suppliers: number; alerts: string[] }
}

export const ROLE_LABEL: Record<Role, string> = {
  mulberry_farm: 'Mulberry Farmer', silkworm_farm: 'Silkworm Farmer', reeler: 'Reeler', spinner: 'Spinner / Throwster',
}
export const KIND_LABEL: Record<string, string> = {
  mulberry_farm: 'Mulberry farm', silkworm_farm: 'Silkworm farm', reeler: 'Reeling unit', spinner: 'Twisting mill',
}

export const isFarmer = (r?: Role) => r === 'mulberry_farm' || r === 'silkworm_farm'

/** Plain-language stock status for farmers. */
export const FRIENDLY_STATUS: Record<string, [string, string]> = {
  ok: ['Good', 'ok'], reorder: ['Running low', 'reorder'], critical: ['Very low', 'critical'], degrading: ['Will spoil soon', 'degrading'],
}

export type NavItem = { to: string; label: string; desc: string; icon: string; badge?: 'approvals' | 'alerts' }
