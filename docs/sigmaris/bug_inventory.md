# 既知・潜在バグの棚卸し調査

**調査日**: 2026-07-08〜07-09
**性質**: 本ドキュメントは調査・一覧化のみを目的とする。**この調査タスクの中では一切のコード修正・DB書き込みを行っていない。** 一覧化した問題への対応可否・優先順位の最終判断は次タスクで行うこと。

## 0. 調査の前提と限界

- 本セッションにはSupabase本番DBへの直接アクセス（SQL実行）、本番サーバーへのSSHアクセス、`agent_invocation_audit_logs`等のテーブルへのライブクエリ実行手段がない。**4つの異常値調査（2章）は、実ログ・実DBの直接確認ではなく、関連コードの動作を読み解いた上でのコード起因の仮説立てにとどまる。** 断定できる箇所と推測にとどまる箇所を明示的に区別して記載する。
- `docs/sigmaris/`配下の全46ファイルを読了した（本タスク自身のために新規作成した`bug_inventory.md`を除く）。個別の一次情報はサブエージェントによる抽出（Phase A0〜A5, A_summary, B1〜B17, B_summary, BA3, BA4, JWT永続化, グローバル状態移行監査, 各インシデントレポート）と、筆者自身によるコード直接確認（BA1/BA2/BA4本文、C-mini/C-full関連コード、response_latency調査、Phase B3/facts_context系）を組み合わせている。
- マイグレーション適用状況（「未適用」と過去に報告されたものが現在適用済みかどうか）は、リポジトリ内の`.sql`ファイル存在有無でしか確認できない。**本番DBに実際に適用されているかどうかは、この環境からは確認不能。** 運用者側での確認方法は2.1節末尾に記載。**【2026-07-10追記】海星さんにSQL実行を依頼し、44件全てが適用済みであることを確認した。詳細は8章を参照。**

---

## 1. 過去レポートからの申し送り事項一覧

Phase A0〜C-full、BA1〜BA4の全報告書・インシデントレポートから「気づいた懸念点」「申し送り事項」「未検証」「未対応」を収集した。件数が多いため、**同種の懸念は横断的にグルーピングし**、個別ファイルの詳細は各項目の出典を参照する形にしている。個別の一次情報（quote付き全リスト）はサブエージェント調査ログに保持されており、必要であれば再展開できる。

### 1.1 横断的テーマ（最も繰り返し出てくる懸念）

1. **本番DB・実モデルAPIでの検証が一度も行われていない機能が非常に多い。** Phase A1〜B17のほぼ全報告書が「`OPENAI_API_KEY`・SSH・Supabaseサービスロールキーがローカルになく、mock/単体テストでしか検証できなかった」と明記している。B1〜B17の17機能全てが実モデル効果測定ゼロのままPhase C-mini/C-fullに突入した（`phase_b_summary.md` 4章item2）。
2. **未適用マイグレーションの累積（【2026-07-10解消済み】8章参照）。** Phase A1(`202607030025`)〜B9(`202607180040`)まで、少なくとも13件のマイグレーションが各報告書時点で「未適用」と記録されていた。適用順序に依存関係がある（B13のRPCがB17に依存等）。**2026-07-10、海星さんにSupabase上でのSQL実行を依頼し、リポジトリに存在する44件のマイグレーション全てが適用済みであることを確認した（8章）。** 各Phase報告書執筆時点では正しく未適用だったが、その後（おそらくPhase B9の申し送り対応、または継続的な運用）で解消されていたと考えられる。
3. **重複実装された「週次抽出→グローバルテーブル→TTLキャッシュ注入」パイプライン。** B2(エピソード統合)・B6(トピック)・B14(判断パターン)・B15(個人別閾値)・B16(ゴール整合性)・B9(ナレッジグラフ)の6機能が、ほぼ同一の設計パターンを毎回独立実装している。`phase_b9_report.md`で最初に指摘され、`phase_b16_report.md`・`phase_b_summary.md`で繰り返し「Phase C-full着手前に統合を検討すべき」と申し送られたが、**現在まで未着手**。
4. **未検証・未実測の暫定チューニング定数が広範囲に存在。** B1の`match_threshold=0.15`、B7の`_MULTIHOP_RESULT_LIMIT=8`、B8のrank17基準、B11の閾値(0.78/0.85/0.5)、B14の`_MIN_DECISIONS_FOR_ANALYSIS=3`/`_MIN_SUPPORTING_DECISIONS=2`、B15の`_MIN_EVIDENCE_FOR_ADJUSTMENT=5`、B16の`_MIN_SUPPORTING_EVIDENCE=2`/`_SURFACE_COOLDOWN_DAYS=14`、B17の`_IMPORTANCE_RANKING_WEIGHT=0.15`等、SB-3の`DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD=0.92`まで、**「実データで検証しておらず、運用データが溜まってから調整が必要」という同一パターンの注記が各報告書に繰り返し現れる**。
5. **fire-and-forgetタスクの信頼性欠如。** `global_state_migration_audit.md`が明示的に指摘: `memory_extractor`・`_cognitive_layer_bg`等の非同期バックグラウンドタスクは例外を握りつぶすのみで、リトライ・失敗検知の仕組みが一切ない。個々の呼び出しは`except Exception: logger.exception(...)`で記録はされるが、**失敗が蓄積しているかどうかを能動的に検知する仕組みはゼロ**。
6. **`sigmaris_decision_log`の実データ蓄積量が一度も確認されていない。** B13〜B16の複数機能が「最低証拠件数」でゲーティングされているが、実運用でどの程度`insufficient_data`に落ちているかは`phase_b9_report.md`・`phase_b_summary.md`双方で「未確認」と明記されたまま。本タスクの2.4節が関連する具体的な状況証拠を提供する。
7. **デッドコード・未使用経路が複数世代にわたって「一旦保留」のまま残存。** `routes/chat.py`の`/api/chat/stream`（Phase A1-b以降、削除検討が繰り返し先送り）、`chat-threads.ts::replaceChatMessages`/`app/chat/messages/replace`（Phase A0で追加、A4時点で呼び出し元ゼロのまま）、`orchestrator/service.py`の重複`facts_ctx`/`trends_ctx`計算（Phase A5で発見、B期に持ち越すと申し送られたまま未整理）。本タスクで新たに`orchestrator/persona_rewriter.py`一式が同種のデッドコードであることを確認した（3.2節参照、これは新規発見）。

### 1.2 Phase A系（個別・未整理のまま残っている項目）

- 3つの主要マイグレーション（`202607030025`チャットメッセージ複合インデックス、`202607040026`decision_log supersede、`202607050027`chat_threads.version）がA期時点で未適用。
- Phase A4のCAS（楽観的ロック）は**同時書き込みレースのみ解決し、クロスセッション分岐（2台目クライアントが古いローカル履歴で上書きするケース）は未解決**のまま設計上の既知の限界として記録されている（`phase_a4_report.md` 5章item2）。
- embeddingのprovenance（どのモデルが生成したか）を追跡する列が存在せず、Ollama生成とOpenAI生成のembeddingが同一列に混在しうる。`embedding_source`列の追加案は「必要性が明確でない」として見送られたまま（`phase_a5_report.md` 7章item1）。
- `update_fact_embeddings`バックフィルジョブが、本番がOpenAIモードで稼働していた期間に無言でno-opしていた可能性が指摘され、確認は運用者に委ねられたまま（`phase_a5_report.md` 7章item3）。
- `/chat`ページ（実際にユーザーが使う画面）がA1で実装したセッション継続・記憶注入の恩恵を受けない、という経路分岐の非対称性がA1で発見され、A1-bでオーケストレーター統一に伴い部分的に解消されたと見られるが、明示的な解消確認の記載はない。
- ファイル/画像添付がA1-b以降`/chat`経由で送信できなくなった（オーケストレーター経路への切替により`extractText()`が`type:"file"`を落とす）機能後退が、実質的な回帰として記録されたまま未修正（`phase_a1b_report.md` 6章item1）。

### 1.3 Phase B系（個別・未整理のまま残っている項目）

- B5ダッシュボードは実ブラウザでの表示確認が一度もされていない（型チェック/lintのみ）。
- セッション序盤で発生した`/chat`表示崩れの調査が、追加指示がないまま未解決で放置されている（`phase_b9_report.md`・`phase_b_summary.md`双方に記載）。
- B8のrank17という安全域基準がB13の報告するrank11-14と食い違っており、テストハーネスの前提差と推測されるが未統一。
- B17の`importance_score`は「per-factで学習された重要度」ではなく「カテゴリ層の粗い代理値」に留まっており、機能名が示唆する精度を実際には持っていない（`phase_b17_report.md` 1章）。
- RRF（Reciprocal Rank Fusion）方式が生の類似度の大小情報を捨てるため、将来的な細粒度の重み付けには不向きという設計上の限界が指摘されたまま。
- B6のトピックラベルは完全表記一致でのみ重複排除されており、表記揺れ（"AdFlow AI收益化" vs "AdFlow AI值付け"）が別トピックとして扱われる。B7のサブクエリ重複排除も同じ限界を抱える。同種の問題がB16の目標整合性チェックの精度にも間接的に影響しうると指摘されている。

### 1.4 Phase BA系（アーキテクチャ再設計、直近の変更に伴う懸念）

- **BA3**: `docs/sigmaris/phase_b_arch_roadmap.md`が実際にはリポジトリに存在しないことがBA1・BA3双方で報告されている（本タスクでのファイル一覧取得でも同ファイルは確認できず、現在も存在しないと見られる）。Snapshot化により、B6の直近ターンでのトピック変化が次回週次Snapshot生成まで反映されない鮮度トレードオフが意図的に導入されている。B16のクールダウンはプロセス内メモリでのみ機能し、複数プロセス構成では機能しない。
- **BA4 本文**: 固有名詞ガードが旧LLM semantic guardより弱くなっており、Phase C-fullのresponse_error_rate評価で問題が出た場合はdeterministic guard追加が「次候補」とされたまま未実装（これは本タスクの2.1節の調査と直接関係する）。非streaming版エンドポイント（`/api/agent/chat/complete`）にはtool-output guardが一切ない。
- **BA4 追補（7〜15章、本番反映後に発覚した問題群）**:
  - 7章: `system_override`の4000文字上限超過による422エラー → 修正済み（persona.md全文注入を停止し、動的コンテキストのみ4000文字上限でトランケート）。
  - 8章: streaming無音時間によるフロントエンド無表示 → 修正済み（delta即時中継に戻す）だが、この修正がfact guardを「表示前の遮断」から「完了後の軽量検知・ログ記録のみ」に変更しており、**ガードが実質的にadvisory化した**という副作用は明示的に記録されているのみで、その影響評価は未実施。
  - 9章: `/api/orchestrator/chat/stream`の422（メッセージ履歴が`max_length=50`超過）→ 修正済み（フロントエンド側で直近24件・1件20,000字にキャップ）。ただしこれは**Next.js `/api/chat`ルート経由の場合のみ**の修正であり、WearOS等`/api/agent/chat/stream`を直接叩く他クライアントが同種の超過を起こしうるかどうかは検証されていない。
  - 10章: B3自動確認質問が文脈と無関係に繰り返し表示される問題 → **根本修正ではなく`SIGMARIS_SURFACE_INQUIRY_QUESTIONS=false`によるデフォルト無効化で回避**。B3抽出ロジック自体は残存しており、真の修正（文脈適合性判定・永続的クールダウン）は明示的に将来課題として先送りされている。
  - 11〜15章: フロントエンドのstreaming表示ちらつき問題への対応が3段階（11章の再レンダリング最適化→12章のMarkdown smooth streaming無効化→13〜15章の応答時間バッジ追加→問題再発→撤去）にわたって行われ、**最終的に「体感応答時間表示」機能自体を撤去する**という結末になっている。15章時点で「assistant-ui/Markdown/streamingとの相互作用が現時点では副作用が読みにくい」ため、ライブ秒数表示機能の再導入は保留のまま。ユーザーがチャットUI上で応答時間を確認する手段は現在存在しない（`agent_invocation_audit_logs.duration_ms`をDB越しに見る以外）。

### 1.5 JWT永続化・グローバル状態移行監査・インシデント系

