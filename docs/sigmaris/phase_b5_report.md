# Phase B5 実施報告: 記憶の鮮度・矛盾ダッシュボード(Phase B群 最終機能)

対象ブランチ: `phase-b5-memory-dashboard`(mainからfork)

**このタスクの完了をもって、Phase B(全17機能: B1〜B17)が正式に完了した。**
完了サマリーは別途`docs/sigmaris/phase_b_summary.md`にまとめた。

---

## 0. 本タスクの位置づけ(経緯の補足)

`docs/sigmaris/phase_b9_report.md`の振り返りで報告した通り、本タスクはB1〜B17
の実行順序に一度も含まれていなかったことが判明していた。今回、改めて依頼を受け
着手した。B5はPhase B群で唯一フロントエンドに関わるタスクであり、これまでのB
群タスク(バックエンドの記憶ロジック中心)とは性質が異なる。

---

## 1. 表示項目の実装詳細

### 表示する情報と、それぞれの出所

| 表示項目 | 出所 | 備考 |
|---|---|---|
| カテゴリ・キー・値 | `user_fact_items.category/key/value` | 既存カラム |
| 確信度 | `user_fact_items.confidence` | Phase B(元々存在)、`validate_all_facts()`の減衰・矛盾検出で更新される |
| 重要度 | `user_fact_items.importance_score` | Phase B17 |
| 矛盾フラグ | `user_fact_items.is_stale` | `memory_validator.validate_all_facts()`の矛盾検出フェーズでtrueになる(2章で詳述) |
| 採用回数 | `user_fact_items.adoption_count` | Phase B13 |
| 出所(会話) | `user_fact_items.thread_id` | Phase B4(insert時のみ設定される、fact単位の出所) |
| 作成・最終更新日時 | `user_fact_items.created_at`/`updated_at` | 既存カラム |

### 「確認履歴(いつ最後に確認されたか)」の扱いについて(判断根拠)

指示書は「B3で追加された確認履歴の状況」の表示を求めていたが、調査の結果、
**B3(`active_inquiry.py`)の保留中確認状態はプロセス内の辞書
(`_pending_confirmations`)のみで管理されており、Postgresには一切永続化され
ていない**ことを確認した。DBに残る最も近い痕跡は、`user_fact_history`テーブル
の変更ログ(Phase B3.5で`thread_id`/`invocation_id`が追加済み)のみである。

本タスクでは、専用の確認履歴テーブルを新設することは指示書の「過剰実装を避け
る」「複雑な視覚化は必須ではない」という優先方針に反すると判断し、**行わなか
った**。代わりに、`user_fact_items.updated_at`を「最終更新(再主張・矛盾調整
を含む)」の代理指標として表示し、画面上にその旨を明記した(「明示的な確認履
歴専用のテーブルが存在しないため...代理指標として使用しています」という説明
文をダッシュボード本文に直接記載)。根拠: `upsert_fact_item()`のUPDATE分岐は、
事実が再主張されるたびに`is_stale`をfalseにクリアし`updated_at`を更新するた
め(Phase B3.5で追加された挙動)、`updated_at`は「最後に触れられた/再確認され
た」ことの妥当な近似値になる。

### 矛盾検出の実際の仕組み(`memory_validator.py`確認結果)

`validate_all_facts()`(週次バッチ、`memory_validator.py`)は、直近7日間の
`user_fact_history`の変更を読み取り、LLMによる矛盾判定(`_check_contradiction`
、1回の実行あたり最大5件の予算制限あり)を行い、「矛盾あり」と判定された事実の
`confidence`を0.7倍(下限0.1)に減衰させると同時に**`is_stale = True`**を設定
する。この処理結果を集計した`{"decayed", "contradictions", "logically_deleted",
"physically_deleted", "errors"}`という要約は**永続化されずレスポンス限りの値**
であるため、ダッシュボードでは「実行結果のサマリー」ではなく「現在時点での
`user_fact_items`のスナップショット」を表示する設計にした(矛盾のあった具体的
な新旧値のペアまでは遡れないが、`is_stale`フラグと減衰後の`confidence`は確認で
きる)。

---

## 2. 画面構成・配置場所

### ルーティング

