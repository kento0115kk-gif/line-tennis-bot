#!/usr/bin/env python3
"""都立公園（有明テニスの森公園・日比谷公園・木場公園・猿江恩賜公園）の
コート空き状況を取得してターミナルに表示する。

都立公園スポーツレクリエーション予約システムはサーバ側セッションで画面遷移を
管理しているため、空き状況URLを直接開くとエラーになる。よってトップページから
「空き状況検索」フォームを操作して結果ページへ遷移する。
"""

import argparse
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta

from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

TOP_URL = "https://kouen.sports.metro.tokyo.lg.jp/web/"

# 監視対象の公園・施設。
# (公園名, 表示名（施設名）, 種目コード, 公園コード, コート種別)
# 有明テニスの森公園は種目ごとに3施設に分かれて登録されている。
FACILITIES = [
    ("有明テニスの森公園", "有明テニスＡ屋外ハードコート", "1000_1020", "1350", "屋外ハード"),
    ("有明テニスの森公園", "有明テニスＢインドアコート", "1000_1020", "1370", "インドアハード"),
    ("有明テニスの森公園", "有明テニスＣ人工芝コート", "1000_1030", "1360", "人工芝"),
    ("日比谷公園", "日比谷公園テニスコート（人工芝）", "1000_1030", "1000", "人工芝"),
    ("木場公園", "木場公園テニスコート（人工芝）", "1000_1030", "1060", "人工芝"),
    ("猿江恩賜公園", "猿江恩賜公園テニスコート（人工芝）", "1000_1030", "1040", "人工芝"),
]

AVAILABLE = "空き"

# 時間帯ラベルは「１１時」のように全角数字で書かれている。
ZEN_TO_HAN = str.maketrans("０１２３４５６７８９", "0123456789")

# 1週分の取得を何回まで試みるか。
RETRIES = 3

# リトライ前に少し待つ（連続アクセスによるサーバ側の一時的な不調を避ける）。
RETRY_WAIT_SECONDS = 3


class Slot:
    """1コマ分の空き状況。"""

    def __init__(self, park_name, facility, court_type, day, time_label, status, count):
        self.park_name = park_name
        self.facility = facility
        self.court_type = court_type
        self.day = day
        self.time_label = time_label
        self.status = status
        self.count = count

    @property
    def is_available(self):
        return self.status == AVAILABLE

    @property
    def hour(self):
        """時刻ラベル（全角数字）を並べ替え用の数値にする。"""
        m = re.search(r"\d+", self.time_label.translate(ZEN_TO_HAN))
        return int(m.group()) if m else -1

    @property
    def key(self):
        """差分検知に使う一意キー。"""
        return f"{self.facility}|{self.day.isoformat()}|{self.hour}"

    @property
    def display_facility(self):
        """通知用の施設名。管理用のＡ/Ｂ/Ｃ記号を空白に置き換える。"""
        return re.sub(r"([Ａ-Ｚ])(?=[^\s])", " ", self.facility).strip()


# 結果ページには月表示(#month-info)と週表示(#week-info)の2つのカレンダーがあり、
# 実際に空き状況が入るのは週表示のほう。
WEEK_TABLE = "table#week-info"


def _calendar_table(page):
    """週表示のカレンダーテーブルを返す。"""
    table = page.query_selector(WEEK_TABLE)
    if table is not None and table.query_selector_all("tr"):
        return table
    return None


def _header_days(table):
    """ヘッダ行から各列の日（数字）を取り出す。"""
    rows = table.query_selector_all("tr")
    days = []
    for cell in rows[0].query_selector_all("th, td")[1:]:
        m = re.search(r"\d+", cell.inner_text() or "")
        days.append(int(m.group()) if m else None)
    return days


def _resolve_dates(start, header_days):
    """開始日と列インデックスから各列の日付を決める。

    検索結果は必ず指定した開始日から7日分が並ぶ。画面上のヘッダは「日」しか
    持たないため日付自体は開始日から計算し、ヘッダとの一致を検証に使う。
    食い違った列は推測せず None にして取りこぼしとして扱う。
    """
    dates = []
    for i, hday in enumerate(header_days):
        d = start + timedelta(days=i)
        if hday is not None and d.day != hday:
            print(
                f"  ! 列{i}の日付が想定と異なります（計算値 {d} / 画面 {hday}日）"
                "→ この列は読み飛ばします",
                file=sys.stderr,
            )
            d = None
        dates.append(d)
    return dates


def scrape_week(page, park_name, facility, court_type, start):
    """表示中の1週間分のカレンダーを Slot のリストにして返す。"""
    table = _calendar_table(page)
    if table is None:
        return []

    rows = table.query_selector_all("tr")
    dates = _resolve_dates(start, _header_days(table))

    slots = []
    for tr in rows[1:]:
        cells = tr.query_selector_all("th, td")
        if len(cells) < 2:
            continue
        time_label = (cells[0].inner_text() or "").strip()
        if not time_label:
            continue
        for i, cell in enumerate(cells[1:]):
            if i >= len(dates) or dates[i] is None:
                continue
            img = cell.query_selector("img.calendar-status")
            status = (img.get_attribute("alt") or "").strip() if img else ""
            if not status:
                continue
            span = cell.query_selector(".calendar-availability span")
            text = (span.inner_text() or "").strip() if span else ""
            count = int(text) if text.isdigit() else None
            slots.append(Slot(park_name, facility, court_type, dates[i], time_label, status, count))
    return slots


