"""通知済みの空き枠を last_state.json に記録し、差分だけを通知するための処理。"""

import json
import sys
from datetime import date
from pathlib import Path

STATE_FILE = Path(__file__).with_name("last_state.json")


def load(path=STATE_FILE):
    """前回通知した枠のキー集合を返す。ファイルが無ければ空集合。"""
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("notified", []))
    except (OSError, ValueError) as e:
        # 壊れていても通知は続けたいので、初回扱いにフォールバックする。
        print(f"  ! {path.name} を読めませんでした（初回扱いで続行）: {e}", file=sys.stderr)
        return set()


def save(keys, path=STATE_FILE):
    """通知済みキーを保存する。"""
    payload = {"updated_at": date.today().isoformat(), "notified": sorted(keys)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def diff(slots, known):
    """まだ通知していない枠だけを返す。"""
    return [s for s in slots if s.key not in known]


def prune(keys, today=None):
    """過ぎ去った日付のキーを捨てて state ファイルの肥大化を防ぐ。

    キーの形式は "施設名|YYYY-MM-DD|時" （check_availability.Slot.key）。
    """
    today = today or date.today()
    kept = set()
    for k in keys:
        parts = k.split("|")
        if len(parts) != 3:
            continue
        try:
            if date.fromisoformat(parts[1]) >= today:
                kept.add(k)
        except ValueError:
            continue
    return kept
