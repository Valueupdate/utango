"""
utango バックエンド - エントリーポイント

英単語帳／英文の画像をアップロードすると、
抽出 → 暗記歌詞生成 → 楽曲生成 を一気通貫で実行し、
歌詞付きの暗記ソング（MP3）を生成する API サーバー。

【動作確認フェーズ】共有キー方式（サーバーのフォールバックキー）＋
BYOK（Bring Your Own Key）併用。キーが送られなければサーバーキーを使う。
"""
import os
import json
import asyncio
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import (
    APP_VERSION, TEMP_DIR, FRONTEND_URL, EXTRA_CORS_ORIGINS,
    MAX_IMAGE_SIZE_BYTES, ALLOWED_IMAGE_EXTENSIONS,
    JOB_CLEANUP_INTERVAL_SECONDS, FALLBACK_GEMINI_API_KEY,
)
from services.job_manager import job_manager, Job
from services.vocab_service import extract_word_pairs
from services.lyrics_service import generate_lyrics
from services.music_service import generate_music


# ─── 定期クリーンアップタスク ─────────────────────────
async def cleanup_loop():
    """期限切れジョブを定期的に削除する"""
    while True:
        await asyncio.sleep(JOB_CLEANUP_INTERVAL_SECONDS)
        job_manager.cleanup_expired()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(cleanup_loop())
    yield
    task.cancel()


# ─── アプリケーション初期化 ───────────────────────────
app = FastAPI(title="utango API", version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000"] + EXTRA_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── メインの生成パイプライン ─────────────────────────
async def run_generation(job: Job, image_path: str, api_key: str, mode: str = "word"):
    """バックグラウンドで 抽出→歌詞生成→楽曲生成 を実行する"""
    try:
        # モードに応じた表示文言
        subject = "英文" if mode == "sentence" else "英単語"

        # 1. 抽出
        await job.update("extract", 10, f"画像から{subject}を読み取っています...")
        word_pairs = await extract_word_pairs(image_path, api_key, mode)
        await job.update(
            "extract", 35,
            f"{len(word_pairs)}個の{subject}を読み取りました"
        )

        # 2. 暗記歌詞生成（表示用=漢字あり / 発音用=ひらがな の2種類）
        await job.update("lyrics", 45, "暗記ソングの歌詞を作っています...")
        display_lyrics, pronunciation_lyrics = await generate_lyrics(
            word_pairs, api_key, mode
        )
        await job.update("lyrics", 60, "歌詞ができました")

        # 3. 楽曲生成（発音用=ひらがな歌詞を渡して正しい日本語発音にする）
        await job.update("music", 70, "歌を作っています（少し時間がかかります）...")
        output_path = os.path.join(job.work_dir, f"{job.job_id}.mp3")
        await generate_music(pronunciation_lyrics, output_path, api_key)
        await job.update("music", 95, "歌が完成しました")

        # 4. 完了（画面には表示用=漢字ありの歌詞を渡す）
        download_url = f"/download/{job.job_id}"
        await job.complete(download_url, display_lyrics, word_pairs)

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[Main] Job {job.job_id} failed: {e}")
        await job.fail(str(e))


# ─── エンドポイント ───────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "ready": True,
        "auth_mode": "shared+byok",
    }


@app.post("/generate")
async def generate(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    api_key: str = Form(""),
    mode: str = Form("word"),
):
    """英単語／英文ソング生成のメインエンドポイント"""

    # 共有キー: ユーザーのキーがあればそれを使い、無ければサーバーのフォールバックキー。
    effective_key = api_key.strip() or FALLBACK_GEMINI_API_KEY
    if not effective_key:
        raise HTTPException(
            status_code=400,
            detail="Gemini API キーを入力してください。",
        )

    # モードの正規化（未知の値は word 扱い）
    if mode not in ("word", "sentence"):
        mode = "word"

    # 拡張子バリデーション
    if not file.filename:
        raise HTTPException(status_code=400, detail="ファイルが選択されていません")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        allowed = ", ".join(ALLOWED_IMAGE_EXTENSIONS)
        raise HTTPException(
            status_code=400,
            detail=f"対応している画像形式は {allowed} です",
        )

    # サイズチェック
    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE_BYTES:
        mb = MAX_IMAGE_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"ファイルサイズが{mb}MBを超えています",
        )

    # ジョブ作成 + 画像保存
    job = job_manager.create_job()
    image_path = os.path.join(job.work_dir, f"input{ext}")
    with open(image_path, "wb") as f:
        f.write(content)

    # バックグラウンドで処理開始
    background_tasks.add_task(run_generation, job, image_path, effective_key, mode)

    return {
        "job_id": job.job_id,
        "status": "processing",
        "message": "ソングの生成を開始しました",
    }


@app.get("/progress/{job_id}")
async def progress(job_id: str):
    """SSEで進捗を配信する"""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")

    async def event_stream():
        while True:
            try:
                event = await asyncio.wait_for(job.queue.get(), timeout=30.0)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("step") in ("done", "error"):
                    break
            except asyncio.TimeoutError:
                keepalive = {
                    "step": "keepalive",
                    "progress": job.progress,
                    "message": job.message,
                }
                yield f"data: {json.dumps(keepalive, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/download/{job_id}")
async def download(job_id: str):
    """生成された楽曲をダウンロードする"""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail="ジョブが見つかりません。有効期限が切れた可能性があります。",
        )

    audio_path = os.path.join(job.work_dir, f"{job.job_id}.mp3")
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="楽曲ファイルが見つかりません")

    return FileResponse(
        audio_path,
        media_type="audio/mpeg",
        filename=f"utango_{job_id}.mp3",
    )


@app.get("/result/{job_id}")
async def result(job_id: str):
    """歌詞・単語ペア・ダウンロードURLをまとめて返す（再生画面用）"""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    if job.status != "completed":
        return {"status": job.status, "step": job.step}

    return {
        "status": "completed",
        "download_url": job.download_url,
        "lyrics": job.lyrics,
        "word_pairs": job.word_pairs,
    }


# ─── フロントエンド静的ファイル配信 ───────────────────
# APIエンドポイントより後にマウントすることで API が優先される
FRONTEND_OUT = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "out"
if FRONTEND_OUT.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_OUT), html=True), name="frontend")
    print(f"[Main] Frontend mounted from: {FRONTEND_OUT}")
else:
    print(f"[Main] Frontend not found at: {FRONTEND_OUT}")

# ─── 直接実行時の起動 ─────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    print(f"[Main] Starting utango on port {port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
