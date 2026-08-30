"""
暗記歌詞生成サービス

抽出した英単語・和訳（または英文・和訳）のペアから、
CMジングル風の「絶対忘れないダジャレ暗記歌詞」を生成する。

歌詞は最初からひらがな＋英語で生成し、
Lyria が漢字を誤読する問題を根本的に回避する。
"""
import json
import re
import asyncio
from typing import List, Dict, Tuple

from config import GEMINI_MODEL


# ─── 英単語モード用プロンプト ─────────────────────────
LYRICS_PROMPT_TEMPLATE = """あなたは下品で最高に笑えるダジャレCMソングの作詞家です。
以下の英単語と和訳のペアを、15〜20秒で歌い切れるバカバカしい歌詞にしてください。

単語ペア:
{word_list}

【絶対ルール】
- 英単語の「音」を日本語のダジャレ・語呂合わせにむりやりこじつける
- 2〜3個の単語をむりやり1つのストーリーや文にまぜこむと最高
- 「おぼえよう」「おぼえたかな」「レッツラーン」のような教育的フレーズは禁止
- [Intro] [Outro] は不要。いきなりサビから始めてサビで終わる
- セクションタグは [Verse] のみ。1セクションだけ
- 全体で4〜6行。短ければ短いほどよい
- くだらなければくだらないほどよい。品性はいらない

【良い歌詞の例】
単語が banana（バナナ）, grape（ぶどう）, cherry（さくらんぼ）の場合:
[Verse]
そんな banana！ そんなばかな！
grape ぶどうを グレープとふんで ぐちゃぐちゃ〜
cherry は「ちぇりー」じゃない さくらんぼだよ ちぇっ！
ばかな banana に ぐちゃぐちゃ grape に ちぇっ！な cherry！

単語が desk（つくえ）, chair（いす）の場合:
[Verse]
desk の うえに すわるな！それは chair だ！
いすと つくえを まちがえるやつ〜
desk! chair! desk! chair!
つくえ！いす！つくえ！いす！

単語が run（はしる）, swim（およぐ）, fly（とぶ）の場合:
[Verse]
run! はしれ！ swim! およげ！ fly! とべ〜！
はしって およいで とんだら つかれた〜
もういっかい！ run! swim! fly!
はしる！およぐ！と〜ぶ！

【こういう歌詞は失格（絶対に書くな）】
- 「さあ おぼえよう」「レッツ スタート」「きょうの たんご」
- 「○○ は △△ という いみです」
- 1単語ずつ おぎょうぎよく ならべただけの歌詞
- おしゃれ・きれい・さわやかな歌詞

【表記ルール】
- にほんごは ぜんぶ ひらがな・カタカナ（かんじ きんし）
- えいたんごは えいご の まま（カタカナに しない）
- ちょうおんは「〜」でOK

【出力形式】
以下の JSON のみを出力（説明文・コードフェンスは不要）:
{
  "lyrics": "（歌詞）"
}
"""

# ─── 英文モード用プロンプト ───────────────────────────
LYRICS_PROMPT_TEMPLATE_SENTENCE = """あなたは下品で最高に笑えるダジャレCMソングの作詞家です。
以下の英文と日本語訳のペアを、15〜20秒で歌い切れるバカバカしい歌詞にしてください。

英文ペア:
{word_list}

【絶対ルール】
- 英文を歌い、そのあと日本語訳をダジャレっぽく続ける
- 「おぼえよう」「おぼえたかな」「レッツラーン」のような教育的フレーズは禁止
- [Intro] [Outro] は不要。いきなり始めていきなり終わる
- セクションタグは [Verse] のみ。1セクションだけ
- 全体で4〜6行。短ければ短いほどよい
- くだらなければくだらないほどよい

【表記ルール】
- にほんごは ぜんぶ ひらがな・カタカナ（かんじ きんし）
- えいぶんは えいご の まま（カタカナに しない）
- ちょうおんは「〜」でOK

【出力形式】
以下の JSON のみを出力（説明文・コードフェンスは不要）:
{
  "lyrics": "（歌詞）"
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

    Returns:
        (display, pronunciation) のタプル。
        ひらがな統一のため、両方とも同じ歌詞を返す。
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
                    temperature=1.2,
                    max_output_tokens=1000,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            raw = (response.text or "").strip()
            if not raw:
                raise Exception("歌詞を生成できませんでした")
            lyrics = _parse_lyrics_json(raw)
            if not lyrics:
                raise Exception("歌詞を生成できませんでした")
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
