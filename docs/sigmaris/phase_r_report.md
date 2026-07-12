# Phase R-1(改訂版) 実施報告: 循環トレースの基盤(参照連鎖方式)

**目的:** Experience→Memory→Temporal Evaluation→Belief/Preference Update→Policy Update→Actionという循環の各段階が、「直前段階への参照」を一貫して持っているかを棚卸しし、欠けている箇所を補完する。単一の新規`cycle_id`は導入しない。
**作業ブランチ:** `phase-r1-reference-chain`(mainから新規作成)
**範囲:** 参照構造の棚卸しと補完、および読み取り専用トレース関数の実装。既存機能のロジック変更(検索・ランキング・生成)は行っていない。

---

## 1. 旧`cycle_id`方式の作業状況

改訂版の指示書が届く前に、旧方針(単一`cycle_id`をExperience発生時に発行し、Memory段階まで伝播させる)に基づく実装に着手していた。具体的には以下を実装していた。

- `supabase/migrations/202607220047_cycle_id_provenance.sql`(`sigmaris_experience`/`user_fact_items`への`cycle_id`列追加、`upsert_fact_item` RPCへの`p_cycle_id`追加)
- `orchestrator/service.py`の`run_orchestrator_chat`/`run_orchestrator_chat_stream`での`cycle_id = invocation_id`という値の再利用、`_extract_facts_bg`/`_cognitive_layer_bg`への伝播
- `experience_layer.py`(`record_experience`/`detect_and_record_episode`/`consolidate_episodic_memory`)、`memory_extractor.py`、`user_fact_data.py`、`routes/agent.py`への`cycle_id`引数の追加

**この作業はすべて未コミットの段階で、改訂版指示書の到着を受けて完全に破棄した。** 具体的には、当該ブランチ(`phase-r1-cycle-id-foundation`)を削除し、変更済みだった5ファイルを`git checkout`でmain時点の内容に戻し、追加していたマイグレーションファイルを削除した上で、mainから`phase-r1-reference-chain`ブランチを新規に切り直した。**引き継いだ実装コードは一切ない。** ただし、旧方針の実装作業を通じて得た「`invocation_id`は`run_orchestrator_chat`/`_stream`冒頭で会話ターンごとに1つ発行され、`_extract_facts_bg`・`_cognitive_layer_bg`経由でMemory・Experience双方の書き込みに既に伝播している」というコードベース理解は、本改訂版の2章の棚卸しに直接活用した。

なお、本タスク開始時点のリポジトリには、これより前のセッションで作成されたと思われる`README.md`の未コミット変更、および`docs/network.md`・`docs/infrastructure.md`・`docs/cloudflare-tunnel.md`という未追跡ファイルが存在していた。これらは本タスク(R-1)とは無関係な別タスクの作業中の成果物と判断し、一切変更・破棄していない。

---

## 2. 既存の参照構造の棚卸し結果

循環の各段階(および隣接するA3/B9)が、現状どのような「直前段階への参照」を持っているかを確認した。**結論として、この仕組みはPhase A3・B4の時点で既にかなり広範囲に実装されており、循環全体を貫く参照連鎖は「ゼロから作る」のではなく「棚卸しして欠けを見つける」対象だった。**

| 段階 | テーブル | 直前段階への参照 | 形式 | 出典 |
|---|---|---|---|---|
| Experience | `sigmaris_experience` | 会話ターン(`thread_id`/`invocation_id`) | UUID列ペア | B4(列追加)、B2(`detect_and_record_episode`が実際に値を供給) |
| Memory | `user_fact_items` | (a) 会話ターン直接生成: `thread_id`/`invocation_id`<br>(b) Experience由来(統合): `source_experience_ids` | (a) UUID列ペア<br>(b) UUID配列(jsonb) | B4(a)、B2(b) |
| Temporal Evaluation | `user_fact_items`(別テーブルなし) | 対象Memory行そのもの(`memory_kind`/`valid_from`/`superseded_by`/`last_mentioned_at`はMemory行自身の列) | 該当なし(参照不要) | Temporal Layer Step1〜3 |
| Action(会話内の決定) | `sigmaris_decision_log` | 会話ターン(`thread_id`/`invocation_id`)+根拠Memory(`memory_refs`) | UUID列ペア + UUID配列(jsonb) | A3(列)、B4(`memory_refs`は実は A3以前の`constitution.sql`起源、B4報告書で「既に実装済みと確認」) |
| Belief Update | `sigmaris_user_preference_patterns` | 根拠Decision群(`supporting_decision_ids`) | UUID配列(jsonb) | B14 |
| Policy Update | `sigmaris_goal_alignment_flags` | 根拠Decision/Topic群(`evidence_refs`) | UUID配列(jsonb、decision_log/topic_logのidが混在) | B16 |
| (循環外・補助) | `sigmaris_entity_relations`(B9) | 任意の既存テーブル行(`source_table`+`source_id`) | 汎用ポインタ(テーブル名+UUID) | B9 |

