#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一階賃貸（賃貸併用住宅）としての成立性スクリーナー
============================================================
data/listings.json（毎日自動更新される23区の売出物件）を読み、
「1階を賃貸に回して、住居費を賃料で相殺できるか」を物件ごとに試算する。

考え方は rental_hybrid.md と対にしてある。要点だけ再掲：

  * 23区の実勢価格では、事業用ローン（金利2.5〜4%・期間20〜25年）で
    1戸だけ貸しても返済は埋まらない。成立させる唯一の現実解は
    「住宅ローン（低金利・35年）＋自宅50%超」の賃貸併用住宅。
  * したがって本スクリーナーの合否は「儲かるか」ではなく
    **住居費をいくらまで下げられるか（実質住居費）** と
    **賃貸部分が自走するか（損益分岐賃料に対する余裕度）** で判定する。

出力:
  data/hybrid_candidates.json  … 試算済みの候補データ
  hybrid.html                  … 一覧ページ（listings.html と同じ場所に置く）

使い方:
  python3 scripts/screen_hybrid.py            # 既定パラメータ
  python3 scripts/screen_hybrid.py --rate 1.3 --equity 800 --top 40

前提数値はすべて下の PARAMS に集約してある。金利・工事費・空室率は
自分の見積りに置き換えて再実行すること（数字を動かして判断が変わるかを見るための道具）。
"""
import argparse
import datetime
import html
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LISTINGS = os.path.join(BASE, "data", "listings.json")
MARKET = os.path.join(BASE, "data", "market_real.json")
OUT_JSON = os.path.join(BASE, "data", "hybrid_candidates.json")
OUT_HTML = os.path.join(BASE, "hybrid.html")

PARAMS = {
    # --- 資金 ---
    "rate": 1.0,           # 住宅ローン金利(%)。2026年時点の変動〜固定の想定レンジ 0.7〜1.8
    "years": 35,           # 返済期間(年)
    "equity": 600,         # 自己資金(万円)。諸費用に優先充当
    "cost_ratio": 0.07,    # 諸費用率（仲介・登記・税・保険）物件価格に対して
    # --- 賃貸化コスト ---
    "reno_man": 550,       # 中古戸建を賃貸併用にする工事費(万円)
                           #   玄関分離・水回り新設・界壁(遮音/準耐火)・メーター分離・内装
    "build_m2_man": 33.0,  # 新築(土地から)の建築費 万円/㎡ ≒ 109万円/坪（木造3階・都内・2026想定）
    "build_extra": 0.10,   # 外構・地盤改良・設計監理などの上乗せ率
    # --- 賃貸運営 ---
    "vacancy": 0.10,       # 空室・滞納損失率（1戸のみ＝空くと収入ゼロなので実質は「入替期間」の年平均）
    "mgmt": 0.05,          # 管理委託料率
    "repair": 0.06,        # 修繕・原状回復の積立率
    "misc": 0.02,          # 保険・雑費率
    "ground_rate": 0.07,   # 1階賃貸の減価率（採光・防犯・浸水懸念）
    # --- 保有コスト ---
    "tax_rate": 0.0035,    # 固定資産税+都市計画税の年額 ≒ 総額の0.35%（住宅用地特例後のざっくり値）
    # --- スクリーニング閾値 ---
    "min_bld": 85,         # 中古戸建の最低延床(㎡)。これ未満は1階を割いても自宅が狭すぎる
    "min_unit": 20,        # 賃貸1戸の最低面積(㎡)
    "max_unit": 45,        # 賃貸1戸の上限(㎡)。大きくすると自宅50%ルールと出口が崩れる
    "max_home_share_rent": 0.45,  # 賃貸部分は延床の45%まで（自宅55%以上＝50%ルールに余裕）
    "min_build_floor": 120,       # 土地の場合の最低建築可能延床(㎡)
    "build_cap": 150,      # 土地から建てる場合の想定延床上限(㎡)。自宅105+賃貸45 が現実的な賃貸併用の型。
                           #   容積が余っていても「建てられる=建てるべき」ではない（建築費が総額を押し上げる）
    "max_walk": 12,        # 駅徒歩(分)。賃貸需要の下限線
    "max_price": 12000,    # 価格上限(万円)。住宅ローンで届く現実的な上限
}


def yen_pay(principal_man, rate_pct, years):
    """元利均等返済の月額（万円）。"""
    if principal_man <= 0:
        return 0.0
    r = rate_pct / 100 / 12
    n = years * 12
    if r == 0:
        return principal_man / n
    return principal_man * r / (1 - (1 + r) ** -n)


def rent_per_m2(ward, market):
    """区ごとの月額賃料単価(円/㎡)を、実取引の㎡単価から利回り逆算で推定する。

    賃料の一次データは本リポジトリに無いため、
      想定表面利回り = 6.2 - 0.018 × (万円/㎡)   ※3.3〜6.0%にクランプ
      月額賃料/㎡ = 価格/㎡ × 利回り / 12
    という単純な近似を置く。価格が高い区ほど利回りが低い（＝賃料は価格ほどには上がらない）
    という実態を1本の直線で表しただけのもの。単身向け小型住戸は㎡単価が上振れするため
    この推定は保守側（低め）に出る。**最終判断は必ずSUUMO賃貸の実募集で置き換えること。**
    """
    w = (market.get("wards") or {}).get(ward) or {}
    p = w.get("ms_m2_txn")
    if not p:
        return None, None
    y = max(3.3, min(6.0, 6.2 - 0.018 * p))
    return p * 10000 * y / 100 / 12, y


def unit_area(r, p):
    """賃貸に回せる1階部分の面積(㎡)を推定する。"""
    land = r.get("land") or 0
    bld = r.get("bld") or 0
    bcr = (r.get("bcr") or 60) / 100.0
    if r["kind"] == "土地":
        # 容積いっぱいには建てない。賃貸併用として現実的な規模で頭打ちにする。
        floor = min(r.get("build_floor") or 0, p["build_cap"])
        # 3層に割って1階分。建ぺい率で頭打ち。
        cand = min(floor / 3.0, land * bcr * 0.85)
        total = floor
    else:
        # 1階の床面積 ≒ 建築面積（建ぺい率上限）と、延床の45%（自宅50%ルール）の小さい方
        cand = min(land * bcr * 0.85, bld * p["max_home_share_rent"])
        total = bld
    if not cand or not total:
        return None, None
    return round(min(max(cand, 0), p["max_unit"]), 1), total


def evaluate(r, market, p):
    """1物件を賃貸併用として試算。除外理由があれば ('ng', 理由) を返す。"""
    tags = r.get("tags") or []
    if r["kind"] not in ("戸建", "土地"):
        return None, "区分マンションは1階だけ貸す構造が作れない"
    if "再建築不可" in tags:
        return None, "再建築不可＝住宅ローンが付かず賃貸併用の前提が崩れる"
    if "借地権" in tags:
        return None, "借地権＝融資と転貸承諾の二重ハードル"
    if (r.get("price") or 0) > p["max_price"]:
        return None, "価格が住宅ローンの現実的上限超"
    if (r.get("walk") or 99) > p["max_walk"]:
        return None, "駅徒歩が遠く単身賃貸の需要が細る"
    if r["kind"] == "戸建" and (r.get("bld") or 0) < p["min_bld"]:
        return None, "延床が小さく、1階を割くと自宅が成立しない"
    if r["kind"] == "土地" and (r.get("build_floor") or 0) < p["min_build_floor"]:
        return None, "建築可能延床が不足（容積不明を含む）"

    area, total_floor = unit_area(r, p)
    if not area or area < p["min_unit"]:
        return None, "1階に独立住戸を切り出せる面積が取れない"

    rpm2, yld = rent_per_m2(r["ward"], market)
    if not rpm2:
        return None, "区の相場データなし"

    price = r["price"]
    # --- 総事業費 ---
    reno = p["reno_man"] if r["kind"] == "戸建" else round(
        total_floor * p["build_m2_man"] * (1 + p["build_extra"]))
    costs = round(price * p["cost_ratio"])
    total_cost = price + costs + reno
    loan = max(total_cost - p["equity"], 0)
    monthly = yen_pay(loan, p["rate"], p["years"])

    # --- 賃料と手取り ---
    gross = rpm2 * area * (1 - p["ground_rate"]) / 10000  # 万円/月
    noi_ratio = 1 - p["vacancy"] - p["mgmt"] - p["repair"] - p["misc"]
    hold = total_cost * p["tax_rate"] / 12                # 固都税など 月割(全体)
    rent_share = area / total_floor                       # 賃貸部分の床面積比
    net = gross * noi_ratio - hold * rent_share

    # --- 損益分岐賃料：賃貸部分に按分した返済を賄うのに要る家賃 ---
    be = (monthly * rent_share + hold * rent_share) / noi_ratio
    margin = gross / be if be > 0 else 0

    # --- 自宅の実質負担 ---
    real_housing = monthly + hold - net

    flags = []
    hz = r.get("hazard") or {}
    if hz.get("flood"):
        flags.append(f"⚠洪水浸水想定ランク{hz['flood']}＝1階賃貸は浸水が直撃（保険料・空室・退去リスク）")
    if (r.get("elev") is not None) and r["elev"] < 3:
        flags.append(f"⚠標高{r['elev']}m＝低地。1階住戸は内水氾濫にも弱い")
    if rent_share > 0.5:
        flags.append("⚠賃貸部分が延床の50%超＝住宅ローンの『自宅1/2以上』要件を満たさない")
    elif rent_share > 0.45:
        flags.append("賃貸部分が延床の45%超＝自宅50%ルールがギリギリ。図面で床面積を確定させること")
    z = r.get("zoning") or ""
    if "低層住居専用" in z:
        flags.append(f"{z}＝住宅の賃貸は可だが店舗貸しは原則不可（兼用住宅の要件内のみ）")
    if r["kind"] == "戸建" and (r.get("struct") or "") == "木造" and (r.get("bld") or 0) < 100:
        flags.append("木造・延床100㎡未満＝界壁/遮音工事後の自宅側が狭くなりやすい")
    if r["kind"] == "土地":
        flags.append("土地＝建築費が総額の過半。設計段階から『長屋(200㎡未満)』で規制を軽くできるか要検討")
    bf = r.get("build_floor") or 0
    if r["kind"] == "戸建" and bf and (r.get("bld") or 0) > bf * 1.05:
        flags.append(f"⚠現況延床{r['bld']:.0f}㎡ > 容積上の建築可能{bf}㎡＝既存不適格の疑い。"
                     "増改築・用途変更で床を減らされる可能性があり、融資審査にも響く")
    _rsn = r.get("reason") or ""
    for kw, msg in (("私道", "私道負担/私道接道あり＝掘削承諾が取れないと水道・ガスの分岐・増設工事ができず、賃貸化そのものが詰まる"),
                    ("旧耐震", "旧耐震＝賃貸募集・融資・保険のすべてで不利")):
        if kw in _rsn:
            flags.append(msg)

    return {
        "id": r["id"], "ward": r["ward"], "loc": r["loc"], "kind": r["kind"],
        "price": price, "land": r.get("land"), "bld": r.get("bld"),
        "build_floor": r.get("build_floor"), "walk": r.get("walk"),
        "struct": r.get("struct"), "plan": r.get("plan"), "url": r.get("url"),
        "score": r.get("score"), "grade": r.get("grade"), "tier": r.get("tier"),
        "days": r.get("days"), "zoning": z, "tags": tags,
        "notes": [n for n in (r.get("reason") or "").split(" / ") if n][:4],
        "unit_area": area, "total_floor": round(total_floor, 1),
        "rent_share": round(rent_share * 100),
        "rent_m2": round(rpm2), "cap_used": round(yld, 2),
        "gross_rent": round(gross, 1), "net_rent": round(net, 1),
        "breakeven_rent": round(be, 1), "margin": round(margin, 2),
        "reno": reno, "costs": costs, "total_cost": total_cost,
        "loan": loan, "monthly": round(monthly, 1),
        "real_housing": round(real_housing, 1),
        "flags": flags,
    }, None


def main():
    ap = argparse.ArgumentParser()
    for k, v in PARAMS.items():
        ap.add_argument("--" + k.replace("_", "-"), type=type(v), default=v)
    ap.add_argument("--top", type=int, default=60)
    a = ap.parse_args()
    p = {k: getattr(a, k) for k in PARAMS}

    if not os.path.exists(LISTINGS):
        sys.exit("data/listings.json がない。先に scripts/fetch_listings.py を実行すること。")
    data = json.load(open(LISTINGS, encoding="utf-8"))
    market = json.load(open(MARKET, encoding="utf-8")) if os.path.exists(MARKET) else {}

    rows, rejected = [], {}
    for r in data["rows"]:
        res, why = evaluate(r, market, p)
        if res:
            rows.append(res)
        elif why:
            rejected[why] = rejected.get(why, 0) + 1

    # 余裕度（賃料/損益分岐賃料）優先。同率は実質住居費の低い順。
    rows.sort(key=lambda x: (-x["margin"], x["real_housing"]))
    rows = rows[: a.top]

    out = {
        "updated": datetime.datetime.now().astimezone().isoformat(),
        "source_updated": data.get("updated"),
        "params": p, "count": len(rows),
        "screened": data.get("count"), "rejected": rejected, "rows": rows,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(OUT_HTML, "w", encoding="utf-8").write(render(out))
    print(f"{len(rows)}件 / 母集団{data.get('count')}件 → {OUT_JSON}, {OUT_HTML}")
    for k, v in sorted(rejected.items(), key=lambda x: -x[1]):
        print(f"  除外 {v:4d}件  {k}")


# ---------------- HTML 出力 ----------------

CSS = """
:root{--bg:#f5f7fa;--card:#fff;--ink:#1b2430;--sub:#5d6b7a;--line:#e3e8ef;--accent:#2563eb;
      --ok:#0f7b52;--warn:#b45309;--ng:#b91c1c}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Hiragino Kaku Gothic ProN",Meiryo,sans-serif;
     margin:0;background:var(--bg);color:var(--ink);line-height:1.65;font-size:15px}
