"""
楽曲生成サービス

生成された歌詞を Google Lyria 3 Pro に渡し、楽曲（MP3）を生成する。
docs/design/lyrics-design.md §5.3 の入力形式に従い、
歌詞を Lyrics: プレフィックスで固定して渡す。
"""
import os
import asyncio
from typing import Optional

from config import LYRIA_MODEL, MUSIC_STYLE_PROMPT


def _build_music_prompt(lyrics: str) -> str:
    """楽曲指示 + Lyrics: で固定した歌詞を組み立てる"""
    return f"{MUSIC_STYLE_PROMPT}\n\nLyrics:\n{lyrics}"


def _extract_audio_bytes(response) -> Optional[bytes]:
    """
    レスポンスから音声バイト列を安全に取り出す。

    response.parts は安全性ブロック時やテキストのみ応答時に None になる
    ことがあり、直接ループすると TypeError で落ちる。candidates から
    辿り、各段階を getattr で防御する。
    """
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline is not None and getattr(inline, "data", None):
                return inline.data
    return None


def _describe_failure(response) -> str:
    """音声が取れなかった理由を、判明する範囲で文字列にまとめる"""
    details = []

    feedback = getattr(response, "prompt_feedback", None)
    block_reason = getattr(feedback, "block_reason", None) if feedback else None
    if block_reason:
        details.append(f"block_reason={block_reason}")

    for candidate in getattr(response, "candidates", None) or []:
        finish = getattr(candidate, "finish_reason", None)
        if finish:
            details.append(f"finish_reason={finish}")

    try:
        text = (getattr(response, "text", None) or "").strip()
    except Exception:
        text = ""
    if text:
        details.append(f"text={text[:200]}")

    if not details:
        details.append("レスポンスに音声パートが含まれていません")
    return " / ".join(details)


async def generate_music(lyrics: str, output_path: str, api_key: str) -> str:
    """
    歌詞から楽曲（MP3）を生成する。

    Args:
        lyrics: generate_lyrics の出力（セクションタグ付き歌詞）
        output_path: 出力MP3ファイルのパス
        api_key: ユーザーの Gemini API キー（BYOK）

    Returns:
        生成された音声ファイルのパス
    """
    from google import genai

    if not api_key:
        raise Exception("Gemini API キーが指定されていません")
    if not lyrics:
        raise Exception("楽曲化する歌詞がありません")

    client = genai.Client(api_key=api_key)
    prompt = _build_music_prompt(lyrics)

    max_retries = 3
    retry_delay = 15.0

    for attempt in range(max_retries):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=LYRIA_MODEL,
                contents=prompt,
            )

            audio_data = _extract_audio_bytes(response)

            if audio_data is None:
                reason = _describe_failure(response)
                print(f"[MusicService] No audio returned: {reason}")
                raise Exception(f"楽曲データが返されませんでした（{reason}）")

            with open(output_path, "wb") as f:
                f.write(audio_data)

            print(f"[MusicService] Generated: {output_path}")
            return output_path

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
            if "返されませんでした" in err_str or "歌詞がありません" in err_str:
                raise
            raise Exception(f"楽曲生成エラー: {err_str}")