**確認できたこと:**

1. **「1対多を許容する形」は既にほぼ全段階で実現されていた。** `source_experience_ids`・`memory_refs`・`supporting_decision_ids`・`evidence_refs`はいずれも配列(jsonb)で、1つのMemory/Belief/Policy行が複数の直前段階行を根拠にできる設計になっている。
2. **命名・形式は指示書が想定した通りバラバラである** が、いずれも「対象の直前段階行のUUIDを保持する」という役割は一貫して果たせている(3章で1件の例外を発見)。無理な統一は行っていない。
3. **Temporal Evaluationは、独立した「段階」としての参照を必要としない。** memory_kind/valid_from/superseded_by/last_mentioned_atはいずれも`user_fact_items`自身の列であり、評価対象のMemory行と評価結果が同一行に同居しているため、そもそも「別テーブルへの参照」という形が存在しえない。指示書1章が予想した「要確認」の答えは「対象テーブルの列そのものが参照先を兼ねるため、新たな参照は不要」で確定した。
4. **decision_log(Action相当)の`memory_refs`は、A3ではなくさらに前の`202606280021_constitution.sql`で既に定義されていた** ことを確認した(B4報告書1章の記述「`sigmaris_decision_log`は既に完全に実装済み」の根拠列)。当初は「A3で新設」と誤解していたが、実際にはより古い時点から存在する列に、A3〜B4を通じて実際の値が供給されるようになった、という経緯である。
5. **`sigmaris_entity_relations`(B9)の`source_table`+`source_id`という汎用ポインタ方式は、この循環のどの段階にも属さないが、「各テーブルの性質に合った形式でよい」という本タスクの原則を先取りして実装していた良い前例**として記録しておく。

---

## 3. 補完が必要だった箇所とその実装内容

棚卸しの結果、**1箇所だけ、明確に「直前段階への参照としての役割を果たせていない」ものが見つかった。**

### 発見: Policy Update(`sigmaris_goal_alignment_flags`)のMemoryへの参照が実質的に機能していない

`sigmaris_goal_alignment_flags`は`evidence_refs`(decision_log/topic_logのUUID)を持つが、これは「根拠となった決定・話題」への参照であり、**その乖離フラグが対象としている`user_fact_items`(category='goals')の具体的な行への参照が存在しなかった。** 唯一それらしい列は`goal_reference`だが、これは中身を確認したところ以下の通りだった。

- `goal_alignment.py::extract_goal_alignment_flags()`が目標一覧をLLMに渡す際、`f"- key={g.get('key')} value={g.get('value')}"`という形式で**idを一切見せていなかった**(修正前コード)。
- そのためLLMが返せるのは「目標のkeyやvalueの要約」という**自由記述の文字列**のみであり、これは週次実行間の重複排除(文字列一致でのdedup)にのみ使われ、`user_fact_items.id`へ確定的に解決する手段がなかった。
- 他の全段階(`source_experience_ids`・`memory_refs`・`supporting_decision_ids`・`evidence_refs`)がいずれも実UUIDの配列である一方、ここだけがLLM生成の自由記述テキストという性質的に不安定な参照になっていた。

これは「命名・形式はバラバラでよいが、役割は果たせているか」という指示書3章の確認観点に照らして、**役割を果たせていない箇所**と判断し、補完した。

### 実装内容

1. **マイグレーション** `supabase/migrations/202607220047_goal_alignment_fact_refs.sql`(新規、未適用)
   ```sql
   alter table public.sigmaris_goal_alignment_flags
     add column if not exists goal_fact_ids uuid[] not null default '{}';
   ```
   既存の`goal_fact_ids`未読み込みの過去行は空配列のままになる(遡及的バックフィルは行っていない、他の全B群タスクと同じ方針)。
