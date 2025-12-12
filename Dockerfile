FROM python:3.11-slim

# 環境変数設定
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Playwright Chromium用の全依存関係をインストール
# playwright install-depsを使わず手動でインストール（Debian Trixieでのパッケージ名問題を回避）
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    # フォント（正しいパッケージ名を使用）
    fonts-noto-cjk \
    fonts-liberation \
    fonts-unifont \
    fonts-ubuntu \
    fonts-freefont-ttf \
    # Chromium依存ライブラリ
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libxshmfence1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 作業ディレクトリ
WORKDIR /app

# 依存関係をインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwrightのブラウザをインストール（Chromiumのみ）
# install-depsは使わない（依存関係は上で手動インストール済み）
RUN playwright install chromium

# バージョン確認
RUN python -c "from playwright.sync_api import sync_playwright; print('Playwright installed successfully')"

# アプリケーションコードをコピー
COPY app/ ./app/

# ポート設定
EXPOSE 8080

# アプリケーション起動
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
