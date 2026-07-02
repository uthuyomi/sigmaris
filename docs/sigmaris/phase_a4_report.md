# Phase A4 実施報告: 同時書き込みの排他制御

**目的:** `replace_chat_messages()`の全削除→全INSERT方式が持つ、同時書き込み時のサイレントなデータ消失リスクを検知・防止する。
**作業ブランチ:** `phase-a4-write-concurrency`（Phase A0〜A3がマージ済みの`main`から新規作成）
**範囲:** Phase A5(RAGのLOCAL_LLM_ENABLED依存見直し)・Phase B(記憶拡張機能群)には着手していない。

---

## 0. 現状の再確認（着手前）

### `replace_chat_messages`呼び出し頻度の変化

Phase A0〜A3の変更を経て、この関数の呼ばれ方は当初(監査レポート執筆時点)から大きく変わっていた:

- **Phase A1以前**: orchestrator経由の呼び出しは`persist_thread: False`固定だったため、`chat_messages`への書き込みは`/api/chat/stream`直呼び経路（Phase A1-bの調査で判明した通り、実際にはナビゲーションからアクセス不可能だった旧`/chat`）でしか発生していなかった。
- **Phase A1**: orchestrator経由の永続化を有効化(`persist_thread: True`)。
- **Phase A1-b**: `/chat`(実際に使われる唯一のチャットUI)をorchestrator経由に切り替え。

結果として、**現在は`/chat`・WearOS・`/sigmaris`の全経路が、チャットターンのたびに必ず`replace_chat_messages`を呼ぶ**状態になっている（`chat.py::run_chat_completion`/`stream_chat_completion_ui`内の4箇所の呼び出し地点、いずれも`persist_messages=True`時に到達）。監査レポート執筆時点より同時書き込みリスクの実際の発生頻度・影響範囲は大きくなっていると判断した。

### 呼び出し箇所の洗い出し

`chat.py`内に4箇所（`run_chat_completion`の確認応答の早期リターンパス・メインパス、`stream_chat_completion_ui`の同じく2パス）。加えてPhase A0で追加した`POST /api/app/chat/messages/replace`（`routes/app_data.py`）が存在するが、こちらは**現在も呼び出し元がゼロ**（Phase A0で確認済み、`frontend/src/lib/chat-threads.ts::replaceChatMessages`に到達するコードパスが存在しない）。

---

## 1. 案1・案2どちらを選んだか、判断根拠

**案1（楽観ロック／CAS）を採用した。** 案2（差分アペンド方式への全面書き換え）は見送った。

### 案2を見送った理由

差分アペンド方式は「新規メッセージのみをINSERTする」という設計だが、これを正しく実装するには**クライアントから送られてくる`UIMessage.id`を安定した比較キーとして扱える**ことが前提になる。しかし、AI SDKの`useChat`が「アシスタントメッセージを再生成（regenerate）」する場合、既存のメッセージIDを保持したまま内容だけが更新されるケースがある。この場合、単純な「IDが未知のメッセージだけをINSERT」というロジックでは、**内容が変わったのに更新されない**という新種のバグを生む。この検証・対応まで含めると、今回のタスクの本来の目的（競合の検知・防止）に対して不釣り合いに大きい変更になると判断した。

### 案1を選んだ理由

- 指示書の「まずはエラーを返してクライアント側に委ねるシンプルな形を基本とし、必要以上に複雑な自動解決ロジックは作らない」という方針に最も忠実に沿う。
- 既存の`replace_chat_messages`の外部契約（全削除→全INSERT）を変えないため、影響範囲を「競合検知」だけに限定できる。
- PostgRESTの条件付きUPDATE（`WHERE`句にバージョン一致条件を含める）だけで実装でき、追加のロック機構やトランザクション制御が不要。

---

## 2. 実装内容・競合検知時の挙動

### スキーマ

```sql
-- supabase/migrations/202607050027_chat_threads_version.sql
alter table public.chat_threads
  add column if not exists version integer not null default 1;
```

### CASの仕組み

`chat_threads.version`を楽観ロックのトークンとして使う。`replace_chat_messages(jwt, *, thread_id, messages, expected_version=None)`は、`expected_version`が指定されている場合、まず`chat_threads`に対して**バージョン一致を条件とした`UPDATE`**（`title`・`updated_at`・`version+1`を同時にセット）を発行する。この`UPDATE`が0件しかヒットしなければ、他の書き込みが先に成功してバージョンが進んでいることを意味し、`ThreadVersionConflictError`を送出する。**このゲートを通過するまで`chat_messages`への削除・挿入は一切行われない**ため、負けたリクエストが勝ったリクエストのメッセージを破壊することは構造的に起こり得ない。

### 【重要】マイグレーション未適用でも安全に動作する設計（当初の実装ミスを自分で発見・修正した経緯）

