#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国交省・不動産情報ライブラリ API（XIT001 不動産取引価格情報）から、
23区の「実取引ベースの相場・町名別プレミアム・価格トレンド(値上がり率)」を集計して
data/market_real.json に出力する。fetch_listings.py がこれを読み込んで採点に使う。

※ APIキーは環境変数 REINFOLIB_API_KEY から取得（リポジトリには絶対に保存しない）。
※ 出力 market_real.json は派生統計のみでキーを含まない＝コミット可。
※ 取引データは四半期更新なので、このスクリプトは日次ではなく時々（月1など）実行すればよい。
"""
import os
import sys
import json
import gzip
import time
import statistics
import datetime
import urllib.request
import urllib.parse
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

WARDS = ["千代田区", "中央区", "港区", "新宿区", "文京区", "台東区", "墨田区", "江東区",
         "品川区", "目黒区", "大田区", "世田谷区", "渋谷区", "中野区", "杉並区", "豊島区",
         "北区", "荒川区", "板橋区", "練馬区", "足立区", "葛飾区", "江戸川区"]
WARD_CODES = [str(c) for c in range(13101, 13124)]

API = "https://www.reinfolib.mlit.go.jp/ex-api/external/XIT001"
# 水準・町名プレミアム用の直近年（サンプルを厚く）＋ トレンド用の過年度
RECENT_YEARS = [2023, 2024]
TREND_YEARS = [2014, 2019, 2024]
ALL_YEARS = sorted(set(RECENT_YEARS + TREND_YEARS))
TOBU = 3.305785  # 1坪 = 3.305785㎡


def api_key():
    k = os.environ.get("REINFOLIB_API_KEY", "").strip()
    if not k:
        sys.exit("ERROR: 環境変数 REINFOLIB_API_KEY が未設定です（APIキーを設定して再実行）")
    return k


def fetch(year, city, key, retries=4):
    url = API + "?" + urllib.parse.urlencode({"year": year, "area": "13", "city": city})
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"Ocp-Apim-Subscription-Key": key, "Accept-Encoding": "gzip"})
            raw = urllib.request.urlopen(req, timeout=40).read()
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
            return json.loads(raw).get("data", [])
        except Exception as e:
            if i == retries - 1:
                print(f"  WARN {city} {year}: {e}", file=sys.stderr)
                return []
            time.sleep(2 ** i)
    return []


def ms_unit(x):
    """中古マンション等の㎡単価（万円/㎡）。異常値は除外。"""
    if x.get("Type") != "中古マンション等":
        return None
    try:
        tp = int(x["TradePrice"]); ar = float(x["Area"])
    except (ValueError, KeyError, TypeError):
        return None
    if ar < 15 or tp <= 0:
        return None
    u = tp / ar / 10000
    return u if 10 <= u <= 600 else None


def land_unit(x):
    """宅地(土地)の坪単価（万円/坪）。"""
    if x.get("Type") != "宅地(土地)":
        return None
    try:
        tp = int(x["TradePrice"]); ar = float(x["Area"])
    except (ValueError, KeyError, TypeError):
        return None
    if ar < 20 or tp <= 0:
        return None
    u = tp * TOBU / ar / 10000
    return u if 30 <= u <= 3000 else None


def med(xs):
    return round(statistics.median(xs), 1) if xs else None


def cagr(old, new, years):
    if not old or not new or old <= 0 or years <= 0:
        return None
    return round(((new / old) ** (1 / years) - 1) * 100, 1)


def main():
    key = api_key()
    out = {"updated": datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=9))).isoformat(), "wards": {}}
    for ward, code in zip(WARDS, WARD_CODES):
        by_year = {}
        for y in ALL_YEARS:
            by_year[y] = fetch(y, code, key)
            time.sleep(0.5)
        # 水準・町名（直近年を合算）
        recent = [x for y in RECENT_YEARS for x in by_year.get(y, [])]
        ms_all = [u for x in recent if (u := ms_unit(x)) is not None]
        land_all = [u for x in recent if (u := land_unit(x)) is not None]
        ward_ms = med(ms_all)
        # 町名別プレミアム（マンション、n>=8 のみ。区中央値に対する倍率）＋実成約レンジ(p25/中央/p75)
        dist = {}
        dist_range = {}
        if ward_ms:
            buckets = {}
            for x in recent:
                u = ms_unit(x)
                if u is None:
                    continue
                buckets.setdefault(x.get("DistrictName", ""), []).append(u)
            for d, vs in buckets.items():
                if d and len(vs) >= 8:
                    dist[d] = round(statistics.median(vs) / ward_ms, 3)
                    q = statistics.quantiles(vs, n=4) if len(vs) >= 4 else [min(vs), statistics.median(vs), max(vs)]
                    dist_range[d] = {"p25": round(q[0]), "p50": round(statistics.median(vs)),
                                     "p75": round(q[2]), "n": len(vs)}
        # トレンド（マンション㎡単価のCAGR：最古→2024）
        def ms_med_of(y):
            return med([u for x in by_year.get(y, []) if (u := ms_unit(x)) is not None])
        base_y = next((y for y in TREND_YEARS if ms_med_of(y)), None)
        cg = cagr(ms_med_of(base_y), ms_med_of(2024), 2024 - base_y) if base_y else None
        out["wards"][ward] = {
            "ms_m2_txn": ward_ms, "land_tsubo_txn": med(land_all),
            "n_ms": len(ms_all), "n_land": len(land_all),
            "cagr_ms": cg, "cagr_from": base_y,
            "districts_ms": dist, "districts_ms_range": dist_range,
        }
        print(f"{ward}: ㎡{ward_ms}(n{len(ms_all)}) 坪{med(land_all)}(n{len(land_all)}) "
              f"CAGR{cg}%({base_y}→) 町名{len(dist)}")
    (DATA / "market_real.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote data/market_real.json ({len(out['wards'])} wards)")


if __name__ == "__main__":
    main()
