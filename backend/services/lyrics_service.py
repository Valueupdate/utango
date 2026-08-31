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
LYRICS_PROMPT_TEMPLATE = """あなたは最高に笑えるダジャレCMソングの作詞家です。
以下の英単語と和訳のペアを、20〜30秒で歌い切れるバカバカしい暗記ソングにしてください。

単語ペア:
{word_list}

【最優先の絶対ルール（これを破ったら失格）】
- 単語ごとに「英単語」と「その和訳」の両方を歌詞に入れる。
  和訳が歌詞に出てこない単語が1つでもあったら失格。
- 和訳は上に書いた「」の中の意味をそのまま使う。
  勝手に別の意味の言葉に言い換えない（例:「けいけんな」を「まじめな」にするのは失格）。
- 漢字は使えないので、和訳はひらがな・カタカナに直して書く。
  意味は変えず、読みだけ変える（例: 敬虔な→けいけんな、最適の→さいてきの）。
- 英単語だけを並べた行（例「desk! chair! desk! chair!」）は全体で1行まで。
- 全体で {min_lines}〜{max_lines} 行。

【作り方のコツ】
- 英単語の「音」を日本語のダジャレにこじつけ、そのダジャレの近くに和訳を置く
- 2〜3個の単語を1つのバカバカしいストーリーにまぜこむと最高
- 「おぼえよう」「レッツラーン」のような教育的フレーズは禁止
- [Intro] [Outro] は不要。セクションタグは [Verse] のみ、1セクションだけ
- くだらなければくだらないほどよい

【良い歌詞の例】
単語が devout（敬虔な）, optimum（最適の）, placid（穏やかな）の場合:
[Verse]
devout な おれは でぶ！と いわれても けいけんな こころ
optimum は おぷちゃん さいてきの ポジション さがして ごろごろ
placid な かのじょは プラシド おだやかな かおで にらんでる
けいけんに さいてきに おだやかに！ devout! optimum! placid!

【失格の例】
- 「devout! optimum! placid!」だけで 和訳（けいけんな・さいてきの・おだやかな）が
  どこにも出てこない歌詞
- 「○○ は △△ という いみです」のような説明くさい歌詞
- おしゃれ・きれい・さわやかな歌詞

【表記ルール】
- にほんごは ぜんぶ ひらがな・カタカナ（かんじ きんし）
- えいたんごは えいご の まま（カタカナに しない）

【出力形式】
以下の JSON のみを出力（説明文・コードフェンスは不要）:
{
  "lyrics": "（歌詞）",
  "used": [
    {"word": "（英単語）", "kana": "（歌詞の中で実際に使った和訳のかな表記）"}
  ]
}
"used" には渡された単語すべてを必ず書く。
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


# def _format_word_list(word_pairs: List[Dict[str, str]]) -> str:
#     lines = []
#     for i, p in enumerate(word_pairs, 1):
#         lines.append(f"{i}. {p['word']} = {p['meaning']}")
#     return "\n".join(lines)

def _split_meanings(meaning: str) -> List[str]:
    parts = [m.strip() for m in re.split(r"[、,，/／]", meaning) if m.strip()]
    return parts or [meaning.strip()]


def _format_word_list(word_pairs: List[Dict[str, str]]) -> str:
    lines = []
    for i, p in enumerate(word_pairs, 1):
        meanings = _split_meanings(p["meaning"])
        main = meanings[0]
        extra = f"（ほかの訳: {'・'.join(meanings[1:])}）" if len(meanings) > 1 else ""
        lines.append(f"{i}. {p['word']} = 「{main}」{extra}")
    return "\n".join(lines)


def _normalize(text: str) -> str:
    return re.sub(r"[\s！!、。,\.〜~ー・]", "", text).lower()


def _find_missing(
    lyrics: str, word_pairs: List[Dict[str, str]], used: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """歌詞に英単語または和訳が入っていない語を返す"""
    kana_map = {
        str(u.get("word", "")).strip().lower(): str(u.get("kana", "")).strip()
        for u in used
        if isinstance(u, dict)
    }
    flat = _normalize(lyrics)
    missing = []
    for p in word_pairs:
        word = p["word"].strip()
        kana = kana_map.get(word.lower(), "")
        word_ok = _normalize(word) in flat
        kana_ok = bool(kana) and _normalize(kana) in flat
        if not (word_ok and kana_ok):
            missing.append({
                "word": word,
                "meaning": _split_meanings(p["meaning"])[0],
                "kana": kana,
                "reason": "英単語なし" if not word_ok else "和訳なし",
            })
    return missing


def _parse_lyrics_json(response_text: str) -> Tuple[str, List[Dict[str, str]]]:
    text = response_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    brace_start, brace_end = text.find("{"), text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            data = json.loads(text[brace_start:brace_end + 1])
            lyrics = (data.get("lyrics") or "").strip()
            used = data.get("used") or []
            if lyrics:
                return lyrics, used if isinstance(used, list) else []
        except json.JSONDecodeError:
            pass
    return response_text.strip(), []

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
    n = len(word_pairs)
    template = (
        LYRICS_PROMPT_TEMPLATE_SENTENCE if mode == "sentence"
        else LYRICS_PROMPT_TEMPLATE
    )
    base_prompt = (
        template.replace("{word_list}", word_list)
        .replace("{min_lines}", str(max(4, n * 2)))
        .replace("{max_lines}", str(max(6, n * 2 + 2)))
    )

    async def _call(prompt_text: str) -> Tuple[str, List[Dict[str, str]]]:
        parts = [types.Part.from_text(text=prompt_text)]
        max_retries, retry_delay = 3, 10.0
        for attempt in range(max_retries):
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=GEMINI_MODEL,
                    contents=parts,
                    config=types.GenerateContentConfig(
                        temperature=1.0,
                        max_output_tokens=1600,
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    ),
                )
                raw = (response.text or "").strip()
                if not raw:
                    raise Exception("歌詞を生成できませんでした")
                return _parse_lyrics_json(raw)
            except Exception as e:
                err = str(e)
                retryable = any(
                    k in err for k in
                    ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE",
                     "high demand", "try again later")
                )
                if retryable and attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                raise
        raise Exception("歌詞を生成できませんでした")

    lyrics, used = await _call(base_prompt)
    missing = _find_missing(lyrics, word_pairs, used)

    # 和訳が落ちた語があれば、指摘して1回だけ書き直させる
    if missing:
        detail = "\n".join(
            f"- {m['word']}（和訳「{m['meaning']}」）: {m['reason']}" for m in missing
        )
        fix_prompt = (
            f"{base_prompt}\n\n"
            "【やり直しの指示】\n"
            "さきほど作った歌詞は次の単語で失格でした:\n"
            f"{detail}\n"
            "これらの単語について、英単語とその和訳（ひらがな）が"
            "必ず歌詞に出てくるように全文を作り直してください。\n"
            f"さきほどの歌詞:\n{lyrics}\n"
        )
        try:
            retry_lyrics, retry_used = await _call(fix_prompt)
            if len(_find_missing(retry_lyrics, word_pairs, retry_used)) < len(missing):
                lyrics, used = retry_lyrics, retry_used
                missing = _find_missing(lyrics, word_pairs, used)
        except Exception:
            pass

    # それでも落ちている語は、機械的に対句を足して和訳を必ず載せる
    if missing:
        extra = [f"{m['word']}！ {m['kana'] or m['meaning']}！" for m in missing]
        lyrics = lyrics.rstrip() + "\n" + "\n".join(extra)

    return lyrics, lyrics

        # except Exception as e:
        #     err_str = str(e)
        #     is_retryable = (
        #         "429" in err_str
        #         or "RESOURCE_EXHAUSTED" in err_str
        #         or "503" in err_str
        #         or "UNAVAILABLE" in err_str
        #         or "high demand" in err_str
        #         or "try again later" in err_str
        #     )
        #     if is_retryable and attempt < max_retries - 1:
        #         await asyncio.sleep(retry_delay)
        #         retry_delay *= 1.5
        #         continue
        #     if "生成できませんでした" in err_str:
        #         raise
        #     raise Exception(f"歌詞生成エラー: {err_str}")
