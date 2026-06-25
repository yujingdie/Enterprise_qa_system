"""
纯文本 / Markdown 解析器
"""


def parse(file_path: str) -> str:
    """读取文本文件内容"""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()