.wrap{max-width:1180px;margin:0 auto;padding:24px 16px 80px}
h1{font-size:1.55rem;margin:0 0 6px}
h2{font-size:1.1rem;margin:34px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--line)}
.lead{color:var(--sub);font-size:.93rem;margin:0 0 18px}
.note{background:#fff8e6;border:1px solid #f0dda8;border-radius:10px;padding:12px 14px;
      font-size:.88rem;color:#6b4e12;margin:14px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 15px}
.card h3{font-size:1.02rem;margin:0 0 2px}
.card h3 a{color:var(--ink);text-decoration:none}
.card h3 a:hover{color:var(--accent)}
.meta{color:var(--sub);font-size:.82rem;margin-bottom:10px}
.big{font-size:1.35rem;font-weight:700}
.kv{display:grid;grid-template-columns:1fr auto;gap:2px 10px;font-size:.87rem;margin:8px 0}
.kv .k{color:var(--sub)}
.kv .v{text-align:right;font-variant-numeric:tabular-nums}
.hr{border-top:1px dashed var(--line);margin:9px 0}
.badge{display:inline-block;font-size:.72rem;padding:2px 7px;border-radius:999px;margin:0 4px 4px 0}
.b-ok{background:#e6f4ee;color:var(--ok)}
.b-warn{background:#fdf1df;color:var(--warn)}
.b-ng{background:#fdeaea;color:var(--ng)}
.b-mut{background:#eef1f5;color:var(--sub)}
.flags{font-size:.8rem;color:var(--warn);margin-top:8px}
.flags div{margin-top:3px}
.notes{font-size:.78rem;color:var(--sub);margin-top:8px;border-top:1px dotted var(--line);padding-top:7px}
.notes div{margin-top:2px}
table{border-collapse:collapse;width:100%;font-size:.86rem;background:#fff;
      border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left}
th{background:#eef2f7;font-weight:600;color:var(--sub);font-size:.8rem}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}
.foot{color:var(--sub);font-size:.82rem;margin-top:26px}
a{color:var(--accent)}
@media (prefers-color-scheme:dark){
 :root{--bg:#11161d;--card:#1a212b;--ink:#e6ecf3;--sub:#93a1b1;--line:#2b3644;--accent:#7aa7ff}
 .note{background:#2a2415;border-color:#4a3f22;color:#e5cf9a}
 th{background:#222b36}
 .b-ok{background:#123a2b;color:#5fd6a4}.b-warn{background:#3a2c12;color:#e5b25f}
 .b-ng{background:#3a1a1a;color:#f08a8a}.b-mut{background:#252d38;color:var(--sub)}
}
"""


def _mbadge(m):
    if m >= 1.3:
        return '<span class="badge b-ok">賃貸部分が自走（余裕度%.2f）</span>' % m
    if m >= 1.0:
        return '<span class="badge b-warn">ほぼ収支トントン（余裕度%.2f）</span>' % m
    return '<span class="badge b-ng">賃料では返済を賄えない（余裕度%.2f）</span>' % m


def render(out):
    p, rows = out["params"], out["rows"]
    e = html.escape
    cards = []
    for r in rows:
        badges = [_mbadge(r["margin"])]
        if r["grade"]:
            badges.append('<span class="badge b-mut">値持ち%s</span>' % e(r["grade"]))
        badges.append('<span class="badge b-mut">出口%s</span>' % e(str(r["tier"])))
        if r["zoning"]:
            badges.append('<span class="badge b-mut">%s</span>' % e(r["zoning"]))
        for t in r["tags"]:
            badges.append('<span class="badge b-mut">%s</span>' % e(t))
        size = (f"土地{r['land']:.0f}㎡ / 建築可{r['build_floor']}㎡"
                if r["kind"] == "土地" else
                f"土地{r['land']:.0f}㎡ / 延床{r['bld']:.0f}㎡")
        cards.append(f"""<div class="card">
 <h3><a href="{e(r['url'])}" target="_blank" rel="noopener">{e(r['loc'])}</a></h3>
 <div class="meta">{e(r['kind'])}・{e(r['struct'] or '')} {e(r['plan'] or '')}／{size}／駅徒歩{r['walk']}分</div>
 <div class="big">{r['price']:,}万円</div>
 <div>{''.join(badges)}</div>
 <div class="kv">
  <span class="k">1階 賃貸戸（想定）</span><span class="v">{r['unit_area']}㎡（延床の{r['rent_share']}%）</span>
  <span class="k">想定賃料（相場推定）</span><span class="v">{r['gross_rent']}万円/月</span>
  <span class="k">損益分岐賃料</span><span class="v">{r['breakeven_rent']}万円/月</span>
 </div>
 <div class="hr"></div>
 <div class="kv">
  <span class="k">賃貸化工事{'（新築建築費）' if r['kind']=='土地' else ''}</span><span class="v">{r['reno']:,}万円</span>
  <span class="k">諸費用</span><span class="v">{r['costs']:,}万円</span>
  <span class="k">総事業費</span><span class="v">{r['total_cost']:,}万円</span>
  <span class="k">借入（自己資金{p['equity']}万円控除後）</span><span class="v">{r['loan']:,}万円</span>
  <span class="k">月返済（{p['rate']}%・{p['years']}年）</span><span class="v">{r['monthly']}万円</span>
  <span class="k">賃貸の手取り</span><span class="v">+{r['net_rent']}万円</span>
 </div>
 <div class="hr"></div>
 <div class="kv"><span class="k"><b>実質の住居費</b></span>
   <span class="v"><b>{r['real_housing']}万円/月</b></span></div>
 <div class="flags">{''.join('<div>'+e(f)+'</div>' for f in r['flags'])}</div>
 <div class="notes">{''.join('<div>・'+e(n)+'</div>' for n in r['notes'])}</div>
</div>""")

    trows = "".join(f"""<tr><td>{e(x['ward'])}</td><td><a href="{e(x['url'])}" target="_blank"
 rel="noopener">{e(x['loc'])}</a></td><td>{e(x['kind'])}</td>
 <td class="num">{x['price']:,}</td><td class="num">{x['unit_area']}</td>
 <td class="num">{x['rent_share']}%</td><td class="num">{x['gross_rent']}</td>
 <td class="num">{x['breakeven_rent']}</td><td class="num">{x['margin']:.2f}</td>
 <td class="num">{x['monthly']}</td><td class="num">{x['real_housing']}</td></tr>""" for x in rows)

    rej = "".join(f"<tr><td>{e(k)}</td><td class='num'>{v}</td></tr>"
                  for k, v in sorted(out["rejected"].items(), key=lambda x: -x[1]))

    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>一階賃貸（賃貸併用）成立性スクリーナー — 東京23区</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>一階を貸す前提で買えるか — 賃貸併用スクリーナー</h1>
<p class="lead">
 母集団 {out['screened']}件（{e(str(out['source_updated'])[:10])} 時点のSUUMO自動取得）から、
 1階に独立住戸を切り出せる戸建・土地を抽出し、<b>住宅ローンで買って1階を貸したときの実質住居費</b>を試算。
 判定基準・法規・税の整理は <a href="./rental_hybrid.md">rental_hybrid.md</a>、
 物件そのものの値持ち評価は <a href="./listings.html">listings.html</a>。
</p>
<div class="note">
 <b>この表の読み方。</b>
 「余裕度」＝想定賃料 ÷ 損益分岐賃料。1.0を割ると、賃貸部分は返済を賄えず自宅側の持ち出しになる。
 「実質の住居費」＝月返済＋固都税等−賃貸の手取り。これを<b>いま払っている家賃と比べる</b>のが唯一の使い方。
 想定賃料は区の実取引㎡単価からの<b>推定値</b>（賃料の一次データではない）。
 必ずSUUMO賃貸で同一エリア・同面積の<b>実募集</b>3件以上に置き換えて再計算すること。
 事業用ローン（金利{2.8}%・25年想定）に置き換えると月返済は約1.6倍になり、
 1戸賃貸ではまず成立しない。そこが「事業として買う」ことの分岐点。
</div>

<h2>候補 {out['count']}件（余裕度順）</h2>
<div class="grid">{''.join(cards)}</div>

<h2>一覧表</h2>
<div class="scroll"><table>
<tr><th>区</th><th>所在</th><th>種別</th><th class="num">価格<br><span style="font-weight:400">万円</span></th>
<th class="num">賃貸戸<br>㎡</th><th class="num">床<br>比</th><th class="num">想定賃料<br>万/月</th>
<th class="num">分岐賃料<br>万/月</th><th class="num">余裕度</th><th class="num">月返済<br>万</th>
<th class="num">実質住居費<br>万/月</th></tr>
{trows}</table></div>

<h2>母集団から外した理由</h2>
<div class="scroll"><table><tr><th>除外理由</th><th class="num">件数</th></tr>{rej}</table></div>

<h2>試算に使った前提</h2>
<div class="scroll"><table><tr><th>項目</th><th>値</th></tr>
<tr><td>住宅ローン金利 / 期間</td><td>{p['rate']}% / {p['years']}年（元利均等）</td></tr>
<tr><td>自己資金</td><td>{p['equity']:,}万円</td></tr>
<tr><td>諸費用</td><td>物件価格の{p['cost_ratio']*100:.0f}%</td></tr>
<tr><td>賃貸化工事（中古戸建）</td><td>{p['reno_man']:,}万円（玄関分離・水回り新設・界壁・メーター分離・内装）</td></tr>
<tr><td>建築費（土地から新築）</td><td>{p['build_m2_man']}万円/㎡ ＋ 外構等{p['build_extra']*100:.0f}%</td></tr>
<tr><td>空室・滞納 / 管理 / 修繕 / 保険雑費</td>
    <td>{p['vacancy']*100:.0f}% / {p['mgmt']*100:.0f}% / {p['repair']*100:.0f}% / {p['misc']*100:.0f}%
        （手取り率 {(1-p['vacancy']-p['mgmt']-p['repair']-p['misc'])*100:.0f}%）</td></tr>
<tr><td>1階の賃料減価</td><td>−{p['ground_rate']*100:.0f}%（採光・防犯・浸水懸念）</td></tr>
<tr><td>固都税等</td><td>総事業費の年{p['tax_rate']*100:.2f}%</td></tr>
<tr><td>賃貸部分の床面積上限</td><td>延床の{p['max_home_share_rent']*100:.0f}%（自宅1/2以上の要件に余裕を持たせる）</td></tr>
</table></div>

<p class="foot">
 生成 {e(out['updated'][:16])}／データ {e(str(out['source_updated'])[:16])}。
 本ページは学習・比較のための試算であり、投資勧誘でも税務・法務・建築の助言でもない。
 賃料・工事費・融資条件はすべて仮定値。実行前に不動産業者・建築士・金融機関・税理士の確認を。
</p>
</div></body></html>"""


if __name__ == "__main__":
    main()
