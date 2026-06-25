// ---- 用户 ----
export interface User {
  id: string
  username: string
  is_active: boolean
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: User
}

// ---- 会话 ----
export interface Session {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface ConversationMessage {
  id: string
  question: string
  answer: string
  sources: SourceInfo[]
  created_at: string
}

export interface SessionDetail {
  session: Session
  messages: ConversationMessage[]
}

// ---- 问答 ----
export interface SourceInfo {
  doc_name: string
  page: number
  score: number
  chunk_text: string
}

// ---- 文档 ----
export interface DocInfo {
  id: string
  filename: string
  file_size: number
  file_type: string
  chunk_count: number
  status: string
  created_at: string
}
