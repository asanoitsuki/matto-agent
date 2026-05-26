#!/usr/bin/env python3
"""
matto morning_agent.py
全国のお祭り・花火・イベント情報を自動収集してSupabaseへ投入するエージェント。

使い方:
  python morning_agent.py --init   # 全国イベントを一括インサート（初回データ投入）
  python morning_agent.py          # Claudeで新着イベントを生成してupsert（毎朝定期実行）

必要パッケージ:
  pip install anthropic requests beautifulsoup4
"""

import sys
import json
import uuid
import time
import argparse
import requests
from datetime import datetime, timedelta
from typing import Any

SUPABASE_URL  = "https://ujdxryxtydbonkqsdpxa.supabase.co"
SUPABASE_KEY  = "sb_publishable_Dy1DP2t9aq7-ebB61hsVJQ_hcUZ65rZ"
import os
CLAUDE_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-haiku-4-5-20251001"

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
}

# 全国主要都市の座標
JAPAN_CITIES = [
    {"name": "札幌市",   "pref": "北海道",   "lat": 43.0618, "lon": 141.3545, "radius": 0.20},
    {"name": "函館市",   "pref": "北海道",   "lat": 41.7688, "lon": 140.7290, "radius": 0.10},
    {"name": "仙台市",   "pref": "宮城県",   "lat": 38.2688, "lon": 140.8721, "radius": 0.15},
    {"name": "盛岡市",   "pref": "岩手県",   "lat": 39.7036, "lon": 141.1527, "radius": 0.10},
    {"name": "秋田市",   "pref": "秋田県",   "lat": 39.7186, "lon": 140.1024, "radius": 0.10},
    {"name": "山形市",   "pref": "山形県",   "lat": 38.2404, "lon": 140.3633, "radius": 0.10},
    {"name": "福島市",   "pref": "福島県",   "lat": 37.7608, "lon": 140.4748, "radius": 0.10},
    {"name": "水戸市",   "pref": "茨城県",   "lat": 36.3418, "lon": 140.4468, "radius": 0.10},
    {"name": "宇都宮市", "pref": "栃木県",   "lat": 36.5551, "lon": 139.8828, "radius": 0.10},
    {"name": "前橋市",   "pref": "群馬県",   "lat": 36.3894, "lon": 139.0634, "radius": 0.10},
    {"name": "さいたま市","pref": "埼玉県",   "lat": 35.8617, "lon": 139.6455, "radius": 0.15},
    {"name": "千葉市",   "pref": "千葉県",   "lat": 35.6074, "lon": 140.1065, "radius": 0.15},
    {"name": "東京都",   "pref": "東京都",   "lat": 35.6895, "lon": 139.6917, "radius": 0.30},
    {"name": "横浜市",   "pref": "神奈川県", "lat": 35.4437, "lon": 139.6380, "radius": 0.20},
    {"name": "新潟市",   "pref": "新潟県",   "lat": 37.9161, "lon": 139.0364, "radius": 0.15},
    {"name": "富山市",   "pref": "富山県",   "lat": 36.6953, "lon": 137.2113, "radius": 0.10},
    {"name": "金沢市",   "pref": "石川県",   "lat": 36.5944, "lon": 136.6256, "radius": 0.10},
    {"name": "福井市",   "pref": "福井県",   "lat": 36.0652, "lon": 136.2216, "radius": 0.10},
    {"name": "甲府市",   "pref": "山梨県",   "lat": 35.6639, "lon": 138.5685, "radius": 0.10},
    {"name": "長野市",   "pref": "長野県",   "lat": 36.6486, "lon": 138.1946, "radius": 0.10},
    {"name": "岐阜市",   "pref": "岐阜県",   "lat": 35.4232, "lon": 136.7608, "radius": 0.10},
    {"name": "静岡市",   "pref": "静岡県",   "lat": 34.9769, "lon": 138.3831, "radius": 0.15},
    {"name": "名古屋市", "pref": "愛知県",   "lat": 35.1815, "lon": 136.9066, "radius": 0.20},
    {"name": "津市",     "pref": "三重県",   "lat": 34.7303, "lon": 136.5086, "radius": 0.10},
    {"name": "大津市",   "pref": "滋賀県",   "lat": 35.0045, "lon": 135.8686, "radius": 0.10},
    {"name": "京都市",   "pref": "京都府",   "lat": 35.0116, "lon": 135.7681, "radius": 0.20},
    {"name": "大阪市",   "pref": "大阪府",   "lat": 34.6937, "lon": 135.5023, "radius": 0.25},
    {"name": "神戸市",   "pref": "兵庫県",   "lat": 34.6913, "lon": 135.1830, "radius": 0.15},
    {"name": "奈良市",   "pref": "奈良県",   "lat": 34.6851, "lon": 135.8048, "radius": 0.10},
    {"name": "和歌山市", "pref": "和歌山県", "lat": 34.2260, "lon": 135.1675, "radius": 0.10},
    {"name": "鳥取市",   "pref": "鳥取県",   "lat": 35.5011, "lon": 134.2351, "radius": 0.10},
    {"name": "松江市",   "pref": "島根県",   "lat": 35.4723, "lon": 133.0505, "radius": 0.10},
    {"name": "岡山市",   "pref": "岡山県",   "lat": 34.6618, "lon": 133.9344, "radius": 0.15},
    {"name": "広島市",   "pref": "広島県",   "lat": 34.3853, "lon": 132.4553, "radius": 0.20},
    {"name": "山口市",   "pref": "山口県",   "lat": 34.1859, "lon": 131.4706, "radius": 0.10},
    {"name": "徳島市",   "pref": "徳島県",   "lat": 34.0658, "lon": 134.5593, "radius": 0.10},
    {"name": "高松市",   "pref": "香川県",   "lat": 34.3401, "lon": 134.0434, "radius": 0.10},
    {"name": "松山市",   "pref": "愛媛県",   "lat": 33.8416, "lon": 132.7657, "radius": 0.10},
    {"name": "高知市",   "pref": "高知県",   "lat": 33.5597, "lon": 133.5311, "radius": 0.10},
    {"name": "福岡市",   "pref": "福岡県",   "lat": 33.5902, "lon": 130.4017, "radius": 0.20},
    {"name": "佐賀市",   "pref": "佐賀県",   "lat": 33.2494, "lon": 130.2988, "radius": 0.10},
    {"name": "長崎市",   "pref": "長崎県",   "lat": 32.7503, "lon": 129.8779, "radius": 0.10},
    {"name": "熊本市",   "pref": "熊本県",   "lat": 32.8031, "lon": 130.7079, "radius": 0.15},
    {"name": "大分市",   "pref": "大分県",   "lat": 33.2382, "lon": 131.6126, "radius": 0.10},
    {"name": "宮崎市",   "pref": "宮崎県",   "lat": 31.9077, "lon": 131.4202, "radius": 0.10},
    {"name": "鹿児島市", "pref": "鹿児島県", "lat": 31.5602, "lon": 130.5581, "radius": 0.15},
    {"name": "那覇市",   "pref": "沖縄県",   "lat": 26.2124, "lon": 127.6809, "radius": 0.10},
]

