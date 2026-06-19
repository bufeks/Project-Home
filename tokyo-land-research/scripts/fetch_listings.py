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


def load_watchlist():
    """あなた専用の追跡リスト（住みたいエリア・気になるマンション・好きな町）。"""
    p = ROOT / "watchlist.json"
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return {"areas": d.get("areas", []), "buildings": d.get("buildings", [])}
        except Exception:
            pass
    return {"areas": [], "buildings": []}


WATCHLIST = load_watchlist()

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

# 区ごとの「都市開発・再開発の将来性」★0-3（出口の“上振れ”期待の目安）。
# 住宅資産価値に効く駅前/沿線再開発を中心に評価（2026年時点の調査ベース。詳細・出典は notes/redevelopment.md）。
# ※ 中野は新北口(サンプラザ跡)が事業費高騰で計画見直し・一旦中止のため控えめ評価。
WARD_DEV = {
    "千代田区": (3, "大手町・常盤橋（TOKYO TORCH／Torch Tower 2028頃）、神田・神保町。都心中枢で更新が活発"),
    "中央区":   (3, "日本橋（首都高地下化・室町/一丁目）、八重洲、月島・勝どき・晴海（HARUMI FLAG）、築地市場跡地"),
    "港区":     (3, "麻布台ヒルズ、品川・高輪ゲートウェイシティ（2025-26）、芝浦・浜松町。最も活発"),
    "渋谷区":   (3, "渋谷駅周辺『100年に1度』の再開発（桜丘・道玄坂・二丁目西, 2027-34）"),
    "新宿区":   (3, "新宿駅西口（小田急・メトロ 2029頃）、西新宿の再編、歌舞伎町"),
    "品川区":   (3, "大崎・五反田、武蔵小山（駅前進行）、大井町（広町地区）、西小山"),
    "豊島区":   (3, "池袋駅周辺（西口地区再開発・公園整備, 2030年代）、ハレザ池袋"),
    "江東区":   (2, "豊洲・有明など湾岸の継続開発、東陽町、亀戸"),
    "文京区":   (2, "後楽園・春日（文京ガーデン）、護国寺"),
    "台東区":   (2, "上野駅周辺、浅草。観光・商業の更新"),
    "墨田区":   (2, "錦糸町・押上（スカイツリー周辺）"),
    "目黒区":   (2, "目黒駅前、学芸大学、自由が丘一丁目"),
    "世田谷区": (2, "下北沢（小田急地下化跡『下北線路街』）、三軒茶屋（三茶のミライ）、二子玉川"),
    "大田区":   (2, "蒲田駅周辺グランドデザイン、大森、羽田イノベーションシティ"),
    "北区":     (2, "十条駅西口市街地再開発（タワマン, 2027頃）＋補助73号線、赤羽・王子"),
    "足立区":   (2, "北千住駅東口周辺、西新井、綾瀬。北千住は商業集積が強い"),
    "荒川区":   (2, "西日暮里駅前地区再開発、南千住"),
    "板橋区":   (2, "大山駅（クロスポイント・ハッピーロード・補助26号線・連続立体交差）、上板橋南口、板橋駅前"),
    "葛飾区":   (2, "京成立石駅前（36階タワマン＋区役所, 進行中）、金町、新小岩"),
    "江戸川区": (2, "JR小岩駅 南北の市街地再開発（タワマン 2026-27竣工）、平井"),
    "中野区":   (1, "中野駅新北口（サンプラザ跡）は事業費高騰で計画見直し・一旦中止。新区役所は開庁済"),
    "杉並区":   (1, "荻窪・阿佐ヶ谷・西荻窪の小規模更新が中心"),
    "練馬区":   (1, "大泉学園・石神井公園・練馬駅前の駅前整備"),
}
DEV_BONUS = {3: 4, 2: 2, 1: 1, 0: 0}   # 将来性スコア加点（最大+4。控えめに）

