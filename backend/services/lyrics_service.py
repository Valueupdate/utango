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
くすっと笑える暗記ソングを作ってください。

単語ペア:
{word_list}

【最優先の絶対ルール（破ったら失格）】
- 語呂合わせは、実在する日本語のことば・フレーズにする。
  意味のない音のならび（例: おぷてぃむむ、いんちきめいと）は失格
- 英単語をカタカナに読みかえただけのものは語呂合わせではない。失格
- 和訳は上の「」の意味をそのまま使う。別の意味に言いかえたら失格
- 漢字は使えないので、和訳はひらがなに直して書く（意味は変えず読みだけ変える）

【歌詞の組み立て（この形を必ずまもる。全体で {total_lines} 行）】
- 1行目: [Verse]
- つぎの {n}行: 単語ごとに1行ずつ。
  その行に「英単語」「語呂合わせの日本語」「和訳（ひらがな）」の3つを必ず入れる
- つぎの1行: サビ。ぜんぶの英単語と和訳を交互にならべる
{summary_rule}
- 英文には、渡された英単語を1つのこらず使う。使っていない単語があったら失格
- 英文は不自然でもよいので、とにかく全部の単語を入れることを優先する
- 英単語が入っていない行を書かない（英文の和訳行だけは例外）
- 日本語だけをならべた行、感想を言う行は失格
  例:「おっと むすこも かめさんも きょうも まじめに いきてる」
- 和訳と対応していない ことばの羅列も失格
  例:「けいけん おだやか きんべん！ devout! placid! assiduous!」
    …英単語と和訳がはなれていて、文にもなっていないのでおぼえられない

【リズム（歌いやすさ）】
- ひらがなは 3〜4文字の かたまりを つなげて書く。かたまりの間は半角スペース
- 1行のひらがなは ぜんぶで 12〜17文字くらい（5・7・5 や 7・7 の調子）
- 6文字をこえる長い かたまりを つくらない。切ってスペースを入れる
- 英単語のあとに「は」「って」などの助詞を入れない
  ×「devout は でっかい ぼうさん」
  ○「devout でっかい ぼうさん」

【日本的にする】
- 題材は日本の暮らし。おふろ、こたつ、おまいり、おべんとう、えんがわ、
  さんぽ、たなばた、おばあちゃん、でんしゃ、たいやき など
- ブラックジョーク、下品なネタ、皮肉は禁止。ほのぼのした笑いにする
- 人の見た目や体型をからかうことば（でぶ、はげ など）は絶対に使わない
- 「おぼえよう」「おぼえろ」「レッツラーン」などの教育的フレーズは禁止
- [Intro] [Outro] は不要。セクションタグは [Verse] のみ、1セクション

【良い歌詞の例】
単語が devout（敬虔な）, placid（穏やかな）, assiduous（勤勉な）の場合:
[Verse]
devout でっかい ぼうさん けいけんな おまいり
placid プラスチック おけに おだやかな ゆげ
assiduous あしを どうする きんべんな ありんこ
devout けいけんな！ placid おだやかな！ assiduous きんべんな！
The devout monk is placid and assiduous.
けいけんな おぼうさん おだやかで きんべん

単語が devout, placid, assiduous, pertinent, optimum の5語の場合の
さいごの4行の例:
The devout monk is placid and assiduous.
けいけんな おぼうさん おだやかで きんべん
His pertinent advice is optimum for us.
かれの てきせつな アドバイス さいこうだね

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
"goro_imi" が書けないような音のならびは失格なので、作り直すこと。
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
    "でぶ", "デブ", "はげ", "ハゲ", "ちび", "ブス",
    "おぼえよう", "おぼえろ", "おぼえたかな", "レッツラーン", "べんきょうしよう",
]


def _split_meanings(meaning: str) -> List[str]:
    parts = [m.strip() for m in re.split(r"[、,，/／]", meaning) if m.strip()]
    return parts or [meaning.strip()]


