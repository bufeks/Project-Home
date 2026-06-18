#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SUUMO 東京23区の「訳あり寄り」中古戸建を取得して
listings.html / data/listings.json を生成する。

- 取得元：SUUMO 中古一戸建て 一覧(JJ012FC001) を キーワード別に取得
- 23区のみ抽出 / 価格で昇順 / 重複排除
- 失敗したソースはスキップして他を継続（落ちない）

注意：個人利用の低頻度(1日1回程度)取得を想定。過度な連続アクセスはしない。
"""
import json, re, sys, time, html as H, urllib.parse, urllib.request, datetime, pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent                      # tokyo-land-research/
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

UA = "Mozilla/5.0 (compatible; tokyo-land-research/1.0; personal research)"

# 23区
WARDS = ["千代田区","中央区","港区","新宿区","文京区","台東区","墨田区","江東区",
         "品川区","目黒区","大田区","世田谷区","渋谷区","中野区","杉並区","豊島区",
         "北区","荒川区","板橋区","練馬区","足立区","葛飾区","江戸川区"]

# (カテゴリ表示名, SUUMO検索キーワード)  /b/kodate/kw/ 解決でキーワードが厳密適用される。
# ※ このリゾルバは特定のキーワード組み合わせのみ有効（無効な組合せは404）。
#    動作確認済みの組合せのみを採用している。
SOURCES = [
    ("再建築不可", "東京23区 再建築不可 中古 戸建て"),
    ("借地権",     "旧法 借地権 中古 戸建 23区"),
    ("古家付き",   "東京23区 古家付 土地"),
]
KW_BASE = "https://suumo.jp/b/kodate/kw/"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
        "Accept-Language": "ja,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def text(s):
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


LINK_RE = re.compile(
    r'href="(https://suumo\.jp/(?:chukoikkodate|ikkodate|tochi)/[^"]+/nc_(\d+)/)[^"]*"'
    r'\s+class="cassette-title')


def parse(htmltext, category):
    """SUUMO /b/kodate/kw/ の cassette レイアウトを解析。"""
    out = {}
    for m in LINK_RE.finditer(htmltext):
        nid = m.group(2)
        if nid in out:
            continue
        t = text(htmltext[m.start():m.start() + 3000])   # 1物件ぶんの窓
        mp = re.search(r"販売価格\s*([0-9,]+)万円", t) or re.search(r"([0-9,]+)万円", t)
        ma = re.search(r"所在地\s*東京都\s*([^\s]+?[区市][^\s]*)", t)
        if not (mp and ma):
            continue
        loc = ma.group(1)
        ward = next((w for w in WARDS if loc.startswith(w)), None)
        if not ward:                      # 23区以外は除外
            continue
        land = re.search(r"土地面積\s*([0-9.]+)", t)
        bld = re.search(r"建物面積\s*([0-9.]+)", t)
        sta = re.search(r"沿線・駅\s*(\S+?「[^」]+」\S*?歩\s*\d+分)", t)
        plan = re.search(r"間取り\s*(\d+[SLDK]+)", t)
        out[nid] = dict(
            id=nid, category=category, ward=ward, loc=loc,
            price=int(mp.group(1).replace(",", "")),
            land=(land.group(1) + "㎡") if land else "",
            bld=(bld.group(1) + "㎡") if bld else "",
            plan=plan.group(1) if plan else "",
            station=sta.group(1) if sta else "",
            url=m.group(1),
        )
    return list(out.values())


def collect():
    all_rows, errors = {}, []
    for cat, kw in SOURCES:
        url = KW_BASE + urllib.parse.quote(kw) + "/"
        try:
            rows = parse(fetch(url), cat)
        except Exception as e:                           # 404等はスキップ
            errors.append(f"{cat}「{kw}」: {e}")
            time.sleep(1.0)
            continue
        for r in rows:
            # 同一物件が複数カテゴリに出たらカテゴリを併記
            if r["id"] in all_rows:
                ex = all_rows[r["id"]]
                if cat not in ex["category"]:
                    ex["category"] += "/" + cat
            else:
                all_rows[r["id"]] = r
        time.sleep(1.3)                                  # 礼儀的な間隔
    rows = sorted(all_rows.values(), key=lambda x: x["price"])
    return rows, errors


def tsuubo(price, land):
    m = re.search(r"([0-9.]+)", land or "")
    if not m:
        return ""
    tsubo = float(m.group(1)) / 3.30578
    if tsubo <= 0:
        return ""
    return f"約{round(price / tsubo)}万/坪"


def render(rows, errors):
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    stamp = now.strftime("%Y-%m-%d %H:%M JST")
    wards = sorted({r["ward"] for r in rows}, key=lambda w: WARDS.index(w))
    cats = ["再建築不可", "借地権", "狭小", "古家付き"]

    rowhtml = []
    for r in rows:
        rowhtml.append(
            f'<tr data-ward="{r["ward"]}" data-cat="{r["category"]}" data-price="{r["price"]}">'
            f'<td>{r["ward"]}</td><td>{H.escape(r["loc"])}</td>'
            f'<td class="num">{r["price"]:,}万円</td>'
            f'<td>{r["land"]}</td><td>{r["bld"]}</td>'
            f'<td>{H.escape(r["plan"])}</td>'
            f'<td class="cat">{H.escape(r["category"])}</td>'
            f'<td>{H.escape(r["station"])}</td>'
            f'<td><a href="{r["url"]}" target="_blank" rel="noopener">SUUMO↗</a></td></tr>'
        )
    cat_opts = "".join(f'<option value="{c}">{c}</option>' for c in cats)
    ward_opts = "".join(f'<option value="{w}">{w}</option>' for w in wards)
    err = ("<p class='lead'>取得エラー: " + H.escape("; ".join(errors)) + "</p>") if errors else ""

    return TEMPLATE.format(stamp=stamp, count=len(rows), rows="\n".join(rowhtml),
                           cat_opts=cat_opts, ward_opts=ward_opts, err=err)


TEMPLATE = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>最新物件一覧（東京23区・訳あり中古戸建）｜自動更新</title>
<style>
  :root{{--bg:#0f1115;--panel:#171a21;--panel2:#1d2129;--ink:#e9edf3;--muted:#9aa4b2;--line:#2a2f3a;--accent:#6ea8fe;--accent2:#7ee0c0}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP","Yu Gothic",Meiryo,sans-serif;line-height:1.6}}
  .wrap{{max-width:1100px;margin:0 auto;padding:18px}}
  h1{{font-size:1.4rem;margin:.2em 0}}
  .meta{{color:var(--muted);font-size:.85rem;margin-bottom:14px}}
  a{{color:var(--accent)}}
  .bar{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:14px}}
  select,input{{background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:7px 10px;font-size:.9rem}}
  .bar label{{font-size:.8rem;color:var(--muted);margin-right:4px}}
  .tablewrap{{overflow-x:auto;border:1px solid var(--line);border-radius:12px}}
  table{{border-collapse:collapse;width:100%;font-size:.86rem;min-width:760px}}
  th,td{{padding:9px 11px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}
  thead th{{background:#212732;position:sticky;top:0;cursor:pointer;user-select:none}}
  thead th:hover{{color:#bcd6ff}}
  td.num,th.num{{text-align:right}}
  td.cat{{color:var(--accent2);font-size:.8rem;white-space:normal}}
  tbody tr:hover{{background:#1b2029}}
  .note{{background:var(--panel2);border:1px solid var(--line);border-left:4px solid var(--accent2);border-radius:10px;padding:10px 14px;font-size:.85rem;color:#dfe5ee;margin:14px 0}}
  .pill{{display:inline-block;background:#24303f;color:var(--accent);border:1px solid #2f4154;border-radius:999px;padding:1px 10px;font-size:.78rem;margin-right:6px}}
</style></head><body><div class="wrap">
<p><a href="./index.html">← まとめ(index.html)へ戻る</a></p>
<h1>最新物件一覧 — 東京23区・訳あり中古戸建</h1>
<p class="meta">出典：SUUMO（再建築不可・借地権・狭小・古家付きの中古戸建を23区で抽出）／
<b>最終更新：{stamp}</b>／ 表示 <b>{count}</b> 件 ／ 毎日自動更新</p>
<div class="bar">
  <span><label>区</label><select id="fward"><option value="">すべて</option>{ward_opts}</select></span>
  <span><label>種別</label><select id="fcat"><option value="">すべて</option>{cat_opts}</select></span>
  <span><label>価格上限(万円)</label><input id="fmax" type="number" inputmode="numeric" placeholder="例 3000" style="width:120px"></span>
  <span class="pill" id="shown"></span>
</div>
<div class="tablewrap"><table id="t">
<thead><tr>
<th data-k="ward">区</th><th data-k="loc">所在地</th><th data-k="price" class="num">価格 ▲</th>
<th data-k="land">土地</th><th data-k="bld">建物</th><th data-k="plan">間取</th>
<th data-k="cat">安い理由(種別)</th><th data-k="station">最寄</th><th>リンク</th>
</tr></thead>
<tbody>
{rows}
</tbody></table></div>
{err}
<div class="note">⚠️ 価格・在庫は変動します。SUUMOの一覧から自動抽出した<b>最新スナップショット</b>です。
個別物件はリンク先で必ず最新状態・権利関係・接道・再建築可否を確認してください。
判断手順は <a href="./index.html">index.html</a> の「物件チェックリスト／リスク判定」を参照。
公売・競売・国有地など他ルートの最新情報は index.html 上部の「実際の物件を見る」リンク集から。</div>
<script>
const tb=document.querySelector('#t tbody'), rows=[...tb.rows];
const fward=fward0(), fcat=document.getElementById('fcat'), fmax=document.getElementById('fmax');
function fward0(){{return document.getElementById('fward')}}
function apply(){{
  const w=fward.value,c=fcat.value,m=parseInt(fmax.value||'0',10);let n=0;
  for(const r of rows){{
    let ok=true;
    if(w&&r.dataset.ward!==w)ok=false;
    if(c&&!r.dataset.cat.includes(c))ok=false;
    if(m&&parseInt(r.dataset.price,10)>m)ok=false;
    r.style.display=ok?'':'none'; if(ok)n++;
  }}
  document.getElementById('shown').textContent=n+' 件表示';
}}
[fward,fcat,fmax].forEach(e=>e.addEventListener('input',apply));
let asc={{}};
document.querySelectorAll('thead th[data-k]').forEach(th=>th.addEventListener('click',()=>{{
  const k=th.dataset.k; asc[k]=!asc[k];
  const num=(k==='price');
  rows.sort((a,b)=>{{
    let x,y;
    if(num){{x=+a.dataset.price;y=+b.dataset.price;}}
    else{{x=a.querySelector('td:nth-child('+(idx(k)+1)+')').textContent;
          y=b.querySelector('td:nth-child('+(idx(k)+1)+')').textContent;}}
    return (x>y?1:x<y?-1:0)*(asc[k]?1:-1);
  }});
  rows.forEach(r=>tb.appendChild(r));
}}));
function idx(k){{return ['ward','loc','price','land','bld','plan','cat','station'].indexOf(k)}}
apply();
</script>
</div></body></html>"""


def main():
    rows, errors = collect()
    (DATA / "listings.json").write_text(
        json.dumps({"updated": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9))).isoformat(),
            "count": len(rows), "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (ROOT / "listings.html").write_text(render(rows, errors), encoding="utf-8")
    print(f"wrote {len(rows)} listings; errors={len(errors)}")
    for e in errors:
        print("  ERR", e, file=sys.stderr)


if __name__ == "__main__":
    main()
