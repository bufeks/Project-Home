#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
東京23区「資産価値が落ちない家」スクリーナーを生成する。

プロジェクトの主旨:
  ・目的＝「住んで、売る時に“買値以上”で手放せる家」を見つける（値持ち・できれば値上がり＝最高）。
  ・安さ単体では選ばず、出口（再売却）での値持ちを最重視。
    評価軸＝①値持ち（名門立地・出口の堅さ）②割安度（相場比）③駅近 ④将来性 ⑤現地解像度。
  ・名門アドレス（内藤町/青葉台/松濤/番町/南青山/上原/広尾等）は満額でも下値が堅く値持ちするため加点。
  ・再建築不可・借地権・古家付き・旧耐震は“主役”にせず「注意タグ」。旧耐震は除外せず建替え目安も表示。
  ・各物件に「資産スコア（買値以上で売れるか＝資産が落ちないかの目安）」を付け、スコア順で並べる。

データ元（自動取得）:
  ・SUUMO 中古戸建（23区・価格安い順）… 通常物件の母集団（property_unit レイアウト）
  ・SUUMO 土地/再建築不可/借地/古家 … 種別・注意タグの付与（cassette レイアウト）

※ cowcamo / HOME'S / 楽待 / at home / 健美家 は自動取得が困難（SPA・アクセス制限）なため、
  HTML側に「キュレーション・リンク」として併設する（listings側の CURATED 参照）。

