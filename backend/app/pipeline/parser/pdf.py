"""
PDF 解析器
使用 PyMuPDF 提取文本，按页返回
扫描件（纯图片PDF）自动走 PaddleOCR
"""

import logging
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


def parse(file_path: str) -> list[dict]:
    """
    解析 PDF 文件，按页提取文本。
    文字型PDF直接提取，扫描件自动走 OCR。

    返回格式:
    [
        {"page": 1, "text": "第一页内容..."},
        {"page": 2, "text": "第二页内容..."},
    ]
    """
    doc = fitz.open(file_path)

    # 先尝试纯文字提取（快速路径）
    pages = []
    has_text = False
    for i, page in enumerate(doc):
        text = page.get_text("text").strip()
        if text:
            pages.append({"page": i + 1, "text": text})
            has_text = True

    # 如果有文字层，直接返回（跳过 OCR）
    if has_text:
        doc.close()
        return pages

    # 全文都是空的 → 可能是扫描件，尝试 OCR
    logger.info(f"[PDF] {file_path} 无文字层，尝试 OCR...")
    try:
        from app.pipeline.ocr import ocr_pdf_pages
        pages = ocr_pdf_pages(doc)
    except RuntimeError as e:
        # PaddleOCR 未安装，无法处理扫描件
        logger.warning(f"[PDF] OCR 不可用: {e}")
        doc.close()
        raise ValueError(
            "此PDF为扫描件（纯图片），需要 OCR 支持。"
            "请安装 PaddleOCR 后重试，或上传文字型PDF"
        )
    except Exception as e:
        logger.error(f"[PDF] OCR 失败: {e}")
        doc.close()
        raise ValueError(f"OCR 识别失败: {e}")

    doc.close()
    return pages