def search_week(page, purpose_code, park_code, start):
    """トップページの空き状況検索フォームを操作し、start から7日分を表示する。"""
    page.goto(TOP_URL, timeout=60000)
    page.wait_for_load_state("networkidle")

    page.fill("#daystart-home", start.isoformat())
    page.select_option("#purpose-home", purpose_code)
    # 種目を選ぶと公園リストが非同期に差し替わるため、対象が現れるまで待つ。
    # option は常に hidden 扱いなので visible ではなく attached を待つ。
    page.wait_for_selector(
        f"#bname-home option[value='{park_code}']", state="attached", timeout=15000
    )
    page.select_option("#bname-home", park_code)

    page.click("button:has-text('検索')")
    page.wait_for_load_state("networkidle", timeout=60000)
    page.wait_for_selector(f"{WEEK_TABLE} tr", timeout=30000)


def fetch_facility(browser, park_name, facility, court_type, purpose_code, park_code, start, weeks):
    """1施設について weeks 週分の空き状況を取得する。

    結果ページの「次週>>」は Ajax 更新だがプログラムからクリックしても発火
    しないため、週ごとに開始日を変えて検索し直す。

    週ごとに新しい page（＝新しいブラウザコンテキスト）を使う。予約サイトは
    サーバ側セッションで画面遷移を管理しており、セッションを使い回して長時間
    アクセスし続けると、まれにトップページ自体がファイルダウンロードとして
    返ってくることがある（Playwright は `Page.goto: Download is starting` で
    例外を送出する）。毎回セッションを作り直すことでこれを避け、万一失敗しても
    新しいセッションでリトライする。
    """
    slots = []
    for w in range(weeks):
        week_start = start + timedelta(days=7 * w)
        # サイトが時折応答しない・不安定なため、週単位でリトライする。
        for attempt in range(RETRIES):
            page = browser.new_page()
            page.set_default_timeout(30000)
            try:
                search_week(page, purpose_code, park_code, week_start)
                slots.extend(scrape_week(page, park_name, facility, court_type, week_start))
                break
            except PWError as e:
                if attempt == RETRIES - 1:
                    raise
                print(
                    f"  ! {week_start} の取得に失敗、再試行します"
                    f"（{attempt + 2}/{RETRIES}）: {e}",
                    file=sys.stderr,
                )
                time.sleep(RETRY_WAIT_SECONDS)
            finally:
                page.close()
    return slots


WEEKDAYS = "月火水木金土日"


def fmt_date(d):
    return f"{d.strftime('%Y-%m-%d')}({WEEKDAYS[d.weekday()]})"


def pad(text, width):
    """全角文字を2桁として数え、表示幅を揃える。"""
    w = sum(2 if unicodedata.east_asian_width(c) in "WFA" else 1 for c in text)
    return text + " " * max(0, width - w)


def report(slots, show_all):
    """取得結果をターミナルに表示する。"""
    target = slots if show_all else [s for s in slots if s.is_available]

    if not target:
        print("\n空きコートは見つかりませんでした。")
        return

    print()
    for d in sorted({s.day for s in target}):
        print(f"■ {fmt_date(d)}")
        rows = [s for s in target if s.day == d]
        for s in sorted(rows, key=lambda x: (x.facility, x.hour)):
            count = f"{s.count}面" if s.count is not None else "-"
            mark = "○" if s.is_available else "  "
            status = s.status if show_all else AVAILABLE
            print(f"   {mark} {pad(s.time_label, 8)}{pad(s.facility, 30)}{pad(status, 10)}{count}")
        print()

    available = [s for s in slots if s.is_available]
    total = sum(s.count for s in available if s.count is not None)
    print(f"── 空きコマ {len(available)} 件 / 合計 {total} 面 ──")


def parse_args():
    p = argparse.ArgumentParser(description="監視対象公園の空き状況を取得する")
    p.add_argument("--date", help="検索開始日 YYYY-MM-DD（既定: 今日）")
    p.add_argument("--weeks", type=int, default=2, help="取得する週数（既定: 2）")
    p.add_argument("--all", action="store_true", help="空き以外の状態も表示する")
    p.add_argument("--headed", action="store_true", help="ブラウザを表示して実行する")
    return p.parse_args()


def collect_slots(start, weeks, headed=False, verbose=True):
    """全施設 × weeks 週分の Slot を集めて返す。

    通知側（main.py）からも呼べるよう、ブラウザの起動と後始末をここに閉じる。
    """
    slots = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        try:
            for park_name, name, purpose, park, court_type in FACILITIES:
                if verbose:
                    # 進捗は stderr へ。stdout は結果（JSON など）専用にしておく。
                    print(f"取得中: {park_name} / {name} ...", file=sys.stderr, flush=True)
                try:
                    slots.extend(
                        fetch_facility(browser, park_name, name, court_type, purpose, park, start, weeks)
                    )
                except PWError as e:
                    # 1施設が取れなくても残りは続行する。
                    print(f"  ! {park_name} / {name} の取得に失敗しました: {e}", file=sys.stderr)
        finally:
            browser.close()
    return slots


def main():
    args = parse_args()
    start = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()

    parks = ", ".join(sorted({p for p, *_ in FACILITIES}))
    print(f"{parks} 空き状況（{start} から {args.weeks} 週間）")
    slots = collect_slots(start, args.weeks, headed=args.headed)
    report(slots, args.all)


if __name__ == "__main__":
    main()
