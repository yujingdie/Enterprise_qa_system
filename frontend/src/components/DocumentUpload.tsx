import { useRef, useState } from 'react'
import { docsApi } from '../api/documents'

interface Props {
  onUploaded: () => void
  onStartPolling: () => void
}

export default function DocumentUpload({ onUploaded, onStartPolling }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [messages, setMessages] = useState<{ name: string; ok: boolean }[]>([])

  const handleFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    setUploading(true)
    setMessages([])

    const results: { name: string; ok: boolean }[] = []
    for (const file of Array.from(files)) {
      try {
        await docsApi.upload(file)
        results.push({ name: file.name, ok: true })
      } catch {
        results.push({ name: file.name, ok: false })
      }
      setMessages([...results])
    }

    setUploading(false)
    onUploaded()
    onStartPolling()
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <div className="flex flex-wrap items-center gap-4">
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".pdf,.docx,.doc,.pptx,.ppt,.txt,.md"
        onChange={handleFiles}
        className="hidden"
        id="file-upload"
      />
      <label
        htmlFor="file-upload"
        className="btn-primary inline-flex items-center gap-2 cursor-pointer"
      >
        {uploading ? (
          <>上传中...</>
        ) : (
          <>
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v12m0 0l-4-4m4 4l4-4M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
            </svg>
            上传文档
          </>
        )}
      </label>
      {messages.length > 0 && (
        <div className="w-full flex flex-wrap gap-2">
          {messages.map((m, i) => (
            <span key={i} className={`text-sm ${m.ok ? 'text-green-600' : 'text-red-400'}`}>
              {m.ok ? '✓' : '✗'} {m.name}
            </span>
          ))}
        </div>
      )}
      <p className="w-full text-xs text-gray-300">支持 PDF / Word / PPT / TXT / Markdown（可多选）</p>
    </div>
  )
}
