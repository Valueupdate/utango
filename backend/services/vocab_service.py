"""
単語ペア抽出サービス

Gemini Vision を使って、英単語帳の撮影画像から
英単語・和訳のペアを構造化抽出する。
docs/design/lyrics-design.md §6 のフォーマットに従う。
"""
import os
import json
import re
import asyncio
from typing import List, Dict

from config import GEMINI_MODEL, MAX_WORDS_PER_SONG

EXTRACT_PROMPT = """あなたは英単語帳の画像を解析する専門家です。
この画像から、英単語とその和訳のペアをすべて抽出してください。

ルール:
- 英単語（English word）と和訳（Japanese meaning）のペアのみを抽出する
- 発音記号、例文、通し番号、ページ番号などは除外する
- 和訳が複数ある場合は最も代表的な1つに絞る
- 画像が不鮮明で読み取れない語はスキップする
- 必ず以下のJSON形式のみを出力する（説明文やコードフェンスは不要）

{
  "word_pairs": [
    { "word": "apple", "meaning": "りんご" },
    { "word": "ocean", "meaning": "海" }
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


def _parse_word_pairs(response_text: str) -> List[Dict[str, str]]:
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
    for p in pairs:
        word = (p.get("word") or "").strip()
        meaning = (p.get("meaning") or "").strip()
        if word and meaning:
            result.append({"word": word, "meaning": meaning})
    return result


async def extract_word_pairs(
    image_path: str, api_key: str, mode: str = "word"
) -> List[Dict[str, str]]:
    """
    画像から英単語・和訳（または英文・和訳）のペアを抽出する。

    Args:
        image_path: 撮影画像のパス
        api_key: ユーザーの Gemini API キー（BYOK）
        mode: "word"（英単語）または "sentence"（英文）

    Returns:
        [{"word": "apple", "meaning": "りんご"}, ...]
        最大 MAX_WORDS_PER_SONG 件（超過分は先頭から採用）
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
                    max_output_tokens=2000,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            text = (response.text or "").strip()
            pairs = _parse_word_pairs(text)
            if not pairs:
                if mode == "sentence":
                    raise Exception("画像から英文を抽出できませんでした。鮮明な英文の画像をお試しください。")
                raise Exception("画像から英単語を抽出できませんでした。鮮明な英単語帳の画像をお試しください。")
            return pairs[:MAX_WORDS_PER_SONG]

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
