"""pytest 配置文件"""

from pathlib import Path
import sys

# 把 backend 目录加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
