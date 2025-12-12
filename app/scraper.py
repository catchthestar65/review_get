"""
Google Maps Review Scraper - Playwright版
Playwrightを使用してBot検出を回避しながら口コミを取得
"""

import time
import re
import urllib.parse
import os
import logging
from typing import List, Dict, Optional, Callable
from playwright.sync_api import sync_playwright, Page, Browser
from playwright_stealth import stealth_sync

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class GoogleMapsReviewScraper:
    """Googleマップから口コミを取得するクラス（Playwright版）"""

    def __init__(self, progress_callback: Optional[Callable] = None):
        self.reviews = []
        self.place_info = {}
        self.found_review_elements = []
        self.progress_callback = progress_callback
        self.debug_info = {}

    def _update_progress(self, message: str, progress: int = 0):
        """進捗を更新"""
        logger.info(f"[進捗 {progress}%] {message}")
        if self.progress_callback:
            self.progress_callback(message, progress)

    def _debug(self, key: str, value):
        """デバッグ情報を記録"""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.debug_info[key] = value
        logger.info(f"[DEBUG {timestamp}] {key}: {value}")

    def _capture_page_state(self, page: Page, label: str):
        """ページの状態をキャプチャしてデバッグ情報に記録"""
        try:
            content = page.content()
            current_url = page.url
            title = page.title()

            state = {
                'label': label,
                'url': current_url[:100],
                'title': title[:50],
                'page_source_length': len(content),
            }

            # 主要な要素の存在確認
            checks = {
                'h1_exists': page.locator('h1').count() > 0,
                'reviews_tab_exists': page.locator('button[aria-label*="クチコミ"]').count() > 0,
                'review_elements': page.locator('div[data-review-id], div.jftiEf.fontBodyMedium').count(),
                'scrollable_divs': page.locator('div.m6QErb').count(),
                'consent_page': 'consent' in current_url.lower(),
            }
            state.update(checks)
            self._debug(f"PAGE_STATE_{label}", state)

            # ページソースの確認
            if len(content) < 1000:
                self._debug(f"PAGE_SOURCE_{label}", f"SHORT_PAGE: {content[:500]}")
            elif 'クチコミ' not in content and 'review' not in content.lower():
                body_text = page.locator('body').inner_text()[:300] if page.locator('body').count() > 0 else ''
                self._debug(f"PAGE_CONTENT_{label}", {
                    "has_review_text": False,
                    "body_preview": body_text[:200]
                })

            return state
        except Exception as e:
            self._debug(f"PAGE_STATE_ERROR_{label}", str(e))
            logger.exception(f"_capture_page_state error: {label}")

    def convert_to_cid_url(self, url: str) -> str:
        """URLをCID形式に変換"""
        self._debug("URL_CONVERT_INPUT", url[:80])

        cid_match = re.search(r'!1s(0x[0-9a-f]+:0x[0-9a-f]+)', url)
        if cid_match:
            cid_hex = cid_match.group(1)
            self._debug("CID_HEX_FOUND", cid_hex)

            try:
                hex_parts = cid_hex.split(':')
                hex_part = hex_parts[1][2:]
                cid_decimal = int(hex_part, 16)
                cid_url = f"https://www.google.com/maps?cid={cid_decimal}&hl=ja"
                self._debug("CID_URL_GENERATED", cid_url)
                return cid_url
            except Exception as e:
                self._debug("CID_CONVERT_ERROR", str(e))

        self._debug("CID_NOT_FOUND", "trying parameter cleanup")
        cleaned_url = re.sub(r'[?&](entry|g_ep)=[^&]*', '', url)
        if '?' not in cleaned_url:
            cleaned_url = cleaned_url.replace('&', '?', 1)
        if 'hl=' not in cleaned_url:
            separator = '&' if '?' in cleaned_url else '?'
            cleaned_url = f"{cleaned_url}{separator}hl=ja"

        self._debug("URL_CONVERT_OUTPUT", cleaned_url[:80])
        return cleaned_url

    def scroll_reviews(self, page: Page, target_count: int) -> int:
        """口コミをスクロールして読み込む"""
        try:
            # スクロール可能な領域を探す
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
                    elements = page.locator(selector).all()
                    self._debug(f"selector_{selector[:30]}", f"found {len(elements)} elements")

                    for idx, elem in enumerate(elements):
                        try:
                            bbox = elem.bounding_box()
                            if bbox and bbox['height'] > 100:
                                # スクロール可能かチェック
                                scroll_height = elem.evaluate("el => el.scrollHeight")
                                client_height = elem.evaluate("el => el.clientHeight")
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
                self._capture_page_state(page, "SCROLL_AREA_NOT_FOUND")
                return 0

            self._update_progress(f"スクロール領域発見: {found_selector[:25]}", 31)

            reviews_loaded = 0
            scroll_attempts = 0
            max_attempts = 100
            no_change_count = 0

            review_selector = 'div[data-review-id], div.jftiEf.fontBodyMedium'

            self._update_progress(f"スクロール開始... 目標: {target_count}件", 32)

            while scroll_attempts < max_attempts:
                current_reviews = page.locator(review_selector).count()
                reviews_loaded = current_reviews

                if scroll_attempts % 10 == 0:
                    progress = min(32 + int((reviews_loaded / target_count) * 38), 70)
                    self._update_progress(f"読込中: {reviews_loaded}/{target_count}件", progress)

                if reviews_loaded >= target_count:
                    self._debug("target_reached", f"loaded={reviews_loaded}, target={target_count}")
                    break

                # スクロール実行
                scrollable_div.evaluate("el => el.scrollTo(0, el.scrollHeight)")
                time.sleep(1.5)

                # 追加のスクロール
                for _ in range(3):
                    scrollable_div.evaluate("el => el.scrollBy(0, 500)")
                    time.sleep(0.3)

                time.sleep(2)

                new_count = page.locator(review_selector).count()

                if new_count == reviews_loaded:
                    no_change_count += 1
                    if no_change_count >= 10:
                        self._update_progress(f"追加読み込み待機中... ({new_count}件)", 68)
                        time.sleep(3)
                        scrollable_div.evaluate("el => el.scrollTo(0, el.scrollHeight)")
                        time.sleep(2)

                        final_count = page.locator(review_selector).count()
                        if final_count > reviews_loaded:
                            no_change_count = 0
                        elif no_change_count >= 15:
                            self._update_progress(f"これ以上読み込めません（最終: {final_count}件）", 70)
                            self._debug("scroll_finished", f"final_count={final_count}, attempts={scroll_attempts}")
                            break
                else:
                    no_change_count = 0

                scroll_attempts += 1

            final_count = page.locator(review_selector).count()
            self._debug("final_review_count", final_count)
            return final_count

        except Exception as e:
            self._update_progress(f"スクロールエラー: {str(e)[:30]}", 70)
            self._debug("scroll_exception", str(e))
            logger.exception("スクロール中にエラー発生")
            return 0

    def expand_review_text(self, page: Page, review_element):
        """「もっと見る」ボタンをクリック"""
        try:
            more_buttons = review_element.locator('button.w8nwRe, button[aria-label*="もっと見る"]').all()
            for button in more_buttons:
                if button.is_visible():
                    button.click()
                    time.sleep(0.2)
                    return
        except:
            pass

    def extract_reviews(self, page: Page, target_count: int, place_url: str) -> List[Dict]:
        """口コミデータを抽出"""
        reviews_data = []
        seen_reviews = set()

        try:
            review_elements = page.locator('div[data-review-id], div.jftiEf.fontBodyMedium').all()

            if not review_elements:
                self._update_progress("抽出対象の口コミなし", 75)
                return []

            self._update_progress(f"口コミを抽出中: 0/{len(review_elements)}件", 75)

            for idx, review in enumerate(review_elements):
                if len(reviews_data) >= target_count:
                    break

                try:
                    self.expand_review_text(page, review)

                    # 投稿者名
                    author = "不明"
                    for sel in ['.WNxzHc.qLhwHc', '.d4r55', 'button[data-review-author-link]']:
                        try:
                            author_elem = review.locator(sel).first
                            if author_elem.count() > 0:
                                author = author_elem.inner_text().split('\n')[0].strip()
                                if author:
                                    break
                        except:
                            continue

                    # 評価
                    rating = 0
                    for sel in ['span.kvMYJc', 'span[role="img"]', 'span.fzvQIb']:
                        try:
                            star_elem = review.locator(sel).first
                            if star_elem.count() > 0:
                                aria_label = star_elem.get_attribute('aria-label') or ''
                                match = re.search(r'(\d+)\s*つ星', aria_label)
                                if match:
                                    rating = int(match.group(1))
                                    break
                                match = re.search(r'(\d+)\s*star', aria_label, re.IGNORECASE)
                                if match:
                                    rating = int(match.group(1))
                                    break
                        except:
                            continue

                    # 投稿日時
                    date = "不明"
                    for sel in ['span.rsqaWe', '.DU9Pgb', 'span.dehysf']:
                        try:
                            date_elem = review.locator(sel).first
                            if date_elem.count() > 0:
                                date = date_elem.inner_text().strip()
                                if date:
                                    break
                        except:
                            continue

                    # 口コミテキスト
                    text = ""
                    for sel in ['span.wiI7pd', '.MyEned span', '.Jtu6Td span', 'div.MyEned']:
                        try:
                            text_elem = review.locator(sel).first
                            if text_elem.count() > 0:
                                text = text_elem.inner_text().strip()
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

                    if (idx + 1) % 10 == 0:
                        progress = min(75 + int((len(reviews_data) / target_count) * 20), 95)
                        self._update_progress(f"抽出中: {len(reviews_data)}/{target_count}件", progress)

                except Exception as e:
                    continue

            return reviews_data

        except Exception as e:
            self._update_progress(f"抽出エラー: {str(e)[:20]}", 95)
            return reviews_data

    def get_place_info(self, page: Page) -> Dict:
        """店舗情報を取得"""
        try:
            debug_title = page.title() or "タイトルなし"

            # 店舗名
            place_name = "不明"
            try:
                h1_elem = page.locator('h1').first
                if h1_elem.count() > 0:
                    place_name = h1_elem.inner_text().strip()
                if not place_name:
                    place_name = f"(h1空) {debug_title[:30]}"
            except:
                place_name = f"(エラー) {debug_title[:30]}"

            # 平均評価
            avg_rating = "不明"
            try:
                rating_elem = page.locator('div.F7nice span[aria-hidden="true"]').first
                if rating_elem.count() > 0:
                    avg_rating = rating_elem.inner_text()
            except:
                pass

            # レビュー数
            review_count = "不明"
            try:
                count_elem = page.locator('button[aria-label*="件のクチコミ"]').first
                if count_elem.count() > 0:
                    aria_label = count_elem.get_attribute('aria-label') or ''
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
        self._debug("SCRAPE_START", {"url": url[:100], "target_count": target_count})
        self._update_progress("Playwrightを起動中...", 5)

        with sync_playwright() as p:
            try:
                # ブラウザ起動
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                        '--disable-blink-features=AutomationControlled',
                        '--lang=ja-JP',
                    ]
                )
                self._debug("BROWSER_LAUNCHED", "chromium headless")

                # コンテキスト作成
                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    locale='ja-JP',
                    timezone_id='Asia/Tokyo',
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                )

                page = context.new_page()

                # playwright-stealthを適用
                stealth_sync(page)
                self._debug("STEALTH_APPLIED", "playwright-stealth enabled")

                self._update_progress("ブラウザ起動完了", 10)

                original_url = url

                # CID形式に変換
                if 'data=' in url and '!1s0x' in url:
                    url = self.convert_to_cid_url(url)
                    self._update_progress("CID形式に変換しました", 12)
                elif '/maps/place/' in url and '@' not in url and 'data=' not in url:
                    place_match = re.search(r'/maps/place/([^/?]+)', url)
                    if place_match:
                        place_query = urllib.parse.unquote(place_match.group(1).replace('+', ' '))
                        url = f"https://www.google.com/maps/search/{urllib.parse.quote(place_query)}?hl=ja"
                        self._update_progress(f"検索URLに変換: {place_query[:20]}", 14)

                if 'hl=' not in url:
                    separator = '&' if '?' in url else '?'
                    url = f"{url}{separator}hl=ja"

                self._debug("URL_FINAL", {"original": original_url[:60], "final": url[:80]})

                # ページアクセス
                self._update_progress("ページにアクセス中...", 15)
                self._debug("PAGE_LOAD_START", url[:80])
                page.goto(url, wait_until='networkidle', timeout=60000)
                page.wait_for_timeout(8000)
                self._debug("PAGE_LOAD_COMPLETE", "waited 8s")

                page_title = page.title() or "タイトルなし"
                current_url = page.url
                self._debug("PAGE_INFO", {"title": page_title[:50], "current_url": current_url[:100]})
                self._capture_page_state(page, "AFTER_LOAD")
                self._update_progress(f"タイトル: {page_title[:30]}", 16)

                # consent処理
                is_consent_page = 'consent' in current_url.lower()
                self._debug("CONSENT_CHECK", {"is_consent": is_consent_page})

                consent_clicked = False
                if is_consent_page or page.locator('form[action*="consent"]').count() > 0:
                    self._update_progress("同意ページ検出、処理中...", 17)
                    consent_selectors = [
                        'button[aria-label*="すべて同意"]',
                        'button[aria-label*="同意する"]',
                        'button[aria-label*="Accept all"]',
                        'form[action*="consent"] button',
                    ]
                    for sel in consent_selectors:
                        try:
                            btn = page.locator(sel).first
                            if btn.count() > 0 and btn.is_visible():
                                btn.click()
                                consent_clicked = True
                                self._update_progress("同意ボタンをクリック", 17)
                                page.wait_for_timeout(3000)
                                break
                        except:
                            continue

                self._debug("CONSENT_RESULT", {"clicked": consent_clicked})
                if consent_clicked:
                    page.wait_for_timeout(2000)
                    self._capture_page_state(page, "AFTER_CONSENT")

                    if 'consent' in page.url.lower():
                        self._debug("CONSENT_REDIRECT_NEEDED", "retrying URL")
                        page.goto(url, wait_until='networkidle', timeout=60000)
                        page.wait_for_timeout(8000)

                # 検索結果ページ処理
                is_cid_url = '?cid=' in url or '&cid=' in url
                is_search_page = '/maps/search/' in url
                store_found = is_cid_url

                self._debug("URL_TYPE_CHECK", {
                    "is_cid_url": is_cid_url,
                    "is_search_page": is_search_page,
                    "store_found": store_found
                })

                if is_search_page:
                    self._update_progress("検索結果から店舗を選択中...", 18)
                    try:
                        first_result = page.locator('a[href*="/maps/place/"]').first
                        if first_result.count() > 0:
                            first_result.click()
                            store_found = True
                            page.wait_for_timeout(8000)
                    except:
                        pass

                    if not store_found:
                        try:
                            results = page.locator('div.Nv2PK').first
                            if results.count() > 0:
                                results.click()
                                store_found = True
                                page.wait_for_timeout(8000)
                        except:
                            pass

                # 店舗情報取得
                self._capture_page_state(page, "BEFORE_PLACE_INFO")
                self._update_progress("店舗情報を取得中...", 20)
                self.get_place_info(page)
                self._debug("PLACE_INFO", self.place_info)
                self._update_progress(f"店舗: {self.place_info.get('name', '不明')[:20]}", 22)

                # 口コミタブをクリック
                self._update_progress("口コミタブを探しています...", 25)
                reviews_tab_found = False
                tab_selectors = [
                    'button[aria-label*="のクチコミ"]',
                    'button[aria-label*="クチコミ"]',
                    'button[data-tab-index="1"]',
                    'button.hh2c6',
                ]

                tab_debug = {}
                for sel in tab_selectors:
                    try:
                        tab_debug[sel[:30]] = page.locator(sel).count()
                    except:
                        tab_debug[sel[:30]] = "error"
                self._debug("TAB_SELECTORS_CHECK", tab_debug)

                for sel in tab_selectors:
                    try:
                        tab = page.locator(sel).first
                        if tab.count() > 0 and tab.is_visible():
                            tab.click()
                            page.wait_for_timeout(8000)
                            reviews_tab_found = True
                            self._debug("REVIEWS_TAB_FOUND", {"selector": sel, "success": True})
                            self._update_progress("口コミタブを開きました", 28)
                            break
                    except Exception as e:
                        self._debug(f"TAB_SELECTOR_FAIL_{sel[:20]}", str(e)[:50])
                        continue

                if not reviews_tab_found:
                    self._debug("REVIEWS_TAB_NOT_FOUND", "all selectors failed")
                    self._update_progress("口コミタブが見つかりません、直接探索", 28)

                self._capture_page_state(page, "AFTER_TAB_CLICK")

                # 並び順を「最新」に変更
                sort_changed = False
                try:
                    sort_btn = page.locator('button[data-value="Sort"]').first
                    if sort_btn.count() > 0 and sort_btn.is_visible():
                        sort_btn.click()
                        page.wait_for_timeout(2000)
                        newest = page.locator('div[role="menuitemradio"]:has-text("新しい順")').first
                        if newest.count() > 0:
                            newest.click()
                            sort_changed = True
                            page.wait_for_timeout(3000)
                except Exception as e:
                    self._debug("SORT_CHANGE_FAILED", str(e)[:50])
                self._debug("SORT_CHANGED", sort_changed)

                # 口コミ要素の確認
                page_content = page.content()
                review_keywords = ['data-review-id', 'jftiEf', 'wiI7pd', 'rsqaWe', 'クチコミ', 'review', '星']
                keyword_check = {}
                for kw in review_keywords:
                    keyword_check[kw] = page_content.count(kw)
                self._debug("PAGE_SOURCE_KEYWORDS", keyword_check)

                # HTMLサンプル取得
                if 'クチコミ' in page_content:
                    idx = page_content.find('クチコミ')
                    sample_start = max(0, idx - 200)
                    sample_end = min(len(page_content), idx + 500)
                    html_sample = page_content[sample_start:sample_end].replace('\n', ' ')
                    self._debug("HTML_AROUND_KUCHIKOMI", html_sample[:400])

                initial_count = page.locator('div[data-review-id], div.jftiEf.fontBodyMedium').count()
                self._debug("INITIAL_REVIEWS", {"count": initial_count})
                self._update_progress(f"初期口コミ数: {initial_count}件", 29)

                # スクロール
                self._debug("SCROLL_START", {"target": target_count})
                loaded_count = self.scroll_reviews(page, target_count)
                self._debug("SCROLL_RESULT", {"loaded": loaded_count})
                self._update_progress(f"スクロール後: {loaded_count}件発見", 72)

                if loaded_count == 0:
                    self._update_progress("スクロールなしで口コミを取得中...", 73)
                    self._capture_page_state(page, "SCROLL_ZERO_FALLBACK")
                    loaded_count = page.locator('div[data-review-id], div.jftiEf.fontBodyMedium').count()
                    self._debug("FALLBACK_REVIEW_COUNT", loaded_count)
                    if loaded_count == 0:
                        self._debug("NO_REVIEWS_FOUND", "returning empty")
                        self._update_progress("口コミが見つかりませんでした", 100)
                        browser.close()
                        return []

                # 口コミ抽出
                self._debug("EXTRACT_START", {"found_elements": loaded_count})
                self.reviews = self.extract_reviews(page, target_count, url)
                self._debug("EXTRACT_RESULT", {"extracted": len(self.reviews)})

                self._update_progress(f"完了: {len(self.reviews)}件取得", 100)

                browser.close()
                return self.reviews

            except Exception as e:
                import traceback
                self._debug("SCRAPE_EXCEPTION", {
                    "error": str(e),
                    "type": type(e).__name__,
                    "traceback": traceback.format_exc()[-500:]
                })
                self._update_progress(f"エラー: {str(e)[:30]}", 100)
                logger.exception("scrape_reviews failed")
                return []

    def scrape_by_search(self, query: str, target_count: int = 100) -> List[Dict]:
        """検索クエリから口コミを取得"""
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.google.com/maps/search/{encoded_query}"
        return self.scrape_reviews(url, target_count)
