import MarkdownRenderer from './MarkdownRenderer'
import { useState } from 'react'

interface Props {
  role: 'user' | 'assistant'
  content: string
  loading?: boolean
  streaming?: boolean
}

export default function ChatBubble({ role, content, loading, streaming }: Props) {
  const isUser = role === 'user'
  const [showFull, setShowFull] = useState(false)

  const displayContent = content.length > 800 && !showFull && !isUser
    ? content.slice(0, 800) + '...'
    : content

  if (loading) {
    return (
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-ocean-400 to-ocean-600 flex items-center justify-center text-white text-xs font-medium shrink-0 shadow-sm">
          AI
        </div>
        <div className="bg-white border border-gray-100 rounded-2xl rounded-tl-md px-5 py-4 shadow-sm">
          <div className="flex gap-1.5 items-center h-5">
            <span className="w-2 h-2 rounded-full bg-ocean-300 animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-2 h-2 rounded-full bg-ocean-400 animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-2 h-2 rounded-full bg-ocean-500 animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div className={`w-9 h-9 rounded-xl flex items-center justify-center text-xs font-semibold shrink-0 shadow-sm ${
        isUser
          ? 'bg-ocean-100 text-ocean-600'
          : 'bg-gradient-to-br from-ocean-400 to-ocean-600 text-white'
      }`}>
        {isUser ? 'U' : 'AI'}
      </div>

      {/* Content */}
      <div className={`max-w-[75%] space-y-1 ${isUser ? 'items-end' : 'items-start'}`}>
        <div
          className={`rounded-2xl px-5 py-3.5 ${
            isUser
              ? 'bg-ocean-500 text-white rounded-tr-md shadow-sm shadow-ocean-200/50'
              : 'bg-white border border-gray-100 rounded-tl-md shadow-sm'
          }`}
        >
          {isUser ? (
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{displayContent}</p>
          ) : (
            <div className="text-sm leading-relaxed text-gray-700 prose-headings:text-gray-800 prose-a:text-ocean-600">
              <MarkdownRenderer content={displayContent} />
              {streaming && <span className="inline-block w-0.5 h-4 bg-ocean-500 ml-0.5 animate-blink" />}
            </div>
          )}
        </div>
        {content.length > 800 && !isUser && (
          <button
            className="text-xs text-gray-400 hover:text-ocean-500 transition-colors ml-1"
            onClick={() => setShowFull(!showFull)}
          >
            {showFull ? '收起' : '展开全文'}
          </button>
        )}
      </div>
    </div>
  )
}
