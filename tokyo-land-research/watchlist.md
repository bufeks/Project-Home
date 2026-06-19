# 定点観測リスト（watchlist.md）

## ★ あなた専用の追跡リスト（`watchlist.json`）

「住みたいエリア・気になるマンション・好きな町」を登録すると、一覧（listings.html）で
**該当物件を⭐ハイライト＆件数表示**し、毎日の自動更新で継続追跡する。
中古マンション等で一覧（戸建/土地）に出ないものは、地図・検索リンクで追える。

データは `watchlist.json`。スキーマ：

```json
{
  "areas": [
    {"match": "世田谷区松原", "label": "松原（明大前）", "note": "好きな町"}
  ],
  "buildings": [
    {"name": "パークコート◯◯", "area": "港区", "note": "狙い"}
  ]
}
```

- `areas[].match`：物件住所（例「世田谷区松原」）への**部分一致**で⭐判定。区だけ／丁目まで、粒度は自由。
- `areas[].label`：表示名（駅名など分かりやすく）。`note`：メモ。
- `buildings`：一覧に出ない分譲マンション等。地図＆「中古マンション SUUMO」検索リンクを自動生成。
- **追加方法**：チャットで「◯◯に住みたい」「△△マンションが気になる」と言うだけ。こちらが `watchlist.json` に追記→次の自動更新で反映。

---

毎月または隔週で巡回するサイト一覧（以下は調査ソース）。
URLは2026年6月時点で確認済み。⚠️は要再確認・流動的。

> 公的ルート（国有地・公有地・公売・競売）は落札後の代金納付期限が短く、
> 通常の住宅ローン特約（ローン不可なら白紙解除）が使えない。
> **現金または競売・公売専用ローンの事前内諾**が前提になる点を常に意識する。

---

## A. 国有地・公有地（安全性高・出物少）

| サイト名 | URL | 見る頻度 | 見るべき条件 | 学ぶべきポイント | 備考 |
|---|---|---:|---|---|---|
| 国有財産売却情報（財務省連携） | https://kokuyuzaisan.akiya-athome.jp/ | 月1 | 東京・23区の土地、狭小・変形地 | 一般競争入札の流れ、予定価格 | アットホーム運営の財務局連携サイト |
| 公的不動産(PRE)情報 | https://pre.akiya-athome.jp/ | 月1 | 23区の売却・貸付 | 売却だけでなく貸付・定借も見る | 自治体の遊休地 |
| 関東財務局 国有地（公示中） | https://lfb.mof.go.jp/kantou/kanzai/mokuji_00001.htm | 月1〜2 | 23区lot、入札スケジュール | 期間入札・入札保証金 | R8第1回 公告5/27–入札6/17–6/25 |
| 関東財務局 同時売却先募集(東京23区) | https://lfb.mof.go.jp/kantou/kokuyuuti/doujibaikyakusaki/list/tokyo.htm | 月1 | 23区の細切れ・隣接地 | 隣地一体での取得 | 23区特化枠 |
| 東京都財務局 公有地入札 | https://www.zaimu.metro.tokyo.lg.jp/kouyu/nyuusatsu | 月1 | 都有地売払い・公募・先着 | 入札・即日開札 | 出物少・公示時のみ |
| 東京都財務局 売払い | https://www.zaimu.metro.tokyo.lg.jp/kouyu/nyuusatsu/baikyaku/ | 月1 | 売払い物件 | 一般競争入札 | |
| 各区 管財・財政課（区有地） | 各区サイトを個別確認 ⚠️ | 月1 | 普通財産の売払い | 区ごとに不定期 | 集約ポータルなし。関心区を登録 |

---

## B. 公売（税滞納差押え・情報限定・現金前提）

| サイト名 | URL | 見る頻度 | 見るべき条件 | 学ぶべきポイント | 備考 |
|---|---|---:|---|---|---|
| 東京都主税局 公売（都税） | https://www.tax.metro.tokyo.lg.jp/kobai/ | 隔週 | 23区の土地・狭小地・古家付き | 見積価額と実勢の差 | 不動産は年3回（郵送期間入札） |
| 　└ 郵送公売 | https://www.tax.metro.tokyo.lg.jp/kobai/mail | 隔週 | 不動産の期間入札 | 公売保証金・短期納付 | R8: 7月・10月・1〜2月 |
| 　└ ネット公売 | https://www.tax.metro.tokyo.lg.jp/kobai/internet | 月1 | 動産等 | KSI連携 | |
| 国税庁 公売情報 | https://www.koubai.nta.go.jp/ | 隔週 | 東京国税局管内の不動産 | 公売と競売の違い | |
| 　└ 不動産検索 | https://www.koubai.nta.go.jp/auctionx/public/hp0241.php | 隔週 | 23区 | 期間入札・ネット公売 | |
| 　└ 公売日程 | https://www.koubai.nta.go.jp/auctionx/public/hp_sh_001.php | 月1 | スケジュール | | |
| 東京国税局 公売 | https://www.nta.go.jp/about/organization/tokyo/kobai/index.htm | 月1 | 管内物件 | | |
| KSI官公庁オークション | https://kankocho.jp/ | 隔週 | インターネット公売・公有財産売却 | 会員登録・保証金・せり/入札 | 都・自治体が利用 |

