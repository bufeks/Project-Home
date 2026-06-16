# 調査メモ・出典（notes/sources.md）

調査日：2026-06-16
対象：東京23区・準都心の安い土地/古家付き土地/借地権/再建築不可/公売/競売ルート

## 方法

- 公的ルート（国有地・公有地・公売・競売）は公式サイトを取得・検証してURLと制度を確認。
- 民間ルートは大手ポータル・投資ポータル・専門業者サイトを確認。
- 候補物件はSUUMOの検索結果ページ（サーバーサイドで描画される一覧カード）から実データを抽出（2026-06-16時点のスナップショット）。
  - 個別物件の恒久URLはID（例 `nc_20551067`）が入れ替わるため取得困難。検索ページURLをアンカーに使う。

## 検証済み主要URL（一次情報）

### 公的
- 財務省連携 国有財産売却情報：https://kokuyuzaisan.akiya-athome.jp/
- 公的不動産(PRE)：https://pre.akiya-athome.jp/
- 関東財務局 国有地（公示中）：https://lfb.mof.go.jp/kantou/kanzai/mokuji_00001.htm
- 関東財務局 同時売却先募集(東京23区)：https://lfb.mof.go.jp/kantou/kokuyuuti/doujibaikyakusaki/list/tokyo.htm
- 東京都財務局 公有地入札：https://www.zaimu.metro.tokyo.lg.jp/kouyu/nyuusatsu
- 東京都主税局 公売：https://www.tax.metro.tokyo.lg.jp/kobai/
- 国税庁 公売情報：https://www.koubai.nta.go.jp/
- 東京国税局 公売：https://www.nta.go.jp/about/organization/tokyo/kobai/index.htm
- KSI官公庁オークション：https://kankocho.jp/
- BIT 不動産競売：https://www.bit.courts.go.jp/
  - 買受可能価額（売却基準価額×0.8）：https://www.bit.courts.go.jp/words/ka-ko/ka01.html
  - 三点セット：https://www.bit.courts.go.jp/words/sa-so/sa05.html

### 民間ポータル
- SUUMO 23区再建築不可：https://suumo.jp/b/kodate/kw/東京２３区　再建築不可　中古　戸建て/
- SUUMO 旧法借地権 戸建 23区：https://suumo.jp/b/kodate/kw/旧法　借地権　中古　戸建　２３区/
- SUUMO 古家付き土地：https://suumo.jp/b/kodate/kw/東京２３区　古家付　土地/
- at home 古家あり 東京：https://www.athome.co.jp/tochi/theme/furuyaari/tokyo/list/
- HOME'S：https://www.homes.co.jp/
- 楽待：https://www.rakumachi.jp/
- 健美家 再建築不可：https://www.kenbiya.com/pp0/saikenfuka=y/

### 専門業者・教材
- インクコーポレーション（再建築不可 実売 1.5M〜6.5M）：https://saikenfuka.jp/archives/category/sale/sale_tokyo
- 第一土地建物（再建築不可買取・世田谷）：https://saikenchikufuka-kaitori.com/
- URUHOME/ドリームプランニング：https://uruhome.net/
- AlbaLink 訳あり買取ナビ：https://albalink.co.jp/realestate/
- サンセイランディック（底地・借地, 上場）：https://www.sansei-l.co.jp/service/
- クランピーリアルエステート（共有持分）：https://c-realestate.jp/co-ownership/
- 任売市場：http://ninbai-ichiba.com/ （⚠️HTTP・在庫流動的）
- 全国任意売却支援協会：https://ninbai-japan.or.jp/baikyaku-realestate

## 制度メモ（確認済み）

- **接道義務（建基法43条1項）**：敷地は幅員4m以上の建築基準法上の道路に2m以上接する必要。未達は再建築不可。
- **43条但し書き（現43条2項2号許可）**：個別審査の救済許可。再建築のたび再申請・承継保証なし。
- **セットバック（42条2項道路）**：道路中心線から2m後退。後退部分は建築不可・容積率/建ぺい率に算入不可。
- **借地権**：旧法（1992年8月以前）＝更新が強く借地人有利／普通借地（新法）＝更新あり／定期借地＝更新なし更地返還。費用：地代・更新料・譲渡承諾料（借地権価格の約1割目安）・建替承諾料。
- **私道持分・掘削承諾**：私道接道はインフラ更新に掘削承諾が必要。なしだとリフォーム・融資が詰まる頻出の隠れ瑕疵。
- **競売の価額**：買受可能価額＝売却基準価額×0.8。保証金＝売却基準価額の20%。代金納付期限 約1か月。
- **公売**：内覧不可が原則・契約不適合責任なし・代金納付期限が短い（数日〜3週間）。住宅ローン前提では不可。

## 主税局 不動産公売 2026年スケジュール例（要再確認）

- ①公告6/12 → 入札7/10–17 → 開札7/22
- ②公告9/25 → 入札10/16–23 → 開札10/27
- ③公告1/8 → 入札1/29–2/5 → 開札2/9

## 不確実・要再確認（⚠️）

- 区有地を集約する公式単一ポータルは確認できず。関心区の管財/財政課を個別に確認。
- 関東財務局ドメインは `lfb.mof.go.jp` が現行（旧 `kantou.mof.go.jp` 系から移行）。
- 各ルートの保証金率はBIT（20%固定）以外は物件ごと設定。
- 任売市場はHTTP・在庫の鮮度未確認。
- candidates.csv の価格・在庫は2026-06-16時点のスナップショットで流動的。