- JWT永続化修正は**将来の再発防止のみ**であり、修正時点で`.env`に保存されていた既に使用済みの可能性があるリフレッシュトークン自体の再発行は別途必要と記録されたまま、その後実施されたか確認できていない。
- `backend/.state/sigmaris_jwt_session.json`のバックアップ戦略が存在しない。ディスク障害等で消失した場合、`.env`への古い値へのフォールバックにより同じ`refresh_token_already_used`障害が再発する設計上の弱点が明記されている。
- `global_state_migration_audit.md`（グローバル状態への移行を検討する事前調査）は多数の未解決の設計論点を残したまま止まっている（同一スレッドへの複数タブ同時書き込みでの後勝ち上書き、JSONBの肥大化対策、単一行グローバル状態への同時PATCHでのlast-write-wins衝突など）。この監査自体が実装に至ったかどうかは、その後の報告書からは確認できない。**この監査が実際にPhase Bのどの機能に反映されたか、あるいは提案のまま棚上げになっているかは不明** — 運用者側で `docs/sigmaris/global_state_migration_audit.md` の提案がその後どのタスクで実装されたか（または実装されなかったか）を確認することを推奨する。
- `incident_shiftpilotai_naming_report.md`は「self-referential confabulation経路」の完全排除ができていないことを認めた上で、`persona_rewriter.py`の"legacy project names"文言を"未確認の別経路"として名指ししている。本タスクの3.2節で、この`persona_rewriter.py`自体がBA4以降呼び出し元ゼロのデッドコードであることが判明した — つまりこの申し送りは**現在の実装に対しては的外れ**であり、実際の命名漏れの経路は（もし再発するなら）`orchestrator/service.py`の`_build_unified_persona_context()`もしくはpersona.md本体を疑うべきという、当時の報告書執筆者が把握していなかった追加情報が今回判明した。
- `incident_free_limit_removal_report.md`: 公開ランディングページに無料枠に関する矛盾した文言が残存（`landing-page-content.tsx`）。`chat_tools.py::has_pro_plan`によるPro限定ツールゲーティングが現状の非商用運用と整合しているか未確認のまま。

---

## 2. 直近の異常値の調査

### 2.1 `response_error_rate` の急上昇（0.049 → 0.177、3.6倍）

> **【2026-07-10追記】本節は初回調査時点（サーバーアクセスなし）の仮説である。実サーバーログ・実DBデータによる追加調査の結果は6章を参照。6章で判明した事実は本節の仮説と部分的に異なる（`used_fallback`消失の仮説自体はデータで裏付けられたが、当初想定していなかった「X投稿フィルタ却下の誤カウント」という別要因が主要な寄与要因として新たに判明した）。**

**確認できたこと（コードベースから）**:

`response_error_rate`は`eval_metrics.py::compute_response_error_rate()`が`agent_invocation_audit_logs.status`列の直近N日分（デフォルト7日）を集計し、`status == "failed"`の割合として算出する（`status == "completed_with_fallback"`はエラーに数えない設計、`eval_metrics.py` 134-147行）。

`status="failed"`が書き込まれるのは、`orchestrator/service.py`の非streaming/streaming両方の統一生成パス（`call_schedule_agent()`呼び出しを含む一連の処理）が例外を送出した場合のみである（`orchestrator/service.py` 984-998行、1231-1246行）。

**重要な発見（コード確認済み、これは推測ではない）**: 現在の`orchestrator/service.py`には、非streaming・streaming双方に`used_fallback`という変数が存在し、これが`True`であれば監査ログの`status`は`"completed_with_fallback"`（エラー非計上）になる設計だが、実際のコードを全文grepした結果、**`used_fallback`が`True`に設定される箇所はコード中に一つも存在しない**（983行・1229行でいずれも`used_fallback = False`と固定代入されるのみ）。これは、BA4で旧来の「schedule-agent出力のドラフト生成 → persona rewrite（失敗時は`used_fallback=True`で生の出力をそのまま返す）」という二段階アーキテクチャが、「一発で統一生成し、失敗時はリトライなしで例外を上に伝播させる」という単一パス設計に置き換わったことの帰結と考えられる（3.2節で述べる`orchestrator/persona_rewriter.py`のデッドコード化と同一のアーキテクチャ変更が原因）。

**仮説（コードから読み取れる範囲の推論。実ログでの確認はできていない）**: BA4以前は、persona rewriteの過程で不整合が検出されても`PersonaRewriteResult(used_fallback=True)`という形で「生の出力をそのまま返す」degradedな成功として吸収できていた。BA4の統一生成アーキテクチャではこの吸収機構が失われており、**以前なら"completed_with_fallback"としてエラーに数えられなかったはずの失敗ケースが、現在はすべて`"failed"`として計上されるようになっている可能性が高い**。BA4の追補7〜9章（4000文字422、streaming無音、履歴50件超過422）はいずれも本番反映直後（2026-07-06前後）に発覚した実際の障害であり、その多くは個別に修正されたと報告されているが、**修正後も同種の未知のエッジケース（WearOS等、Next.js `/api/chat`ルートを経由しない呼び出し元でのメッセージ長超過など、1.4節で述べた通り未検証のまま）が残っている可能性がある**。

**運用者側で確認すべき具体的な手順**:
1. `agent_invocation_audit_logs`から直近7〜14日分の`status='failed'`行を`error_code`列でグルーピングして集計する（`error_code`は`type(error).__name__`、`orchestrator/service.py` 992行/1239行）。どの例外型が急増しているかで原因を大きく絞り込める。
   ```sql
   select error_code, count(*), date_trunc('day', created_at) as day
   from agent_invocation_audit_logs
   where status = 'failed' and created_at > now() - interval '14 days'
   group by error_code, day
   order by day desc, count(*) desc;
   ```
2. サーバーのアプリケーションログ（journalctl等）で、上記のerror_code発生時刻周辺のスタックトレースを確認し、BA4追補で報告された422系・空応答RuntimeError系のいずれに該当するか、あるいは全く新しい原因かを特定する。
3. `status='completed_with_fallback'`の行数が直近で0件（もしくは大幅減少）になっていないか確認する。もし過去は一定数存在していたのに直近で0件になっていれば、上記の「フォールバック吸収機構の消失」仮説を強く裏付ける。

### 2.2 `memory_duplicate_rate` が高い（0.349、505件中176件重複、46クラスタ）

**確認できたこと（コード確認済み）**:

`compute_memory_duplicate_rate()`（`eval_metrics.py` 234行〜）は、`user_fact_items.embedding`の全ペア間コサイン類似度が0.92以上のものをUnion-Findでクラスタリングし、「重複排除した場合に削除される件数／全アクティブfact数」を算出する。この設計自体はドキュメント化されている通り、**「同一(category,key)の重複」ではなく「異なるcategory/keyだが実質的に同じ主張をしている行」**を検出する（DBのUNIQUE制約により前者は原理的に発生しない）。

事実生成経路を確認した結果、**もっとも有力な原因は`memory_extractor.py`（毎チャットターン実行される事実抽出）である**:
- `memory_extractor.py`の抽出プロンプト（18-55行）は、**その時点で既に登録されている事実の一覧を一切LLMに提示していない**。LLMは会話の最新ターンだけを見て、`category`と`key`（snake_case）を毎回ゼロから自由に決定する。
- 抽出後のコード側の重複防止は、`confidence_map`による**完全一致の(category, key)ペアに対する信頼度比較のみ**（108-117行）。category/keyの表記が微妙に異なれば（例: `preferences/favorite_color` と `lifestyle/color_preference`）、DBのUNIQUE制約もこのconfidence比較もすり抜け、意味的には重複だが行としては別々のfactとして`upsert_fact_item`される。
- これはまさに`eval_metrics.py`のコメント（150-168行）が「重複」の定義として説明している具体例そのものである。

二次的な寄与経路として、B2エピソード統合（`experience_layer.py`の`consolidate_episodic_memory()`、weekly batch）も同様に`upsert_fact_item`を使うが、こちらは直近100件のエピソードを毎回再スキャンする設計であり、`upsert_fact_item`が(user_id, category, key)に対して冪等であることを根拠に「同じepisodeから同じfactを再導出しても重複しない」という設計コメントが付いている（427-430行）。ただし、この冪等性が成立するのは**LLMが毎回同じcategory/keyを選ぶ場合に限られ**、memory_extractor.pyと同じ「category/key選択がLLM任せで既存fact一覧を見ていない」という構造的弱点を共有している可能性がある（B2側のプロンプトは今回精査していないため、これは推測）。B14の判断パターン抽出は`sigmaris_user_preference_patterns`という別テーブルに書き込むため、`user_fact_items`の重複には直接寄与しない。

**運用者側で確認すべき具体的な手順**:
1. `run_eval.py`の標準出力（`--dry-run`でも表示される）に含まれる「重複候補クラスタ」一覧（`duplicate_clusters`、類似度降順で最大10件表示、全件は`sigmaris_eval_runs.details.duplicate_clusters`に保存）を実際に読み、各クラスタのfact_idに対応する`category`/`key`/`value`を`user_fact_items`から引いて中身を確認する。これにより「memory_extractor.py起源のcategory/key表記ゆれ」という仮説が実際に正しいかどうかを直接検証できる。
   ```sql
   select id, category, key, value, source, created_at
   from user_fact_items
   where id = any(array['<クラスタ内のfact_id...>']);
   ```
2. 各重複クラスタのfactの`source`列（Phase B4のprovenance拡張、`thread_id`/`invocation_id`）を確認し、複数の異なるターンから生成されているか（memory_extractor.py起源の証拠）、それとも同じ週次バッチ実行から生成されているか（B2/B14起源の証拠）を切り分ける。

### 2.3 `memory_precision` の低下（0.125 → 0.112）

**確認できたこと（コード確認済み）**: `memory_precision`はテストセットの各設問について`search_relevant_memories()`が返す上位`search_limit`件（デフォルト5件）のうち、正解として期待される`expected_fact_keys`に一致した件数の割合をマクロ平均したもの（`eval_metrics.py` 45-62行）。

**仮説**: 2.2節で確認した`memory_duplicate_rate`の高さと構造的に関連している可能性が高い。あるテストセット設問の正解が特定の1つのfact IDを指しているとき、`user_fact_items`内に意味的にほぼ同一だが**IDが異なる**重複factが存在すると、検索が正解ではなく重複先のfactを上位に返してしまい、そのスロットは「不正解」としてカウントされる（内容としては実質的に正しい情報を返していても、`retrieved_ids`と`expected_fact_keys`解決後のIDが一致しないため）。総fact数がセッションを通じて増加し続けている（過去のセッション記録では285→383→493→495→505件と推移）中で重複クラスタも46まで積み上がっていることを踏まえると、**「正解と意味的に同じだがIDの異なる重複行がヒットしてしまう」ケースが増加し、precisionを押し下げている**という説明は筋が通るが、実際のper_query内訳（`sigmaris_eval_runs.details.per_query`）を見なければ断定はできない。

これに加えて、fact総数の増加自体がテストセットを固定した状態での検索精度低下（上位5件の枠を巡る競合の激化）に寄与している可能性もあるが、これは重複問題と独立した一般的な傾向であり、切り分けが必要。

**運用者側で確認すべき具体的な手順**:
1. `sigmaris_eval_runs`テーブルの直近2回分の`details.per_query`を比較し、precisionが悪化した設問（`query_id`）を特定する。
2. その設問の`expected_fact_keys`が指すfactが、2.2節の重複クラスタに含まれているかどうかを確認する。含まれていれば、上記仮説が裏付けられる。

### 2.4 テストセットの`decision由来`が Phase A3以降ずっと0件

**確認できたこと（コード確認済み、これはかなり具体的に原因を絞り込めた）**:

`testset_gen.py::_build_decision_entries()`（123-164行）は、`sigmaris_decision_log`から取得した各decisionについて、**`decision.memory_refs`が現在アクティブな`user_fact_items`のいずれかのIDに解決できるものだけ**を候補として残す（130-137行のコメントで明記: `sigmaris_decision_log`はベクトル検索の対象外のため、決定由来の設問であっても採点には対応するuser_fact_itemsのIDが必要）。**`memory_refs`が空、または参照先が全て削除・変更済みのdecisionは、無条件に除外される。**

