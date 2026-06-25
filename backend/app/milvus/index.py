"""
Milvus Index 创建与参数配置

索引类型对比:
- HNSW:   图索引，召回率高，内存占用大，适合中小规模 (< 1000万)
- IVF_FLAT: 聚类 + 暴力搜索，内存小，适合大规模
- IVF_SQ8:  IVF + 量化压缩，内存更小，精度略降
"""

from pymilvus import Collection, IndexType, utility
from app.core.config import config

COLLECTION_NAME = config.pipeline["milvus"]["collection"]
METRIC_TYPE = config.pipeline["milvus"]["metric_type"]


def create_index(collection: Collection):
    """为 Collection 创建索引"""
    index_config = config.pipeline["milvus"]
    index_type = index_config["index_type"]

    # ---- Dense 向量索引 ----
    if index_type == "HNSW":
        hnsw_params = index_config["hnsw"]
        index_params = {
            "index_type": "HNSW",
            "metric_type": METRIC_TYPE,
            "params": {
                "M": hnsw_params["M"],
                "efConstruction": hnsw_params["ef_construction"],
            },
        }
    elif index_type == "IVF_FLAT":
        index_params = {
            "index_type": "IVF_FLAT",
            "metric_type": METRIC_TYPE,
            "params": {"nlist": 128},
        }
    elif index_type == "IVF_SQ8":
        index_params = {
            "index_type": "IVF_SQ8",
            "metric_type": METRIC_TYPE,
            "params": {"nlist": 128},
        }
    else:
        raise ValueError(f"不支持的索引类型: {index_type}")

    # 检查是否已有索引
    if not collection.has_index(index_name="dense_vector"):
        collection.create_index(
            field_name="dense_vector",
            index_params=index_params,
            index_name="dense_vector",
        )


def load_collection(collection: Collection):
    """加载 Collection 到内存（查询前必须调用）"""
    try:
        collection.load(timeout=30000)
        print(f"[STARTUP] Collection 已加载 ({collection.num_entities} 条数据)")
    except Exception as e:
        print(f"[STARTUP] load() 异常（跳过）: {e}")
