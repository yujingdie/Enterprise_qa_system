"""
OCR 模块 — Tesseract 封装

轻量级 OCR，替代 PaddleOCR。
- Tesseract 是纯 C++ OCR 引擎，1MB 二进制 + 语言包
- 无深度学习框架依赖（不装 pytorch/paddle 几百 MB）
- 中文识别精度略低于 PaddleOCR 但够用
- 会在首次调用时检查 tesseract 是否可用
"""

import io
import logging
import subprocess

from PIL import Image

logger = logging.getLogger(__name__)

_ocr_available = None


def check_tesseract() -> bool:
    """检查 tesseract 是否可用"""
    try:
        subprocess.run(
            ["tesseract", "--version"],
            capture_output=True,
            timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def ocr_image(img_bytes: bytes) -> str:
    """
    识别一张图片，返回文字。

    Args:
        img_bytes: 图片的原始字节（PNG/JPEG）

    Returns:
        识别出的文字
    """
    global _ocr_available
    if _ocr_available is None:
        _ocr_available = check_tesseract()

    if not _ocr_available:
        logger.warning("[OCR] Tesseract 不可用，跳过 OCR")
        return ""

    try:
        import pytesseract

        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        # lang='chi_sim+eng' 识别中文简体 + 英文
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        return text.strip()
    except Exception as e:
        logger.error(f"[OCR] Tesseract 识别失败: {e}")
        return ""


def ocr_pdf_pages(doc, dpi: int = 300) -> list[dict]:
    """
    对 PyMuPDF 文档中没有文字层的页面做 OCR。

    Args:
        doc: fitz.Document 对象
        dpi: 渲染分辨率，300 对扫描文档足够

    Returns:
        [{"page": 1, "text": "..."}, ...]
    """
    pages = []
    for i, page in enumerate(doc):
        # 先尝试提取文字层
        text = page.get_text("text").strip() if hasattr(page, 'get_text') else ''
        if text:
            pages.append({"page": i + 1, "text": text})
            continue

        # 无文字层 → 渲染为图片 → OCR
        logger.info(f"[OCR] 第 {i + 1} 页无文字层，执行 OCR...")
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("png")

        ocr_text = ocr_image(img_bytes)
        if ocr_text.strip():
            pages.append({"page": i + 1, "text": ocr_text.strip()})
        else:
            logger.warning(f"[OCR] 第 {i + 1} 页 OCR 结果为空")

    return pages
