import { NavLink, useNavigate, useSearchParams } from 'react-router-dom'
import { useEffect, useState, useCallback } from 'react'
import { sessionApi } from '../api/session'
import type { Session } from '../types'

function groupSessions(sessions: Session[]) {
  const now = new Date()
  const today = new Date(now); today.setHours(0, 0, 0, 0)
  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1)
  const weekAgo = new Date(today); weekAgo.setDate(weekAgo.getDate() - 6)

  const groups: { label: string; items: Session[] }[] = []
  let todayItems: Session[] = []
  let yesterdayItems: Session[] = []
  let weekItems: Session[] = []
  let olderItems: Session[] = []

  for (const s of sessions) {
    const d = new Date(s.updated_at)
    if (d >= today) todayItems.push(s)
    else if (d >= yesterday) yesterdayItems.push(s)
    else if (d >= weekAgo) weekItems.push(s)
    else olderItems.push(s)
  }

  if (todayItems.length) groups.push({ label: '今天', items: todayItems })
  if (yesterdayItems.length) groups.push({ label: '昨天', items: yesterdayItems })
  if (weekItems.length) groups.push({ label: '最近 7 天', items: weekItems })
  if (olderItems.length) groups.push({ label: '更早', items: olderItems })
  return groups
}

function formatTime(dateStr: string) {
  const d = new Date(dateStr)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export default function Sidebar() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const activeSessionId = searchParams.get('s')

  const [sessions, setSessions] = useState<Session[]>([])
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')

  const loadSessions = useCallback(async () => {
    try {
      const res = await sessionApi.list()
      setSessions(res.data.items)
    } catch {
      // 静默失败
    }
  }, [])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  // 监听会话变化事件
  useEffect(() => {
    const handler = () => loadSessions()
    window.addEventListener('kqa-sessions-changed', handler)
    return () => window.removeEventListener('kqa-sessions-changed', handler)
  }, [loadSessions])

  const logout = () => {
    localStorage.removeItem('token')
    navigate('/login')
  }

  const handleNewChat = () => {
    window.dispatchEvent(new Event('kqa-new-chat'))
    navigate('/')
  }

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('确定删除这个会话？')) return
    try {
      await sessionApi.delete(id)
      setSessions((prev) => prev.filter((s) => s.id !== id))
      if (activeSessionId === id) navigate('/')
    } catch {
      // 静默失败
    }
  }

  const handleRenameStart = (s: Session, e: React.MouseEvent) => {
    e.stopPropagation()
    setEditingId(s.id)
    setEditTitle(s.title)
  }

  const handleRenameConfirm = async (id: string) => {
    if (!editTitle.trim()) return
    try {
      await sessionApi.rename(id, editTitle.trim())
      setSessions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, title: editTitle.trim() } : s))
      )
    } catch {
      // 静默失败
    }
    setEditingId(null)
  }

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 ${
      isActive
        ? 'bg-white/15 text-white shadow-sm'
        : 'text-white/50 hover:text-white hover:bg-white/8'
    }`

  const groups = groupSessions(sessions)

  const renderSessionItem = (s: Session) => {
    const isActive = s.id === activeSessionId

    if (editingId === s.id) {
      return (
        <div key={s.id} className="px-3 py-1">
          <input
            className="w-full bg-white/10 text-white text-sm px-2 py-1.5 rounded-lg outline-none border border-white/20"
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onBlur={() => handleRenameConfirm(s.id)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleRenameConfirm(s.id)
              if (e.key === 'Escape') setEditingId(null)
            }}
            autoFocus
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )
    }

    return (
      <div
        key={s.id}
        onClick={() => navigate(`/?s=${s.id}`)}
        className={`group flex items-center gap-2 px-3 py-2 mx-2 rounded-xl text-sm cursor-pointer transition-all duration-200 ${
          isActive
            ? 'bg-white/15 text-white shadow-sm'
            : 'text-white/50 hover:text-white hover:bg-white/8'
        }`}
      >
        <svg className="w-4 h-4 shrink-0 opacity-60" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 0 1 1.037-.443 48.282 48.282 0 0 0 5.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z" />
        </svg>
        <span className="truncate flex-1">{s.title}</span>
        <span className="text-[10px] text-white/20 shrink-0 group-hover:hidden">{formatTime(s.updated_at)}</span>
        <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
          <button
            onClick={(e) => handleRenameStart(s, e)}
            className="p-1 rounded text-white/30 hover:text-white/70 hover:bg-white/10"
            title="重命名"
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Z" />
            </svg>
          </button>
          <button
            onClick={(e) => handleDelete(s.id, e)}
            className="p-1 rounded text-white/30 hover:text-red-400 hover:bg-white/10"
            title="删除"
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
            </svg>
          </button>
        </div>
      </div>
    )
  }

  return (
    <aside className="w-60 sidebar-gradient flex flex-col shrink-0 select-none">
      {/* Logo */}
      <div className="flex items-center gap-3 px-5 h-16 border-b border-white/8">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-ocean-300 to-white/80 flex items-center justify-center text-sm font-bold text-ocean-800 shadow-md">
          K
        </div>
        <div>
          <span className="font-heading font-semibold text-white text-sm leading-none block">知识问答系统</span>
          <span className="text-[11px] text-white/30 mt-0.5 block">Enterprise QA</span>
        </div>
      </div>

      {/* 新建对话 */}
      <div className="px-3 pt-4 pb-2">
        <button
          onClick={handleNewChat}
          className="flex items-center gap-2 w-full px-3 py-2.5 rounded-xl border border-white/15 text-white/70 hover:text-white hover:border-white/25 hover:bg-white/8 transition-all text-sm"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          新建对话
        </button>
      </div>

      {/* 会话列表 */}
      <div className="flex-1 overflow-y-auto px-1 pb-2">
        {sessions.length === 0 ? (
          <div className="px-5 mt-6 text-center">
            <p className="text-white/20 text-xs">暂无会话记录</p>
          </div>
        ) : (
          groups.map((group) => (
            <div key={group.label} className="mt-3">
              <p className="text-[11px] text-white/20 font-medium px-5 mb-1">{group.label}</p>
              {group.items.map(renderSessionItem)}
            </div>
          ))
        )}
      </div>

      {/* 底部导航 + 用户 */}
      <div className="border-t border-white/8">
        <nav className="p-3 space-y-0.5">
          <NavLink to="/documents" className={linkClass}>
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
            </svg>
            <span>文档管理</span>
          </NavLink>
        </nav>

        <div className="p-3 border-t border-white/8">
          <div className="flex items-center gap-3 px-3 py-2">
            <div className="w-8 h-8 rounded-full bg-white/15 flex items-center justify-center text-xs text-white/70 font-medium">
              A
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm text-white/80 font-medium truncate">Admin</p>
            </div>
            <button
              onClick={logout}
              className="p-1.5 rounded-lg text-white/30 hover:text-white/70 hover:bg-white/8 transition-all"
              title="退出登录"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15m3 0 3-3m0 0-3-3m3 3H9" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </aside>
  )
}
