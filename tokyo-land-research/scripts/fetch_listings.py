#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
東京23区「割安×資産性（売却益狙い）」物件スクリーナーを生成する。

コンセプト（脱・ゲテモノ）:
  ・主役は「都心〜準都心で、相場より割安で、駅近・流動性があり、将来の売却益が狙える」物件。
  ・再建築不可・借地権・古家付きは“主役”にせず、資産性を下げる「注意タグ」として扱う。
  ・各物件に簡易の「資産スコア（売却益ポテンシャル目安）」を付け、スコア順で並べる。

データ元（自動取得）:
  ・SUUMO 中古戸建（23区・価格安い順）… 通常物件の母集団（property_unit レイアウト）
  ・SUUMO 土地/再建築不可/借地/古家 … 種別・注意タグの付与（cassette レイアウト）

※ cowcamo / HOME'S / 楽待 / at home / 健美家 は自動取得が困難（SPA・アクセス制限）なため、
  HTML側に「キュレーション・リンク」として併設する（listings側の CURATED 参照）。

スコア・相場は簡易な“目安”。実際の売買判断前に必ず現地・専門家確認を。
"""
import json, re, sys, time, gzip, html as H, urllib.parse, urllib.request, datetime, pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

WARDS = ["千代田区","中央区","港区","新宿区","文京区","台東区","墨田区","江東区",
         "品川区","目黒区","大田区","世田谷区","渋谷区","中野区","杉並区","豊島区",
         "北区","荒川区","板橋区","練馬区","足立区","葛飾区","江戸川区"]
WARD_CODES = [str(c) for c in range(13101, 13124)]   # 13101..13123

# エリアティア（売却益の“出口の堅さ”の目安）
TIER = {w: "S" for w in ["千代田区","中央区","港区","渋谷区"]}
TIER.update({w: "A" for w in ["新宿区","文京区","目黒区","品川区","世田谷区","台東区","豊島区","中野区"]})
TIER.update({w: "B" for w in ["杉並区","墨田区","江東区","大田区","北区","荒川区","板橋区"]})
TIER.update({w: "C" for w in ["練馬区","足立区","葛飾区","江戸川区"]})
TIER_MEMO = {
    "S": "都心中枢。希少性・流動性が高く下値が堅い＝売却益の出口が最も堅い",
    "A": "人気住宅地・準都心。実需が厚く資産性が安定。再開発で上振れも",
    "B": "割安で実需厚め。駅近・再開発を選べば値上がり余地あり",
    "C": "価格は控えめ。駅近・整形地・再開発など条件を厳選すれば妙味",
}
# ざっくり中古戸建の土地相場（万円/坪・目安）。割安度判定の基準。
WARD_TSUBO = {
    "千代田区":900,"中央区":700,"港区":850,"新宿区":520,"文京区":480,"台東区":430,
    "墨田区":330,"江東区":350,"品川区":430,"目黒区":520,"大田区":330,"世田谷区":400,
    "渋谷区":800,"中野区":400,"杉並区":360,"豊島区":400,"北区":320,"荒川区":320,
    "板橋区":290,"練馬区":270,"足立区":220,"葛飾区":220,"江戸川区":240,
}

# 通常物件（母集団）: SUUMO 中古戸建 23区・価格安い順
AREA_URL = "https://suumo.jp/jj/bukken/ichiran/JJ012FC001/"
AREA_PAGES = 3
# 種別・注意タグ付与: SUUMO /b/kodate/kw/（解決可能な組合せのみ）
KW_BASE = "https://suumo.jp/b/kodate/kw/"
KW_SOURCES = [
    ("土地",        "東京23区 土地",            None),
    ("再建築不可",  "東京23区 再建築不可 中古 戸建て", "再建築不可"),
    ("借地権",      "旧法 借地権 中古 戸建 23区",     "借地権"),
    ("古家付き",    "東京23区 古家付 土地",          "古家付き"),
]


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "ja,en;q=0.8",
        "Accept": "text/html,*/*"})
    d = urllib.request.urlopen(req, timeout=30).read()
    try:
        d = gzip.decompress(d)
    except Exception:
        pass
    return d.decode("utf-8", "ignore")


def text(s):
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


PRICE_TOK = re.compile(r"(?:([0-9]+)\s*億)?\s*([0-9,]+)?\s*万円(／坪|/坪)?")


def max_price(t):
    """テキスト中の最大の販売価格(万円)を億対応で返す。坪単価(／坪)は除外。"""
    best = None
    for m in PRICE_TOK.finditer(t):
        if m.group(3):                       # ／坪 は坪単価なので除外
            continue
        if m.group(1) is None and m.group(2) is None:
            continue
        val = (int(m.group(1)) * 10000 if m.group(1) else 0) + \
              (int(m.group(2).replace(",", "")) if m.group(2) else 0)
        if val and (best is None or val > best):
            best = val
    return best


def fmt_price(man):
    if man is None:
        return "?"
    if man >= 10000:
        oku, rest = divmod(man, 10000)
        return f"{oku}億{rest:,}万円" if rest else f"{oku}億円"
    return f"{man:,}万円"


def ward_of(loc):
    return next((w for w in WARDS if loc and w in loc[:6]), None)


def base_row(nid, source, kind, ward, loc, price, land, bld, plan, walk, url):
    return dict(id=nid, source=source, kind=kind, ward=ward, loc=loc, price=price,
                land=land, bld=bld, plan=plan, walk=walk, url=url, tags=[])


def parse_area(htmltext):
    """SUUMO property_unit レイアウト（中古戸建 一覧）。"""
    rows = {}
    for b in htmltext.split('class="property_unit')[1:]:
        ml = re.search(r'href="(/(?:chukoikkodate|ikkodate)/[^"]+/nc_(\d+)/)"', b)
        if not ml or "万円" not in b:
            continue
        nid = ml.group(2)
        if nid in rows:
            continue
        t = text(b)
        price = max_price(t)
        ma = re.search(r"東京都\s*([^\s]+?区[^\s]*)", t)
        if not (price and ma):
            continue
        ward = ward_of(ma.group(1))
        if not ward:
            continue
        land = re.search(r"土地面積\s*([0-9.]+)", t)
        bld = re.search(r"建物面積\s*([0-9.]+)", t)
        walk = re.search(r"「[^」]+」[^\s]*?歩\s*(\d+)分", t)
        plan = re.search(r"\b(\d+[SLDK]+)\b", t)
        rows[nid] = base_row(
            nid, "SUUMO戸建", "戸建", ward, ma.group(1), price,
            float(land.group(1)) if land else None,
            float(bld.group(1)) if bld else None,
            plan.group(1) if plan else "",
            int(walk.group(1)) if walk else None,
            "https://suumo.jp" + ml.group(1))
    return list(rows.values())


CASS_LINK = re.compile(
    r'href="(https://suumo\.jp/(?:chukoikkodate|ikkodate|tochi)/[^"]+/nc_(\d+)/)[^"]*"'
    r'\s+class="cassette-title')


def parse_cassette(htmltext, kind):
    """SUUMO /b/kodate/kw/ の cassette レイアウト。"""
    rows = {}
    for m in CASS_LINK.finditer(htmltext):
        nid = m.group(2)
        if nid in rows:
            continue
        t = text(htmltext[m.start():m.start() + 3000])
        price = max_price(t)
        ma = re.search(r"所在地\s*東京都\s*([^\s]+?[区市][^\s]*)", t)
        if not (price and ma):
            continue
        ward = ward_of(ma.group(1))
        if not ward:
            continue
        land = re.search(r"土地面積\s*([0-9.]+)", t)
        bld = re.search(r"建物面積\s*([0-9.]+)", t)
        walk = re.search(r"「[^」]+」[^\s]*?歩\s*(\d+)分", t)
        plan = re.search(r"間取り\s*(\d+[SLDK]+)", t)
        k = "土地" if "/tochi/" in m.group(1) else "戸建"
        rows[nid] = base_row(
            nid, "SUUMO土地" if k == "土地" else "SUUMO戸建", k, ward, ma.group(1), price,
            float(land.group(1)) if land else None,
            float(bld.group(1)) if bld else None,
            plan.group(1) if plan else "",
            int(walk.group(1)) if walk else None,
            m.group(1))
    return list(rows.values())


def collect():
    merged, errors = {}, []

    def add(rows, tag=None):
        for r in rows:
            cur = merged.get(r["id"])
            if cur is None:
                merged[r["id"]] = r
                cur = r
            else:
                # 面積など欠損を補完
                for k in ("land", "bld", "plan", "walk"):
                    if not cur.get(k) and r.get(k):
                        cur[k] = r[k]
            if tag and tag not in cur["tags"]:
                cur["tags"].append(tag)

    # 1) 通常物件の母集団（中古戸建・価格安い順）
    for pn in range(1, AREA_PAGES + 1):
        q = [("ar", "030"), ("bs", "021"), ("ta", "13")] + \
            [("sc", w) for w in WARD_CODES] + [("po", "1"), ("pn", str(pn))]
        url = AREA_URL + "?" + urllib.parse.urlencode(q)
        try:
            add(parse_area(fetch(url)))
        except Exception as e:
            errors.append(f"area p{pn}: {e}")
        time.sleep(1.3)

    # 2) 種別・注意タグ
    for _cat, kw, tag in KW_SOURCES:
        url = KW_BASE + urllib.parse.quote(kw) + "/"
        try:
            add(parse_cassette(fetch(url), _cat), tag=tag)
        except Exception as e:
            errors.append(f"{_cat}: {e}")
        time.sleep(1.3)

    rows = list(merged.values())
    for r in rows:
        enrich(r)
    rows.sort(key=lambda x: (-x["score"], x["price"]))
    return rows, errors


def tsubo_unit(price, land):
    if not land or land <= 0:
        return None
    return price / (land / 3.30578)          # 万円/坪


def enrich(r):
    ward = r["ward"]
    tier = TIER.get(ward, "C")
    r["tier"] = tier
    tp = tsubo_unit(r["price"], r["land"])
    r["tsubo"] = round(tp) if tp else None
    med = WARD_TSUBO.get(ward)
    ratio = (med / tp) if (tp and med) else None
    r["ratio"] = round(ratio, 2) if ratio else None

    # 割安度 (0-40)
    if ratio is None:
        s_w = 15
    else:
        s_w = (40 if ratio >= 1.6 else 34 if ratio >= 1.4 else 28 if ratio >= 1.25
               else 22 if ratio >= 1.1 else 17 if ratio >= 1.0 else 11 if ratio >= 0.9
               else 6 if ratio >= 0.8 else 3)
    # 駅近 (0-25)
    w = r["walk"]
    s_e = (10 if w is None else 25 if w <= 3 else 22 if w <= 5 else 18 if w <= 7
           else 14 if w <= 10 else 9 if w <= 15 else 5)
    # 出口（エリアティア, 0-25）
    s_t = {"S": 25, "A": 19, "B": 13, "C": 9}[tier]
    # 規模 (0-10)
    land = r["land"]
    s_s = (4 if land is None else 10 if land >= 60 else 8 if land >= 40
           else 5 if land >= 25 else 3 if land >= 15 else 2)
    score = s_w + s_e + s_t + s_s
    # 注意タグの減点（資産性・流動性を下げる）
    if "再建築不可" in r["tags"]:
        score -= 20
    if "借地権" in r["tags"]:
        score -= 12
    if "古家付き" in r["tags"]:
        score -= 2
    r["score"] = max(0, min(100, score))
    r["grade"] = ("高" if r["score"] >= 78 else "中高" if r["score"] >= 62
                  else "中" if r["score"] >= 48 else "低")

    bits = []
    if r["ratio"]:
        bits.append(f"相場比{r['ratio']}倍" + ("（割安）" if r["ratio"] >= 1.1 else "（相場並〜割高）"))
    if w is not None:
        bits.append(f"駅徒歩{w}分")
    bits.append(f"出口{tier}")
    if "再建築不可" in r["tags"]:
        bits.append("再建築不可→流動性難")
    if "借地権" in r["tags"]:
        bits.append("借地→融資/出口難")
    r["comment"] = " / ".join(bits)


# ------- HTML 出力 -------
CURATED = [
    ("cowcamo（カウカモ）", "https://cowcamo.jp/", "リノベ・デザイン重視の都心物件。SPAのため自動一覧は不可→公式で閲覧"),
    ("HOME'S 23区 中古戸建", "https://www.homes.co.jp/kodate/tokyo/23ku-city/list/", "大手ポータル（自動取得はブロック）"),
    ("at home 中古戸建 東京", "https://www.athome.co.jp/kodate/chuko/tokyo/list/", "大手ポータル（自動取得は要追加対応）"),
    ("楽待（投資）", "https://www.rakumachi.jp/syuuekibukken/area/prefecture/13/", "投資物件（JS描画のため自動取得不可）"),
    ("健美家（投資）", "https://www.kenbiya.com/", "投資物件（再建築不可など訳あり寄り）"),
    ("SUUMO 23区 中古戸建", "https://suumo.jp/jj/bukken/ichiran/JJ012FC001/?ar=030&bs=021&ta=13&sc=13101&po=1", "この一覧の母集団（公式で最新確認）"),
]


def render(rows, errors):
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    stamp = now.strftime("%Y-%m-%d %H:%M JST")
    wards = sorted({r["ward"] for r in rows}, key=lambda w: WARDS.index(w))

    def gcolor(g):
        return {"高": "g-hi", "中高": "g-mh", "中": "g-mid", "低": "g-lo"}[g]

    from collections import Counter
    cnt = Counter(r["ward"] for r in rows)

    cards = []
    for r in rows:
        tags = "".join(f'<span class="tag">{H.escape(t)}</span>' for t in r["tags"])
        area = []
        if r["land"]:
            area.append(f'土{r["land"]:.0f}㎡')
        if r["bld"]:
            area.append(f'建{r["bld"]:.0f}㎡')
        if r["plan"]:
            area.append(H.escape(r["plan"]))
        area_s = " ".join(area) or "—"
        ratio = r["ratio"]
        ratio_s = f'{ratio}倍' if ratio else "—"
        walk = r["walk"]
        walk_s = f'{walk}分' if walk is not None else "—"
        tsubo_s = f'{r["tsubo"]}万/坪' if r["tsubo"] else "—"
        # 相場比バー（0.8→0%, 1.8→100%）。1.1以上=割安(緑)/1.0-1.1=並(黄)/未満=割高(赤)
        if ratio:
            fill = max(4, min(100, round((ratio - 0.8) / 1.0 * 100)))
            rcol = "#3fbf8f" if ratio >= 1.1 else "#e6b13c" if ratio >= 1.0 else "#e06a82"
        else:
            fill, rcol = 0, "#2a2f3a"
        risky = ("再建築不可" in r["tags"]) or ("借地権" in r["tags"])
        badges = []
        if r["score"] >= 78:
            badges.append('<span class="bdg b-top">★高評価</span>')
        if (ratio and ratio >= 1.3) and (walk is not None and walk <= 7) and not risky:
            badges.append('<span class="bdg b-gem">💎穴場候補</span>')
        if risky:
            badges.append('<span class="bdg b-warn">⚠落とし穴</span>')
        badges_s = "".join(badges)
        cards.append(
            f'<article class="card" data-ward="{r["ward"]}" data-price="{r["price"]}" '
            f'data-score="{r["score"]}" data-tags="{H.escape("|".join(r["tags"]))}" '
            f'data-kind="{r["kind"]}" data-ratio="{ratio or 0}" '
            f'data-walk="{walk if walk is not None else 999}" data-tsubo="{r["tsubo"] or 0}">'
            f'<div class="ctop t{r["tier"]}">'
            f'<div class="ci"><div class="price">{fmt_price(r["price"])}</div>'
            f'<div class="loc"><span class="tier t{r["tier"]}">{r["tier"]}</span>'
            f'{H.escape(r["loc"])}<span class="kindchip">{r["kind"]}</span></div></div>'
            f'<div class="ring" style="--p:{r["score"]}"><b>{r["score"]}</b><small>資産</small></div>'
            f'</div>'
            f'{f"<div class=bd>{badges_s}</div>" if badges_s else ""}'
            f'<div class="facts">'
            f'<div class="f"><span>相場比</span><b>{ratio_s}</b>'
            f'<div class="rbar"><i style="width:{fill}%;background:{rcol}"></i></div></div>'
            f'<div class="f"><span>坪単価</span><b>{tsubo_s}</b></div>'
            f'<div class="f"><span>駅徒歩</span><b>{walk_s}</b></div>'
            f'<div class="f"><span>面積 / 間取</span><b>{area_s}</b></div>'
            f'<div class="f"><span>出口の堅さ</span><b>{r["tier"]}ティア</b></div>'
            f'<div class="f"><span>評価</span><b class="grade {gcolor(r["grade"])}">{r["grade"]}</b></div>'
            f'</div>'
            f'{f"<div class=tags>{tags}</div>" if tags else ""}'
            f'<div class="cmt">{H.escape(r["comment"])}</div>'
            f'<a class="view" href="{r["url"]}" target="_blank" rel="noopener">SUUMOで詳細を見る ↗</a>'
            f'</article>')

    ward_opts = "".join(f'<option value="{w}">{w}（{cnt.get(w,0)}）</option>' for w in wards)

    # 学び①：ティア別「区の相場坪単価」早見表
    mt = []
    for tier in ["S", "A", "B", "C"]:
        ws = [w for w in WARDS if TIER.get(w, "C") == tier]
        cells = "".join(
            f'<div class="mw"><span class="tier t{tier}">{tier}</span>{w}'
            f'<b>{WARD_TSUBO.get(w,"—")}万/坪</b><small>{cnt.get(w,0)}件</small></div>'
            for w in ws)
        mt.append(
            f'<div class="mrow"><div class="mlabel t{tier}">{tier}'
            f'<small>{H.escape(TIER_MEMO[tier])}</small></div>'
            f'<div class="mws">{cells}</div></div>')
    market = "".join(mt)

    curated = "".join(
        f'<a class="cu" href="{u}" target="_blank" rel="noopener"><b>{H.escape(n)} ↗</b>'
        f'<span>{H.escape(d)}</span></a>' for n, u, d in CURATED)
    err = ("<p class='lead'>取得エラー: " + H.escape("; ".join(errors)) + "</p>") if errors else ""

    return TEMPLATE.format(stamp=stamp, count=len(rows), cards="\n".join(cards),
                           ward_opts=ward_opts, curated=curated, err=err, market=market)


TEMPLATE = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>都心 割安×資産性スクリーナー（東京23区・売却益狙い）</title>
<style>
  :root{{--bg:#0f1115;--panel:#171a21;--panel2:#1d2129;--card:#191d25;--ink:#e9edf3;--muted:#9aa4b2;--line:#2a2f3a;--accent:#6ea8fe;--accent2:#7ee0c0}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP","Yu Gothic",Meiryo,sans-serif;line-height:1.55}}
  .wrap{{max-width:1180px;margin:0 auto;padding:18px}}
  h1{{font-size:1.45rem;margin:.2em 0}}
  h2{{font-size:1.08rem;margin:1.2em 0 .5em;border-left:4px solid var(--accent);padding-left:10px}}
  .meta{{color:var(--muted);font-size:.85rem;margin-bottom:12px}}
  a{{color:var(--accent)}}
  .lead{{color:var(--muted);font-size:.9rem}}
  /* ---- フィルタバー ---- */
  .bar{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px;margin:12px 0;position:sticky;top:0;z-index:5}}
  select,input{{background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:9px;padding:7px 10px;font-size:.9rem}}
  .bar label{{font-size:.8rem;color:var(--muted);margin-right:4px}}
  .ck{{display:flex;align-items:center;gap:6px;font-size:.84rem;color:#dfe5ee}}
  .pill{{display:inline-block;background:#24303f;color:var(--accent);border:1px solid #2f4154;border-radius:999px;padding:2px 12px;font-size:.82rem;font-weight:700}}
  /* ---- カードグリッド ---- */
  .cards{{display:grid;gap:14px;grid-template-columns:1fr}}
  @media(min-width:640px){{.cards{{grid-template-columns:1fr 1fr}}}}
  @media(min-width:980px){{.cards{{grid-template-columns:1fr 1fr 1fr}}}}
  .card{{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;display:flex;flex-direction:column;transition:transform .12s,border-color .12s,box-shadow .12s}}
  .card:hover{{transform:translateY(-3px);border-color:var(--accent);box-shadow:0 8px 24px rgba(0,0,0,.35)}}
  .ctop{{position:relative;padding:14px 16px 12px;background:linear-gradient(135deg,#222936,#171b22)}}
  .ctop.tS{{background:linear-gradient(135deg,#163a31,#171b22)}}
  .ctop.tA{{background:linear-gradient(135deg,#19324a,#171b22)}}
  .ctop.tB{{background:linear-gradient(135deg,#3a341a,#171b22)}}
  .ctop.tC{{background:linear-gradient(135deg,#2a2f38,#171b22)}}
  .ci{{padding-right:64px}}
  .price{{font-size:1.5rem;font-weight:800;letter-spacing:.2px}}
  .loc{{font-size:.84rem;color:#cdd6e2;margin-top:3px}}
  .kindchip{{display:inline-block;background:#2b3543;color:#bcd6ff;border-radius:6px;padding:0 7px;font-size:.72rem;margin-left:6px}}
  .ring{{position:absolute;top:12px;right:14px;width:54px;height:54px;border-radius:50%;
        background:conic-gradient(var(--accent) calc(var(--p)*1%),#2a2f3a 0);
        display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}}
  .ring::before{{content:"";position:absolute;inset:5px;border-radius:50%;background:var(--card)}}
  .ring b{{position:relative;font-size:1.05rem;line-height:1}}
  .ring small{{position:relative;font-size:.55rem;color:var(--muted)}}
  .bd{{display:flex;flex-wrap:wrap;gap:6px;padding:10px 16px 0}}
  .bdg{{font-size:.72rem;font-weight:700;border-radius:999px;padding:2px 9px}}
  .b-top{{background:#1f3d33;color:#7ee0c0;border:1px solid #2f5d4d}}
  .b-gem{{background:#1c2f49;color:#9ad0ff;border:1px solid #2e4a6e}}
  .b-warn{{background:#3a2530;color:#ff9db0;border:1px solid #5a3a45}}
  .facts{{display:grid;grid-template-columns:1fr 1fr;gap:8px 14px;padding:12px 16px}}
  .f{{font-size:.82rem}}
  .f span{{display:block;color:var(--muted);font-size:.7rem}}
  .f b{{font-weight:700}}
  .rbar{{height:6px;border-radius:999px;background:#2a2f3a;margin-top:4px;overflow:hidden}}
  .rbar i{{display:block;height:100%}}
  .tier{{display:inline-block;min-width:17px;text-align:center;border-radius:5px;margin-right:5px;font-weight:700;font-size:.74rem;color:#10141a}}
  .tS{{background:#7ee0c0}}.tA{{background:#9ad0ff}}.tB{{background:#ffe08a}}.tC{{background:#c9d1da}}
  .tags{{padding:0 16px}}
  .tag{{display:inline-block;background:#3a2530;color:#ff9db0;border:1px solid #5a3a45;border-radius:999px;padding:0 8px;font-size:.72rem;margin:0 4px 4px 0}}
  .grade{{display:inline-block;border-radius:6px;padding:0 8px;color:#10141a}}
  .g-hi{{background:#7ee0c0}}.g-mh{{background:#9ad0ff}}.g-mid{{background:#ffe08a}}.g-lo{{background:#c9d1da}}
  .cmt{{color:var(--muted);font-size:.78rem;padding:4px 16px 12px}}
  .view{{margin-top:auto;display:block;text-align:center;text-decoration:none;background:#212a37;color:#bcd6ff;border-top:1px solid var(--line);padding:10px;font-size:.85rem;font-weight:700}}
  .view:hover{{background:#27313f}}
  /* ---- 学び（details） ---- */
  details{{background:var(--panel2);border:1px solid var(--line);border-radius:12px;margin:10px 0;overflow:hidden}}
  details>summary{{cursor:pointer;list-style:none;padding:12px 16px;font-weight:700;font-size:.95rem;background:#1b2029}}
  details>summary::-webkit-details-marker{{display:none}}
  details>summary::before{{content:"▸ ";color:var(--accent)}}
  details[open]>summary::before{{content:"▾ "}}
  .dbody{{padding:12px 16px;font-size:.85rem;color:#dfe5ee}}
  .dbody li{{margin:4px 0}}
  /* 相場早見 */
  .mrow{{display:grid;grid-template-columns:130px 1fr;gap:10px;padding:10px 0;border-top:1px solid var(--line)}}
  .mrow:first-child{{border-top:none}}
  .mlabel{{font-weight:800;font-size:1.05rem;color:#10141a;border-radius:8px;padding:8px 10px;height:fit-content}}
  .mlabel small{{display:block;font-weight:500;font-size:.66rem;color:#0d1116;opacity:.85;margin-top:3px}}
  .mws{{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:6px}}
  .mw{{background:#171b22;border:1px solid var(--line);border-radius:9px;padding:7px 9px;font-size:.8rem}}
  .mw b{{display:block;color:#bcd6ff}}
  .mw small{{color:var(--muted);font-size:.7rem}}
  .note{{background:var(--panel2);border:1px solid var(--line);border-left:4px solid var(--accent2);border-radius:10px;padding:10px 14px;font-size:.84rem;color:#dfe5ee;margin:14px 0}}
  .cu{{display:block;text-decoration:none;background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:11px 14px;margin:8px 0;color:var(--ink)}}
  .cu:hover{{border-color:var(--accent);background:#1c2330}}
  .cu b{{color:#bcd6ff}}.cu span{{display:block;color:var(--muted);font-size:.8rem}}
  .grid{{display:grid;gap:8px}}
  @media(min-width:720px){{.grid{{grid-template-columns:1fr 1fr}}}}
</style></head><body><div class="wrap">
<p><a href="./index.html">← まとめ(index.html)へ戻る</a></p>
<h1>都心 割安×資産性スクリーナー — 東京23区（売却益狙い）</h1>
<p class="meta">コンセプト：<b>都心〜準都心で「相場より割安・駅近・出口が堅い」物件</b>を、売却益ポテンシャルの目安スコアで並べた一覧。
再建築不可・借地権などは“注意タグ”として減点表示（主役にしない）。<br>
出典：SUUMO（中古戸建を価格安い順で取得＋種別タグ付与）／<b>最終更新：{stamp}</b>／<b>{count}</b>件／毎日自動更新</p>

<div class="bar">
  <span><label>区</label><select id="fward"><option value="">すべて</option>{ward_opts}</select></span>
  <span><label>種別</label><select id="fkind"><option value="">すべて</option><option value="戸建">戸建</option><option value="土地">土地</option></select></span>
  <span><label>並び</label><select id="fsort"><option value="score">資産スコア順</option><option value="price">価格が安い順</option><option value="ratio">割安(相場比)順</option><option value="walk">駅が近い順</option></select></span>
  <span><label>価格上限(万円)</label><input id="fmax" type="number" inputmode="numeric" placeholder="例 5000" style="width:110px"></span>
  <span><label>最低スコア</label><input id="fscore" type="number" inputmode="numeric" placeholder="例 60" style="width:90px"></span>
  <label class="ck"><input type="checkbox" id="fexcl"> 再建築不可・借地を除く</label>
  <span class="pill" id="shown"></span>
</div>

<div class="cards" id="grid">
{cards}
</div>
{err}

<h2>学び（相場・穴場・落とし穴）</h2>

<details open><summary>📊 相場早見表 — 区ごとの中古戸建 相場坪単価＆出口ティア</summary>
<div class="dbody">
<p class="lead">「相場比＝この相場坪単価 ÷ 物件の実坪単価」。<b>相場比が高い＝割安</b>。ティアは売却時の“出口の堅さ”（S＝都心中枢ほど下値が堅い）。（）内は今の掲載件数。</p>
{market}
</div></details>

<details><summary>💎 穴場の見つけ方 — スコアの読み方と優先条件</summary>
<div class="dbody">
<p><b>資産スコア（0-100）</b>＝ 割安度（相場坪単価との比, 最大40）＋ 駅近（最大25）＋ 出口の堅さ＝ティア（最大25）＋ 規模（最大10）。再建築不可 −20／借地権 −12／古家付き −2 を減点。</p>
<ul>
<li><b>💎穴場候補</b>バッジ＝「相場比1.3倍以上 × 駅徒歩7分以内 × 注意タグ無し」。割安なのに出口・利便が確保できている本命ゾーン。</li>
<li><b>★高評価</b>バッジ＝スコア78以上。割安×駅近×出口の総合点が高い。</li>
<li>売却益を狙うなら <b>相場比1.1倍以上 × 駅近 × 出口S/A</b> を優先。価格の安さだけで選ばない（安い＝出口が弱い/訳ありのことが多い）。</li>
<li>「価格が安い順」で並べて掘るより、「割安(相場比)順」で並べると“相対的に得な物件”が上に来る。</li>
</ul>
</div></details>

<details><summary>⚠️ 落とし穴 — 安い物件に潜むリスク（タグの意味）</summary>
<div class="dbody">
<ul>
<li><b>再建築不可</b>（−20）：接道義務（幅員4m道路に2m以上接道）未達。今の建物を壊すと建て直せない＝<b>住宅ローンが付きにくく出口が極端に狭い</b>。現金/リフォーム前提の上級者向け。</li>
<li><b>借地権</b>（−12）：土地は借り物。地代・更新料・譲渡承諾料が発生し、<b>融資・売却に地主の承諾が要る</b>。旧法借地権は借地人有利だが流動性は低い。</li>
<li><b>古家付き土地</b>（−2）：解体費（木造で150〜250万円目安）と滅失登記が必要。実質の取得コストは表示価格＋解体費で見る。</li>
<li><b>セットバック</b>：42条2項道路に接する敷地は中心線から2m後退が必要。後退部分は建築・容積に算入不可＝<b>使える面積が減る</b>。</li>
<li><b>私道・掘削承諾</b>：私道接道はインフラ更新時に掘削承諾が必要。無いと<b>リフォーム・建替・融資が詰まる</b>頻出の隠れ瑕疵。</li>
<li>共通：<b>内見・現地・登記簿・公図・接道</b>を必ず確認。安さには理由がある前提で“理由を割り出して納得できる割安”だけ狙う。詳しい判断手順は <a href="./index.html">index.html</a> のチェックリスト/リスク判定へ。</li>
</ul>
</div></details>

<h2>他サイト（キュレーション・リンク）</h2>
<p class="lead">cowcamo・HOME'S・at home・楽待・健美家は、SPAやアクセス制限のため自動一覧に統合できません。最新は各公式でご確認ください（cowcamoはリノベ・デザイン重視で“脱ゲテモノ”に好相性）。</p>
<div class="grid">{curated}</div>

<div class="note">⚠️ 価格・在庫・相場は変動します。本スクリーナーはSUUMOからの自動取得スナップショット＋簡易スコアです。
購入判断の前に、再建築可否・接道・境界・用途地域・融資・出口を必ず現地と専門家（不動産業者/建築士/司法書士/金融機関）で確認してください。</div>

<script>
const grid=document.getElementById('grid'), cards=[...grid.children];
const el=id=>document.getElementById(id);
const fward=el('fward'),fkind=el('fkind'),fsort=el('fsort'),fmax=el('fmax'),fscore=el('fscore'),fexcl=el('fexcl');
function apply(){{
  const w=fward.value,k=fkind.value,mx=parseInt(fmax.value||'0',10),ms=parseInt(fscore.value||'0',10),ex=fexcl.checked,sk=fsort.value;
  let n=0;
  for(const c of cards){{
    const d=c.dataset; let ok=true;
    if(w&&d.ward!==w)ok=false;
    if(k&&d.kind!==k)ok=false;
    if(mx&&parseInt(d.price,10)>mx)ok=false;
    if(ms&&parseInt(d.score,10)<ms)ok=false;
    if(ex&&/(再建築不可|借地権)/.test(d.tags))ok=false;
    c.style.display=ok?'':'none'; if(ok)n++;
  }}
  const dir=(sk==='price'||sk==='walk')?1:-1;
  [...cards].sort((a,b)=>(parseFloat(a.dataset[sk])-parseFloat(b.dataset[sk]))*dir)
            .forEach(c=>grid.appendChild(c));
  el('shown').textContent=n+' 件';
}}
[fward,fkind,fsort,fmax,fscore,fexcl].forEach(e=>e.addEventListener('input',apply));
apply();
</script>
</div></body></html>"""


def main():
    rows, errors = collect()
    (DATA / "listings.json").write_text(json.dumps(
        {"updated": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9))).isoformat(),
         "count": len(rows), "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "listings.html").write_text(render(rows, errors), encoding="utf-8")
    print(f"wrote {len(rows)} listings; errors={len(errors)}")
    for e in errors:
        print("  ERR", e, file=sys.stderr)


if __name__ == "__main__":
    main()
