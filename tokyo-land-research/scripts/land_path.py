#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
都心に土地を持つまでの経路シミュレータ
============================================================
ゴール：**都心に土地を持つ**。時間軸は5〜10年。手段は問わない。

このゴールに変えると、判断の前提が3つ変わる。

  1. 「そこに住む」を外せる  → 住宅ローンの自宅1/2ルールと年収天井から自由になる
  2. 「すぐ建てる」を外せる  → 再建築不可・狭小地が候補に入る（土地の所有権は完全に手に入る）
  3. 時間がある            → 接道改善の交渉、法人の決算実績づくりができる

一方で、時間には値段が付いている。都心の地価は年4〜5.6%で上がっており、
**貯めてから買う経路はほぼ全ての現実的な貯蓄ペースで「届かない」**。
本スクリプトはそれを数字で出し、レバレッジを使う経路と並べて比較する。

出力:
  land_path.html            … 経路比較・待つコスト・現在の到達可能候補
  data/land_path.json       … 同じ内容のデータ

使い方:
  python3 scripts/land_path.py --equity 1000 --save 300 --income 800
  python3 scripts/land_path.py --equity 2000 --save 500 --years 10 --growth 4.5
"""
import argparse
import datetime
import html
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LISTINGS = os.path.join(BASE, "data", "listings.json")
MARKET = os.path.join(BASE, "data", "market_real.json")
OUT_JSON = os.path.join(BASE, "data", "land_path.json")
OUT_HTML = os.path.join(BASE, "land_path.html")

CORE = ["千代田区", "中央区", "港区", "新宿区", "文京区",
        "渋谷区", "目黒区", "品川区", "台東区", "豊島区"]


def ppm(rate, years):
    """借入1円あたりの月返済額。"""
    i = rate / 100 / 12
    n = years * 12
    return 1 / n if i == 0 else i / (1 - (1 + i) ** -n)


def loan_constant(rate, years):
    """ローン定数（年返済額 ÷ 借入額、%）。物件のNOI利回りがこれを下回ると回らない。"""
    return ppm(rate, years) * 12 * 100


def balance_after(principal, rate, years, t_years, extra=0.0):
    """毎月 extra を元金に上乗せしたときの t 年後のローン残高。"""
    i = rate / 100 / 12
    m = principal * ppm(rate, years)
    bal = principal
    for _ in range(int(round(t_years * 12))):
        if bal <= 0:
            return 0.0
        bal -= (m - bal * i + extra)
    return max(bal, 0.0)


def cash_reach_year(price_now, growth, equity, save, tmax=30):
    """地価が年 growth% で上がる中、貯蓄だけで現金到達する年。届かなければ None。"""
    for t in range(tmax + 1):
        if equity + save * t >= price_now * (1 + growth / 100) ** t:
            return t
    return None


def core_market(market):
    """都心10区の土地坪単価とCAGRを取り出す。"""
    out = []
    for w in CORE:
        v = (market.get("wards") or {}).get(w) or {}
        if v.get("land_tsubo_txn"):
            out.append({"ward": w, "tsubo": v["land_tsubo_txn"],
                        "m2": v["land_tsubo_txn"] / 3.30578,
                        "cagr": v.get("cagr_ms") or 0})
    return sorted(out, key=lambda x: x["tsubo"])


def core_candidates(listings, limit=20):
    """いま都心で『土地の所有権を手に入れられる』最安の売り物。借地権は除く（土地が自分のものにならない）。"""
    rows = []
    for r in listings["rows"]:
        if r["ward"] not in CORE or r["kind"] not in ("戸建", "土地"):
            continue
        tags = r.get("tags") or []
        if "借地権" in tags:
            continue
        rows.append({
            "ward": r["ward"], "loc": r["loc"], "price": r["price"],
            "land": r.get("land"), "tsubo_unit": r.get("tsubo"), "walk": r.get("walk"),
            "kind": r["kind"], "url": r.get("url"), "tags": tags,
            "rebuild_ng": "再建築不可" in tags,
            "ratio": r.get("ratio"), "grade": r.get("grade"),
        })
    return sorted(rows, key=lambda x: x["price"])[:limit]


def build(a, listings, market):
    """4つの経路を同じ時間軸で並べる。"""
    g = a.growth
    core = core_market(market)
    cands = core_candidates(listings)

    # 目標：都心の土地。予算指定がなければ「現在の最安到達可能物件」を目標に置く
    target = a.target or (cands[0]["price"] if cands else 5000)

    # --- 待つコスト：目標が毎年いくら逃げるか ---
    escape = []
    for t in (0, 3, 5, 7, 10):
        escape.append({"year": t, "price": round(target * (1 + g / 100) ** t)})

    # --- ルートA：貯蓄だけ（レバレッジなし）---
    route_a = []
    for P in sorted({target, 3000, 5000, 8000, 12000}):
        row = {"price": P, "years": {}}
        for S in (200, 300, 500, 800):
            t = cash_reach_year(P, g, a.equity, S)
            row["years"][S] = t
        route_a.append(row)

    # --- ルートB：外周区で回る1棟を持ち、賃料手取りを繰上返済に回して育てる ---
    #   数字は hybrid.html の実候補（外周区の賃貸併用）を想定した既定値。
    route_b = []
    for t in (5, 7, 10, 15):
        bal = balance_after(a.b_loan, a.rate, a.years_loan, t, a.b_net)
        val = a.b_price * (1 + a.b_growth / 100) ** t
        equity_b = val - bal
        saved = a.save * t            # 住居費が下がるぶんは save に織り込む前提
        route_b.append({"year": t, "value": round(val), "balance": round(bal),
                        "equity": round(equity_b), "saved": round(saved),
                        "total": round(equity_b + saved)})

    # --- ネガティブレバレッジ：都心の収益物件は事業用ローンで回るか ---
    lev = []
    for gross in (3.5, 4.0, 4.5, 5.0, 6.0, 7.0):
        noi = gross * a.noi_ratio
        row = {"gross": gross, "noi": round(noi, 2), "cases": []}
        for r, y in ((a.biz_rate, a.biz_years), (a.biz_rate_bad, a.biz_years_bad)):
            debt = a.ltv * loan_constant(r, y)
            row["cases"].append({"rate": r, "years": y, "debt": round(debt, 2),
                                 "ok": noi > debt})
        lev.append(row)

    # --- ルートE：都心を自己資金比率を上げて取りに行くときの必要額 ---
    route_e = []
    for P in (5000, 8000, 12000):
        row = {"price": P, "cases": []}
        for er in (0.2, 0.3, 0.4, 1.0):
            loan = P * (1 - er)
            row["cases"].append({
                "equity_ratio": er, "equity": round(P * er), "loan": round(loan),
                "annual": round(loan * loan_constant(a.biz_rate, a.biz_years) / 100)})
        route_e.append(row)

    return {
        "updated": datetime.datetime.now().astimezone().isoformat(),
        "source_updated": listings.get("updated"),
        "input": vars(a), "target": target,
        "core": core, "candidates": cands, "escape": escape,
        "route_a": route_a, "route_b": route_b, "route_e": route_e,
        "leverage": lev,
        "loan_constants": [{"rate": r, "years": y, "k": round(loan_constant(r, y), 2)}
                           for r, y in ((1.0, 35), (2.0, 30), (2.8, 25), (3.5, 20), (4.5, 20))],
    }


CSS = """
:root{--bg:#f5f7fa;--card:#fff;--ink:#1b2430;--sub:#5d6b7a;--line:#e3e8ef;--accent:#2563eb;
      --ok:#0f7b52;--warn:#b45309;--ng:#b91c1c}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Hiragino Kaku Gothic ProN",Meiryo,sans-serif;
     margin:0;background:var(--bg);color:var(--ink);line-height:1.65;font-size:15px}
