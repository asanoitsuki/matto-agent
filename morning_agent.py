#!/usr/bin/env python3
"""
matto morning_agent.py
公式サイトから実在するお祭り・花火情報を収集してSupabaseへ登録するエージェント。

使い方:
  python morning_agent.py --clean  # 既存のエージェント登録データを全削除
  python morning_agent.py --init   # 公式サイトから全件収集してインサート
  python morning_agent.py          # 毎朝の差分更新

必要パッケージ:
  pip install anthropic requests beautifulsoup4
"""

import os
import sys
import json
import uuid
import time
import argparse
import requests
from datetime import datetime
from typing import Any
from bs4 import BeautifulSoup

SUPABASE_URL   = "https://ujdxryxtydbonkqsdpxa.supabase.co"
SUPABASE_KEY   = "sb_publishable_Dy1DP2t9aq7-ebB61hsVJQ_hcUZ65rZ"
CLAUDE_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL          = "claude-haiku-4-5-20251001"

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# 公式スクレイピング対象サイト
SCRAPE_TARGETS = [
    {
        "name": "じゃらんnet イベント・お祭り",
        "url":  "https://www.jalan.net/event/evt_genre_list/?genre_cd=0200&sort=date",
    },
    {
        "name": "じゃらんnet 花火大会",
        "url":  "https://www.jalan.net/event/evt_genre_list/?genre_cd=0203&sort=date",
    },
    {
        "name": "ウォーカープラス 花火大会",
        "url":  "https://hanabi.walkerplus.com/list/",
    },
    {
        "name": "ウォーカープラス イベント",
        "url":  "https://www.walkerplus.com/event_list/",
    },
    {
        "name": "まつりずむ",
        "url":  "https://matsurism.com/festivals/",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}


# ─────────────────────────────────────────
# Supabase 操作
# ─────────────────────────────────────────

def supabase_get(path: str, params: dict = {}) -> list:
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers=SUPABASE_HEADERS,
        params=params,
        timeout=15,
    )
    return resp.json() if resp.status_code == 200 else []


def supabase_delete(ids: list[str]) -> int:
    """指定IDのレコードを削除。削除件数を返す"""
    deleted = 0
    chunk_size = 50
    for i in range(0, len(ids), chunk_size):
        chunk = ids[i:i + chunk_size]
        id_list = ",".join(chunk)
        resp = requests.delete(
            f"{SUPABASE_URL}/rest/v1/festivals",
            headers={**SUPABASE_HEADERS, "Prefer": "return=minimal"},
            params={"id": f"in.({id_list})"},
            timeout=15,
        )
        if resp.status_code in (200, 204):
            deleted += len(chunk)
    return deleted


def supabase_insert(events: list[dict]) -> int:
    """イベントを一括インサート（重複は無視）。成功件数を返す"""
    success = 0
    chunk_size = 50
    for i in range(0, len(events), chunk_size):
        chunk = events[i:i + chunk_size]
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/festivals",
            headers={**SUPABASE_HEADERS, "Prefer": "resolution=ignore-duplicates,return=minimal"},
            json=chunk,
            timeout=30,
        )
        if resp.status_code in (200, 201):
            success += len(chunk)
            print(f"  登録: {success}件")
        else:
            print(f"  エラー [{resp.status_code}]: {resp.text[:200]}")
        time.sleep(0.3)
    return success


def fetch_existing_names() -> set[str]:
    """既存のイベント名一覧を取得（重複チェック用）"""
    rows = supabase_get("festivals", {"select": "name", "limit": "10000"})
    return {r["name"] for r in rows if "name" in r}


# ─────────────────────────────────────────
# Web スクレイピング
# ─────────────────────────────────────────

def scrape_page(url: str) -> str:
    """ページのテキストを取得"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.content, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 10]
        return "\n".join(lines[:500])
    except Exception as e:
        return f"取得エラー: {e}"


# ─────────────────────────────────────────
# Claude による構造化
# ─────────────────────────────────────────

def parse_with_claude(raw_text: str, source_name: str) -> list[dict]:
    """
    Webページの生テキストから祭り情報をClaudeで構造化。
    AIは「生成」ではなく「抽出・整形」のみ行う。
    """
    if not CLAUDE_API_KEY:
        print("  ANTHROPIC_API_KEY が未設定のためスキップ")
        return []

    import anthropic
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    today = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""
以下は「{source_name}」のWebページから取得したテキストです。
このテキストに記載されている実在する祭り・花火大会・イベントの情報を抽出して、
JSON形式に整理してください。

【重要ルール】
- テキストに実際に書かれている情報のみ使用すること
- 情報が不足している場合は該当フィールドを省略するか null にすること
- 絶対に情報を推測・創作しないこと
- 開催日が不明なものは含めないこと
- 今日（{today}）以降のイベントのみ抽出すること

テキスト:
{raw_text[:4000]}

出力形式（JSONのみ、コードブロック不要）:
[
  {{
    "name": "イベント名（テキストに記載の正式名称）",
    "category": "花火 or 祭り or 市 or 縁日 or フリーマーケット",
    "date": "YYYY-MM-DDTHH:MM:00+09:00",
    "description": "テキストに記載の説明（100文字以内）",
    "location": "開催地（都道府県市区町村に加え、会場名・番地など判明している範囲で最大限詳しく）",
    "has_stalls": true or false
  }}
]

イベントが見つからない場合は [] を返してください。
"""

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
            system="Webページから情報を抽出するアシスタントです。テキストに存在する情報のみを使い、絶対に創作・推測しません。",
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)
    except Exception as e:
        print(f"  Claude解析エラー: {e}")
        return []


