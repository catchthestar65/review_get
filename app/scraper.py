"""
Google Maps Review Scraper
汎用的なGoogle Mapsの口コミ取得モジュール
"""

import time
import re
import urllib.parse
import os
from typing import List, Dict, Optional, Callable
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


class GoogleMapsReviewScraper:
    """Googleマップから口コミを取得するクラス"""

    def __init__(self, progress_callback: Optional[Callable] = None):
        self.reviews = []
        self.place_info = {}
        self.found_review_elements = []
        self.progress_callback = progress_callback

    def _update_progress(self, message: str, progress: int = 0):
        """進捗を更新"""
        if self.progress_callback:
            self.progress_callback(message, progress)

    def setup_driver(self) -> webdriver.Chrome:
        """Chrome WebDriverのセットアップ"""
        self._update_progress("ChromeDriverをセットアップ中...", 5)

        chrome_options = Options()

        # ヘッドレスモード
        chrome_options.add_argument('--headless=new')

        # 基本設定
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1280,720')
        chrome_options.add_argument('--lang=ja-JP')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        # メモリ節約設定（Render 512MB対応）
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-plugins')
        chrome_options.add_argument('--disable-software-rasterizer')
        chrome_options.add_argument('--disable-background-networking')
        chrome_options.add_argument('--disable-default-apps')
        chrome_options.add_argument('--disable-sync')
        chrome_options.add_argument('--disable-translate')
        chrome_options.add_argument('--single-process')
        chrome_options.add_argument('--no-zygote')
        chrome_options.add_argument('--renderer-process-limit=1')
        chrome_options.add_argument('--memory-pressure-off')
        chrome_options.add_argument('--js-flags=--max-old-space-size=256')

        # 画像読み込み無効化で高速化
        prefs = {
            'intl.accept_languages': 'ja,ja-JP',
            'profile.default_content_setting_values': {'images': 2}
        }
        chrome_options.add_experimental_option('prefs', prefs)
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging', 'enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        # Docker環境での設定
        chrome_bin = os.environ.get('CHROME_BIN')
        chromedriver_path = os.environ.get('CHROMEDRIVER_PATH')

        if chrome_bin:
            chrome_options.binary_location = chrome_bin

        if chromedriver_path:
            service = Service(executable_path=chromedriver_path)
        else:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())

        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(30)

        self._update_progress("ChromeDriverの起動完了", 10)
        return driver

    def scroll_reviews(self, driver, target_count: int) -> int:
        """口コミをスクロールして読み込む"""
        try:
            scrollable_div = None
            selectors = [
                'div.m6QErb.DxyBCb.kA9KIf.dS8AEf.XiKgde',
                'div.m6QErb.XiKgde',
                'div.m6QErb.DxyBCb',
                'div[role="main"]',
                'div.m6QErb'
            ]

            for selector in selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    for elem in elements:
                        scroll_height = driver.execute_script("return arguments[0].scrollHeight", elem)
                        client_height = driver.execute_script("return arguments[0].clientHeight", elem)
                        if scroll_height > client_height * 1.1:
                            scrollable_div = elem
                            break
                    if scrollable_div:
                        break
                except:
                    continue

            if not scrollable_div:
                return 0

            reviews_loaded = 0
            scroll_attempts = 0
            max_attempts = 500
            no_change_count = 0

            self._update_progress(f"スクロール開始... 目標: {target_count}件", 30)

            while scroll_attempts < max_attempts:
                current_reviews = driver.find_elements(By.CSS_SELECTOR,
                    'div[data-review-id], div.jftiEf.fontBodyMedium')
                reviews_loaded = len(current_reviews)

                if scroll_attempts % 20 == 0:
                    progress = min(30 + int((reviews_loaded / target_count) * 40), 70)
                    self._update_progress(f"読み込み中: {reviews_loaded}/{target_count}件", progress)

                if reviews_loaded >= target_count:
                    break

                driver.execute_script(
                    "arguments[0].scrollTo(0, arguments[0].scrollHeight);",
                    scrollable_div
                )
                time.sleep(1.5)

                for _ in range(5):
                    driver.execute_script("arguments[0].scrollBy(0, 800);", scrollable_div)
                    time.sleep(0.3)

                time.sleep(2)

                new_reviews = driver.find_elements(By.CSS_SELECTOR,
                    'div[data-review-id], div.jftiEf.fontBodyMedium')

                if len(new_reviews) == reviews_loaded:
                    no_change_count += 1
                    if no_change_count >= 20:
                        break
                else:
                    no_change_count = 0

                scroll_attempts += 1

            self.found_review_elements = driver.find_elements(By.CSS_SELECTOR,
                'div[data-review-id], div.jftiEf.fontBodyMedium')
            return len(self.found_review_elements)

        except Exception as e:
            return 0

    def expand_review_text(self, driver, review_element):
        """「もっと見る」ボタンをクリック"""
        try:
            selectors = [
                'button[aria-label*="もっと見る"]',
                'button.w8nwRe.kyuRq',
                'button.w8nwRe'
            ]
            for selector in selectors:
                try:
                    buttons = review_element.find_elements(By.CSS_SELECTOR, selector)
                    for button in buttons:
                        if button.is_displayed():
                            driver.execute_script("arguments[0].click();", button)
                            time.sleep(0.2)
                            return
                except:
                    continue
        except:
            pass

    def extract_reviews(self, driver, target_count: int, place_url: str) -> List[Dict]:
        """口コミデータを抽出"""
        reviews_data = []
        seen_reviews = set()

        try:
            review_elements = self.found_review_elements

            if not review_elements:
                review_elements = driver.find_elements(By.CSS_SELECTOR,
                    'div[data-review-id], div.jftiEf.fontBodyMedium')

            if not review_elements:
                return []

            self._update_progress(f"口コミを抽出中: 0/{len(review_elements)}件", 75)

            for idx, review in enumerate(review_elements, 1):
                if len(reviews_data) >= target_count:
                    break

                try:
                    self.expand_review_text(driver, review)

                    # 投稿者名
                    author = "不明"
                    try:
                        author_elem = review.find_element(By.CSS_SELECTOR, '.WNxzHc.qLhwHc')
                        author = author_elem.text.split('\n')[0].strip()
                    except:
                        pass

                    # 評価
                    rating = 0
                    try:
                        star_elem = review.find_element(By.CSS_SELECTOR, 'span.kvMYJc')
                        aria_label = star_elem.get_attribute('aria-label')
                        if aria_label:
                            match = re.search(r'(\d+)\s*つ星', aria_label)
                            if match:
                                rating = int(match.group(1))
                    except:
                        pass

                    # 投稿日時
                    date = "不明"
                    try:
                        date_elem = review.find_element(By.CSS_SELECTOR, 'span.rsqaWe')
                        date = date_elem.text.strip()
                    except:
                        pass

                    # 口コミテキスト
                    text = ""
                    try:
                        text_elem = review.find_element(By.CSS_SELECTOR, 'span.wiI7pd')
                        text = text_elem.text.strip()
                        if 'オーナーからの返信' in text:
                            text = text.split('オーナーからの返信')[0].strip()
                        text = text.replace('もっと見る', '').strip()
                    except:
                        pass

                    if not text:
                        continue

                    # 重複チェック
                    review_key = f"{author}_{text[:50]}"
                    if review_key in seen_reviews:
                        continue
                    seen_reviews.add(review_key)

                    reviews_data.append({
                        '投稿者名': author,
                        '評価': rating,
                        '評価星': '★' * rating + '☆' * (5 - rating) if rating > 0 else '評価なし',
                        '投稿日時': date,
                        '口コミテキスト': text,
                        '出典URL': place_url
                    })

                    if idx % 10 == 0:
                        progress = min(75 + int((len(reviews_data) / target_count) * 20), 95)
                        self._update_progress(f"抽出中: {len(reviews_data)}/{target_count}件", progress)

                except:
                    continue

            return reviews_data

        except Exception as e:
            return reviews_data

    def get_place_info(self, driver) -> Dict:
        """店舗情報を取得"""
        try:
            # 店舗名
            place_name = "不明"
            try:
                h1_elem = driver.find_element(By.TAG_NAME, 'h1')
                place_name = h1_elem.text.strip()
            except:
                try:
                    page_title = driver.title
                    if " - Google" in page_title:
                        place_name = page_title.split(" - Google")[0].strip()
                except:
                    pass

            # 平均評価
            avg_rating = "不明"
            try:
                rating_elem = driver.find_element(By.CSS_SELECTOR, 'div.F7nice span[aria-hidden="true"]')
                avg_rating = rating_elem.text
            except:
                pass

            # レビュー数
            review_count = "不明"
            try:
                count_elem = driver.find_element(By.CSS_SELECTOR, 'button[aria-label*="件のクチコミ"]')
                aria_label = count_elem.get_attribute('aria-label')
                match = re.search(r'([\d,]+)\s*件', aria_label)
                if match:
                    review_count = match.group(1)
            except:
                pass

            self.place_info = {
                'name': place_name,
                'avg_rating': avg_rating,
                'review_count': review_count
            }

            return self.place_info

        except Exception as e:
            self.place_info = {'name': '不明', 'avg_rating': '不明', 'review_count': '不明'}
            return self.place_info

    def scrape_reviews(self, url: str, target_count: int = 100) -> List[Dict]:
        """メイン処理：口コミを取得"""
        driver = self.setup_driver()

        try:
            # 日本語設定
            if 'hl=' not in url:
                separator = '&' if '?' in url else '?'
                url = f"{url}{separator}hl=ja"

            self._update_progress(f"ページにアクセス中...", 15)
            driver.get(url)
            time.sleep(10)

            # デバッグ: ページタイトルとURLを記録
            self._update_progress(f"ページ読込完了: {driver.title[:30]}...", 16)

            # Cookieバナーを閉じる
            try:
                cookie_buttons = driver.find_elements(By.CSS_SELECTOR,
                    'button[aria-label*="すべて拒否"], button[aria-label*="同意"], form[action*="consent"] button')
                for btn in cookie_buttons:
                    if btn.is_displayed():
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(2)
                        break
            except:
                pass

            # 検索結果ページの場合、最初の店舗をクリック
            if '/maps/search/' in url:
                self._update_progress("検索結果から店舗を選択中...", 18)
                try:
                    # 検索結果の最初の店舗をクリック
                    first_result = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="/maps/place/"]'))
                    )
                    driver.execute_script("arguments[0].click();", first_result)
                    time.sleep(8)
                except:
                    # 別のセレクタを試す
                    try:
                        results = driver.find_elements(By.CSS_SELECTOR, 'div.Nv2PK')
                        if results:
                            driver.execute_script("arguments[0].click();", results[0])
                            time.sleep(8)
                    except:
                        pass

            # 店舗情報取得
            self._update_progress("店舗情報を取得中...", 20)
            self.get_place_info(driver)

            # 口コミタブをクリック
            self._update_progress("口コミタブを開いています...", 25)
            try:
                reviews_tab = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'button[aria-label*="のクチコミ"]'))
                )
                driver.execute_script("arguments[0].click();", reviews_tab)
                time.sleep(5)
            except:
                pass

            # 並び順を「最新」に変更
            try:
                sort_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-value="Sort"]'))
                )
                driver.execute_script("arguments[0].click();", sort_button)
                time.sleep(2)

                newest_option = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, '//div[@role="menuitemradio"][contains(., "新しい順")]'))
                )
                driver.execute_script("arguments[0].click();", newest_option)
                time.sleep(3)
            except:
                pass

            # 口コミをスクロールして読み込み
            loaded_count = self.scroll_reviews(driver, target_count)

            if loaded_count == 0:
                return []

            # 口コミを抽出
            self.reviews = self.extract_reviews(driver, target_count, url)

            self._update_progress(f"完了: {len(self.reviews)}件取得", 100)
            return self.reviews

        except Exception as e:
            return []

        finally:
            driver.quit()

    def scrape_by_search(self, query: str, target_count: int = 100) -> List[Dict]:
        """検索クエリから口コミを取得"""
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.google.com/maps/search/{encoded_query}"
        return self.scrape_reviews(url, target_count)
