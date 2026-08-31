"""
単語ペア抽出サービス

Gemini Vision を使って、英単語帳の撮影画像から
英単語・和訳のペアを構造化抽出する。

抽出上限（MAX_EXTRACT_WORDS）と、1曲に入れる語数の上限
（MAX_WORDS_PER_SONG）は別物として扱う。抽出はページ全体を読み取り、
そこから何語を歌にするかはユーザーが選択する。
"""
import os
import json
import re
import asyncio
from typing import List, Dict

from config import GEMINI_MODEL, MAX_EXTRACT_WORDS, MAX_MEANINGS_PER_WORD

EXTRACT_PROMPT = """あなたは英単語帳の画像を解析する専門家です。
この画像から、見出しになっている英単語とその和訳のペアを「すべて」抽出してください。

【抽出するもの】
- 見出し語（太字・大きな文字で書かれた英単語）
- その日本語訳

【除外するもの】
- 発音記号（[dɪváut] のような角括弧内の記号列）
- 英語の同義語・言い換え（[= religious, pious] のような表記）
- 派生語・関連語・コロケーション（intimacy、intimate friend など）
- 例文とその和訳（ページ右側などにある文章）
- 通し番号、ページ番号、章タイトル、品詞ラベル

【和訳のルール】
- 和訳が複数ある場合は「、」で区切って最大3つまで含める
  例: "敬虔な、熱心な" / "最高の、最適の"
- 記号（形、動、▶、=、丸囲み文字など）は和訳に含めない

【重要】
- 見出し語は1つも飛ばさず、ページに載っているものをすべて出力する
- 画像が不鮮明で読み取れない語のみスキップする
- 必ず以下のJSON形式のみを出力する（説明文やコードフェンスは不要）

{
  "word_pairs": [
    { "word": "devout", "meaning": "敬虔な、熱心な" },
    { "word": "optimum", "meaning": "最高の、最適の" }
  ]
}
"""

# 英文モード用: 英文とその日本語訳のペアを抽出する
EXTRACT_PROMPT_SENTENCE = """あなたは英語の文章を解析する専門家です。
この画像から、英文とその日本語訳のペアをすべて抽出してください。

ルール:
- 英文（English sentence）と日本語訳（Japanese translation）のペアを抽出する
- 画像に日本語訳が無い場合は、英文の意味を自然な日本語に訳して補う
- 発音記号、通し番号、ページ番号などは除外する
- 長すぎる文は、意味のまとまりごとに区切ってよい
- 画像が不鮮明で読み取れない文はスキップする
- 必ず以下のJSON形式のみを出力する（説明文やコードフェンスは不要）
- "word" に英文、"meaning" に日本語訳を入れる

{
  "word_pairs": [
    { "word": "I have a dream.", "meaning": "私には夢がある。" },
    { "word": "The sky is blue.", "meaning": "空は青い。" }
  ]
}
"""


def _get_image_mime_type(image_path: str) -> str:
    ext = os.path.splitext(image_path)[1].lower()
    mime_types = {
        ".webp": "image/webp",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".heic": "image/heic",
    }
    return mime_types.get(ext, "image/jpeg")


def _normalize_meaning(raw, mode: str) -> str:
    """
    和訳を「、」区切りの文字列に正規化する。

    モデルが配列で返す場合（["敬虔な", "熱心な"]）と、
    文字列で返す場合（"敬虔な、熱心な"）の両方を受け付ける。
    英文モードは訳文をそのまま使うので分割しない。
    """
    if isinstance(raw, list):
        items = [str(x).strip() for x in raw if str(x).strip()]
    else:
        text = str(raw or "").strip()
        if not text:
            return ""
        if mode == "sentence":
            return text
        # 「、」「,」「/」「;」を区切りとみなす
        items = [s.strip() for s in re.split(r"[、,／/;；]", text) if s.strip()]

    if not items:
        return ""
    return "、".join(items[:MAX_MEANINGS_PER_WORD])


def _parse_word_pairs(response_text: str, mode: str = "word") -> List[Dict[str, str]]:
    """AIレスポンスからword_pairsを取り出す。コードフェンス等を許容する。"""
    text = response_text.strip()

    fence_match = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        text = text[brace_start:brace_end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    pairs = data.get("word_pairs", [])
    result = []
    seen = set()
    for p in pairs:
        if not isinstance(p, dict):
            continue
        word = str(p.get("word") or "").strip()
        meaning = _normalize_meaning(p.get("meaning"), mode)
        if not word or not meaning:
            continue
        key = word.lower()
        if key in seen:          # 同じ見出し語の重複を除く
            continue
        seen.add(key)
        result.append({"word": word, "meaning": meaning})
    return result


async def extract_word_pairs(
    image_path: str, api_key: str, mode: str = "word"
) -> List[Dict[str, str]]:
    """
    画像から英単語・和訳（または英文・和訳）のペアを抽出する。

    Returns:
        [{"word": "devout", "meaning": "敬虔な、熱心な"}, ...]
        最大 MAX_EXTRACT_WORDS 件。
        1曲に入れる語数の絞り込みは UI 側で行う。
    """
    from google import genai
    from google.genai import types

    if not api_key:
        raise Exception("Gemini API キーが指定されていません")

    client = genai.Client(api_key=api_key)

    prompt = EXTRACT_PROMPT_SENTENCE if mode == "sentence" else EXTRACT_PROMPT

    mime_type = _get_image_mime_type(image_path)
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    parts = [
        types.Part.from_text(text=prompt),
        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
    ]

    max_retries = 5
    retry_delay = 4.0

    for attempt in range(max_retries):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_MODEL,
                contents=parts,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    # 単語帳1ページ分（数十語）を出し切れる余裕を持たせる
                    max_output_tokens=8000,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            text = (response.text or "").strip()
            pairs = _parse_word_pairs(text, mode)
            if not pairs:
                if mode == "sentence":
                    raise Exception("画像から英文を抽出できませんでした。鮮明な英文の画像をお試しください。")
                raise Exception("画像から英単語を抽出できませんでした。鮮明な英単語帳の画像をお試しください。")
            print(f"[VocabService] Extracted {len(pairs)} pairs (mode={mode})")
            return pairs[:MAX_EXTRACT_WORDS]

        except Exception as e:
            err_str = str(e)
            is_retryable = (
                "429" in err_str
                or "RESOURCE_EXHAUSTED" in err_str
                or "503" in err_str
                or "UNAVAILABLE" in err_str
                or "high demand" in err_str
                or "try again later" in err_str
            )
            if is_retryable and attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                retry_delay *= 1.5
                continue
            if "抽出できませんでした" in err_str:
                raise
            raise Exception(f"単語抽出エラー: {err_str}")
