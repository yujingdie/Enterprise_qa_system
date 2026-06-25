import type { SourceInfo } from '../types'

interface Props {
  source: SourceInfo
}

export default function SourceCard({ source }: Props) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl px-3 py-2 text-xs max-w-[180px] hover:border-ocean-300 hover:shadow-sm transition-all">
      <div className="flex items-center gap-1.5 mb-1">
        <svg className="w-3.5 h-3.5 text-ocean-400 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
        </svg>
        <p className="font-medium text-gray-700 truncate">{source.doc_name}</p>
      </div>
      <p className="text-gray-400">第 {source.page} 页 · 相关度 {source.score.toFixed(2)}</p>
    </div>
  )
}
