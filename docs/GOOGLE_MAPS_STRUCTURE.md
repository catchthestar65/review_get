# Google Maps スクレイピング技術ドキュメント

最終更新: 2025-12-12

## 1. URL形式と表示モード

### 1.1 問題の発見

Google Mapsは**URLのパラメータによって異なるページモードを表示**します。

| URL形式 | 表示モード | クチコミタブ | 備考 |
|---------|-----------|-------------|------|
| 通常のplace URL + `entry=ttu&g_ep=...` | 簡易版 | ❌ なし | 共有リンクなど |
| CID形式 `?cid=XXXXX` | 完全版 | ✅ あり | **推奨** |
| 検索URL `/maps/search/店舗名` | 完全版 | ✅ あり | 検索結果から開く |
| place URL (entry/g_ep削除) | 完全版 | ✅ あり | パラメータ削除 |

### 1.2 簡易版の特徴
- タブが「概要」「基本情報」の2つのみ
- クチコミタブが存在しない
- 口コミ要素 (`div[data-review-id]`) が0件
- 評価は表示されるが件数が表示されない

### 1.3 完全版の特徴
- タブが「概要」「クチコミ」「基本情報」の3つ
- 口コミが表示される
- 評価と件数が表示される (例: 4.7 (4,286))

## 2. URL構造の解析

### 2.1 典型的なGoogle Maps URL

```
https://www.google.com/maps/place/店舗名/@緯度,経度,ズーム/data=エンコードデータ?entry=ttu&g_ep=パラメータ
```

### 2.2 data=パラメータの構造

`data=` パラメータには以下の情報がエンコードされています：

```
!4m6!3m5!1s{CID}!8m2!3d{緯度}!4d{経度}!16s{Place_ID}
```

- **CID**: `!1s0x60188b07360bc5cd:0xc7555f7221569dd6` 形式
- **Place ID**: `!16s%2Fg%2F11f7srztfr` → `/g/11f7srztfr`
- **座標**: `!3d35.6445882!4d139.7487278`

### 2.3 CIDの変換

CIDは16進数形式で格納されています：
```
0x60188b07360bc5cd:0xc7555f7221569dd6
```

後半部分 (`0xc7555f7221569dd6`) を10進数に変換：
```python
cid_decimal = int("c7555f7221569dd6", 16)
# → 14363491530358300118
```

### 2.4 推奨URL形式

**CID形式（最も確実）:**
```
https://www.google.com/maps?cid={CID_10進数}&hl=ja
```

例:
```
https://www.google.com/maps?cid=14363491530358300118&hl=ja
```

## 3. HTML要素のセレクタ

### 3.1 タブ関連

| 要素 | セレクタ | 備考 |
|------|---------|------|
| タブリスト | `[role="tablist"]` | タブのコンテナ |
| 概要タブ | `button[aria-label*="の概要"]` | |
| クチコミタブ | `button[aria-label*="のクチコミ"]` | **重要** |
| 基本情報タブ | `button[aria-label*="について"]` | |
| タブ共通 | `button.hh2c6` | クラスベース |
| タブインデックス | `button[data-tab-index="1"]` | クチコミは通常1 |

### 3.2 口コミ要素

| 要素 | セレクタ | 備考 |
|------|---------|------|
| 口コミコンテナ | `div[data-review-id]` | **最も確実** |
| 口コミコンテナ(代替) | `div.jftiEf.fontBodyMedium` | |
| 投稿者名 | `.WNxzHc.qLhwHc` または `.d4r55` | |
| 評価(星) | `span.kvMYJc` | aria-labelに「星N つ」 |
| 投稿日時 | `span.rsqaWe` | |
| 口コミテキスト | `span.wiI7pd` | |
| 「もっと見る」 | `button.w8nwRe.kyuRq` | テキスト展開用 |

### 3.3 店舗情報