def _format_word_list(word_pairs: List[Dict[str, str]]) -> str:
    lines = []
    for i, p in enumerate(word_pairs, 1):
        ms = _split_meanings(p["meaning"])
        extra = f"（ほかの訳: {'・'.join(ms[1:])}）" if len(ms) > 1 else ""
        lines.append(f"{i}. {p['word']} = 「{ms[0]}」{extra}")
    return "\n".join(lines)


def _normalize(text: str) -> str:
    return re.sub(r"[\s！!？?、。,\.〜~ー・]", "", text).lower()


def _kana_only(text: str) -> str:
    return re.sub(r"[^ぁ-んァ-ヶー]", "", text)


def _count_words(line: str, word_pairs: List[Dict[str, str]]) -> int:
    low = line.lower()
    return sum(1 for p in word_pairs if p["word"].strip().lower() in low)


def _filler_indices(lyrics: str, word_pairs: List[Dict[str, str]]) -> List[int]:
    """英単語も和訳も入っていない、おぼえる価値のない行の位置"""
    lines = lyrics.splitlines()
    idx = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s or s.startswith("[") or re.search(r"[A-Za-z]", s):
            continue
        prev = lines[i - 1].strip() if i > 0 else ""
        if _count_words(prev, word_pairs) >= 2:
            continue  # 直前の英文の和訳行なので残す
        idx.append(i)
    return idx


def _strip_filler(lyrics: str, word_pairs: List[Dict[str, str]]) -> str:
    drop = set(_filler_indices(lyrics, word_pairs))
    return "\n".join(
        ln for i, ln in enumerate(lyrics.splitlines()) if i not in drop
    ).strip()


def _drop_particles(lyrics: str) -> str:
    """英単語の直後の「は」「って」を落とす"""
    return re.sub(r"([A-Za-z][A-Za-z\-']*)\s*(?:は|って)\s+", r"\1 ", lyrics)


def _audit(
    lyrics: str, used: List[Dict[str, str]], word_pairs: List[Dict[str, str]]
) -> Tuple[List[str], List[Dict[str, str]]]:
    """歌詞を検査して (問題点リスト, 和訳が落ちた語リスト) を返す"""
    kana_map = {
        str(u.get("word", "")).strip().lower(): str(u.get("kana", "")).strip()
        for u in used if isinstance(u, dict)
    }
    flat = _normalize(lyrics)
    problems: List[str] = []
    missing: List[Dict[str, str]] = []

    for p in word_pairs:
        word = p["word"].strip()
        main = _split_meanings(p["meaning"])[0]
        kana = kana_map.get(word.lower(), "")
        word_ok = _normalize(word) in flat
        kana_ok = bool(kana) and _normalize(kana) in flat
        if not (word_ok and kana_ok):
            reason = "英単語が歌詞にない" if not word_ok else "和訳が歌詞にない"
            missing.append({"word": word, "meaning": main, "kana": kana})
            problems.append(f"- {word}（和訳「{main}」）: {reason}")

    weak = [
        str(u.get("word") or "").strip() for u in used
        if isinstance(u, dict)
        and (not str(u.get("goro") or "").strip()
             or len(str(u.get("goro_imi") or "").strip()) < 4)
    ]
    if any(weak):
        problems.append(
            "- 語呂合わせが日本語として意味をなしていない: "
            + "・".join(w for w in weak if w)
        )

    banned = [w for w in _BANNED_WORDS if w in lyrics]
    if banned:
        problems.append("- 使ってはいけないことばが入っている: " + "・".join(banned))

    lines = lyrics.splitlines()
    filler = [lines[i].strip() for i in _filler_indices(lyrics, word_pairs)]
    if filler:
        problems.append(
            "- 英単語も和訳も入っていない行がある（不要）: " + " / ".join(filler)
        )

    long_chunks = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("["):
            continue
        for chunk in re.split(r"[\s！!、。,\.]+", s):
            if len(_kana_only(chunk)) > 7:
                long_chunks.append(chunk)
    if long_chunks:
        problems.append(
            "- ひらがなの かたまりが長くて歌いにくい（3〜4文字ずつに切る）: "
            + " / ".join(long_chunks)
        )

    stripped = [ln.strip() for ln in lines if ln.strip()]
    covered = set()
    sentence_found = False
    for i, ln in enumerate(stripped[:-1]):
        nxt = stripped[i + 1]
        if re.search(r"[A-Za-z]", nxt):
            continue
        if len(_kana_only(nxt)) < 6:
            continue
        # 対象単語以外の英語（is, and, the など）が2つ以上あれば「英文」と判定
        tokens = re.findall(r"[A-Za-z][A-Za-z\-']*", ln)
        targets = {p["word"].strip().lower() for p in word_pairs}
        others = [t for t in tokens if t.lower() not in targets]
        if len(others) < 2:
            continue
        sentence_found = True
        covered |= {t.lower() for t in tokens if t.lower() in targets}

    if not sentence_found:
        problems.append("- さいごの『ぜんぶの単語を使った英文』と『その和訳』がない")
    else:
        uncovered = [
            p["word"] for p in word_pairs
            if p["word"].strip().lower() not in covered
        ]
        if uncovered:
            problems.append(
                "- さいごの英文に入っていない単語がある（英文を2文に分けて全部入れる）: "
                + "・".join(uncovered)
            )
    return problems, missing