# ─────────────────────────────────────────
# ジオコーディング（Nominatim）
# ─────────────────────────────────────────

def geocode(location: str):
    """住所 → 緯度経度（OpenStreetMap Nominatim）"""
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": location, "format": "json", "limit": 1, "countrycodes": "jp"},
            headers={"User-Agent": "matto-festival-agent/2.0"},
            timeout=10,
        )
        data = resp.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None


# ─────────────────────────────────────────
# モード別処理
# ─────────────────────────────────────────

def run_clean_mode() -> None:
    """--clean: vote_count=0 のエージェント登録データを全削除"""
    print("=== クリーンモード: 未検証データを削除 ===")
    rows = supabase_get("festivals", {"select": "id,name", "vote_count": "eq.0", "limit": "10000"})
    if not rows:
        print("削除対象なし")
        return
    ids = [r["id"] for r in rows]
    print(f"{len(ids)}件を削除中...")
    deleted = supabase_delete(ids)
    print(f"完了: {deleted}件を削除しました")


def run_scrape(targets: list[dict], existing_names: set[str]) -> list[dict]:
    """サイトを巡回してイベントを収集"""
    all_events: list[dict] = []

    for target in targets:
        print(f"\n巡回: {target['name']}")
        raw = scrape_page(target["url"])
        if raw.startswith("取得エラー"):
            print(f"  スキップ: {raw}")
            continue

        events = parse_with_claude(raw, target["name"])
        print(f"  抽出: {len(events)}件")

        for ev in events:
            name = ev.get("name", "").strip()
            if not name or name in existing_names:
                continue

            location = ev.get("location", "")
            coords   = geocode(location) if location else None
            time.sleep(1.0)  # Nominatim利用ポリシー（1リクエスト/秒）を厳守
            if not coords:
                print(f"  座標取得失敗: {name}（{location}）→ スキップ")
                continue

            lat, lon = coords
            all_events.append({
                "id":          str(uuid.uuid4()),
                "name":        name,
                "category":    ev.get("category", "祭り"),
                "date":        ev.get("date", ""),
                "description": ev.get("description", "")[:100],
                "latitude":    round(lat, 6),
                "longitude":   round(lon, 6),
                "has_stalls":  bool(ev.get("has_stalls", False)),
                "status":      "active",
                "vote_count":  0,
            })
            existing_names.add(name)

        time.sleep(2.0)   # サイトへの負荷軽減

    return all_events


def run_init_mode() -> None:
    """--init: 全サイトを巡回して一括インサート"""
    print("=== 初期データ収集モード ===")
    print(f"対象: {len(SCRAPE_TARGETS)}サイト\n")
    existing = fetch_existing_names()
    events   = run_scrape(SCRAPE_TARGETS, existing)
    print(f"\n合計{len(events)}件をSupabaseへ登録中...")
    total = supabase_insert(events)
    print(f"\n完了: {total}件を登録しました")


def run_daily_mode() -> None:
    """引数なし: 毎日の差分更新"""
    print("=== 日次更新モード ===")
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    existing = fetch_existing_names()
    events   = run_scrape(SCRAPE_TARGETS, existing)
    print(f"\n{len(events)}件をSupabaseへ登録中...")
    total = supabase_insert(events)
    print(f"\n完了: {total}件を登録しました")


def main() -> None:
    parser = argparse.ArgumentParser(description="matto agent: 公式サイトから実在祭り情報を収集")
    parser.add_argument("--clean", action="store_true", help="未検証データ（vote_count=0）を全削除")
    parser.add_argument("--init",  action="store_true", help="全サイト巡回して一括インサート")
    args = parser.parse_args()

    if args.clean:
        run_clean_mode()
    elif args.init:
        run_init_mode()
    else:
        run_daily_mode()


if __name__ == "__main__":
    main()