実装の初期バージョンでは、`get_chat_thread()`のSELECT句に無条件で`version`を含め、`replace_chat_messages`のUPDATE文にも無条件で`version`列を書き込んでいた。**これは重大な設計ミスだった**: これまでのPhase(A1〜A3)で追加した列は「存在すれば使う、なければ無視される」新規機能だったのに対し、`get_chat_thread`は**チャット永続化のたびに必ず呼ばれる既存の中核関数**であり、マイグレーション未適用の状態でこのコードをデプロイすると、**新機能どころか既存のチャット永続化そのものが全滅する**（`column chat_threads.version does not exist`エラー）ことに、本番相当のSupabaseプロジェクトに対する検証中に気づいた（4章参照）。

この反省を踏まえ、以下の設計に修正した:

- `get_chat_thread()`のデフォルトSELECTは**変更していない**（`version`を含めない）。既存の全呼び出し元への影響をゼロにする。
- 新設の`get_chat_thread_version(jwt, thread_id) -> int | None`が、`version`列を個別に読み取る。この関数は**例外を握りつぶし、失敗時は常に`None`を返す**（マイグレーション未適用時はここで安全に失敗する）。
- `replace_chat_messages`は`expected_version`が`None`の場合、**`version`列をSELECT・UPDATEどちらでも一切参照しない**。これにより、マイグレーション未適用の状態でこのコードをデプロイしても、**Phase A4以前と完全に同一の挙動**になる（バイト単位で同じ処理パス）。
- `chat.py`は`get_chat_thread_version()`経由で`expected_version`を取得するため、マイグレーション適用前は常に`None`（CAS無効・従来通りの無条件上書き）、適用後は自動的に実際のバージョン番号が返るようになり、**コードの再デプロイなしにCAS保護が有効化される**。

### 競合検知時の挙動

**バックエンド（実際にライブトラフィックが通る`chat.py`の永続化パス）**: `_persist_chat_messages_safely()`という共通ヘルパーを新設し、4箇所の呼び出し地点全てに適用した。`ThreadVersionConflictError`を専用に`logger.warning`で記録するが、**チャット応答自体は失敗させない**。理由: この永続化はLLM応答が生成・ストリーミング済みの後に行われる副作用であり、ここで例外を上位に伝播させると、ユーザーには既に見えている（ストリーミング済みの）回答を持つリクエストが500エラーとして扱われてしまう。競合時にDBへの保存だけがスキップされても、次のターンで再度スレッドを読み直すため実害は限定的と判断した。

**なお、この作業と合わせて`run_chat_completion`の確認応答早期リターンパスに`if persist_messages:`のガードが欠落していた既存バグ（`persist_messages=False`でも無条件に永続化を試みていた）を発見し、修正した。** ちょうどこの同じコードブロックを触っていたため、放置するより直す方が適切と判断した。

**バックエンドREST APIエンドポイント（`POST /api/app/chat/messages/replace`、現状呼び出し元なし）**: `expectedVersion`を受け取り、`ThreadVersionConflictError`を**HTTP 409**にマッピングする。

**フロントエンド（`chat-threads.ts::replaceChatMessages`、同じく現状呼び出し元なし）**: `fetchBackendJson`が投げるエラーにHTTPステータスを持たせるため、`BackendApiError`クラスを新設(`lib/backend/client.ts`)。409を受け取った場合、スレッドの最新バージョンを再取得して**1回だけ再試行**し、それでも失敗する場合は呼び出し元に例外を伝播する（無限リトライや自動マージは行わない）。

---

## 3. マイグレーション内容・適用手順

```sql
-- supabase/migrations/202607050027_chat_threads_version.sql
alter table public.chat_threads
  add column if not exists version integer not null default 1;
```

適用手順（ユーザー側で実施）:

```bash
cd /path/to/shift-pilot-ai
python3 scripts/apply_migration.py 202607050027
```

**2章で述べた通り、このマイグレーションは適用前・適用後のどちらの状態でコードが動いていても安全** —未適用の間はCAS機能が単に無効なだけで、既存機能への影響はゼロ。

---

## 4. テスト結果

### 既存テスト

`backend/tests/`（8件）全てPASS。フロントエンド`tsc --noEmit`・`eslint`ともにエラーなし。

### マイグレーション未適用状態での安全性検証（本番相当のSupabaseプロジェクトに対する実データ検証）

上記2章の設計ミス発見のきっかけになった検証。`version`列が存在しない状態で、Phase A4のコードが**既存機能を一切壊さない**ことを実データで確認した:

```
PASS: create_chat_thread works pre-migration
PASS: get_chat_thread works pre-migration, returns: ['id', 'title', 'created_at', 'updated_at']
get_chat_thread_version pre-migration returned: None
PASS: get_chat_thread_version degrades to None instead of raising
replace_chat_messages pre-migration returned new_version=None
PASS: replace_chat_messages persists correctly pre-migration, exactly like before Phase A4
```

