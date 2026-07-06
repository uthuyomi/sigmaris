# Phase BA3 実装報告: Memory Snapshot方式の導入

作業ブランチ: `phase-ba3-memory-snapshot`

## 0. 事前確認

指定ドキュメントのうち、以下を確認した。

- `docs/sigmaris/sigmaris_roadmap.md`
- `docs/sigmaris/phase_b_summary.md`
- `docs/sigmaris/incident_response_latency_investigation.md`
- `docs/sigmaris/phase_ba1_report.md`
- `docs/sigmaris/phase_ba2_report.md`

`docs/sigmaris/phase_b_arch_roadmap.md` はリポジトリ内に存在しなかった。BA1報告書にも同ファイルが存在しない旨が記録されていたため、今回は `incident_response_latency_investigation.md` と BA1/BA2報告書を直近のアーキテクチャ文脈として扱った。

## 1. Snapshotテーブル設計

新規マイグレーション:

- `supabase/migrations/202607190041_memory_snapshot.sql`

新規テーブル:

- `public.sigmaris_user_snapshot`

設計:

- `user_id uuid primary key`: ユーザーごとに最新1件を保持する。
- `preference_patterns jsonb`: B14 `sigmaris_user_preference_patterns` の会話時注入用上位5件。
- `topic_state jsonb`: B6 `sigmaris_topic_log` の current/previous 2件。
- `goal_alignment_flags jsonb`: B16 `sigmaris_goal_alignment_flags` の会話時注入用1件。
- `entities jsonb`, `relations jsonb`: B9 `sigmaris_entities` / `sigmaris_entity_relations` のヒント生成用bounded snapshot。
- `generated_at`, `created_at`, `updated_at`: 生成時刻と通常の更新時刻。

判断根拠:

- 過剰な正規化や集約ロジックを避け、既存4機能の「会話時に読んでいた出力」をそのままJSONとして束ねた。
- 元テーブルは削除・置換せず、B6/B9/B14/B16の抽出ロジックと保存形式は維持した。
- 他のSigmaris派生テーブルと同じ `service_role_only` RLSにした。

## 2. 集約処理とスケジュール

新規サービス:

- `backend/app/services/memory_snapshot.py`

主な関数:

- `build_memory_snapshot_payload(user_id)`: B6/B9/B14/B16の既存取得関数を呼び、Snapshot payloadを作る。
- `write_memory_snapshot(payload)`: `user_id` をキーに `sigmaris_user_snapshot` へupsertする。
- `generate_memory_snapshot(user_id)`: 週次ジョブ用の集約エントリポイント。
- `get_memory_snapshot(user_id)`: 会話時の単一読み込み用。

スケジュール:

- `backend/app/services/proactive/scheduler.py`
- 日曜 5:25 `memory_snapshot_generate`

判断根拠:

- 既存週次ジョブは日曜 4:35 B16、4:45 B14、5:15 B9、5:30 curiosity系がある。
- SnapshotはB9までの出力を含めたいので、B9の5:15より後、5:30より前の5:25に置いた。
- B6はターンごとの `sigmaris_topic_log` だが、Snapshot生成時点のcurrent/previousを束ねるだけに留めた。

## 3. 会話時読み込み置き換え

変更ファイル:

- `backend/app/services/orchestrator/service.py`

変更内容:

- 削除したホットパス直接読み込み:
  - `_cached_preference_patterns()` -> B14直接読み込み
  - `_cached_current_and_previous_topic()` -> B6直接読み込み
  - `_cached_goal_alignment_flags()` -> B16直接読み込み
  - `_cached_entities_and_relations()` -> B9直接読み込み
- 追加したホットパス読み込み:
  - `_cached_memory_snapshot(user_id)` -> `sigmaris_user_snapshot` を1回読む
- `run_orchestrator_chat()` / `run_orchestrator_chat_stream()` は、認証後に `fact_items` と `memory_snapshot` を並列取得し、Snapshotから既存の文脈ビルダーへ値を渡す。
- B15 `get_threshold_adjustment()` はBA3対象外のため従来通り個別TTLキャッシュで残した。
- B16の `last_surfaced_at` 互換性のため、promptへ入れたflag idはプロセス内 `_recently_surfaced_goal_flag_ids` で除外する。DBへのsurfaced反映は従来通りbackground flushで行う。

## 4. テスト結果

追加テスト:

- `backend/tests/test_memory_snapshot.py`

確認内容:

- B6/B9/B14/B16のモック出力がSnapshot payloadへ正しく集約されること。
- Snapshot展開時、直近提示済みのB16 flagが再注入されないこと。

実行結果:

```text
cd backend
python -m unittest tests.test_memory_snapshot tests.orchestrator.test_service tests.orchestrator.test_audit
=> Ran 6 tests ... OK

python -m compileall app tests
=> OK

python -m unittest discover
=> Ran 10 tests ... OK
```

補足:

- ローカル環境にはSupabase/OpenAIの実キーがないため、既存orchestratorテストでは設定不足のfallbackログが出るが、テスト結果はOK。
- 実DBへのマイグレーション適用・実モデルAPI検証は行っていない。指示通り、マイグレーションは作成のみ。

## 5. 懸念点・BA4への影響

- `phase_b_arch_roadmap.md` は存在しないため、BA3の判断根拠は `incident_response_latency_investigation.md` と BA1/BA2報告書に依存した。
- Snapshot化により、B6の「直近ターンで変わったtopic」は次回週次Snapshot生成までDB Snapshotへは反映されない。会話時の読み込み回数削減を優先した判断だが、topic鮮度を重視するなら、将来「turn後backgroundで軽量Snapshot更新」を検討してよい。
- B16のcooldownは元テーブルでは即時に効くが、Snapshot DB自体は週次生成まで古いflagを含み得る。今回、プロセス内の直近提示済みセットで連続注入は抑止した。複数プロセス構成にする場合は、Snapshot側のflag更新またはより短いSnapshot再生成が必要。
- BA4では応答生成とpersona rewriteの統合が主戦場になる。今回の変更でB6/B9/B14/B16の読み込みは1回にまとまったため、BA4の計測では「メモリ読み込み群」より二段階LLM生成の比率がさらに目立つはず。