`memory_refs`が実際に埋まる経路は`decision_log.py::detect_and_record_decision()`のみで（643-648行）、LLMが返す`related_fact_keys`（`category/key`形式の文字列リスト）を、その時点で渡された`fact_items`引数から作った`fact_lookup`辞書で解決できたものだけが採用される。この`fact_items`は`orchestrator/service.py`の`_cognitive_layer_bg()`呼び出し元（1066行・1305行）から正しく渡されていることをコードで確認済み。

つまり、decision由来の設問が0件である原因は、**以下の3段階のいずれか、または複数が重なっている可能性がある**（この環境からはどれが実際に起きているか切り分けられない）:

1. **`sigmaris_decision_log`自体に十分な件数の決定が記録されていない。** `phase_c_mini_report.md`が報告した「`LLMRouter.is_available()`のバグでOllamaが実際には利用不可なのに利用可能と誤判定され、決定検出のfire-and-forget呼び出しが日常的に404で無言失敗していた」問題はPhase C-mini時点で修正されたと報告されているが、その修正がdecision蓄積を実際に回復させたかどうかの再確認は行われていない（`phase_b13_report.md`・`phase_b14_report.md`双方が「この環境からは確認できない」と明記したまま）。
2. **decisionは記録されているが、LLMが`related_fact_keys`を返さない、または返した`category/key`が`fact_lookup`（その時点のアクティブfact一覧）に一致しない。** `_DETECT_PROMPT`（`decision_log.py` 42-69行）は`related_fact_keys`の記入を求めてはいるが必須にはしておらず、LLMが決定内容とfactの紐付けを省略する可能性は十分にある。
3. **decisionは記録され`memory_refs`も一度は埋まったが、参照先のfactがその後削除・カテゴリ変更されて解決不能になった。** `fact_id_to_key`は`testset_gen.py`実行時点の**現在**のアクティブfact一覧から作られるため（184-185行）、記録時点では有効だった参照が後から無効化されるケースは構造的に起こりうる。

なお、Phase A3時点で報告された「`202607040026`マイグレーション（decision_log supersede機構）未適用の間はpolicy_change系のINSERTがCHECK制約で失敗し続ける」という問題は、マイグレーションファイル自体はリポジトリに存在するが、**本番DBへの適用有無はこの環境から確認できない**。もし未適用のままなら、これも0件の直接的な原因になりうる。

**運用者側で確認すべき具体的な手順**:
1. `sigmaris_decision_log`の総行数と、直近30日の行数を確認する。0件〜数件であれば原因1（そもそも記録されていない）。
   ```sql
   select count(*), count(*) filter (where created_at > now() - interval '30 days') as recent
   from sigmaris_decision_log;
   ```
2. 件数が十分あるなら、`memory_refs`が空配列でない行の割合を確認する。ほぼ全て空配列なら原因2。
   ```sql
   select count(*) filter (where jsonb_array_length(memory_refs) > 0) as with_refs, count(*) as total
   from sigmaris_decision_log;
   ```
3. `memory_refs`に値が入っている行がある場合、その参照先IDが現在の`user_fact_items`に実在するか突き合わせる。実在しないものが多ければ原因3。
4. `\d sigmaris_decision_log`または`information_schema.table_constraints`で、`202607040026`マイグレーションが定義するCHECK制約・`superseded_by`列が実際に存在するか確認する。

---

## 3. 静的コードチェック

### 3.1 `backend/tests/` の実行結果

```
16 passed in 1.65s
```

**全16件成功、失敗なし。** 事前に知られていた「BA4関連の3件の陳腐化したスクラッチテスト」は、過去セッションのスクラッチディレクトリ（セッションスコープの一時ディレクトリ）に存在していたものであり、`backend/tests/`にコミットされたテストではない。本セッションのスクラッチディレクトリにも該当ファイルは存在せず、`backend/tests/`のテスト結果には一切影響しない。

### 3.2 既知バグパターンの再発チェック（grep結果）

過去に発見・修正された4種のバグパターンについて、コードベース全体を再チェックした。

**(a) `jwt[:20]`によるキャッシュキー衝突パターン** — 再発なし。`orchestrator/service.py`・`app_profile_data.py`にはコメントとして過去の教訓（フルJWTをそのままキーにしない）が残っているのみで、実際のキー生成はSHA-256ハッシュ化された`_jwt_cache_key()`を使っている。他のキャッシュ実装（`billing.py`等）でも同様のパターンの再発は見当たらない。

**(b) `local_llm.py`のTaskTypeルーティングをバイパスする生の`AsyncOpenAI`クライアント使用** — 4箇所で使用を確認、うち2箇所は新規に問題として指摘できる:
- `backend/app/services/memory_search.py:239`（embedding生成）— 妥当。`local_llm.py`のLLMRouterはchat completion専用でembeddings APIを扱わないため、これはバイパスではなく別カテゴリのAPI呼び出し。
- `backend/app/services/chat.py:392`（`run_chat_completion`/`stream_chat_completion_ui`向け）— これはPhase A1-b以降「デッドコードとして温存」と繰り返し報告されている旧`/api/chat/stream`直接呼び出し経路向け。オーケストレーター経由が主経路である現在、実害は小さいと考えられるが、経路自体が生きているかどうかの再確認はされていない。**加えて、このファイル376-383行のコメントは「`classify_chat_intent()`, `run_chat_completion()`, `stream_chat_completion_ui()`がこのクライアントを使う」と書かれているが、実際には`classify_chat_intent()`は既に`chat_routing.py`に移設されTaskTypeルーティング(`TaskType.CHAT_INTENT_CLASSIFICATION`)を使うようになっており、このコメントは陳腐化している**（軽微、コードの動作に影響なし、コメントの誤りのみ）。
- `backend/app/services/self_model.py:230`（`_analyze()`、週次自己モデル分析ジョブ）— **新規発見。** `local_llm.py`には同種の「自己内省」的呼び出し向けに`TaskType.SELF_REFLECT`が既に存在し、`decision_log.py::analyze_decision_patterns()`や`goal_alignment.py`はこれを正しく使っている。しかし`self_model.py::_analyze()`は生の`AsyncOpenAI`クライアントを直接構築しており（`if not settings.openai_api_key: raise RuntimeError(...)`と無条件にOpenAIキー必須にしている）、`LOCAL_LLM_ENABLED`が有効でもこの週次ジョブだけは常にOpenAI課金が発生し、Ollamaでは動作しない。既存のTaskType体系との一貫性を欠く、典型的な「TaskTypeバイパス」パターンの再発と判断する。
- `backend/app/services/orchestrator/persona_rewriter.py:39`（`rewrite_with_persona`/`rewrite_with_persona_stream`）— 3.3節で述べる通り、この関数群自体が**呼び出し元ゼロのデッドコード**であるため、TaskTypeバイパスとしての実害は現状ない。ただし、もしこのモジュールが将来復活・再利用される場合は同じ問題を抱える。

**(c) fire-and-forgetタスクでの例外の無言破棄（`except ...: pass`で握りつぶし、ログすら残さない）** — 複数件確認。いずれも「ベストエフォートの補助情報取得」に対するもので、単独では低リスクだが、パターンとしての再発が広範囲にわたる:
- `backend/app/services/billing.py:37-38`（override email確認の失敗を無言で握りつぶし、通常の課金状態チェックにフォールバック — 意図的な設計と読めるが、ログがない）
- `backend/app/services/proactive/jwt_manager.py:124-125`（Windowsでのbest-effort処理、コメントで意図明記済み、問題なし）
- `backend/app/services/research_agent.py:294-295, 588-589, 718-719`（HackerNews等の外部情報源パース失敗を無言スキップ）
- `backend/app/services/self_narrative.py:197-198, 205-206, 213-214, 228-229`（自己モデル・プロフィール・前回タイトル取得失敗を無言スキップ）— **同一ファイル189-190行の直前の`except`ブロックだけが`logger.warning(...)`を呼んでおり、すぐ下に続く4つの`except`ブロックだけがログなしの`pass`になっている。同一関数内でログ有無の扱いが不統一**であり、意図的な省略というより書き漏れの可能性がある。

いずれも即座に外部から観測可能な障害には直結しないが、`global_state_migration_audit.md`が指摘する「fire-and-forgetの信頼性欠如」という横断的懸念（1.1節item5）の具体的な発生箇所として記録しておく。

### 3.3 新規発見: `orchestrator/persona_rewriter.py` はBA4以降デッドコード

grep調査で確認: `backend`配下のどのファイルからも`persona_rewriter`という文字列が（自ファイルを除いて）一切参照されていない。つまり`rewrite_with_persona()`・`rewrite_with_persona_stream()`は**呼び出し元が存在しない**。

`orchestrator/service.py`のコメント（113行付近、`_build_unified_persona_context()`）に "Answer as Sigmaris directly in this first generation; no later rewrite step" とあることから、これはBA4の「二段階生成（ドラフト生成→persona rewrite）から単一パス統一生成への置き換え」によって置き換えられた旧アーキテクチャの残骸と判断できる。

これは単なるコード整理の話にとどまらない。1.5節で述べた通り、`incident_shiftpilotai_naming_report.md`はこのファイルの"legacy project names"文言を未確認の懸念経路として名指ししているが、**実際には呼ばれていないため、この経路からの命名漏れは起こりえない**。逆に、2.1節で述べた「フォールバック吸収機構の消失」の直接の物証でもある——このファイルが実装している`used_fallback=True`という緩やかな失敗吸収の仕組み自体が、もはやどこからも呼ばれていない。

---

## 4. 問題一覧表

凡例: 深刻度は「ユーザー影響の大きさ×発生確度」の主観的評価。優先度は次タスクでの対応検討順の目安であり、対応の可否自体は本タスクでは判断していない。