# 地区(丁目)レベルの将来性スポット。住所(loc)の前方一致で判定。住所の細かさを活かし、
# 「今は割安・古家密集だが、再開発の波が来る前夜」のエリアを拾う。
#   kind="再開発": 駅前再開発の直撃/近接（進行中の市街地再開発など）
#   kind="波":     木造住宅密集＝東京都『不燃化特区』等。今安い＋将来の建替/更新ポテンシャル
# (住所prefix, ラベル, kind, ★0-3, メモ)  ※随時追記して充実させる。出典 notes/redevelopment.md
DEV_SPOTS = [
    # --- 再開発 直撃/近接（進行中） ---
    ("新宿区西新宿", "西新宿五丁目", "再開発", 3, "西新宿五丁目中央南/中央北で市街地再開発（木造密集→住宅約470戸ほか）。新宿至近で出口◎"),
    ("品川区小山",   "武蔵小山",   "再開発", 3, "武蔵小山駅前のタワマン再開発が連続。商店街×再開発で資産性が上昇"),
    ("品川区西小山", "西小山",     "再開発", 2, "西小山駅前の再開発。武蔵小山に次ぐ更新エリア"),
    ("葛飾区立石",   "京成立石",   "再開発", 3, "立石駅前で36階タワマン＋新区役所が進行中。葛飾の中心が刷新"),
    ("江戸川区南小岩","南小岩",     "再開発", 3, "JR小岩駅 南北の市街地再開発でタワマン2026-27竣工。南小岩七・八丁目は不燃化特区"),
    ("北区十条",     "十条",       "再開発", 3, "十条駅西口で高層タワマン再開発＋補助73号線。十条駅周辺は不燃化特区"),
    ("板橋区大山町", "大山",       "再開発", 3, "大山駅クロスポイント等の再開発＋補助26号線＋連続立体交差。木密の刷新が進む"),
    ("中野区中野",   "中野駅",     "再開発", 1, "中野駅新北口(サンプラザ跡)は事業費高騰で計画見直し中。再始動なら大化けも現時点は不透明"),
    # --- 波の前夜（不燃化特区・木造密集＝今割安・将来更新） ---
    ("新宿区北新宿", "北新宿(西口北側)", "波", 2, "西新宿再開発の北側。木造住宅が密集し今は割安、将来の更新余地"),
    ("新宿区百人町", "百人町(大久保)",   "波", 2, "大久保駅周辺の密集市街地。更新ポテンシャル"),
    ("品川区戸越",   "戸越",       "波", 2, "戸越二・四・五・六丁目は不燃化特区（木密）。戸越銀座人気で実需厚い"),
    ("品川区豊町",   "豊町",       "波", 2, "豊町ほか不燃化特区。武蔵小山・西小山に近接"),
    ("品川区西大井", "西大井",     "波", 2, "西大井の不燃化特区。大井町再開発の波及"),
    ("世田谷区太子堂","太子堂",     "波", 2, "太子堂・若林は不燃化特区。三軒茶屋再開発に近接"),
    ("世田谷区若林", "若林",       "波", 2, "若林は不燃化特区。三軒茶屋至近"),
    ("世田谷区北沢", "北沢",       "波", 2, "北沢三・四/五丁目は不燃化特区。下北沢再開発に近接"),
    ("荒川区町屋",   "町屋",       "波", 2, "町屋・尾久は不燃化特区（木密）"),
    ("荒川区荒川",   "荒川",       "波", 2, "荒川・南千住の不燃化特区"),
    ("荒川区東尾久", "尾久",       "波", 2, "尾久の不燃化特区（木密）"),
    ("墨田区京島",   "京島",       "波", 2, "京島周辺は不燃化特区（木密の代表格）。押上・スカイツリー至近"),
    ("豊島区東池袋", "東池袋",     "波", 2, "東池袋四・五丁目は不燃化特区。池袋再開発に近接"),
    ("豊島区南池袋", "南池袋",     "波", 2, "雑司が谷・南池袋の不燃化特区。池袋至近"),
    ("豊島区雑司が谷","雑司が谷",   "波", 2, "雑司が谷の不燃化特区"),
    ("大田区大森中", "大森中",     "波", 2, "大森中地区は不燃化特区（木密）"),
    ("大田区東蒲田", "東蒲田",     "波", 2, "東蒲田は不燃化特区。蒲田再開発に近接"),
    ("足立区西新井", "西新井",     "波", 2, "西新井駅西口周辺は不燃化特区。駅前更新が進む"),
    ("中野区大和町", "大和町",     "波", 2, "大和町は不燃化特区（木密）。中野・高円寺至近"),
    ("文京区大塚",   "大塚",       "波", 2, "大塚五・六丁目は不燃化特区。文京の希少な割安余地"),
    ("杉並区方南",   "方南町",     "波", 2, "方南一丁目は不燃化特区。丸ノ内線方南町"),
    ("江東区北砂",   "北砂",       "波", 2, "北砂三・四・五丁目は不燃化特区（木密）"),
    ("板橋区大谷口", "大谷口",     "波", 2, "大谷口一丁目周辺は不燃化特区（木密）"),
    ("葛飾区四つ木", "四つ木",     "波", 2, "四つ木は不燃化特区。立石再開発に近接"),
    ("葛飾区東四つ木","東四つ木",   "波", 2, "東四つ木は不燃化特区"),
    ("葛飾区堀切",   "堀切",       "波", 2, "堀切の不燃化特区"),
    ("台東区谷中",   "谷中",       "波", 2, "谷中二・三・五丁目は不燃化特区。人気エリアで実需厚い"),
    ("目黒区目黒本町","目黒本町",   "波", 2, "目黒本町五・六丁目ほか不燃化特区。学芸大学至近"),
    ("目黒区原町",   "原町",       "波", 2, "原町一丁目は不燃化特区"),
    ("目黒区洗足",   "洗足",       "波", 2, "洗足一丁目は不燃化特区"),
    ("江戸川区平井", "平井",       "波", 2, "平井二丁目付近は不燃化特区"),
]

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

    # 都市開発・将来性（区レベル＋地区スポット）。出口の“上振れ”を控えめに加点。
    ward_stars, ward_note = WARD_DEV.get(ward, (0, ""))
    spot = next((s for s in DEV_SPOTS if r["loc"].startswith(s[0])), None)
    slabel, skind, snote, sstars = ("", "", "", 0)
    if spot:
        _, slabel, skind, sstars, snote = spot
    dev_stars = max(ward_stars, sstars)
    r["dev"] = dev_stars
    r["dev_ward_note"] = ward_note
    r["spot"] = slabel
    r["spot_kind"] = skind
    r["spot_note"] = snote
    score += DEV_BONUS[dev_stars]
    if skind == "波" and ratio and ratio >= 1.1:
        score += 1                        # 割安×“波の前夜”は本命候補として微加点

    r["score"] = max(0, min(100, score))
    r["grade"] = ("高" if r["score"] >= 78 else "中高" if r["score"] >= 62
                  else "中" if r["score"] >= 48 else "低")

    # あなたの追跡リスト：住所がウォッチ対象エリアに一致したら⭐（matchは文字列/リスト両対応）
    watch = ""
    for a in WATCHLIST.get("areas", []):
        m = a.get("match")
        toks = m if isinstance(m, list) else ([m] if m else [])
        if any(t and t in r["loc"] for t in toks):
            watch = a.get("label") or (toks[0] if toks else "")
            break
    r["watch"] = watch

    bits = []
    if r["ratio"]:
        if r["ratio"] >= 1:
            bits.append(f"相場より約{round((1 - 1 / r['ratio']) * 100)}%安い（相場比{r['ratio']}倍）")
        else:
            bits.append(f"相場より約{round((1 / r['ratio'] - 1) * 100)}%高い（相場比{r['ratio']}倍）")
    if w is not None:
        bits.append(f"駅徒歩{w}分")
    bits.append(f"出口{tier}")
    if dev_stars >= 2:
        bits.append((f"{slabel}・" if slabel else "") + f"将来性{'★' * dev_stars}")
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
    trs = []
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
        # 分かりやすい言い換え：相場より何%安い/高い（坪単価ベース）
        if ratio:
            if ratio >= 1:
                cheap_s = f"相場より{round((1 - 1 / ratio) * 100)}%安い"
                cheap_short = f"{round((1 - 1 / ratio) * 100)}%安"
            else:
                cheap_s = f"相場より{round((1 / ratio - 1) * 100)}%高い"
                cheap_short = f"{round((1 / ratio - 1) * 100)}%高"
        else:
            cheap_s = cheap_short = "—"
        walk = r["walk"]
        walk_s = f'{walk}分' if walk is not None else "—"
        tsubo_s = f'{r["tsubo"]}万/坪' if r["tsubo"] else "—"
        # 相場比バー（0.8→0%, 1.8→100%）。1.1以上=割安(緑)/1.0-1.1=並(黄)/未満=割高(赤)
        if ratio:
            fill = max(4, min(100, round((ratio - 0.8) / 1.0 * 100)))
            rcol = "#3fbf8f" if ratio >= 1.1 else "#e6b13c" if ratio >= 1.0 else "#e06a82"
        else:
            fill, rcol = 0, "#2a2f3a"
        gmap = ("https://www.google.com/maps/search/?api=1&query="
                + urllib.parse.quote("東京都" + r["loc"]))
        risky = ("再建築不可" in r["tags"]) or ("借地権" in r["tags"])
        dev = r.get("dev", 0)
        stars = "★" * dev + "☆" * (3 - dev)
        spot_kind = r.get("spot_kind", "")
        watch = r.get("watch", "")
        badges = []
        if watch:
            badges.append(f'<span class="bdg b-watch">⭐ {H.escape(watch)}</span>')
        if r["score"] >= 78:
            badges.append('<span class="bdg b-top">★高評価</span>')
        if (ratio and ratio >= 1.3) and (walk is not None and walk <= 7) and not risky:
            badges.append('<span class="bdg b-gem">💎穴場候補</span>')
        if spot_kind == "波":
            badges.append('<span class="bdg b-wave">🌊波の前夜</span>')
        elif spot_kind == "再開発" and dev >= 2:
            badges.append('<span class="bdg b-dev">🏗再開発エリア</span>')
        elif dev >= 3:
            badges.append('<span class="bdg b-dev">🏗再開発活発</span>')
        if risky:
            badges.append('<span class="bdg b-warn">⚠落とし穴</span>')
        badges_s = "".join(badges)
        spotfact = (" " + H.escape(r["spot"])) if r.get("spot") else ""
        if r.get("spot_note"):
            _ic = "🌊" if spot_kind == "波" else "🏗"
            _ncls = "n-wave" if spot_kind == "波" else "n-dev"
            devnote = f'<div class="devnote {_ncls}">{_ic} {H.escape(r["spot_note"])}</div>'
        else:
            devnote = ""
        cards.append(
            f'<article class="card" data-ward="{r["ward"]}" data-price="{r["price"]}" '
            f'data-score="{r["score"]}" data-tags="{H.escape("|".join(r["tags"]))}" '
            f'data-kind="{r["kind"]}" data-ratio="{ratio or 0}" '
            f'data-walk="{walk if walk is not None else 999}" data-tsubo="{r["tsubo"] or 0}" '
            f'data-dev="{dev}" data-watch="{1 if watch else 0}">'
            f'<div class="ctop t{r["tier"]}">'
            f'<div class="ci"><div class="price">{fmt_price(r["price"])}</div>'
            f'<div class="loc"><span class="tier t{r["tier"]}">{r["tier"]}</span>'
            f'{H.escape(r["loc"])}<span class="kindchip">{r["kind"]}</span></div></div>'
            f'<div class="ring" style="--p:{r["score"]}"><b>{r["score"]}</b><small>資産</small></div>'
            f'</div>'
            f'{f"<div class=bd>{badges_s}</div>" if badges_s else ""}'
            f'<div class="facts">'
            f'<div class="f"><span>割安度（相場比{ratio_s}）</span><b style="color:{rcol}">{cheap_s}</b>'
            f'<div class="rbar"><i style="width:{fill}%;background:{rcol}"></i></div></div>'
            f'<div class="f"><span>坪単価</span><b>{tsubo_s}</b></div>'
            f'<div class="f"><span>駅徒歩</span><b>{walk_s}</b></div>'
            f'<div class="f"><span>面積 / 間取</span><b>{area_s}</b></div>'
            f'<div class="f"><span>出口の堅さ</span><b>{r["tier"]}ティア</b></div>'
            f'<div class="f"><span>将来性(再開発)</span><b class="dev d{dev}">{stars}{spotfact}</b></div>'
            f'</div>'
            f'{devnote}'
            f'{f"<div class=tags>{tags}</div>" if tags else ""}'
            f'<div class="cmt">{H.escape(r["comment"])}</div>'
            f'<div class="viewrow">'
            f'<a class="view" href="{r["url"]}" target="_blank" rel="noopener">SUUMO ↗</a>'
            f'<a class="view vmap" href="{gmap}" target="_blank" rel="noopener">🗺 地図で見る</a>'
            f'</div>'
            f'</article>')

        # 比較用の表行（同じデータ属性。フィルタ/並び替えはカードと共通）
        dev_ic = "🌊" if spot_kind == "波" else ("🏗" if spot_kind == "再開発" else "")
        trs.append(
            f'<tr data-ward="{r["ward"]}" data-price="{r["price"]}" data-score="{r["score"]}" '
            f'data-tags="{H.escape("|".join(r["tags"]))}" data-kind="{r["kind"]}" '
            f'data-ratio="{ratio or 0}" data-walk="{walk if walk is not None else 999}" '
            f'data-tsubo="{r["tsubo"] or 0}" data-dev="{dev}" data-watch="{1 if watch else 0}">'
            f'<td class="tw"><span class="tier t{r["tier"]}">{r["tier"]}</span>{r["ward"]}</td>'
            f'<td class="tloc">{("⭐" + chr(32)) if watch else ""}'
            f'<a href="{r["url"]}" target="_blank" rel="noopener">{H.escape(r["loc"])}</a> '
            f'<a class="mp" href="{gmap}" target="_blank" rel="noopener" title="Googleマップで開く">🗺</a>'
            f'{(" " + tags) if tags else ""}</td>'
            f'<td class="num pr">{fmt_price(r["price"])}</td>'
            f'<td class="num"><span style="color:{rcol};font-weight:700" title="相場比{ratio_s}">{cheap_short}</span></td>'
            f'<td class="num">{tsubo_s}</td>'
            f'<td class="num">{walk_s}</td>'
            f'<td class="tarea">{area_s}</td>'
            f'<td class="dev d{dev}">{dev_ic}{("★" * dev) if dev else "—"}</td>'
            f'<td class="num"><span class="sc {gcolor(r["grade"])}">{r["score"]}</span></td>'
            f'</tr>')

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

    # 学び②：区別「都市開発・将来性」マップ（★高い順）
    dm = []
    for st in (3, 2, 1):
        for w in [w for w in WARDS if WARD_DEV.get(w, (0, ""))[0] == st]:
            note = WARD_DEV[w][1]
            dm.append(
                f'<div class="dvw"><span class="devb d{st}">{"★" * st}</span>'
                f'<b>{w}</b><small>{cnt.get(w,0)}件</small>'
                f'<span class="dvn">{H.escape(note)}</span></div>')
    devmap = "".join(dm)

    # 学び③：波の前夜エリア（地区スポット＝再開発直撃／不燃化特区・木密）
    spot_cnt = Counter(r["spot"] for r in rows if r.get("spot"))
    sm = []
    for pref, label, kind, st, note in DEV_SPOTS:
        ic = "🌊" if kind == "波" else "🏗"
        c = spot_cnt.get(label, 0)
        sm.append(
            f'<div class="spt {"s-wave" if kind == "波" else "s-dev"}">'
            f'<b>{ic} {H.escape(label)}</b><span class="dvn">{H.escape(note)}</span>'
            f'<small>{("掲載" + str(c) + "件") if c else "現在は該当物件なし"}</small></div>')
    spotmap = "".join(sm)

    # あなたの追跡リスト（住みたいエリア・好きな町／気になるマンション）
    areas = WATCHLIST.get("areas", [])
    buildings = WATCHLIST.get("buildings", [])
    watch_cnt = Counter(r["watch"] for r in rows if r.get("watch"))
    wparts = []
    if areas:
        items = ""
        for a in areas:
            m = a.get("match")
            toks = m if isinstance(m, list) else ([m] if m else [])
            m0 = toks[0] if toks else ""
            label = H.escape(a.get("label") or m0)
            note = H.escape(a.get("note", ""))
            key = a.get("label") or m0
            c = watch_cnt.get(key, 0)
            gm = ("https://www.google.com/maps/search/?api=1&query="
                  + urllib.parse.quote("東京都" + m0))
            items += (f'<div class="wli"><b>⭐ {label}</b>{(" — " + note) if note else ""}'
                      f'<span class="wc">{("この一覧に" + str(c) + "件") if c else "現在は該当なし"}</span>'
                      f'<a href="{gm}" target="_blank" rel="noopener">🗺地図</a></div>')
        wparts.append('<div class="wsub">住みたいエリア・好きな町</div>' + items)
    if buildings:
        items = ""
        for b in buildings:
            name, area = b.get("name", ""), b.get("area", "")
            note = H.escape(b.get("note", ""))
            gm = ("https://www.google.com/maps/search/?api=1&query="
                  + urllib.parse.quote((name + " " + area).strip()))
            gs = "https://www.google.com/search?q=" + urllib.parse.quote(name + " 中古マンション SUUMO")
            items += (f'<div class="wli"><b>🏢 {H.escape(name)}</b>'
                      f'{(" (" + H.escape(area) + ")") if area else ""}{(" — " + note) if note else ""}'
                      f'<a href="{gm}" target="_blank" rel="noopener">🗺地図</a>'
                      f'<a href="{gs}" target="_blank" rel="noopener">🔎検索</a></div>')
        wparts.append('<div class="wsub">気になるマンション・物件</div>'
                      '<p class="lead">※中古マンションは本一覧（戸建/土地）に出ないため、検索・地図リンクで追跡します。</p>'
                      + items)
    watch_html = "".join(wparts) if wparts else (
        '<p class="lead">まだ登録がありません。「○○に住みたい」「△△マンションが気になる」'
        '「□□の町が好き」と言ってくれれば、ここに追加して<b>毎日の自動更新で継続追跡</b>します'
        '（該当物件は一覧で⭐表示・「⭐ウォッチのみ」で抽出可）。</p>')

    curated = "".join(
        f'<a class="cu" href="{u}" target="_blank" rel="noopener"><b>{H.escape(n)} ↗</b>'
        f'<span>{H.escape(d)}</span></a>' for n, u, d in CURATED)
    err = ("<p class='lead'>取得エラー: " + H.escape("; ".join(errors)) + "</p>") if errors else ""

    return TEMPLATE.format(stamp=stamp, count=len(rows), cards="\n".join(cards),
                           rows="\n".join(trs), ward_opts=ward_opts, curated=curated,
                           err=err, market=market, devmap=devmap, spotmap=spotmap,
                           watch=watch_html)


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
  .b-wave{{background:#13303a;color:#67d6e6;border:1px solid #245863}}
  .b-dev{{background:#2e2940;color:#c4a8ff;border:1px solid #463a66}}
  .b-watch{{background:#3a3416;color:#ffe08a;border:1px solid #6a5d23}}
  /* 追跡リスト */
  .wsub{{font-weight:700;font-size:.9rem;margin:8px 0 4px;color:#ffe08a}}
  .wli{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:8px 10px;margin:5px 0;background:#171b22;border:1px solid var(--line);border-radius:9px;font-size:.85rem}}
  .wli b{{color:#e9edf3}}
  .wc{{color:var(--accent);font-size:.78rem;background:#1c2533;border:1px solid #2f4154;border-radius:999px;padding:1px 9px}}
  .wli a{{margin-left:auto;text-decoration:none}}.wli a+a{{margin-left:10px}}
  .dev.d3{{color:#67d6e6}}.dev.d2{{color:#9ad0ff}}.dev.d1{{color:#9aa4b2}}.dev.d0{{color:#5a6472}}
  .devnote{{margin:0 16px 10px;padding:8px 10px;border-radius:9px;font-size:.78rem;line-height:1.45}}
  .devnote.n-wave{{background:#10262e;border:1px solid #245863;color:#bfe7ee}}
  .devnote.n-dev{{background:#241f33;border:1px solid #463a66;color:#ddd0ff}}
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
  .viewrow{{margin-top:auto;display:flex;border-top:1px solid var(--line)}}
  .view{{flex:1;text-align:center;text-decoration:none;background:#212a37;color:#bcd6ff;padding:10px;font-size:.85rem;font-weight:700}}
  .view:hover{{background:#27313f}}
  .view.vmap{{border-left:1px solid var(--line);color:#9ce0c2}}
  .mp{{text-decoration:none;font-size:.95rem}}.mp:hover{{filter:brightness(1.3)}}
  /* ---- 表（比較）ビュー＆ビュー切替 ---- */
  .seg{{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden}}
  .seg button{{background:var(--panel2);color:var(--muted);border:0;padding:7px 13px;font-size:.85rem;cursor:pointer}}
  .seg button.on{{background:var(--accent);color:#0d1116;font-weight:700}}
  .hidden{{display:none!important}}
  .tblwrap{{overflow-x:auto;border:1px solid var(--line);border-radius:14px}}
  table{{border-collapse:collapse;width:100%;font-size:.85rem;min-width:760px}}
  thead th{{position:sticky;top:60px;background:#212732;text-align:left;padding:9px 10px;cursor:pointer;white-space:nowrap;user-select:none;border-bottom:1px solid var(--line);z-index:1}}
  thead th.num{{text-align:right}}
  thead th:hover{{color:#bcd6ff}}
  tbody td{{padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap;vertical-align:top}}
  tbody tr:hover{{background:#1b2029}}
  td.num{{text-align:right;font-variant-numeric:tabular-nums}}
  td.tw{{font-weight:600}}
  td.pr{{font-weight:800;font-size:.95rem}}
  td.tloc{{white-space:normal;min-width:160px}}
  td.tloc a{{color:#e9edf3;text-decoration:none}}
  td.tloc a:hover{{color:var(--accent);text-decoration:underline}}
  td.tarea{{color:var(--muted);font-size:.77rem}}
  td.dev{{font-weight:700;font-size:.78rem}}
  td.dev.d3{{color:#67d6e6}}td.dev.d2{{color:#9ad0ff}}td.dev.d1,td.dev.d0{{color:#6b7480}}
  .sc{{display:inline-block;min-width:30px;text-align:center;border-radius:6px;padding:1px 6px;font-weight:800;color:#10141a}}
  .sc.g-hi{{background:#7ee0c0}}.sc.g-mh{{background:#9ad0ff}}.sc.g-mid{{background:#ffe08a}}.sc.g-lo{{background:#c9d1da}}
  td .tag{{font-size:.68rem;padding:0 6px;margin:2px 3px 0 0}}
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
  /* 将来性マップ */
  .dvw{{display:grid;grid-template-columns:auto auto auto 1fr;align-items:center;gap:8px;padding:7px 0;border-top:1px solid var(--line)}}
  .dvw:first-child{{border-top:none}}
  .devb{{font-weight:800;border-radius:6px;padding:2px 7px;color:#10141a;font-size:.8rem}}
  .devb.d3{{background:#67d6e6}}.devb.d2{{background:#9ad0ff}}.devb.d1{{background:#c9d1da}}
  .dvw b{{min-width:64px}}.dvw small{{color:var(--muted);font-size:.72rem;min-width:34px}}
  .dvn{{color:#cdd6e2;font-size:.8rem}}
  .spt{{padding:9px 11px;border-radius:10px;margin:6px 0;border:1px solid var(--line)}}
  .spt.s-wave{{background:#10262e;border-color:#245863}}
  .spt.s-dev{{background:#241f33;border-color:#463a66}}
  .spt b{{display:block;margin-bottom:2px}}
  .spt small{{display:block;color:var(--muted);font-size:.72rem;margin-top:3px}}
  .spotgrid{{display:grid;gap:6px}}
  @media(min-width:720px){{.spotgrid{{grid-template-columns:1fr 1fr}}}}
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

<details open><summary>⭐ あなたの追跡リスト — 住みたいエリア・気になるマンション・好きな町</summary>
<div class="dbody">{watch}</div></details>

<div class="bar">
  <span><label>区</label><select id="fward"><option value="">すべて</option>{ward_opts}</select></span>
  <span><label>種別</label><select id="fkind"><option value="">すべて</option><option value="戸建">戸建</option><option value="土地">土地</option></select></span>
  <span><label>並び</label><select id="fsort"><option value="score">資産スコア順</option><option value="dev">将来性(再開発)順</option><option value="price">価格が安い順</option><option value="ratio">割安(相場比)順</option><option value="walk">駅が近い順</option></select></span>
  <span><label>価格上限(万円)</label><input id="fmax" type="number" inputmode="numeric" placeholder="例 5000" style="width:110px"></span>
  <span><label>最低スコア</label><input id="fscore" type="number" inputmode="numeric" placeholder="例 60" style="width:90px"></span>
  <label class="ck"><input type="checkbox" id="fexcl"> 再建築不可・借地を除く</label>
  <label class="ck"><input type="checkbox" id="fdev"> 将来性★2以上のみ</label>
  <label class="ck"><input type="checkbox" id="fwatch"> ⭐ウォッチのみ</label>
  <span class="seg"><button id="vTable" class="on" type="button">表で比較</button><button id="vCard" type="button">カード</button></span>
  <span class="pill" id="shown"></span>
</div>

<div class="tblwrap" id="tblwrap">
<table>
<thead><tr>
<th data-k="ward">区</th><th>所在地・地図・タグ</th>
<th class="num" data-k="price">価格 ⇅</th><th class="num" data-k="ratio">割安度 ⇅</th>
<th class="num">坪単価</th><th class="num" data-k="walk">駅徒歩 ⇅</th>
<th>面積</th><th data-k="dev">将来性 ⇅</th><th class="num" data-k="score">スコア ⇅</th>
</tr></thead>
<tbody id="tbody">
{rows}
</tbody></table></div>

<div class="cards hidden" id="grid">
{cards}
</div>
{err}

<h2>学び（相場・穴場・落とし穴）</h2>

<details open><summary>📊 相場早見表 — 区ごとの中古戸建 相場坪単価＆出口ティア</summary>
<div class="dbody">
<p class="lead"><b>相場比＝区の相場坪単価 ÷ この物件の坪単価</b>。1.0＝相場どおり、1.2＝相場より約17%安い、2.0＝相場の半額。<b>数字が大きいほど割安</b>（カードでは「相場より◯%安い」と表示）。ただし2倍超の“激安”は再建築不可・借地・狭小など理由ありのサイン。ティアは売却時の“出口の堅さ”（S＝都心中枢ほど下値が堅い）。（）内は今の掲載件数。</p>
{market}
</div></details>

<details><summary>🏗 都市開発・将来性マップ — 区ごとの再開発の勢い（★高い順）</summary>
<div class="dbody">
<p class="lead">再開発が活発な区＝将来の“出口の上振れ”が期待できる。スコアにも控えめに反映（★3で+4点ほど）。<b>★は2026年時点の調査ベースの目安</b>。</p>
{devmap}
</div></details>

<details open><summary>🌊 波が来る前夜エリア — 今は割安、これから更新が進む地区</summary>
<div class="dbody">
<p class="lead">住所（丁目）単位で、<b>🏗再開発が直撃／近接する地区</b>と、<b>🌊木造住宅が密集し東京都『不燃化特区』等で更新が進む地区</b>を判定。
「今は古家が多く割安だが、これから波が来る」エリアを拾う（例：新宿西口北側の<b>北新宿</b>＝西新宿再開発の波及）。物件カードにも該当メモを表示します。</p>
<div class="spotgrid">{spotmap}</div>
<p class="lead" style="margin-top:10px">出典：東京都都市整備局「不燃化特区」各区の取組／各区・東京都の市街地再開発事業ページ。具体の進捗・範囲は必ず公式で確認を。</p>
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
const el=id=>document.getElementById(id);
const grid=el('grid'), cards=[...grid.children];
const tbody=el('tbody'), trs=[...tbody.children];
const fward=el('fward'),fkind=el('fkind'),fsort=el('fsort'),fmax=el('fmax'),fscore=el('fscore'),fexcl=el('fexcl'),fdev=el('fdev'),fwatch=el('fwatch');
let sortK='score', sortAsc=false;
const defAsc=k=>(k==='price'||k==='walk');   // 価格・駅徒歩は小さい順、その他は大きい順を既定に
function pass(d){{
  if(fward.value&&d.ward!==fward.value)return false;
  if(fkind.value&&d.kind!==fkind.value)return false;
  const mx=parseInt(fmax.value||'0',10); if(mx&&parseInt(d.price,10)>mx)return false;
  const ms=parseInt(fscore.value||'0',10); if(ms&&parseInt(d.score,10)<ms)return false;
  if(fexcl.checked&&/(再建築不可|借地権)/.test(d.tags))return false;
  if(fdev.checked&&parseInt(d.dev,10)<2)return false;
  if(fwatch.checked&&d.watch!=='1')return false;
  return true;
}}
function run(items,parent){{
  let n=0;
  for(const c of items){{const ok=pass(c.dataset);c.style.display=ok?'':'none';if(ok)n++;}}
  const dir=sortAsc?1:-1;
  [...items].sort((a,b)=>{{
    const p=(parseFloat(a.dataset[sortK])-parseFloat(b.dataset[sortK]))*dir;
    return p!==0?p:(parseFloat(b.dataset.score)-parseFloat(a.dataset.score));
  }}).forEach(c=>parent.appendChild(c));
  return n;
}}
function apply(){{run(cards,grid);el('shown').textContent=run(trs,tbody)+' 件';}}
[fward,fkind,fmax,fscore,fexcl,fdev,fwatch].forEach(e=>e.addEventListener('input',apply));
fsort.addEventListener('change',()=>{{sortK=fsort.value;sortAsc=defAsc(sortK);apply();}});
document.querySelectorAll('thead th[data-k]').forEach(th=>th.addEventListener('click',()=>{{
  const k=th.dataset.k; if(k==='ward')return;
  if(k===sortK)sortAsc=!sortAsc; else {{sortK=k;sortAsc=defAsc(k);}}
  fsort.value=k; apply();
}}));
const vT=el('vTable'),vC=el('vCard');
vT.addEventListener('click',()=>{{vT.classList.add('on');vC.classList.remove('on');el('tblwrap').classList.remove('hidden');grid.classList.add('hidden');}});
vC.addEventListener('click',()=>{{vC.classList.add('on');vT.classList.remove('on');grid.classList.remove('hidden');el('tblwrap').classList.add('hidden');}});
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
