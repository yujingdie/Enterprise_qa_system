"""
Milvus 连接管理
"""

from pymilvus import connections
from app.core.config import config


def connect():
    """连接到 Milvus"""
    connections.connect(
        alias="default",
        host=config.env.milvus_host,
        port=config.env.milvus_port,
    )


def disconnect():
    """断开 Milvus 连接"""
    connections.disconnect("default")