`frontend/src/app/admin/memory/page.tsx`として実装した(指示書が例示した
`/admin/memory`という命名をそのまま採用)。既存のメイン画面用ナビゲーション
(`app-shell.tsx`の`navIconByPath`)には**意図的に追加していない**(判断根拠):
本ダッシュボードは開発者(海星さん)専用の管理画面であり、一般利用の`/chat`導
線と混同させないという指示書の注意事項に従い、直接URLでのみアクセスする隠しペ
ージとした。既存の`/memory`ページ(一般利用者向けの記憶閲覧画面)とは完全に別
ルートであり、コンポーネントも共有していない。

### 画面構成

- `AppShell`(既存の共通レイアウト、`/memory`や`/settings`と同じラッパー)でト
  ーン・パーソナリティを排した実用画面として構成(バッジを"Admin"表示、
  persona.mdの言い回しやシグマリスの人格は一切使用していない)。
- 本体は単一のテーブル(`MemoryDashboardTable`、新規クライアントコンポーネン
  ト)。複雑なグラフ・チャートは実装していない(指示書の明示的な優先方針に従
  う)。
- フィルタ: 「矛盾フラグ(is_stale)のみ表示」チェックボックス。
- ソート: カテゴリ・確信度・重要度・最終更新の4列でクリックソート可能(昇順/降
  順トグル)。
- 矛盾フラグの立った行は赤系の背景色で視覚的に強調。
- フィルタ・ソートは**クライアント側完結**とした(判断根拠): 単一ユーザー向け
  システムであり事実件数は少量であるため、サーバーへの再フェッチなしにブラウザ
  内でのフィルタ・ソートで十分実用的と判断した。追加のAPI呼び出しは発生しない。

---

## 3. バックエンドAPIの実装詳細

### 新規エンドポイント

`GET /api/app/memory-dashboard`(`backend/app/routes/app_data.py`)を追加した。
既存の`app_data.py`の慣習(`_require_jwt()`によるBearerトークンのみのチェッ
ク、`routes/agent.py`のようなエージェント秘密鍵検証は行わない)にそのまま従っ
た(判断根拠: 指示書が「既存のapp_data.py・app_chat_data.py等のパターンに沿っ
た実装にすること」と明示していたため)。レスポンス封筒は既存の慣習
(`{"ok": true, "items": [...], "count": N}`)に合わせた。

```python
@router.get("/memory-dashboard")
async def memory_dashboard(authorization: str | None = Header(default=None)):
    jwt = _require_jwt(authorization)
    items = await get_memory_dashboard_items(jwt)
    return {"ok": True, "items": items, "count": len(items)}
```

### サービス関数

`backend/app/services/user_fact_data.py`に`get_memory_dashboard_items(jwt)`を
新設した(既存の`get_fact_items()`を再利用せず、専用のSELECT列リストを定義し
た判断根拠: `get_fact_items()`は`select=*`のため`embedding vector(768)`と生成
列`search_text`まで取得してしまい、ダッシュボード用途には無駄に重い。専用関数
で必要な列のみを明示的に選択した)。

```python
_DASHBOARD_SELECT = (
    "id,category,key,value,confidence,importance_score,is_stale,"
    "adoption_count,source,thread_id,invocation_id,source_experience_ids,"
    "created_at,updated_at"
)

async def get_memory_dashboard_items(jwt: str) -> list[dict[str, Any]]:
    params = {
        "select": _DASHBOARD_SELECT,
        "is_deleted": "eq.false",
        "order": "updated_at.asc",
    }
    result = await rest_select(jwt, "user_fact_items", params)
    return result if isinstance(result, list) else []
```

- `is_deleted=eq.false`のみサーバー側フィルタとして適用し、`is_stale`(矛盾フ
  ラグ)は意図的に除外していない(矛盾フラグの表示こそがこの機能の目的のた
  め)。
- デフォルトの並び順は`updated_at`昇順(最も長く更新されていない=レビューが
  必要な可能性が高いものを先頭に表示)。

### マイグレーション

**新規マイグレーションは不要**と判断した。表示に必要な列(`is_stale`・
`importance_score`・`adoption_count`・`thread_id`・`confidence`等)はすべて既
存の`user_fact_items`テーブルに既に存在する(B1・B4・B13・B17等で追加済み)。
新規テーブル・新規カラムの追加は行っていない。

### 応答経路(`/chat`)への影響について

`backend/app/services/orchestrator/service.py`・`local_llm.py`・
`multihop_search.py`・`memory_search.py`・`memory_confidence.py`等、`/chat`の
応答生成に関わる全ファイルへの変更差分がゼロであることを`git diff --stat
main`で確認した。本タスクは`routes/app_data.py`・`services/app_data.py`・
`services/user_fact_data.py`という読み取り専用の周辺ファイルのみを変更してお
り、応答経路には一切触れていない。