# 有名な全国イベントシード
JAPAN_FESTIVALS_SEED = [
    ("隅田川花火大会", "花火", "東京の夏の風物詩。約2万発が夅大な水上花火として打ち上げられる日本最大級の花火大会。", False),
    ("祇園祭", "祭り", "京都八坂神社の祭礼。7月に行われる日本三大祭の一つ。山鉾巡行が見どころ。", True),
    ("阿波おどり", "祭り", "徳島の伝統的な盆踊り。日本三大盆踊りの一つで約400年の歴史を誇る。", True),
    ("青森ねぶた祭", "祭り", "青森の夏祭り。大型の灯篭ねぶたが街を練り歩く東北を代表するお祭り。", True),
    ("さっぽろ雪まつり", "祭り", "札幌の冬の祭典。大通公園に巨大な雪像が立ち並ぶ国際的なイベント。", True),
    ("博多どんたく", "祭り", "福岡の春祭り。参加者数日本一を誇る市民祭。仮装行列が博多の街を彩る。", True),
    ("長岡花火", "花火", "新潟長岡の花火大会。三尺玉や復興祈願花火フェニックスで知られる日本三大花火の一つ。", False),
    ("大曲の花火", "花火", "秋田大曲で開催される全国花火競技大会。職人技の競演が見られる花火の聖地。", False),
    ("天神祭", "祭り", "大阪天満宮の夏祭り。日本三大祭の一つ。船渡御と奉納花火が大阪の夏を飾る。", True),
    ("よさこい祭り", "祭り", "高知の夏祭り。鳴子を手に持って踊るよさこい踊りが全国に広まるきっかけとなった。", True),
    ("仙台七夕まつり", "祭り", "仙台の夏の風物詩。色とりどりの七夕飾りが商店街を彩る東北最大の夏祭り。", True),
    ("秋田竿燈まつり", "祭り", "秋田の夏祭り。46個の提灯を付けた竿燈を体で操る妙技が圧巻。東北三大祭りの一つ。", False),
    ("那智の火祭", "祭り", "和歌山の熊野那智大社の祭礼。12本の大松明が石段を降りる勇壮な神事。", False),
    ("浅草三社祭", "祭り", "東京浅草神社の例大祭。神輿の担ぎ手が100万人を超える東京最大の祭り。", True),
    ("鎌倉花火大会", "花火", "神奈川鎌倉の由比ヶ浜で開催。2000発の花火が相模湾に打ち上げられる夏の風物詩。", False),
]