| # | 概要 | 出典 | 深刻度 | 推定根本原因 | 優先度目安 |
|---|---|---|---|---|---|
| 1 | 【2026-07-10実データで確定】BA4の統一生成アーキテクチャで`used_fallback`が2026-07-06 19:50のマージ以降常にFalse固定になり、旧来"completed_with_fallback"として吸収されていた失敗が全て"failed"として計上されるようになった。60日間のcompleted_with_fallback件数（13件、06-28〜07-05のみ）が実データで裏付け済み | 本タスク2.1節・6.2節（実ログ確認済み） | 高 | アーキテクチャ変更（BA4）に伴うフォールバック機構の消失 | 高（response_error_rate上昇の寄与要因の一つと確定。ただし単独で3.6倍全てを説明できるかは未確定、6.4節参照） |
| 1b | 【2026-07-10新規発見・実データで確定】`response_error_rate`が、X投稿自動生成の品質フィルタ却下（`x_post_generator.py::_log_filter_rejection()`、正常動作）を`status="failed"`として恒常的に誤カウントしている。直近14日のfailedサンプル16件中14件がこれに該当 | 本タスク6.1節（実ログ確認済み） | 高 | メトリクス設計の欠陥（自己フィルタ却下と真の障害が同じstatus値を共有） | 高（response_error_rateの絶対値を常に押し上げている。修正方針は6.1節参照） |
| 1c | 【2026-07-10調査・解決済みとして記録】2026-07-06 11:36-37の2件のRuntimeError（`'PersonaRewriteResult' object has no attribute 'text'`）はBA4マージ（同日19:50）以前の旧・二段階生成アーキテクチャで発生した一時的な問題。該当コード経路は現在のコードベースに存在せず再現しない | 本タスク6.3節（journalctlで確認済み） | 低（解決済み） | 旧アーキテクチャの一時的な不具合（詳細機序は特定不能） | 低（対応不要、記録のみ） |
| 2 | 【2026-07-10修正済み】`memory_extractor.py`の事実抽出プロンプトが既存fact一覧をLLMに見せておらず（当初の想定「5件に制限」ではなく実際は0件だったことを7.1節で確認）、category/key表記ゆれによる意味的重複が`user_fact_items`に蓄積し続ける構造的欠陥。B1ハイブリッド検索で関連事実を事前検索しプロンプトに注入する方式に修正、スクラッチテスト4件・既存16件とも成功 | 本タスク2.2節・7章（コード確認・修正済み、実データでの効果未検証） | 高→修正済み | 設計上の欠陥（重複防止が完全一致キーのみ） | 対応済み。効果は運用者側でのSB-3再計測が必要（7.6節） |
| 2b | 【2026-07-10新規発見・未修正】`experience_layer.py::consolidate_episodic_memory()`（B2週次バッチ）にも#2と同一の構造的欠陥が存在する。バッチ形状の違いにより#2と同じ修正パターンを単純流用できず、別途クエリ戦略の設計が必要 | 本タスク7.7節（コード確認済み） | 中 | 設計上の欠陥（#2と同型、B2固有の分岐） | 中（次タスクとして切り出すことを推奨） |
| 3 | `self_model.py::_analyze()`が`TaskType.SELF_REFLECT`ルーティングをバイパスし生のOpenAIクライアントを直接使用。LOCAL_LLM_ENABLEDでも常にOpenAI課金・Ollama非対応 | 本タスク3.2節（コード確認済み、新規発見） | 中 | 既知バグパターン（TaskTypeバイパス）の再発 | 中 |
| 4 | `orchestrator/persona_rewriter.py`一式が呼び出し元ゼロのデッドコード。旧アーキテクチャの残骸で、インシデントレポートが誤ってこれを懸念経路として名指ししていた | 本タスク3.3節（コード確認済み、新規発見） | 低〜中 | アーキテクチャ変更（BA4）後の未整理 | 中（削除するか、フォールバック機構として復活させるか要判断） |
| 5 | 【2026-07-10修正済み】decision由来テストセット0件の原因を実データで特定（42/42件が例外なくmemory_refs空、蓄積不足ではなく完全なゼロ充足率）。`decision_log.py`の`facts_context`がグローバル重要度順の固定上位15件だったため、決定内容と無関係な事実しか見せられていなかったのが原因。B1検索で関連事実を注入する方式に修正、スクラッチテスト3件・既存16件とも成功 | 本タスク2.4節・9章（DB実データ・コード確認・修正済み） | 中→修正済み | 設計上の欠陥（memory_extractor.pyと同型、9.3節） | 対応済み。効果は運用者側での次回decision記録時のmemory_refs確認が必要（9.5節） |
| 6 | B群6機能（B2/B6/B14/B15/B16/B9）が同一の「週次抽出→グローバルテーブル→TTLキャッシュ」パイプラインを重複実装しており、複数の報告書で統合が推奨されたまま未着手 | phase_b9_report.md, phase_b16_report.md, phase_b_summary.md | 中 | リファクタリング先送りの累積 | 中（機能追加のたびに保守コストが増える） |
| 7 | B1〜B17の全17機能が実モデルAPI・実DBでの効果測定を一度も経験しないままリリースされている | phase_b_summary.md 4章item2 | 中 | 開発環境の制約（本番アクセス権限なし）の慢性化 | 中（C-full以降の継続測定で徐々に解消されるべき） |
| 8 | 【2026-07-10解消済み】各報告書時点で未適用と記録されていたマイグレーションについて、44件全てが本番Supabaseに適用済みであることを実データで確認した | 本タスク8章（海星さんによるSQL実行結果で確認済み） | 解消済み | （過去の懸念、現在は該当なし） | 対応不要。他の調査結果への影響は8.3節参照 |
| 9 | BA4追補10章: B3自動確認質問の文脈無関係表示問題が根本修正されず、デフォルト無効化（killswitch）でのみ回避されている | phase_ba4_report.md 10章 | 低〜中 | 恒久修正の先送り | 低（現状は無効化で実害なし、再有効化時に要対応） |
| 10 | BA4追補11〜15章: フロントエンドのstreaming表示ちらつき問題が複数回の対応でも根本解決せず、応答時間表示機能自体を撤去する結果になった | phase_ba4_report.md 11-15章 | 低 | assistant-ui/Markdown/streaming間の相互作用が未解明 | 低（機能撤去により実害は現状なし） |
| 11 | Phase A4のCAS機構はクロスセッション分岐（2台目クライアントの古い履歴での上書き）を解決していない、既知の設計上の限界 | phase_a4_report.md 5章item2, phase_a5_report.md 6章 | 中 | 設計判断（差分アペンド方式への転換は未実施） | 低〜中（発生頻度は低いと推測されるが、データ損失の可能性がある） |
| 12 | fire-and-forgetタスク群（memory_extractor, _cognitive_layer_bg等）が例外を記録するのみでリトライ・失敗検知機構を持たない | global_state_migration_audit.md 4章・9章 | 中 | 設計判断（signal-and-forgetの限界） | 低〜中（グローバル状態設計等、今後この上に重要機能を積む場合は再検討必須） |
| 13 | `self_narrative.py`内で隣接する`except`ブロック間でログ出力の有無が不統一（同一関数内で1つだけ`logger.warning`、残り4つは無言`pass`） | 本タスク3.2節（コード確認済み、新規発見） | 低 | 実装の書き漏れの可能性 | 低 |
| 14 | 埋め込みのprovenance（生成モデル）を追跡する列がなく、Ollama/OpenAI由来のembeddingが同一列に混在しうる | phase_a5_report.md 7章item1 | 低〜中 | 設計判断（列追加が見送られた） | 低（実害が顕在化した報告はまだない） |
| 15 | ファイル/画像添付がPhase A1-b以降`/chat`経由で送信できない機能後退が未修正のまま | phase_a1b_report.md 6章item1 | 中 | オーケストレーター経路移行時の機能欠落 | 中（ユーザー向け機能の欠落として体感されうる） |
| 16 | 公開ランディングページに無料枠上限に関する矛盾した文言が残存 | incident_free_limit_removal_report.md 5章item1 | 低 | 対外文言の更新漏れ | 低 |
| 17 | `sigmaris_decision_log`の実データ蓄積量・`insufficient_data`への転落頻度が一度も確認されていない（B13〜B16が依存） | phase_b9_report.md, phase_b_summary.md | 中 | 運用データの未観測 | 中（#5の調査結果と合わせて評価すべき） |
| 18 | 多数の暫定チューニング定数（B1/B7/B8/B11/B14/B15/B16/B17/SB-3の各種閾値）が実データ未検証のまま本番稼働している | 1.1節item4、各該当報告書 | 低（個々は） | チューニング不足 | 低（運用データが十分蓄積してから一括見直しが効率的） |
| 19 | 【2026-07-10修正済み】`decision_type`が42件中41件`action`に偏っていた原因（プロンプトが5種類中2種類しか例示していなかった）を特定し、5種類全てを定義付きで列挙するよう修正。スクラッチテスト5件・既存16件とも成功 | 本タスク10.1〜10.2節（コード確認・修正済み） | 中→修正済み | プロンプト設計の不備（enum未明示） | 対応済み。効果は数週間の運用後に分布を再確認する必要あり（10.5節） |
| 20 | 【2026-07-10発見・一部修正】B2(`experience_layer.py::consolidate_episodic_memory()`)にmemory_extractor.py/decision_log.pyと同型の欠陥（既存事実を見せずに新規category/keyを発明）を確認し修正。同型の欠陥がB9(`knowledge_graph.py`)・B14(`extract_preference_patterns()`)・B16(`goal_alignment.py`)にも存在することを新たに確認したが、この3箇所は未修正のまま次タスクへ申し送り | 本タスク10.3〜10.4節（コード確認済み、B9/B14/B16は未修正） | 中 | 設計上の欠陥（横展開、9件目の同型欠陥） | 中（B9/B14/B16の修正は次タスクへ申し送り、10.4節） |

---

## 5. 次タスクへの申し送り

本タスクでは一覧化のみを行い、修正は一切試みていない。次タスクでの判断材料として:

- **#1・#1b・#1cはサーバーアクセスによる実データ調査（6章）で解決・確定した。** #1cは対応不要。#1（フォールバック機構の消失）と#1b（X投稿フィルタ却下の誤カウント）は、それぞれ6.2節・6.1節に示した修正方針案（実装はしていない）から次タスクで対応を判断すること。特に#1bは即座に着手可能な小さな修正（案A: `caller_agent_id`によるフィルタ除外）であり、費用対効果が高いと考えられる。
- **#2（memory_duplicate_rateの構造的欠陥）はまだ実データでの裏付けができていない**（duplicate_clustersの実内容確認、2.2節の運用者向け手順が未実施）。response_error_rateと同様、実データ調査を行うことを推奨する。
- **#8（マイグレーション適用状況の確認）は他の多くの調査結果の前提を左右する**ため、他の対応に先立って運用者側で確認することを推奨する。
- #4（persona_rewriter.pyのデッドコード化）は、削除するか、#1で失われたフォールバック機構として意図的に復活させるか（6.2節の案A/案B）の設計判断が必要。単純な削除では#1の根本対策にならない点に留意。

---

## 6. 追加調査（2026-07-10）: `response_error_rate`の実測調査（サーバーアクセス実施後）

**調査日**: 2026-07-10
**性質**: 前回（2.1節）はサーバー・DBアクセスができない環境での仮説提示にとどまっていた。今回は運用者にTailscale経由のSSH・`agent_invocation_audit_logs`へのクエリを実行してもらい、その結果（本節はその生データに基づく）を基に調査した。**本節でも一切のコード変更は行っていない。**

### 6.0 データ取得の経緯

運用者に以下を依頼し、結果を共有してもらった:
- A1: `agent_invocation_audit_logs`の日次status別件数（直近30日）
- A2: `status='failed'`のerror_code分布（直近14日）
- A3: `status='completed_with_fallback'`の日次件数（直近60日）
- A4: `status='failed'`の詳細サンプル（直近14日、16件）
- 2026-07-06 11:30〜11:45のjournalctlログ（`sigmaris-backend`）

なお、調査の初期段階で運用者から「HTTP 401が6件、HTTP 404が6件、target_agent_id:"agent"からの失敗」という要約が共有されたが、これは実際にA4で共有されたデータ（`error_code`列はnullまたは`RuntimeError`のみ、`target_agent_id`は`content_filter`または`schedule-agent`のみ、401/404という値はどこにも存在しない）と一致しなかった。本節の調査は、この要約ではなく**実際にペーストされたA1/A2/A4の生データそのもの**に基づいている。この食い違いの原因は特定できていない（別のクエリ結果との混同の可能性があるが、確認は取れていない）。

### 6.1 発見1（確定）: `response_error_rate`がX投稿のフィルタ却下を「失敗」として誤カウントしている

A4の16件の`status='failed'`サンプルのうち、**14件**が`target_agent_id="content_filter"`、`target_endpoint="generate_post"`、`error_code=null`、reasonが「品質スコアX/10（...）」という日本語の文言だった。

コードを確認したところ、これは`x_post_generator.py::_log_filter_rejection()`（136-159行）が書き込んでいるものと断定できる。このX投稿自動生成機能（`generate_post(post_type, max_tries=3)`、564行〜）は、生成したツイート候補が品質・プライバシー・コンテンツフィルタのいずれかで却下されるたびに、**`status="failed"`**として`agent_invocation_audit_logs`に1行記録する（152行）。これは1回のX投稿生成サイクルにつき最大3回発生しうる**通常の・意図された動作**であり、システムの異常や不具合ではない（低品質な下書きを自己判定で捨てて再生成しているだけ）。

このコード自体は2026-06-27（コミット`6837ad6`）以降変更されておらず、`response_error_rate`のスパイクが起きた時期に新たに発生した問題ではない。**恒常的に`response_error_rate`を実際の値より高く見せている構造的な要因**であり、直近のスパイク固有の原因ではないが、`status='failed'`を単純集計する現在の`compute_response_error_rate()`の定義そのものに欠陥がある。

`agent_invocation_audit_logs`にはユーザーの/chat経由の失敗と、この種のバックグラウンド自己フィルタリングの「失敗」が同じ`status='failed'`という値で混在しており、後者の量（X投稿生成の頻度、フィルタの厳しさ、投稿の試行回数など）が変動すれば、ユーザー向けチャット機能には何の変化がなくても`response_error_rate`は変動しうる。

