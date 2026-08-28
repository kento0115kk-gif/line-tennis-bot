# line-tennis-bot

有明テニスの森公園・日比谷公園・木場公園・猿江恩賜公園のテニスコートの空きを監視し、
空きが出たら LINE に通知する bot。

[都立公園スポーツレクリエーション予約システム](https://kouen.sports.metro.tokyo.lg.jp/web/)を
Playwright で操作して空き状況を取得し、天気を添えて LINE の Flex Message で送る。

## 通知条件

- **土日・祝日**: 全時間帯
- **平日**: 19時以降のみ（`WEEKDAY_FROM_HOUR` で変更可）
- 23:00〜7:00 は通知しない（`QUIET_START` / `QUIET_END`）
- 一度通知した枠は `last_state.json` に記録し、重複通知しない

## 対象施設

有明テニスの森公園は予約システム上3つの施設に分かれている。それ以外の公園は
1公園1施設（人工芝）。

| 公園 | 施設 | 種目 |
| --- | --- | --- |
| 有明テニスの森公園 | 有明テニスＡ屋外ハードコート | テニス（ハード） |
| 有明テニスの森公園 | 有明テニスＢインドアコート | テニス（ハード） |
| 有明テニスの森公園 | 有明テニスＣ人工芝コート | テニス（人工芝） |
| 日比谷公園 | 日比谷公園テニスコート（人工芝） | テニス（人工芝） |
| 木場公園 | 木場公園テニスコート（人工芝） | テニス（人工芝） |
| 猿江恩賜公園 | 猿江恩賜公園テニスコート（人工芝） | テニス（人工芝） |

天気は公園ごとに座標が異なるため、通知カードには各公園の座標に基づく予報を表示する
（`weather.PARK_COORDS`）。監視対象を増やす場合は `check_availability.FACILITIES` に
`(公園名, 施設名, 種目コード, 公園コード, コート種別)` を追加し、`weather.PARK_COORDS`
にも座標を追加する。

## 構成

| ファイル | 役割 |
| --- | --- |
| `main.py` | 全体の制御（夜間停止 → 取得 → 絞り込み → 差分 → 天気 → 送信） |
| `check_availability.py` | 空き状況のスクレイピング。単体でも実行可能 |
| `weather.py` | Open-Meteo から有明の時間別天気を取得 |
| `notifier.py` | Flex Message の組み立てと LINE 送信 |
| `state.py` | `last_state.json` による差分検知 |

## セットアップ（ローカル）

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium

cp .env.example .env   # LINE のトークンなどを記入
```

## 使い方

```bash
# 空き状況をターミナルに表示するだけ
.venv/bin/python check_availability.py --weeks 2

# 送信せずに Flex Message の中身を確認
.venv/bin/python main.py --dry-run

# 実際に通知する
.venv/bin/python main.py
```

主なオプション:

| オプション | 説明 |
| --- | --- |
| `--weeks N` | 何週間先まで調べるか（既定 2） |
| `--date YYYY-MM-DD` | 検索開始日（既定 今日） |
| `--dry-run` | 送信せず Flex JSON を標準出力に表示 |
| `--force` | 夜間停止と差分チェックを無視して送信 |
| `--all-slots` | 土日祝／平日夜のフィルタを外す |

## 自動実行

GitHub Actions（`.github/workflows/notify.yml`）で15分おきに実行する。

リポジトリの Secrets に以下を登録する:

- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_TO`

`last_state.json` は実行ごとにリポジトリへコミットして状態を引き継ぐ。

> **注意**: ワークフローには `TZ: Asia/Tokyo` が必須。GitHub Actions の既定は UTC のため、
> これがないと夜間停止の時間帯が9時間ずれる。

## 補足

- 予約システムは画面遷移をサーバ側セッションで管理しているため、空き状況の URL を
  直接開くとエラーになる。必ずトップページの検索フォームから遷移する必要がある。
- 結果ページの「次週>>」は Ajax だがプログラムからは発火しないため、週ごとに
  開始日を変えて検索し直している。
- 同じセッション（ブラウザページ）を使い回して長時間アクセスし続けると、まれに
  トップページ自体がファイルダウンロードとして返ってくることがある
  （Playwright は `Page.goto: Download is starting` で例外を送出する）。
  これを避けるため、週ごとの検索は毎回新しいブラウザコンテキスト（新しい
  セッション）で行い、失敗時は数秒待ってから新しいセッションでリトライする
  （`check_availability.fetch_facility` / `RETRIES` / `RETRY_WAIT_SECONDS`）。
  1施設のリトライが尽きても他の施設の取得は続行する。
- カードの「参加する」「パス」ボタンは postback アクション。反応させるには
  Webhook サーバーが別途必要（未実装）。
