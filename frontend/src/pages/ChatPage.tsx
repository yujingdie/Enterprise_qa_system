import { useState, useRef, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { sessionApi } from '../api/session'
import { fetchSSE } from '../api/stream'
import type { SourceInfo, ConversationMessage } from '../types'
import ChatBubble from '../components/ChatBubble'
import SourceCard from '../components/SourceCard'

// ===== 模块级流式状态：跨组件卸载/重挂载持久 =====
let globalLoading = false
let globalAnswer = ''
let globalSources: SourceInfo[] | null = null
let globalStreamSessionId: string | null = null
let globalAbortController: AbortController | null = null
let globalToolStatus: string | null = null
const globalListeners = new Set<() => void>()

// per-session 消息缓存，切换会话时不丢失 optimistic message
const messageCache = new Map<string, ConversationMessage[]>()

function notifyListeners() {
  globalListeners.forEach((fn) => fn())
}

function startStream(
  question: string,
  sessionId: string | null,
  token: string,
  onFinalize: (newSessionId: string | null) => void,
) {
  globalLoading = true
  globalAnswer = ''
  globalSources = null
  globalToolStatus = null
  globalStreamSessionId = sessionId || '__new__'
  const controller = new AbortController()
  globalAbortController = controller
  notifyListeners()

  let answerAcc = ''

  fetchSSE(question, sessionId, token, {
    onSources: (sources) => {
      globalSources = sources
      globalToolStatus = null
      notifyListeners()
    },
    onAnswer: (chunk) => {
      answerAcc += chunk
      globalAnswer = answerAcc
      globalToolStatus = null
      notifyListeners()
    },
    onToolCall: (data) => {
      const toolNames: Record<string, string> = {
        search_knowledge_base: '正在搜索知识库',
        search_by_filename: '正在读取文件内容',
        list_documents: '正在查看文档列表',
      }
      globalToolStatus = toolNames[data.name] || `正在调用 ${data.name}`
      notifyListeners()
    },
    onDone: (data) => {
      globalLoading = false
      globalStreamSessionId = null
      notifyListeners()
      onFinalize(data.session_id)
    },
    onAbort: () => {
      globalLoading = false
      globalToolStatus = null
      globalStreamSessionId = null
      notifyListeners()
      onFinalize(null)
    },
    onError: () => {
      globalLoading = false
      globalToolStatus = null
      globalStreamSessionId = null
      notifyListeners()
      onFinalize(null)
    },
  }, controller.signal)
}
// ===== END 模块级状态 =====

const suggestions = [
  { text: 'CAP定理包含哪三个要素？', icon: '🏗️' },
  { text: '微服务架构有哪些核心特征？', icon: '🔧' },
  { text: 'ATAM评估方法的流程是什么？', icon: '📊' },
  { text: '管道-过滤器和批处理风格有什么区别？', icon: '⚙️' },
]

export default function ChatPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const sessionId = searchParams.get('s')

  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)
  const messagesRef = useRef(messages)
  messagesRef.current = messages

  // 仅当当前会话是流式会话时才同步 loading 状态
  const isCurrentSessionStreaming = globalLoading && (globalStreamSessionId === sessionId || globalStreamSessionId === '__new__')
  const [loading, setLoading] = useState(isCurrentSessionStreaming)
  const [streamingAnswer, setStreamingAnswer] = useState(isCurrentSessionStreaming ? globalAnswer : '')
  const [streamingSources, setStreamingSources] = useState<SourceInfo[] | null>(isCurrentSessionStreaming ? globalSources : null)
  const [toolStatus, setToolStatus] = useState<string | null>(isCurrentSessionStreaming ? globalToolStatus : null)

  // 加载历史会话消息（使用 messageCache 保留 optimistic message）
  useEffect(() => {
    if (!sessionId) {
      setMessages([])
      return
    }
    // 缓存中有就先用（保留 optimistic message）
    const cached = messageCache.get(sessionId)
    if (cached) {
      setMessages(cached)
      return
    }
    let cancelled = false
    sessionApi.get(sessionId).then((res) => {
      if (cancelled) return
      const msgs = res.data.messages
      messageCache.set(sessionId, msgs)
      setMessages(msgs)
    }).catch(() => {
      if (!cancelled) setMessages([])
    })
    return () => { cancelled = true }
  }, [sessionId])

  // 订阅模块级状态，仅当前会话是流式会话时才同步
  useEffect(() => {
    const sync = () => {
      const isActive = globalLoading && (globalStreamSessionId === sessionId || globalStreamSessionId === '__new__')
      setLoading(isActive)
      setStreamingAnswer(isActive ? globalAnswer : '')
      setStreamingSources(isActive ? globalSources : null)
      setToolStatus(isActive ? globalToolStatus : null)
    }
    globalListeners.add(sync)
    sync()
    return () => { globalListeners.delete(sync) }
  }, [sessionId])

  // 缓存同步：messages 变化时写回 messageCache
  useEffect(() => {
    if (sessionId && messages.length > 0) {
      messageCache.set(sessionId, messages)
    }
  }, [sessionId, messages])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingAnswer])

  const handleAsk = useCallback(async (q?: string) => {
    const question = q || input.trim()
    if (!question || globalLoading) return
    setInput('')

    const optimisticMsg: ConversationMessage = {
      id: 'temp-' + Date.now(),
      question,
      answer: '',
      sources: [],
      created_at: new Date().toISOString(),
    }

    // 写入 messageCache 并更新视图
    const currentSid = sessionId || '__pending__'
    const existing = messageCache.get(currentSid) || []
    const updatedCache = [...existing, optimisticMsg]
    messageCache.set(currentSid, updatedCache)
    setMessages(updatedCache)

    startStream(question, sessionId, localStorage.getItem('token') || '', (newSessionId) => {
      const finalAnswer = globalAnswer || '（已停止生成）'
      const finalSources = globalSources
      // 从 __pending__ 缓存取出 optimistic message 并填入最终答案
      const pending = messageCache.get(currentSid) || []
      const updated = pending.map((m) =>
        m.id.startsWith('temp-') && !m.answer
          ? { ...m, answer: finalAnswer, sources: finalSources || [] }
          : m,
      )
      // 同时写入两个 key：pending（当前渲染）+ 真实 ID（URL 更新后 useEffect 读取）
      messageCache.set(currentSid, updated)
      if (newSessionId) {
        messageCache.set(newSessionId, updated)
        setMessages(updated)
        window.dispatchEvent(new Event('kqa-sessions-changed'))
        setSearchParams({ s: newSessionId })
      } else {
        setMessages(updated)
      }
    })
  }, [input, sessionId, setSearchParams])

  const handleStop = useCallback(() => {
    globalAbortController?.abort()
    globalLoading = false
    globalStreamSessionId = null
    globalToolStatus = null
    notifyListeners()
  }, [])

  // 监听 Sidebar 的新建对话事件
  const handleNewChatRef = useRef(() => {
    if (globalLoading) {
      globalAbortController?.abort()
    }
    globalLoading = false
    globalAnswer = ''
    globalSources = null
    globalToolStatus = null
    globalStreamSessionId = null
    setMessages([])
    setSearchParams({})
  })

  useEffect(() => {
    const handler = () => handleNewChatRef.current()
    window.addEventListener('kqa-new-chat', handler)
    return () => window.removeEventListener('kqa-new-chat', handler)
  }, [])

  return (
    <div className="flex flex-col h-full chat-gradient">
      {/* 对话区 */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4">
          {messages.length === 0 && !loading ? (
            <div className="flex flex-col items-center justify-center min-h-[calc(100vh-200px)] pb-12">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-ocean-400 to-ocean-600 flex items-center justify-center text-white text-2xl font-bold shadow-lg shadow-ocean-500/20 mb-5">
                K
              </div>
              <h1 className="font-heading text-3xl font-bold text-gray-800 mb-2">
                知识问答系统
              </h1>
              <p className="text-gray-400 text-sm mb-10">
                向 AI 提问，基于您的知识库获取精准答案
              </p>

              <div className="grid grid-cols-2 gap-3 w-full max-w-lg">
                {suggestions.map((s) => (
                  <button
                    key={s.text}
                    onClick={() => handleAsk(s.text)}
                    className="group text-left p-4 rounded-2xl border border-gray-200/80 hover:border-ocean-300 hover:bg-white hover:shadow-md hover:shadow-ocean-100/50 transition-all duration-300"
                  >
                    <span className="text-lg mb-2 block">{s.icon}</span>
                    <span className="text-sm text-gray-600 group-hover:text-ocean-700 leading-relaxed transition-colors">
                      {s.text}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="py-6 space-y-6">
              {messages.map((m, idx) => {
                const isLastStreaming = loading && idx === messages.length - 1 && !m.answer
                return (
                <div key={m.id} className="space-y-4">
                  <ChatBubble role="user" content={m.question} />
                  {m.answer ? (
                    <ChatBubble role="assistant" content={m.answer} />
                  ) : isLastStreaming ? null : (
                    <div className="flex items-start gap-3">
                      <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-ocean-400 to-ocean-600 flex items-center justify-center text-white text-xs font-medium shrink-0 shadow-sm">AI</div>
                      <div className="bg-amber-50 border border-amber-100 text-amber-600 text-xs rounded-2xl rounded-tl-md px-4 py-3">
                        该回答生成失败，可重新提问
                      </div>
                    </div>
                  )}
                  {m.sources && m.sources.length > 0 && (
                    <div className="ml-12">
                      <p className="text-xs text-gray-400 mb-1.5 font-medium">参考来源</p>
                      <div className="flex flex-wrap gap-2">
                        {m.sources.map((s, j) => (
                          <SourceCard key={j} source={s} />
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                )
              })}

              {loading && (
                <div className="space-y-4">
                  {streamingSources && streamingSources.length > 0 && (
                    <div className="ml-12">
                      <p className="text-xs text-gray-400 mb-1.5 font-medium">参考来源</p>
                      <div className="flex flex-wrap gap-2">
                        {streamingSources.map((s, j) => (
                          <SourceCard key={j} source={s} />
                        ))}
                      </div>
                    </div>
                  )}
                  {streamingAnswer ? (
                    <ChatBubble role="assistant" content={streamingAnswer} streaming />
                  ) : toolStatus ? (
                    <div className="flex items-start gap-3">
                      <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-ocean-400 to-ocean-600 flex items-center justify-center text-white text-xs font-medium shrink-0 shadow-sm">AI</div>
                      <div className="bg-white border border-gray-100 rounded-2xl rounded-tl-md px-5 py-4 shadow-sm">
                        <div className="flex items-center gap-2 text-sm text-gray-500">
                          <svg className="w-4 h-4 animate-spin text-ocean-400" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                          </svg>
                          {toolStatus}...
                        </div>
                      </div>
                    </div>
                  ) : (
                    <ChatBubble role="assistant" content="" loading />
                  )}
                </div>
              )}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* 输入区 */}
      <div className="border-t border-gray-100/80 bg-white/80 backdrop-blur-sm px-4 py-4">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-end gap-2 border border-gray-200 rounded-2xl px-4 py-3 focus-within:border-ocean-400 focus-within:ring-2 focus-within:ring-ocean-400/15 transition-all bg-white shadow-sm shadow-gray-100/50">
            <textarea
              className="flex-1 outline-none text-sm bg-transparent placeholder:text-gray-300 resize-none min-h-[20px] max-h-[120px] leading-relaxed"
              placeholder="输入你的问题..."
              rows={1}
              value={input}
              onChange={(e) => {
                setInput(e.target.value)
                e.target.style.height = 'auto'
                e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px'
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleAsk()
                }
              }}
              disabled={loading}
            />
            {loading ? (
              <button
                className="shrink-0 w-9 h-9 rounded-xl bg-red-500 text-white flex items-center justify-center hover:bg-red-600 transition-all duration-200 active:scale-95"
                onClick={handleStop}
                title="停止生成"
              >
                <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                  <rect x="4" y="4" width="16" height="16" rx="3" />
                </svg>
              </button>
            ) : (
              <button
                className="shrink-0 w-9 h-9 rounded-xl bg-ocean-500 text-white flex items-center justify-center hover:bg-ocean-600 disabled:opacity-25 disabled:cursor-not-allowed transition-all duration-200 active:scale-95"
                onClick={() => handleAsk()}
                disabled={!input.trim()}
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 12 3.269 3.125A59.769 59.769 0 0 1 21.485 12 59.768 59.768 0 0 1 3.27 20.875L5.999 12Zm0 0h7.5" />
                </svg>
              </button>
            )}
          </div>
          <p className="text-[11px] text-gray-300 text-center mt-2.5">
            知识问答系统 · 基于文档内容生成答案
          </p>
        </div>
      </div>
    </div>
  )
}
