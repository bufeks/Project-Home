#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕組み全体の整合性を自動検査する自己点検（回帰の早期検出）。
ネットワーク不要（data/listings.json のキャッシュを使用）。失敗時は exit 1。
CI（.github/workflows/selfcheck.yml）とローカルの両方で実行できる。

検査項目:
  1. 全スクリプトの構文(AST)
  2. watchlist.json / market_real.json の妥当性・building_flags構造
  3. render() のスモーク（=TEMPLATE.format の全プレースホルダ整合・stray brace検出）
  4. 生成HTMLの <script> を node --check（nodeがあれば）
  5. enrich の冪等性（2回適用でスコア/主要フィールドが不変＝状態残りバグ検出）
  6. JS の el()/getElementById 参照 ⊆ テンプレ定義id
  7. 削除済み機能（renderShare/makeShareUrl/digest 等）の残骸なし
"""
import sys
import re
import ast
import json
import copy
import shutil
import subprocess
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
fails = []


def check(name, ok, detail=""):
    mark = "OK " if ok else "NG "
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name + (f": {detail}" if detail else ""))


def main():
    print("=== selfcheck: 仕組み整合性の自己点検 ===")

    # 1. AST
    for f in ("fetch_listings.py", "fetch_market.py", "fast_watch.py", "screen_hybrid.py", "loan_plan.py", "selfcheck.py"):
        try:
            ast.parse((HERE / f).read_text(encoding="utf-8"))
            check(f"AST {f}", True)
        except Exception as e:
            check(f"AST {f}", False, str(e))

    # 2. JSON妥当性
    try:
        wl = json.loads((ROOT / "watchlist.json").read_text(encoding="utf-8"))
        check("watchlist.json parse", True)
        bf_ok = all(isinstance(b.get("name"), str) for b in wl.get("building_flags", []))
        check("building_flags 構造", bf_ok, "name必須")
    except Exception as e:
        check("watchlist.json parse", False, str(e))
    mr = ROOT / "data" / "market_real.json"
    if mr.exists():
        try:
            json.loads(mr.read_text(encoding="utf-8"))
            check("market_real.json parse", True)
        except Exception as e:
            check("market_real.json parse", False, str(e))

    # モジュール読込
    spec = importlib.util.spec_from_file_location("fl", HERE / "fetch_listings.py")
    fl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fl)
    rows = json.loads((ROOT / "data" / "listings.json").read_text(encoding="utf-8"))["rows"]

    # 3. render スモーク（format整合・stray brace）
    html = None
    try:
        html = fl.render(rows, [])
        check("render() スモーク（format整合）", len(html) > 10000, f"len={len(html) if html else 0}")
    except Exception as e:
        check("render() スモーク（format整合）", False, f"{type(e).__name__}: {e}")

    # 4. JS node --check
    if html and shutil.which("node"):
        m = re.search(r"<script>(.*?)</script>", html, re.S)
        if m:
            (pathlib.Path("/tmp/_selfcheck.js")).write_text(m.group(1), encoding="utf-8")
            r = subprocess.run(["node", "--check", "/tmp/_selfcheck.js"],
                               capture_output=True, text=True)
            check("JS 構文(node --check)", r.returncode == 0, r.stderr.strip()[:200])
    else:
        print("  [--] JS node --check スキップ（node無し）")

    # 5. enrich 冪等性
    drift = []
    for r in rows[:300]:
        a = copy.deepcopy(r); fl.enrich(a)
        b = copy.deepcopy(a); fl.enrich(b)
        for k in ("score", "ratio", "reason", "premium", "tags"):
            if a.get(k) != b.get(k):
                drift.append(f"{r.get('id')}::{k}")
                break
    check("enrich 冪等性（状態残りなし）", not drift, f"{len(drift)}件ドリフト 例:{drift[:3]}")

    # 6. 要素ID参照 ⊆ 定義
    src = (HERE / "fetch_listings.py").read_text(encoding="utf-8")
    t = re.search(r'TEMPLATE\s*=\s*r?"""(.*?)"""', src, re.S).group(1)
    refs = set(re.findall(r"el\('([\w]+)'\)", t)) | set(re.findall(r"getElementById\('([\w]+)'\)", t))
    defined = set(re.findall(r'id="([\w]+)"', t))
    miss = sorted(refs - defined)
    check("要素ID参照の整合", not miss, f"未定義:{miss}")

    # 7. 削除済み機能の残骸
    dead = [w for w in ("renderShare", "makeShareUrl", "fbStop", "{digest}", "気になるマンション速報") if w in src]
    check("削除済み機能の残骸なし", not dead, f"残存:{dead}")

    print("=== 結果:", "全て合格 ✅" if not fails else f"{len(fails)}件の不整合 ❌ → {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
