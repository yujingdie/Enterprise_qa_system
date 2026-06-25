"""
检索质量评估工具

运行方式:
  cd backend

  # 默认评估
  python -m eval.run_eval

  # 单项对比实验
  python -m eval.run_eval --experiment rerank
  python -m eval.run_eval --experiment search
  python -m eval.run_eval --experiment chunk
  python -m eval.run_eval --experiment embedding

  # 全部实验
  python -m eval.run_eval --experiment all

评估指标:
  - Recall@k:  前 k 条结果中命中正确文档的比例
  - MRR:       正确答案排名的倒数均值
"""

import json
import os
import asyncio
import argparse
import time
import copy
from pathlib import Path
from datetime import datetime
from app.core.config import config
from app.pipeline.query import run_retrieval, run_query
from app.milvus.schema import create_collection
from app.milvus.index import create_index, load_collection
from app.milvus.client import connect as milvus_connect, disconnect as milvus_disconnect

HERE = Path(__file__).resolve().parent
DATASET_PATH = HERE / "test_dataset.json"
REPORTS_DIR = HERE / "reports"


def load_dataset(path: Path = None) -> list[dict]:
    p = path or DATASET_PATH
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_search(question: str, results: list[dict], expected_docs: list[str]) -> dict:
    """评估单条检索结果"""
    hit_docs = []
    seen = set()
    for r in results:
        doc_name = r.get("doc_name", "")
        if doc_name not in seen:
            hit_docs.append(doc_name)
            seen.add(doc_name)

    hit_rank = None
    for i, doc in enumerate(hit_docs):
        if doc in expected_docs:
            hit_rank = i + 1
            break

    mrr_score = 1.0 / hit_rank if hit_rank else 0.0
    return {
        "recall_1": hit_rank is not None and hit_rank <= 1,
        "recall_3": hit_rank is not None and hit_rank <= 3,
        "recall_5": hit_rank is not None and hit_rank <= 5,
        "mrr_score": mrr_score,
        "hit_rank": hit_rank,
    }


def _ensure_milvus():
    milvus_connect()
    collection = create_collection()
    create_index(collection)
    load_collection(collection)


async def run_evaluation(exp_name: str = "default", dataset_path: Path = None) -> dict:
    """运行评估并保存报告"""
    _ensure_milvus()

    dataset = load_dataset(dataset_path)
    results = []
    total_start = time.time()

    for item in dataset:
        q_start = time.time()
        query_result = await run_query(item["question"])
        q_time = time.time() - q_start

        eval_result = evaluate_search(
            item["question"],
            query_result.get("sources", []),
            item.get("expected_docs", []),
        )
        results.append({
            "question": item["question"],
            "difficulty": item.get("difficulty"),
            "type": item.get("type"),
            "time_seconds": q_time,
            "evaluation": eval_result,
        })

    total_time = time.time() - total_start
    summary = _calculate_summary(results)

    report = {
        "experiment": exp_name,
        "timestamp": datetime.now().isoformat(),
        "config": {
            "chunk_strategy": config.pipeline["chunk"]["strategy"],
            "chunk_size": config.pipeline["chunk"]["size"],
            "embedding_provider": config.env.embedding_provider,
            "embedding_model": config.env.embedding_model,
            "index_type": config.pipeline["milvus"]["index_type"],
            "retrieval_top_k": config.pipeline["retrieval"]["top_k"],
            "rerank_enabled": config.pipeline["reranker"]["enabled"],
        },
        "summary": summary,
        "details": results,
    }

    os.makedirs(REPORTS_DIR, exist_ok=True)
    report_path = REPORTS_DIR / f"{exp_name}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    milvus_disconnect()
    return report


def _calculate_summary(results: list[dict]) -> dict:
    valid = [r for r in results if r.get("evaluation") is not None]
    n = len(valid)
    if n == 0:
        return {"total_questions": 0, "error": "无有效评估结果"}

    recall_1 = sum(1 for r in valid if r["evaluation"]["recall_1"]) / n
    recall_3 = sum(1 for r in valid if r["evaluation"]["recall_3"]) / n
    recall_5 = sum(1 for r in valid if r["evaluation"]["recall_5"]) / n
    mrr = sum(r["evaluation"]["mrr_score"] for r in valid) / n

    by_difficulty = {}
    for diff in ["easy", "medium", "hard"]:
        group = [r for r in valid if r.get("difficulty") == diff]
        if group:
            by_difficulty[diff] = {
                "count": len(group),
                "recall_5": sum(1 for g in group if g["evaluation"]["recall_5"]) / len(group),
                "mrr": sum(g["evaluation"]["mrr_score"] for g in group) / len(group),
            }

    avg_time = sum(r.get("time_seconds", 0) for r in valid) / n
    return {
        "total_questions": n,
        "recall@1": round(recall_1, 4),
        "recall@3": round(recall_3, 4),
        "recall@5": round(recall_5, 4),
        "mrr": round(mrr, 4),
        "avg_time_seconds": round(avg_time, 2),
        "by_difficulty": by_difficulty,
    }


