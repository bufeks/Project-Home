#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
取得力と返済加速のプランナー
============================================================
「都心に家が欲しいが、自分だけのローンでは届かない。
  1階を貸して取得し、ローンを早く返す事業にできないか」

この問いは、実はまったく別の2つの問いに分かれる。

  問1【取得力】 1階の賃料は、借りられる額を増やしてくれるか？
  問2【返済加速】1階の賃料は、ローンを早く終わらせてくれるか？

答えは **問1はほぼノー、問2は明確にイエス**。本スクリプトはそれを数字で出す。
賃貸併用は「買えるようにする道具」ではなく「早く返す道具」である、というのが結論。

出力:
  loan_plan.html                … 4ルートの取得力比較・必要頭金・返済加速の表
  data/loan_plan.json           … 同じ内容のデータ

使い方:
  python3 scripts/loan_plan.py --income 900 --equity 2000 --target 10800
  python3 scripts/loan_plan.py --income 700 --partner 400 --target 8500 --rent 12
"""
import argparse
import datetime
import html
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_JSON = os.path.join(BASE, "data", "loan_plan.json")
OUT_HTML = os.path.join(BASE, "loan_plan.html")


def ppm(rate, years):
    """借入1万円あたりの月返済額（元利均等）。"""
    i = rate / 100 / 12
    n = years * 12
    return 1 / n if i == 0 else i / (1 - (1 + i) ** -n)


def capacity(income_man, ratio, shinsa, years):
    """借入可能額(万円)。銀行は実行金利ではなく審査金利で返済比率を測る。"""
    return (income_man * ratio / 12) / ppm(shinsa, years)


def need_income(loan_man, ratio, shinsa, years):
    """その借入額を通すのに必要な年収(万円)。"""
    return loan_man * ppm(shinsa, years) * 12 / ratio


def payoff(principal_man, rate, years, extra=0.0):
    """毎月 extra を元金に上乗せしたときの (完済月数, 総利息)。"""
    if principal_man <= 0:
        return 0, 0.0
    i = rate / 100 / 12
    m = principal_man * ppm(rate, years)
    bal, months, interest = principal_man, 0, 0.0
    while bal > 1e-9 and months < years * 12 + 1:
        it = bal * i
        interest += it
        prin = m - it + max(extra, 0)
        months += 1
        if prin >= bal:
            break
        bal -= prin
    return months, interest


def build(a):
    """4ルートの取得力・必要頭金・返済加速を計算する。"""
    net_rent = a.rent * a.noi                      # 賃貸の手取り(万円/月)
    solo = capacity(a.income, a.ratio, a.shinsa, a.years)
    household = a.income + a.partner

    routes = [
        {
            "key": "solo",
            "name": "① 自分ひとりの住宅ローン",
            "capacity": solo,
            "rate": a.rate,
            "note": f"年収{a.income:,.0f}万・返済比率{a.ratio*100:.0f}%・審査金利{a.shinsa}%。ここが出発点",
            "risk": "—",
        },
        {
            "key": "rent_income",
            "name": "② ①＋賃料を年収に算入",
            "capacity": capacity(a.income + a.rent * 12 * a.rent_count,
                                 a.ratio, a.shinsa, a.years),
            "rate": a.rate,
            "note": f"賃料{a.rent:g}万/月の{a.rent_count*100:.0f}%（年{a.rent*12*a.rent_count:.0f}万）を年収に加算。"
                    "算入してくれる金融機関に限る",
            "risk": "増える枠より賃貸化工事費のほうが大きくなりがち（上の判定を参照）",
        },
        {
            "key": "pair",
            "name": "③ ペアローン・収入合算（＋賃料算入）",
            "capacity": capacity(household + a.rent * 12 * a.rent_count,
                                 a.ratio, a.shinsa, a.years) if a.partner else 0,
            "rate": a.rate,
            "note": (f"世帯年収{household:,.0f}万（本人{a.income:,.0f}＋配偶者{a.partner:,.0f}）で審査"
                     if a.partner else "配偶者等の収入がない前提のため算出せず（--partner で指定）"),
            "risk": "離職・離婚・片方の病気で一気に破綻する。団信・持分・贈与税の設計が必須",
        },
        {
            "key": "mixed",
            "name": "④ 世帯年収＋賃貸部分をアパートローン別枠",
            "capacity": 0,  # 後で加算
            "rate": a.biz_rate,
            "note": f"世帯年収の住宅ローン枠（賃料は算入しない）に、賃貸部分だけ"
                    f"金利{a.biz_rate}%・{a.biz_years}年の事業用融資を上乗せ。"
                    f"上乗せ枠は手取り{net_rent:.1f}万/月をDSCR{a.dscr}で割った返済原資から逆算",
            "risk": "総債務が増える。賃貸部分の返済は賃料が止まると即座に自宅家計を直撃",
        },
    ]
    # ④ の上乗せ分：賃料手取りを DSCR で割った額が返済原資。
    #    同じ賃料を「年収算入」と「アパートローンの返済原資」に二重計上しないよう、
    #    土台は賃料を算入しない世帯年収ベースの枠にする。
    biz = (net_rent / a.dscr) / ppm(a.biz_rate, a.biz_years)
    base4 = capacity(household, a.ratio, a.shinsa, a.years)
    routes[3]["capacity"] = base4 + biz
    routes[3]["biz_part"] = biz

    for r in routes:
        r["capacity"] = round(r["capacity"])
        r["total"] = round(r["capacity"] + a.equity)
        r["gap"] = round(max(a.target - r["total"], 0))
        r["reach"] = r["gap"] <= 0
    routes[3]["biz_part"] = round(routes[3]["biz_part"])

    # 賃料算入で増える額 vs 賃貸化工事費 ＝ 取得力の正味増減
    gain = routes[1]["capacity"] - routes[0]["capacity"]
    verdict = {
        "gain": round(gain),
        "reno": a.reno,
        "net": round(gain - a.reno),
        "positive": gain > a.reno,
    }

    # 必要頭金の表（目標価格に対して）
    equity_table = []
    for eq in (0, 1000, 2000, 3000, 4000, 5000):
        loan = max(a.target - eq, 0)
        equity_table.append({
            "equity": eq, "loan": round(loan),
            "income_30": round(need_income(loan, 0.30, a.shinsa, a.years)),
            "income_35": round(need_income(loan, 0.35, a.shinsa, a.years)),
            "income_35_low": round(need_income(loan, 0.35, a.shinsa_low, a.years)),
            "monthly": round(loan * ppm(a.rate, a.years), 1),
        })

    # 返済加速：賃料手取りを全額 元金に充当
    loan = max(a.target - a.equity, 0)
    accel = []
    for extra in (0, net_rent * 0.5, net_rent, net_rent * 1.5):
        mo, inte = payoff(loan, a.rate, a.years, extra)
        accel.append({
            "extra": round(extra, 1),
            "years": round(mo / 12, 1),
            "saved_y": round((a.years * 12 - mo) / 12, 1),
            "interest": round(inte),
        })
    base_int = accel[0]["interest"]
    for x in accel:
        x["interest_saved"] = base_int - x["interest"]

    return {
        "updated": datetime.datetime.now().astimezone().isoformat(),
        "input": vars(a), "net_rent": round(net_rent, 1),
        "routes": routes, "verdict": verdict,
        "equity_table": equity_table, "accel": accel,
        "loan": round(loan),
    }


CSS = """
:root{--bg:#f5f7fa;--card:#fff;--ink:#1b2430;--sub:#5d6b7a;--line:#e3e8ef;--accent:#2563eb;
      --ok:#0f7b52;--warn:#b45309;--ng:#b91c1c}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Hiragino Kaku Gothic ProN",Meiryo,sans-serif;
     margin:0;background:var(--bg);color:var(--ink);line-height:1.65;font-size:15px}
