import { useEffect, useState } from 'react'
import { docsApi } from '../api/documents'
import type { DocInfo } from '../types'
import DocumentUpload from '../components/DocumentUpload'

const PAGE_SIZE = 10

export default function DocumentPage() {
  const [docs, setDocs] = useState<DocInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)

  const fetchDocs = async () => {
    try {
      const res = await docsApi.list()
      setDocs(res.data.documents)
      return res.data.documents
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDocs()
  }, [])

  // 轮询：有处理中的文档时每 3 秒刷新
  const [polling, setPolling] = useState(false)

  const startPolling = () => {
    if (polling) return
    setPolling(true)
  }

  useEffect(() => {
    if (!polling) return
    const timer = setInterval(async () => {
      const latest = await fetchDocs()
      if (latest && !latest.some(d => d.status === 'processing' || d.status === 'pending')) {
        setPolling(false)
      }
    }, 3000)
    return () => clearInterval(timer)
  }, [polling])

  const handleDelete = async (id: string) => {
    if (!confirm('确定要删除该文档吗？')) return
    await docsApi.remove(id)
    fetchDocs()
  }

  // 分页
  const totalPages = Math.max(1, Math.ceil(docs.length / PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const paged = docs.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)

  const statusBadge = (s: string) => {
    const map: Record<string, { label: string; cls: string }> = {
      completed: { label: '已完成', cls: 'bg-emerald-50 text-emerald-600 border-emerald-100' },
      processing: { label: '处理中', cls: 'bg-amber-50 text-amber-600 border-amber-100' },
      pending: { label: '等待中', cls: 'bg-gray-50 text-gray-500 border-gray-100' },
      failed: { label: '失败', cls: 'bg-red-50 text-red-500 border-red-100' },
    }
    const m = map[s] || { label: s, cls: 'bg-gray-50 text-gray-500 border-gray-100' }
    return <span className={`text-xs px-2.5 py-1 rounded-full border font-medium ${m.cls}`}>{m.label}</span>
  }

  const fileTypeIcon = (type: string) => {
    const colors: Record<string, string> = {
      pdf: 'text-red-400',
      docx: 'text-blue-400',
      doc: 'text-blue-400',
      pptx: 'text-orange-400',
      ppt: 'text-orange-400',
      txt: 'text-gray-400',
      md: 'text-gray-400',
    }
    return (
      <svg className={`w-5 h-5 ${colors[type] || 'text-gray-400'}`} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
      </svg>
    )
  }

  return (
    <div className="h-full flex flex-col bg-gray-50/50">
      {/* Header */}
      <div className="px-8 py-5 bg-white border-b border-gray-100">
        <div className="max-w-5xl mx-auto">
          <h1 className="text-lg font-heading font-semibold text-gray-800">文档管理</h1>
          <p className="text-sm text-gray-400 mt-0.5">上传和管理知识库文档</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-8">
        <div className="max-w-5xl mx-auto space-y-6">
          {/* 上传区 */}
          <div className="bg-white border border-gray-100 rounded-2xl p-6 shadow-sm">
            <DocumentUpload onUploaded={fetchDocs} onStartPolling={startPolling} />
          </div>

          {/* 文档列表 */}
          <div className="bg-white border border-gray-100 rounded-2xl shadow-sm overflow-hidden">
            {loading ? (
              <div className="flex items-center justify-center py-20">
                <div className="flex gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-ocean-300 animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-2 h-2 rounded-full bg-ocean-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-2 h-2 rounded-full bg-ocean-500 animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            ) : docs.length === 0 ? (
              <div className="text-center py-20">
                <svg className="w-12 h-12 mx-auto text-gray-200 mb-3" fill="none" viewBox="0 0 24 24" strokeWidth={1} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m6.75 12H9.75m0-3h6m-6 0a9 9 0 1 1 18 0" />
                </svg>
                <p className="text-gray-300 text-base mb-1">暂无文档</p>
                <p className="text-gray-300 text-sm">上传文档以开始构建知识库</p>
              </div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-50 bg-gray-50/50">
                        <th className="text-left text-gray-400 font-medium px-6 py-3">文件名</th>
                        <th className="text-left text-gray-400 font-medium px-6 py-3">类型</th>
                        <th className="text-left text-gray-400 font-medium px-6 py-3">大小</th>
                        <th className="text-left text-gray-400 font-medium px-6 py-3">切片</th>
                        <th className="text-left text-gray-400 font-medium px-6 py-3">状态</th>
                        <th className="text-right text-gray-400 font-medium px-6 py-3">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paged.map((d) => (
                        <tr key={d.id} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50 transition-colors">
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-3">
                              {fileTypeIcon(d.file_type)}
                              <span className="font-medium text-gray-700">{d.filename}</span>
                            </div>
                          </td>
                          <td className="px-6 py-4 text-gray-400 uppercase text-xs font-medium">{d.file_type}</td>
                          <td className="px-6 py-4 text-gray-400">{(d.file_size / 1024).toFixed(1)} KB</td>
                          <td className="px-6 py-4 text-gray-400">{d.chunk_count}</td>
                          <td className="px-6 py-4">{statusBadge(d.status)}</td>
                          <td className="px-6 py-4 text-right">
                            <button
                              className="text-xs text-gray-400 hover:text-red-500 transition-colors px-2 py-1 rounded-lg hover:bg-red-50"
                              onClick={() => handleDelete(d.id)}
                            >
                              删除
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {/* 分页 */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-between px-6 py-3 border-t border-gray-50 bg-gray-50/30">
                    <span className="text-xs text-gray-400">共 {docs.length} 个文档，第 {safePage}/{totalPages} 页</span>
                    <div className="flex gap-1">
                      <button
                        disabled={safePage <= 1}
                        onClick={() => setPage(safePage - 1)}
                        className="px-3 py-1 text-xs rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed"
                      >
                        上一页
                      </button>
                      {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                        <button
                          key={p}
                          onClick={() => setPage(p)}
                          className={`px-3 py-1 text-xs rounded-lg border ${
                            p === safePage
                              ? 'bg-ocean-500 text-white border-ocean-500'
                              : 'border-gray-200 text-gray-500 hover:bg-gray-100'
                          }`}
                        >
                          {p}
                        </button>
                      ))}
                      <button
                        disabled={safePage >= totalPages}
                        onClick={() => setPage(safePage + 1)}
                        className="px-3 py-1 text-xs rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed"
                      >
                        下一页
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