# ===== 对比实验 =====

async def experiment_rerank(dataset_path: Path = None):
    """实验: Rerank 开 vs 关"""
    print("\n" + "=" * 50)
    print("实验: Rerank 开关对比")
    print("=" * 50)

    original = config.pipeline["reranker"]["enabled"]
    reports = []

    for enabled in [False, True]:
        config.pipeline["reranker"]["enabled"] = enabled
        name = "rerank_on" if enabled else "rerank_off"
        print(f"\n  运行: {name} ...")
        report = await run_evaluation(name, dataset_path=dataset_path)
        reports.append(report)
        print(f"  {name}: Recall@5={report['summary']['recall@5']}, MRR={report['summary']['mrr']}")

    config.pipeline["reranker"]["enabled"] = original
    _print_comparison("Rerank", reports)
    return reports


async def experiment_search(dataset_path: Path = None):
    """实验: Dense vs Hybrid 检索"""
    print("\n" + "=" * 50)
    print("实验: Dense vs Hybrid 检索")
    print("=" * 50)

    from app.milvus.searcher import search_dense, search_hybrid
    from app.pipeline.query import run_retrieval as _orig_retrieval

    original_retrieval = __import__("app.pipeline.query", fromlist=["run_retrieval"]).run_retrieval

    reports = []

    # Dense (默认)
    print("\n  运行: dense ...")
    report = await run_evaluation("search_dense", dataset_path=dataset_path)
    reports.append(report)
    print(f"  dense: Recall@5={report['summary']['recall@5']}, MRR={report['summary']['mrr']}")

    # Hybrid — monkey-patch run_retrieval 使用 search_hybrid
    async def _hybrid_retrieval(question: str) -> dict:
        """临时替换: 使用 hybrid 检索"""
        from app.pipeline.query import _parse_rewrite_result
        from app.embed.client import embed as do_embed
        from app.milvus.schema import get_collection
        import time as _t

        t0 = _t.time()
        rewriter_prompt = config.prompts["query_rewrite"]["system"]
        rewrite_queries = [question]
        try:
            from app.llm.client import chat as llm_chat
            rewrite_result = await llm_chat(
                system_prompt=rewriter_prompt,
                user_message=f"用户原始问题：{question}",
                temperature=0.3,
            )
            parsed = _parse_rewrite_result(rewrite_result)
            if parsed["need_rewrite"]:
                rewrite_queries = parsed["queries"]
                if question not in rewrite_queries:
                    rewrite_queries.insert(0, question)
        except Exception:
            pass

        t1 = _t.time()
        all_candidates = {}
        collection = get_collection()
        top_k = config.pipeline["retrieval"]["top_k"]

        for query in rewrite_queries:
            try:
                query_vector = await do_embed([query])
            except Exception:
                continue
            try:
                results = search_hybrid(collection, query_vector[0], top_k=top_k)
            except Exception:
                results = search_dense(collection, query_vector[0], top_k=top_k)
            for r in results:
                if r["id"] not in all_candidates or r["score"] > all_candidates[r["id"]]["score"]:
                    all_candidates[r["id"]] = r

        candidates = sorted(
            all_candidates.values(), key=lambda x: x["score"], reverse=True
        )[:top_k]

        if config.pipeline["reranker"]["enabled"] and len(candidates) > 1:
            from app.pipeline.reranker import rerank
            try:
                candidates = rerank(question, candidates, top_k=config.pipeline["retrieval"]["rerank_top_k"])
            except Exception:
                candidates = candidates[:config.pipeline["retrieval"]["rerank_top_k"]]

        threshold = config.pipeline["retrieval"]["score_threshold"]
        candidates = [c for c in candidates if c["score"] >= threshold]

        sources = [
            {"doc_name": c["source"], "page": c["page"], "score": round(c["score"], 4), "chunk_text": c["chunk_text"][:300]}
            for c in candidates
        ]
        context_parts = [
            f"[资料{i+1}] 来源：{c['source']} 第{c['page']}页\n{c['chunk_text']}"
            for i, c in enumerate(candidates)
        ]

        return {
            "candidates": candidates,
            "sources": sources,
            "context": "\n\n".join(context_parts),
            "rewrite_queries": rewrite_queries,
        }

    import app.pipeline.query as query_mod
    query_mod.run_retrieval = _hybrid_retrieval
    print("\n  运行: hybrid ...")
    report = await run_evaluation("search_hybrid", dataset_path=dataset_path)
    reports.append(report)
    query_mod.run_retrieval = original_retrieval
    print(f"  hybrid: Recall@5={report['summary']['recall@5']}, MRR={report['summary']['mrr']}")

    _print_comparison("Search Method", reports)
    return reports