| 要素 | セレクタ | 備考 |
|------|---------|------|
| 店舗名 | `h1` | ページ内の最初のh1 |
| 評価エリア | `div.F7nice` | 評価と件数を含む |
| 評価(数値) | `span.ceNzKf` または `span[role="img"]` | aria-labelに「N つ星」 |
| 口コミ件数 | `div.F7nice span` | 括弧内の数字 |

### 3.4 スクロールエリア

| 要素 | セレクタ | 備考 |
|------|---------|------|
| メインスクロール | `div.m6QErb.DxyBCb.kA9KIf.dS8AEf.XiKgde` | 最も具体的 |
| スクロール(代替1) | `div.m6QErb.XiKgde` | |
| スクロール(代替2) | `div.m6QErb.DxyBCb` | |
| スクロール(汎用) | `div.m6QErb` | |

## 4. スクレイピングのベストプラクティス

### 4.1 URL変換

```python
def convert_to_cid_url(url: str) -> str:
    """URLをCID形式に変換"""
    import re

    # CIDを抽出 (0x....:0x....)
    cid_match = re.search(r'!1s(0x[0-9a-f]+:0x[0-9a-f]+)', url)
    if cid_match:
        cid_hex = cid_match.group(1)
        # 後半の16進数を10進数に変換
        hex_part = cid_hex.split(':')[1]
        cid_decimal = int(hex_part[2:], 16)  # '0x'を除去
        return f"https://www.google.com/maps?cid={cid_decimal}&hl=ja"

    return url  # 変換できない場合は元のURLを返す
```

### 4.2 口コミタブのクリック

```python
def click_reviews_tab(driver):
    """口コミタブをクリック"""
    selectors = [
        'button[aria-label*="のクチコミ"]',
        'button[data-tab-index="1"]',
        'button.hh2c6',
    ]

    for sel in selectors:
        try:
            tabs = driver.find_elements(By.CSS_SELECTOR, sel)
            for tab in tabs:
                aria = tab.get_attribute('aria-label') or ''
                if 'クチコミ' in aria and tab.is_displayed():
                    driver.execute_script("arguments[0].click();", tab)
                    return True
        except:
            pass
    return False
```

### 4.3 スクロールによる口コミ読み込み

```python
def scroll_reviews(driver, target_count):
    """口コミをスクロールして読み込む"""
    scroll_area = driver.find_element(
        By.CSS_SELECTOR,
        'div.m6QErb.DxyBCb.kA9KIf.dS8AEf.XiKgde'
    )

    for _ in range(max_attempts):
        # scrollTo で最下部へ
        driver.execute_script(
            "arguments[0].scrollTo(0, arguments[0].scrollHeight);",
            scroll_area
        )
        time.sleep(2)

        # scrollBy で追加スクロール
        for _ in range(5):
            driver.execute_script(
                "arguments[0].scrollBy(0, 800);",
                scroll_area
            )
            time.sleep(0.5)

        reviews = driver.find_elements(
            By.CSS_SELECTOR,
            'div[data-review-id]'
        )
        if len(reviews) >= target_count:
            break
```

## 5. 注意事項

### 5.1 Bot検出対策

Google MapsはBot検出を行っており、以下の対策が必要：

1. **WebDriver検出回避**
```python
chrome_options.add_argument('--disable-blink-features=AutomationControlled')
chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])

driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
    'source': 'Object.defineProperty(navigator, "webdriver", { get: () => undefined });'
})
```

2. **適切なUser-Agent**
```python
chrome_options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
```

3. **日本語設定**
```python
chrome_options.add_argument('--lang=ja-JP')
url += '&hl=ja'
```

### 5.2 レート制限

- 連続リクエスト間に20秒以上の間隔を空ける
- 1セッションでの取得数を制限する

### 5.3 セレクタの変更

Google MapsのHTML構造は頻繁に変更されます。セレクタが動作しない場合は、複数の代替セレクタを試すか、最新の構造を確認してください。

## 6. 更新履歴

| 日付 | 内容 |
|------|------|
| 2025-12-12 | 初版作成。CID形式URL、簡易版/完全版の違いを発見・文書化 |