def call_claude(prompt: str, system: str = "") -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    messages = [{"role": "user", "content": prompt}]
    kwargs: dict[str, Any] = {"model": MODEL, "max_tokens": 4096, "messages": messages}
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    return response.content[0].text


def generate_events_for_city(city: dict, count: int = 10) -> list[dict]:
    """指定都市のイベントをClaudeで生成"""
    import random

    seed_items = JAPAN_FESTIVALS_SEED[:5]
    seed_text  = "\n".join([f"- {s[0]}（{s[1]}）: {s[2]}" for s in seed_items])

    today            = datetime.now()
    six_months_later = today + timedelta(days=180)

    prompt = f"""
{city["pref"]}{city["name"]}周辺で開催されるお祭り・花火・イベントを{count}件、JSONリストとして生成してください。
地域の実際の文化・歴史に根ざしたリアルなイベントを作成してください。

参考例:
{seed_text}

必ず以下のJSON形式のみで出力（コードブロック不要）:
[
  {{
    "name": "イベント名",
    "category": "花火 or 祭り or 市 or 縁日 or フリーマーケット",
    "date": "YYYY-MM-DDTHH:MM:00+09:00",
    "description": "100文字以内の説明",
    "latitude": {city["lat"] + random.uniform(-city["radius"]/2, city["radius"]/2):.4f},
    "longitude": {city["lon"] + random.uniform(-city["radius"]/2, city["radius"]/2):.4f},
    "has_stalls": true or false
  }}
]

dateは{today.strftime("%Y-%m-%d")}から{six_months_later.strftime("%Y-%m-%d")}の間にしてください。
"""
    try:
        response = call_claude(
            prompt,
            system="あなたは日本全国のお祭り・イベント情報の専門家です。必ずJSON形式のみで出力し、説明文は書かないでください。"
        )
        text = response.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        events = json.loads(text)
        return events
    except Exception as e:
        print(f"  Claude生成エラー ({city['name']}): {e}")
        return generate_fallback_events(count, city)


