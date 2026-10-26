import type { NavItem } from './types'

const home: NavItem = { to: '/', label: 'Dashboard', desc: 'Your stock, suppliers and what needs attention', icon: 'home' }
const assistant: NavItem = { to: '/assistant', label: 'Assistant', desc: 'Report a problem with a photo or ask a question', icon: 'chat' }
const alerts: NavItem = { to: '/alerts', label: 'Alerts', desc: 'Warnings when something upstream or downstream affects you', icon: 'bell', badge: 'alerts' }
const incidents: NavItem = { to: '/incidents', label: 'Incidents', desc: 'Problems reported, with the advice and offers Ariadne made', icon: 'flag' }
const approvals: NavItem = { to: '/approvals', label: 'Approvals', desc: 'Offers waiting for your yes or no', icon: 'check', badge: 'approvals' }
const deals: NavItem = { to: '/deals', label: 'Deals & ledger', desc: 'Deals in progress, completed deals and money movements', icon: 'deals' }
const knowledge: NavItem = { to: '/knowledge', label: 'Knowledge', desc: 'Cited answers on disease, rearing, storage and reeling', icon: 'book' }
const chain: NavItem = { to: '/chain', label: 'Chain', desc: 'The whole supply chain, what-if demand and what Ariadne did', icon: 'chain' }
const system: NavItem = { to: '/system', label: 'System', desc: 'Live data, prices and which models are running', icon: 'cog' }
const evaluation: NavItem = { to: '/eval', label: 'Evaluation', desc: 'How well Ariadne answers and routes, measured', icon: 'chart' }

export const FULL_MAIN = [home, assistant, alerts, incidents, approvals, deals, chain, knowledge]
export const FULL_MORE = [system, evaluation]

export const FARMER_MAIN: NavItem[] = [
  { ...home, label: 'Home', desc: 'How your stock is and what needs doing' },
  { ...assistant, label: 'Report a problem', desc: 'Send a photo of your plants or worms' },
  { ...approvals, label: 'Offers', desc: 'Someone wants to buy or sell: say yes or no' },
  { ...alerts, desc: 'News that affects you' },
  { ...knowledge, label: 'Ask a question', desc: 'Advice on rearing, disease and storage' },
]
export const FARMER_MORE = [chain, deals, incidents, system, evaluation]
