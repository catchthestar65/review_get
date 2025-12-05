# Google Maps Review Scraper

Google Mapsから口コミを抽出してCSVでダウンロードできるWebアプリケーション。

## 機能

- **URL直接入力**: Google MapsのURLを入力して口コミを取得
- **店舗検索**: 店舗名や住所で検索して口コミを取得
- **CSV一括処理**: CSVファイルをアップロードして複数店舗の口コミを一括取得

## 技術スタック

- Backend: FastAPI (Python 3.11)
- Frontend: HTML + Tailwind CSS + JavaScript
- ブラウザ自動化: Selenium + Chromium Headless
- コンテナ: Docker
- ホスティング: Render

## ローカル開発

### 必要なもの

- Python 3.11+
- Google Chrome

### セットアップ

```bash
# リポジトリをクローン
git clone https://github.com/YOUR_USERNAME/google-maps-review-scraper.git
cd google-maps-review-scraper

# 仮想環境を作成
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 依存関係をインストール
pip install -r requirements.txt

# アプリを起動
uvicorn app.main:app --reload --port 8080
```

ブラウザで http://localhost:8080 を開く

### Dockerで起動

```bash
# ビルド
docker build -t google-maps-review-scraper .

# 起動
docker run -p 8080:8080 google-maps-review-scraper
```

## Renderへのデプロイ

1. このリポジトリをGitHubにプッシュ
2. [Render](https://render.com)でアカウント作成
3. "New" → "Web Service" を選択
4. GitHubリポジトリを接続
5. 以下の設定を確認:
   - **Name**: google-maps-review-scraper
   - **Runtime**: Docker
   - **Plan**: Starter ($7/month)
6. "Create Web Service" をクリック

## 使い方

### URL入力

1. Google Mapsで店舗ページを開く
2. URLをコピー
3. アプリにURLを貼り付け
4. 取得件数を指定して「口コミを取得」をクリック

### 店舗検索

1. 検索キーワード（例: "スターバックス 渋谷駅前"）を入力
2. 取得件数を指定して「口コミを取得」をクリック

### CSV一括

1. CSVファイルを用意（「URL」または「店舗名」「住所」列を含む）
2. CSVファイルをアップロード
3. 各店舗の取得件数を指定
4. 「一括取得開始」をクリック

## 注意事項

- Googleの利用規約を遵守してご利用ください
- 大量のリクエストはレート制限される可能性があります
- 商用利用の場合は適切なライセンスを確認してください

## ライセンス

MIT License