def _parse_lyrics_json(response_text: str) -> Tuple[str, List[Dict[str, str]]]:
    """AIレスポンスから lyrics と used を取り出す"""
    text = response_text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
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
    n = len(word_pairs)
    template = (
        LYRICS_PROMPT_TEMPLATE_SENTENCE if mode == "sentence"
        else LYRICS_PROMPT_TEMPLATE
    )
    if n <= 3:
        summary_rule = (
            "- つぎの1行: ぜんぶの英単語を使った かんたんな英文（5〜8語、現在形）\n"
            "- さいごの1行: その英文の和訳（ひらがな）"
        )
        total_lines = n + 4
    else:
        summary_rule = (
            "- つぎの1行: 英単語3つを使った英文（5〜8語、現在形）\n"
            "- つぎの1行: その英文の和訳（ひらがな）\n"
            "- つぎの1行: のこりの英単語ぜんぶを使った英文（5〜8語、現在形）\n"
            "- さいごの1行: その英文の和訳（ひらがな）"
        )
        total_lines = n + 6

    base_prompt = (
        template.replace("{word_list}", _format_word_list(word_pairs))
        .replace("{n}", str(n))
        .replace("{summary_rule}", summary_rule)
        .replace("{total_lines}", str(total_lines))
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
                retryable = any(k in err for k in (
                    "429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE",
                    "high demand", "try again later",
                ))
                if retryable and attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                raise
        raise Exception("歌詞を生成できませんでした")

    lyrics, used = await _call(base_prompt)
    problems, missing = _audit(lyrics, used, word_pairs)

    # 問題があれば、指摘して1回だけ書き直させる
    if problems:
        fix_prompt = (
            f"{base_prompt}\n\n"
            "【やり直しの指示】\n"
            "さきほど作った歌詞は次の点で失格でした:\n"
            + "\n".join(problems)
            + "\n実在する日本語のことばを使った語呂合わせに直し、"
            "決められた行の組み立てを守って全文を作り直してください。\n"
            f"さきほどの歌詞:\n{lyrics}\n"
        )
        try:
            r_lyrics, r_used = await _call(fix_prompt)
            r_problems, r_missing = _audit(r_lyrics, r_used, word_pairs)
            if len(r_problems) < len(problems):
                lyrics, used = r_lyrics, r_used
                problems, missing = r_problems, r_missing
        except Exception:
            pass

    # 後処理: 不要な行を落とし、英単語のあとの助詞を消す
    candidate = _drop_particles(_strip_filler(lyrics, word_pairs))
    if candidate:
        _, cand_missing = _audit(candidate, used, word_pairs)
        if len(cand_missing) <= len(missing):
            lyrics, missing = candidate, cand_missing

    # それでも和訳が落ちている語は、機械的に足して必ず載せる
    if missing:
        lyrics = lyrics.rstrip() + "\n" + "\n".join(
            f"{m['word']}！ {m['kana'] or m['meaning']}！" for m in missing
        )

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
