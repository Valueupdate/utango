"""
utango バックエンド - エントリーポイント

3段階 API:
  POST /extract  — 画像から単語を抽出
  POST /lyrics   — 単語ペアから歌詞を生成（何度でも再生成可能）
  POST /sing     — 歌詞から楽曲を生成（SSE で進捗配信）
"""
import os
import json
import asyncio
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import (
    APP_VERSION, TEMP_DIR, FRONTEND_URL, EXTRA_CORS_ORIGINS,
    MAX_IMAGE_SIZE_BYTES, ALLOWED_IMAGE_EXTENSIONS,
    JOB_CLEANUP_INTERVAL_SECONDS, FALLBACK_GEMINI_API_KEY,
    MAX_WORDS_PER_SONG,
)

from services.job_manager import job_manager, Job
from services.vocab_service import extract_word_pairs
from services.lyrics_service import generate_lyrics
from services.music_service import generate_music


# ─── 定期クリーンアップタスク ─────────────────────────
async def cleanup_loop():
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


# ─── 楽曲生成パイプライン（SSE用）────────────────────
async def run_sing(job: Job, lyrics: str, api_key: str):
    """歌詞→楽曲生成を実行する"""
    try:
        await job.update("music", 20, "歌を作っています（少し時間がかかります）...")
        output_path = os.path.join(job.work_dir, f"{job.job_id}.mp3")
        await generate_music(lyrics, output_path, api_key)
        await job.update("music", 95, "歌が完成しました")

        download_url = f"/download/{job.job_id}"
        await job.complete(download_url, lyrics, [])

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[Main] Job {job.job_id} failed: {e}")
        await job.fail(str(e))


# ─── ヘルパー: ジョブ状態のスナップショット ───────────
def _job_snapshot(job: Job) -> dict:
    """
    現在のジョブ状態を SSE イベントと同じ形で返す。
    SSE 再接続時やポーリング復帰時に、取り逃したイベントを補うために使う。
    """
    if job.status == "completed":
        return {
            "step": "done",
            "progress": 100,
            "download_url": job.download_url,
            "lyrics": job.lyrics,
            "word_pairs": job.word_pairs,
        }
    if job.status == "failed":
        return {
            "step": "error",
            "progress": -1,
            "message": job.error or "処理中にエラーが発生しました",
        }
    return {
        "step": job.step,
        "progress": job.progress,
        "message": job.message,
    }


# ─── ヘルパー: APIキー解決 ────────────────────────────
def _resolve_api_key(api_key: str) -> str:
    effective = api_key.strip() or FALLBACK_GEMINI_API_KEY
    if not effective:
        raise HTTPException(
            status_code=400,
            detail="Gemini API キーを入力してください。",
        )
    return effective


# ─── エンドポイント ───────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "version": APP_VERSION, "ready": True}


@app.post("/extract")
async def extract(
    file: UploadFile = File(...),
    api_key: str = Form(""),
    mode: str = Form("word"),
):
    """画像から英単語／英文を抽出する"""
    effective_key = _resolve_api_key(api_key)

    if mode not in ("word", "sentence"):
        mode = "word"

    if not file.filename:
        raise HTTPException(status_code=400, detail="ファイルが選択されていません")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        allowed = ", ".join(ALLOWED_IMAGE_EXTENSIONS)
        raise HTTPException(
            status_code=400,
            detail=f"対応している画像形式は {allowed} です",
        )

    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE_BYTES:
        mb = MAX_IMAGE_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"ファイルサイズが{mb}MBを超えています",
        )

    # 一時ファイル保存
    job = job_manager.create_job()
    image_path = os.path.join(job.work_dir, f"input{ext}")
    with open(image_path, "wb") as f:
        f.write(content)

    word_pairs = await extract_word_pairs(image_path, effective_key, mode)

    return {
        "word_pairs": word_pairs,
        "mode": mode,
        "max_words_per_song": MAX_WORDS_PER_SONG,
    }



@app.post("/lyrics")
async def lyrics_endpoint(
    api_key: str = Form(""),
    mode: str = Form("word"),
    word_pairs_json: str = Form(...),
):
    """単語ペアから歌詞を生成する（何度でも呼べる）"""
    effective_key = _resolve_api_key(api_key)

    if mode not in ("word", "sentence"):
        mode = "word"

    try:
        word_pairs = json.loads(word_pairs_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="単語データが不正です")

    if not word_pairs:
        raise HTTPException(status_code=400, detail="単語が選択されていません")

    # 形式チェック（フロントで手動追加・編集できるため、空欄を弾く）
    cleaned = []
    for p in word_pairs:
        if not isinstance(p, dict):
            continue
        word = str(p.get("word") or "").strip()
        meaning = str(p.get("meaning") or "").strip()
        if word and meaning:
            cleaned.append({"word": word, "meaning": meaning})

    if not cleaned:
        raise HTTPException(status_code=400, detail="英単語と和訳の両方が入力された単語がありません")

    if len(cleaned) > MAX_WORDS_PER_SONG:
        raise HTTPException(
            status_code=400,
            detail=f"1曲に入れられるのは{MAX_WORDS_PER_SONG}語までです（現在{len(cleaned)}語）",
        )

    display_lyrics, pronunciation_lyrics = await generate_lyrics(
        cleaned, effective_key, mode
    )



@app.post("/sing")
async def sing(
    api_key: str = Form(""),
    lyrics: str = Form(...),
):
    """歌詞から楽曲を生成する（SSE で進捗配信）"""
    effective_key = _resolve_api_key(api_key)

    if not lyrics.strip():
        raise HTTPException(status_code=400, detail="歌詞がありません")

    job = job_manager.create_job()
    job.meta = {
        "lyrics": lyrics.strip(),
        "api_key": effective_key,
    }

    return {
        "job_id": job.job_id,
        "status": "accepted",
    }


@app.get("/progress/{job_id}")
async def progress(job_id: str):
    """SSE で進捗を配信する"""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")

    async def event_stream():
        meta = getattr(job, "meta", None)
        if meta and job.status == "pending":
            job.status = "processing"
            asyncio.create_task(
                run_sing(job, meta["lyrics"], meta["api_key"])
            )

        # 接続直後に現在の状態を必ず1件送る。
        # これにより、切断後の再接続でも取り逃した完了・失敗を回収できる。
        snapshot = _job_snapshot(job)
        yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
        if snapshot.get("step") in ("done", "error"):
            return

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


@app.get("/result/{job_id}")
async def result(job_id: str):
    """
    ジョブの現在状態をポーリングで取得する。
    SSE が切断された場合のフォールバック経路。
    """
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail="ジョブが見つかりません。有効期限が切れた可能性があります。",
        )

    snapshot = _job_snapshot(job)
    snapshot["job_id"] = job.job_id
    snapshot["status"] = job.status
    return snapshot


@app.get("/download/{job_id}")
async def download(job_id: str):
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


# ─── フロントエンド静的ファイル配信 ───────────────────
FRONTEND_OUT = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "out"
if FRONTEND_OUT.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_OUT), html=True), name="frontend")
    print(f"[Main] Frontend mounted from: {FRONTEND_OUT}")
else:
    print(f"[Main] Frontend not found at: {FRONTEND_OUT}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    print(f"[Main] Starting utango on port {port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