2. **`goal_alignment.py`の変更:**
   - 抽出プロンプトの目標一覧に`id=...`を追加(`f"- id={g.get('id')} key={g.get('key')} value={g.get('value')}"`)。
   - JSON出力スキーマに`goal_fact_id`を追加し、対象目標のidを返すよう指示。
   - 抽出後、**その週次バッチが実際にLLMへ送った目標id集合(`goal_fact_ids_known`)に含まれるものだけを信用する**(`evidence_refs`の既存の検証と全く同じ「LLM生成idを鵜呑みにしない」防御パターン)。解決できない場合は空配列にする(推測で埋めない)。
   - `_upsert_flag()`に`goal_fact_ids`引数を追加し、`evidence_refs`と全く同じ「既存行があれば配列をマージ、なければ新規作成」という蓄積パターンを踏襲。
   - 既存の`goal_reference`列・その用途(LLM向け重複排除コンテキスト・人間向け表示)は一切変更していない — 今回追加したのはあくまで並存するid参照であり、置き換えではない。

この変更以外に、他の段階(Experience/Memory/Action/Belief)では、既存の参照が既に役割を果たせていることを確認できたため、**スキーマ変更は行っていない。**

---

## 4. 動的トレース関数の実装内容

`backend/app/services/cycle_trace.py`(新規)に、読み取り専用のトレース関数を3つ実装した。いずれも新しいテーブル・キャッシュを持たず、毎回既存の参照列を読み直す(supersede・統合等で状態が変わってもトレース結果は常に最新を反映する)。

1. **`trace_memory_to_experience(fact_item)`** — Memory→Experience(1段階)。渡された`user_fact_items`行の`thread_id`/`invocation_id`(直接会話由来)と`source_experience_ids`(統合由来、`sigmaris_experience`を実際に取得)の両方を返す。呼び出し元が既にfact行を持っている前提(二重取得を避けるため、idではなく行そのものを引数に取る)。
2. **`trace_belief_to_memory(pattern_id)`** — Belief Update→Memory(2段階、Action/decision_logを経由)。`sigmaris_user_preference_patterns`の`supporting_decision_ids`→該当`sigmaris_decision_log`群→それぞれの`memory_refs`の和集合(重複排除)→該当`user_fact_items`群、を実際に辿る。中間のdecision行自体も結果に含め、Action段階への参照が失われないようにしている。
3. **`trace_policy_to_evidence(flag_id)`** — Policy Update→evidence(Action/decision_log + topic_log)とMemory(3章の`goal_fact_ids`補完)。`sigmaris_goal_alignment_flags`の`evidence_refs`(decision_logとtopic_logのidが型情報なしに混在)を両テーブルへ`id=in.(...)`で問い合わせ、実在する方だけを結果として拾う設計にした(該当しないテーブルへの問い合わせは0件で返るだけで、実害はない)。`goal_fact_ids`は3章の実装をそのまま解決する。

これらを支える最小限の補助関数(いずれも`id=in.(...)`によるservice-role読み取り、空リストなら通信すら発生させない)を4モジュールに追加した: `user_fact_data.get_fact_items_by_ids`・`experience_layer.get_experiences_by_ids`・`decision_log.get_decisions_by_ids`/`get_preference_patterns_by_ids`・`topic_tracker.get_topics_by_ids`・`goal_alignment.get_goal_alignment_flags_by_ids`。いずれも`mark_facts_mentioned()`(Temporal Layer Step2)や`recompute_adoption_counts()`(B13)が既に確立した`id=in.(...)`パターンをそのまま踏襲しており、新しいアクセス方式は導入していない。

**指示書4章の「循環全体を一度に実装する必要はなく、2段階分でよい」という許容範囲に対し、Memory→Experience(1段階)・Belief→Memory(2段階)・Policy→evidence/Memory(1〜2段階)の3系統を実装した。** Temporal Evaluationは2章の通りMemory行そのものなのでトレース不要、Action(decision_log)→Memoryは`trace_belief_to_memory`の内部で既に辿っている。循環の残り(Policy→Belief間、Action→新Experienceの明示的な逆引き)は5章で申し送る。

---

## 5. テスト結果

いずれもモック(実DB未接続、`unittest.IsolatedAsyncioTestCase`)。scratchディレクトリに作成(`backend/tests/`には追加していない、既定の方針通り)。

