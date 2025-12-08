"""
Google Maps Review Scraper
汎用的なGoogle Mapsの口コミ取得モジュール
"""

import time
import re
import urllib.parse
import os
import logging
from typing import List, Dict, Optional, Callable
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class GoogleMapsReviewScraper:
    """Googleマップから口コミを取得するクラス"""

    def __init__(self, progress_callback: Optional[Callable] = None):
        self.reviews = []
        self.place_info = {}
        self.found_review_elements = []
        self.progress_callback = progress_callback
        self.debug_info = {}  # デバッグ情報を保持

    def _update_progress(self, message: str, progress: int = 0):
        """進捗を更新"""
        logger.info(f"[進捗 {progress}%] {message}")
        if self.progress_callback:
            self.progress_callback(message, progress)

    def _debug(self, key: str, value):
        """デバッグ情報を記録"""
        self.debug_info[key] = value
        logger.info(f"[DEBUG] {key}: {value}")

    def setup_driver(self) -> webdriver.Chrome:
        """Chrome WebDriverのセットアップ（元のeminal_mac_完全版と同じ設定）"""
        self._update_progress("ChromeDriverをセットアップ中...", 5)

        chrome_options = Options()

        # ヘッドレスモード
        chrome_options.add_argument('--headless=new')

        # 基本設定（元のeminal_mac_完全版と同じ）
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--lang=ja-JP')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        # 画像読み込み無効化で高速化（元のeminal_mac_完全版と同じ）
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
            # スクロール可能な領域を探す（元のeminal_mac_完全版と同じセレクタ順）
            scrollable_div = None
            found_selector = None
            selectors = [
                'div.m6QErb.DxyBCb.kA9KIf.dS8AEf.XiKgde',
                'div.m6QErb.XiKgde',
                'div.m6QErb.DxyBCb',
                'div[role="main"]',
                'div.m6QErb'
            ]

            self._debug("scroll_selectors_count", len(selectors))

            for selector in selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    self._debug(f"selector_{selector[:30]}", f"found {len(elements)} elements")

                    for idx, elem in enumerate(elements):
                        try:
                            scroll_height = driver.execute_script("return arguments[0].scrollHeight", elem)
                            client_height = driver.execute_script("return arguments[0].clientHeight", elem)
                            self._debug(f"elem_{idx}_heights", f"scroll={scroll_height}, client={client_height}")

                            if scroll_height > client_height * 1.1:
                                scrollable_div = elem
                                found_selector = selector
                                self._debug("found_scrollable", f"{selector}, heights: {scroll_height}/{client_height}")
                                break
                        except Exception as e:
                            self._debug(f"elem_{idx}_error", str(e)[:50])
                    if scrollable_div:
                        break
                except Exception as e:
                    self._debug(f"selector_error_{selector[:20]}", str(e)[:50])
                    continue

            if not scrollable_div:
                self._update_progress("スクロール領域が見つかりません", 31)
                self._debug("scroll_area_not_found", "true")
                # ページ全体のスクリーンショット的な情報を取得
                page_source_len = len(driver.page_source)
                self._debug("page_source_length", page_source_len)
                return 0

            self._update_progress(f"スクロール領域発見: {found_selector[:25]}", 31)

            reviews_loaded = 0
            scroll_attempts = 0
            max_attempts = 500  # 元のコードと同じ
            no_change_count = 0
            last_scroll_height = 0

            # 口コミ要素のセレクタ（元のeminal_mac_完全版と同じ - div.jftiEf単体は広すぎるので除外）
            review_selectors = 'div[data-review-id], div.jftiEf.fontBodyMedium'

            self._update_progress(f"スクロール開始... 目標: {target_count}件", 32)

            while scroll_attempts < max_attempts:
                current_reviews = driver.find_elements(By.CSS_SELECTOR, review_selectors)
                reviews_loaded = len(current_reviews)

                # 定期的に詳細ログ（元のコードと同じ: 20回ごと）
                if scroll_attempts % 20 == 0:
                    progress = min(32 + int((reviews_loaded / target_count) * 38), 70)
                    self._update_progress(f"読込中: {reviews_loaded}/{target_count}件", progress)

                if reviews_loaded >= target_count:
                    self._debug("target_reached", f"loaded={reviews_loaded}, target={target_count}")
                    break

                # スクロール実行（元のコードと完全一致: scrollTo使用）
                driver.execute_script(
                    "arguments[0].scrollTo(0, arguments[0].scrollHeight);",
                    scrollable_div
                )
                time.sleep(2.0)  # Render環境用に延長

                # 追加のスクロール（元のコードと完全一致: 800px）
                for _ in range(5):
                    driver.execute_script("arguments[0].scrollBy(0, 800);", scrollable_div)
                    time.sleep(0.5)  # Render環境用に延長

                time.sleep(3.0)  # Render環境用に延長

                # 新しい口コミ数を確認
                new_reviews = driver.find_elements(By.CSS_SELECTOR, review_selectors)

                # 変化がない場合のカウント
                if len(new_reviews) == reviews_loaded:
                    no_change_count += 1
                    if no_change_count >= 15:  # 早めに確認開始
                        # 終了前に追加待機して再確認（Render環境は読み込みが遅い）
                        self._update_progress(f"追加読み込み待機中... ({len(new_reviews)}件)", 68)
                        time.sleep(5)  # 長めに待機

                        # 追加スクロール
                        for _ in range(3):
                            driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", scrollable_div)
                            time.sleep(2)

                        final_reviews = driver.find_elements(By.CSS_SELECTOR, review_selectors)
                        if len(final_reviews) > reviews_loaded:
                            # まだ増えているのでリセット
                            no_change_count = 0
                            self._debug("found_more_after_wait", f"new={len(final_reviews)}, old={reviews_loaded}")
                        elif no_change_count >= 25:  # 本当の終了
                            self._update_progress(f"これ以上読み込めません（最終: {len(final_reviews)}件）", 70)
                            self._debug("scroll_finished", f"final_count={len(final_reviews)}, attempts={scroll_attempts}")
                            break
                else:
                    no_change_count = 0

                scroll_attempts += 1

            self.found_review_elements = driver.find_elements(By.CSS_SELECTOR, review_selectors)
            final_count = len(self.found_review_elements)
            self._debug("final_review_count", final_count)
            return final_count

        except Exception as e:
            self._update_progress(f"スクロールエラー: {str(e)[:30]}", 70)
            self._debug("scroll_exception", str(e))
            logger.exception("スクロール中にエラー発生")
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
                self._update_progress("抽出対象の口コミなし", 75)
                return []

            self._update_progress(f"口コミを抽出中: 0/{len(review_elements)}件", 75)

            for idx, review in enumerate(review_elements, 1):
                if len(reviews_data) >= target_count:
                    break

                try:
                    self.expand_review_text(driver, review)

                    # 投稿者名（複数セレクタ対応）
                    author = "不明"
                    author_selectors = ['.WNxzHc.qLhwHc', '.d4r55', 'button[data-review-author-link]', 'a[data-review-author-link]']
                    for sel in author_selectors:
                        try:
                            author_elem = review.find_element(By.CSS_SELECTOR, sel)
                            author = author_elem.text.split('\n')[0].strip()
                            if author:
                                break
                        except:
                            continue

                    # 評価（複数パターン対応）
                    rating = 0
                    rating_selectors = ['span.kvMYJc', 'span[role="img"]', 'span.fzvQIb']
                    for sel in rating_selectors:
                        try:
                            star_elem = review.find_element(By.CSS_SELECTOR, sel)
                            aria_label = star_elem.get_attribute('aria-label')
                            if aria_label:
                                # 日本語パターン
                                match = re.search(r'(\d+)\s*つ星', aria_label)
                                if match:
                                    rating = int(match.group(1))
                                    break
                                # 英語パターン
                                match = re.search(r'(\d+)\s*star', aria_label, re.IGNORECASE)
                                if match:
                                    rating = int(match.group(1))
                                    break
                        except:
                            continue

                    # 投稿日時（複数セレクタ対応）
                    date = "不明"
                    date_selectors = ['span.rsqaWe', '.DU9Pgb', 'span.dehysf']
                    for sel in date_selectors:
                        try:
                            date_elem = review.find_element(By.CSS_SELECTOR, sel)
                            date = date_elem.text.strip()
                            if date:
                                break
                        except:
                            continue

                    # 口コミテキスト（複数セレクタ対応）
                    text = ""
                    text_selectors = ['span.wiI7pd', '.MyEned span', '.Jtu6Td span', 'div.MyEned']
                    for sel in text_selectors:
                        try:
                            text_elem = review.find_element(By.CSS_SELECTOR, sel)
                            text = text_elem.text.strip()
                            if text:
                                break
                        except:
                            continue

                    if text:
                        if 'オーナーからの返信' in text:
                            text = text.split('オーナーからの返信')[0].strip()
                        text = text.replace('もっと見る', '').strip()

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
            self._update_progress(f"抽出エラー: {str(e)[:20]}", 95)
            return reviews_data

    def get_place_info(self, driver) -> Dict:
        """店舗情報を取得"""
        try:
            # デバッグ用：ページタイトル
            debug_title = driver.title if driver.title else "タイトルなし"

            # 店舗名
            place_name = "不明"
            try:
                h1_elem = driver.find_element(By.TAG_NAME, 'h1')
                place_name = h1_elem.text.strip()
                if not place_name:
                    place_name = f"(h1空) {debug_title[:30]}"
            except:
                try:
                    page_title = driver.title
                    if " - Google" in page_title:
                        place_name = page_title.split(" - Google")[0].strip()
                    else:
                        place_name = f"(h1なし) {debug_title[:30]}"
                except:
                    place_name = f"(エラー) {debug_title[:30]}"

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

            # /maps/place/店舗名 形式を /maps/search/店舗名 形式に変換
            # （座標がないplace URLは検索として処理する方が確実）
            if '/maps/place/' in url and '@' not in url and 'data=' not in url:
                # URLから店舗名を抽出
                place_match = re.search(r'/maps/place/([^/?]+)', url)
                if place_match:
                    place_query = urllib.parse.unquote(place_match.group(1).replace('+', ' '))
                    url = f"https://www.google.com/maps/search/{urllib.parse.quote(place_query)}"
                    self._update_progress(f"検索URLに変換: {place_query[:20]}", 14)

            self._update_progress(f"ページにアクセス中...", 15)
            driver.get(url)
            time.sleep(10)

            # デバッグ: ページタイトルとURLを記録
            page_title = driver.title if driver.title else "タイトルなし"
            current_url = driver.current_url
            self._update_progress(f"タイトル: {page_title[:30]}", 16)

            # デバッグ: consent/同意ページかチェック
            if 'consent' in current_url.lower() or 'consent' in page_title.lower():
                self._update_progress("同意ページ検出、処理中...", 17)

            # Cookieバナー/同意ページを閉じる（複数のパターン対応）
            consent_clicked = False
            try:
                cookie_selectors = [
                    # 日本語
                    'button[aria-label*="すべて同意"]',
                    'button[aria-label*="同意する"]',
                    'button[aria-label*="すべて拒否"]',
                    # 英語
                    'button[aria-label*="Accept all"]',
                    'button[aria-label*="Reject all"]',
                    'button[aria-label*="Accept"]',
                    # フォームボタン
                    'form[action*="consent"] button[value="1"]',
                    'form[action*="consent"] button',
                    # 汎用
                    'button.VfPpkd-LgbsSe[data-mdc-dialog-action="accept"]',
                    'button[jsname="higCR"]',
                    'button[jsname="b3VHJd"]',
                    # XPath fallback
                ]
                for sel in cookie_selectors:
                    try:
                        btns = driver.find_elements(By.CSS_SELECTOR, sel)
                        for btn in btns:
                            if btn.is_displayed():
                                driver.execute_script("arguments[0].click();", btn)
                                consent_clicked = True
                                self._update_progress("同意ボタンをクリック", 17)
                                time.sleep(3)
                                break
                        if consent_clicked:
                            break
                    except:
                        continue

                # XPathでも試す
                if not consent_clicked:
                    try:
                        accept_btn = driver.find_element(By.XPATH, '//button[contains(text(), "同意") or contains(text(), "Accept") or contains(text(), "すべて")]')
                        if accept_btn.is_displayed():
                            driver.execute_script("arguments[0].click();", accept_btn)
                            self._update_progress("XPathで同意ボタンクリック", 17)
                            time.sleep(3)
                    except:
                        pass
            except:
                pass

            # 同意後、再度ページタイトル確認
            if consent_clicked:
                time.sleep(2)
                page_title = driver.title if driver.title else "タイトルなし"
                self._update_progress(f"同意後タイトル: {page_title[:25]}", 18)

            # 検索結果ページ判定（座標付きURLは直接店舗ページなので除外）
            # 座標付きURL例: /@35.6931021,139.6988854,17z/
            has_coordinates = '/@' in url and 'z/' in url
            is_search_page = '/maps/search/' in url or ('/maps/place/' in url and not has_coordinates)
            store_found = False

            self._debug("URL判定", f"has_coordinates={has_coordinates}, is_search_page={is_search_page}")

            if is_search_page:
                self._update_progress("検索結果から店舗を選択中...", 18)

                # まず店舗リストから最初の店舗をクリック
                try:
                    # 方法1: 店舗カードをクリック
                    first_result = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="/maps/place/"]'))
                    )
                    driver.execute_script("arguments[0].click();", first_result)
                    store_found = True
                    time.sleep(8)
                except:
                    pass

                if not store_found:
                    try:
                        # 方法2: div.Nv2PKをクリック
                        results = driver.find_elements(By.CSS_SELECTOR, 'div.Nv2PK')
                        if results:
                            driver.execute_script("arguments[0].click();", results[0])
                            store_found = True
                            time.sleep(8)
                    except:
                        pass

                if not store_found:
                    try:
                        # 方法3: 任意のクリック可能な結果
                        results = driver.find_elements(By.CSS_SELECTOR, '[role="article"], .fontHeadlineSmall')
                        if results:
                            driver.execute_script("arguments[0].click();", results[0])
                            store_found = True
                            time.sleep(8)
                    except:
                        pass

                if store_found:
                    self._update_progress("店舗を選択しました", 19)
                else:
                    self._update_progress("店舗の選択に失敗", 19)

            # 店舗情報取得
            self._update_progress("店舗情報を取得中...", 20)
            self.get_place_info(driver)
            self._update_progress(f"店舗: {self.place_info.get('name', '不明')[:20]}", 22)

            # 口コミタブをクリック（複数のセレクタ対応）
            self._update_progress("口コミタブを探しています...", 25)
            reviews_tab_found = False
            tab_selectors = [
                'button[aria-label*="のクチコミ"]',
                'button[aria-label*="クチコミ"]',
                'button[aria-label*="reviews"]',
                'button[data-tab-index="1"]',
                'div[role="tab"][aria-label*="クチコミ"]',
                'button.hh2c6'
            ]
            for sel in tab_selectors:
                try:
                    reviews_tab = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                    )
                    driver.execute_script("arguments[0].click();", reviews_tab)
                    time.sleep(5)
                    reviews_tab_found = True
                    self._update_progress("口コミタブを開きました", 28)
                    break
                except:
                    continue

            if not reviews_tab_found:
                self._update_progress("口コミタブが見つかりません、直接探索", 28)

            # 並び順を「最新」に変更
            try:
                sort_button = WebDriverWait(driver, 8).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-value="Sort"]'))
                )
                driver.execute_script("arguments[0].click();", sort_button)
                time.sleep(2)

                newest_option = WebDriverWait(driver, 8).until(
                    EC.element_to_be_clickable((By.XPATH, '//div[@role="menuitemradio"][contains(., "新しい順")]'))
                )
                driver.execute_script("arguments[0].click();", newest_option)
                time.sleep(3)
            except:
                pass

            # 現在のページの口コミ要素を事前確認
            initial_reviews = driver.find_elements(By.CSS_SELECTOR,
                'div[data-review-id], div.jftiEf.fontBodyMedium')
            self._update_progress(f"初期口コミ数: {len(initial_reviews)}件", 29)

            # 口コミをスクロールして読み込み
            loaded_count = self.scroll_reviews(driver, target_count)
            self._update_progress(f"スクロール後: {loaded_count}件発見", 72)

            if loaded_count == 0:
                # スクロールできなかった場合、現在表示されている口コミを取得
                self._update_progress("スクロールなしで口コミを取得中...", 73)
                self.found_review_elements = driver.find_elements(By.CSS_SELECTOR,
                    'div[data-review-id], div.jftiEf.fontBodyMedium')
                loaded_count = len(self.found_review_elements)
                if loaded_count == 0:
                    self._update_progress("口コミが見つかりませんでした", 100)
                    return []

            # 口コミを抽出
            self.reviews = self.extract_reviews(driver, target_count, url)

            self._update_progress(f"完了: {len(self.reviews)}件取得", 100)
            return self.reviews

        except Exception as e:
            self._update_progress(f"エラー: {str(e)[:30]}", 100)
            return []

        finally:
            driver.quit()

    def scrape_by_search(self, query: str, target_count: int = 100) -> List[Dict]:
        """検索クエリから口コミを取得"""
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.google.com/maps/search/{encoded_query}"
        return self.scrape_reviews(url, target_count)