スコア・相場は簡易な“目安”。実際の売買判断前に必ず現地・専門家確認を。
"""
import json, re, sys, time, gzip, math, os, html as H, urllib.parse, urllib.request, datetime, pathlib
import unicodedata


def norm_name(s):
    """マンション名の表記揺れを吸収（全半角・空白・ヶケ・ウエ/ウェ・記号・長音）。"""
    s = unicodedata.normalize("NFKC", s or "")
    for a, b in [(" ", ""), ("　", ""), ("・", ""), ("ヶ", "ケ"), ("ｹ", "ケ"),
                 ("ウェ", "ウエ"), ("ヴ", "ブ"), ("－", "-"), ("ー", "")]:
        s = s.replace(a, b)
    return s.lower()


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
            return {"areas": d.get("areas", []), "buildings": d.get("buildings", []),
                    "budget_man": d.get("budget_man"), "min_area_m2": d.get("min_area_m2"),
                    "pins": d.get("pins", [])}
        except Exception:
            pass
    return {"areas": [], "buildings": [], "budget_man": None, "min_area_m2": None, "pins": []}


WATCHLIST = load_watchlist()
HISTORY = DATA / "history.json"


def update_history(rows):
    """毎日の価格を蓄積し、各物件に観測日数(days)・値下げ(drop)を付与。
    ※first_seenは“当ツールが最初に観測した日”（SUUMOの掲載開始日ではない）。日が経つほど精度が上がる。"""
    try:
        hist = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else {}
    except Exception:
        hist = {}
    today = datetime.date.today()
    tstr = today.isoformat()
    had_history = bool(hist)                   # 初回フル実行（履歴空）では全件newにしない
    for r in rows:
        hid, p = r["id"], r["price"]
        h = hist.get(hid)
        r["new"] = h is None and had_history   # 今日初観測＝新着
        if h is None:
            h = {"first_seen": tstr, "first_price": p, "last_price": p,
                 "last_change": tstr, "min_price": p}
            hist[hid] = h
        else:
            prev = h.get("last_price", p)
            if p != prev:
                h["last_change"] = tstr
            h["last_price"] = p
            if p < h.get("min_price", p):
                h["min_price"] = p
        h["last_seen"] = tstr
        try:
            r["days"] = (today - datetime.date.fromisoformat(h["first_seen"])).days
        except Exception:
            r["days"] = 0
        fp = h.get("first_price", p)
        r["first_price"] = fp
        r["drop"] = max(0, fp - p)
        r["drop_pct"] = round(r["drop"] / fp * 100) if fp else 0
        mnotes = []
        if r["drop"] > 0:
            mnotes.append(f"掲載後 {fp:,}→{p:,}万円（-{r['drop']:,}万・-{r['drop_pct']}%）値下げ＝指値余地/売り急ぎの可能性")
        if r["days"] >= 30:
            mnotes.append(f"観測{r['days']}日の滞留＝買い手がついていない（指値の余地）")
        if mnotes:
            base = r.get("reason", "")
            r["reason"] = " / ".join(mnotes + ([base] if base else []))
    cutoff = (today - datetime.timedelta(days=45)).isoformat()
    hist = {k: v for k, v in hist.items() if v.get("last_seen", "0") >= cutoff}
    try:
        HISTORY.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

WARDS = ["千代田区","中央区","港区","新宿区","文京区","台東区","墨田区","江東区",
         "品川区","目黒区","大田区","世田谷区","渋谷区","中野区","杉並区","豊島区",
         "北区","荒川区","板橋区","練馬区","足立区","葛飾区","江戸川区"]
WARD_CODES = [str(c) for c in range(13101, 13124)]   # 13101..13123
THIS_YEAR = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).year

# エリアティア（売却益の“出口の堅さ”の目安）
TIER = {w: "S" for w in ["千代田区","中央区","港区","渋谷区"]}
TIER.update({w: "A" for w in ["新宿区","文京区","目黒区","品川区","世田谷区","台東区","豊島区","中野区"]})
TIER.update({w: "B" for w in ["杉並区","墨田区","江東区","大田区","北区","荒川区","板橋区"]})
TIER.update({w: "C" for w in ["練馬区","足立区","葛飾区","江戸川区"]})
TIERN = {"S": 4, "A": 3, "B": 2, "C": 1}
TIER_MEMO = {
    "S": "都心中枢。希少性・流動性が高く下値が堅い＝売却益の出口が最も堅い",
    "A": "人気住宅地・準都心。実需が厚く資産性が安定。再開発で上振れも",
    "B": "割安で実需厚め。駅近・再開発を選べば値上がり余地あり",
    "C": "価格は控えめ。駅近・整形地・再開発など条件を厳選すれば妙味",
}
# ざっくり中古戸建の土地相場（万円/坪・目安）。割安度判定の基準。
# 2026-06 掲載中央値で監査。新宿/渋谷は±一桁%で整合。目黒は実勢が上回るため520→545に補正。
# 外周区(墨田/荒川/板橋/練馬/江戸川等)は当ツールが割安・訳あり物件を選好収集する標本バイアスで
# 掲載中央値が実勢より低く出るため、表の値は据え置き（中央値へ寄せると基準が崩れる）。
WARD_TSUBO = {
    "千代田区":900,"中央区":700,"港区":850,"新宿区":520,"文京区":480,"台東区":430,
    "墨田区":330,"江東区":350,"品川区":430,"目黒区":545,"大田区":330,"世田谷区":400,
    "渋谷区":800,"中野区":400,"杉並区":360,"豊島区":400,"北区":320,"荒川区":320,
    "板橋区":290,"練馬区":270,"足立区":220,"葛飾区":220,"江戸川区":240,
}
# 中古マンションのざっくり相場（万円/㎡・専有面積ベース・目安）。マンションの割安判定基準。
# 2026-06 掲載中央値で監査。新宿(130≒実138)・世田谷(115≒実106)は整合。
# 目黒は実勢が大幅に上回るため150→165に補正。渋谷(190 vs 実164)は標本バイアス分とみて据え置き。
WARD_MS_M2 = {
    "千代田区":175,"中央区":155,"港区":200,"新宿区":130,"文京区":135,"台東区":115,
    "墨田区":100,"江東区":105,"品川区":125,"目黒区":165,"大田区":95,"世田谷区":115,
    "渋谷区":190,"中野区":110,"杉並区":100,"豊島区":115,"北区":90,"荒川区":92,
    "板橋区":82,"練馬区":78,"足立区":68,"葛飾区":68,"江戸川区":72,
}
# 区平均では捉えきれない“プレミアム微立地（町丁目）”の補正倍率。
# 区相場×倍率で割安度の基準を引き上げ＝名門アドレスの好物件が「割高」と誤判定されるのを防ぐ。
# 加えてプレミアム立地では旧耐震の築年ディスカウントを緩める（土地・希少性が価値を支え値持ちするため）。
# ※ヒューリスティック。将来は国交省・不動産情報ライブラリの町丁目別実取引で置換予定。
PREMIUM_AREA = {
    "千代田区": [("番町", 1.25), ("一番町", 1.28), ("九段", 1.2), ("麹町", 1.2), ("三番町", 1.25), ("六番町", 1.25)],
    "港区": [("元麻布", 1.3), ("南麻布", 1.25), ("麻布永坂", 1.28), ("麻布台", 1.28), ("南青山", 1.22),
            ("白金台", 1.22), ("高輪", 1.15), ("赤坂", 1.12), ("六本木", 1.12), ("三田", 1.12)],
    "渋谷区": [("松濤", 1.3), ("神山町", 1.25), ("大山町", 1.25), ("上原", 1.18), ("富ヶ谷", 1.18),
            ("神宮前", 1.2), ("広尾", 1.22), ("恵比寿", 1.15), ("代官山町", 1.25), ("猿楽町", 1.22),
            ("鉢山町", 1.25), ("南平台町", 1.2), ("元代々木町", 1.15), ("代々木", 1.08)],
    "新宿区": [("内藤町", 1.32), ("南元町", 1.18), ("若宮町", 1.18), ("市谷砂土原", 1.2),
            ("四谷", 1.1), ("神楽坂", 1.12), ("市谷", 1.1)],
    "目黒区": [("青葉台", 1.2), ("東山", 1.12), ("上目黒", 1.12), ("中目黒", 1.12), ("鷹番", 1.1),
            ("八雲", 1.12), ("柿の木坂", 1.12), ("自由が丘", 1.15), ("駒場", 1.18), ("祐天寺", 1.08)],
    "文京区": [("西片", 1.18), ("小日向", 1.15), ("目白台", 1.15), ("本駒込", 1.08), ("関口", 1.12)],
    "品川区": [("上大崎", 1.15), ("東五反田", 1.15), ("北品川", 1.1), ("島津山", 1.18)],
    "世田谷区": [("成城", 1.15), ("深沢", 1.1), ("上野毛", 1.1), ("等々力", 1.1), ("玉川田園調布", 1.18), ("奥沢", 1.08)],
}


def premium_factor(ward, loc):
    """プレミアム微立地の補正倍率（最大一致）。該当しなければ1.0。"""
    best = 1.0
    for sub, m in PREMIUM_AREA.get(ward, []):
        if sub in loc and m > best:
            best = m
    return best


def _norm_dist(s):
    """町名の表記揺れ吸収（NFKC＋小さいヶ→ケ）。例 '幡ヶ谷'='幡ケ谷'、'千駄ヶ谷'='千駄ケ谷'。"""
    return unicodedata.normalize("NFKC", s or "").replace("ヶ", "ケ").strip()


def load_market_real():
    """国交省・不動産情報ライブラリの実取引集計（scripts/fetch_market.pyが生成）。"""
    try:
        m = json.loads((DATA / "market_real.json").read_text(encoding="utf-8"))
    except Exception:
        return {"wards": {}}
    # 町名キーを正規化した索引を付与（SUUMO所在地との表記揺れ対策）
    for w in m.get("wards", {}).values():
        w["_dn"] = {_norm_dist(k): v for k, v in (w.get("districts_ms") or {}).items()}
        w["_dr"] = {_norm_dist(k): v for k, v in (w.get("districts_ms_range") or {}).items()}
    return m


MARKET_REAL = load_market_real()


def district_of(ward, loc):
    """所在地から町名を抽出（例: '目黒区青葉台１'→'青葉台'）。"""
    s = loc[len(ward):] if loc.startswith(ward) else loc
    return re.split(r"[0-9０-９]|丁目|−|-|‐|ー", s)[0].strip()


def real_premium(ward, loc):
    """実取引ベースの町名プレミアム倍率（区中央値比）。データが無ければNone。"""
    w = MARKET_REAL.get("wards", {}).get(ward)
    if not w:
        return None
    return (w.get("_dn") or {}).get(_norm_dist(district_of(ward, loc)))


def ward_cagr(ward):
    """区のマンション㎡単価の年率（実取引・%）。"""
    w = MARKET_REAL.get("wards", {}).get(ward)
    return w.get("cagr_ms") if w else None


def seitei_range(ward, loc):
    """町名の実成約㎡単価レンジ {p25,p50,p75,n}（マンション・実取引）。無ければNone。"""
    w = MARKET_REAL.get("wards", {}).get(ward)
    if not w:
        return None
    return (w.get("_dr") or {}).get(_norm_dist(district_of(ward, loc)))

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
DEV_BONUS = {3: 6, 2: 3, 1: 1, 0: 0}   # 将来性(再開発)加点（最大+6）。10〜30年保有で収益upsideが効くため重めに

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
    # --- 鉄道計画（新駅・延伸＝沿線の地価上昇期待） ---
    ("江東区枝川",   "枝川（有楽町線延伸）",   "鉄道", 2, "有楽町線 豊洲〜住吉 延伸（事業中）の沿線。新駅構想で利便・地価の上昇期待"),
    ("江東区東陽",   "東陽町（有楽町線延伸）", "鉄道", 2, "有楽町線延伸ルート。乗換新設で都心アクセス向上期待"),
    ("江東区千石",   "千石（有楽町線延伸）",   "鉄道", 2, "有楽町線 豊洲〜住吉 延伸の沿線"),
    ("江東区住吉",   "住吉（有楽町線延伸）",   "鉄道", 2, "有楽町線延伸の接続駅。半蔵門線との乗換利便が向上"),
    ("港区高輪",     "高輪（南北線品川延伸）", "鉄道", 3, "南北線 白金高輪〜品川 延伸＋高輪ゲートウェイ。資産性の上昇期待"),
    ("港区港南",     "港南（品川・リニア）",   "鉄道", 3, "品川駅周辺再開発・リニア始発。将来性は最上位級"),
    ("中央区晴海",   "晴海（臨海地下鉄）",     "鉄道", 2, "都心部・臨海地下鉄 新駅構想。HARUMI FLAGの足回り改善期待"),
    ("中央区勝どき", "勝どき（臨海地下鉄）",   "鉄道", 2, "臨海地下鉄ルート。湾岸の交通改善期待"),
    ("江東区有明",   "有明（臨海地下鉄）",     "鉄道", 2, "都心部・臨海地下鉄の新駅構想エリア"),
    ("練馬区大泉町", "大泉町（大江戸線延伸）", "鉄道", 2, "大江戸線 光が丘〜大泉学園町 延伸の新駅構想"),
    ("練馬区土支田", "土支田（大江戸線延伸）", "鉄道", 2, "大江戸線延伸の新駅構想エリア"),
    ("大田区西蒲田", "西蒲田（蒲蒲線）",       "鉄道", 2, "新空港線(蒲蒲線)で蒲田〜京急蒲田接続構想。空港アクセス向上"),
    ("大田区東矢口", "矢口（蒲蒲線沿線）",     "鉄道", 2, "蒲蒲線・蒲田再開発の波及エリア"),
]

# 通常物件（母集団）: SUUMO 中古戸建 23区・価格安い順
AREA_URL = "https://suumo.jp/jj/bukken/ichiran/JJ012FC001/"
AREA_PAGES = 3
# 中古マンション 23区・価格安い順
MS_URL = "https://suumo.jp/jj/bukken/ichiran/JJ010FJ001/"
MS_PAGES = 3
# 新築一戸建て（未完成・建築中含む）bs=020
SHINCHIKU_URL = "https://suumo.jp/jj/bukken/ichiran/JJ012FC001/"
SHINCHIKU_PAGES = 2
# 詳細ページから現地シグナルを取得する上位件数（重いので限定）＋ウォッチ該当は別途必ず取得
DETAIL_TOPN = 40
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
    """SUUMO 中古戸建 一覧。物件単位（property_unit-title）で分割し全件取得（取得率が約2倍に改善）。"""
    rows = {}
    for b in htmltext.split('property_unit-title')[1:]:
        ml = re.search(r'href="(/(?:chukoikkodate|ikkodate)/[^"]+/nc_(\d+)/)"', b)
        if not ml or "万円" not in b:
            continue
        nid = ml.group(2)
        if nid in rows:
            continue
        t = text(b[:4000])
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
        rows[nid]["struct"] = struct_of(t)
    return list(rows.values())


def parse_mansion(htmltext):
    """SUUMO 中古マンション一覧。物件単位（property_unit-title）で分割し全件取得。
    ※ class="property_unit" 分割だと1物件が複数断片に割れ取得率が半減するため title 分割にする。"""
    rows = {}
    for b in htmltext.split('property_unit-title')[1:]:
        ml = re.search(r'href="(/ms/chuko/[^"]+/nc_(\d+)/)"', b)
        if not ml or "万円" not in b:
            continue
        nid = ml.group(2)
        if nid in rows:
            continue
        t = text(b[:4000])
        price = max_price(t)
        ma = re.search(r"所在地\s*東京都\s*([^\s]+?区[^\s]*)", t)
        if not (price and ma):
            continue
        ward = ward_of(ma.group(1))
        if not ward:
            continue
        senyu = re.search(r"専有面積\s*([0-9.]+)", t)
        plan = re.search(r"間取り\s*(\d+[SLDK]+)", t)
        walk = re.search(r"徒歩\s*(\d+)分", t)
        name = re.search(r"物件名\s*(.+?)\s*(?:販売価格|$)", t)
        year = re.search(r"築年月\s*(\d{4})年", t)
        r = base_row(
            nid, "SUUMOマンション", "マンション", ward, ma.group(1), price,
            None, float(senyu.group(1)) if senyu else None,
            plan.group(1) if plan else "",
            int(walk.group(1)) if walk else None,
            "https://suumo.jp" + ml.group(1))
        r["name"] = name.group(1).strip() if name else ""
        r["year"] = int(year.group(1)) if year else None
        r["struct"] = struct_of(t)
        rows[nid] = r
    return list(rows.values())


def parse_shinchiku(htmltext):
    """SUUMO 新築一戸建て（bs=020・未完成/建築中含む）。/ikkodate/ リンク。"""
    rows = {}
    for b in htmltext.split('class="property_unit')[1:]:
        ml = re.search(r'href="(/ikkodate/[^"]+/nc_(\d+)/)"', b)
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
        comp = re.search(r"(未完成|建築中|完成済|即入居可|[0-9]{4}年[0-9]{1,2}月(?:完成|築|下旬|上旬|中旬)?)", t)
        row = base_row(
            nid, "SUUMO新築戸建", "戸建", ward, ma.group(1), price,
            float(land.group(1)) if land else None,
            float(bld.group(1)) if bld else None,
            plan.group(1) if plan else "",
            int(walk.group(1)) if walk else None,
            "https://suumo.jp" + ml.group(1))
        row["tags"] = ["新築"]
        row["struct"] = struct_of(t) or "木造"
        row["comp"] = comp.group(1) if comp else ""
        rows[nid] = row
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
        rows[nid]["struct"] = struct_of(t)
    return list(rows.values())


def watchlist_search():
    """ウォッチ対象（住みたいエリア/マンション）の“区”を能動的に深掘り取得して優先的に拾う。"""
    rows, wards = [], set()
    for a in WATCHLIST.get("areas", []):
        m = a.get("match")
        for t in (m if isinstance(m, list) else [m] if m else []):
            w = ward_of(t)
            if w:
                wards.add(w)
    for b in WATCHLIST.get("buildings", []):
        w = ward_of(b.get("area", ""))
        if w:
            wards.add(w)
    for w in wards:
        code = WARD_CODES[WARDS.index(w)]
        # 中古マンション 深掘り：ソート順で結果セットが変わるため po=1(価格安い順)＋po=0(おすすめ順)の
        # 両方を取得して取りこぼしを防ぐ（例：都立大アーバンハイムは po=1 では出ず po=0 のみに出る）。
        for po in ("1", "0"):
            for pn in range(1, 6):
                q = [("ar", "030"), ("bs", "011"), ("ta", "13"), ("sc", code), ("po", po), ("pn", str(pn))]
                try:
                    rows += parse_mansion(fetch(MS_URL + "?" + urllib.parse.urlencode(q)))
                except Exception:
                    pass
                time.sleep(1.0)
        for pn in range(1, 3):           # 中古戸建
            q = [("ar", "030"), ("bs", "021"), ("ta", "13"), ("sc", code), ("po", "1"), ("pn", str(pn))]
            try:
                rows += parse_area(fetch(AREA_URL + "?" + urllib.parse.urlencode(q)))
            except Exception:
                pass
            time.sleep(1.0)
    return rows


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

    # 1b) 中古マンション（専有㎡単価で評価）
    for pn in range(1, MS_PAGES + 1):
        q = [("ar", "030"), ("bs", "011"), ("ta", "13")] + \
            [("sc", w) for w in WARD_CODES] + [("po", "1"), ("pn", str(pn))]
        url = MS_URL + "?" + urllib.parse.urlencode(q)
        try:
            add(parse_mansion(fetch(url)))
        except Exception as e:
            errors.append(f"mansion p{pn}: {e}")
        time.sleep(1.3)

    # 1c) 新築一戸建て（未完成・建築中含む）
    for pn in range(1, SHINCHIKU_PAGES + 1):
        q = [("ar", "030"), ("bs", "020"), ("ta", "13")] + \
            [("sc", w) for w in WARD_CODES] + [("po", "1"), ("pn", str(pn))]
        try:
            add(parse_shinchiku(fetch(SHINCHIKU_URL + "?" + urllib.parse.urlencode(q))))
        except Exception as e:
            errors.append(f"shinchiku p{pn}: {e}")
        time.sleep(1.3)

    # 2) 種別・注意タグ
    for _cat, kw, tag in KW_SOURCES:
        url = KW_BASE + urllib.parse.quote(kw) + "/"
        try:
            add(parse_cassette(fetch(url), _cat), tag=tag)
        except Exception as e:
            errors.append(f"{_cat}: {e}")
        time.sleep(1.3)

    # 0) ウォッチ優先探索（住みたいエリア/マンションの区を深掘り）
    try:
        add(watchlist_search())
    except Exception as e:
        errors.append(f"watch: {e}")

    rows = list(merged.values())
    # 重複名寄せ（E）：同一物件が別ID/別業者で重複することがある。住所+種別+価格+面積で寄せる
    uniq = {}
    for r in rows:
        key = (r["kind"], r["loc"], r["price"], r.get("land"), r.get("bld"))
        uniq.setdefault(key, r)
    rows = list(uniq.values())
    for r in rows:
        enrich(r)
    rows.sort(key=lambda x: (-x["score"], x["price"]))

    # 上位＋ウォッチ該当のみ詳細ページを取得し“現地シグナル”を付与（重いので限定）
    targets = list(rows[:DETAIL_TOPN])
    seen_ids = {r["id"] for r in targets}
    for r in rows[DETAIL_TOPN:]:
        if r.get("watch") and r["id"] not in seen_ids:
            targets.append(r)
            seen_ids.add(r["id"])
    targets = targets[:90]              # 実行時間を抑える上限（速報は詳細不要なので影響なし）
    for r in targets:
        try:
            apply_detail(r, fetch(r["url"]))
            enrich(r)                       # 是正タグ・現地シグナルを反映して再採点
        except Exception as e:
            errors.append(f"detail {r['id']}: {e}")
        time.sleep(0.7)

    # 戸建/土地は「再建築不可/借地」が一覧カードに出ず取りこぼすため、全件を詳細で軽量チェック
    # （標高APIはスキップして高速化。既に詳細取得済み or 既タグのものは除く）
    for r in rows:
        if (r["kind"] in ("戸建", "土地") and not r.get("detailed") and "新築" not in r["tags"]
                and not (set(r["tags"]) & {"再建築不可", "借地権"})):
            try:
                apply_detail(r, fetch(r["url"]), with_elev=False)
                enrich(r)
            except Exception as e:
                errors.append(f"risk {r['id']}: {e}")
            time.sleep(0.5)
    rows.sort(key=lambda x: (-x["score"], x["price"]))
    return rows, errors


def tsubo_unit(price, land):
    if not land or land <= 0:
        return None
    return price / (land / 3.30578)          # 万円/坪


def n_rooms(plan):
    m = re.match(r"(\d+)", plan or "")
    return int(m.group(1)) if m else 0


def struct_of(t):
    """構造（木造/鉄骨/RC/SRC）をテキストから判定。"""
    if not t:
        return ""
    if re.search(r"鉄骨鉄筋|ＳＲＣ|SRC", t):
        return "SRC"
    if re.search(r"鉄筋|ＲＣ|RC", t):
        return "RC"
    if re.search(r"軽量鉄骨", t):
        return "軽量鉄骨"
    if re.search(r"鉄骨|Ｓ造", t):
        return "鉄骨"
    if re.search(r"木造|木質", t):
        return "木造"
    return ""


def infer_reason(r):
    """現地不動産屋的な“安い理由の推定”。手持ちシグナルからの推定（断定しない）。"""
    tags = r["tags"]
    ratio = r["ratio"]
    w = r["walk"]
    rs = []
    if "再建築不可" in tags:
        rs.append("再建築不可（建て替え不可）が主因。現金/リフォーム前提で出口は狭い")
    if "借地権" in tags:
        rs.append("借地権（土地が借り物）。地代・承諾料と融資の難しさが価格に反映")
    if r["kind"] == "マンション" and "旧耐震" in tags:
        y = r.get("year")
        if y:
            age = THIS_YEAR - y
            zone_start = y + 50            # 建替え検討ゾーンの目安＝築50〜60年（中心55年）
            prime = r.get("tier") in ("S", "A") and (w is not None and w <= 7)
            if age >= 55:
                t = f"既に建替え検討ゾーン（築{age}年）。区分所有法改正で決議要件は緩和方向＝今後動く可能性"
            elif age >= 50:
                t = f"建替え検討ゾーンの入口（築{age}年／目安は築50〜60年）。区分所有法改正で決議要件は緩和方向"
            else:
                t = f"建替え目安は築50〜60年＝{zone_start}年頃〜（現状築{age}年・あと{zone_start-THIS_YEAR}年前後）"
            if prime:
                t += "。都心×駅近で事業性が高く、容積に余裕があれば等価交換で新築取得の含み（要・容積率/合意状況の確認）"
            rs.append("旧耐震・築古＝住宅ローンが付きにくく管理状態の精査が必須。" + t)
        else:
            rs.append("旧耐震・築古。住宅ローンが付きにくく管理状態の精査が必須")
    if "古家付き" in tags:
        rs.append("古家付き土地。解体費（木造150〜250万円目安）込みで実質コストを見る")
    if w is not None and w >= 15:
        rs.append(f"駅徒歩{w}分の駅遠が割安の一因")
    if r["kind"] == "マンション":
        if r.get("bld") and r["bld"] < 25:
            rs.append("専有が狭い投資ワンルーム系で実需は付きにくい")
    else:
        if r.get("land") and r["land"] < 40:
            rs.append("土地が狭小で接道・建築プランに制約が出やすい")
    if ratio and ratio >= 1.8 and not rs:
        rs.append("相場比が極端に高い＝まだ見えていない難（接道・間口・方位・嫌悪施設など）の可能性。現地確認必須")
    if not rs:
        if ratio and ratio >= 1.1:
            rs.append("目立つ難は見当たらず相場より割安。指値や設備更新で詰める領域（要現地確認）")
        else:
            rs.append("価格は相場相応。立地・築年・管理状態で比較するゾーン")
    if r.get("premium", 1.0) >= 1.1:
        rs.insert(0, "名門アドレスで下値が堅く“売る時に買値以上”を狙える値持ちエリア（満額でも資産が落ちにくい）")
    return rs[:3]


def detail_fields(html):
    """SUUMO詳細ページの th/td・dt/dd を label→value 辞書に。"""
    f = {}
    for m in re.finditer(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", html, re.S):
        k, v = text(m.group(1)), text(m.group(2))
        if k and v and k not in f:
            f[k] = v
    for m in re.finditer(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", html, re.S):
        k, v = text(m.group(1)), text(m.group(2))
        if k and v and k not in f:
            f[k] = v
    return f


def gsi_geocode(addr):
    """国土地理院API（無料・鍵不要）で住所→(lat, lon)。失敗時はNone。"""
    try:
        g = json.loads(urllib.request.urlopen(
            "https://msearch.gsi.go.jp/address-search/AddressSearch?q="
            + urllib.parse.quote(addr), timeout=15).read())
        if not g:
            return None
        lon, lat = g[0]["geometry"]["coordinates"]
        return float(lat), float(lon)
    except Exception:
        return None


def gsi_elevation_ll(lat, lon):
    """緯度経度→標高(m)。"""
    try:
        e = json.loads(urllib.request.urlopen(
            "https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php"
            f"?lon={lon}&lat={lat}&outtype=JSON", timeout=15).read())
        el = e.get("elevation")
        return float(el) if isinstance(el, (int, float)) else None
    except Exception:
        return None


# ===== 国交省・不動産情報ライブラリ GIS（住所→緯度経度→タイル→ポリゴン内外判定） =====
REINFOLIB_KEY = os.environ.get("REINFOLIB_API_KEY", "").strip()


def _tile_xy(lat, lon, z):
    n = 2 ** z
    return (int((lon + 180) / 360 * n),
            int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n))


def _pip(lat, lon, ring):
    """点(lon,lat)がリング内か（レイキャスト）。ringは[[lon,lat],...]。"""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def reinfolib_gis(eid, lat, lon, z, retries=3):
    """指定レイヤー(eid)のGeoJSONタイルを取得し、点を含むフィーチャのpropertiesを返す。鍵が無ければ[]。"""
    if not REINFOLIB_KEY:
        return []
    x, y = _tile_xy(lat, lon, z)
    url = (f"https://www.reinfolib.mlit.go.jp/ex-api/external/{eid}"
           f"?response_format=geojson&z={z}&x={x}&y={y}")
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"Ocp-Apim-Subscription-Key": REINFOLIB_KEY, "Accept-Encoding": "gzip"})
            raw = urllib.request.urlopen(req, timeout=30).read()
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
            hits = []
            for ft in json.loads(raw).get("features", []):
                geom = ft.get("geometry") or {}
                if geom.get("type") not in ("Polygon", "MultiPolygon"):
                    continue
                polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
                if any(rings and _pip(lat, lon, rings[0]) for rings in polys):
                    hits.append(ft.get("properties", {}))
            return hits
        except Exception:
            if i == retries - 1:
                return []
            time.sleep(1.5 * (i + 1))
    return []


def zoning_of(lat, lon):
    """用途地域・容積率(%)・建ぺい率(%)を返す（XKT002）。容積率付きの地物を優先。"""
    best = None
    for ft in reinfolib_gis("XKT002", lat, lon, 14):
        ua = ft.get("use_area_ja")
        if not ua:
            continue
        far = re.search(r"(\d+)", ft.get("u_floor_area_ratio_ja", "") or "")
        bcr = re.search(r"(\d+)", ft.get("u_building_coverage_ratio_ja", "") or "")
        cand = {"use_area": ua,
                "far": int(far.group(1)) if far else None,
                "bcr": int(bcr.group(1)) if bcr else None}
        if cand["far"]:
            return cand
        best = best or cand
    return best


def pop_mesh(lat, lon):
    """250mメッシュ将来推計人口（XKT013・社人研）。2025→2050総人口増減%と2050高齢化率を返す。"""
    for ft in reinfolib_gis("XKT013", lat, lon, 13):
        n0, n1 = ft.get("PT00_2025"), ft.get("PT00_2050")
        if n0 and n1 and n0 > 0:
            return {"chg": round((n1 / n0 - 1) * 100, 1), "aging": ft.get("RTD_2050")}
    return None


def apply_detail(r, html, with_elev=True):
    """詳細ページから“現地シグナル”を抽出して r['onsite'] に格納（必要なら是正タグも付与）。"""
    f = detail_fields(html)

    def g(*keys):
        for k, v in f.items():
            if any(key in k for key in keys):
                return v
        return ""

    notes = []
    if not r.get("struct"):
        r["struct"] = struct_of(g("構造"))
    # 再建築不可：制限事項欄だけでなく物件PR/備考のフリーテキストにも書かれるため本文全体を走査
    body_t = text(html)
    if (("再建築不可" in g("制限事項") or "再建築不可" in g("備考") or "再建築不可" in body_t)
            and "再建築可" not in body_t):
        if "再建築不可" not in r["tags"]:
            r["tags"].append("再建築不可")
        notes.append("再建築不可（建て替え不可）＝出口が極端に狭い。現金/リフォーム前提")
    yoto = g("用途地域")
    if any(x in yoto for x in ["商業", "近隣商業", "準工業", "工業"]):
        notes.append(f"用途地域:{yoto}（店舗・交通量で住環境はやや劣るが容積に余裕）")
    kenri, chidai = g("土地の権利"), g("諸費用")
    if r["kind"] != "マンション" and ("借地" in kenri or "賃借" in kenri or "地代" in chidai):
        if "借地権" not in r["tags"]:
            r["tags"].append("借地権")
        notes.append("借地（土地は借り物・地代/承諾料が必要）")
    road = g("私道負担", "前面道路", "道路")
    if road:
        if "私道" in road and not road.lstrip().startswith("無"):
            notes.append("私道負担/私道接道（掘削承諾・整備費・融資に注意）")
        mw = re.search(r"([0-9.]+)\s*[ｍm]", road)
        if mw and float(mw.group(1)) < 4:
            notes.append(f"前面道路 約{mw.group(1)}m（4m未満＝セットバック/再建築の制約に注意）")
        elif (r["kind"] != "マンション" and "再建築不可" not in r["tags"]
              and mw and float(mw.group(1)) >= 4 and "私道" not in road):
            notes.append(f"接道良好（前面道路 約{mw.group(1)}m・公道想定）＝再建築の見込み（最終は役所で確認）")
    if r["kind"] == "マンション":
        muki = g("向き")
        if muki and any(x in muki for x in ["北", "西"]):
            notes.append(f"{muki}向き（採光面でマイナス材）")
        # 管理・修繕の健全性（10〜30年保有の値持ちに直結）。総戸数＋修繕積立金の十分性で評価。
        adj = 0
        mt = re.search(r"(\d+)\s*戸", g("総戸数"))
        if mt:
            units = int(mt.group(1))
            r["units"] = units
            if units >= 50:
                adj += 2
                notes.append(f"総戸数{units}戸の大規模＝管理・修繕が安定し流動性も高い（値持ちプラス）")
            elif units < 20:
                adj -= 1
                notes.append(f"総戸数{units}戸の小規模（1戸あたり修繕負担が重く流動性やや低）")
        ms = re.search(r"([0-9,]+)\s*円", g("修繕積立金"))
        size = r.get("bld")
        if ms and size:
            pm2 = int(ms.group(1).replace(",", "")) / size          # 円/㎡/月
            r["reserve_pm2"] = round(pm2)
            age = (THIS_YEAR - r["year"]) if r.get("year") else 25
            req = min(350, 200 + max(0, age - 15) * 3)              # 築古ほど必要額が増える目安
            if pm2 < req * 0.6:
                adj -= 4
                notes.append(f"修繕積立金が不足気味（約{round(pm2)}円/㎡月・築{age}年の目安{req}）＝将来の大幅値上げ/一時金リスク")
            elif pm2 < req * 0.85:
                adj -= 1
                notes.append(f"修繕積立金がやや低め（約{round(pm2)}円/㎡月）")
            else:
                adj += 1
                notes.append(f"修繕積立金は十分水準（約{round(pm2)}円/㎡月）＝長期保有でも安心材料")
        r["mgmt_adj"] = max(-5, min(3, adj))
        if re.match(r"^1階(?!\d)", g("所在階").lstrip()):
            notes.append("1階住戸（防犯・眺望でマイナス、専用庭の利点も）")
    # 位置情報（標高・用途地域・ハザード）。重いので with_elev の詳細パスのみ。住所→緯度経度は1回。
    if with_elev:
        latlon = gsi_geocode("東京都" + r["loc"])
        if latlon:
            lat, lon = latlon
            el = gsi_elevation_ll(lat, lon)
            if el is not None:
                r["elev"] = round(el, 1)
                if el < 5:
                    notes.append(f"標高約{r['elev']}m＝低地（浸水・液状化の可能性、ハザードマップ要確認）")
            # 用途地域・容積率・建ぺい率（国交省GIS・鍵がある時のみ。SUUMO抽出より正確）
            z = zoning_of(lat, lon)
            if z:
                r["zoning"], r["far"], r["bcr"] = z["use_area"], z["far"], z["bcr"]
                _fa = f"・容積{z['far']}%/建ぺい{z['bcr']}%" if z["far"] else ""
                notes.append(f"用途地域：{z['use_area']}{_fa}（国交省・都市計画）")
                time.sleep(0.25)
            # 将来推計人口（250mメッシュ・社人研）：将来需要＝値持ちの最良シグナル
            pop = pop_mesh(lat, lon)
            if pop:
                r["pop_chg"] = pop["chg"]
                tr = "増加" if pop["chg"] >= 2 else "ほぼ横ばい" if pop["chg"] >= -3 else "減少"
                ag = f"・2050高齢化率{round(pop['aging'] * 100)}%" if pop.get("aging") else ""
                notes.append(f"将来人口(社人研・地点250m) 2025→2050 {pop['chg']:+.0f}%＝{tr}{ag}")
                time.sleep(0.25)
    # 建替え余地（戦略③）：容積率×土地面積で建てられる延床を概算。API容積率優先・無ければSUUMO抽出。
    if r["kind"] in ("戸建", "土地") and r.get("land"):
        vr = r.get("far")
        if not vr:
            pcts = re.findall(r"(\d+)\s*[%％]", g("容積率", "建ぺい率"))
            vr = int(pcts[-1]) if pcts else None
        if vr and 50 <= vr <= 1300:
            floor = round(r["land"] * vr / 100)
            r["build_floor"] = floor
            cur = r.get("bld") or 0
            if not cur or floor > cur * 1.15:
                notes.append(f"容積率{vr}%＝土地{r['land']:.0f}㎡で延床約{floor}㎡まで建築可（建替えで床増し/賃貸併用の余地）")
    # 売り急ぎ・相続シグナル（指値が通りやすい＝割安取得チャンスの可能性）。相続は申告期限10ヶ月で急ぐことが多い。
    urg = [k for k in ("相続", "売り急ぎ", "早期売却", "即金", "価格応談", "価格相談", "任意売却", "お早めに")
           if k in body_t]
    if urg:
        if "売り急ぎ" not in r["tags"]:
            r["tags"].append("売り急ぎ")
        notes.append("売り急ぎ/相続のサイン（" + "・".join(urg[:3]) + "）＝指値が通りやすい可能性（要確認）")
    # 重複除去・最大4件
    seen, uniq = set(), []
    for n in notes:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    r["onsite"] = uniq[:4]
    r["detailed"] = True


def enrich(r):
    ward = r["ward"]
    tier = TIER.get(ward, "C")
    r["tier"] = tier
    is_ms = r["kind"] == "マンション"
    wk = r["walk"]
    if is_ms:
        size = r.get("bld")                       # 専有面積㎡
        unit = (r["price"] / size) if size else None      # 万円/㎡
        med = WARD_MS_M2.get(ward)
        r["unit_disp"] = f"{round(unit)}万/㎡" if unit else "—"
        # 実需/投資の別（D）：狭小・ワンルーム系は投資、それ以外は実需
        r["use"] = "投資" if ((size and size < 30) or r.get("plan") in
                              ("1R", "1K", "1DK", "ワンルーム")) else "実需"
    else:
        unit = tsubo_unit(r["price"], r["land"])          # 万円/坪
        size = r["land"]
        med = WARD_TSUBO.get(ward)
        r["unit_disp"] = f"{round(unit)}万/坪" if unit else "—"
        r["use"] = "実需"
    r["tsubo"] = round(unit) if unit else None
    # 町名プレミアム：実取引(国交省)と目安ヒューリスティックを併用。
    #  既知の名門立地(目安>1.0)は過小評価しないよう高い方を採用、それ以外は実取引をそのまま使う
    #  （実取引は鉢山町等の発見や、割安区の<1.0補正にも効く）。
    rh = premium_factor(ward, r["loc"])
    rp = real_premium(ward, r["loc"])
    if rh > 1.0:
        pf = max(rh, rp or rh)
        r["premium_src"] = "目安+実取引" if rp else "目安"
    elif rp:
        pf = rp
        r["premium_src"] = "実取引"
    else:
        pf = 1.0
        r["premium_src"] = "—"
    r["premium"] = round(pf, 2)
    # 実取引が薄い町＝流動性が低く出口に時間。中心区(S/A)なのに中古M実成約が年8件未満で
    # 集計できない町を「流通が乏しい」と判定（例：信濃町＝特定組織の所有・利用が多い等）。
    r["thin_liq"] = (is_ms and rp is None and tier in ("S", "A")
                     and bool(MARKET_REAL.get("wards", {}).get(ward)))
    # 相場ベンチマークの補正：駅距離(B)＋マンションは築年(D)で“同条件比”に近づける
    if med:
        wf = (1.15 if (wk is not None and wk <= 3) else 1.06 if (wk is not None and wk <= 7)
              else 1.0 if (wk is None or wk <= 10) else 0.9 if wk <= 15 else 0.82)
        med *= wf
        if is_ms and r.get("year"):
            age = THIS_YEAR - r["year"]
            af = (1.12 if age <= 5 else 1.04 if age <= 15 else 1.0 if age <= 25
                  else 0.9 if age <= 35 else 0.8 if age <= 45 else 0.72)
            if pf > 1.0:
                af = max(af, 0.92)               # プレミアム立地は旧耐震でも値持ち＝築年減価を緩和
            med *= af
        med *= pf
        # 再建築不可・借地は“相場(=建築可・所有権前提)”がそのまま当てはまらない。構造的ディスカウントを
        # 「割安」と誤認しないよう相場ベンチマーク自体を引き下げ、相場比・手取り試算を正直化する。
        if "再建築不可" in r["tags"]:
            med *= 0.55
        elif "借地権" in r["tags"]:
            med *= 0.60
    ratio = (med / unit) if (unit and med) else None
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
    # 規模 (0-10)。マンションは専有面積、戸建/土地は土地面積で評価。
    if is_ms:
        s_s = (4 if size is None else 10 if size >= 70 else 8 if size >= 55
               else 5 if size >= 40 else 3 if size >= 25 else 2)
    else:
        s_s = (4 if size is None else 10 if size >= 60 else 8 if size >= 40
               else 5 if size >= 25 else 3 if size >= 15 else 2)
    # 立地プレミアム＝値持ち (0-12)。本プロジェクトの核「売る時に買値以上＝資産が落ちない」を
    # 直接評価。名門アドレス（内藤町/青葉台/松濤/番町/南青山/上原/広尾等）は満額でも下値が堅く
    # 出口で値持ちするため、割安でなくてもスコアが落ちないよう加点する。
    s_p = (12 if pf >= 1.28 else 9 if pf >= 1.18 else 5 if pf >= 1.10 else 2 if pf >= 1.05 else 0)
    score = s_w + s_e + s_t + s_s + s_p
    # 注意タグの減点（資産性・流動性を下げる）
    if "再建築不可" in r["tags"]:
        score -= 20                       # 建て替え不可＝『建てて売る/建替えて売る』が封じられ出口が極端に狭い
    if "借地権" in r["tags"]:
        score -= 12
    # ※古家付きは減点しない＝『古家壊して建て直して売る』戦略の“素材”。解体費は見立てに注記
    # マンションの築年（1981以前＝旧耐震は注意タグ扱い。古家付き同様、除外せず控えめ減点）
    # ※プレミアム立地では出口を立地が支え値持ちするため減点を半減（リスクはタグ・見立てで明示）
    if is_ms and r.get("year"):
        if r["year"] <= 1981:
            if "旧耐震" not in r["tags"]:
                r["tags"].append("旧耐震")
            score -= 3 if pf > 1.0 else 6
        elif r["year"] <= 2000:
            score -= 4

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
    score += r.get("mgmt_adj", 0)         # 管理・修繕の健全性（詳細取得済みマンションのみ）
    # 値持ち実測：区の中古マンション㎡単価の年率（国交省・実取引）。23区平均≈4.5%/年を基準に相対加点。
    cg = ward_cagr(ward)
    r["cagr"] = cg
    if is_ms:
        r["seitei"] = seitei_range(ward, r["loc"])   # 町名の実成約㎡単価レンジ
    if cg is not None:
        score += (4 if cg >= 5.5 else 3 if cg >= 4.8 else 1 if cg >= 4.0 else 0 if cg >= 3.7 else -1)

    r["score"] = max(0, min(100, score))

    # 手取り試算：今の相場で売却したら往復コスト差引でいくら残るか（＝買値以上で出せるかの目安）。
    # 相場価値=買値×相場比（割安なら買値<相場価値）。取得諸費用≈7%・売却諸費用≈3.5%で控除。
    # ※将来の値上がりは見込まない“今すぐ相場で売却”の保守的試算。値上がり率はAPI導入後に加味予定。
    if ratio and unit and size:
        mval = round(r["price"] * ratio)
        r["market_value"] = mval
        r["resale_net"] = round(mval - r["price"] - r["price"] * 0.07 - mval * 0.035)
    else:
        r["market_value"] = None
        r["resale_net"] = None
    r["grade"] = ("高" if r["score"] >= 78 else "中高" if r["score"] >= 62
                  else "中" if r["score"] >= 48 else "低")

    # あなたの追跡リスト：住所がウォッチ対象エリアに一致したら⭐（matchは文字列/リスト両対応）
    watch, watch_kind = "", ""
    for a in WATCHLIST.get("areas", []):
        m = a.get("match")
        toks = m if isinstance(m, list) else ([m] if m else [])
        if any(t and t in r["loc"] for t in toks):
            watch = a.get("label") or (toks[0] if toks else "")
            watch_kind = "area"
            break
    # マンションは物件名がウォッチ登録マンションに一致したら⭐（建物＝無条件で速報）
    if is_ms and r.get("name"):
        for b in WATCHLIST.get("buildings", []):
            nm = b.get("name", "")
            if nm and norm_name(nm) in norm_name(r["name"]):
                watch = nm
                watch_kind = "building"   # 建物一致はエリア一致より優先（無条件速報）
                break
    r["watch"] = watch
    r["watch_kind"] = watch_kind

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
    if "旧耐震" in r["tags"]:
        bits.append("旧耐震(1981以前)→融資/出口に注意")
    r["comment"] = " / ".join(bits)
    thin = (["実取引が少ない町＝流動性が薄く出口に時間（一般市場の流通が乏しい・価格は要現地確認）"]
            if r.get("thin_liq") else [])
    r["reason"] = " / ".join((thin + (r.get("onsite") or []) + infer_reason(r))[:4])


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
        tags = "".join(f'<span class="tag">{H.escape(t)}</span>' for t in r["tags"] if t not in ("新築", "売り急ぎ"))
        is_ms = r["kind"] == "マンション"
        area = []
        if is_ms:
            if r.get("bld"):
                area.append(f'専有{r["bld"]:.0f}㎡')
            if r["plan"]:
                area.append(H.escape(r["plan"]))
            if r.get("year"):
                area.append(f'{r["year"]}年築')
        else:
            if r["land"]:
                area.append(f'土{r["land"]:.0f}㎡')
            if r["bld"]:
                area.append(f'建{r["bld"]:.0f}㎡')
            if r["plan"]:
                area.append(H.escape(r["plan"]))
        if r.get("struct"):
            area.append(f'<span class="st">{H.escape(r["struct"])}</span>')
        area_s = " ".join(area) or "—"
        unit_s = r.get("unit_disp", "—")
        unit_label = "㎡単価" if is_ms else "坪単価"
        name_html = (f'<a class="mn" href="{r["url"]}" target="_blank" rel="noopener">{H.escape(r["name"])}</a> '
                     if is_ms and r.get("name") else "")
        loc_short = r["loc"][len(r["ward"]):] if r["loc"].startswith(r["ward"]) else r["loc"]
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
        drop = r.get("drop", 0)
        days = r.get("days", 0)
        dp = r.get("drop_pct", 0)
        badges = []
        if "新築" in r["tags"]:
            badges.append(f'<span class="bdg b-new">🆕新築{("・"+H.escape(r["comp"])) if r.get("comp") else ""}</span>')
        if watch:
            badges.append(f'<span class="bdg b-watch">⭐ {H.escape(watch)}</span>')
        if drop > 0:
            badges.append(f'<span class="bdg b-drop">📉値下げ -{r.get("drop_pct", 0)}%</span>')
        if days >= 30:
            badges.append(f'<span class="bdg b-stale">⏳滞留{days}日</span>')
        if r["score"] >= 78:
            badges.append('<span class="bdg b-top">★高評価</span>')
        if r.get("premium", 1.0) >= 1.1:
            badges.append('<span class="bdg b-prime">🏛名門アドレス・値持ち</span>')
        if (ratio and ratio >= 1.3) and (walk is not None and walk <= 7) and not risky:
            badges.append('<span class="bdg b-gem">💎穴場候補</span>')
        if r.get("mgmt_adj", 0) >= 2:
            badges.append('<span class="bdg b-mgmt">🏢管理良好</span>')
        elif r.get("mgmt_adj", 0) <= -3:
            badges.append('<span class="bdg b-warn">⚠積立不足</span>')
        if "売り急ぎ" in r["tags"]:
            badges.append('<span class="bdg b-urgent">🏃売り急ぎ?（指値余地）</span>')
        if (r.get("cagr") or 0) >= 5:
            badges.append(f'<span class="bdg b-cagr">📈値上がりエリア +{r["cagr"]}%/年</span>')
        if r.get("pop_chg") is not None and r["pop_chg"] <= -8:
            badges.append(f'<span class="bdg b-warn">📉将来人口減 {r["pop_chg"]:+.0f}%(→2050)</span>')
        if spot_kind == "鉄道":
            badges.append('<span class="bdg b-rail">🚇新駅・延伸</span>')
        elif spot_kind == "波":
            badges.append('<span class="bdg b-wave">🌊波の前夜</span>')
        elif spot_kind == "再開発" and dev >= 2:
            badges.append('<span class="bdg b-dev">🏗再開発エリア</span>')
        elif dev >= 3:
            badges.append('<span class="bdg b-dev">🏗再開発活発</span>')
        if risky:
            badges.append('<span class="bdg b-warn">⚠落とし穴</span>')
        if r.get("detailed"):
            badges.append('<span class="bdg b-onsite">🏠現地反映</span>')
        badges_s = "".join(badges)
        spotfact = (" " + H.escape(r["spot"])) if r.get("spot") else ""
        if r.get("spot_note"):
            _ic = {"波": "🌊", "鉄道": "🚇"}.get(spot_kind, "🏗")
            _ncls = "n-wave" if spot_kind in ("波", "鉄道") else "n-dev"
            devnote = f'<div class="devnote {_ncls}">{_ic} {H.escape(r["spot_note"])}</div>'
        else:
            devnote = ""
        reason_html = (f'<div class="reason">🔎 見立て(推定)：{H.escape(r.get("reason", ""))}</div>'
                       if r.get("reason") else "")
        # 実質コストはJS側で計算（フル/簡易リノベ切替・総額並べ替えに対応）。空なら非表示
        cost_html = '<div class="cost"></div>'
        rn = r.get("resale_net")
        if rn is not None:
            _col = "#0b7a55" if rn >= 0 else "#b42318"
            _sg = "+" if rn >= 0 else "−"
            net_html = (f'<div class="netline">💰 相場で今売却した時の手取り目安 '
                        f'<b style="color:{_col}">{_sg}{abs(rn):,}万</b>'
                        f'<span class="brk">＝相場価値{r["market_value"]:,} − 買値{r["price"]:,} − 往復コスト(取得約7%/売却約3.5%)</span></div>')
        else:
            net_html = ""
        cg = r.get("cagr")
        cagr_disp = f'+{cg}%/年' if cg is not None else "—"
        sr = r.get("seitei")
        if sr and is_ms:
            _unit = (r["price"] / r["bld"]) if r.get("bld") else None
            _pos = ("この物件は割安側" if _unit and _unit <= sr["p25"]
                    else "この物件は割高側" if _unit and _unit >= sr["p75"] else "中央付近")
            seitei_html = (f'<div class="netline">📊 この町の実成約 ㎡単価 '
                           f'<b>{sr["p25"]}〜{sr["p75"]}万</b>（中央{sr["p50"]}・{sr["n"]}件・国交省成約）'
                           f'<span class="brk">{H.escape(district_of(r["ward"], r["loc"]))}の実取引レンジ／'
                           + (f'本物件{round(_unit)}万＝{_pos}' if _unit else '') + '</span></div>')
        else:
            seitei_html = ""
        cards.append(
            f'<article class="card" data-cagr="{cg or 0}" data-ward="{r["ward"]}" data-price="{r["price"]}" '
            f'data-score="{r["score"]}" data-tags="{H.escape("|".join(r["tags"]))}" '
            f'data-net="{rn or 0}" '
            f'data-kind="{r["kind"]}" data-ratio="{ratio or 0}" '
            f'data-walk="{walk if walk is not None else 999}" data-tsubo="{r["tsubo"] or 0}" '
            f'data-dev="{dev}" data-watch="{1 if watch else 0}" '
            f'data-drop="{r.get("drop_pct", 0)}" data-days="{days}" data-use="{r.get("use", "実需")}" '
            f'data-tier="{r["tier"]}" data-rooms="{n_rooms(r.get("plan"))}" '
            f'data-area="{r.get("bld") or 0}" data-year="{r.get("year") or 0}" '
            f'data-land="{r.get("land") or 0}" data-furuya="{1 if "古家付き" in r["tags"] else 0}" data-shin="{1 if "新築" in r["tags"] else 0}" data-id="{r["id"]}" data-tiern="{TIERN.get(r["tier"],1)}" data-watchlabel="{H.escape(r.get("watch", ""))}">'
            f'<div class="ctop t{r["tier"]}">'
            f'<div class="ci"><div class="price">{fmt_price(r["price"])}</div>'
            f'<div class="loc"><span class="tier t{r["tier"]}">{r["tier"]}</span>'
            f'{name_html}{H.escape(r["loc"])}<span class="kindchip">{r["kind"]}</span></div></div>'
            f'<div class="ring" style="--p:{r["score"]}"><b>{r["score"]}</b><small>資産</small></div>'
            f'</div>'
            f'{f"<div class=bd>{badges_s}</div>" if badges_s else ""}'
            f'<div class="facts">'
            f'<div class="f"><span>割安度（相場比{ratio_s}）</span><b style="color:{rcol}">{cheap_s}</b>'
            f'<div class="rbar"><i style="width:{fill}%;background:{rcol}"></i></div></div>'
            f'<div class="f"><span>{unit_label}</span><b>{unit_s}</b></div>'
            f'<div class="f"><span>駅徒歩</span><b>{walk_s}</b></div>'
            f'<div class="f"><span>面積 / 間取</span><b>{area_s}</b></div>'
            f'<div class="f"><span>出口の堅さ</span><b>{r["tier"]}ティア</b></div>'
            f'<div class="f"><span>将来性(再開発)</span><b class="dev d{dev}">{stars}{spotfact}</b></div>'
            f'<div class="f"><span>区の実勢(年率)</span><b class="cagrf">{cagr_disp}</b></div>'
            f'</div>'
            f'{devnote}'
            f'{f"<div class=tags>{tags}</div>" if tags else ""}'
            f'{reason_html}'
            f'{cost_html}'
            f'{net_html}'
            f'{seitei_html}'
            f'<div class="cmt">{H.escape(r["comment"])}</div>'
            f'<div class="viewrow">'
            f'<button class="view mark" data-id="{r["id"]}" type="button">📌気になる</button>'
            f'<a class="view" href="{r["url"]}" target="_blank" rel="noopener">SUUMO ↗</a>'
            f'<a class="view vmap" href="{gmap}" target="_blank" rel="noopener">🗺 地図で見る</a>'
            f'</div>'
            f'</article>')

        # 比較用の表行（同じデータ属性。フィルタ/並び替えはカードと共通）
        dev_ic = {"波": "🌊", "鉄道": "🚇", "再開発": "🏗"}.get(spot_kind, "")
        trs.append(
            f'<tr data-cagr="{cg or 0}" data-ward="{r["ward"]}" data-price="{r["price"]}" data-score="{r["score"]}" '
            f'data-net="{rn or 0}" '
            f'data-tags="{H.escape("|".join(r["tags"]))}" data-kind="{r["kind"]}" '
            f'data-ratio="{ratio or 0}" data-walk="{walk if walk is not None else 999}" '
            f'data-tsubo="{r["tsubo"] or 0}" data-dev="{dev}" data-watch="{1 if watch else 0}" '
            f'data-drop="{r.get("drop_pct", 0)}" data-days="{days}" data-use="{r.get("use", "実需")}" '
            f'data-tier="{r["tier"]}" data-rooms="{n_rooms(r.get("plan"))}" '
            f'data-area="{r.get("bld") or 0}" data-year="{r.get("year") or 0}" '
            f'data-land="{r.get("land") or 0}" data-furuya="{1 if "古家付き" in r["tags"] else 0}" data-shin="{1 if "新築" in r["tags"] else 0}" data-id="{r["id"]}" data-tiern="{TIERN.get(r["tier"],1)}" data-watchlabel="{H.escape(r.get("watch", ""))}">'
            f'<td class="tw"><button class="mark mk-t" data-id="{r["id"]}" type="button">📌</button><span class="tier t{r["tier"]}">{r["tier"]}</span>{r["ward"]}</td>'
            f'<td class="tloc">{("⭐" + chr(32)) if watch else ""}'
            f'{name_html}'
            f'<a href="{r["url"]}" target="_blank" rel="noopener">{H.escape(loc_short)}</a> '
            f'<a class="mp" href="{gmap}" target="_blank" rel="noopener" title="Googleマップで開く">🗺</a>'
            f'<span class="kindchip">{r["kind"]}</span>'
            f'{(f" <span class=t-drop>📉-{dp}%</span>") if drop > 0 else ""}'
            f'{(f" <span class=t-stale>⏳{days}d</span>") if days >= 30 else ""}'
            f'{(" " + tags) if tags else ""}</td>'
            f'<td class="num pr" title="🔎見立て(推定): {H.escape(r.get("reason", ""))}">{fmt_price(r["price"])}</td>'
            f'<td class="num"><span style="color:{rcol};font-weight:700" title="相場比{ratio_s}">{cheap_short}</span></td>'
            f'<td class="num">{unit_s}</td>'
            f'<td class="num">{walk_s}</td>'
            f'<td class="tarea">{area_s}</td>'
            f'<td class="dev d{dev}">{dev_ic}{("★" * dev) if dev else "—"}</td>'
            f'<td class="num"><span class="sc {gcolor(r["grade"])}">{r["score"]}</span></td>'
            f'</tr>')

    ward_opts = "".join(f'<option value="{w}">{w}（{cnt.get(w,0)}）</option>' for w in wards)

    # 学び①：ティア別「区の相場＋実取引・値上がり率」早見表
    def _wcell(w, tier):
        wr = MARKET_REAL.get("wards", {}).get(w, {})
        cg = wr.get("cagr_ms")
        msr = wr.get("ms_m2_txn")
        real = (f'<small class="rl">実取引M {msr}万/㎡'
                + (f' ・<b class="cagrf">+{cg}%/年</b>' if cg is not None else "") + '</small>') if msr else ""
        return (f'<div class="mw"><span class="tier t{tier}">{tier}</span>{w}'
                f'<b>{WARD_TSUBO.get(w,"—")}万/坪</b>{real}<small>{cnt.get(w,0)}件</small></div>')
    mt = []
    for tier in ["S", "A", "B", "C"]:
        ws = [w for w in WARDS if TIER.get(w, "C") == tier]
        cells = "".join(_wcell(w, tier) for w in ws)
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
        ic = {"波": "🌊", "鉄道": "🚇"}.get(kind, "🏗")
        scls = "s-wave" if kind in ("波", "鉄道") else "s-dev"
        c = spot_cnt.get(label, 0)
        sm.append(
            f'<div class="spt {scls}">'
            f'<b>{ic} {H.escape(label)}</b><span class="dvn">{H.escape(note)}</span>'
            f'<small>{("掲載" + str(c) + "件") if c else "現在は該当物件なし"}</small></div>')
    spotmap = "".join(sm)

    # あなたの追跡リスト（住みたいエリア・好きな町／気になるマンション）
    areas = WATCHLIST.get("areas", [])
    buildings = WATCHLIST.get("buildings", [])
    watch_cnt = Counter(r["watch"] for r in rows if r.get("watch"))
    pins = WATCHLIST.get("pins", [])
    wparts = []
    # 🚨速報：気になるマンション（建物名一致）の売り物件だけ無条件で全掲載。
    # 住みたいエリアは無条件表示しない（⭐タグと「注目エリア」タブで条件付きで見る）。
    hits = [r for r in rows if r.get("watch_kind") == "building"]   # rowsはスコア降順
    # 気になるマンション速報に新着(売り物件)がある時だけ追跡リストを開く。他トグルは初期クローズ
    watch_open = " open" if hits else ""
    if buildings:
        if hits:
            hi = ""
            for r in hits:
                nm = (H.escape(r["name"]) + "・") if r.get("name") else ""
                gm = ("https://www.google.com/maps/search/?api=1&query="
                      + urllib.parse.quote("東京都" + r["loc"]))
                hi += (f'<div class="hit"><b>🏢 {H.escape(r["watch"])}</b> '
                       f'<span class="hk">{r["kind"]}</span> {nm}{H.escape(r["loc"])}'
                       f'<span class="hp">{fmt_price(r["price"])}</span>'
                       f'<span class="hs">スコア{r["score"]}</span>'
                       f'<a href="{r["url"]}" target="_blank" rel="noopener">SUUMO↗</a>'
                       f'<a href="{gm}" target="_blank" rel="noopener">🗺</a></div>')
            wparts.append(f'<div class="wsub">🚨 速報：気になるマンションの売り物件 {len(hits)}件（条件無視で全掲載）</div>{hi}')
        else:
            wparts.append('<div class="wsub">🚨 気になるマンション速報</div>'
                          '<p class="lead">現在、登録マンションの売り出しは見つかっていません（毎日チェック中）。</p>')
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
            cnt_html = (f'<button class="wc wcbtn" data-wl="{H.escape(key)}">この一覧に{c}件 ▸</button>'
                        if c else '<span class="wc">現在は該当なし</span>')
            items += (f'<div class="wli"><b>⭐ {label}</b>{(" — " + note) if note else ""}'
                      f'{cnt_html}'
                      f'<a href="{gm}" target="_blank" rel="noopener">🗺地図</a></div>')
        wparts.append('<div class="wsub">住みたいエリア・好きな町</div>' + items)
    if buildings:
        items = ""
        for b in buildings:
            name, area = b.get("name", ""), b.get("area", "")
            note = H.escape(b.get("note", ""))
            ref = H.escape(b.get("ref", ""))
            gm = ("https://www.google.com/maps/search/?api=1&query="
                  + urllib.parse.quote((name + " " + area).strip()))
            gs = "https://www.google.com/search?q=" + urllib.parse.quote(name + " 中古マンション SUUMO")
            burl = b.get("url", "")
            burl_link = f'<a href="{burl}" target="_blank" rel="noopener">🏢SUUMO建物</a>' if burl else ""
            ref_html = f'<span class="bref">{ref}</span>' if ref else ""
            items += (f'<div class="wli"><b>🏢 {H.escape(name)}</b>'
                      f'{(" (" + H.escape(area) + ")") if area else ""}{(" — " + note) if note else ""}'
                      f'<a href="{gm}" target="_blank" rel="noopener">🗺地図</a>'
                      f'<a href="{gs}" target="_blank" rel="noopener">🔎検索</a>'
                      f'{burl_link}{ref_html}</div>')
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

    budget = WATCHLIST.get("budget_man") or ""
    minarea = WATCHLIST.get("min_area_m2") or ""
    pin_ids = json.dumps([p.get("id", "") for p in pins if p.get("id")], ensure_ascii=False)
    pin_meta = json.dumps({p["id"]: {"n": p.get("name", ""), "s": p.get("spec", ""),
                                     "u": p.get("url", "")}
                           for p in pins if p.get("id")}, ensure_ascii=False)

    # 🆕 今日のダイジェスト：新着の本命・値下げを能動的にまとめる
    def _digrow(r, badge):
        gm = ('https://www.google.com/maps/search/?api=1&query='
              + urllib.parse.quote("東京都" + r["loc"]))
        wl = f' <span class="hs">⭐{H.escape(r["watch"])}</span>' if r.get("watch") else ""
        dp = f' <span class="hs">-{r["drop_pct"]}%値下げ</span>' if r.get("drop", 0) > 0 else ""
        return (f'<div class="hit">{badge} {H.escape(r["loc"])}'
                f'<span class="hp">{fmt_price(r["price"])}</span> '
                f'<span class="hs">スコア{r["score"]}</span>{wl}{dp} '
                f'<a href="{r["url"]}" target="_blank" rel="noopener">SUUMO↗</a> '
                f'<a href="{gm}" target="_blank" rel="noopener">🗺</a></div>')

    # ダイジェストは予算上限以内のみ（予算超え＝1億超は既定で除外）
    budget_cap = WATCHLIST.get("budget_man") or 10 ** 9
    drows = [r for r in rows if r["price"] <= budget_cap]
    new_honmei = sorted([r for r in drows if r.get("new") and (r["score"] >= 70 or r.get("watch"))],
                        key=lambda x: -x["score"])[:12]
    drops = sorted([r for r in drows if r.get("drop", 0) > 0],
                   key=lambda x: -x.get("drop_pct", 0))[:10]
    urgent = sorted([r for r in drows if "売り急ぎ" in r.get("tags", [])],
                    key=lambda x: -x["score"])[:10]
    if new_honmei or drops or urgent:
        dparts = []
        if new_honmei:
            dparts.append('<div class="wsub">🆕 新着の本命（今日初観測・スコア70+ または ウォッチ該当）'
                          + f'{len(new_honmei)}件</div>' + "".join(_digrow(r, "🆕") for r in new_honmei))
        if urgent:
            dparts.append('<div class="wsub">🏃 売り急ぎ/相続サイン（指値が通りやすい可能性）'
                          + f'{len(urgent)}件</div>' + "".join(_digrow(r, "🏃") for r in urgent))
        if drops:
            dparts.append('<div class="wsub">📉 値下げ（指値・売り急ぎの可能性）'
                          + f'{len(drops)}件</div>' + "".join(_digrow(r, "📉") for r in drops))
        digest_html = ('<details open><summary>🆕 今日のダイジェスト — 新着の本命・値下げ</summary>'
                       '<div class="dbody">' + "".join(dparts) + '</div></details>')
    else:
        digest_html = ""

    return TEMPLATE.format(stamp=stamp, count=len(rows), cards="\n".join(cards),
                           rows="\n".join(trs), ward_opts=ward_opts, curated=curated,
                           err=err, market=market, devmap=devmap, spotmap=spotmap,
                           watch=watch_html, budget=budget, minarea=minarea,
                           watch_open=watch_open, pinids=pin_ids, pinmeta=pin_meta,
                           digest=digest_html)


TEMPLATE = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>資産価値が落ちない家さがし — 東京23区（買値以上で売る）</title>
<style>
  :root{{--bg:#f5f7fa;--panel:#ffffff;--panel2:#eef2f7;--card:#ffffff;--ink:#1b2430;--muted:#5d6b7a;--line:#dce3ec;--accent:#2563eb;--accent2:#0f9d6b}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP","Yu Gothic",Meiryo,sans-serif;line-height:1.55}}
  .wrap{{max-width:1180px;margin:0 auto;padding:18px}}
  h1{{font-size:1.45rem;margin:.2em 0}}
  h2{{font-size:1.08rem;margin:1.2em 0 .5em;border-left:4px solid var(--accent);padding-left:10px}}
  .meta{{color:var(--muted);font-size:.85rem;margin-bottom:12px}}
  .tagline{{font-size:.95rem;margin:2px 0 8px;line-height:1.5}}
  .tagline .src{{color:var(--muted);font-size:.78rem;margin-left:6px;white-space:nowrap}}
  details.concept p{{margin:8px 0;line-height:1.65}}
  .concept-l{{margin:6px 0;padding-left:1.3em}}.concept-l li{{margin:4px 0}}
  .concept .note{{color:var(--muted);font-size:.82rem}}
  a{{color:var(--accent)}}
  .lead{{color:var(--muted);font-size:.9rem}}
  .scorebreak{{margin:6px 0 10px;padding-left:1.1em}}.scorebreak li{{margin:3px 0;font-size:.9rem}}
  /* ---- フィルタバー ---- */
  .bar{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px;margin:12px 0}}
  select,input{{background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:9px;padding:7px 10px;font-size:.9rem}}
  .bar label{{font-size:.8rem;color:var(--muted);margin-right:4px}}
  .ck{{display:flex;align-items:center;gap:6px;font-size:.84rem;color:#2c3744}}
  .bnote{{font-size:.72rem;color:var(--muted);margin-left:6px}}
  .view.mark{{color:#8a93a3;background:#f1f3f6;border:0;cursor:pointer;opacity:.85}}
  .view.mark.on{{background:#ffe6ad;color:#8a5a00;opacity:1;font-weight:800}}
  .mark.mk-t{{background:none;border:0;cursor:pointer;font-size:.95rem;padding:0 5px 0 0;opacity:.3;filter:grayscale(1)}}
  .mark.mk-t.on{{opacity:1;filter:none}}
  .pill{{display:inline-block;background:#e7eefb;color:var(--accent);border:1px solid #c8d8f7;border-radius:999px;padding:2px 12px;font-size:.82rem;font-weight:700}}
  /* ---- カードグリッド ---- */
  .cards{{display:grid;gap:10px;grid-template-columns:1fr}}
  @media(min-width:640px){{.cards{{grid-template-columns:1fr 1fr}}}}
  @media(min-width:980px){{.cards{{grid-template-columns:1fr 1fr 1fr}}}}
  .card{{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;display:flex;flex-direction:column;transition:transform .12s,border-color .12s,box-shadow .12s}}
  .card:hover{{transform:translateY(-3px);border-color:var(--accent);box-shadow:0 8px 22px rgba(30,50,90,.13)}}
  .ctop{{position:relative;padding:9px 12px 7px;background:linear-gradient(135deg,#f3f6fb,#ffffff)}}
  .ctop.tS{{background:linear-gradient(135deg,#e6f6ef,#ffffff)}}
  .ctop.tA{{background:linear-gradient(135deg,#e7f0fd,#ffffff)}}
  .ctop.tB{{background:linear-gradient(135deg,#fbf3df,#ffffff)}}
  .ctop.tC{{background:linear-gradient(135deg,#eef1f5,#ffffff)}}
  .ci{{padding-right:52px}}
  .price{{font-size:1.3rem;font-weight:800;letter-spacing:.2px}}
  .loc{{font-size:.8rem;color:#46505d;margin-top:2px}}
  .kindchip{{display:inline-block;background:#e7eef8;color:#2563eb;border-radius:6px;padding:0 7px;font-size:.72rem;margin-left:6px}}
  .mn{{color:#a25e00;font-weight:700;text-decoration:none}}
  .st{{display:inline-block;background:#e8eef0;color:#3a4a52;border-radius:5px;padding:0 6px;font-size:.68rem;font-weight:700}}.mn:hover{{text-decoration:underline}}
  .ring{{position:absolute;top:12px;right:14px;width:44px;height:44px;border-radius:50%;
        background:conic-gradient(var(--accent) calc(var(--p)*1%),#e1e6ee 0);
        display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--ink)}}
  .ring::before{{content:"";position:absolute;inset:5px;border-radius:50%;background:var(--card)}}
  .ring b{{position:relative;font-size:.92rem;line-height:1}}
  .ring small{{position:relative;font-size:.55rem;color:var(--muted)}}
  .bd{{display:flex;flex-wrap:wrap;gap:5px;padding:6px 12px 0}}
  .bdg{{font-size:.72rem;font-weight:700;border-radius:999px;padding:2px 9px}}
  .b-top{{background:#e3f6ee;color:#0b7a55;border:1px solid #b8e6d3}}
  .b-gem{{background:#e4eefe;color:#1d5fd6;border:1px solid #c2d8fb}}
  .b-aff{{background:#fce7f1;color:#c01a6b;border:1px solid #f6bcd6}}
  .b-prime{{background:#f3ecda;color:#8a6d1f;border:1px solid #e0cf9b}}
  .b-mgmt{{background:#e3f6ee;color:#0b7a55;border:1px solid #b8e6d3}}
  .b-urgent{{background:#fdeede;color:#b5630a;border:1px solid #f4cf9f}}
  .b-cagr{{background:#e6f7ed;color:#0a7d4f;border:1px solid #b3e6cb}}
  .cagrf{{color:#0a7d4f}}
  .mw .rl{{display:block;color:#5d6b7a;font-size:.7rem;margin-top:1px}}
  .netline{{font-size:.82rem;color:#2c3744;background:#f3f7f4;border:1px solid #d8e6dd;border-radius:8px;padding:6px 10px;margin:6px 0}}
  .netline .brk{{display:block;color:var(--muted);font-size:.74rem;margin-top:1px}}
  .profline{{font-size:.84rem;color:#1b2430;background:#fff;border:1px solid #f1d9a0;border-radius:9px;padding:8px 11px;margin:4px 0 8px;line-height:1.7}}
  .b-warn{{background:#fde7ec;color:#c0344f;border:1px solid #f3c2cd}}
  .b-wave{{background:#e0f3f8;color:#0e7d92;border:1px solid #bce4ee}}
  .b-dev{{background:#efe9fb;color:#6b46c1;border:1px solid #d8c9f3}}
  .b-rail{{background:#e4f5ea;color:#1d7a45;border:1px solid #c0e6cd}}
  .b-onsite{{background:#f3e9fb;color:#8a3fc0;border:1px solid #e0c9f3}}
  .b-drop{{background:#fde7ea;color:#c8324a;border:1px solid #f4c2cb}}
  .b-stale{{background:#fbf2d6;color:#8a6d10;border:1px solid #ecdc9a}}
  .t-drop{{color:#c8324a;font-weight:700;font-size:.72rem}}
  .t-stale{{color:#8a6d10;font-weight:700;font-size:.72rem}}
  .reason{{margin:0 12px 7px;padding:6px 9px;border-radius:9px;font-size:.78rem;line-height:1.45;background:#f4f8ec;border:1px solid #dbe6c4;color:#4a5a2e}}
  .cost{{margin:0 12px 7px;padding:6px 9px;border-radius:9px;font-size:.78rem;background:#eef3fb;border:1px solid #cfddf3;color:#274472}}.cost b{{color:#1b3a6b;font-size:.86rem}}.cost:empty{{display:none}}
  .brk{{color:#7e8aa0;font-size:.7rem}}
  .tblwrap-g{{overflow-x:auto}}
  table.kobai{{border-collapse:collapse;width:100%;font-size:.82rem;min-width:420px}}
  table.kobai th,table.kobai td{{border:1px solid var(--line);padding:6px 8px;text-align:center}}
  table.kobai thead th{{background:#eef2f7}}
  .b-watch{{background:#fdf3d4;color:#8a6a00;border:1px solid #ecdc92}}
  /* 追跡リスト */
  .wsub{{font-weight:700;font-size:.9rem;margin:8px 0 4px;color:#a07b00}}
  .wli{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:8px 10px;margin:5px 0;background:#f7f9fc;border:1px solid var(--line);border-radius:9px;font-size:.85rem}}
  .wli b{{color:var(--ink)}}
  .wc{{color:var(--accent);font-size:.78rem;background:#e7eefb;border:1px solid #c8d8f7;border-radius:999px;padding:1px 9px}}
  .wcbtn{{cursor:pointer;font-family:inherit}}.wcbtn:hover{{filter:brightness(.96)}}
  .wcbtn.on{{background:#2563eb;color:#fff;border-color:#2563eb}}
  .wli a{{margin-left:auto;text-decoration:none}}.wli a+a{{margin-left:10px}}
  .bref{{flex-basis:100%;color:#5d6b7a;font-size:.76rem;margin-top:2px}}
  .pspec{{flex-basis:100%;margin-top:2px;color:#3a4654}}
  .sharerow{{background:#eef4ff;border:1px solid #cdddf6;border-radius:9px;padding:9px 11px;margin:4px 0 8px}}
  .sharerow .shareflex{{display:flex;gap:6px;margin:5px 0 3px}}
  .sharerow #shareurl{{flex:1;min-width:0;font-size:.78rem;padding:6px 8px;border:1px solid var(--line);border-radius:7px;background:#fff;color:#1b2430}}
  .sharerow .sharebtn{{flex:none;background:var(--accent);color:#fff;border:0;border-radius:7px;padding:6px 12px;font-size:.82rem;font-weight:700;cursor:pointer}}
  .hit{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:9px 11px;margin:5px 0;background:#fff7e6;border:1px solid #f1d9a0;border-radius:9px;font-size:.85rem}}
  .hit .hk{{background:#e7eef8;color:#2563eb;border-radius:6px;padding:0 7px;font-size:.72rem}}
  .hit .hp{{font-weight:800;color:#1b2430}}.hit .hs{{color:#5d6b7a;font-size:.78rem}}
  .hit a{{text-decoration:none;font-weight:700}}.hit a+a{{margin-left:2px}}
  .hit.off{{background:#f3f4f6;border-color:#d6dae0;color:#8a94a0}}
  .hit.off .hp{{color:#8a94a0;text-decoration:line-through}}
  .hit .gone{{background:#fde2e1;color:#b42318;border:1px solid #f3b6b1;border-radius:6px;padding:0 7px;font-size:.72rem;font-weight:700}}
  .dev.d3{{color:#0e7d92}}.dev.d2{{color:#1d5fd6}}.dev.d1{{color:#5d6b7a}}.dev.d0{{color:#9aa4b2}}
  .devnote{{margin:0 12px 7px;padding:6px 9px;border-radius:9px;font-size:.78rem;line-height:1.45}}
  .devnote.n-wave{{background:#e6f4f8;border:1px solid #bce0ea;color:#185f70}}
  .devnote.n-dev{{background:#f2ecfb;border:1px solid #ddccf3;color:#5a3f8a}}
  .facts{{display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;padding:7px 12px}}
  .f{{font-size:.78rem}}
  .f span{{display:block;color:var(--muted);font-size:.66rem}}
  .f b{{font-weight:700}}
  .rbar{{height:6px;border-radius:999px;background:#e6eaf0;margin-top:4px;overflow:hidden}}
  .rbar i{{display:block;height:100%}}
  .tier{{display:inline-block;min-width:17px;text-align:center;border-radius:5px;margin-right:5px;font-weight:700;font-size:.74rem;color:#10141a}}
  .tS{{background:#7ee0c0}}.tA{{background:#9ad0ff}}.tB{{background:#ffe08a}}.tC{{background:#c9d1da}}
  .tags{{padding:0 12px}}
  .tag{{display:inline-block;background:#fde8ec;color:#b23a52;border:1px solid #f3c8d1;border-radius:999px;padding:0 8px;font-size:.72rem;margin:0 4px 4px 0}}
  .grade{{display:inline-block;border-radius:6px;padding:0 8px;color:#10141a}}
  .g-hi{{background:#7ee0c0}}.g-mh{{background:#9ad0ff}}.g-mid{{background:#ffe08a}}.g-lo{{background:#c9d1da}}
  .cmt{{color:var(--muted);font-size:.74rem;padding:2px 12px 8px}}
  .viewrow{{margin-top:auto;display:flex;border-top:1px solid var(--line)}}
  .view{{flex:1;text-align:center;text-decoration:none;background:#eef3fb;color:#2563eb;padding:7px;font-size:.82rem;font-weight:700}}
  .view:hover{{background:#e2ebfb}}
  .view.vmap{{border-left:1px solid var(--line);color:#0f9d6b}}
  .mp{{text-decoration:none;font-size:.95rem}}.mp:hover{{filter:brightness(1.1)}}
  /* ---- 表（比較）ビュー＆ビュー切替 ---- */
  .seg{{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden}}
  .seg button{{background:var(--panel2);color:var(--muted);border:0;padding:7px 13px;font-size:.85rem;cursor:pointer}}
  .seg button.on{{background:var(--accent);color:#ffffff;font-weight:700}}
  .seg-preset button.on{{background:#7c3aed;color:#fff}}
  .seg-reno button.on{{background:#0f9d6b;color:#fff}}
  .hidden{{display:none!important}}
  .tblwrap{{overflow-x:auto;border:1px solid var(--line);border-radius:14px}}
  table{{border-collapse:collapse;width:100%;font-size:.85rem;min-width:760px}}
  thead th{{position:sticky;top:0;background:#eef2f7;text-align:left;padding:9px 10px;cursor:pointer;white-space:nowrap;user-select:none;border-bottom:1px solid var(--line);z-index:1}}
  thead th.num{{text-align:right}}
  thead th:hover{{color:var(--accent)}}
  tbody td{{padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap;vertical-align:top}}
  tbody tr:hover{{background:#f1f5fb}}
  td.num{{text-align:right;font-variant-numeric:tabular-nums}}
  td.tw{{font-weight:600}}
  td.pr{{font-weight:800;font-size:.95rem}}
  td.tloc{{white-space:normal;min-width:160px}}
  td.tloc a{{color:var(--ink);text-decoration:none}}
  td.tloc a:hover{{color:var(--accent);text-decoration:underline}}
  td.tarea{{color:var(--muted);font-size:.77rem}}
  td.dev{{font-weight:700;font-size:.78rem}}
  td.dev.d3{{color:#0e7d92}}td.dev.d2{{color:#1d5fd6}}td.dev.d1,td.dev.d0{{color:#7a8694}}
  .sc{{display:inline-block;min-width:30px;text-align:center;border-radius:6px;padding:1px 6px;font-weight:800;color:#10141a}}
  .sc.g-hi{{background:#7ee0c0}}.sc.g-mh{{background:#9ad0ff}}.sc.g-mid{{background:#ffe08a}}.sc.g-lo{{background:#c9d1da}}
  td .tag{{font-size:.68rem;padding:0 6px;margin:2px 3px 0 0}}
  /* ---- 学び（details） ---- */
  details{{background:var(--panel2);border:1px solid var(--line);border-radius:12px;margin:10px 0;overflow:hidden}}
  details>summary{{cursor:pointer;list-style:none;padding:12px 16px;font-weight:700;font-size:.95rem;background:#e9eef4}}
  details>summary::-webkit-details-marker{{display:none}}
  details>summary::before{{content:"▸ ";color:var(--accent)}}
  details[open]>summary::before{{content:"▾ "}}
  .dbody{{padding:12px 16px;font-size:.85rem;color:#2c3744}}
  .dbody li{{margin:4px 0}}
  /* 相場早見 */
  .mrow{{display:grid;grid-template-columns:130px 1fr;gap:10px;padding:10px 0;border-top:1px solid var(--line)}}
  .mrow:first-child{{border-top:none}}
  .mlabel{{font-weight:800;font-size:1.05rem;color:#10141a;border-radius:8px;padding:8px 10px;height:fit-content}}
  .mlabel small{{display:block;font-weight:500;font-size:.66rem;color:#0d1116;opacity:.85;margin-top:3px}}
  .mws{{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:6px}}
  .mw{{background:#f4f7fb;border:1px solid var(--line);border-radius:9px;padding:7px 9px;font-size:.8rem}}
  .mw b{{display:block;color:#2563eb}}
  .mw small{{color:var(--muted);font-size:.7rem}}
  /* 将来性マップ */
  .dvw{{display:grid;grid-template-columns:auto auto auto 1fr;align-items:center;gap:8px;padding:7px 0;border-top:1px solid var(--line)}}
  .dvw:first-child{{border-top:none}}
  .devb{{font-weight:800;border-radius:6px;padding:2px 7px;color:#10141a;font-size:.8rem}}
  .devb.d3{{background:#67d6e6}}.devb.d2{{background:#9ad0ff}}.devb.d1{{background:#c9d1da}}
  .dvw b{{min-width:64px}}.dvw small{{color:var(--muted);font-size:.72rem;min-width:34px}}
  .dvn{{color:#46505d;font-size:.8rem}}
  .spt{{padding:9px 11px;border-radius:10px;margin:6px 0;border:1px solid var(--line)}}
  .spt.s-wave{{background:#e9f5f8;border-color:#c4e2ea}}
  .spt.s-dev{{background:#f2ecfb;border-color:#ddccf3}}
  .spt b{{display:block;margin-bottom:2px}}
  .spt small{{display:block;color:var(--muted);font-size:.72rem;margin-top:3px}}
  .spotgrid{{display:grid;gap:6px}}
  @media(min-width:720px){{.spotgrid{{grid-template-columns:1fr 1fr}}}}
  .note{{background:var(--panel2);border:1px solid var(--line);border-left:4px solid var(--accent2);border-radius:10px;padding:10px 14px;font-size:.84rem;color:#2c3744;margin:14px 0}}
  .cu{{display:block;text-decoration:none;background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:11px 14px;margin:8px 0;color:var(--ink)}}
  .cu:hover{{border-color:var(--accent);background:#f0f5fd}}
  .cu b{{color:#2563eb}}.cu span{{display:block;color:var(--muted);font-size:.8rem}}
  .grid{{display:grid;gap:8px}}
  @media(min-width:720px){{.grid{{grid-template-columns:1fr 1fr}}}}
</style></head><body><div class="wrap">
<h1>資産価値が落ちない家さがし — 東京23区</h1>
<p class="tagline"><b>10〜30年“住んで”、売る時に「買値以上」で手放せる家</b>を探すツール。<span class="src">SUUMO／{stamp}／{count}件／毎日更新</span></p>
<details class="concept"><summary>💡 コンセプトと使い方</summary>
<div class="dbody">
<p><b>目的</b>：10〜30年“住んで”、売る時に<b>買値以上</b>で手放せる家を見つける。落ちない（できれば上がる）＝最高。だから安さ単体では選ばず、<b>出口（再売却）で価値が残る／上がるか</b>を最重視。<b>古い建物にはこだわらない</b>（新しくてもOK）。</p>
<p><b>■ 出口（売って利益）の作り方は4通り、どれもアリ</b></p>
<ol class="concept-l">
<li><b>そのまま住んで値持ち</b> ― 名門立地・人気エリア・ヴィンテージ</li>
<li><b>リノベして売る</b> ― 割安な中古を仕入れて価値を足す</li>
<li><b>土地・古家から建て替えて売る</b> ― 再建築可の土地／古家が素材</li>
<li><b>建替えまで保有して最終利益</b> ― 旧耐震等を等価交換の建替えまで持つ</li>
</ol>
<p><b>■ 採点の軸（資産スコア0-100）</b><br>①値持ち（名門立地・出口の堅さ）／②割安度（相場比）／③駅近／④将来性＝再開発の収益upside／⑤現地解像度／⑥<b>値上がり実測</b>（国交省・実取引の区㎡単価トレンド＝年率）。<br>町名プレミアムと値上がり率は<b>国交省・不動産情報ライブラリの実成約データ</b>で算出（カードに「区の実勢(年率)」を表示）。<b>プリセット</b>と<b>注目エリアタブ</b>で戦略別に絞り込み、📌から<b>好みを学習</b>して似た物件を上位表示。</p>
<p><b>■ 既定ルール</b><br>再建築不可・借地・駅徒歩16分以上は<b>除外</b>（建てて売る／値持ちが封じられるため）。旧耐震・古家付きは除外せず<b>“素材”として表示</b>（古家＝建替え素材で減点なし、旧耐震＝建替え目安も表示、名門立地のヴィンテージは値持ちするため過度に減点しない）。</p>
<p class="note">※ スコア・相場は簡易な目安。購入前に必ず現地・専門家確認を。</p>
</div></details>

{digest}
<details{watch_open}><summary>⭐ 追跡リスト — 住みたいエリア・気になる物件</summary>
<div class="dbody">{watch}</div></details>

<details><summary>📌 気になる物件 — 📌から好みを学習</summary>
<div class="dbody"><div id="pinprofile"></div><div id="sharebox"></div><div id="pinclicks"></div></div></details>

<div class="bar">
  <span><label>区</label><select id="fward"><option value="">すべて</option>{ward_opts}</select></span>
  <span><label>種別</label><select id="fkind"><option value="">すべて</option><option value="戸建">戸建</option><option value="マンション">マンション</option><option value="土地">土地</option></select></span>
  <span><label>並び</label><select id="fsort"><option value="score">資産スコア順</option><option value="aff">📌好み順（似てる）</option><option value="net">手取り(相場売却)順</option><option value="cagr">値上がり率(実取引)順</option><option value="dev">将来性(再開発)順</option><option value="price">価格が安い順</option><option value="total">実質総額が安い順</option><option value="ratio">割安(相場比)順</option><option value="walk">駅が近い順</option><option value="drop">値下げ率順</option><option value="days">滞留日数順</option></select></span>
  <span><label>価格上限(万円)</label><input id="fmax" type="number" inputmode="numeric" placeholder="例 5000" value="{budget}" style="width:110px"></span>
  <span><label>面積下限(㎡)</label><input id="fminarea" type="number" inputmode="numeric" placeholder="例 45" value="{minarea}" style="width:90px"></span>
  <span><label>最低スコア</label><input id="fscore" type="number" inputmode="numeric" placeholder="例 60" style="width:90px"></span>
  <span class="seg seg-area"><button type="button" id="aAll" class="on">すべて</button><button type="button" id="aWatch">⭐注目エリア</button><button type="button" id="aOther">その他</button></span>
  <span class="seg seg-preset"><button type="button" id="pNone" class="on" title="フィルタなし（全件表示）">条件なし</button><button type="button" id="pAsset" title="S/A・駅7分内・割安(相場比1.0+)・再建築不可/借地を除く＝資産価値が落ちにくい本命">💎資産価値</button><button type="button" id="pReno" title="再建築可の戸建/土地（古家OK）＋リノベ向きマンション（旧耐震ヴィンテージも可）＝建替え/リノベ前提">🔨建替/リノベ</button><button type="button" id="pFamily" title="マンション専有65㎡+&2LDK+／戸建3室+／土地50㎡+・再建築不可/借地を除く＝家族向け">👨‍👩‍👧ファミリー</button></span>
  <label class="ck"><input type="checkbox" id="fdrop"> 📉値下げのみ</label>
  <label class="ck"><input type="checkbox" id="fshin"> 🆕新築のみ</label>
  <label class="ck"><input type="checkbox" id="fmark"> 📌気になるのみ</label>
  <label class="ck"><input type="checkbox" id="fwaru"> ⚠️訳あり(再建築不可/借地)も表示</label>
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

<h2>値持ちの見極め（出口・相場・将来性・落とし穴）</h2>

<details><summary>🛡 値持ちの観点 — 出口で困らない視点</summary>
<div class="dbody">
<p class="lead">スコアは目安。最後は<b>「10〜30年後に、誰が・いくらで買ってくれるか（出口）」</b>を物件ごとに具体で考えます。値持ちを左右する主な観点：</p>
<ul>
<li><b>💰手取り目安（相場で今売却）</b>：各カードに「相場価値 − 買値 − 往復コスト(取得約7%/売却約3.5%)」を表示。<b>プラス＝割安クッションが往復コストを上回る</b>。満額のプレミアム物件はマイナス＝<b>その分の値上がりが必要</b>＝出口は将来の値上がり頼み、と読む。並びの「手取り順」で比較可。<br>※大きなプラスは“相場比が過大（訳あり）”のこともあるので🔎見立てと併読。</li>
<li><b>流動性（売りやすさ）</b>：駅近 × 実需サイズ（専有50〜80㎡）× 人気/名門エリア＝<b>いつでも買い手がいる</b>。スコアの駅近・出口ティア・規模・🏛値持ちが代理指標。<br>　逆に<b>実取引が極端に少ない町</b>（中心区なのに中古M成約が年8件未満＝特定組織の所有・利用が多い等で一般流通が乏しい。例：信濃町）は<b>出口に時間がかかる</b>ため、該当物件の🔎見立てに注意表示します。</li>
<li><b>管理・修繕の健全性（マンション）</b>：修繕積立金の積立不足は将来の一時金・値崩れに直結。<b>総戸数が多いほど管理が安定</b>（小規模は1戸あたり負担が重い）。🔎見立てで「積立金低め」を警告。</li>
<li><b>建替え事業性（戦略④）</b>：<b>容積に余裕</b>（消化率が低い）・敷地権割合・合意のしやすさ＝建替えで等価交換の含み益。都心・駅近・低層ほど有利。各カードに建替え目安年。</li>
<li><b>建てて売る成立性（戦略③）</b>：<b>再建築可・接道・用途地域/容積</b>＝土地/古家の建替え事業が成立するか。再建築不可は既定で除外。</li>
<li><b>災害リスク</b>：標高（低地＝浸水・液状化）・旧耐震の耐震性。🔎見立てで低地を警告、ハザードマップは必ず確認。</li>
<li><b>住環境・学区</b>：将来の家族なら人気学区・公園・治安＝実需が厚く値持ち。</li>
<li><b>供給過剰リスク</b>：大量供給エリア（湾岸タワマン等）は中古の値崩れ余地。<b>希少立地はその逆</b>＝値持ちの源泉。</li>
<li><b>金利・ローン適合</b>：旧耐震・再建築不可は融資が付きにくく<b>買い手が限られる＝出口が狭い</b>。現金/リノベ前提の戦略とセットで。</li>
</ul>
</div></details>

<details><summary>📊 相場早見表 — 区別の相場＆出口ティア</summary>
<div class="dbody">
<p class="lead"><b>相場比＝区の相場坪単価 ÷ この物件の坪単価</b>。1.0＝相場どおり、1.2＝相場より約17%安い、2.0＝相場の半額。<b>数字が大きいほど割安</b>（カードでは「相場より◯%安い」と表示）。ただし2倍超の“激安”は再建築不可・借地・狭小など理由ありのサイン。ティアは売却時の“出口の堅さ”（S＝都心中枢ほど下値が堅い）。（）内は今の掲載件数。</p>
{market}
</div></details>

<details><summary>🏗 将来性マップ — 区別の再開発の勢い</summary>
<div class="dbody">
<p class="lead">再開発が活発な区＝将来の“出口の上振れ”が期待できる。スコアにも控えめに反映（★3で+4点ほど）。<b>★は2026年時点の調査ベースの目安</b>。</p>
{devmap}
</div></details>

<details><summary>🌊 波の前夜エリア — 今割安・これから更新</summary>
<div class="dbody">
<p class="lead">住所（丁目）単位で、<b>🏗再開発が直撃／近接</b>・<b>🚇新駅/延伸の沿線</b>・<b>🌊木造住宅が密集し東京都『不燃化特区』等で更新が進む地区</b>を判定。
「今は古家が多く割安だが、これから波が来る」エリアを拾う（例：新宿西口北側の<b>北新宿</b>＝西新宿再開発の波及／<b>港区港南・高輪</b>＝南北線品川延伸）。物件カードにも該当メモを表示します。</p>
<div class="spotgrid">{spotmap}</div>
<p class="lead" style="margin-top:10px">出典：東京都都市整備局「不燃化特区」各区の取組／各区・東京都の市街地再開発／鉄道各社・国交省の延伸事業。<b>🚇鉄道計画は構想〜事業中で時期未確定のものを含む</b>。具体の進捗・範囲は必ず公式で確認を。</p>
</div></details>

<details><summary>🔎 安い理由の読み方 — 見立ての使い方</summary>
<div class="dbody">
<p class="lead">各カードの<b>🔎見立て(推定)</b>は、手持ちデータ（相場比・タグ・築年・駅距離・規模）から「<b>この安さの主因は何か</b>」を推定したもの。<b>断定ではなく現地確認の出発点</b>。表ビューでは価格セルにカーソルを当てると表示。</p>
<ul>
<li><b>相場比が極端（1.8倍超）</b>：まだ見えていない難（接道・間口・方位・嫌悪施設＝隣に飲食店/線路際 等）の可能性。安さには必ず理由がある前提で現地へ。</li>
<li><b>再建築不可／借地／旧耐震／古家</b>：安さの主因が明確。出口（売却・融資）の制約をコストとして織り込む。</li>
<li><b>駅遠・狭小・極小ワンルーム</b>：実需が薄く価格が出にくい。賃貸・転売の出口を具体に描けるかが鍵。</li>
<li><b>難が見当たらず割安</b>：指値・設備更新で“詰める”領域。掲載が長い物件は値下げ余地があることも（＝大家が売り急ぐ／こだわらないサイン）。</li>
<li><b>📉値下げ／⏳滞留バッジ</b>：当ツールが毎日価格を記録し、<b>値下げ額・観測日数</b>を自動算出。値下げ＝指値が通りやすい・売り急ぎのサイン、滞留が長い＝買い手不在で交渉余地。<b>「値下げ率順」「滞留日数順」で並べ替え可能</b>。</li>
<li><b>🏃売り急ぎ?（指値余地）バッジ</b>：詳細ページのPR/備考に<b>相続・売り急ぎ・早期売却・即金・価格応談</b>等の語を検知。<b>相続は申告期限（10ヶ月）で1年以内に売り急ぐ</b>ことが多く、<b>相場価値より安く出る＝割安取得チャンス</b>。今日のダイジェストにも一覧表示。※業者表現のこともあるので必ず現地・売却理由を確認。</li>
</ul>
<p class="lead">※観測日数は「当ツールが最初に見た日」起点（SUUMOの掲載開始日ではない）。日が経つほど精度が上がります。「大家が売り急いでいるか」の最良の代理指標です。</p>
</div></details>

<details><summary>💎 穴場の見つけ方 — スコアの読み方</summary>
<div class="dbody">
<p><b>資産スコア（0-100）</b>＝「<b>売る時に買値以上で手放せるか＝資産が落ちないか</b>」を点数化したもの。配点：</p>
<ul class="scorebreak">
<li><b>割安度（相場比）最大40</b>：区相場×（駅距離・築年・<b>名門立地</b>補正）÷この物件の単価。1.0＝相場どおり、1.4＝約3割安。</li>
<li><b>駅近 最大25</b>：徒歩2分=満点、遠いほど減。流動性＝出口の広さに直結。</li>
<li><b>出口の堅さ＝エリアティア 最大25</b>：S(都心中枢)＞A＞B＞C。下値の堅さ＝買値割れしにくさ。</li>
<li><b>規模 最大10</b>：実需が付く広さか（マンション専有・戸建/土地は土地面積）。</li>
<li><b>🏛立地プレミアム（値持ち）最大+12</b>：内藤町・青葉台・松濤・番町・南青山・上原・広尾等の名門アドレスは、<b>満額で買っても下値が堅く“買値以上で売れる”可能性が高い</b>ため加点。本プロジェクトの核。</li>
<li><b>将来性（再開発）最大+6</b>：区・地区の更新ポテンシャル＝<b>収益upside</b>。10〜30年保有で効くため重め。</li>
<li><b>減点</b>：再建築不可 −20（＝建てて売る／建替えて売るが封じられる）／借地権 −12／旧耐震 −6（<b>名門立地では −3</b>＝立地が出口を支え値持ちするため半減）。<b>古家付きは減点なし</b>＝「壊して建て直して売る」戦略の素材（解体費は🔎見立てに注記）。リスクは消さずタグ・見立て・建替え目安で明示。</li>
</ul>
<p style="font-size:.88rem"><b>出口（売って利益）の作り方は4通り、どれでもスコアが活きる設計：</b></p>
<ul>
<li><b>①そのまま住んで値持ち</b>：名門立地・人気エリア・ヴィンテージ。→ 🏛値持ち＋出口ティアが効く。</li>
<li><b>②リノベして売る</b>：割安な中古を仕入れて価値を足す。→ 割安度＋駅近。<b>🔨建替/リノベ</b>プリセット。</li>
<li><b>③土地・古家から建て替えて売る</b>：再建築可の土地/古家が素材。→ 再建築不可は除外、古家は減点なし。</li>
<li><b>④建替えまで保有して最終利益</b>：旧耐震等を等価交換の建替えまで持つ。→ 旧耐震減点を抑え、<b>建替え目安年</b>を見立てに表示。</li>
</ul>
<ul>
<li><b>💎穴場候補</b>バッジ＝「相場比1.3倍以上 × 駅徒歩7分以内 × 注意タグ無し」。割安なのに出口・利便が確保できている本命ゾーン。</li>
<li><b>🏛名門アドレス・値持ち</b>バッジ＝プレミアム微立地。<b>割安でなくても“資産が落ちない”狙いの本命</b>（満額でも値持ち）。</li>
<li><b>★高評価</b>バッジ＝スコア78以上。値持ち×割安×駅近×出口の総合点が高い。</li>
<li>狙いは<b>「買値以上で売れる」＝出口S/A × 駅近 ×（割安 または 名門立地の値持ち または 再開発upside）</b>。価格の安さだけでは選ばない。</li>
</ul>
</div></details>

<details><summary>⚠️ 落とし穴 — タグの意味とリスク</summary>
<div class="dbody">
<ul>
<li><b>再建築不可</b>（−20）：接道義務（幅員4m道路に2m以上接道）未達。今の建物を壊すと建て直せない＝<b>住宅ローンが付きにくく出口が極端に狭い</b>。現金/リフォーム前提の上級者向け。<br>　※<b>相場比・手取り目安は割引後の実勢で計算</b>（相場の約55%＝建築可前提の相場をそのまま当てない）。なので「相場の半額＝激安」と誤表示しません。借地は約60%で同様。</li>
<li><b>借地権</b>（−12）：土地は借り物。地代・更新料・譲渡承諾料が発生し、<b>融資・売却に地主の承諾が要る</b>。旧法借地権は借地人有利だが流動性は低い。</li>
<li><b>古家付き土地</b>（<b>減点なし＝戦略の“素材”</b>）：再建築可なら「<b>壊して建て直して売る</b>」の好材料。リスクではなく出口の選択肢。解体費（木造で150〜250万円目安）と滅失登記だけ実質コストに織り込む（表示価格＋解体費で判断）。</li>
<li><b>旧耐震マンション</b>（−6・除外せず注意タグ）：1981年以前の旧基準。住宅ローン/フラット35が付きにくく出口は限定。<b>ただし“建替えまで持つ”出口もある</b>＝都心・駅近で容積に余裕がある低層物件は、建替え（等価交換）で<b>新築区分を持ち出し少なく取得→含み益</b>が狙える。<br>　<b>建替え時期の目安＝築50〜60年（中心55年）</b>。例：1975年築なら2025〜2035年頃が検討ゾーン。実際の建替えは区分所有法の<b>5分の4合意</b>が必要で全国でも事例は少数・期間も不確実（10〜20年塩漬けもザラ）。ただし<b>2024年の区分所有法改正で決議要件は緩和方向</b>＝今後は進みやすくなる可能性。各カードの🔎見立てに物件ごとの目安年を表示。</li>
<li><b>セットバック</b>：42条2項道路に接する敷地は中心線から2m後退が必要。後退部分は建築・容積に算入不可＝<b>使える面積が減る</b>。</li>
<li><b>私道・掘削承諾</b>：私道接道はインフラ更新時に掘削承諾が必要。無いと<b>リフォーム・建替・融資が詰まる</b>頻出の隠れ瑕疵。</li>
<li>共通：<b>内見・現地・登記簿・公図・接道</b>を必ず確認。安さには理由がある前提で“理由を割り出して納得できる割安”だけ狙う。</li>
</ul>
</div></details>

<details><summary>📅 公売スケジュール — <span id="kobaiNext">次回を計算中…</span></summary>
<div class="dbody">
<p class="lead">税滞納差押えの<b>公売</b>（現金前提・内覧不可・契約不適合責任なし）は年3回。<b>事前に知るなら公式メルマガ登録が確実</b>。下は東京都主税局の例年パターン（日付は目安。最終は公式で確認）。</p>
<div class="tblwrap-g"><table class="kobai">
<thead><tr><th>回</th><th>公告</th><th>入札期間</th><th>開札</th><th>代金納付</th></tr></thead>
<tbody>
<tr><td>第1回</td><td>6/12頃</td><td><b>7/10〜7/17頃</b></td><td>7/22頃</td><td>8/12頃</td></tr>
<tr><td>第2回</td><td>9/25頃</td><td><b>10/16〜10/23頃</b></td><td>10/27頃</td><td>11月中</td></tr>
<tr><td>第3回</td><td>1月中</td><td><b>1月末〜2月初</b></td><td>2月初</td><td>3月初</td></tr>
</tbody></table></div>
<p class="lead" style="margin-top:8px">・東京都主税局 郵送公売：<a href="https://www.tax.metro.tokyo.lg.jp/kobai/mail" target="_blank" rel="noopener">公式↗</a>（メルマガ登録で実施通知）<br>・国税庁 公売（東京国税局）：<a href="https://www.koubai.nta.go.jp/" target="_blank" rel="noopener">公式↗</a> ／ 今後の日程：<a href="https://www.koubai.nta.go.jp/auctionx/public/hp_sh_001.php" target="_blank" rel="noopener">日程↗</a><br>・裁判所 競売（BIT・随時/期間入札）：<a href="https://www.bit.courts.go.jp/" target="_blank" rel="noopener">BIT↗</a></p>
<p class="lead">⚠️ 公売・競売はローン特約が使えず<b>現金または専用ローンの事前内諾が前提</b>。本スクリーナーの売り物件（SUUMO）とは別ルートです。</p>
</div></details>

<details><summary>🔗 他サイトリンク</summary>
<div class="dbody">
<p class="lead">cowcamo・HOME'S・at home・楽待・健美家は、SPAやアクセス制限のため自動一覧に統合できません。最新は各公式でご確認ください（cowcamoはリノベ・デザイン重視で“脱ゲテモノ”に好相性）。</p>
<div class="grid">{curated}</div>
</div></details>

<div class="note">⚠️ 価格・在庫・相場は変動します。本スクリーナーはSUUMOからの自動取得スナップショット＋簡易スコアです。
購入判断の前に、再建築可否・接道・境界・用途地域・融資・出口を必ず現地と専門家（不動産業者/建築士/司法書士/金融機関）で確認してください。</div>

<script>
const el=id=>document.getElementById(id);
const grid=el('grid'), cards=[...grid.children];
const tbody=el('tbody'), trs=[...tbody.children];
const fward=el('fward'),fkind=el('fkind'),fsort=el('fsort'),fmax=el('fmax'),fscore=el('fscore'),fdrop=el('fdrop'),fminarea=el('fminarea'),fshin=el('fshin'),fwaru=el('fwaru'),fmark=el('fmark');
let areaMode='all';   // all | watch | other （注目エリア/その他タブ）
let watchLabel='';    // 追跡リストの「◯件」クリックで特定エリアに絞る
let presetMode='none';// none | asset | family | live | reno （プリセット）
let renoGrade='full'; // full | simple （リノベ単価）
const RISKY=/(再建築不可|借地権)/;
const RRATE={{S:22,A:20,B:18,C:16}};
function calcExtra(d){{
  if(d.kind==='マンション'&&parseFloat(d.area||'0')>0){{
    const rate=(renoGrade==='simple')?9:(RRATE[d.tier]||18);
    return {{extra:Math.round(parseFloat(d.area)*rate),lab:'リノベ',rate:rate}};
  }}
  if(d.furuya==='1'){{
    const land=parseFloat(d.land||'0')||parseFloat(d.area||'0')||0;
    return {{extra:land?Math.max(120,Math.round(land*1.5)):200,lab:'解体'}};
  }}
  return {{extra:0}};
}}
function computeCosts(){{
  for(const c of cards){{
    const d=c.dataset,e=calcExtra(d);
    d.total=(parseInt(d.price,10)||0)+e.extra;
    const box=c.querySelector('.cost');
    if(box) box.innerHTML = e.extra ?
      `💰 実質目安 <b>約${{d.total.toLocaleString()}}万</b><span class="brk"> ＝ 買値${{(parseInt(d.price,10)||0).toLocaleString()}} ＋ ${{e.lab}}${{e.extra.toLocaleString()}}${{e.rate?`(${{e.rate}}万/㎡)`:''}}</span>` : '';
  }}
  for(const t of trs){{const d=t.dataset;d.total=(parseInt(d.price,10)||0)+calcExtra(d).extra;}}
}}
function preset(d){{
  if(presetMode==='asset'){{
    if(!(d.tier==='S'||d.tier==='A'))return false;
    if(parseInt(d.walk,10)>7)return false;
    if(RISKY.test(d.tags))return false;
    if(parseFloat(d.ratio||'0')<1.0)return false;
    if(d.kind==='土地')return false;
    if(d.kind==='マンション'&&(parseFloat(d.area||'0')<45||parseInt(d.year||'0')<1990))return false;
  }}
  if(presetMode==='family'){{
    if(RISKY.test(d.tags))return false;
    const ok=(d.kind==='マンション'&&parseFloat(d.area||'0')>=65&&parseInt(d.rooms||'0')>=2)||(d.kind==='戸建'&&parseInt(d.rooms||'0')>=3)||(d.kind==='土地'&&parseFloat(d.land||'0')>=50);
    if(!ok)return false;
  }}
  if(presetMode==='reno'){{
    // 再建築可の戸建/土地（古家・築古OK）＋ 新耐震マンション（リノベ向き）。再建築不可・借地は除外
    if(/(再建築不可|借地権)/.test(d.tags))return false;
    if(d.kind==='マンション'&&parseFloat(d.area||'0')<45)return false;
  }}
  return true;
}}
let sortK='score', sortAsc=false;
const defAsc=k=>(k==='price'||k==='walk'||k==='total');   // 価格・総額・駅徒歩は小さい順、その他は大きい順を既定に
function pass(d){{
  if(fward.value&&d.ward!==fward.value)return false;
  if(fkind.value&&d.kind!==fkind.value)return false;
  const mx=parseInt(fmax.value||'0',10); if(mx&&parseInt(d.price,10)>mx)return false;
  const ms=parseInt(fscore.value||'0',10); if(ms&&parseInt(d.score,10)<ms)return false;
  if(areaMode==='watch'&&d.watch!=='1')return false;
  if(areaMode==='other'&&d.watch==='1')return false;
  if(watchLabel&&d.watchlabel!==watchLabel)return false;
  if(presetMode!=='none'&&!preset(d))return false;
  if(fdrop.checked&&parseInt(d.drop||'0',10)<=0)return false;
  if(d.use==='投資')return false;
  {{const w=parseInt(d.walk||'999',10); if(w>=16&&w<900)return false;}}  // 駅徒歩16分以上は全体で除外（駅情報なし999は残す）
  if(fshin.checked&&d.shin!=='1')return false;
  if(!fwaru.checked&&/(再建築不可|借地権)/.test(d.tags))return false;
  if(fmark.checked&&!marks.has(d.id))return false;
  const ma=parseFloat(fminarea.value||'0'); if(ma){{const sz=d.kind==='土地'?(parseFloat(d.land)||0):(parseFloat(d.area)||0); if(sz>0&&sz<ma)return false;}}
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
[fward,fkind,fmax,fscore,fdrop,fminarea,fshin,fwaru,fmark].forEach(e=>e.addEventListener('input',apply));
{{const A=el('aAll'),W=el('aWatch'),O=el('aOther');
 function setA(m,b){{areaMode=m;[A,W,O].forEach(x=>x.classList.remove('on'));b.classList.add('on');apply();}}
 A.addEventListener('click',()=>setA('all',A));W.addEventListener('click',()=>setA('watch',W));O.addEventListener('click',()=>setA('other',O));}}
{{const P={{none:el('pNone'),asset:el('pAsset'),reno:el('pReno'),family:el('pFamily')}};
 function setP(m){{presetMode=m;Object.values(P).forEach(x=>x.classList.remove('on'));P[m].classList.add('on');apply();}}
 P.none.addEventListener('click',()=>setP('none'));P.asset.addEventListener('click',()=>setP('asset'));
 P.reno.addEventListener('click',()=>setP('reno'));
 P.family.addEventListener('click',()=>setP('family'));}}
fsort.addEventListener('change',()=>{{sortK=fsort.value;sortAsc=defAsc(sortK);apply();}});
document.querySelectorAll('thead th[data-k]').forEach(th=>th.addEventListener('click',()=>{{
  const k=th.dataset.k; if(k==='ward')return;
  if(k===sortK)sortAsc=!sortAsc; else {{sortK=k;sortAsc=defAsc(k);}}
  fsort.value=k; apply();
}}));
const vT=el('vTable'),vC=el('vCard');
vT.addEventListener('click',()=>{{vT.classList.add('on');vC.classList.remove('on');el('tblwrap').classList.remove('hidden');grid.classList.add('hidden');}});
vC.addEventListener('click',()=>{{vC.classList.add('on');vT.classList.remove('on');grid.classList.remove('hidden');el('tblwrap').classList.add('hidden');}});
if(!localStorage.getItem('marksSeeded')){{var _seed=JSON.parse(localStorage.getItem('marks')||'[]').concat({pinids});localStorage.setItem('marks',JSON.stringify([...new Set(_seed)]));localStorage.setItem('marksSeeded','1');}}
let marks=new Set(JSON.parse(localStorage.getItem('marks')||'[]'));
// 📌した物件のスナップショット（掲載終了後も情報を保持するため）
let pinData=JSON.parse(localStorage.getItem('pinData')||'{{}}');
{{var _pm={pinmeta};for(var _k in _pm){{if(!pinData[_k])pinData[_k]={{n:_pm[_k].n,loc:_pm[_k].s,price:'',url:_pm[_k].u}};}}localStorage.setItem('pinData',JSON.stringify(pinData));}}
// 端末間共有：URLの #share= を読み込んで📌をローカルに統合（外部サーバー不要・完全プライベート）
(function(){{
  var m=(location.hash||'').match(/share=([^&]+)/);
  if(!m)return;
  try{{
    var b=decodeURIComponent(m[1]).replace(/-/g,'+').replace(/_/g,'/');
    while(b.length%4)b+='=';
    var obj=JSON.parse(decodeURIComponent(escape(atob(b))));
    (obj.m||[]).forEach(function(id){{marks.add(id);}});
    if(obj.d){{for(var k in obj.d){{if(!pinData[k])pinData[k]=obj.d[k];}}}}
    localStorage.setItem('marks',JSON.stringify([...marks]));
    localStorage.setItem('pinData',JSON.stringify(pinData));
  }}catch(e){{}}
  history.replaceState(null,'',location.pathname);
}})();
function makeShareUrl(){{
  var d={{}};for(var k in pinData){{var v=pinData[k]||{{}};d[k]={{n:v.n||'',loc:v.loc||'',price:v.price||'',url:v.url||''}};}}
  var payload=JSON.stringify({{m:[...marks],d:d}});
  var b64=btoa(unescape(encodeURIComponent(payload))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  return location.origin+location.pathname+'#share='+b64;
}}
function renderShare(){{
  var box=document.getElementById('sharebox');if(!box)return;
  if(!marks.size){{box.innerHTML='';return;}}
  var url=makeShareUrl();
  box.innerHTML='<div class="sharerow"><b>🔗 端末間で共有・同期</b>'
    +'<div class="shareflex"><input id="shareurl" readonly value="'+url.replace(/"/g,'&quot;')+'">'
    +'<button id="sharecopy" class="sharebtn" type="button">コピー</button></div>'
    +'<div class="hs">このリンクを<b>自分の別の端末や共有したい人</b>に送り、開くと📌が読み込まれます（相手の📌に統合）。📌を増減したら再送で同期。外部サーバーは使わず端末内に保持。</div></div>';
}}
document.addEventListener('click',function(e){{
  if(e.target&&e.target.id==='sharecopy'){{
    var i=document.getElementById('shareurl');if(!i)return;
    i.select();try{{navigator.clipboard.writeText(i.value);}}catch(_){{document.execCommand('copy');}}
    e.target.textContent='コピー済✓';setTimeout(function(){{e.target.textContent='コピー';}},1500);
  }}
}});
function snapCard(id){{
  var c=grid.querySelector('.card[data-id="'+id+'"]');if(!c)return null;
  var le=c.querySelector('.loc').cloneNode(true);
  le.querySelectorAll('.tier,.kindchip').forEach(function(x){{x.remove();}});
  var loc=le.textContent.trim();
  var pe=c.querySelector('.price');var price=pe?pe.textContent.trim():'';
  var a=c.querySelector('.viewrow a[href]');var url=a?a.getAttribute('href'):'#';
  var ne=c.querySelector('.mn');var nm=ne?ne.textContent.trim():'';
  var ds=c.dataset;
  var f={{ward:ds.ward||'',kind:ds.kind||'',area:parseFloat(ds.area)||0,land:parseFloat(ds.land)||0,
    walk:parseInt(ds.walk||'999',10),year:parseInt(ds.year||'0',10),tiern:parseInt(ds.tiern||'0',10),
    ratio:parseFloat(ds.ratio)||0,price:parseInt(ds.price||'0',10),rooms:parseInt(ds.rooms||'0',10)}};
  return {{n:nm,loc:loc,price:price,url:url,f:f}};
}}
// ===== 📌から好みを学習（掲載終了したスナップショットも教師データに含める） =====
function _median(arr){{if(!arr.length)return null;var s=arr.slice().sort(function(a,b){{return a-b;}});var m=Math.floor(s.length/2);return s.length%2?s[m]:(s[m-1]+s[m])/2;}}
let affProf=null;
function pinProfile(){{
  var fs=[];marks.forEach(function(id){{var p=pinData[id];if(p&&p.f)fs.push(p.f);}});
  if(fs.length<2)return null;
  var wards={{}},kinds={{}};
  fs.forEach(function(f){{if(f.ward)wards[f.ward]=(wards[f.ward]||0)+1;if(f.kind)kinds[f.kind]=(kinds[f.kind]||0)+1;}});
  function col(key,min){{return fs.map(function(f){{return f[key];}}).filter(function(v){{return v&&v>(min||0);}});}}
  return {{n:fs.length,wards:wards,kinds:kinds,
    area:_median(col('area',0)),
    walk:_median(fs.map(function(f){{return f.walk;}}).filter(function(v){{return v>0&&v<900;}})),
    year:_median(col('year',1900)),price:_median(col('price',0)),rooms:_median(col('rooms',0))}};
}}
function affinity(d,prof){{
  if(!prof)return 0;
  var sc=0,wt=0;
  wt+=25; if(prof.wards[d.ward])sc+=25;                                   // 同じ区
  wt+=15; if(prof.kinds[d.kind])sc+=15;                                   // 同じ種別
  if(prof.area){{wt+=20;var a=parseFloat(d.area)||parseFloat(d.land)||0;if(a>0)sc+=20*Math.max(0,1-Math.abs(a-prof.area)/prof.area);}}
  if(prof.walk!=null){{wt+=18;var w=parseInt(d.walk||'999',10);if(w>0&&w<900)sc+=18*Math.max(0,1-Math.abs(w-prof.walk)/Math.max(6,prof.walk));}}
  if(prof.year){{wt+=12;var y=parseInt(d.year||'0',10);if(y>1900)sc+=12*Math.max(0,1-Math.abs(y-prof.year)/25);}}
  if(prof.price){{wt+=10;var pr=parseInt(d.price||'0',10);if(pr>0)sc+=10*Math.max(0,1-Math.abs(pr-prof.price)/prof.price);}}
  return wt?Math.round(sc/wt*100):0;
}}
function badgeRow(c){{var b=c.querySelector('.bd');if(!b){{b=document.createElement('div');b.className='bd';c.insertBefore(b,c.querySelector('.facts'));}}return b;}}
function computeAffinity(){{
  affProf=pinProfile();
  for(var i=0;i<cards.length;i++)cards[i].dataset.aff=affProf?affinity(cards[i].dataset,affProf):0;
  for(var j=0;j<trs.length;j++)trs[j].dataset.aff=affProf?affinity(trs[j].dataset,affProf):0;
  document.querySelectorAll('.affbadge').forEach(function(x){{x.remove();}});
  if(affProf){{cards.forEach(function(c){{var v=parseInt(c.dataset.aff,10);if(v>=70){{var b=document.createElement('span');b.className='bdg b-aff affbadge';b.textContent='💖好み'+v;var br=badgeRow(c);br.insertBefore(b,br.firstChild);}}}});}}
  renderProfile(affProf);
}}
function renderProfile(prof){{
  var box=document.getElementById('pinprofile');if(!box)return;
  if(!prof){{box.innerHTML='<div class="lead">📌が2件以上たまると、エリア・面積・駅距離・築年・価格帯から<b>あなたの好み</b>を学習し、似た物件を上位に出します（並び＝「📌好み順」、カードに💖好み○バッジ）。</div>';return;}}
  function topk(m){{return Object.keys(m).sort(function(x,y){{return m[y]-m[x];}}).slice(0,3);}}
  var parts=[];
  if(Object.keys(prof.wards).length)parts.push('エリア: '+topk(prof.wards).join('・'));
  if(Object.keys(prof.kinds).length)parts.push('種別: '+topk(prof.kinds).join('・'));
  if(prof.area)parts.push('面積: '+Math.round(prof.area)+'㎡前後');
  if(prof.walk!=null)parts.push('駅徒歩: '+Math.round(prof.walk)+'分前後');
  if(prof.year)parts.push('築年: '+prof.year+'年前後');
  if(prof.price)parts.push('価格帯: '+(prof.price>=10000?(prof.price/10000).toFixed(2)+'億':prof.price+'万')+'前後');
  box.innerHTML='<div class="wsub">🎯 あなたの📌プロフィール（'+prof.n+'件から学習）</div><div class="profline">'+parts.join(' ／ ')+'<br><span class="hs">↑この傾向に近い物件ほど 💖好み の数値が高く、「📌好み順」で上位に並びます。</span></div>';
}}
function renderMarks(){{document.querySelectorAll('.mark').forEach(b=>{{const on=marks.has(b.dataset.id);b.classList.toggle('on',on);b.textContent=b.classList.contains('mk-t')?'📌':'📌気になる';}});}}
function renderPinClicks(){{
  var box=document.getElementById('pinclicks');if(!box)return;
  var changed=false;
  var h='',n=0;
  marks.forEach(function(id){{
    var snap=snapCard(id);var live=!!snap;
    if(live){{ if(JSON.stringify(pinData[id])!==JSON.stringify(snap)){{pinData[id]=snap;changed=true;}} }}
    else {{ snap=pinData[id]; }}
    if(!snap)return;  // 一度も観測できていない（古いシード等）はスキップ
    var loc=snap.loc||snap.n||'(物件)';
    var price=snap.price?'<span class="hp">'+snap.price+'</span>':'';
    var url=snap.url||'#';
    var gm='https://www.google.com/maps/search/?api=1&query='+encodeURIComponent('東京都'+loc);
    var gone=live?'':'<span class="gone">⚠掲載終了/売却の可能性</span>';
    h+='<div class="hit'+(live?'':' off')+'"><b>📌</b> '+loc+price+gone+' <a href="'+url+'" target="_blank" rel="noopener">SUUMO↗</a> <a href="'+gm+'" target="_blank" rel="noopener">🗺</a></div>';
    n++;
  }});
  if(changed)localStorage.setItem('pinData',JSON.stringify(pinData));
  box.innerHTML=n?'<div class="wsub">📌 気になる物件 '+n+'件</div>'+h:'<div class="lead">まだ📌はありません。一覧のカード/行の📌で登録できます。</div>';
  renderShare();
}}
document.addEventListener('click',e=>{{const b=e.target.closest('.mark');if(!b)return;e.preventDefault();const id=b.dataset.id;if(marks.has(id)){{marks.delete(id);delete pinData[id];}}else{{marks.add(id);var s=snapCard(id);if(s)pinData[id]=s;}}localStorage.setItem('marks',JSON.stringify([...marks]));localStorage.setItem('pinData',JSON.stringify(pinData));renderMarks();renderPinClicks();computeAffinity();apply();}});
document.addEventListener('click',e=>{{const b=e.target.closest('.wcbtn');if(!b)return;e.preventDefault();const wl=b.dataset.wl;watchLabel=(watchLabel===wl)?'':wl;document.querySelectorAll('.wcbtn').forEach(x=>x.classList.toggle('on',x.dataset.wl===watchLabel&&watchLabel!==''));apply();(grid.classList.contains('hidden')?el('tblwrap'):grid).scrollIntoView({{behavior:'smooth'}});}});
renderMarks();renderPinClicks();computeAffinity();
(function(){{var ds=[[7,10],[10,16],[1,29]];var now=new Date();var best=null;for(var i=0;i<ds.length;i++){{for(var k=0;k<2;k++){{var y=now.getFullYear()+k;var dt=new Date(y,ds[i][0]-1,ds[i][1]);if(dt>=now){{if(!best||dt<best)best=dt;break;}}}}}}var el=document.getElementById('kobaiNext');if(el&&best){{var days=Math.ceil((best-now)/86400000);el.textContent='次回 入札開始 '+(best.getMonth()+1)+'/'+best.getDate()+'（あと'+days+'日）';}}}})();
computeCosts();apply();
</script>
</div></body></html>"""