async def experiment_chunk(dataset_path: Path = None):
    """实验: 对比不同切分策略

    注意: 切分策略变更需要重新入库才能生效。
    脚本会临时修改配置并运行评估，但结果依赖于已入库的数据。
    若要准确对比，需先用不同策略分别入库到不同 collection。
    """
    print("\n" + "=" * 50)
    print("实验: 切分策略对比")
    print("=" * 50)

    original_strategy = config.pipeline["chunk"]["strategy"]
    original_size = config.pipeline["chunk"]["size"]
    reports = []

    configs = [
        ("recursive_512", "recursive", 512),
        ("recursive_256", "recursive", 256),
        ("recursive_1024", "recursive", 1024),
    ]

    for name, strategy, size in configs:
        config.pipeline["chunk"]["strategy"] = strategy
        config.pipeline["chunk"]["size"] = size
        print(f"\n  运行: {name} (strategy={strategy}, size={size}) ...")
        print(f"  ⚠ 如需准确对比，请先用此配置重新入库")
        report = await run_evaluation(f"chunk_{name}", dataset_path=dataset_path)
        reports.append(report)
        print(f"  {name}: Recall@5={report['summary']['recall@5']}, MRR={report['summary']['mrr']}")

    config.pipeline["chunk"]["strategy"] = original_strategy
    config.pipeline["chunk"]["size"] = original_size
    _print_comparison("Chunk Strategy", reports)
    return reports


async def experiment_embedding(dataset_path: Path = None):
    """实验: 对比不同 Embedding 模型

    注意: Embedding 模型变更需要重新向量化所有文档。
    脚本会临时修改配置，但结果依赖于已入库的向量。
    若切换模型，需先重新入库。
    """
    print("\n" + "=" * 50)
    print("实验: Embedding 模型对比")
    print("=" * 50)

    original_provider = config.env.embedding_provider
    original_model = config.env.embedding_model
    reports = []

    # 当前配置
    name = f"{original_provider}_{original_model}"
    print(f"\n  运行: {name} (当前配置) ...")
    report = await run_evaluation(f"embed_{name}", dataset_path=dataset_path)
    reports.append(report)
    print(f"  {name}: Recall@5={report['summary']['recall@5']}, MRR={report['summary']['mrr']}")

    _print_comparison("Embedding Model", reports)
    print("\n  提示: 要对比其他模型，需在 .env 中切换 EMBEDDING_PROVIDER/EMBEDDING_MODEL 后重新入库")
    return reports


def _print_comparison(title: str, reports: list[dict]):
    print(f"\n{'─' * 50}")
    print(f"  {title} 对比结果:")
    print(f"{'─' * 50}")
    print(f"  {'配置':<20} {'Recall@5':>10} {'MRR':>10} {'耗时':>10}")
    print(f"  {'─'*20} {'─'*10} {'─'*10} {'─'*10}")
    for r in reports:
        s = r["summary"]
        print(f"  {r['experiment']:<20} {s.get('recall@5', 0):>10.4f} {s.get('mrr', 0):>10.4f} {s.get('avg_time_seconds', 0):>9.2f}s")

    if len(reports) >= 2:
        best = max(reports, key=lambda r: r["summary"].get("mrr", 0))
        print(f"\n  最优: {best['experiment']} (MRR={best['summary']['mrr']:.4f})")


EXPERIMENTS = {
    "rerank": experiment_rerank,
    "search": experiment_search,
    "chunk": experiment_chunk,
    "embedding": experiment_embedding,
}


async def run_all_experiments(dataset_path: Path = None):
    for name, fn in EXPERIMENTS.items():
        await fn(dataset_path=dataset_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="检索质量评估工具")
    parser.add_argument(
        "--experiment", "-e",
        choices=list(EXPERIMENTS.keys()) + ["all", "default"],
        default="default",
        help="运行的实验: default(仅评估) / rerank / search / chunk / embedding / all",
    )
    parser.add_argument(
        "--dataset", "-d",
        default=None,
        help="自定义测试集路径，默认 test_dataset.json",
    )
    args = parser.parse_args()

    # 加载指定测试集
    dataset_path = Path(args.dataset) if args.dataset else DATASET_PATH
    if not dataset_path.exists():
        print(f"错误: 测试集文件不存在: {dataset_path}")
        exit(1)

    print("=" * 60)
    print("检索质量评估工具")
    print(f"测试集: {dataset_path.name}")
    print("=" * 60)

    if args.experiment == "default":
        report = asyncio.run(run_evaluation("default", dataset_path=dataset_path))
        s = report["summary"]
        print(f"\n评估完成! 共 {s['total_questions']} 条问题")
        print(f"Recall@1:  {s['recall@1']}")
        print(f"Recall@3:  {s['recall@3']}")
        print(f"Recall@5:  {s['recall@5']}")
        print(f"MRR:       {s['mrr']}")
    elif args.experiment == "all":
        asyncio.run(run_all_experiments(dataset_path=dataset_path))
    else:
        asyncio.run(EXPERIMENTS[args.experiment](dataset_path=dataset_path))
