"""
FastAPI 入口
企业知识问答系统
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import config
from app.core.database import init_db
from app.milvus.client import connect as milvus_connect, disconnect as milvus_disconnect
from app.milvus.schema import create_collection
from app.milvus.index import create_index, load_collection
from app.api import auth, qa, documents, history, sessions

# 配置日志：让 app 层的 logger 输出到控制台
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时连接 Milvus + 创建表，关闭时断开"""
    # 启动时
    print("[STARTUP] 正在连接 Milvus...")
    milvus_connect()

    print("[STARTUP] 正在初始化 PostgreSQL 表...")
    init_db()

    print("[STARTUP] 正在初始化 Milvus Collection...")
    collection = create_collection()
    create_index(collection)
    load_collection(collection)

    print("[STARTUP] 企业知识问答系统已启动")
    yield

    # 关闭时
    print("[SHUTDOWN] 正在断开 Milvus 连接...")
    milvus_disconnect()


app = FastAPI(
    title="企业知识问答系统",
    description="基于 Milvus + RAG 的企业内部知识检索与问答平台",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置（开发环境允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router)
app.include_router(qa.router)
app.include_router(documents.router)
app.include_router(history.router)
app.include_router(sessions.router)


@app.get("/")
def root():
    return {
        "name": "企业知识问答系统",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}
