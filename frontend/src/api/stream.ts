import type { SourceInfo } from '../types'

interface SSEHandlers {
  onSources: (sources: SourceInfo[]) => void
  onAnswer: (chunk: string) => void
  onDone: (data: { session_id: string }) => void
  onToolCall: (data: { name: string; args: Record<string, unknown>; result: string }) => void
  onAbort: () => void
  onError: (err: Error) => void
}

export async function fetchSSE(
  question: string,
  sessionId: string | null,
  token: string,
  handlers: SSEHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const body: Record<string, string> = { question }
  if (sessionId) body.session_id = sessionId

  try {
    const res = await fetch('/api/qa/ask', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
      signal,
    })

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`)
    }

    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()! // 保留不完整的最后一行

      let eventType = ''
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          const rawData = line.slice(6)
          try {
            const parsed = JSON.parse(rawData)
            switch (eventType) {
              case 'sources':
                handlers.onSources(parsed)
                break
              case 'answer':
                handlers.onAnswer(parsed)
                break
              case 'done':
                handlers.onDone(parsed)
                break
              case 'tool_call':
                handlers.onToolCall(parsed)
                break
            }
          } catch {
            // data 不是 JSON，直接作为 answer 文本
            if (eventType === 'answer') {
              handlers.onAnswer(rawData)
            }
          }
          eventType = ''
        }
      }
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      handlers.onAbort()
      return
    }
    handlers.onError(err instanceof Error ? err : new Error(String(err)))
  }
}
