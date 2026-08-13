#!/usr/bin/env python3
"""有明テニスの森公園の空きコートを監視し、新しい枠が出たら LINE に通知する。

  1. 夜間（既定 23:00〜7:00）は何もせず終了する
  2. 空き状況をスクレイピングする
  3. last_state.json と突き合わせて、まだ通知していない枠だけ抽出する
  4. 各枠の天気を Open-Meteo から取得する
  5. Flex Message（カード型）にまとめて LINE に送る
  6. 通知済みキーを保存する
"""

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path

import jpholiday
from dotenv import load_dotenv

import notifier
import state
import weather
from check_availability import collect_slots

# launchd や cron から起動されるとカレントディレクトリが異なるため、
# .env はこのファイルからの相対位置で明示的に読み込む。
load_dotenv(Path(__file__).with_name(".env"))


def _env_int(name, default):
    raw = os.environ.get(name, "")
    try:
        return int(raw)
    except ValueError:
        return default


# 夜間停止の既定値。.env の QUIET_START / QUIET_END で上書きできる。
QUIET_START = _env_int("QUIET_START", 23)
QUIET_END = _env_int("QUIET_END", 7)

# 平日に通知する下限時刻。土日祝は終日が対象。
WEEKDAY_FROM_HOUR = _env_int("WEEKDAY_FROM_HOUR", 19)


def is_target(slot, from_hour=None):
    """通知対象の枠か判定する。

    土日祝は全時間帯、平日は from_hour 以降（既定 19時〜）のみ。
    """
    from_hour = WEEKDAY_FROM_HOUR if from_hour is None else from_hour
    if slot.day.weekday() >= 5 or jpholiday.is_holiday(slot.day):
        return True
    return slot.hour >= from_hour


def in_quiet_hours(now, start=QUIET_START, end=QUIET_END):
    """通知を止める時間帯かどうか。日付をまたぐ範囲（23→7）に対応する。"""
    h = now.hour
    if start == end:
        return False
    if start < end:
        return start <= h < end
    return h >= start or h < end


def parse_args():
    p = argparse.ArgumentParser(description="空きコートを LINE に通知する")
    p.add_argument("--weeks", type=int, default=2, help="監視する週数（既定: 2）")
    p.add_argument("--date", help="監視開始日 YYYY-MM-DD（既定: 今日）")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="LINE に送信せず Flex JSON を表示する（state も更新しない）",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="夜間停止と差分チェックを無視して、見つかった空きを全て通知する",
    )
    p.add_argument(
        "--all-slots",
        action="store_true",
        help="土日祝・平日夜のフィルタを外し、全ての空き枠を通知対象にする",
    )
    p.add_argument("--headed", action="store_true", help="ブラウザを表示して実行する")
    return p.parse_args()


def main():
    args = parse_args()
    now = datetime.now()

    if in_quiet_hours(now) and not args.force:
        print(f"夜間（{QUIET_START}:00〜{QUIET_END}:00）のため通知をスキップします。", file=sys.stderr)
        return 0

    start = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    print(f"空き状況を確認中（{start} から {args.weeks} 週間）...", file=sys.stderr)

    found = [s for s in collect_slots(start, args.weeks, headed=args.headed) if s.is_available]
    slots = found if args.all_slots else [s for s in found if is_target(s)]
    print(
        f"空き枠: {len(found)} 件 → 通知対象: {len(slots)} 件"
        f"（土日祝は終日 / 平日は{WEEKDAY_FROM_HOUR}時以降）",
        file=sys.stderr,
    )

    known = state.load()
    targets = slots if args.force else state.diff(slots, known)
    if not targets:
        print("新しい空き枠はありません。通知しません。", file=sys.stderr)
        # 埋まった枠のキーを落として、再び空いたら通知できるようにする。
        if not args.dry_run:
            state.save(state.prune({s.key for s in slots}))
        return 0

    print(f"新規: {len(targets)} 件 → 通知します", file=sys.stderr)
    targets.sort(key=lambda s: (s.day, s.hour, s.facility))

    forecast = weather.fetch_hourly()
    message = notifier.build_message(targets, lambda s: weather.for_slot(forecast, s.day, s.hour))

    if args.dry_run:
        notifier.dump(message)
        print(f"\n[dry-run] 送信しませんでした（{len(targets)}件）", file=sys.stderr)
        return 0

    if not notifier.send(message):
        # 送信できなかった枠は未通知のまま残し、次回に再挑戦させる。
        print("送信に失敗したため state を更新しません。", file=sys.stderr)
        return 1

    # 「現在空いている対象枠」だけを保存する。既知キーを足し込むと、
    # 一度埋まった枠が再び空いたときに通知できなくなる。
    state.save(state.prune({s.key for s in slots}))
    print(f"通知しました（{len(targets)}件）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
