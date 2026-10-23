import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, getToken, post, setToken } from './api'
import type { User } from './types'

interface Ctx { user: User | null; loading: boolean; login: (u: string, p: string) => Promise<void>; logout: () => void }
const AuthCtx = createContext<Ctx>(null!)
export const useAuth = () => useContext(AuthCtx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(!!getToken())

  useEffect(() => {
    if (!getToken()) return
    api<User>('/api/auth/me').then(setUser).catch(() => setToken(null)).finally(() => setLoading(false))
  }, [])

  const login = async (username: string, password: string) => {
    const r = await post<{ token: string; user: User }>('/api/auth/login', { username, password })
    setToken(r.token)
    setUser(r.user)
  }
  const logout = () => { setToken(null); setUser(null) }
  return <AuthCtx.Provider value={{ user, loading, login, logout }}>{children}</AuthCtx.Provider>
}