---

## C. 裁判所競売（学習価値最大・三点セット）

| サイト名 | URL | 見る頻度 | 見るべき条件 | 学ぶべきポイント | 備考 |
|---|---|---:|---|---|---|
| BIT 不動産競売物件情報 | https://www.bit.courts.go.jp/ | 隔週 | 東京地裁管轄、23区の土地・戸建て・借地権 | 三点セットの読み方、占有・残置・滞納 | 期間入札 |
| 　└ 用語(買受可能価額) | https://www.bit.courts.go.jp/words/ka-ko/ka01.html | 随時 | — | 買受可能価額＝売却基準価額×0.8 | |
| 　└ 用語(三点セット) | https://www.bit.courts.go.jp/words/sa-so/sa05.html | 随時 | — | 物件明細書・現況調査報告書・評価書 | 保証金＝売却基準価額の20% |

---

## D. 民間流通（最も現実的・情報が見やすい）

| サイト名 | URL | 見る頻度 | 見るべき条件 | 学ぶべきポイント | 備考 |
|---|---|---:|---|---|---|
| SUUMO（23区 再建築不可） | https://suumo.jp/b/kodate/kw/東京２３区　再建築不可　中古　戸建て/ | 隔週 | 23区・再建築不可・狭小 | 安い理由の典型 | kwキーワード検索が有効 |
| SUUMO（23区 古家付き土地） | https://suumo.jp/b/kodate/kw/東京２３区　古家付　土地/ | 隔週 | 古家付き土地 | 解体費前提の価格 | |
| SUUMO（旧法借地権 戸建 23区） | https://suumo.jp/b/kodate/kw/旧法　借地権　中古　戸建　２３区/ | 隔週 | 借地権 | 地代・承諾料の構造 | 23区の借地は薄いが存在 |
| HOME'S | https://www.homes.co.jp/ | 隔週 | こだわり条件で借地権・再建築不可 | 条件フィルタの使い方 | ⚠️個別フィルタ操作要 |
| at home（古家あり） | https://www.athome.co.jp/tochi/theme/furuyaari/tokyo/list/ | 隔週 | 古家付き土地 | 23区は少なく多摩が安い傾向 | |
| 楽待（投資） | https://www.rakumachi.jp/ | 隔週 | 戸建賃貸・再建築不可（除外/限定可） | 利回りの読み方 | 独自・非公開物件多 |
| 健美家（再建築不可） | https://www.kenbiya.com/pp0/saikenfuka=y/ | 隔週 | 再建築不可の収益物件 | 高利回り＝欠陥の対価 | 約900件超（時点） |

---

## E. 専門業者・教材（off-market・相場感・知識）

| サイト名 | URL | 見る頻度 | 見るべき条件 | 学ぶべきポイント | 備考 |
|---|---|---:|---|---|---|
| インクコーポレーション（再建築不可 販売） | https://saikenfuka.jp/archives/category/sale/sale_tokyo | 月1 | 23区の再建築不可 実売 | 1.5M〜6.5Mの激安帯 | |
| 第一土地建物（再建築不可 買取） | https://saikenchikufuka-kaitori.com/ | 月1 | 世田谷中心 | 買取相場＝出口価格 | |
| URUHOME/ドリームプランニング | https://uruhome.net/ | 月1 | 再建築不可・底地・借地・共有持分 | 解説が厚い | 教材として優秀 |
| AlbaLink 訳あり物件買取ナビ | https://albalink.co.jp/realestate/ | 月1 | 空き家・再建築不可・共有持分・事故物件 | 買取相場・リスク解説 | |
| サンセイランディック（底地・借地） | https://www.sansei-l.co.jp/service/ | 月1 | 底地・借地権 | 底地ビジネスの実際 | 上場・唯一の専業 |
| クランピーリアルエステート（共有持分） | https://c-realestate.jp/co-ownership/ | 月1 | 共有持分 | 持分の出口（分割・売戻し） | 弁護士連携 |
| 任売市場（任意売却） | http://ninbai-ichiba.com/ | 月1 | 首都圏の任意売却 | 任売≠競売の違い | ⚠️HTTP・在庫流動的 |
| 全国任意売却支援協会 | https://ninbai-japan.or.jp/baikyaku-realestate | 月1 | 任意売却 | 競売前の交渉売却 | |

---

## 巡回のコツ

- **隔週**：BIT・公売・SUUMO/健美家（新着が動く）
- **月1**：国有地・公有地・専門業者（出物が少ない）
- 気になった物件は必ず **property_checklist.md** に転記してから検討する
- 同じ条件で見続けると「相場の体」ができる。最初は買わずに観測に徹する
