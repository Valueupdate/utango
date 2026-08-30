# Slide2Video 運用手順書

## デプロイフロー

### 基本方針
- **必ずローカルで動作確認してから VPS に反映する**
- `npm run dev` でローカル確認 → `git push` → VPS で反映

### ローカル動作確認手順

```bash
# バックエンド起動
cd backend
venv\Scripts\activate
python -m uvicorn main:app --reload --port 8000

# フロントエンド起動（別ターミナル）
cd frontend
npm run dev
# http://localhost:3000 で確認
```

### VPS 反映手順

```bash
cd /opt/slide2video
git pull
cd frontend
npm run build
cd ..
sudo systemctl restart slide2video
sudo systemctl restart nginx
```

### 動作確認

```bash
# サービス状態確認
sudo systemctl status slide2video
sudo systemctl status nginx

# ログ確認
journalctl -u slide2video -f
```

---

## VPS 情報

- **サーバー**: ConoHa VPS
- **OS**: Ubuntu
- **IP**: 133.88.121.90
- **アプリディレクトリ**: `/opt/slide2video`

## ドメイン

| ドメイン | SSL | DNS |
|---------|-----|-----|
| slide2video.valueupdate.jp | ✅ | ✅ |
| slide2video.valueupdate.co.jp | ✅ | ✅ |
| slide2video.valueupdate.net | ❌ | ❌ 未設定 |

---

## トラブルシューティング

### 502 Bad Gateway
```bash
sudo systemctl restart slide2video
sudo systemctl restart nginx
```

### git push 後に反映されない
```bash
cd /opt/slide2video
git pull
cd frontend
npm run build
sudo systemctl restart slide2video
```

### git を特定コミットに戻したい
```bash
# ローカル・VPS 両方で実行
git reset --hard <コミットID>

# GitHub にも反映（注意：強制上書き）
git push origin main --force
```

---

## 環境変数

### backend/.env（VPS）
```env
DEBUG=False
PORT=8000
FRONTEND_URL=https://slide2video.valueupdate.jp
EXTRA_CORS_ORIGINS=https://slide2video.valueupdate.jp,https://slide2video.valueupdate.co.jp,https://slide2video.valueupdate.net
```

### frontend/.env.local（VPS・git管理外）
```env
NEXT_PUBLIC_GA_ID=G-SXC5C128QH
```
```
