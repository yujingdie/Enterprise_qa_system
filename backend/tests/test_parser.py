"""解析器测试"""

from app.pipeline.parser import text as text_parser


def test_text_parser(tmp_path):
    """纯文本解析器测试"""
    file = tmp_path / "test.md"
    file.write_text("# 标题\n\n这是测试内容。", encoding="utf-8")
    result = text_parser.parse(str(file))
    assert "标题" in result
    assert "测试内容" in result
