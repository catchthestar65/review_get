"""
Google Maps Review Scraper - FastAPI Application
"""

import os
import uuid
import io
import csv
import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from pydantic import BaseModel

from app.scraper import GoogleMapsReviewScraper

# FastAPI アプリ
app = FastAPI(
    title="Google Maps Review Scraper",
    description="Google Mapsから口コミを抽出するWebアプリ",
    version="1.0.0"
)

# 静的ファイルとテンプレート
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# タスク管理（メモリ内ストレージ）
tasks: Dict[str, Dict] = {}

# スレッドプール（Seleniumはブロッキングなので）
executor = ThreadPoolExecutor(max_workers=2)


# リクエストモデル
class UrlRequest(BaseModel):
    url: str
    count: int = 50


class SearchRequest(BaseModel):
    query: str
    count: int = 50


# ルートページ
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# タスクステータス取得
@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return tasks[task_id]


# URL直接入力でスクレイピング
@app.post("/api/scrape/url")
async def scrape_by_url(request: UrlRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "task_id": task_id,
        "status": "processing",
        "progress": 0,
        "message": "処理を開始しています...",
        "data": None,
        "place_info": None,
        "error": None
    }

    background_tasks.add_task(run_scrape_url, task_id, request.url, request.count)

    return {"task_id": task_id, "status": "processing"}


def run_scrape_url(task_id: str, url: str, count: int):
    """URLからスクレイピング実行（バックグラウンド）"""
    def update_progress(message: str, progress: int):
        tasks[task_id]["message"] = message
        tasks[task_id]["progress"] = progress

    try:
        scraper = GoogleMapsReviewScraper(progress_callback=update_progress)
        reviews = scraper.scrape_reviews(url, count)

        tasks[task_id]["status"] = "completed"
        tasks[task_id]["progress"] = 100
        tasks[task_id]["message"] = f"完了: {len(reviews)}件の口コミを取得しました"
        tasks[task_id]["data"] = reviews
        tasks[task_id]["place_info"] = scraper.place_info

    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["message"] = f"エラー: {str(e)}"
        tasks[task_id]["error"] = str(e)


# 検索クエリでスクレイピング
@app.post("/api/scrape/search")
async def scrape_by_search(request: SearchRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "task_id": task_id,
        "status": "processing",
        "progress": 0,
        "message": "処理を開始しています...",
        "data": None,
        "place_info": None,
        "error": None
    }

    background_tasks.add_task(run_scrape_search, task_id, request.query, request.count)

    return {"task_id": task_id, "status": "processing"}


def run_scrape_search(task_id: str, query: str, count: int):
    """検索クエリからスクレイピング実行"""
    def update_progress(message: str, progress: int):
        tasks[task_id]["message"] = message
        tasks[task_id]["progress"] = progress

    try:
        scraper = GoogleMapsReviewScraper(progress_callback=update_progress)
        reviews = scraper.scrape_by_search(query, count)

        tasks[task_id]["status"] = "completed"
        tasks[task_id]["progress"] = 100
        tasks[task_id]["message"] = f"完了: {len(reviews)}件の口コミを取得しました"
        tasks[task_id]["data"] = reviews
        tasks[task_id]["place_info"] = scraper.place_info

    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["message"] = f"エラー: {str(e)}"
        tasks[task_id]["error"] = str(e)


# CSV一括処理
@app.post("/api/scrape/csv")
async def scrape_by_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    count: int = Form(default=50)
):
    # CSVファイルを読み込み
    content = await file.read()
    try:
        text = content.decode('utf-8-sig')
    except:
        try:
            text = content.decode('shift-jis')
        except:
            text = content.decode('cp932')

    # CSVをパース
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)

    if not rows:
        raise HTTPException(status_code=400, detail="CSVファイルが空です")

    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "task_id": task_id,
        "status": "processing",
        "progress": 0,
        "message": f"処理を開始: {len(rows)}店舗",
        "data": None,
        "total_stores": len(rows),
        "completed_stores": 0,
        "error": None
    }

    background_tasks.add_task(run_scrape_csv, task_id, rows, count)

    return {"task_id": task_id, "status": "processing", "total_stores": len(rows)}


def run_scrape_csv(task_id: str, rows: List[Dict], count: int):
    """CSV一括スクレイピング実行"""
    import time
    import urllib.parse

    all_reviews = []
    total = len(rows)

    for idx, row in enumerate(rows):
        # URL列を探す
        url = None
        for key in row.keys():
            if 'url' in key.lower() or 'マップ' in key or 'map' in key.lower():
                url = row[key]
                break

        # URLがない場合は検索
        if not url:
            # 店舗名・住所を組み合わせて検索
            search_parts = []
            for key in ['店舗名', '院名', 'name', '名前', '住所', 'address']:
                if key in row and row[key]:
                    search_parts.append(row[key])
            if search_parts:
                query = ' '.join(search_parts)
                encoded = urllib.parse.quote(query)
                url = f"https://www.google.com/maps/search/{encoded}"

        if not url:
            continue

        tasks[task_id]["message"] = f"処理中: {idx + 1}/{total} 店舗"
        tasks[task_id]["progress"] = int((idx / total) * 100)
        tasks[task_id]["completed_stores"] = idx

        def update_progress(message: str, progress: int):
            store_progress = int((idx / total) * 100) + int((progress / 100) * (100 / total))
            tasks[task_id]["progress"] = min(store_progress, 99)

        try:
            scraper = GoogleMapsReviewScraper(progress_callback=update_progress)
            reviews = scraper.scrape_reviews(url, count)

            # 店舗情報を追加
            for review in reviews:
                review['店舗名'] = scraper.place_info.get('name', '不明')
                for key in row.keys():
                    if key not in review:
                        review[key] = row[key]

            all_reviews.extend(reviews)

        except Exception as e:
            pass

        # レート制限対策
        if idx < total - 1:
            time.sleep(20)

    tasks[task_id]["status"] = "completed"
    tasks[task_id]["progress"] = 100
    tasks[task_id]["message"] = f"完了: {len(all_reviews)}件の口コミを取得しました（{total}店舗）"
    tasks[task_id]["data"] = all_reviews
    tasks[task_id]["completed_stores"] = total


# CSVダウンロード
@app.get("/api/download/{task_id}")
async def download_csv(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = tasks[task_id]
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="Task not completed yet")

    if not task["data"]:
        raise HTTPException(status_code=400, detail="No data available")

    # CSVを作成
    output = io.StringIO()
    if task["data"]:
        fieldnames = task["data"][0].keys()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(task["data"])

    output.seek(0)

    # ファイル名
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"google_maps_reviews_{timestamp}.csv"

    # BOMつきUTF-8で返す（Excel対応）
    content = '\ufeff' + output.getvalue()

    return StreamingResponse(
        io.BytesIO(content.encode('utf-8')),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ヘルスチェック
@app.get("/health")
async def health_check():
    return {"status": "healthy"}
