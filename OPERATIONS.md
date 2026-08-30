# utango（うたんご）運用手順書

## サービス概要

- **サービス名**: utango（うたんご）
- **公開URL**: https://utango.valueupdate.net
- **構成**: Slide2Video と同一 VPS に相乗り（ポートを分けて共存）
- **姉妹サービス**: Slide2Video（`/opt/slide2video`, ポート 8000）

---

## デプロイフロー

### 基本方針
- **必ずローカルで動作確認してから VPS に反映する**
- `npm run dev` でローカル確認 → `git push` → VPS で反映
- Slide2Video とポートが衝突しないよう、utango は **ポート 8001** を使う

### ローカル動作確認手順

```bash
# バックエンド起動（ローカルは 8000 でよい）
cd backend
venv\Scripts\activate
python -m uvicorn main:app --reload --port 8000

# フロントエンド起動（別ターミナル）
cd frontend
npm run dev
# http://localhost:3000 で確認

VPS 反映手順
Copycd /opt/utango
git pull
cd frontend
npm run build
cd ..
sudo systemctl restart utango
sudo systemctl restart nginx
動作確認
Copy# サービス状態確認
sudo systemctl status utango
sudo systemctl status nginx

# バックエンドの死活確認（ポート 8001）
curl http://localhost:8001/health
# 期待値: {"status":"ok","ready":true} 等

# ログ確認
journalctl -u utango -f
VPS 情報
サーバー: ConoHa VPS（Slide2Video と同一）
OS: Ubuntu
IP: 133.88.121.90
アプリディレクトリ: /opt/utango
使用ポート: 8001（Slide2Video は 8000）
ドメイン
ドメイン	SSL	DNS
utango.valueupdate.net	⬜ 未設定（構築時に取得）	⬜ 未設定（構築時に設定）
DNS: utango.valueupdate.net の A レコードを 133.88.121.90 に向ける。 SSL: sudo certbot --nginx -d utango.valueupdate.net で取得する。

初回セットアップ手順（構築時のみ）
1. コード配置
Copycd /opt
sudo git clone <utango リポジトリURL> utango
cd utango
2. バックエンド準備
Copycd /opt/utango/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
3. フロントエンド準備
Copycd /opt/utango/frontend
npm install
npm run build
4. systemd サービス登録
/etc/systemd/system/utango.service を作成（詳細は「systemd 設定」参照）。

Copysudo systemctl daemon-reload
sudo systemctl enable utango
sudo systemctl start utango
5. Nginx 設定
/etc/nginx/sites-available/utango を作成し、有効化する。

Copysudo ln -s /etc/nginx/sites-available/utango /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
6. SSL 取得
Copysudo certbot --nginx -d utango.valueupdate.net
systemd 設定
/etc/systemd/system/utango.service

Copy[Unit]
Description=utango backend (FastAPI)
After=network.target

[Service]
User=root
WorkingDirectory=/opt/utango/backend
ExecStart=/opt/utango/backend/venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8001
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
ポートは 8001。Slide2Video（8000）と衝突しないこと。

Nginx 設定（雛形）
/etc/nginx/sites-available/utango

Copyserver {
    listen 80;
    server_name utango.valueupdate.net;

    # フロントエンド（静的エクスポート物 or Next 起動先）
    # 構成に合わせて root もしくは proxy_pass を調整する
    location / {
        root /opt/utango/frontend/out;
        try_files $uri $uri/ /index.html;
    }

    # バックエンド API（ポート 8001）
    location /generate {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    location /progress/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_buffering off;           # SSE のためバッファリング無効
        proxy_read_timeout 3600s;      # 楽曲生成の待ち時間に耐える
    }
    location /download/ {
        proxy_pass http://127.0.0.1:8001;
    }
    location /result/ {
        proxy_pass http://127.0.0.1:8001;
    }
    location /health {
        proxy_pass http://127.0.0.1:8001;
    }
}
Copy
⚠️ この Nginx 設定は雛形です。実際は Slide2Video で稼働中の設定を複製し、 ドメイン名（utango.valueupdate.net）とポート（8001）を書き換えて作るのが確実。 /progress/ の SSE は proxy_buffering off と長めの proxy_read_timeout が必須。

環境変数
backend/.env（VPS）
CopyDEBUG=False
PORT=8001
FRONTEND_URL=https://utango.valueupdate.net
EXTRA_CORS_ORIGINS=https://utango.valueupdate.net
# Gemini API キー（サーバー集約方式：運営者が保持）
# Lyria 3 Pro 利用のため、課金（Billing）有効化済みのキーであること
GEMINI_API_KEY=（本番用キーを設定）
frontend/.env.local（VPS・git管理外）
CopyNEXT_PUBLIC_API_URL=https://utango.valueupdate.net
⚠️ ローカル開発時は NEXT_PUBLIC_API_URL=http://localhost:8000、 本番は上記のとおり公開URLに変更する。ビルド時に埋め込まれるため、 値を変えたら npm run build をやり直すこと。

トラブルシューティング
502 Bad Gateway
Copysudo systemctl restart utango
sudo systemctl restart nginx
# バックエンドが 8001 で起動しているか確認
curl http://localhost:8001/health
楽曲生成でエラー（429 RESOURCE_EXHAUSTED）
Gemini API キーの課金（Billing）が有効か確認する。
Lyria 3 Pro は無料枠が無いため、課金未有効だと 429 になる。
楽曲生成でエラー（503 UNAVAILABLE）
Google 側の一時的な高負荷。サーバー側で自動リトライ（最大5回）する実装済み。
それでも続く場合は時間をおいて再実行。
進捗（SSE）が途中で切れる
Nginx の /progress/ で proxy_buffering off と proxy_read_timeout が十分長いか確認する。
git push 後に反映されない
Copycd /opt/utango
git pull
cd frontend
npm run build
sudo systemctl restart utango
ポート衝突（Slide2Video と競合）
utango は 8001、Slide2Video は 8000。
sudo lsof -i :8001 で使用プロセスを確認できる。
Slide2Video との共存メモ
項目	Slide2Video	utango
ディレクトリ	/opt/slide2video	/opt/utango
ポート	8000	8001
systemd	slide2video	utango
Nginx	slide2video	utango
ドメイン	slide2video.valueupdate.*	utango.valueupdate.net
Nginx / Certbot / VPS は共用。どちらかの作業が他方に影響しないよう、 設定ファイルは必ず別名で管理する。