```
GetByIdsEmptyShortCircuitTests (4件)
  PASS: get_fact_items_by_ids([]) / get_experiences_by_ids([]) /
        get_decisions_by_ids([]) / get_topics_by_ids([]) が
        いずれもクライアント自体を呼ばずに [] を返すこと

GoalAlignmentGoalFactIdTests (3件)
  PASS: LLMが実際に送った目標一覧に存在しないgoal_fact_id(捏造id)は
        破棄され、goal_fact_ids=[] のまま保存されること
  PASS: 実在するgoal_fact_idは正しく保存されること
  PASS: _upsert_flag()が既存行のgoal_fact_ids/evidence_refsを
        新しい値とマージすること(週次実行を跨いだ蓄積)

CycleTraceTests (5件)
  PASS: trace_memory_to_experience — thread_id/invocation_idのみの行は
        Experience取得を一切呼ばずdirect_turnのみ返すこと
  PASS: trace_memory_to_experience — source_experience_idsがある行は
        該当するsigmaris_experience行を実際に取得すること
  PASS: trace_belief_to_memory — supporting_decision_ids→decisions→
        memory_refsの和集合(重複排除)→factsという2段階の連鎖が
        正しいidで各取得関数を呼ぶこと
  PASS: trace_belief_to_memory — 存在しないpattern_idはfound=falseを返すこと
  PASS: trace_policy_to_evidence — evidence_refsをdecision_log/topic_log
        両方へ問い合わせ、goal_fact_idsをuser_fact_itemsへ解決すること

12 passed
```

既存の`backend/tests/`(16件)を変更前後で再実行し、リグレッションがないことを確認した。

```
16 passed (変更前)
16 passed (変更後)
```

**実モデルAPI・実DBでの検証は行っていない。** マイグレーション適用・実運用での確認は運用者に委ねる(注意事項の通り、追加のサーバーアクセス・APIキー取得は試みていない)。

---

## 6. 気づいた懸念点・次のステップへの申し送り

1. **`sigmaris_goal_alignment_flags.goal_fact_ids`は今回の週次バッチ実行以降に生成されるフラグにのみ設定される。** 既存のフラグ行(あれば)は遡及的な補完を行っていないため空配列のままであり、`trace_policy_to_evidence()`はそれらに対して`goal_facts=[]`を返す(エラーにはならないが、トレースが不完全になる)。運用者側でマイグレーション適用後、既存フラグの`evidence_count`・件数を確認し、必要なら次回の週次実行で自然に補完されるのを待つか、手動での紐付けを検討することを推奨する。
2. **Policy Updateは、Belief Update(B14の`sigmaris_user_preference_patterns`)を直接参照していない。** `evidence_refs`はdecision_log/topic_logへの参照であり、B14が既に合成した「傾向」を経由せず、B16は毎回独立して生の決定・話題から乖離を再判定している。これは指示書の言う「無理に統一しようとしない」の範囲内(B16の設計としてはB14を経由しない方が判断の独立性を保てるという合理性もある)と判断し、今回は変更していないが、次タスク以降で「PolicyはBeliefの上に構築されるべきか、独立した評価であるべきか」を意図的な設計判断として一度文書化する価値がある。
3. **`evidence_refs`がdecision_log/topic_logのidを型情報なしに混在させている構造上、`trace_policy_to_evidence()`は両テーブルへの問い合わせを常に両方実行する。** 実害はない(該当しない方は0件で返るだけ)が、evidenceの件数が将来大きく増えた場合、無駄なクエリが線形に増える点は留意事項として記録する。
4. **RC指標の実装(次のR-2または別タスクと想定される作業)に向けて**、本タスクで実装した3つのトレース関数(特に`trace_belief_to_memory`)は、「ある信念更新が、実際にどれだけの独立した会話ターン・Experienceに根ざしているか」を数える基礎として転用できる可能性がある(`trace_belief_to_memory`の`supporting_decisions`から、さらに各decisionの`thread_id`/`invocation_id`を辿れば、Belief一件あたりのユニーク会話ターン数が算出できる)。今回はこの集計・指標化までは実装していない(スコープ外)。
5. **`sigmaris_entity_relations`(B9)の`source_table`/`source_id`という汎用ポインタは、循環の5段階には含まれないが、この参照連鎖の設計原則と完全に整合している。** 将来、循環の外側にある補助データ(B9等)もトレースに含めたくなった場合、`source_table`文字列を分岐に使えばcycle_trace.pyに素直に統合できる。
6. **旧`cycle_id`方式のマイグレーションファイルは完全に削除済みで、本番には一切影響していない**(1章の通り、未コミット段階での破棄のため)。運用者側で特別な後始末は不要。
