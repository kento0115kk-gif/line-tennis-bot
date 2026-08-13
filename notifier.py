"""空き枠を LINE の Flex Message（カード型）で通知する。"""

import json
import os
import sys

import requests

from check_availability import PARK_NAME

PUSH_URL = "https://api.line.me/v2/bot/message/push"
BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"

# 予約サイト（トップ）。空き状況ページは直リンクするとエラーになるためトップを開く。
RESERVE_URL = "https://kouen.sports.metro.tokyo.lg.jp/web/"

LINE_GREEN = "#06C755"
HEADER_BG = "#EAF9F0"  # ヘッダーの淡い緑
DARK = "#111111"
GRAY = "#8C8C8C"

# Flex のカルーセルは最大12枚。
MAX_BUBBLES = 12

WEEKDAYS = "月火水木金土日"


def _time_range(hour):
    """開始時刻から「9:00 - 11:00」形式の2時間枠を作る。"""
    return f"{hour}:00 - {hour + 2}:00"


def _date_label(day):
    return f"{day.month}/{day.day}({WEEKDAYS[day.weekday()]})"


def _row(icon, label, value):
    """「📅 日付   4/6(月)」の1行。ラベルは灰色、値は太字。

    値が長いと折り返すため、wrap が確実に効く horizontal を使う。
    """
    return {
        "type": "box",
        "layout": "horizontal",
        "spacing": "sm",
        "contents": [
            {"type": "text", "text": f"{icon} {label}", "size": "sm", "color": GRAY, "flex": 3},
            {
                "type": "text",
                "text": value,
                "size": "sm",
                "color": DARK,
                "weight": "bold",
                "flex": 5,
                "wrap": True,
            },
        ],
    }


def build_bubble(slot, weather):
    """空き枠1件分のカードを組み立てる。"""
    body = [
        {"type": "text", "text": PARK_NAME, "size": "lg", "weight": "bold", "wrap": True},
        {"type": "separator", "margin": "lg"},
        {
            "type": "box",
            "layout": "vertical",
            "margin": "lg",
            "spacing": "md",
            "contents": [
                _row("📅", "日付", _date_label(slot.day)),
                _row("⏰", "時間", _time_range(slot.hour)),
                _row("🎪", "コート", slot.court_type),
                _row("📍", "施設", slot.display_facility),
                _row("✨", "空き", f"{slot.count}面" if slot.count is not None else "空きあり"),
                _row("🌤", "天気", weather.card_text() if weather else "予報なし"),
            ],
        },
    ]

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": HEADER_BG,
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "text",
                    "text": "🎾 空きコート発見！",
                    "color": LINE_GREEN,
                    "weight": "bold",
                    "size": "xl",
                }
            ],
        },
        "body": {"type": "box", "layout": "vertical", "contents": body},
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "button",
                            "style": "primary",
                            "color": LINE_GREEN,
                            "height": "sm",
                            "action": {
                                "type": "postback",
                                "label": "参加する",
                                "data": f"action=join&slot={slot.key}",
                                "displayText": f"{_date_label(slot.day)} {_time_range(slot.hour)} 参加します",
                            },
                        },
                        {
                            "type": "button",
                            "style": "secondary",
                            "height": "sm",
                            "action": {
                                "type": "postback",
                                "label": "パス",
                                "data": f"action=pass&slot={slot.key}",
                                "displayText": f"{_date_label(slot.day)} {_time_range(slot.hour)} パスします",
                            },
                        },
                    ],
                },
                {
                    "type": "button",
                    "style": "link",
                    "height": "sm",
                    "action": {"type": "uri", "label": "予約サイトを開く", "uri": RESERVE_URL},
                },
            ],
        },
    }


def build_message(slots, forecast_lookup):
    """空き枠リストから Flex Message を1通組み立てる。

    forecast_lookup は slot を受け取って Weather か None を返す呼び出し可能オブジェクト。
    """
    shown = slots[:MAX_BUBBLES]
    bubbles = [build_bubble(s, forecast_lookup(s)) for s in shown]

    alt = f"空きコート {len(slots)}件（{_date_label(shown[0].day)} ほか）"
    if len(slots) > MAX_BUBBLES:
        alt += f" ※先頭{MAX_BUBBLES}件を表示"

    return {
        "type": "flex",
        "altText": alt[:400],
        "contents": {"type": "carousel", "contents": bubbles},
    }


def send(message, token=None, to=None, timeout=20):
    """Flex Message を送信する。

    LINE_TO が設定されていれば push、無ければ friends 全員に broadcast する。
    成功したら True を返す。
    """
    token = token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    to = to if to is not None else os.environ.get("LINE_TO", "")

    if not token:
        print("  ! LINE_CHANNEL_ACCESS_TOKEN が未設定のため送信できません", file=sys.stderr)
        return False

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if to:
        url, payload = PUSH_URL, {"to": to, "messages": [message]}
    else:
        url, payload = BROADCAST_URL, {"messages": [message]}

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as e:
        print(f"  ! LINE への送信に失敗しました: {e}", file=sys.stderr)
        return False

    if res.status_code != 200:
        # LINE はエラー内容を JSON で返すので、そのまま出して原因を追えるようにする。
        print(f"  ! LINE API エラー {res.status_code}: {res.text[:300]}", file=sys.stderr)
        return False
    return True


def dump(message):
    """送信せず Flex JSON を標準出力に書き出す（動作確認用）。"""
    print(json.dumps(message, ensure_ascii=False, indent=2))
