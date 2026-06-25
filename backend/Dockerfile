FROM python:3.11-slim

WORKDIR /app

# 使用国内镜像源安装系统依赖
# libgl1/libglib2.0-0 供 OpenCV 使用
# tesseract-ocr 用于扫描件 PDF OCR
RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null; \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libc6-dev \
    libpq-dev \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    tesseract-ocr-chi-tra \
    antiword \
    && rm -rf /var/lib/apt/lists/*

# 清华 PyPI 镜像
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple/

# ===== Step 1: 基础依赖 =====
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip --retries 5 --timeout 120 --break-system-packages && \
    pip install --no-cache-dir --retries 5 --timeout 120 \
        -r requirements.txt --break-system-packages && \
    pip install --no-cache-dir --force-reinstall --retries 5 --timeout 120 \
        "bcrypt==4.0.1" --break-system-packages

# ===== Step 2: Tesseract OCR Python 绑定 =====
RUN pip install --no-cache-dir --retries 5 --timeout 120 --break-system-packages \
        pytesseract

# ===== Step 3: 预下载 Reranker 模型（通过 curl 跳过 SSL 验证） =====
RUN mkdir -p /app/reranker_model && \
    cd /app/reranker_model && \
    curl -k -L -o config.json "https://hf-mirror.com/BAAI/bge-reranker-v2-m3/resolve/main/config.json" && \
    curl -k -L -o tokenizer_config.json "https://hf-mirror.com/BAAI/bge-reranker-v2-m3/resolve/main/tokenizer_config.json" && \
    curl -k -L -o tokenizer.json "https://hf-mirror.com/BAAI/bge-reranker-v2-m3/resolve/main/tokenizer.json" && \
    curl -k -L -o vocab.txt "https://hf-mirror.com/BAAI/bge-reranker-v2-m3/resolve/main/vocab.txt" && \
    curl -k -L -o special_tokens_map.json "https://hf-mirror.com/BAAI/bge-reranker-v2-m3/resolve/main/special_tokens_map.json" && \
    curl -k -L -o model.safetensors "https://hf-mirror.com/BAAI/bge-reranker-v2-m3/resolve/main/model.safetensors" && \
    echo "Reranker model downloaded OK"

# 复制代码
COPY . .

# 创建上传目录
RUN mkdir -p uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