（最後の完了メッセージのみ、テストスクリプト側のprint文に含めた文字がWindowsコンソールのcp932コードページでエンコードできずクラッシュしたが、それより前の全アサーションは成功している。テストロジック自体の失敗ではない。）

### PostgRESTの条件付きUPDATE挙動の実API検証

CAS設計の根幹となる「`WHERE`条件が一致しない`UPDATE`は、エラーではなく0件の結果を返す」というPostgRESTの挙動を、まだ存在する既存の`title`列を使って実際のSupabase APIに対して検証した:

```
matching-condition UPDATE returned 1 row(s): [...]
non-matching-condition UPDATE returned 0 row(s): []
final title after failed CAS attempt: CAS-verify-thread-v2  (変更されていないことを確認)
```

想定通りの挙動を確認した（エラーにならず空配列が返ることを実証。仮に不一致時にHTTPエラーになる仕様だったら例外処理を作り直す必要があったため、これは設計上の重要な前提確認だった）。

### CAS競合検知ロジックのモック検証（マイグレーション適用後の状態をシミュレート）

`version`列が存在する状態を想定し、LLM呼び出しを介さずSupabase HTTP層のみをモックして、実際の同時書き込みに相当するシナリオを検証した:

```
Case 1: matching version -> new_version=6
PASS: matching expected_version succeeds and bumps version, messages written

Case 2: stale version -> raised ThreadVersionConflictError: chat_thread thread-2 was modified concurrently (expected version 5).
PASS: stale expected_version is rejected BEFORE any chat_messages delete/insert (the winner's data is never touched by the loser)
```

Case 2が要件1の核心（「片方の変更が黙って消えることがなく、競合が検知されエラーとして扱われる」）を直接裏付けている: 古いバージョンを元にした書き込み試行は、`chat_messages`のDELETE呼び出しが一度も発生する前に拒否されることを確認した。

### 実際の「2リクエストをほぼ同時に送る」形式のテストについて

指示書が例示する形式（2つのHTTPリクエストを同時発火する統合テスト）は、マイグレーション未適用のため`version`列を使った実際のレースは本番DB上では再現できなかった。上記のモックベース検証（PostgRESTの単一条件付きUPDATEの挙動を実APIで確認した上で、そのAPIを使うロジック自体はモックで検証）を、指示書が許容する「可能な範囲の検証」として位置づけている。

---

## 5. 気づいた懸念点・Phase A5以降に影響しそうな発見

1. **（最重要）新規カラムを既存の中核関数のSELECTに追加する変更は、たとえ「オプトイン」のつもりでも、その関数が広く使われている場合は事実上「必須」の変更になり得る**。今回、この失敗パターンを自分で発見して設計をやり直した。Phase A5以降で新しいカラムを追加する際は、「そのカラムを参照するコードが、カラムがまだ存在しない状態でも安全に動作するか」を必ず個別に検証する必要がある。
2. **CASは「厳密に同時」なレースは解決するが、「セッションをまたいだ divergence」は解決しない**: 同一スレッドをクライアントA・Bが並行して開いている場合、Aの書き込みが成功した直後にBが（新しいバージョンを読み直さずに）次のターンを送信すると、Bはその時点で改めて`get_chat_thread_version`を呼ぶため新しいバージョンを取得でき、書き込み自体は成功するが、**Bのローカルな会話履歴（Aの変更を知らない）で上書きしてしまう**。これは「全メッセージ配列を毎回丸ごと送信・上書きする」設計に内在する限界で、CAS単体では解決しない。真に解決するには案2（差分アペンド）か、クライアント側で書き込み前に最新状態を再取得する設計が必要になる。今回のタスク範囲では対応していない（1章で見送った案2の再検討理由がここでも当てはまる）。
3. **永続化の追加コスト**: `chat.py`が`expected_version`取得のために`get_chat_thread_version()`を新たに呼ぶようになったため、チャットターンごとに軽量なHTTPラウンドトリップが1回増えている。LLM生成時間（数秒オーダー）と比べれば無視できる規模だが、「変更前と同等のパフォーマンス」という要件2に対しては、厳密には「ほぼ同等（無視できる程度のオーバーヘッド増）」という留保付きの達成である。
4. **`/api/app/chat/messages/replace`・`chat-threads.ts::replaceChatMessages`は依然として現状の生きたトラフィックでは使われていない**。今回追加した409エラーハンドリング・リトライロジックも、実際にはまだ検証されていない経路である点は正直に記載しておく。

---

## Related Documents

- [global_state_migration_audit.md](global_state_migration_audit.md) — 発端となった監査レポート(2章)
- [phase_a0_report.md](phase_a0_report.md) — `replace_chat_messages`統一の経緯
- [phase_a1_report.md](phase_a1_report.md) / [phase_a1b_report.md](phase_a1b_report.md) — 呼び出し頻度が変化した経緯