def generate_fallback_events(count: int, city: dict) -> list[dict]:
    """フォールバック: ローカルシードから生成"""
    import random
    events = []
    today = datetime.now()
    for i in range(count):
        seed   = JAPAN_FESTIVALS_SEED[i % len(JAPAN_FESTIVALS_SEED)]
        lat    = city["lat"] + random.uniform(-city["radius"], city["radius"])
        lon    = city["lon"] + random.uniform(-city["radius"], city["radius"])
        offset = random.randint(7, 180)
        dt     = today + timedelta(days=offset)
        events.append({
            "name":        f"{city['name']} {seed[0]}",
            "category":    seed[1],
            "date":        dt.strftime("%Y-%m-%dT18:00:00+09:00"),
            "description": seed[2][:100],
            "latitude":    round(lat, 6),
            "longitude":   round(lon, 6),
            "has_stalls":  seed[3],
        })
    return events


def bulk_insert(events: list[dict]) -> int:
    """Supabaseへ一括インサート。成功件数を返す"""
    chunk_size    = 50
    success_count = 0
    for i in range(0, len(events), chunk_size):
        chunk   = events[i:i + chunk_size]
        payload = []
        for ev in chunk:
            payload.append({
                "id":          str(uuid.uuid4()),
                "name":        ev.get("name", ""),
                "category":    ev.get("category", "祭り"),
                "date":        ev.get("date", "2026-08-01T18:00:00+09:00"),
                "description": ev.get("description", ""),
                "latitude":    float(ev.get("latitude", 35.6895)),
                "longitude":   float(ev.get("longitude", 139.6917)),
                "has_stalls":  bool(ev.get("has_stalls", False)),
                "status":      "active",
                "vote_count":  0,
            })
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/festivals",
            headers={**SUPABASE_HEADERS, "Prefer": "resolution=ignore-duplicates,return=minimal"},
            json=payload,
            timeout=30,
        )
        if resp.status_code in (200, 201):
            success_count += len(chunk)
            print(f"  インサート成功: {success_count}件")
        else:
            print(f"  インサートエラー [{resp.status_code}]: {resp.text[:200]}")
        time.sleep(0.5)
    return success_count


def run_init_mode() -> None:
    """--init: 全国主要都市のイベントを一括インサート"""
    print("=== matto agent: 全国初期データ投入モード ===")
    print(f"対象: {len(JAPAN_CITIES)}都市 × 10件 = 最大{len(JAPAN_CITIES)*10}件\n")

    all_events: list[dict] = []
    for i, city in enumerate(JAPAN_CITIES):
        print(f"[{i+1}/{len(JAPAN_CITIES)}] {city['pref']} {city['name']} のイベントを生成中...")
        events = generate_events_for_city(city, count=10)
        all_events.extend(events)
        print(f"  → {len(events)}件生成")
        time.sleep(1.0)   # APIレート制限対策

    print(f"\n合計{len(all_events)}件をSupabaseへインサート中...")
    total = bulk_insert(all_events)
    print(f"\n完了: {total}件を登録しました。")


def run_daily_update_mode() -> None:
    """引数なし: 毎朝の定期更新（直近イベントを補充）"""
    print("=== matto agent: 日次更新モード ===")
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # ランダムに5都市を選んで最新情報を補充
    import random
    target_cities = random.sample(JAPAN_CITIES, 5)
    all_events: list[dict] = []

    for city in target_cities:
        print(f"更新中: {city['pref']} {city['name']}")
        events = generate_events_for_city(city, count=5)
        all_events.extend(events)
        print(f"  → {len(events)}件生成")
        time.sleep(1.0)

    print(f"\n合計{len(all_events)}件をSupabaseへupsert中...")
    total = bulk_insert(all_events)
    print(f"\n完了: {total}件を処理しました。")


def main() -> None:
    parser = argparse.ArgumentParser(description="matto agent: 全国お祭りデータ収集エージェント")
    parser.add_argument("--init", action="store_true", help="全国主要都市のイベントを一括インサート（初回のみ）")
    args = parser.parse_args()

    if args.init:
        run_init_mode()
    else:
        run_daily_update_mode()


if __name__ == "__main__":
    main()