def collection_selfcheck(rows):
    """収集件数の自己点検。前日傾向比で総数/カテゴリが急減したら警告（パース崩れ・サイト変更の早期検知）。
    日次統計を data/collect_stats.json に蓄積（毎日の差分で異常が追える）。"""
    jst = datetime.timezone(datetime.timedelta(hours=9))
    today = datetime.datetime.now(jst).date().isoformat()
    kinds = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    stat = {"date": today, "total": len(rows),
            "戸建": kinds.get("戸建", 0), "マンション": kinds.get("マンション", 0),
            "土地": kinds.get("土地", 0),
            "新築": sum(1 for r in rows if "新築" in r["tags"]),
            "detailed": sum(1 for r in rows if r.get("detailed"))}
    sf = DATA / "collect_stats.json"
    try:
        hist = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else []
    except Exception:
        hist = []
    prev = [h for h in hist if h.get("date") != today]

    def med(key, n=7):
        vals = sorted(h[key] for h in prev[-n:] if isinstance(h.get(key), int))
        return vals[len(vals) // 2] if vals else None

    warnings = []
    mt = med("total")
    if mt and stat["total"] < mt * 0.7:
        warnings.append(f"総件数が急減 {stat['total']}件（直近中央値{mt}）＝パース崩れ/サイト変更の可能性")
    for k in ("戸建", "マンション", "土地"):
        mk = med(k)
        if mk and mk >= 5 and stat[k] < mk * 0.6:
            warnings.append(f"{k}が急減 {stat[k]}件（直近中央値{mk}）")
    stat["warnings"] = warnings
    try:
        sf.write_text(json.dumps((prev + [stat])[-60:], ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    return stat, warnings


def main():
    rows, errors = collect()
    update_history(rows)          # 観測日数・値下げを付与（毎日の蓄積）
    stat, warnings = collection_selfcheck(rows)
    for w in warnings:
        print("  ⚠SELFCHECK", w, file=sys.stderr)
    rows.sort(key=lambda x: (-x["score"], x["price"]))
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