**修正方針案（実装はしていない、方針の提示のみ）**:
- **案A（推奨、スキーマ変更不要）**: `eval_metrics.py::compute_response_error_rate()`が集計対象とする行から、`caller_agent_id='x_filter'`（または`target_agent_id`が`content_filter`/`privacy_filter`/`private_facts_filter`のいずれか）の行を除外する。`eval_runner.py::_fetch_recent_audit_statuses()`のSELECT条件に`caller_agent_id=neq.x_filter`を追加するだけで済み、DBスキーマ変更・マイグレーション不要。最も影響範囲が小さい。
- **案B（より根本的、マイグレーション要）**: `_log_filter_rejection()`が書き込む`status`列の値を`"failed"`ではなく専用の値（例: `"self_rejected"`）に変更する。`agent_invocation_audit_logs`テーブルのCHECK制約（`status in ('started','completed','completed_with_fallback','failed')`）を拡張するマイグレーションが必要。案Aより意味的に正確だが、影響範囲がテーブル定義に及ぶ。
- どちらの案でも、修正後は`response_error_rate`の過去との連続性が失われる（同じ計算式でも対象行が変わるため）。修正時は「この時点で定義が変わった」ことをレポートまたはコードコメントに明記することを推奨する。

### 6.2 発見2（確定）: `completed_with_fallback`はBA4のマージ以降、構造的に発生しなくなっている

A3（60日間の`completed_with_fallback`日次件数）の結果:

| day | n |
|---|---|
| 2026-07-05 | 1 |
| 2026-07-04 | 4 |
| 2026-07-03 | 6 |
| 2026-06-29 | 1 |
| 2026-06-28 | 1 |

60日間を通して`completed_with_fallback`が記録されているのはこの5日間（06-28〜07-05、合計13件）のみで、**2026-07-06以降は1件も存在しない**。これはBA4の統一生成アーキテクチャ導入コミット（`3a46e89` "Integrate Sigmaris response generation"、2026-07-06 19:50）が、`orchestrator/service.py`の`used_fallback`変数を全経路で`False`固定にしたこと（2.1節で確認済み）と時期が正確に一致する。**2.1節で提示した仮説（フォールバック吸収機構の消失）は、この実データにより裏付けられたと判断してよい。**

なお、`completed_with_fallback`自体は2026-06-28以前の60日間（すなわち06-28より前）にも1件も存在しておらず、この機構は06-28〜07-05の約1週間だけ実際に機能していたことになる。それ以前の期間にフォールバックが一度も発生しなかった理由（そもそも遭遇するケースが少なかったのか、それより前は別の実装だったのか）は今回のデータからは分からない。

**扱い方針案（実装はしていない、方針の提示のみ）**:
- **案A: フォールバック機構を統一生成アーキテクチャに合わせて復活させる。** 現在の単一パス生成（`call_schedule_agent()`一発呼び出し）で、fact guardや整合性チェックに相当する失敗が起きた場合に、例外を伝播させて`"failed"`にする代わりに、生のschedule-agent出力をそのまま返す`"completed_with_fallback"`として吸収する経路を新設する。ユーザー体験としては「エラー画面が出る」より「多少スタイルが整っていない応答が返る」方が望ましいと考えられ、response_error_rateの見かけ上の改善にもなるが、fact guardが本来検出すべき問題（事実不整合等）を隠蔽するリスクとのトレードオフがあるため、設計判断が必要。
- **案B: 現状を追認し、`used_fallback`関連の死んだ変数・`completed_with_fallback`ステータス・関連コメントを整理する。** 統一生成アーキテクチャは「失敗したら例外を上げて素直に失敗として扱う」という設計だと割り切り、常に`False`にしかならない`used_fallback`変数と、事実上使われなくなった`completed_with_fallback`というstatus値（DBのCHECK制約に残ったまま）を、意図的な設計としてコメントに明記するか、あるいは削除する。この場合`response_error_rate`の「本来の値」は現状のままで正しいことになるが、根本原因（#1で述べたBA4の失敗吸収機構の消失）自体への対策にはならない点に留意。
- いずれの案を採るにせよ、`orchestrator/persona_rewriter.py`（3.3節、呼び出し元ゼロのデッドコード）を削除するか復活させるかの判断とセットで検討すべき。

### 6.3 発見3（確定・解決済みとして記録）: 2026-07-06の2件のRuntimeErrorは、BA4マージ前の旧アーキテクチャの一時的な問題であり、現在は再現しない

`journalctl -u sigmaris-backend --since "2026-07-06 11:30" --until "2026-07-06 11:45"`の結果、A4で確認された2件の`RuntimeError`（11:36:58、11:37:34、`target_agent_id="schedule-agent"`、duration_ms 3663/8847）に対応する以下のエラーメッセージが確認された:

```
ERROR: 'PersonaRewriteResult' object has no attribute 'text'
```

このタイムスタンプ（2026-07-06 11:36〜11:37）は、BA4統一生成アーキテクチャのマージコミット（`3a46e89`、同日19:50）より**約8時間前**である。コード履歴を確認したところ:

- `orchestrator/persona_rewriter.py`（`PersonaRewriteResult`の定義）は2026-06-29のコミット（`b387b2d`）以降変更されておらず、当該エラー発生時点でも現行と同一の内容だった。`PersonaRewriteResult`は`text: str`フィールドを持っており、定義上は`.text`アクセスが失敗する理由はない。
- エラー発生時点（07-06 11:36時点）で稼働していたと見られるコード（直前のコミット`d7a1493`、07-05 11:31時点の`orchestrator/service.py`）を確認したところ、旧・二段階生成アーキテクチャ（`call_schedule_agent()`でドラフト生成 → `rewrite_with_persona()`でpersona rewrite）がまだ現役で、890-895行目で`rewrite = await rewrite_with_persona(...)` に続けて`rewrite.text`にアクセスするコードが存在した。エラーメッセージの形（`'PersonaRewriteResult' object has no attribute 'text'`）はこの呼び出し箇所の形状と一致する。
- `PersonaRewriteResult`という名前のクラスはリポジトリ全体で`persona_rewriter.py`にしか定義されておらず、名前空間の衝突による誤解釈の可能性は排除できた。
- ただし、フィールドが定義上存在するにもかかわらずなぜ`AttributeError`相当のメッセージが出たか（`await`漏れによるコルーチンオブジェクトの取り違え、あるいはガード処理内での例外ラップ等の可能性はあるが）の内部的な発生機序そのものは、当時のプロセス状態を直接観測できない以上、これ以上は特定できなかった。

**重要な事実として確定できるのは以下の点である**: このエラーを引き起こしたコード経路（旧・二段階生成アーキテクチャの`rewrite_with_persona()`呼び出し）は、同日19:50のBA4マージによって完全に置き換えられ、現在のコードベースには一切残っていない（`persona_rewriter.py`は3.3節で確認した通り呼び出し元ゼロのデッドコード）。したがって、**この特定の失敗モードは現在のコードでは再現しえない**。60日間のデータでもこの2件以外に同種のエラーは確認されておらず、単発の過去の問題として扱ってよい。**この項目については追加の対応は不要と判断する。**

### 6.4 総合評価: `response_error_rate`スパイク（0.049→0.177）の原因

今回の調査で「これが直接の原因である」と単一の要因に断定することはできなかったが、以下の2つの構造的要因が複合していると考えられる:

1. **`response_error_rate`の定義そのものが、X投稿フィルタの自己却下（正常動作）を「エラー」として恒常的に誤カウントしている（6.1節）。** これは06-27以降ずっと存在する定義上のノイズであり、スパイク固有の原因ではないが、指標の絶対値を常に押し上げている。
2. **BA4（2026-07-06 19:50）が`used_fallback`によるフォールバック吸収機構を消失させ、以前なら`"completed_with_fallback"`として非エラー扱いされていたはずの失敗が、それ以降すべて`"failed"`としてエラーに計上されるようになった（6.2節、実データで裏付け済み）。** ただし60日間のfallback件数自体は13件と少量であり、これだけで0.049→0.177という3.6倍の変化の全てを説明できるかは、今回集めたサンプル数（A4の16件、A1の日次集計）だけでは断定できない。

なお、2026-07-06朝に発生した2件のRuntimeError（6.3節）はBA4マージ以前の旧コードの問題であり、スパイクの直接原因ではない（マージ後の時期にも別途failedが発生しているため）。

**さらなる調査が必要な場合の追加手順**: 0.049（旧値）が実際にいつ・どの`error_window_days=7`のウィンドウで計測されたものかが分かれば、そのウィンドウ内の`agent_invocation_audit_logs`を同様に`caller_agent_id`で層別集計し、「X投稿フィルタ起因」対「schedule-agent起因」の内訳比率が新旧でどう変化したかを直接比較することで、6.4節の2つの要因の寄与度をより正確に切り分けられる。今回は0.049計測時点の正確な日付・ウィンドウが分からなかったため、この比較はできていない。

---

## 7. `memory_duplicate_rate`の修正（2026-07-10）

**タスクの性質**: 前回（2.2節）の仮説を検証した上で、実際にコードを修正した初の実装タスク。本番稼働中のため作業用ブランチ（`fix-memory-duplicate-rate`）で実施。

### 7.1 仮説検証の結果

依頼元の想定は「`memory_extractor.py`が既存の類似事実をコンテキストとして渡す件数が5件程度に制限されている」というものだったが、`memory_extractor.py`を精読した結果、**この想定は不正確であることが判明した**。実際には:

- 事実抽出プロンプト（`_PROMPT`、修正前）は、その時点の会話（直近20メッセージ）のみを含んでおり、**既存事実は1件も含まれていなかった**。「5件に制限」ではなく「0件」が実態である。
- 抽出後に呼ばれる`get_fact_items(jwt)`（修正前の109行目）は上限なしで**全件**取得しており、5件制限はここにも存在しない。この結果は`confidence_map`という`(category, key)`の完全一致のみを見る辞書に変換され、**LLMには一切見せられず**、「同じcategory/keyの事実が既存にあり、かつそちらの方が確信度が高い場合にのみ新規upsertをスキップする」という最終防御としてのみ使われていた。

つまり実際の欠陥は「コンテキストが狭い」ではなく、「LLMが既存事実を一切参照せずに毎ターンcategory/keyをゼロから発明しており、事後の重複防止も完全一致でしか機能しない」という、依頼元の想定よりも根が深いものだった。表現が違うだけの同一事実（例: `preferences/favorite_color`と`lifestyle/color_preference`）は、DBのUNIQUE制約にも、この完全一致チェックにも引っかからず、そのまま2行として登録され続ける構造だったことが確定した。

### 7.2 重複パターンの分析（SB-3クラスタの実データは未確認）

今回のタスクでは、SB-3が実際に検出した46クラスタの中身（`sigmaris_eval_runs.details.duplicate_clusters`）には**アクセスしていない**（本タスクの指示は「サーバーアクセスやAPIキーの追加取得を試みる必要はない」としており、直近の`response_error_rate`調査タスクのように運用者に個別クエリの実行を依頼することもしなかった）。したがって、実際の46クラスタが本当に「category/keyの表記ゆれ」パターンなのかは、**引き続きコードから読み取れる構造的な推論にとどまり、実データでの確認はできていない**。

7.1節で確定した構造的欠陥（LLMが既存事実を見ずに独立にcategory/keyを発明する）は、`memory_extractor.py`（毎ターン実行、fire-and-forget）だけでなく、`experience_layer.py::consolidate_episodic_memory()`（Phase B2、週次バッチ、エピソード→意味記憶への昇格）の抽出プロンプト（`_CONSOLIDATE_PROMPT`）にも**全く同一の形で存在する**ことをコードで確認した。こちらも既存の`user_fact_items`を一切参照せずに`category`/`key`を提案し、`upsert_fact_item()`で書き込む。この事実は7.6節「気づいた懸念点」に記載し、本タスクでは修正対象に含めていない（7.3節で判断根拠を述べる）。

### 7.3 修正方針とその判断根拠

依頼元が提示した(a)(b)の選択肢のうち、**(a)（既存事実の確認範囲拡大、B1ハイブリッド検索の再利用）のみを実装し、(b)（事後の重複統合バッチ新設）は見送った。**

