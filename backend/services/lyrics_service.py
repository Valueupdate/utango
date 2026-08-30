"""
暗記歌詞生成サービス

抽出した英単語・和訳（または英文・和訳）のペアから、
暗記に最適化された歌詞を生成する。

【発音対策】Lyria 3 が漢字を誤読（中国語読み等）するのを防ぐため、
表示用（漢字あり）と発音用（漢字をひらがなに変換、英語はそのまま）の
2種類の歌詞を生成する。表示用は画面に、発音用は楽曲生成に使う。
"""
import json
import re
import asyncio
from typing import List, Dict, Tuple

from config import GEMINI_MODEL

# 発音用歌詞の共通ルール（両モードのプロンプト末尾に付加する）
PRONUNCIATION_RULE = """

【出力形式・重要】
上記の構成で歌詞を作り、必ず以下の JSON 形式のみで出力してください（説明文やコードフェンスは不要）。

- "display": 画面表示用の歌詞。日本語は漢字のまま。
- "pronunciation": 楽曲生成（歌唱）用の歌詞。display と同じ構成・同じ行数で、
  次の変換を施したもの:
    - 日本語の漢字を、その文脈での正しい読みに従ってすべて「ひらがな」に変換する
      （例: 海→うみ、覚えよう→おぼえよう、私には夢がある→わたしにはゆめがある）
    - ひらがな・カタカナはそのまま
    - 英単語・英文は英語表記のまま維持し、カタカナやローマ字読みにしない
      （例: apple は apple のまま）
    - [Intro] などのセクションタグはそのまま残す

出力JSON:
{
  "display": "（漢字ありの歌詞全文）",
  "pronunciation": "（漢字をひらがなに変換した歌詞全文）"
}
"""

LYRICS_PROMPT_TEMPLATE = """あなたは英単語暗記ソングの作詞家です。
以下の英単語と和訳のペアから、暗記に最適化された歌詞を作成してください。

単語ペア:
{word_list}

ルール:
- 各単語を Verse で「英単語 (和訳), 英単語 (和訳)」の形で反復する（括弧内はエコー）
- Chorus では英単語をまとめて並べ、続けて和訳をまとめて並べる
- セクション構成は [Intro] [Verse 1] [Chorus] [Verse 2] [Chorus] [Outro] とする
- 単語が少ない場合は Verse を1つにまとめてよい
- 英単語と和訳は与えられたものを変更しない（綴り・訳語を勝手に変えない）
- Outro では全単語を一度ずつ並べる

display の歌詞の例（この形の歌詞を作る）:
[Intro]
Let's learn some words! (うたんご)

[Verse 1]
apple (りんご), apple (りんご)
ocean (海), ocean (海)

[Chorus]
apple, ocean (覚えよう)
りんご, 海 (もう一回)

[Outro]
apple, ocean
""" + PRONUNCIATION_RULE

# 英文モード用: 英文 → 日本語訳を交互に歌う日英併記の歌詞
LYRICS_PROMPT_TEMPLATE_SENTENCE = """あなたは英語学習ソングの作詞家です。
以下の英文と日本語訳のペアから、意味を理解しながら覚えられる歌詞を作成してください。

英文ペア:
{word_list}

ルール:
- 各ペアを Verse で「英文」の次の行に「(日本語訳)」を置き、交互に歌う形にする
- 英文を歌ったすぐ後に日本語訳が来ることで、意味とセットで覚えられるようにする
- Chorus では覚えてほしい英文をリズムよく繰り返す
- セクション構成は [Intro] [Verse 1] [Chorus] [Verse 2] [Chorus] [Outro] とする
- ペアが少ない場合は Verse を1つにまとめてよい
- 英文と日本語訳は与えられたものを変更しない（勝手に書き換えない）

display の歌詞の例（この形の歌詞を作る）:
[Intro]
Let's sing and understand! (うたんご)

[Verse 1]
I have a dream.
(私には夢がある。)
The sky is blue.
(空は青い。)

[Chorus]
I have a dream, the sky is blue
一緒に覚えよう

[Outro]
I have a dream.
The sky is blue.
""" + PRONUNCIATION_RULE


def _format_word_list(word_pairs: List[Dict[str, str]]) -> str:
    lines = []
    for i, p in enumerate(word_pairs, 1):
        lines.append(f"{i}. {p['word']} = {p['meaning']}")
    return "\n".join(lines)


def _parse_lyrics_json(response_text: str) -> Tuple[str, str]:
    """
    AIレスポンスから display / pronunciation を取り出す。
    パースに失敗した場合は、全文を display・pronunciation 両方に使う
    （最低限、従来どおり歌は生成できるようにするフォールバック）。
    """
    text = response_text.strip()

    fence_match = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        json_text = text[brace_start:brace_end + 1]
        try:
            data = json.loads(json_text)
            display = (data.get("display") or "").strip()
            pronunciation = (data.get("pronunciation") or "").strip()
            if display and pronunciation:
                return display, pronunciation
            if display:
                return display, display
        except json.JSONDecodeError:
            pass

    # フォールバック: JSON でなければ全文をそのまま両方に使う
    return response_text.strip(), response_text.strip()


async def generate_lyrics(
    word_pairs: List[Dict[str, str]], api_key: str, mode: str = "word"
) -> Tuple[str, str]:
    """
    単語／英文ペアから暗記歌詞を生成する。

    Args:
        word_pairs: [{"word": "apple", "meaning": "りんご"}, ...]
        api_key: ユーザーの Gemini API キー
        mode: "word"（英単語）または "sentence"（英文）

    Returns:
        (display, pronunciation) のタプル。
        display: 画面表示用（漢字あり）
        pronunciation: 楽曲生成用（漢字をひらがなに変換）
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
    # 注: プロンプト内に JSON 例（波括弧）を含むため str.format は使わず、
    #     プレースホルダ {word_list} のみを replace で差し替える。
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
                    temperature=0.7,
                    max_output_tokens=3000,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            raw = (response.text or "").strip()
            if not raw:
                raise Exception("歌詞を生成できませんでした")
            display, pronunciation = _parse_lyrics_json(raw)
            if not display:
                raise Exception("歌詞を生成できませんでした")
            return display, pronunciation

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
