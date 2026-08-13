"""有明（江東区）の時間別天気を Open-Meteo から取得する。

Open-Meteo は API キー不要・商用利用可の無料 API で、16日先までの
時間別予報を返す。Yahoo!天気は時間別予報の公開 API がないため採用しなかった。
"""

import sys
from datetime import datetime

import requests

# 有明テニスの森公園の座標
LATITUDE = 35.6355
LONGITUDE = 139.7939

API_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather code -> (絵文字, 日本語)
# https://open-meteo.com/en/docs
WMO = {
    0: ("☀️", "快晴"),
    1: ("🌤", "晴れ"),
    2: ("⛅️", "薄ぐもり"),
    3: ("☁️", "くもり"),
    45: ("🌫", "霧"),
    48: ("🌫", "霧"),
    51: ("🌦", "霧雨"),
    53: ("🌦", "霧雨"),
    55: ("🌦", "霧雨"),
    56: ("🌧", "着氷性の霧雨"),
    57: ("🌧", "着氷性の霧雨"),
    61: ("🌦", "小雨"),
    63: ("🌧", "雨"),
    65: ("🌧", "強い雨"),
    66: ("🌧", "着氷性の雨"),
    67: ("🌧", "着氷性の雨"),
    71: ("🌨", "小雪"),
    73: ("🌨", "雪"),
    75: ("❄️", "大雪"),
    77: ("🌨", "霧雪"),
    80: ("🌦", "にわか雨"),
    81: ("🌧", "にわか雨"),
    82: ("⛈", "激しいにわか雨"),
    85: ("🌨", "にわか雪"),
    86: ("❄️", "にわか雪"),
    95: ("⛈", "雷雨"),
    96: ("⛈", "雷雨（雹）"),
    99: ("⛈", "雷雨（雹）"),
}

UNKNOWN = ("❓", "不明")


class Weather:
    """ある1時間の天気。"""

    def __init__(self, code, temperature, pop):
        self.code = code
        self.temperature = temperature
        self.pop = pop  # 降水確率(%)

    @property
    def icon(self):
        return WMO.get(self.code, UNKNOWN)[0]

    @property
    def description(self):
        return WMO.get(self.code, UNKNOWN)[1]

    def summary(self):
        """「🌤 晴れ 28℃ / 降水20%」形式の1行（ターミナル表示用）。"""
        parts = [f"{self.icon} {self.description}"]
        if self.temperature is not None:
            parts.append(f"{round(self.temperature)}℃")
        if self.pop is not None:
            parts.append(f"降水{self.pop}%")
        return " / ".join(parts)

    def card_text(self):
        """「☁️ くもり 20℃」形式の1行（通知カード用）。"""
        text = f"{self.icon} {self.description}"
        if self.temperature is not None:
            text += f" {round(self.temperature)}℃"
        return text


def fetch_hourly(timeout=20):
    """時間別予報を {datetime: Weather} で返す。失敗時は空 dict。

    予報が取れなくても空き通知自体は送りたいので、例外は投げず握りつぶす。
    """
    try:
        res = requests.get(
            API_URL,
            params={
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "hourly": "temperature_2m,weather_code,precipitation_probability",
                "timezone": "Asia/Tokyo",
                "forecast_days": 16,
            },
            timeout=timeout,
        )
        res.raise_for_status()
        hourly = res.json()["hourly"]
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"  ! 天気の取得に失敗しました（天気なしで続行）: {e}", file=sys.stderr)
        return {}

    out = {}
    for i, stamp in enumerate(hourly["time"]):
        when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M")
        out[when] = Weather(
            hourly["weather_code"][i],
            hourly["temperature_2m"][i],
            hourly["precipitation_probability"][i],
        )
    return out


def for_slot(forecast, day, hour):
    """指定の日付・時刻に対応する Weather を返す（予報範囲外なら None）。"""
    return forecast.get(datetime(day.year, day.month, day.day, hour))