**(a)を選んだ理由**:
- 7.1節で確定した根本原因（LLMが既存事実を見ていない）に対する直接的な対処になる。依頼元の指示文も「B1のハイブリッド検索を使って実際に類似度の高い既存事実を検索してから渡す方式」を優先的に検討するよう明示していた。
- `memory_extractor.extract_from_conversation()`は`orchestrator/service.py`の`_extract_facts_bg()`経由でfire-and-forgetのバックグラウンドタスクとして実行されており（`asyncio.create_task`、ユーザーへの応答を待たせない）、応答経路のレイテンシ予算を消費しない。既存の検索インフラ（`memory_search.search_relevant_memories()`、B1のベクトル+trigramハイブリッド検索）をもう1回追加で呼び出すコストは、この文脈では許容できると判断した。

**(b)を見送った理由**:
- (a)が新規重複の発生そのものを防ぐのに対し、(b)は「発生した重複を後から統合する」という事後対応であり、要件2（新規に抽出される事実が重複しにくくなること）に対しては(a)だけで直接的に応えられる。
- (b)は本番の`user_fact_items`データを書き換える統合バッチであり、依頼元の注意事項が明示的に警告する「誤った統合が起きないよう慎重に設計すること」という高いリスクを伴う。7.2節で述べた通り実際のクラスタ内容を確認できていない状態で統合ロジックを設計すると、誤統合のリスクを正しく評価できない。
- 依頼元の指示自体が「判断に迷う場合は、既存データのクリーンアップは別タスクとして先送りし、本タスクでは『新規の重複を防ぐ』ことに専念してよい」と明示的に許可しており、この状況はまさにその「判断に迷う場合」に該当すると判断した。
- 過剰実装を避けるという指示（「(a)(b)は排他的ではないが、必要十分な対応に留めること」）にも合致する。まず(a)を投入し、その効果をSB-3の指標推移で観察してから、それでも改善が不十分な場合に(b)を独立したタスクとして検討する方が、段階的でリスクが低いと判断した。

### 7.4 実装詳細

`backend/app/services/memory_extractor.py`を修正した。

1. **`_build_existing_facts_context()`（新規関数）**: 会話中の直近のユーザー発言（`_latest_user_text()`で取得）をクエリとして、`memory_search.search_relevant_memories()`（B1のハイブリッド検索をそのまま呼び出し、新規の検索ロジックは実装していない）で既存事実を最大8件（`_EXISTING_FACTS_SEARCH_LIMIT`）取得し、`"- category/key: value"`形式の文字列に整形する。
2. **`_PROMPT`の変更**: 上記の整形済みコンテキストを`## 既に記録されている関連事実`セクションとして注入し、「既存事実と実質的に同じ内容の場合は、既存と全く同じcategory/keyを使うこと」という明示的な指示を追加した。
3. **フェイルセーフ**: 検索自体が失敗した場合（`search_relevant_memories()`が例外を送出した場合、あるいは`user_id`が解決できない場合）は、既存コンテキストを`"（なし）"`として抽出処理自体は継続する（`extract_from_conversation()`本体の「例外を投げない」という既存の契約を壊さないため）。
4. **`user_id`引数の追加（オプショナル）**: `extract_from_conversation()`に`user_id: str | None = None`を追加。呼び出し元がすでに`user_id`を持っている場合（`orchestrator/service.py`の`_extract_facts_bg`）はそれを渡すことで`get_current_user()`の冗長な呼び出しを避け、持っていない場合（`bench_pipeline.py`の独立したベンチマーク経路）は内部で`get_current_user(jwt)`から導出する形にフォールバックする。`orchestrator/service.py`側は1行の変更（`user_id=user_id`を追加）のみで、`bench_pipeline.py`側は変更していない（フォールバックが自動的に機能するため）。
5. 事後の完全一致confidence比較（`confidence_map`によるスキップ判定）は変更していない。今回追加した仕組みは「重複を作る前に防ぐ」層であり、この既存の仕組みは「それでも完全一致が起きた場合の最終防御」として引き続き有効に機能する。

マイグレーションは不要（スキーマ変更なし、既存のB1検索RPCをそのまま再利用しているため）。

### 7.5 既存データのクリーンアップについて

**見送った。** 7.3節で述べた通り、(b)（事後統合バッチ）自体を見送ったため、既存の176件の重複に対する遡及的な統合処理は本タスクでは一切行っていない。既存の`user_fact_items`データへの書き込み・削除・統合は本タスク中一切実施していない（本番記憶データは読み取りすら行っていない）。

### 7.6 テスト結果

`backend/tests/`には新規テストを追加していない（このセッションの既定の方針: 新規テストはスクラッチディレクトリに作成し、`backend/tests/`は既存の16件のまま維持する）。スクラッチディレクトリに4件のテストを作成し、以下を確認した:

- `search_relevant_memories()`が直近のユーザー発言をクエリとして正しく呼び出され、その結果が実際にLLMへ送るプロンプト文字列に反映されること（`"preferences/favorite_color: 青が好き"`のような行が実際にプロンプトに含まれることを直接assertした）。
- `user_id`を呼び出し元が渡した場合、`get_current_user()`が呼ばれないこと（冗長な呼び出しの回避）。
- `user_id`を渡さなかった場合、`get_current_user(jwt)`から正しく導出されること。
- 検索自体が例外を送出した場合でも、抽出処理全体は例外を投げずに完走し、プロンプトには`"（なし）"`が使われること。
- 既存の完全一致confidence比較によるスキップ動作が、今回の変更後も従来通り機能すること（回帰確認）。

結果: スクラッチテスト4件全て成功。

```
4 passed in 2.88s
```

既存の`backend/tests/`（16件）も全て成功し、リグレッションは確認されなかった。

```
16 passed in 2.07s
```

**実モデルAPIでの検証、および修正後の`run_eval.py`（SB-3）再実行による重複率の実測改善見積もりは行っていない。** 本タスクの注意事項が「実モデルAPIでの検証ができない場合、サーバーアクセスやAPIキーの追加取得を試みる必要はない」と明示しており、この環境には引き続き`OPENAI_API_KEY`・Supabase認証情報がないため、モック・単体テストによる論理的な検証にとどめた。**運用者側で`run_eval.py`を再実行し、`memory_duplicate_rate`が実際に低下傾向を示すか（新規重複の増加ペースが鈍化するか）を、数日〜1週間程度の運用後に確認することを推奨する。**

### 7.7 気づいた懸念点・次のステップへの示唆

- **`experience_layer.py::consolidate_episodic_memory()`（Phase B2週次バッチ）にも同一の構造的欠陥が存在する（7.2節）。** ただし単一会話ターンではなく最大100件のエピソードをまとめて処理するバッチ形状のため、「直近のユーザー発言」に相当する自然なクエリが存在せず、今回と同じ「検索してからプロンプトに注入する」設計をそのまま流用できない。クエリ戦略（例: 各エピソードのtitleを個別にクエリとして使う、あるいはLLMが候補を提案した後に候補ごとに事後検索して照合するなど）の設計判断が別途必要であり、次タスクとして切り出すことを推奨する。
- **`decision由来0件`問題への示唆（`docs/sigmaris/bug_inventory.md` 2.4節）**: 今回の修正は、category/keyの表記ゆれによる事実の分裂を将来的に減らす方向に働く。`decision_log.py::detect_and_record_decision()`はLLMが返す`related_fact_keys`（`category/key`形式）を、その時点の`fact_items`から作った`fact_lookup`と完全一致で照合しており、もし同一の実世界の事実が表記ゆれで複数のcategory/keyに分裂していると、LLMが選んだcategory/keyが実際に保存されているものと一致せず`memory_refs`が空になりやすい、という経路が理論上存在する。今回の修正が新規の分裂を減らすことで、この経路での`memory_refs`未充足も間接的に緩和される可能性があるが、**これは推測であり、2.4節で特定した他の要因（decision_log自体の蓄積不足、マイグレーション未適用の可能性）とは独立した話である**。decision由来0件問題そのものの解決には、2.4節末尾に示した運用者向けSQLでの実態確認が引き続き必要。
- 今回の修正により、`memory_extractor.py`の1ターンあたりのfire-and-forget処理に、検索呼び出しが1回追加された（LLM呼び出し自体は増えていない）。バックグラウンド処理であるため直接のユーザー体感レイテンシには影響しないが、B1検索の呼び出し頻度・コストが単純計算で「チャット全ターン分」増える点は、運用コスト監視の対象に加えておくとよい。

---

## 8. マイグレーション適用状況の確認（2026-07-10）

**きっかけ**: 海星さんが`202607210044_sigmaris_improvement_cycles.sql`を開いていたことをきっかけに、「マイグレーション適用は何か必要なものがあるか」という質問を受けた。0章・1.1節item2・4章#8で繰り返し「未適用マイグレーションが本セッションから確認できない」ことを最優先の未解決事項として記録していたため、この機会に海星さんにSupabase SQL Editorで実データを確認してもらい、解消した。

### 8.1 確認方法

44件全てのマイグレーションについて、各マイグレーションが作成・変更するテーブル/列/インデックス/制約の存在有無を`information_schema`・`pg_indexes`・`pg_proc`から一括で確認する検証クエリを作成し、海星さんに実行してもらった。関数のみを変更するマイグレーション（023/029/031/037、`search_fact_memory`/`search_fact_memory_trgm`の再定義）については、同名関数が版を重ねてdrop+recreateされているため、単純な「関数が存在するか」ではなく「関数定義の本文に、その版固有の変更が反映されているか」を確認する形にした。

### 8.2 結果: 44件中44件が適用済み

初回実行では44件中43件が`true`、1件（`202607150037_time_aware_search`）のみ`false`という結果だった。この1件について、検証クエリ自体が`updated_at timestamptz`という型名込みの文字列一致でチェックしていたことが原因の**偽陰性**だったことが判明した。PostgreSQLの`pg_get_functiondef()`は型名を正式名称（`timestamp with time zone`）に展開して返すため、マイグレーションのSQLソース上の表記（`timestamptz`、省略形）とは文字列として一致しない。

型名に依存しない再検証（`pg_proc.proargnames`で関数の戻り値列名一覧を直接確認する方法）を海星さんに実行してもらった結果、`search_fact_memory`・`search_fact_memory_trgm`のいずれも`updated_at`列を実際に返しており、**この1件も適用済みであることを確認した**。

**結論: 現時点でリポジトリに存在する44件のマイグレーション全てが本番Supabaseに適用済みであることを実データで確認した。** 過去の各Phase報告書（Phase A1〜B9等、1.1節item2参照）が繰り返し「未適用」と記録していた状態は、その後のどこかの時点（おそらくPhase B9の申し送り「13件のマイグレーションを作成順に適用すること（最優先）」への対応、または継続的な運用）で解消されていたと考えられる。

### 8.3 この確認による他の調査結果への影響

- **4章#8（本一覧表の最優先項目）は解消したものとして扱ってよい。** 「マイグレーション未適用により機能が実質無効化されている」という可能性は、現時点では排除できる。
- **2.4節「decision由来0件」問題の候補原因のうち、「`202607040026`マイグレーション（decision_log supersede機構）が未適用でpolicy_change系INSERTがCHECK制約で失敗し続けている」という原因3は排除できる。** `sigmaris_decision_log.supersedes`列の存在を直接確認済み。残る候補（decision_log自体の蓄積不足、LLMが`related_fact_keys`を返さない/一致しない）に絞り込まれたことになるが、これらの実データ確認（2.4節末尾のSQL）は依然として未実施。
- 7.7節で「マイグレーション未適用の可能性」を独立要因として挙げていた記述も、本節により排除された。

### 8.4 今回使った検証クエリの再利用について

今回作成した2本のクエリ（全件一括チェック、および037の型非依存の再検証）はいずれも読み取り専用（`select`のみ）で、副作用はない。今後新しいマイグレーションを追加した際に、同じパターンで検証行を1行追加していけば、同種の確認を継続的に行える。クエリ本体はスクラッチディレクトリに保存したのみで、リポジトリにはコミットしていない（一度きりの確認作業であり、恒久的なツールとして`backend/scripts/`等に追加するかどうかは別途判断が必要と考えたため）。

---

## 9. `decision由来テストセット0件`問題の修正（2026-07-10）

### 9.1 `sigmaris_decision_log`の実データ確認結果

