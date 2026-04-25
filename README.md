# ShiftPilotAI

ShiftPilotAI は、チャット起点で予定を組み、カレンダー、タイムライン、Google 連携まで扱う予定調整アプリだよ。  
いまは責務分離のため、`frontend/` に Next.js、`backend/` に FastAPI を置く構成へ切り替えてある。

## 構成
- `frontend/`: Next.js / TypeScript / Tailwind / assistant-ui
- `backend/`: FastAPI / Python API 土台
- `supabase/`: migration と DB 関連
- `docs/`: 設計、判断、作業ログ

## フロントエンド
```powershell
cd frontend
npm run dev
```

よく使うコマンド:
- `npm run dev`
- `npm run lint`
- `npm run build`

## バックエンド
```powershell
cd backend
python -m pip install -e .
python -m uvicorn app.main:app --reload --port 8000
```

バックエンドは今、次を受ける。
- `/health`
- `/api/health`
- `/api/mobility/plan`
- `/api/import/preview`

frontend の `mobility` と `import preview` は、この backend を使う形に切り替えてある。
さらに chat の中でも、画像解析と公共交通候補探索は backend を使う形に寄せてある。
加えて chat の `Google Calendar` と `Google Sheets` の実 API 呼び出しも backend に寄せてある。frontend は provider token を持って backend へ渡す薄い層になってきている。
さらに chat の app-side データとして、イベント検索、ホーム文脈取得、スレッド存在確認、メッセージ保存も backend に寄せてある。frontend は Supabase JWT と Google provider token の橋渡しを行う。

## 環境変数
- Next.js 用の `.env.local` は `frontend/.env.local`
- Python 用の `.env` は今後 `backend/.env` を置く想定
- `frontend/.env.local` では `BACKEND_API_BASE_URL` を使うと、フロントから叩く backend の URL を固定できる

## ドキュメント
- [docs/README.md](/d:/souce/ShiftPilotAI/docs/README.md)
- [docs/project-overview.md](/d:/souce/ShiftPilotAI/docs/project-overview.md)
- [docs/design/README.md](/d:/souce/ShiftPilotAI/docs/design/README.md)
- [docs/decisions/README.md](/d:/souce/ShiftPilotAI/docs/decisions/README.md)
- [docs/operations/README.md](/d:/souce/ShiftPilotAI/docs/operations/README.md)
