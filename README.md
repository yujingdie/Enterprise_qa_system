# 企业知识问答系统

基于 **Milvus + RAG + Agent** 的企业内部知识检索与问答系统。上传文档 → 向量化入库 → 智能检索 → LLM 生成答案，支持多轮对话与来源引用。

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110-green?logo=fastapi)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react)
![Milvus](https://img.shields.io/badge/Milvus-2.4-00A1E0)
![Docker](https://img.shields.io/badge/Docker-Compose-blue?logo=docker)

## 功能特性

- 📄 **多格式文档解析** — 支持 PDF、Word、PPT、Markdown、TXT、扫描件自动 OCR
- 🧠 **语义切分** — 基于段落边界的智能切分，保留文档结构
- 🤖 **Agent 智能问答** — LLM 自主判断问题复杂度，决定是否改写查询词，自行调用检索工具
- 🎯 **Reranker 精排** — BGE-reranker-v2-m3 cross-encoder 二次排序
- 💬 **多会话管理** — 创建/切换/删除对话，历史记录持久化
- 📡 **SSE 流式输出** — 实时流式返回答案，前端实时展示搜索状态

## 技术栈

| 层级 | 技术选型 |
|------|---------|
| LLM | DeepSeek（LangChain + OpenAI 兼容接口） |
| LLM 框架 | LangChain 0.3 |
| Embedding | 千问百炼 text-embedding-v4（1024 维） |
| 向量库 | Milvus Standalone（HNSW 索引） |
| 业务库 | PostgreSQL 16 |
| 后端 | Python FastAPI + SQLAlchemy |
| 前端 | React 18 + Vite + TypeScript + Tailwind CSS |
| 部署 | Docker Compose（6 个容器） |

## 快速开始

### 环境要求

- Docker & Docker Compose
- LLM API Key（用于答案生成和查询改写）
- Embedding API Key（用于文本向量化）

### 启动

```bash
# 1. 克隆项目
git clone <your-repo-url>
cd Enterprise_qa_system

# 2. 配置环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入你的 API Key

# 3. 启动所有服务
docker-compose up -d

# 4. 访问
# 前端: http://localhost:3000
# 后端 API 文档: http://localhost:8000/docs
```

### 默认账户

首次访问需注册账号，注册后登录。

## 项目结构

```
Enterprise_qa_system/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口，lifespan 初始化
│   │   ├── api/
│   │   │   ├── qa.py            # 问答接口（Agent Loop + SSE 流式输出）
│   │   │   ├── auth.py          # 注册/登录/JWT
│   │   │   ├── documents.py     # 文档上传/删除/列表
│   │   │   ├── sessions.py      # 会话 CRUD
│   │   │   ├── history.py       # 历史记录查询
│   │   │   └── deps.py          # 依赖注入（JWT 认证、数据库连接）
│   │   ├── pipeline/
│   │   │   ├── ingest.py        # 入库管线（解析→切分→Embedding→Milvus）
│   │   │   ├── chunker.py       # 语义切分
│   │   │   ├── reranker.py      # BGE-reranker 精排
│   │   │   ├── ocr.py           # 扫描件 OCR
│   │   │   └── parser/          # 文档解析（PDF/Word/PPT/Text）
│   │   ├── models/              # SQLAlchemy 数据模型
│   │   ├── schemas/             # Pydantic 请求/响应模型
│   │   ├── core/
│   │   │   ├── config.py        # 配置加载（.env + YAML）
│   │   │   ├── database.py      # SQLAlchemy 引擎
│   │   │   └── security.py      # 密码哈希 + JWT
│   │   ├── milvus/              # 向量库操作（client/schema/index/searcher/writer）
│   │   ├── llm/client.py        # LLM 调用（LangChain ChatOpenAI）
│   │   └── embed/client.py      # Embedding（千问 API / 本地 BGE）
│   ├── config/
│   │   ├── pipeline.yml         # 切分/检索/Milvus 参数配置
│   │   └── prompts.yml          # 提示词模板
│   ├── eval/                    # 检索质量评估
│   │   └── run_eval.py
│   ├── tests/                   # 单元测试
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example             # 环境变量模板
├── frontend/
│   ├── src/
│   │   ├── pages/               # 页面组件（Chat/Documents/Login/Register）
│   │   ├── components/          # UI 组件
│   │   ├── api/                 # API 客户端 + SSE 流式处理
│   │   └── types/               # TypeScript 类型定义
│   ├── Dockerfile
│   └── nginx.conf               # 反向代理配置
├── docker-compose.yml           # 6 个容器编排
└── .gitignore
```

## 查询流程

```
用户提问
  ↓
Phase 1 — Agent 工具决策（LangChain chat_with_tools）
  LLM 自主判断问题是否模糊：
  ├─ 模糊 → 拆成 3 个 query 一次性调 search_knowledge_base
  └─ 明确 → 调 1 次即可
  每条 query → Embedding → Milvus HNSW 粗排 Top 20
    → 粗筛（COSINE ≥0.3）→ Reranker 精排 Top 5 → 精筛（sigmoid ≥0.5）
  看到所有结果后，LLM 再决定是否还需更多搜索
  ↓
Phase 2 — 流式输出答案
  所有检索结果拼入上下文，逐 chunk 流式输出
  ↓
前端展示答案 + 来源卡片
```

## 入库流程

```
上传文档
  ↓
解析（PDF/Word/PPT/Text，扫描件自动 OCR）
  ↓
语义切分（按段落边界，目标 512 字）
  ↓
Embedding（千问 text-embedding-v4，1024 维）
  ↓
批量写入 Milvus（HNSW 索引，COSINE 相似度）
  ↓
更新 PostgreSQL 文档状态
```

## 配置说明

编辑 `backend/.env`：

```bash
# LLM
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-v4-flash

# Embedding（千问 API）
EMBEDDING_PROVIDER=qianwen
EMBEDDING_MODEL=text-embedding-v4
QIANWEN_API_KEY=your-key-here
```

## 效果图

<img width="1910" height="915" alt="chat" src="https://github.com/user-attachments/assets/628bac95-40e0-475b-9e66-a2ca0c4a1d3b" />
<img width="1910" height="915" alt="chat" src="https://github.com/user-attachments/assets/a182deca-524e-4910-afc8-a3dfa543facc" />
<img width="1910" height="915" alt="chat" src="https://github.com/user-attachments/assets/49961ee3-d8ee-450d-9e0e-79941ce7ee88" />
<img width="1910" height="915" alt="chat" src="https://github.com/user-attachments/assets/a8326dc0-8aed-425d-864e-4564457c6a47" />

## 协议

MIT
