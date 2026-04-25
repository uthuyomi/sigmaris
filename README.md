# ShiftPilotAI

ShiftPilotAI は、チャットを起点に日々の予定を構築し、移動時間や外部サービス連携まで含めて「現実的に間に合うスケジュール」を自動生成する予定調整アプリです。

ユーザーはイベントを個別に入力するのではなく、やりたいことや目的を自然言語で伝えるだけで、生活全体を逆算したスケジュールを構築できます。

---

## ✨ 主な機能

* チャットベースでの予定作成（自然言語入力）
* テキスト・画像・スプレッドシートからの予定抽出
* 移動時間の自動計算（車 / 自転車 / 徒歩 / 公共交通）
* Google カレンダー連携
* タイムラインベースのスケジュール管理
* バックエンド主導のAI処理（解析・API連携・統合制御）

---

## 🏗 アーキテクチャ

本プロジェクトは責務分離を前提に、フロントエンドとバックエンドを分離した構成になっています。

```
ShiftPilotAI/
├── frontend/   # UI / ユーザー操作
├── backend/    # AI処理 / 外部連携
├── supabase/   # DB / マイグレーション
├── docs/       # 設計・意思決定・ログ
```

### フロントエンド

* Next.js
* TypeScript
* Tailwind CSS
* assistant-ui

役割：

* UI描画
* チャットインターフェース
* 認証トークンの橋渡し（Supabase / Google）

### バックエンド

* FastAPI
* Python

役割：

* AI処理
* 外部API連携（Google API / 移動計算など）
* データ統合・オーケストレーション

---

## 🚀 セットアップ

### フロントエンド

```bash
cd frontend
npm install
npm run dev
```

主なコマンド：

* `npm run dev` : 開発サーバー起動
* `npm run build` : 本番ビルド
* `npm run lint` : Lint実行

---

### バックエンド

```bash
cd backend
python -m pip install -e .
python -m uvicorn app.main:app --reload --port 8000
```

---

## 🔌 API エンドポイント

現在利用可能なAPI：

* `GET /health`
* `GET /api/health`
* `POST /api/mobility/plan`
* `POST /api/import/preview`

---

## 🔐 環境変数

### フロントエンド（frontend/.env.local）

```
BACKEND_API_BASE_URL=http://localhost:8000
```

### バックエンド（backend/.env）

外部サービス連携に応じて設定予定

---

## 📄 ドキュメント

詳細な設計・判断ログは `docs/` ディレクトリにまとめています。

* project-overview.md
* design/
* decisions/
* operations/

---

## 🧠 設計思想

ShiftPilotAI は次の考え方をベースに設計されています。

> 「予定を入力する」のではなく「間に合うように生活を構築する」

単なるカレンダー入力ツールではなく、移動・余裕時間・現実的な制約まで含めてスケジュールを構成することを目的としています。

---

## 📌 開発状況

* 基本アーキテクチャ：実装済み
* バックエンドAPI：一部実装済み
* チャット統合：開発中
* Google連携：一部実装済み

---

## 👤 Author

Kaisei Yasuzaki
Frontend Engineer / AI Application Developer
