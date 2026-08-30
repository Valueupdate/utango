"""
楽曲／音声生成サービス

2つのモードを提供:
  - TTS モード（無料）: Gemini TTS で歌詞をテンション高く読み上げる
  - Lyria モード（有料）: Lyria 3 Clip でメロディ付きの歌を生成する
"""
import os
import wave
import base64
import asyncio

from config import (
    LYRIA_MODEL, MUSIC_STYLE_PROMPT,
    TTS_MODEL, TTS_VOICE, TTS_STYLE_PROMPT,
)


def _build_music_prompt(lyrics: str) -> str:
    """Lyria 用: 楽曲指示 + 歌詞"""
    return f"{MUSIC_STYLE_PROMPT}\n\nLyrics:\n{lyrics}"


def _build_tts_prompt(lyrics: str) -> str:
    """TTS 用: スタイル指示 + 歌詞"""
    # セクションタグを演出タグに変換
    text = lyrics
    text = text.replace("[Verse]", "[excited, energetic]")
    text = text.replace("[Intro]", "[excited]")
    text = text.replace("[Outro]", "[shouting]")
    return f"{TTS_STYLE_PROMPT}{text}"


def _save_wave(filename: str, pcm_data: bytes,
               channels: int = 1, rate: int = 24000, sample_width: int = 2):
    """PCMデータをWAVファイルとして保存"""
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_data)


async def generate_music_lyria(lyrics: str, output_path: str, api_key: str) -> str:
    """Lyria 3 Clip で楽曲を生成する（有料）"""
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
            # Lyria は generate_content でも動作する（公式 Cookbook 準拠）
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=LYRIA_MODEL,
                contents=prompt,
            )

            audio_data = None
            for part in response.parts:
                if getattr(part, "inline_data", None) is not None:
                    audio_data = part.inline_data.data
                    break

            if audio_data is None:
                raise Exception("楽曲データが返されませんでした")

            with open(output_path, "wb") as f:
                f.write(audio_data)

            print(f"[MusicService] Lyria generated: {output_path}")
            return output_path

        except Exception as e:
            err_str = str(e)
            is_retryable = (
                "429" in err_str
                or "RESOURCE_EXHAUSTED" in err_str
                or "503" in err_str
                or "UNAVAILABLE" in err_str
            )
            if is_retryable and attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                retry_delay *= 1.5
                continue
            if "返されませんでした" in err_str:
                raise
            raise Exception(f"楽曲生成エラー: {err_str}")


async def generate_music_tts(lyrics: str, output_path: str, api_key: str) -> str:
    """Gemini TTS で歌詞を読み上げる（無料）"""
    from google import genai

    if not api_key:
        raise Exception("Gemini API キーが指定されていません")
    if not lyrics:
        raise Exception("読み上げる歌詞がありません")

    client = genai.Client(api_key=api_key)
    prompt = _build_tts_prompt(lyrics)

    max_retries = 3
    retry_delay = 10.0

    for attempt in range(max_retries):
        try:
            # 公式ドキュメント準拠: Interactions API TTS
            # https://ai.google.dev/gemini-api/docs/speech-generation
            interaction = await asyncio.to_thread(
                client.interactions.create,
                model=TTS_MODEL,
                input=prompt,
                response_format={"type": "audio"},
                generation_config={
                    "speech_config": [
                        {"voice": TTS_VOICE}
                    ]
                },
                store=False,
            )

            if not interaction.output_audio or not interaction.output_audio.data:
                raise Exception("音声データが返されませんでした")

            pcm_data = base64.b64decode(interaction.output_audio.data)

            # WAV として保存
            wav_path = output_path.replace(".mp3", ".wav")
            _save_wave(wav_path, pcm_data)

            print(f"[MusicService] TTS generated: {wav_path}")
            return wav_path

        except Exception as e:
            err_str = str(e)
            is_retryable = (
                "429" in err_str
                or "RESOURCE_EXHAUSTED" in err_str
                or "503" in err_str
                or "UNAVAILABLE" in err_str
            )
            if is_retryable and attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                retry_delay *= 1.5
                continue
            if "返されませんでした" in err_str:
                raise
            raise Exception(f"TTS生成エラー: {err_str}")


async def generate_music(lyrics: str, output_path: str, api_key: str,
                         quality: str = "standard") -> str:
    """
    歌詞から音声を生成する統合関数。

    Args:
        quality: "standard"（TTS無料）または "high"（Lyria有料）
    """
    if quality == "high":
        return await generate_music_lyria(lyrics, output_path, api_key)
    else:
        return await generate_music_tts(lyrics, output_path, api_key)