海星さんにSupabase SQL Editorで4本のクエリ（読み取り専用）を実行してもらい、以下が判明した。

**総件数・memory_refs充足率・decision_type内訳（D1）**:

| total | empty_refs | empty_refs_pct | policy_change | proposal | refusal | notification | action |
|---|---|---|---|---|---|---|---|
| 42 | 42 | 100.0 | 1 | 0 | 0 | 0 | 41 |

**42件全て、例外なく`memory_refs`が空である。** これは「充足率が低い」という緩やかな状態ではなく、**完全なゼロ充足**である。

**週次の蓄積分布（D2）**:

| week | n | n_with_refs |
|---|---|---|
| 2025-11-24 | 1 | 0 |
| 2025-12-08 | 2 | 0 |
| 2026-02-16 | 3 | 0 |
| 2026-02-23 | 23 | 0 |
| 2026-06-22 | 7 | 0 |
| 2026-06-29 | 6 | 0 |

約8ヶ月間で42件が断続的に蓄積されており、2026-02-23の週だけで23件（全体の過半数）という大きな偏りがある。全期間を通じて`n_with_refs`（memory_refsが非空の件数）は常に0。

**参照先factの現在アクティブ性確認（D3・D4）**: 「Success. No rows returned」。これは、`memory_refs`が非NULLかつ非空配列のレコードが1件も存在しないことを意味する（D1の`empty_refs=42/42`と完全に整合）。D3が0件で返ってきた時点でD4（D3の集計版）は実行するまでもなく自明（分母がゼロ）と判断し、追加実行は求めなかった。

**結論**: 「蓄積不足」（候補c）ではなく（8ヶ月・42件という量自体は`generate_eval_testset.py`のデフォルト`max_decision_questions=10`を満たすのに十分）、「`memory_refs`が実質的に一度も機能したことがない」（候補a、書き込み側の問題）ことが実データで確定した。「参照先factが後から削除/失効した」（bug_inventory.md 2.4節で挙げていた候補3）という可能性も、そもそも非空のmemory_refsが1件もないため該当しない。

### 9.2 テストセット生成ロジックの条件確認

`testset_gen.py::_build_decision_entries()`（123-137行）を再確認した。条件は単純: `decision.memory_refs`が空でなく、かつ`fact_id_to_key`（現在アクティブなuser_fact_itemsから構築）で1件以上解決できること。この条件を満たさないdecisionは無条件に候補から除外される。**volume（件数）に関する閾値は存在しない** — 1件でもmemory_refsが充足していれば、その時点でdecision由来の設問が生成されうる設計になっている。

したがって、9.1節の実データ（memory_refs充足率0%）と組み合わせると、0件という結果は完全に説明がつく。

### 9.3 特定された原因

`decision_log.py::detect_and_record_decision()`（修正前）を精読した結果、`memory_refs`の充足が構造的にほぼ不可能だった原因を特定した。

`related_fact_keys`（LLMが決定に関連する事実として引用するcategory/key）を導くための材料として、LLMに提示される`facts_context`は、修正前は`build_facts_context(fact_items or [], top_n=15)`——**現在アクティブな全事実（現在505件）の中から、importance_score×confidenceで最も高い、グローバルな上位15件を機械的に抜粋したもの**——だった。この15件は「今回の決定が何についてのものか」とは一切無関係に、常に同じ基準で選ばれる。

現在の事実数（505件）に対して、決定の内容がこの固定された上位15件（全体の約3%）のどれかに偶然一致しない限り、LLMは`related_fact_keys`として引用すべき事実をそもそも提示されていない。これは、**直前のタスク（7章、`memory_duplicate_rate`の修正）で`memory_extractor.py`に発見したのとまったく同じ構造の欠陥**——「LLMに、今回の文脈に関連する既存データを見せず、固定的・グローバルなリストしか見せていない」——が、`decision_log.py`にも独立に存在していたことになる。42件全件が空という完全なゼロ充足率は、この仮説と整合する（偶然一致する確率が低いことを踏まえれば、たまに1〜2件成功していてもおかしくないところ、実際には一度も成功していない）。

なお、D1で判明した「41/42件が`decision_type=action`」という内訳の偏りについては、`_DETECT_PROMPT`のJSON出力例が`"policy_change または proposal"`しか例示していないにもかかわらずLLMが`action`という(有効だが説明されていない)値を選び続けている、という別の疑問点だが、これは`memory_refs`の充足とは無関係（`action`型でも`policy_change`型でも同じロジックで`related_fact_keys`を扱っている）と判断し、本タスクでは深追いしていない。9.6節に懸念点として記録する。

### 9.4 選択した対応: (a) `decision_log.py`の`memory_refs`充足ロジックを修正

3つの選択肢のうち、**(a)（書き込み処理の修正）を選択した。** (c)（時間経過で解消される）は9.1節の実データにより明確に排除される（時間経過ではなく構造的な欠陥であり、あと8ヶ月待っても改善しない）。(b)（テストセット生成側の条件緩和）は、`testset_gen.py`のコード自身のコメントが明記する通り「`memory_refs`が空の決定は、`search_relevant_memories`で採点しようがないため除外する」という、**採点可能性そのものに関わる必須条件**であり、緩和するとdecision由来の設問が生成されても正解判定ができない（あるいは恣意的な正解判定になる）という、要件3（fact由来の質・ロジックへの悪影響回避）に反するより深刻な問題を生む。よって(a)一択と判断した。

**実装内容**:

1. `decision_log.py`に`_build_relevant_facts_context()`を新設。会話の直近ユーザー発言をクエリとして、B1のハイブリッド検索（`memory_search.search_relevant_memories()`、既存インフラをそのまま再利用、新規の検索ロジックは実装していない）で関連度の高い既存事実を最大15件（`_RELEVANT_FACTS_SEARCH_LIMIT`）取得し、`facts_context`として`_DETECT_PROMPT`に注入する。7章の`memory_extractor.py`修正と同一の設計パターン。
2. `jwt`/`user_id`が渡されない場合（既存呼び出し元との後方互換のため両方ともオプショナル引数）、または検索自体が失敗した場合は、修正前の`build_facts_context(fact_items, top_n=15)`（グローバル重要度順）にフォールバックする。フォールバック時も動作は修正前と完全に同一。
3. `detect_and_record_decision()`に`jwt: str | None = None`・`user_id: str | None = None`を追加。
4. `orchestrator/service.py`の`_cognitive_layer_bg()`に`user_id`パラメータを追加し（`jwt`は既にスコープ内にあったのでそのまま渡すだけ）、`detect_and_record_decision()`呼び出しに`jwt=jwt, user_id=user_id`を追加。呼び出し元2箇所（`run_orchestrator_chat`・`run_orchestrator_chat_stream`）は、いずれも既に`user_id`をローカル変数として持っていたため、`user_id=user_id`を1行追加するのみで済んだ。

`related_fact_keys`から`memory_refs`への解決自体（`fact_lookup`、717-721行）は変更していない——これは検索結果ではなく、呼び出し元から渡された完全なfact一覧（`fact_items`、現在アクティブな全505件）から構築されるため、検索が返す上位15件というサブセットに含まれるcategory/keyであれば必ず解決できる。

マイグレーションは不要（スキーマ変更なし、B1の既存検索インフラを再利用しているため）。

### 9.5 テスト結果

`backend/tests/`には新規テストを追加していない（既定の方針通り、スクラッチディレクトリに作成）。3件のテストを作成し、以下を確認した:

- `search_relevant_memories()`が直近のユーザー発言をクエリとして正しく呼び出され、その結果（`"lifestyle/gym_choice: A社ジム"`のような行）が実際に`_DETECT_PROMPT`へ渡されるプロンプト文字列に反映されること。
- LLMが返す`related_fact_keys`が、検索結果由来のcategory/keyであっても、`fact_items`全体から構築される`fact_lookup`経由で正しく`memory_refs`（fact ID）に解決され、`log_decision()`に渡されること（`memory_refs=["fact-1"]`を直接assert）。
- `jwt`が渡されない場合、検索を試みずに修正前と同じグローバル重要度順のコンテキストにフォールバックすること。
- 検索自体が例外を送出した場合でも、決定検出処理全体は例外を投げずに完走し、フォールバックのコンテキストが使われること。

```
3 passed in 1.80s
```

既存の`backend/tests/`（16件）も全て成功し、リグレッションは確認されなかった。

```
16 passed in 2.00s
```

**実モデルAPIでの検証、および修正後の`generate_eval_testset.py`実行によるdecision由来設問の実際の生成確認は行っていない。** 本タスクの注意事項が「実モデルAPIでの検証ができない場合、サーバーアクセスやAPIキーの追加取得を試みる必要はない」と明示しており、この環境には引き続き`OPENAI_API_KEY`・Supabase認証情報がないため、モック・単体テストによる論理的な検証にとどめた。**運用者側で、次回の会話で新たに決定が記録された後（あるいは`generate_eval_testset.py`を手動実行して）、その`sigmaris_decision_log`行の`memory_refs`が実際に非空になっているかを確認することを推奨する。**

### 9.6 気づいた懸念点・残るHigh項目に影響しそうな発見

> **【2026-07-10追記】本節item1（decision_type偏り）・item2（B2への同種欠陥の横展開）は10章で調査・対応済み。**

- **`_DETECT_PROMPT`のJSON出力例が`decision_type`について`"policy_change または proposal"`しか示していないにもかかわらず、実データでは41/42件(97.6%)が`action`という、例示すらされていない値に分類されている（9.1節D1）。** `_VALID_TYPES`には`action`が含まれるため技術的には妥当な値だが、プロンプトがLLMにこの値の使い分けを一切教えていない状態で、LLMが独自の判断でほぼ全件をこの型に分類し続けているのは、決定の分類精度そのものに疑問符がつく状態だと考えられる。本タスクの範囲外として修正はしていないが、次タスクで`_DETECT_PROMPT`のdecision_type例示を全5種類に拡充し、それぞれの使い分けを明記することを検討する価値がある。
- **本タスクの修正（B1検索によるコンテキスト注入）は、7章の`memory_extractor.py`修正と全く同じパターンの、2件目の適用例である。** 同一の構造的欠陥（LLMに文脈非依存の固定リストしか見せない設計）が、ファクト抽出（B4/memory_extractor.py）と決定検出（A3/decision_log.py）という独立した2つのサブシステムに、独立に埋め込まれていたことになる。7.7節で触れた`experience_layer.py::consolidate_episodic_memory()`（B2週次バッチ）も同型の欠陥を抱えていることは既に判明しており、**同種の欠陥が他の「LLMに何かを判定・分類させる」処理にも潜んでいないか、横断的に確認する価値がある**（例: `topic_tracker.py`のトピック遷移検出、`goal_alignment.py`のゴール整合性チェック等、本タスクでは確認していない）。
- 今回の修正により、`_cognitive_layer_bg`の1ターンあたりの処理に、検索呼び出しが1回追加された（7章のmemory_extractor.py修正と合わせると、1ターンあたり2回分のB1検索が新たに追加されたことになる）。いずれもfire-and-forgetのバックグラウンド処理でユーザー体感レイテンシには影響しないが、B1検索の呼び出し頻度・コストの増加は運用コスト監視の対象に加えておくとよい。
- **decision_log.py::analyze_decision_patterns()・extract_preference_patterns()（Phase B14）は、`decision_type`の分布（`type_counts`、`proposal_rate`/`refusal_rate`）を分析対象にしている。** 上記の`action`偏重が続く限り、これらの週次分析の意味のある差別化が乏しくなる可能性がある。今回のmemory_refs修正とは独立の問題だが、関連する既知の懸念として記録しておく。

---

## 10. `decision_type=action`偏りの調査・修正、およびB2への同種欠陥の横展開修正（2026-07-10）

### 10.1 `decision_type=action`偏りの原因調査

`decision_log.py`の`_DETECT_PROMPT`（修正前）を精読した結果、原因を特定した。