.wrap{max-width:1120px;margin:0 auto;padding:24px 16px 80px}
h1{font-size:1.5rem;margin:0 0 6px}
h2{font-size:1.12rem;margin:36px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--line)}
h3{font-size:1rem;margin:22px 0 8px}
.lead{color:var(--sub);font-size:.92rem;margin:0 0 18px}
.verdict{border-radius:12px;padding:16px 18px;margin:18px 0;border:1px solid;
         background:#fdeaea;border-color:#f0c0c0;color:#7d1d1d}
.verdict.ok{background:#e6f4ee;border-color:#b6dfcc;color:#0b5236}
table{border-collapse:collapse;width:100%;font-size:.87rem;background:#fff;
      border:1px solid var(--line);border-radius:10px;overflow:hidden;margin:10px 0}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:#eef2f7;font-weight:600;color:var(--sub);font-size:.8rem}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.ng{color:var(--ng);font-weight:600}.ok{color:var(--ok);font-weight:600}
.warn{color:var(--warn)}
.tag{display:inline-block;font-size:.72rem;padding:1px 6px;border-radius:999px;
     background:#eef1f5;color:var(--sub);margin-right:3px}
.tag.r{background:#fdeaea;color:var(--ng)}
.scroll{overflow-x:auto}
.foot{color:var(--sub);font-size:.82rem;margin-top:28px}
a{color:var(--accent)}
@media (prefers-color-scheme:dark){
 :root{--bg:#11161d;--card:#1a212b;--ink:#e6ecf3;--sub:#93a1b1;--line:#2b3644;--accent:#7aa7ff}
 th{background:#222b36}
 .verdict{background:#3a1a1a;border-color:#5c2b2b;color:#f0b0b0}
 .verdict.ok{background:#123a2b;border-color:#1e5c44;color:#8fe0bb}
 .tag{background:#252d38}.tag.r{background:#3a1a1a;color:#f08a8a}
}
"""


def render(d):
    e = html.escape
    a = d["input"]
    g = a["growth"]

    esc = d["escape"][-1]
    esc_per_year = (esc["price"] - d["target"]) / 10

    a_rows = ""
    for row in d["route_a"]:
        cells = ""
        for S in (200, 300, 500, 800):
            t = row["years"][S]
            cells += (f'<td class="num ok">{t}年</td>' if t is not None
                      else '<td class="num ng">届かない</td>')
        a_rows += f'<tr><td class="num">{row["price"]:,}万</td>{cells}</tr>'

    b_rows = "".join(
        f'<tr><td class="num">{x["year"]}年後</td><td class="num">{x["value"]:,}</td>'
        f'<td class="num">{x["balance"]:,}</td><td class="num ok">{x["equity"]:,}</td>'
        f'<td class="num">{x["saved"]:,}</td><td class="num"><b>{x["total"]:,}</b></td></tr>'
        for x in d["route_b"])

    lev_rows = ""
    for x in d["leverage"]:
        cs = ""
        for c in x["cases"]:
            cls = "ok" if c["ok"] else "ng"
            word = "回る" if c["ok"] else "回らない"
            cs += f'<td class="num">{c["debt"]}%</td><td class="{cls}">{word}</td>'
        lev_rows += (f'<tr><td class="num">{x["gross"]}%</td>'
                     f'<td class="num">{x["noi"]}%</td>{cs}</tr>')

    e_rows = ""
    for x in d["route_e"]:
        for i, c in enumerate(x["cases"]):
            head = f'<td class="num" rowspan="{len(x["cases"])}">{x["price"]:,}万</td>' if i == 0 else ""
            lab = "現金" if c["equity_ratio"] == 1.0 else f'{c["equity_ratio"]*100:.0f}%'
            e_rows += (f'<tr>{head}<td>{lab}</td><td class="num">{c["equity"]:,}</td>'
                       f'<td class="num">{c["loan"]:,}</td><td class="num">{c["annual"]:,}</td></tr>')

    core_rows = "".join(
        f'<tr><td>{e(x["ward"])}</td><td class="num">{x["tsubo"]:,.0f}</td>'
        f'<td class="num">{x["m2"]:,.0f}</td><td class="num">{x["cagr"]:.1f}%</td>'
        f'<td class="num">{x["tsubo"]*(1+x["cagr"]/100)**5:,.0f}</td>'
        f'<td class="num">{x["tsubo"]*(1+x["cagr"]/100)**10:,.0f}</td></tr>'
        for x in d["core"])

    cand_rows = ""
    for x in d["candidates"]:
        tags = "".join(f'<span class="tag{" r" if t=="再建築不可" else ""}">{e(t)}</span>'
                       for t in x["tags"])
        land = f'{x["land"]:.1f}' if x["land"] else "—"
        tsubo = f'{x["land"]/3.30578:.1f}' if x["land"] else "—"
        unit = f'{x["tsubo_unit"]:,.0f}' if x["tsubo_unit"] else "—"
        cand_rows += (f'<tr><td>{e(x["ward"])}</td>'
                      f'<td><a href="{e(x["url"] or "")}" target="_blank" rel="noopener">{e(x["loc"])}</a>'
                      f'<br>{tags}</td>'
                      f'<td class="num">{x["price"]:,}</td><td class="num">{land}</td>'
                      f'<td class="num">{tsubo}</td><td class="num">{unit}</td>'
                      f'<td class="num">{x["walk"]}分</td></tr>')

    k_rows = "".join(f'<tr><td>{x["rate"]}% / {x["years"]}年</td><td class="num">{x["k"]}%</td></tr>'
                     for x in d["loan_constants"])

    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>都心に土地を持つまでの経路 — 5〜10年の設計図</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>都心に土地を持つまでの経路</h1>
<p class="lead">
 前提：自己資金 {a['equity']:,.0f}万円／年間貯蓄 {a['save']:,.0f}万円／世帯年収 {a['income']:,.0f}万円／
 都心の地価上昇率 年{g}%（実取引ベースの実績は4.0〜5.6%）。
 目標に置いた都心の土地＝<b>{d['target']:,}万円</b>（現在の最安到達可能物件）。
 考え方は <a href="./land_strategy.md">land_strategy.md</a>、
 1階賃貸の型は <a href="./rental_hybrid.md">rental_hybrid.md</a>、
 物件一覧は <a href="./listings.html">listings.html</a>。
</p>

<div class="verdict">
 <b>待つコストは年 {esc_per_year:,.0f}万円。</b>
 目標の土地は 10年で {d['target']:,}万 → {esc['price']:,}万（+{esc['price']-d['target']:,}万）に逃げる。<br>
 <b>そして貯蓄だけで追いつく経路は、現実的な貯蓄ペースではほぼ存在しない（下表）。</b>
 つまり「貯めてから買う」は選択肢ではなく、<b>レバレッジ（融資）を使う経路を設計するしかない</b>。
</div>

<h2>ルートA：貯蓄だけで現金到達できるか</h2>
<div class="scroll"><table>
<tr><th class="num">目標価格</th><th class="num">年200万貯蓄</th><th class="num">年300万</th>
    <th class="num">年500万</th><th class="num">年800万</th></tr>
{a_rows}</table></div>
<p class="lead">自己資金 {a['equity']:,.0f}万円スタート、地価上昇 年{g}%。
「届かない」は30年以内に価格に追いつかないという意味。</p>

<h2>ルートB：外周区で回る1棟を持ち、賃料を繰上返済に回して育てる</h2>
<p class="lead">
 物件価格 {a['b_price']:,.0f}万／借入 {a['b_loan']:,.0f}万（{a['rate']}%・{a['years_loan']}年）／
 賃貸の手取り 月{a['b_net']}万円を全額 元金に充当／エリアの地価上昇 年{a['b_growth']}%。
 数字は <a href="./hybrid.html">hybrid.html</a> の外周区候補の実データに基づく既定値。
</p>
<div class="scroll"><table>
<tr><th class="num">時点</th><th class="num">物件価値<br>万</th><th class="num">ローン残<br>万</th>
    <th class="num">エクイティ<br>万</th><th class="num">その間の貯蓄<br>万</th><th class="num">合計<br>万</th></tr>
{b_rows}</table></div>
<p class="lead">
 <b>この経路が作るのは現金だけではない。</b>①自己資金 ②賃貸業の決算実績（＝法人・事業用融資の与信）
 ③住居費の削減、の3つを同時に作る。5〜10年後に都心を取りに行くときに効くのは、現金より②と③。
</p>

<h2>都心は「利回りで買う」場所ではない — ネガティブレバレッジの検証</h2>
<div class="scroll"><table>
<tr><th class="num">表面利回り</th><th class="num">NOI利回り<br>（{a['noi_ratio']*100:.0f}%換算）</th>
    <th class="num">年返済<br>{a['biz_rate']}%/{a['biz_years']}年</th><th>判定</th>
    <th class="num">年返済<br>{a['biz_rate_bad']}%/{a['biz_years_bad']}年</th><th>判定</th></tr>
{lev_rows}</table></div>
<p class="lead">
 借入比率 {a['ltv']*100:.0f}% での年返済（＝借入比率×ローン定数）と、NOI利回りの比較。
 <b>都心の表面利回りは概ね3.5〜4.5%、外周区は5〜6%。</b>
 都心は借入を厚くすると回らない＝<b>自己資金比率を上げるか、外周区で稼いで取りに行くしかない</b>。
</p>
<div class="scroll"><table style="max-width:420px">
<tr><th>ローン条件</th><th class="num">ローン定数（年返済÷借入）</th></tr>{k_rows}</table></div>

<h2>ルートE：都心を取りに行くときに要る自己資金</h2>
<div class="scroll"><table>
<tr><th class="num">物件価格</th><th>自己資金比率</th><th class="num">自己資金<br>万</th>
    <th class="num">借入<br>万</th><th class="num">年返済<br>万（{a['biz_rate']}%/{a['biz_years']}年）</th></tr>
{e_rows}</table></div>
<p class="lead">
 土地だけ（収益を生まない更地）には事業用融資が出にくい。
 <b>都心の土地を融資で取るなら「収益建物ごと買う」か「建てる計画とセットで買う」</b>。
 現金なら制約はないが、上のルートAのとおり貯蓄だけでは届かない。
</p>

<h2>都心10区の土地相場と、5年後・10年後</h2>
<div class="scroll"><table>
<tr><th>区</th><th class="num">坪単価<br>万</th><th class="num">㎡単価<br>万</th>
    <th class="num">年率</th><th class="num">5年後 坪<br>万</th><th class="num">10年後 坪<br>万</th></tr>
{core_rows}</table></div>
<p class="lead">実取引ベース（国交省）。年率はマンション成約のCAGR＝そのエリアの値動きの代理指標。</p>

<h2>いま都心で「土地の所有権」を最も安く手に入れられる売り物</h2>
<div class="scroll"><table>
<tr><th>区</th><th>所在</th><th class="num">価格<br>万</th><th class="num">土地<br>㎡</th>
    <th class="num">坪</th><th class="num">坪単価<br>万</th><th class="num">駅</th></tr>
{cand_rows}</table></div>
<p class="lead">
 借地権は除外（土地が自分のものにならないためゴールに反する）。
 <span class="tag r">再建築不可</span> は<b>建物が建てられないだけで、土地の所有権は完全に手に入る</b>。
 坪単価が相場の3〜5割で買える一方、融資が付かず現金が要り、出口も狭い。
 <b>ゴールが「持つこと」で時間が5〜10年あるなら、評価はこれまでと変わる</b>
 （接道改善・隣地買収の交渉時間が取れる）。判断の枠組みは
 <a href="./risk_guide.md">risk_guide.md</a> と <a href="./property_checklist.md">property_checklist.md</a>。
</p>

<p class="foot">
 生成 {e(d['updated'][:16])}／物件データ {e(str(d['source_updated'])[:16])}。
 本ページは学習・比較のための試算であり、投資勧誘でも税務・法務・建築の助言でもない。
 地価上昇率は過去実績であって将来を保証しない。金利・賃料・融資条件はすべて仮定値。
 実行前に不動産業者・建築士・金融機関・税理士の確認を。
</p>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="都心に土地を持つまでの経路シミュレータ")
    ap.add_argument("--equity", type=float, default=1000, help="現在の自己資金(万円)")
    ap.add_argument("--save", type=float, default=300, help="年間の貯蓄可能額(万円)")
    ap.add_argument("--income", type=float, default=800, help="世帯年収(万円)")
    ap.add_argument("--target", type=float, default=0, help="目標の都心の土地の価格(万円)。0で最安候補を自動採用")
    ap.add_argument("--growth", type=float, default=4.5, help="都心の地価上昇率(%/年)")
    ap.add_argument("--years", type=int, default=10, help="時間軸(年)")
    # ルートB（外周区の1棟目）の既定値は hybrid.html の実候補ベース
    ap.add_argument("--b-price", type=float, default=2450, help="1棟目の物件価格(万円)")
    ap.add_argument("--b-loan", type=float, default=2572, help="1棟目の借入(万円)")
    ap.add_argument("--b-net", type=float, default=4.4, help="1棟目の賃貸手取り(万円/月)")
    ap.add_argument("--b-growth", type=float, default=4.5, help="1棟目エリアの地価上昇率(%/年)")
    ap.add_argument("--rate", type=float, default=1.0, help="住宅ローン金利(%)")
    ap.add_argument("--years-loan", type=int, default=35, help="住宅ローン期間(年)")
    ap.add_argument("--biz-rate", type=float, default=2.8, help="事業用ローン金利(%)")
    ap.add_argument("--biz-years", type=int, default=25, help="事業用ローン期間(年)")
    ap.add_argument("--biz-rate-bad", type=float, default=3.5, help="比較用の厳しい事業用ローン金利(%)")
    ap.add_argument("--biz-years-bad", type=int, default=20, help="同・期間(年)")
    ap.add_argument("--ltv", type=float, default=0.70, help="借入比率")
    ap.add_argument("--noi-ratio", type=float, default=0.75, help="表面利回りからNOI利回りへの換算率")
    a = ap.parse_args()

    listings = json.load(open(LISTINGS, encoding="utf-8"))
    market = json.load(open(MARKET, encoding="utf-8")) if os.path.exists(MARKET) else {}
    d = build(a, listings, market)

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump(d, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(OUT_HTML, "w", encoding="utf-8").write(render(d))

    esc = d["escape"][-1]
    print(f"目標の都心の土地 {d['target']:,}万円 → 10年後 {esc['price']:,}万円"
          f"（待つコスト 年{(esc['price']-d['target'])/10:,.0f}万円）\n")
    print("ルートA 貯蓄だけで現金到達（自己資金%s万・地価上昇%s%%）:" % (f"{a.equity:,.0f}", a.growth))
    for row in d["route_a"]:
        cells = "  ".join(f"年{S}万:{('%d年' % t) if t is not None else '届かない'}"
                          for S, t in row["years"].items())
        print(f"  目標{row['price']:6,}万 → {cells}")
    print("\nルートB 外周区の1棟を育てる:")
    for x in d["route_b"]:
        print(f"  {x['year']:2d}年後 エクイティ {x['equity']:5,}万 ＋ 貯蓄 {x['saved']:5,}万 = {x['total']:6,}万")
    print("\n都心の収益物件は事業用ローンで回るか（借入%d%%）:" % (a.ltv * 100))
    for x in d["leverage"]:
        c = x["cases"][0]
        print(f"  表面{x['gross']}% → NOI{x['noi']}% vs 年返済{c['debt']}% … "
              f"{'回る' if c['ok'] else '回らない'}")
    print(f"\n→ {OUT_HTML}, {OUT_JSON}")


if __name__ == "__main__":
    main()
