# utango - 環境構築・起動ガイド

英単語帳を撮影すると暗記ソングを自動生成する PoC の、ローカル起動手順です。

---

## 前提条件

| ツール | バージョン | 用途 |
|--------|-----------|------|
| Python | 3.10 以上 | バックエンド実行 |
| Node.js | 18 以上 | フロントエンド実行 |
| Git | 最新版 | バージョン管理 |
| Gemini API キー | — | 単語抽出・歌詞生成・楽曲生成（運営者が保持） |

### Gemini API キーについて（重要）

utango は「サーバー集約方式」を採用しています。中高生は API キーの取得や課金が
できないため、**運営者（あなた）の Gemini API キーをサーバー側に設定**し、
ユーザーはキー入力なしで使えるようにします。

このキーで以下のすべてを呼び出します。
- 単語抽出（Gemini Vision）
- 歌詞生成（Gemini）
- 楽曲生成（Lyria 3 Pro）

楽曲生成（Lyria 3 Pro）は従量課金モデルのため、API キーに対して
課金（Pay per request）の有効化が必要です。AI Studio / Google Cloud で
請求が有効なプロジェクトのキーを使用してください。

> ⚠️ Lyria 3 は preview 段階のモデルです。モデルID（`lyria-3-pro-preview`）や
> レスポンス仕様が変更される可能性があります。動作しない場合は
> `backend/config.py` の `LYRIA_MODEL` と
> `backend/services/music_service.py` のレスポンス解析を確認してください。

---

## 1. リポジトリの取得

    git clone <リポジトリURL>
    cd utango

---

## 2. バックエンドのセットアップ

### 2-1. 仮想環境の作成と依存インストール

    cd backend
    python -m venv venv

    # Windows
    venv\Scripts\activate
    # macOS / Linux
    source venv/bin/activate

    pip install -r requirements.txt

### 2-2. 環境変数の設定

`backend/.env` を作成し、運営者の Gemini API キーを設定します。

    GEMINI_API_KEY=ここにあなたのGeminiAPIキー
    DEBUG=true
    PORT=8000
    FRONTEND_URL=http://localhost:3000

> `.env` は `.gitignore` 対象です。API キーを Git にコミットしないでください。

### 2-3. バックエンドの起動

    python -m uvicorn main:app --reload --port 8000

起動確認:

    curl http://localhost:8000/health

以下のように `ready: true` が返れば、キーが認識されています。

    {"status": "ok", "version": "0.1.0", "ready": true}

`ready: false` の場合は `.env` の `GEMINI_API_KEY` を確認してください。

---

## 3. フロントエンドのセットアップ

### 3-1. 依存インストール

新しいターミナルを開いて:

    cd frontend
    npm install

### 3-2. 環境変数の設定

`frontend/.env.local` を作成します。

    NEXT_PUBLIC_API_URL=http://localhost:8000

### 3-3. 開発サーバーの起動

    npm run dev

ブラウザで http://localhost:3000 を開くと utango の画面が表示されます。

---

## 4. 動作確認（一本道フロー）

1. ブラウザで http://localhost:3000 を開く
2. 「カメラで撮影」または「画像を選ぶ」で英単語帳の画像を読み込む
   - PCの場合は「画像を選ぶ」で、英単語と和訳が並んだ画像を選択
3. 「🎶 暗記ソングを作る」を押す
4. 進捗が「単語を読み取る → 歌詞を作る → 歌を作る」と進む
5. 完成後、プレイヤーで再生し、単語リスト・歌詞タブを確認

> 楽曲生成（Lyria 3 Pro）は数十秒〜数分かかることがあります。
> 進捗バーが「歌を作っています...」で止まって見えても処理中です。

---

## 5. スマホ実機での確認

PoC はスマホ撮影を主用途に想定しています。同一ネットワーク内のスマホから
確認する場合は、以下のようにホストを指定して起動します。

バックエンド:

    python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

フロントエンド `frontend/.env.local` を PC の LAN IP に変更:

    NEXT_PUBLIC_API_URL=http://<PCのLAN_IP>:8000

フロントエンドを `--hostname` 指定で起動:

    npm run dev -- --hostname 0.0.0.0

スマホのブラウザで `http://<PCのLAN_IP>:3000` を開きます。

> カメラ撮影機能（`capture` 属性）はスマホのブラウザで有効になります。
> 一部ブラウザは `http://` ではカメラを制限するため、その場合は
> ngrok 等で https 化するか、「画像を選ぶ」で代用してください。

---

## 6. 本番ビルド（静的エクスポート + バックエンド配信）

フロントエンドを静的エクスポートし、バックエンドから配信する構成です。
（Slide2Video と同じ方式）

    cd frontend
    npm run build

`frontend/out/` が生成され、バックエンド起動時に `/` で自動配信されます。
この場合 `NEXT_PUBLIC_API_URL` は空（同一オリジン）で動作します。

    cd backend
    python -m uvicorn main:app --port 8000

http://localhost:8000 で、フロント・API が同一オリジンで動きます。

---

## トラブルシューティング

### `ready: false` が返る
`backend/.env` の `GEMINI_API_KEY` が未設定か、読み込まれていません。
`.env` の場所（`backend/` 直下）と、サーバー再起動を確認してください。

### 楽曲生成でエラーになる
- Lyria 3 Pro は課金（Pay per request）が有効なキーが必要です。
- preview のためモデルIDが変わっている可能性があります。
  `backend/config.py` の `LYRIA_MODEL` を最新のモデルIDに更新してください。
- レスポンス形式が変わっている場合は
  `backend/services/music_service.py` の `inline_data` 解析部分を確認してください。

### 単語が抽出されない
- 英単語と和訳がはっきり写った、明るく鮮明な画像を使ってください。
- 手書きや極端に小さい文字は読み取り精度が下がります。

### スマホでカメラが起動しない
`http://` 接続ではブラウザがカメラを制限する場合があります。
ngrok などで https 化するか、「画像を選ぶ」を使ってください。

### ポートが使用中
別ポートで起動し、`frontend/.env.local` の `NEXT_PUBLIC_API_URL` も合わせて変更します。

    python -m uvicorn main:app --reload --port 8001
