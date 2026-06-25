import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { authApi } from '../api/auth'

export default function RegisterPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleRegister = async () => {
    setError('')
    if (password.length < 4) {
      setError('密码至少 4 位')
      return
    }
    setLoading(true)
    try {
      const res = await authApi.register(username, password)
      localStorage.setItem('token', res.data.access_token)
      window.dispatchEvent(new Event('auth-change'))
      navigate('/')
    } catch (e: any) {
      setError(e.response?.data?.detail || '注册失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center relative overflow-hidden bg-gradient-to-br from-ocean-800 via-ocean-900 to-slate-900">
      {/* 背景装饰 */}
      <div className="absolute inset-0 overflow-hidden">
        <div className="absolute -top-40 -right-40 w-96 h-96 rounded-full bg-ocean-400/10 blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-96 h-96 rounded-full bg-ocean-300/10 blur-3xl" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-ocean-500/5 blur-3xl" />
      </div>

      {/* 注册卡片 */}
      <div className="relative w-full max-w-md mx-4">
        <div className="bg-white/95 backdrop-blur-sm rounded-2xl shadow-2xl shadow-black/20 p-8">
          {/* Logo */}
          <div className="text-center mb-8">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-ocean-400 to-ocean-600 flex items-center justify-center text-white text-2xl font-bold shadow-lg shadow-ocean-500/30">
              K
            </div>
            <h1 className="font-heading text-2xl font-bold text-gray-800">创建账号</h1>
            <p className="text-sm text-gray-400 mt-1.5">注册并开始使用知识问答系统</p>
          </div>

          {/* 表单 */}
          <div className="space-y-4">
            {error && (
              <div className="bg-red-50 border border-red-100 text-red-500 text-sm rounded-xl px-4 py-3 flex items-center gap-2">
                <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
                {error}
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-gray-600 mb-1.5">用户名</label>
              <input
                className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-ocean-400 focus:ring-2 focus:ring-ocean-400/20 placeholder:text-gray-300 transition-all"
                placeholder="请输入用户名（至少 2 位）"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-600 mb-1.5">密码</label>
              <input
                className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-ocean-400 focus:ring-2 focus:ring-ocean-400/20 placeholder:text-gray-300 transition-all"
                type="password"
                placeholder="请输入密码（至少 4 位）"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleRegister()}
              />
            </div>

            <button
              className="btn-primary w-full !py-3 !text-sm !rounded-xl mt-2"
              onClick={handleRegister}
              disabled={loading}
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  注册中...
                </span>
              ) : '注册'}
            </button>
          </div>
        </div>

        <p className="text-center text-sm text-white/50 mt-6">
          已有账号？
          <Link to="/login" className="text-ocean-300 hover:text-ocean-200 font-medium ml-1 transition-colors">
            返回登录
          </Link>
        </p>
      </div>
    </div>
  )
}
