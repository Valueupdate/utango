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
LYRICS_PROMPT_TEMPLATE = """あなたは日本の暗記ソングの作詞家です。
英単語の音を「実在する日本語のことば」に置きかえた語呂合わせで、
20〜30秒で歌い切れる、くすっと笑える暗記ソングを作ってください。

単語ペア:
{word_list}

【最優先の絶対ルール（破ったら失格）】
- 単語ごとに「英単語」「語呂合わせの日本語」「和訳」の3つを同じ行に入れる
- 語呂合わせは、実在する日本語のことば・フレーズにする。
  意味のない音のならび（例: おぷてぃむむ、いんちきめいと、でぶうっとり）は失格
- 英単語をカタカナに読みかえただけのものは語呂合わせではない。失格
- 各行は、日本語の文として通じること。景色が目に浮かぶ一文にする
- 和訳は上の「」の意味をそのまま使う。別の意味に言いかえたら失格
- 漢字は使えないので、和訳はひらがなに直して書く（意味は変えず読みだけ変える）
- 全体で {min_lines}〜{max_lines} 行

【日本的にする】
- 題材は日本の暮らし。おふろ、こたつ、おまいり、おべんとう、えんがわ、
  さんぽ、たなばた、おばあちゃん、こうえん、でんしゃ、たいやき など
- ブラックジョーク、下品なネタ、皮肉は禁止。ほのぼのした笑いにする
- 人の見た目や体型をからかうことば（でぶ、はげ など）は絶対に使わない
- 「おぼえよう」「おぼえろ」「レッツラーン」などの教育的フレーズは禁止
- [Intro] [Outro] は不要。セクションタグは [Verse] のみ、1セクション

【良い歌詞の例】
単語が devout（敬虔な）, placid（穏やかな）, assiduous（勤勉な）の場合:
[Verse]
devout は でっかい ぼうさん けいけんな かおで おまいり
placid は プラスチックの おけ おだやかな おふろの ゆげ
assiduous は あしを どうする？ きんべんな ありが ぎょうれつ
でっかい ぼうさんも ありんこも きょうも まじめに あるいてる
devout! placid! assiduous!

（ポイント: でっかいぼうさん・プラスチックのおけ・あしをどうする は
 どれも日本語として意味が通じることば。音だけの断片にしていない）

【失格の例】
- 「optimum！ おぷてぃむむ！」…英単語をカタカナにしただけ
- 「devout！ でぶ うっとり」…意味のない断片、しかも見た目をからかっている
- 「intimate！ いんちき めいと」…日本語として意味が通じない
- 和訳（けいけんな など）が歌詞のどこにも出てこない
- 「○○ は △△ という いみです」のような説明くさい歌詞

【表記ルール】
- にほんごは ぜんぶ ひらがな・カタカナ（かんじ きんし）
- えいたんごは えいご の まま（カタカナに しない）

【出力形式】
以下の JSON のみを出力（説明文・コードフェンスは不要）:
{
  "lyrics": "（歌詞）",
  "used": [
    {
      "word": "（英単語）",
      "goro": "（語呂合わせに使った日本語のことば）",
      "goro_imi": "（その日本語が何を指すかの説明）",
      "kana": "（歌詞の中で使った和訳のかな表記）"
    }
  ]
}
"used" には渡された単語すべてを必ず書く。
"goro_imi" が書けないような音のならびは語呂合わせとして失格なので、作り直すこと。
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

_BANNED_WORDS = [
    "でぶ", "デブ", "はげ", "ハゲ", "ちび", "ブス", "きちがい",
    "おぼえよう", "おぼえろ", "おぼえたかな", "レッツラーン", "べんきょうしよう",
]


def _find_banned(lyrics: str) -> List[str]:
    return [w for w in _BANNED_WORDS if w in lyrics]


def _find_weak_goro(used: List[Dict[str, str]]) -> List[str]:
    """語呂の説明を書けていない＝音の羅列になっている語を返す"""
    weak = []
    for u in used:
        if not isinstance(u, dict):
            continue
        goro = str(u.get("goro") or "").strip()
        imi = str(u.get("goro_imi") or "").strip()
        if not goro or not imi or len(imi) < 4:
            weak.append(str(u.get("word") or "").strip())
    return [w for w in weak if w]


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
                        temperature=0.9,
                        max_output_tokens=2400,
                        thinking_config=types.ThinkingConfig(thinking_budget=1024),
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
    banned = _find_banned(lyrics)
    weak = _find_weak_goro(used)

    if missing or banned or weak:
        problems = []
        if missing:
            problems += [
                f"- {m['word']}（和訳「{m['meaning']}」）: {m['reason']}" for m in missing
            ]
        if banned:
            problems.append(
                f"- 使ってはいけないことばが入っている: {'・'.join(banned)}"
            )
        if weak:
            problems.append(
                f"- 語呂合わせが日本語として意味をなしていない: {'・'.join(weak)}"
            )
        fix_prompt = (
            f"{base_prompt}\n\n"
            "【やり直しの指示】\n"
            "さきほど作った歌詞は次の点で失格でした:\n"
            + "\n".join(problems)
            + "\n実在する日本語のことばを使った語呂合わせに直し、"
            "英単語と和訳の両方が出てくるように全文を作り直してください。\n"
            f"さきほどの歌詞:\n{lyrics}\n"
        )
        try:
            r_lyrics, r_used = await _call(fix_prompt)
            r_score = (
                len(_find_missing(r_lyrics, word_pairs, r_used))
                + len(_find_banned(r_lyrics))
                + len(_find_weak_goro(r_used))
            )
            if r_score < len(missing) + len(banned) + len(weak):
                lyrics, used = r_lyrics, r_used
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
