"""
Word 解析器
- .docx: python-docx 提取段落
- .doc:  antiword 命令行工具提取文字（fallback: textract）
"""

import subprocess
import logging

logger = logging.getLogger(__name__)


def parse(file_path: str) -> str:
    """解析 Word 文档，返回完整文本"""
    if file_path.lower().endswith(".doc"):
        return _parse_doc(file_path)
    return _parse_docx(file_path)


def _parse_docx(file_path: str) -> str:
    """解析 .docx 文件"""
    from docx import Document as DocxDocument
    doc = DocxDocument(file_path)
    paragraphs = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _parse_doc(file_path: str) -> str:
    """解析 .doc 文件（antiword）"""
    try:
        result = subprocess.run(
            ["antiword", file_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        logger.warning("antiword failed (code=%d): %s", result.returncode, result.stderr[:200])
    except FileNotFoundError:
        logger.warning("antiword not installed, trying python-docx fallback")
    except Exception as e:
        logger.warning("antiword error: %s", e)

    # fallback: 尝试用 python-docx 打开（某些 .doc 文件实际是 .docx 格式）
    try:
        return _parse_docx(file_path)
    except Exception:
        pass

    raise ValueError("无法解析 .doc 文件，请安装 antiword (apt-get install antiword) 或将文件另存为 .docx 格式")
