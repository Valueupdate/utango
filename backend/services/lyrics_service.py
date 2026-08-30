"""
暗記歌詞生成サービス

抽出した英単語・和訳（または英文・和訳）のペアから、
CMジングル風の「絶対忘れないダジャレ暗記歌詞」を生成する。

【発音対策】歌詞は最初からひらがな＋英語で生成し、
Lyria が漢字を誤読する問題を根本的に回避する。
"""
import json
import re
import asyncio
from typing import List, Dict, Tuple

from config import GEMINI_MODEL


# ─── 英単語モード用プロンプト ─────────────────────────
LYRICS_PROMPT_TEMPLATE = """あなたはCMジングルの天才コピーライターです。
以下の英単語と和訳のペアを「絶対に忘れられない30秒のジングル歌詞」にしてください。

単語ペア:
{word_list}

【歌詞のルール】
- 英単語の発音を日本語のダジャレ・語呂合わせ・ツッコミに変換する
- 真面目に訳すな。ふざけろ。笑えるほど記憶に残るフレーズにする
- 1単語につき1〜2行のキャッチフレーズ
- 繰り返し・リズム・韻を重視する
- 30秒で歌い切れる短さにする（全体で8〜12行以内）
- セクション構成: [Intro](1行) → [Verse](本体) → [Outro](1行)

【良い歌詞の例】
- banana（バナナ）→「そんなバナナ！ そんなばかな！ きいろいバナナ しんじられな〜い！」
- apple（りんご）→「あっぷるぷる！ りんごがぷるぷる ふるえてる〜！」
- bus（バス）→「バスが バスっと はしってく〜 のりおくれるな BUS BUS BUS！」
- desk（つくえ）→「デスクで デスゲーム？ ただのつくえだよ！ DESK！」

【悪い歌詞の例（このような真面目な歌詞は絶対に作るな）】
- 「apple は りんご、おぼえましょう」
- 「banana は バナナ という いみです」
- 「さあ みんなで おぼえよう」

【発音・表記ルール（重要）】
- 日本語パートはすべてひらがな・カタカナで書く（漢字は一切使わない）
- 英単語は英語表記のまま維持する（カタカナに変換しない）
- [Intro] [Verse] [Outro] などのセクションタグはそのまま残す
- 長音は「〜」で表記してよい

【出力形式】
以下の JSON 形式のみで出力してください（説明文やコードフェンスは不要）。
{
  "lyrics": "（ひらがな＋英語の歌詞全文）"
}
"""

# ─── 英文モード用プロンプト ───────────────────────────
LYRICS_PROMPT_TEMPLATE_SENTENCE = """あなたはCMジングルの天才コピーライターです。
以下の英文と日本語訳のペアを「絶対に忘れられない30秒のジングル歌詞」にしてください。

英文ペア:
{word_list}

【歌詞のルール】
- 英文のあとに日本語訳をリズムよく続ける
- ただ訳すのではなく、ダジャレ・語呂合わせ・ツッコミで印象づける
- 30秒で歌い切れる短さにする（全体で8〜12行以内）
- セクション構成: [Intro](1行) → [Verse](本体) → [Outro](1行)

【発音・表記ルール（重要）】
- 日本語パートはすべてひらがな・カタカナで書く（漢字は一切使わない）
- 英文は英語表記のまま維持する（カタカナに変換しない）
- [Intro] [Verse] [Outro] などのセクションタグはそのまま残す
- 長音は「〜」で表記してよい

【出力形式】
以下の JSON 形式のみで出力してください（説明文やコードフェンスは不要）。
{
  "lyrics": "（ひらがな＋英語の歌詞全文）"
}
"""


def _format_word_list(word_pairs: List[Dict[str, str]]) -> str:
    lines = []
    for i, p in enumerate(word_pairs, 1):
        lines.append(f"{i}. {p['word']} = {p['meaning']}")
    return "\n".join(lines)


def _parse_lyrics_json(response_text: str) -> str:
    """
    AIレスポンスから lyrics を取り出す。
    パースに失敗した場合は全文をそのまま使う（フォールバック）。
    """
    text = response_text.strip()

    # コードフェンスを除去
    fence_match = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # JSON を抽出
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        json_text = text[brace_start:brace_end + 1]
        try:
            data = json.loads(json_text)
            lyrics = (data.get("lyrics") or "").strip()
            if lyrics:
                return lyrics
        except json.JSONDecodeError:
            pass

    # フォールバック: JSON でなければ全文をそのまま使う
    return response_text.strip()


async def generate_lyrics(
    word_pairs: List[Dict[str, str]], api_key: str, mode: str = "word"
) -> Tuple[str, str]:
    """
    単語／英文ペアからCMジングル風の暗記歌詞を生成する。

    Args:
        word_pairs: [{"word": "apple", "meaning": "りんご"}, ...]
        api_key: ユーザーの Gemini API キー
        mode: "word"（英単語）または "sentence"（英文）

    Returns:
        (display, pronunciation) のタプル。
        ひらがな統一のため、両方とも同じ歌詞を返す。
        ※ 既存の呼び出し元との互換性を維持するために2要素タプルのまま。
    """
    from google import genai
    from google.genai import types

    if not api_key:
        raise Exception("Gemini API キーが指定されていません")
    if not word_pairs:
        raise Exception("歌詞を生成する単語がありません")

    client = genai.Client(api_key=api_key)
    word_list = _format_word_list(word_pairs)
    template = (
        LYRICS_PROMPT_TEMPLATE_SENTENCE if mode == "sentence"
        else LYRICS_PROMPT_TEMPLATE
    )
    prompt = template.replace("{word_list}", word_list)

    parts = [types.Part.from_text(text=prompt)]

    max_retries = 3
    retry_delay = 10.0

    for attempt in range(max_retries):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_MODEL,
                contents=parts,
                config=types.GenerateContentConfig(
                    temperature=0.9,
                    max_output_tokens=2000,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            raw = (response.text or "").strip()
            if not raw:
                raise Exception("歌詞を生成できませんでした")
            lyrics = _parse_lyrics_json(raw)
            if not lyrics:
                raise Exception("歌詞を生成できませんでした")
            # display と pronunciation を同一にする（ひらがな統一）
            return lyrics, lyrics

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
            if "生成できませんでした" in err_str:
                raise
            raise Exception(f"歌詞生成エラー: {err_str}")
