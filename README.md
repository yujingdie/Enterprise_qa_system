# 企业知识问答系统

基于 **Milvus + RAG** 的企业内部知识检索与问答系统。上传文档 → 向量化入库 → 智能检索 → LLM 生成答案，支持多轮对话与来源引用。

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110-green?logo=fastapi)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react)
![Milvus](https://img.shields.io/badge/Milvus-2.4-00A1E0)
![Docker](https://img.shields.io/badge/Docker-Compose-blue?logo=docker)

## 功能特性

- 📄 **多格式文档解析** — 支持 PDF、Word、PPT、Markdown、TXT、扫描件自动 OCR
- 🧠 **语义切分** — 基于段落边界的智能切分，保留文档结构
- 🔍 **Query Rewrite + 确定性检索** — LLM 先判断问题复杂度，决定是否改写查询词，再用确定 query 去检索
- 🎯 **Reranker 精排** — BGE-reranker-v2-m3 cross-encoder 二次排序
- 💬 **多会话管理** — 创建/切换/删除对话，历史记录持久化
- 📡 **SSE 流式输出** — 实时流式返回答案，前端实时展示搜索状态
- 📊 **检索评估体系** — Recall@k、MRR 指标，支持对比实验

## 技术栈

| 层级 | 技术选型 |
|------|---------|
| LLM | MiMo 2.5 Pro（Anthropic 兼容 API） |
| Embedding | 千问百炼 text-embedding-v4（1024 维） |
| 向量库 | Milvus Standalone（HNSW 索引） |
| 业务库 | PostgreSQL 16（JSONB 存储来源信息） |
| 后端 | Python FastAPI + SQLAlchemy |
| 前端 | React 18 + Vite + TypeScript + Tailwind CSS |
| 部署 | Docker Compose（6 个容器） |

## 快速开始

### 环境要求

- Docker & Docker Compose
- LLM 模型 API Key（用于答案生成和查询改写）
- Embedding 模型 API Key（用于文本向量化）

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
│   │   │   ├── qa.py            # 问答接口（Query Rewrite + 检索 + SSE 流式输出）
│   │   │   ├── auth.py          # 注册/登录/JWT
│   │   │   ├── documents.py     # 文档上传/删除/列表
│   │   │   ├── sessions.py      # 会话 CRUD
│   │   │   ├── history.py       # 历史记录查询
│   │   │   └── deps.py          # 依赖注入（JWT 认证、数据库连接）
│   │   ├── pipeline/
│   │   │   ├── ingest.py        # 入库管线（解析→切分→Embedding→Milvus）
│   │   │   ├── chunker.py       # 语义切分
│   │   │   ├── reranker.py      # BGE-reranker 精排
│   │   │   ├── query.py         # 查询管线（非 Agent 路径，含 query_rewrite）
│   │   │   ├── ocr.py           # 扫描件 OCR（Tesseract/PaddleOCR）
│   │   │   └── parser/          # 文档解析（PDF/Word/PPT/Text）
│   │   ├── models/              # SQLAlchemy 数据模型
│   │   │   ├── user.py          # 用户表
│   │   │   ├── session.py       # 会话表
│   │   │   ├── conversation.py  # 对话记录表
│   │   │   └── document.py      # 文档元数据表
│   │   ├── schemas/             # Pydantic 请求/响应模型
│   │   ├── core/
│   │   │   ├── config.py        # 配置加载（.env + YAML）
│   │   │   ├── database.py      # SQLAlchemy 引擎
│   │   │   └── security.py      # 密码哈希 + JWT
│   │   ├── milvus/              # 向量库操作（client/schema/index/searcher/writer）
│   │   ├── llm/client.py        # LLM 调用（Anthropic SDK）
│   │   └── embed/client.py      # Embedding（千问 API / 本地 BGE）
│   ├── config/
│   │   ├── pipeline.yml         # 切分/检索/Milvus 参数配置
│   │   └── prompts.yml          # 提示词模板
│   ├── scripts/
│   │   └── reingest.py          # 重新入库脚本
│   ├── eval/                    # 检索质量评估（Recall@k, MRR）
│   │   └── run_eval.py
│   ├── tests/                   # 单元测试
│   │   ├── test_chunker.py
│   │   ├── test_embedder.py
│   │   ├── test_milvus_searcher.py
│   │   └── test_parser.py
│   ├── uploads/                 # 上传文件存储（运行时数据，不入 Git）
│   ├── Dockerfile
│   ├── .dockerignore
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
├── docker-compose.yml           # 6 个容器编排（postgres/etcd/minio/milvus/backend/frontend）
└── .gitignore
```

## 架构设计

### 查询流程（Query Rewrite + 确定性检索）

```
用户提问
  ↓
Step 1: Query 改写判断（LLM，不带工具）
  ├─ 问题具体、明确 → 不改写，只用原始完整问题
  └─ 问题模糊、宽泛 → 改写为 3 条 query（原始 + 2 条改写）
  ↓
Step 2: 确定性检索（每条 query 独立搜索）
  每条 query → Embedding → Milvus HNSW 粗排 Top 20
    → 粗筛（COSINE ≥0.3）→ Reranker 精排 Top 5 → 精筛（sigmoid ≥0.5）
  ↓
Step 3: 合并去重（按 doc+页码）→ 分数排序取 Top 5
  ↓
Step 4: LLM 基于检索结果生成答案（SSE 流式输出）
  ↓
前端展示答案 + 真实来源卡片
（如果 LLM 回答"未找到相关资料"，则不展示来源卡片）
```

### 入库流程

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

### SSE 事件流

```
event: tool_call     → "正在分析问题"
event: tool_call     → "正在搜索 (1/N)"（每调一次搜索发一次）
event: answer        → 流式 LLM 输出文本（逐 chunk）
event: sources       → 参考来源卡片（JSON）
event: done          → 完成，包含 session_id
```

### 核心配置

| 配置项 | 默认值 | 说明 |
|-------|-------|------|
| 切分策略 | semantic | 语义切分（可选 fixed/recursive） |
| 切分大小 | 512 字 | 每个 chunk 的目标字符数 |
| Embedding | text-embedding-v4 | 千问百炼 API |
| 索引类型 | HNSW | M=16, ef_construction=256 |
| 粗排 Top K | 20 | Milvus 返回的候选数 |
| 精排 Top K | 5 | Reranker 后的最终结果数 |
| 粗排阈值 | 0.3 | Milvus COSINE 分数门槛 |
| 精排阈值 | 0.5 | Reranker sigmoid 归一化后分数门槛 |

## 评估体系

```bash
# 默认评估（本地运行，需 Milvus 已启动）
cd backend
python -m eval.run_eval

# 对比实验
python -m eval.run_eval --experiment rerank    # Rerank 开关
python -m eval.run_eval --experiment search    # Dense vs Hybrid
python -m eval.run_eval --experiment chunk     # 切分策略对比
python -m eval.run_eval --experiment all       # 全部实验
```

评估指标：Recall@1、Recall@3、Recall@5、MRR

## 测试

```bash
cd backend
# 运行全部测试
pytest tests/ -v

# 单个测试
pytest tests/test_chunker.py -v
pytest tests/test_parser.py::test_parse_txt -v
```

## 配置说明

### 切换 Embedding 模型

编辑 `backend/.env`：

```bash
# 使用千问 API（推荐）
EMBEDDING_PROVIDER=qianwen
EMBEDDING_MODEL=text-embedding-v4

# 使用本地 BGE 模型（需安装 sentence-transformers）
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
```

### 关闭 Reranker

编辑 `backend/config/pipeline.yml`：

```yaml
reranker:
  enabled: false    # 关闭后跳过精排，响应更快
```


### 调整 Query Rewrite 策略

编辑 `backend/config/prompts.yml`，修改 `query_rewrite` 部分的判断标准和示例，即可控制哪些问题触发改写。

## 效果图:

<img width="1910" height="915" alt="e52645d6e37d25a4fca7084500ba8598" src="https://github.com/user-attachments/assets/628bac95-40e0-475b-9e66-a2ca0c4a1d3b" />

<img width="1910" height="915" alt="011601c098b70440eaa4eb5cb1114ae8" src="https://github.com/user-attachments/assets/a182deca-524e-4910-afc8-a3dfa543facc" />

<img width="1910" height="915" alt="8ca12ee70cfdf18ddb6da5c111e7d16e" src="https://github.com/user-attachments/assets/49961ee3-d8ee-450d-9e0e-79941ce7ee88" />

<img width="1910" height="915" alt="b6b8df32e2414cc34bdbaef6d3db2586" src="https://github.com/user-attachments/assets/a8326dc0-8aed-425d-864e-4564457c6a47" />

<img width="1910" height="915" alt="b954a52537c658e9d43e0885c0865162" src="https://github.com/user-attachments/assets/80d402c7-55b2-4bb2-8516-eb4413a0910d" />