- **プロンプトのJSON出力例は`"decision_type": "policy_change または proposal"`という1行のみで、`_VALID_TYPES = {"proposal", "refusal", "notification", "action", "policy_change"}`（コード側が受理する5種類）のうち2種類しかLLMに提示していなかった。** `refusal`・`action`・`notification`という残り3つの値については、それが何を意味するか、いつ使うべきかの説明が一切ない状態だった。
- **コード側に`action`をデフォルト値とするフォールバック処理は存在しない。** `decision_type = parsed.get("decision_type"); if decision_type not in _VALID_TYPES: decision_type = "policy_change"`（修正前後で変更していない）——コードのフォールバック先は`policy_change`であり、`action`ではない。これはテストでも直接確認した（10.4節）。したがって41/42件の`action`は、**LLM自身が能動的に選択した値**であり、パース失敗等によるコード側の後付けデフォルトではないと断定できる。
- LLMがこの値を選んだ理由そのもの（学習データ由来の一般的な分類語彙として"action"が自然に選ばれやすい、等）を直接検証する手段はないが、少なくとも「プロンプトが選択肢を十分に説明していない」ことは確定した事実であり、これが最有力の説明であると判断した。
- なお、同ファイル内の`_EXTRACT_PREFERENCE_PROMPT`（B14）に、`policy_change`のみが「海星さん自身が実際に下した決定・方針転換」で、それ以外（proposal/refusal/notification/action）は「シグマリス側の行動記録」だという既存の使い分け方針が明記されていた。今回の修正はこの既存方針に準拠する形で行った。

### 10.2 `decision_type`偏りの修正

`_DETECT_PROMPT`のJSON出力例を、5種類全ての`decision_type`を列挙し、それぞれに一行程度の定義を付与する形に書き換えた。「自由記述は禁止」であることも明記した。

- `policy_change`: 海星さん自身が方針・ルールを決定または変更した（海星さん本人の決定）
- `proposal`: シグマリスが海星さんに何かを提案した（まだ確定していない）
- `refusal`: シグマリスが海星さんの提案・依頼を断った
- `action`: シグマリスが実際に何らかの操作・行動を実行した（方針決定ではなく処理の実施）
- `notification`: シグマリスが海星さんに何かを知らせた・報告した（他の4つに該当しない場合の最終手段としてのみ）

JSON schemaのプレースホルダ自体も、説明文をそのまま値として埋め込む形（`"decision_type": "以下の5種類の...一つ（...）: - policy_change: ...\n    - proposal: ..."`）を一度検討したが、これは実際のJSON応答としては不正な形（LLMがこの説明文自体をそのままコピーしてしまうリスクがある）と判断し、**説明はJSON schemaの外（prose）に置き、schema内のプレースホルダは`"policy_change | proposal | refusal | action | notification のいずれか一つ"`という簡潔な一行に留めた。** これは判断が分かれうる実装上の選択だったため、根拠を明記しておく。

`notification`について、`notification_budget.py::record_notification()`が既に`log_decision(decision_type="notification", ...)`を直接呼ぶ別経路を持っている（この`detect_and_record_decision()`のLLM検出フローとは無関係）ため、両者の役割が重複しないよう、プロンプト内で「他の4つのいずれにも該当しない場合の最終手段としてのみ選ぶこと」と明記し、detect_and_record_decision側では極力使われないよう誘導した。

### 10.3 B2（`experience_layer.py`）の調査結果

`consolidate_episodic_memory()`（Phase B2週次バッチ、エピソード→意味記憶昇格）の`_CONSOLIDATE_PROMPT`を確認した結果、**`decision_log.py`で発見・修正したのと全く同型の欠陥が存在することを確認した**（これは実は前々タスク・7章の`memory_duplicate_rate`修正時に既に発見していた内容の再確認であり、今回はそれを実際に修正した）。

具体的には、最大100件のエピソード記憶を意味記憶（`user_fact_items`）に昇格させる際、LLMには昇格対象のエピソード群のみが渡され、**既存の`user_fact_items`は一切見せられていなかった。** そのため、昇格させる`category`/`key`をLLMが毎回ゼロから発明しており、既存の類似事実と表記が食い違う形で重複登録される（`memory_duplicate_rate`と同じ問題）リスクを抱えていた。

**修正**: `memory_extractor.py`（7章）・`decision_log.py`（9章・本章）で確立したパターンに倣い、B1のハイブリッド検索で関連する既存事実を検索してからプロンプトに注入する`_build_existing_facts_context_for_consolidation()`を新設した。

ただし、`consolidate_episodic_memory()`は単一の会話ターンではなく最大100件のエピソードを一括処理するバッチ形状のため、「直近のユーザー発言」に相当する自然な検索クエリが存在しない。**このタスクでの設計判断として、対象エピソード群のtitleを`" / "`で連結したもの（最大2000文字にトランケート）を検索クエリとして採用した。** これは、話題が多様なバッチに対しては単一の検索で全ての候補に関連する既存事実を網羅的に拾いきれない可能性がある、という限界を伴う妥協案だが、「既存事実を全く見せない」という修正前の状態よりは明確な改善であり、過剰実装を避けつつ確立済みパターンを再利用するという方針に合致すると判断した。

`jwt`のみを受け取り`user_id`を持たない`consolidate_episodic_memory(jwt)`の呼び出し形状（週次スケジューラから`get_sigmaris_jwt()`のみで呼ばれる）に合わせ、`_build_existing_facts_context_for_consolidation()`内部で`get_current_user(jwt)`により`user_id`を導出する形にした（`decision_log.py`・`memory_extractor.py`で確立済みのフォールバック導出パターンと同一）。検索失敗時は既存事実なし（`"（なし）"`）にフォールバックし、統合処理自体は継続する。

マイグレーションは不要（スキーマ変更なし、B1の既存検索インフラを再利用）。

### 10.4 他の分類系処理への横断確認結果（本タスクでは修正せず、申し送り事項として記録）

指示の通り、以下5箇所を確認したが、**発見した欠陥はこのタスクでは修正していない。**

- **`orchestrator/service.py`**: 独自のLLM分類呼び出し（`TaskType`/プロンプト定数）は存在しない。他モジュールへのオーケストレーションのみで、この欠陥パターンには該当しない。
- **`topic_tracker.py`（B6）**: `detect_and_record_topic_transition()`は「現在アクティブな話題ラベル1件」とのみ比較する設計で、`decision_log.py`/`experience_layer.py`のような「既存アイテムの固定/不在リスト」という構造にはそもそも該当しない。ただし、話題ラベルの重複排除が完全表記一致でしか機能しない（bug_inventory.md 1.3節で既に記録済みの既知の懸念）という、**関連するが異なる種類の問題**を抱えている。
- **`knowledge_graph.py`（B9）**: `extract_entities_and_relations()`（週次バッチ）の`_EXTRACT_PROMPT`は、抽出元となる目標・決定・話題の情報のみを渡しており、**既存の`sigmaris_entities`（エンティティ一覧）を一切見せていない。** `_get_or_create_entity()`は`(name, entity_type)`の完全一致でしかマッチングしないため、LLMが週ごとに微妙に異なるエンティティ名（例:「AdFlow AI」と「AdFlowAI」）を生成すると、同一エンティティが別々のノードとして重複登録されるリスクがある。**decision_log.py・experience_layer.pyと同型の欠陥が存在することを確認した。**
- **`goal_alignment.py`（B16）**: `_ANALYZE_PROMPT`（週次バッチ）も同様に、目標・決定・話題の情報のみを渡しており、**既存の目標整合性フラグ一覧を一切見せていない。** `_upsert_flag()`は`goal_reference`（LLMが生成する短い識別子文字列）の完全一致でのみエビデンスを蓄積するため、表記ゆれがあると同じ乖離が複数の別々のフラグ行に分裂しうる。bug_inventory.md 1.3節が既に「B6の話題ラベル表記ゆれがB16の整合性判定精度にも間接的に影響しうる」と指摘していた懸念と直接関連しており、**decision_log.py・experience_layer.pyと同型の欠陥が存在することを確認した。**
- **B14（`decision_log.py::extract_preference_patterns()`）**: 本タスクで既に`decision_log.py`を扱った延長で確認したところ、こちらも同様に既存の`sigmaris_user_preference_patterns`一覧を一切見せておらず、`_upsert_preference_pattern()`が`pattern_key`の完全一致でのみエビデンスを蓄積する。**同型の欠陥が存在することを確認した。**

**申し送り**: `knowledge_graph.py`（B9）・`goal_alignment.py`（B16）・`decision_log.py::extract_preference_patterns()`（B14）の3箇所に、本タスクで修正した`decision_log.py::detect_and_record_decision()`・`experience_layer.py::consolidate_episodic_memory()`と同型の欠陥が存在することを確認した。次タスクで、同じ「B1検索で関連する既存アイテムを検索してから注入する」パターンによる修正を検討することを推奨する。いずれも週次バッチ処理であり、`consolidate_episodic_memory()`と同様に「単一ターンに相当する自然なクエリが存在しない」というクエリ戦略上の課題を共有しているため、10.3節で採用した「対象データの要約テキストを連結してクエリにする」アプローチが同様に適用できる可能性が高い。

### 10.5 テスト結果

`backend/tests/`には新規テストを追加していない（既定の方針通り、スクラッチディレクトリに作成）。5件のテストを作成し、以下を確認した:

- `_DETECT_PROMPT`をレンダリングした結果に、5種類全てのdecision_typeとそれぞれの定義文（「海星さん本人の決定」「承認待ちの提案」等）が実際に含まれること。「自由記述は禁止」という文言が含まれること。
- 不正な/未知の`decision_type`をLLMが返した場合、コード側のフォールバックが`policy_change`になること（`action`にはならないこと）を直接確認し、10.1節の「コード側デフォルトではない」という判断を裏付けた。
- `experience_layer.py::consolidate_episodic_memory()`が、対象エピソード群のtitleを連結したクエリで`search_relevant_memories()`を正しく呼び出し、その検索結果が実際に`_CONSOLIDATE_PROMPT`へ渡されるプロンプト文字列に反映されること。
- 検索が失敗した場合でも、統合処理全体は例外を投げずに完走し、「（なし）」のフォールバックが使われること。

```
5 passed in 1.19s
```

既存の`backend/tests/`（16件）も全て成功し、リグレッションは確認されなかった。

```
16 passed in 0.74s
```

なお、スクラッチディレクトリには本タスクと無関係な、過去のセッションで作成された陳腐化したテストファイル（`test_classify_intent_lightweight.py`・`test_phase_ba1_service_integration.py`・`test_phase_ba1_stream_integration.py`、いずれも既に削除された`rewrite_with_persona_stream`を参照している）が残っており、スクラッチディレクトリ全体を一括実行すると8件が失敗する。これらは3.1節で既に「BA4関連の陳腐化したスクラッチテスト」として記録済みの既知の状態であり、本タスクの変更や`backend/tests/`の結果には一切影響しない。

**実モデルAPIでの検証は行っていない。** 本タスクの注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない。**運用者側で、次回decision_type分類・エピソード統合が実行された後、実際の分布が改善しているか（`action`偏重が緩和されているか）、B2の統合結果に重複が発生していないかを、数週間の運用後に確認することを推奨する。**

### 10.6 気づいた懸念点

- **10.4節で発見した3箇所（B9・B14・B16）は本タスクでは修正していない、次タスクへの明確な申し送り事項である。** 特にB9・B16は、bug_inventory.md 1.3節で既に「表記ゆれ」問題として一部認識されていたものが、実は根本的には「既存アイテムを見せていない」という、今回3回連続で発見・修正してきたのと同一の構造的欠陥に起因している可能性が高いことが、本タスクで初めて明確になった。
- **decision_typeの5値のうち`refusal`・`notification`は、本タスクの実データ（42件）には1件も出現していない。** プロンプト修正により`action`偏重が緩和された場合、次にどの値へ分布がシフトするか（`policy_change`が増えるのか、`refusal`が新たに現れるのか）は実データでの再確認が必要。
- 今回の一連の修正（7章memory_extractor.py、9章decision_log.py、10章decision_log.py再修正+experience_layer.py）により、B1のハイブリッド検索がバックグラウンドタスクから呼ばれる箇所が着実に増えている（現時点で1チャットターンあたり最大2箇所、週次バッチで1箇所）。B1検索自体の負荷・コストが今後どの程度になるかは、運用データでの継続的な監視が必要（7.7節・9.6節で既に触れた懸念の延長）。