.wrap{max-width:1080px;margin:0 auto;padding:24px 16px 80px}
h1{font-size:1.5rem;margin:0 0 6px}
h2{font-size:1.12rem;margin:34px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--line)}
.lead{color:var(--sub);font-size:.92rem;margin:0 0 18px}
.verdict{border-radius:12px;padding:16px 18px;margin:18px 0;border:1px solid}
.v-ng{background:#fdeaea;border-color:#f0c0c0;color:#7d1d1d}
.v-ok{background:#e6f4ee;border-color:#b6dfcc;color:#0b5236}
.verdict b{font-size:1.05rem}
table{border-collapse:collapse;width:100%;font-size:.88rem;background:#fff;
      border:1px solid var(--line);border-radius:10px;overflow:hidden;margin:10px 0}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:#eef2f7;font-weight:600;color:var(--sub);font-size:.82rem}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.hit td{background:#eaf6f0}
.tag{display:inline-block;font-size:.72rem;padding:2px 7px;border-radius:999px}
.t-ok{background:#e6f4ee;color:var(--ok)}.t-ng{background:#fdeaea;color:var(--ng)}
.risk{color:var(--warn);font-size:.82rem}
.scroll{overflow-x:auto}
.foot{color:var(--sub);font-size:.82rem;margin-top:26px}
a{color:var(--accent)}
@media (prefers-color-scheme:dark){
 :root{--bg:#11161d;--card:#1a212b;--ink:#e6ecf3;--sub:#93a1b1;--line:#2b3644;--accent:#7aa7ff}
 th{background:#222b36} tr.hit td{background:#143126}
 .v-ng{background:#3a1a1a;border-color:#5c2b2b;color:#f0b0b0}
 .v-ok{background:#123a2b;border-color:#1e5c44;color:#8fe0bb}
}
"""


def render(d):
    e = html.escape
    a = d["input"]
    v = d["verdict"]

    vclass = "v-ok" if v["positive"] else "v-ng"
    vtext = (f"<b>賃料を年収に算入すると借入可能額は +{v['gain']:,}万円。"
             f"賃貸化工事費 {v['reno']:,.0f}万円を引いて、正味 {v['net']:+,}万円。</b><br>"
             + ("工事費を上回るので、取得力はわずかに増える。"
                "ただし増えるのは数百万円規模であって、エリアを一段上げられる額ではない。"
                if v["positive"] else
                "<b>つまり、1階を貸すことで買える価格は上がらない。むしろ下がる。</b><br>"
                "賃料の年収算入で増える借入枠より、賃貸化に要る工事費のほうが大きいため。"
                "「自分のローンでは都心に届かないから1階を貸す」という筋道は、ここで成立しない。"))

    rrows = "".join(
        f"""<tr class="{'hit' if r['reach'] else ''}">
 <td>{e(r['name'])}<div class="risk">{e(r['risk'])}</div></td>
 <td class="num">{r['capacity']:,}</td>
 <td class="num">{r['total']:,}</td>
 <td class="num">{'<span class="tag t-ok">届く</span>' if r['reach'] else f'<span class="tag t-ng">-{r["gap"]:,}万</span>'}</td>
 <td>{e(r['note'])}</td></tr>""" for r in d["routes"])

    erows = "".join(
        f"""<tr><td class="num">{x['equity']:,}</td><td class="num">{x['loan']:,}</td>
 <td class="num">{x['monthly']}</td><td class="num">{x['income_30']:,}</td>
 <td class="num">{x['income_35']:,}</td><td class="num">{x['income_35_low']:,}</td></tr>"""
        for x in d["equity_table"])

    arows = "".join(
        f"""<tr class="{'hit' if i == 2 else ''}">
 <td>{'返済のみ（賃料を使わない）' if i == 0 else f'賃料手取りの{[0,50,100,150][i]}% を元金充当'}</td>
 <td class="num">{x['extra']}</td><td class="num">{x['years']}</td>
 <td class="num">{'—' if i == 0 else f"-{x['saved_y']}"}</td>
 <td class="num">{x['interest']:,}</td>
 <td class="num">{'—' if i == 0 else f"-{x['interest_saved']:,}"}</td></tr>"""
        for i, x in enumerate(d["accel"]))

    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>取得力と返済加速のプラン — 1階賃貸で都心に届くか</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>1階を貸せば都心に届くか、そしてローンは早く終わるか</h1>
<p class="lead">
 世帯の前提：本人年収 {a['income']:,.0f}万円{f"／配偶者 {a['partner']:,.0f}万円" if a['partner'] else ""}、
 自己資金 {a['equity']:,.0f}万円、目標の総事業費 {a['target']:,.0f}万円、
 1階の想定賃料 {a['rent']:g}万円/月（手取り {d['net_rent']}万円）。
 考え方は <a href="./rental_hybrid.md">rental_hybrid.md</a>、
 物件ごとの試算は <a href="./hybrid.html">hybrid.html</a>。
</p>

<div class="verdict {vclass}">{vtext}</div>

<h2>問1：借りられる額は増えるか（4ルートの取得力）</h2>
<div class="scroll"><table>
<tr><th>ルート</th><th class="num">借入可能<br>万円</th><th class="num">＋自己資金<br>万円</th>
    <th class="num">目標{a['target']:,.0f}万に</th><th>前提</th></tr>
{rrows}</table></div>
<p class="lead">
 借入可能額は<b>実行金利ではなく審査金利（{a['shinsa']}%）で決まる</b>。
 変動0.7%で借りるつもりでも、返済比率は3〜4%で測られる。ここが取得力の天井。
</p>

<h2>目標 {a['target']:,.0f}万円に必要な頭金と年収</h2>
<div class="scroll"><table>
<tr><th class="num">自己資金<br>万円</th><th class="num">借入<br>万円</th>
    <th class="num">月返済<br>（{a['rate']}%）万</th>
    <th class="num">必要年収<br>比率30%</th><th class="num">必要年収<br>比率35%</th>
    <th class="num">必要年収<br>比率35%・審査{a['shinsa_low']}%</th></tr>
{erows}</table></div>
<p class="lead">
 返済比率35%は審査上の上限であって安全圏ではない。金利が上がると即座に苦しくなる。
 審査金利は金融機関により差があり、固定金利型では実行金利に近い値で見る先もある。
 <b>この表の一番効く列は「審査金利」</b>＝取扱行を複数当たる価値がここにある。
</p>

<h2>問2：ローンは早く終わるか（賃料手取りを元金に充当）</h2>
<div class="scroll"><table>
<tr><th>使い方</th><th class="num">月の上乗せ<br>万円</th><th class="num">完済<br>年</th>
    <th class="num">短縮<br>年</th><th class="num">総利息<br>万円</th><th class="num">利息削減<br>万円</th></tr>
{arows}</table></div>
<p class="lead">
 借入 {d['loan']:,}万円・金利{a['rate']}%・{a['years']}年が前提。
 <b>ここが賃貸併用の本当の効き目。</b>取得力はほとんど増えないが、返済期間は明確に縮む。
 繰上返済は「期間短縮型」を選ぶこと（返済額軽減型では利息削減が小さくなる）。
 ただし<b>手取りを全額つぎ込む前に、修繕・空室・原状回復の備えを先に積む</b>。
 1戸しかない賃貸は、空けば収入がゼロになる。
</p>

<h2>この計算の使い方</h2>
<p class="lead">
 数字を自分の条件に置き換えて再実行する。<br>
 <code>python3 scripts/loan_plan.py --income {a['income']:g} --partner {a['partner']:g} --equity {a['equity']:g} --target {a['target']:g} --rent {a['rent']:g}</code><br>
 賃料を年収に算入してくれる金融機関が見つかったら <code>--rent-count 0.8</code>、
 審査金利が低い先なら <code>--shinsa 3.0</code> を指定して、判断がどこで反転するかを見る。
</p>

<p class="foot">
 生成 {e(d['updated'][:16])}。本ページは学習・比較のための試算であり、
 投資勧誘でも税務・法務の助言でもない。金利・審査基準・賃料はすべて仮定値であり、
 実際の借入可能額は金融機関の審査によってのみ確定する。事前審査で確認すること。
</p>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="取得力と返済加速のプランナー")
    ap.add_argument("--income", type=float, default=800, help="本人の年収(万円)")
    ap.add_argument("--partner", type=float, default=0, help="配偶者等の年収(万円)。0ならペアローンは算出しない")
    ap.add_argument("--equity", type=float, default=2000, help="自己資金(万円)")
    ap.add_argument("--target", type=float, default=10800, help="目標の総事業費(万円・諸費用と工事費込み)")
    ap.add_argument("--rent", type=float, default=12, help="1階の想定賃料(万円/月)")
    ap.add_argument("--reno", type=float, default=550, help="賃貸化工事費(万円)")
    ap.add_argument("--noi", type=float, default=0.77, help="賃料の手取り率")
    ap.add_argument("--rate", type=float, default=1.0, help="住宅ローンの実行金利(%)")
    ap.add_argument("--years", type=int, default=35, help="返済期間(年)")
    ap.add_argument("--ratio", type=float, default=0.30, help="返済比率")
    ap.add_argument("--shinsa", type=float, default=3.5, help="審査金利(%)")
    ap.add_argument("--shinsa-low", type=float, default=2.0, help="比較用の低い審査金利(%)")
    ap.add_argument("--rent-count", type=float, default=0.8, help="賃料の年収算入率")
    ap.add_argument("--biz-rate", type=float, default=2.8, help="アパートローン金利(%)")
    ap.add_argument("--biz-years", type=int, default=25, help="アパートローン期間(年)")
    ap.add_argument("--dscr", type=float, default=1.25, help="賃貸部分に求める債務返済カバー率")
    a = ap.parse_args()

    d = build(a)
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump(d, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(OUT_HTML, "w", encoding="utf-8").write(render(d))

    print(f"目標 {a.target:,.0f}万円 / 自己資金 {a.equity:,.0f}万円")
    for r in d["routes"]:
        mark = "届く" if r["reach"] else f"-{r['gap']:,.0f}万"
        print(f"  {r['name']:36s} 借入可能 {r['capacity']:7,.0f}万 ＋自己資金 {r['total']:7,.0f}万  {mark}")
    v = d["verdict"]
    print(f"\n賃料の年収算入で増える枠 +{v['gain']:,}万 − 賃貸化工事費 {v['reno']:,.0f}万 "
          f"＝ 正味 {v['net']:+,}万（取得力は{'増える' if v['positive'] else '増えない'}）")
    print("\n返済加速（賃料手取りを元金充当）:")
    for i, x in enumerate(d["accel"]):
        if i == 0:
            print(f"  上乗せなし          → 完済 {x['years']}年  総利息 {x['interest']:,}万")
        else:
            print(f"  月+{x['extra']:.1f}万を元金充当 → 完済 {x['years']}年（-{x['saved_y']}年） "
                  f"利息 -{x['interest_saved']:,}万")
    print(f"\n→ {OUT_HTML}, {OUT_JSON}")


if __name__ == "__main__":
    main()
