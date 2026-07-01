#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ウォッチ（住みたいエリア・気になるマンション）の“新着最速検知”用の軽量チェック。
全23区の重い日次スクレイプとは別に、対象区だけを高頻度(日中2時間毎)で見て、
前回まで未観測の物件のうちウォッチ該当（エリア/建物一致・予算内）を data/watch_alerts.json に追記する。
ページは client 側でこの JSON を読み『🔔 ウォッチ新着（直近）』として表示する。

※レインズ/未公開などの一次情報は取得できない（業者専用DB・公開APIなし）。本ジョブは
  “SUUMO掲載の最速察知”に特化。APIキー不要。
"""
import json
import time
import datetime
import urllib.parse
import fetch_listings as fl   # 同ディレクトリ。関数・定数を再利用

DATA = fl.DATA
JST = datetime.timezone(datetime.timedelta(hours=9))


def watch_of(r):
    """物件がウォッチ（エリア/建物）に該当すればラベルを返す。"""
    for a in fl.WATCHLIST.get("areas", []):
        m = a.get("match")
        toks = m if isinstance(m, list) else ([m] if m else [])
        if any(t and t in r["loc"] for t in toks):
            return a.get("label") or (toks[0] if toks else ""), "area"
    if r["kind"] == "マンション" and r.get("name"):
        for b in fl.WATCHLIST.get("buildings", []):
            nm = b.get("name", "")
            if nm and fl.norm_name(nm) in fl.norm_name(r["name"]):
                return nm, "building"
    return "", ""


def watch_wards():
    wards = set()
    for a in fl.WATCHLIST.get("areas", []):
        m = a.get("match")
        for t in (m if isinstance(m, list) else [m] if m else []):
            w = fl.ward_of(t)
            if w:
                wards.add(w)
    for b in fl.WATCHLIST.get("buildings", []):
        w = fl.ward_of(b.get("area", ""))
        if w:
            wards.add(w)
    return wards


def collect():
    """対象区の中古マンション(po=0/1 各1-2p)＋中古戸建(po=0 1p)を軽量取得。"""
    rows = {}
    for w in watch_wards():
        code = fl.WARD_CODES[fl.WARDS.index(w)]
        for po in ("0", "1"):
            for pn in (1, 2):
                q = [("ar", "030"), ("bs", "011"), ("ta", "13"), ("sc", code), ("po", po), ("pn", str(pn))]
                try:
                    for r in fl.parse_mansion(fl.fetch(fl.MS_URL + "?" + urllib.parse.urlencode(q))):
                        rows[r["id"]] = r
                except Exception:
                    pass
                time.sleep(0.8)
        q = [("ar", "030"), ("bs", "021"), ("ta", "13"), ("sc", code), ("po", "0"), ("pn", "1")]
        try:
            for r in fl.parse_area(fl.fetch(fl.AREA_URL + "?" + urllib.parse.urlencode(q))):
                rows[r["id"]] = r
        except Exception:
            pass
        time.sleep(0.8)
    return list(rows.values())


def main():
    now = datetime.datetime.now(JST)
    sf, af = DATA / "seen_watch.json", DATA / "watch_alerts.json"
    seen_list = []
    try:
        seen_list = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else []
    except Exception:
        seen_list = []
    seen = set(seen_list)
    first_run = not seen
    try:
        alerts = json.loads(af.read_text(encoding="utf-8")) if af.exists() else []
    except Exception:
        alerts = []
    budget = fl.WATCHLIST.get("budget_man") or 10 ** 9

    rows = collect()
    new = 0
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        seen_list.append(r["id"])
        if first_run:
            continue                      # 初回は既知化のみ（大量アラート防止）
        wl, wk = watch_of(r)
        if not wl or r["price"] > budget:
            continue                      # ウォッチ該当かつ予算内のみ
        alerts.insert(0, {"id": r["id"], "name": r.get("name") or "", "loc": r["loc"],
                          "price": r["price"], "url": r["url"], "watch": wl, "wk": wk,
                          "kind": r["kind"], "ts": now.isoformat()})
        new += 1
    cutoff = (now - datetime.timedelta(days=7)).isoformat()
    alerts = [a for a in alerts if a.get("ts", "") >= cutoff][:40]
    sf.write_text(json.dumps(seen_list[-8000:], ensure_ascii=False), encoding="utf-8")
    af.write_text(json.dumps(alerts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"fast_watch: scanned {len(rows)} / new watch-alerts {new} / kept {len(alerts)}"
          + (" (first run: seeded seen only)" if first_run else ""))


if __name__ == "__main__":
    main()