---

## 4. テスト結果

### バックエンド(mock、5ケース、スクラッチテスト)

- `get_memory_dashboard_items()`が正しい列リスト・`is_deleted`フィルタ・
  `updated_at`昇順を指定してクエリすること
- `embedding`/`search_text`が選択列に含まれないこと
- レスポンスがリストでない場合に空リストを返すこと
- `is_stale`な事実がサーバー側フィルタで除外されず結果に含まれること
- ルートがBearerトークンなしで401を返すこと
- ルートが`{"ok": true, "items": [...], "count": N}`の封筒を返すこと

```
5 passed (新規)
```

### 既存機能への非破壊確認

これまでのB群スクラッチテスト・facts cache修正テストを合わせた既存テスト群を
再実行し、全て成功することを確認した。

```
190 passed (スクラッチテスト全体、新規5件含む)
8 passed (backend/tests/、既存の安定回帰スイート)
```

### フロントエンド検証

実ブラウザでの操作確認は本セッションの環境制約(サーバー・実APIアクセスな
し)により行えなかったが、以下の静的検証を実施した:

```
npx tsc --noEmit -p tsconfig.json   → exit code 0(型エラーなし)
npx eslint <新規2ファイル>           → exit code 0(lintエラーなし)
```

Tailwind CSS v4を使用しているため、`line-clamp-3`ユーティリティは追加プラグ
インなしでビルトインで利用可能であることを`package.json`で確認済み。

**制約の明記**: 実際のブラウザでの表示確認・実データでのフィルタ/ソート動作
確認は行えていない。運用者側での実機確認を推奨する。

---

## 5. Phase B全体(B1〜B17、全機能)を通じての最終的な振り返り

詳細な技術的教訓・パイプライン重複の懸念・マイグレーション適用状況について
は、`docs/sigmaris/phase_b9_report.md`5章で既に詳しく報告済みである。ここでは
B5(最後の1機能)を経て追加・更新された点のみをまとめ、全体の最終振り返りは
`docs/sigmaris/phase_b_summary.md`に集約した。

### B5固有の追加所見

1. **フロントエンドタスクは、バックエンドB群タスクと検証の質が異なる**: B1〜
   B4・B6〜B17は全てmock/単体テストで検証できたが、B5は実際の画面表示・操作感
   はブラウザでの確認が必須であり、静的検証(型検査・lint)だけでは「意図通り
   に表示されるか」までは確認できない。この種のギャップは今後フロントエンドタ
   スクが増える場合、B群の標準的な検証プロセス(mock単体テストで十分)をその
   まま適用できないことを意味する。
2. **「確認履歴」のように、指示書が前提とする永続化状態が実際には存在しないケ
   ースがある**: B3の確認状態がプロセス内メモリのみで管理されていたことは、
   B3実装当時の報告書には明記されていたが、B5の指示書作成時点ではこの制約が反
   映されていなかった。今後、複数フェーズにまたがる前提を含むタスクを指示する
   際は、対象データの永続化状況を都度確認する必要がある。
3. **B9の振り返りで指摘したB5スコープ抜けの再発防止**: 今回B5を実施したことで
   Phase Bの17機能全てが完了した。今後Phase C以降で同様の「ロードマップに存在
   するが実行順序に含まれない」機能が発生しないよう、フェーズ完了報告のたびに
   ロードマップとの突き合わせを行うことを推奨する。

---

## Related Documents

- `docs/sigmaris/sigmaris_roadmap.md`
- `docs/sigmaris/phase_b9_report.md`(B5のスコープ抜けが判明した報告書、5パイ
  プライン重複・未適用マイグレーション等の詳細な懸念事項はこちらに集約)
- `docs/sigmaris/phase_b3_report.md`(確認状態がプロセス内メモリのみで管理さ
  れている根拠)
- `docs/sigmaris/phase_b17_report.md`(`importance_score`の実装、本ダッシュボ
  ードの表示項目のひとつ)
- `docs/sigmaris/phase_a0_report.md`(`app_data.py`のルーティング・認証慣習の
  出典)
- `docs/sigmaris/phase_b_summary.md`(Phase B全体の完了サマリー、本報告書と合
  わせて作成)
