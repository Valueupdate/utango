"""
utango バックエンド設定の一元管理モジュール
"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)

# ─── バージョン ─────────────────────────────────────
APP_VERSION = "0.1.1"

# ─── ディレクトリ設定 ───────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# ─── サーバー設定 ────────────────────────────────────
DEBUG = os.getenv("DEBUG", "True").lower() == "true"
PORT = int(os.getenv("PORT", "8000"))

# ─── フロントエンドURL（CORS用）─────────────────────
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
EXTRA_CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("EXTRA_CORS_ORIGINS", "").split(",")
    if origin.strip()
]

# ─── ファイル制限 ────────────────────────────────────
MAX_IMAGE_SIZE_MB = 20
MAX_IMAGE_SIZE_BYTES = MAX_IMAGE_SIZE_MB * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".heic")

# ─── ジョブ設定 ──────────────────────────────────────
JOB_EXPIRY_MINUTES = 30
JOB_CLEANUP_INTERVAL_SECONDS = 60

# ─── API キー方式 ────────────────────────────────────
# 【動作確認フェーズ限定】BYOK（Bring Your Own Key）方式。
# ユーザーが自分の Gemini API キーを入力し、リクエストごとに送信する。
# サーバーにはキーを保持しない。
#
# 【本番方針】エンドユーザー（中高生）向けにはサーバー集約方式に戻す予定
# （REQUIREMENTS.md §3.3 参照）。その際は下記フォールバックの
# サーバーキーを使う運用に切り替える。
#
# 開発用フォールバック: 環境変数にキーがあれば、リクエストに
# キーが無い場合の予備として使う（無ければ空。BYOK運用では通常空）。
FALLBACK_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ─── AI モデル設定 ───────────────────────────────────
# 画像解析・歌詞生成に使う Gemini モデル
GEMINI_MODEL = "models/gemini-2.5-flash"
# 楽曲生成に使う Lyria 3 モデル（preview のため変更の可能性あり）
# LYRIA_MODEL = "lyria-3-pro-preview"
LYRIA_MODEL = "lyria-3-clip-preview"

# ─── 歌詞・楽曲設定 ──────────────────────────────────
# 1曲あたりの単語数上限（docs/design/lyrics-design.md §3 参照）
MAX_WORDS_PER_SONG = 5
# 楽曲生成プロンプトに前置する楽曲指示
MUSIC_STYLE_PROMPT = (
    "日本語と英語がまざったキャッチーなCMジングル。"
    "テレビCMのように耳に残る、明るくテンポの良い30秒の曲。"
    "日本語パートははっきりした発音で元気に歌い、"
    "英語パートは正しい英語の発音で歌うこと。"
)

# ─── TTS（読み上げ）設定 ─────────────────────────────
TTS_MODEL = "gemini-2.5-flash-preview-tts"
TTS_VOICE = "Kore"    # 日本語対応の明るい声

# TTS 用の読み上げプロンプト（歌詞の前に付加される）
TTS_STYLE_PROMPT = (
    "あなたはテレビCMのナレーターです。"
    "以下の暗記ジングルの歌詞を、CMのように元気いっぱい、"
    "テンション高く、リズミカルに読み上げてください。"
    "ダジャレの部分は特に大げさに、笑えるくらいふざけて読んでください。"
    "英単語の部分は正しい英語の発音で、はっきり発音してください。\n\n"
)
