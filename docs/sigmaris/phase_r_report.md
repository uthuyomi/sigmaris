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

---

# Phase R-2 実施報告: RC指標(Reflexive Cycle 循環健全性指標)の実装

**作業ブランチ:** `phase-r2-cycle-health`(mainから新規作成)
**範囲:** RC-1(Cycle Completion Rate)・RC-2(Temporal Consistency Score)の2指標のみ。残り3指標(信念の安定性・方策と信念の一致度・循環破損の自動検知)はR-3で扱う。

---

## 7. RC-1: Cycle Completion Rateの算出ロジック

### 7.1 「到達」の定義

R-1で確認した通り、ExperienceからMemoryへの到達経路は`consolidate_episodic_memory()`(週次バッチ)による`source_experience_ids`の付与のみである(直接会話由来のfactにはこの参照が付かない)。そのため「到達」とは、**あるExperience行のidが、いずれかのアクティブなuser_fact_items行の`source_experience_ids`配列に含まれること**、と定義した。全アクティブfactの`source_experience_ids`の和集合(`reached_experience_ids`)を作り、判定対象のExperience各行がこの集合に含まれるかを見るだけの、単純な集合演算である。

### 7.2 意図的な非到達と異常な非到達の区別方法(判断根拠)

`consolidate_episodic_memory()`の実装(R-1の棚卸しで確認済み)には、以下3つの構造的な非到達要因があることが分かっている。

1. **母数ゲート**: `_MIN_EXPERIENCES_FOR_CONSOLIDATION=3`未満なら、総experience数に関わらず**バッチ全体が何もせず終了**する。個々のexperienceの内容とは無関係な、システム全体の状態による非到達。
2. **再スキャン窓**: 毎回「直近`_CONSOLIDATION_SCAN_WINDOW`(=100)件」のみを走査する。窓の外に出た古いexperienceは、その後どれだけ経っても二度と評価されない。
3. **昇格基準**: 単発では原則昇格せず、最低2件以上の裏付けが必要(`_MIN_SUPPORTING_EXPERIENCES`)。「単発だが明らかに恒久的」という例外はLLMの判断に委ねられている。

このうち1・2は**LLMの意味的判断を一切介さず、機械的に判定できる**。一方3は「本当に裏付けが薄かったのか、それとも本来なら昇格すべきパターンをLLMが見逃したのか」を再現するにはLLMの再判定が必要であり、これは「循環破損の自動検知」(R-3で扱う指標)そのものにあたる。

そこで、非到達理由を以下4種類に分類した。

| 理由 | 判定基準 | 性質 |
|---|---|---|
| `not_yet_eligible` | このExperienceの`created_at`が、直近の想定バッチ実行時刻(下記7.3節)より後 | 構造的・非異常(タイミングの問題) |
| `system_wide_insufficient_volume` | 現在の総experience数が`_MIN_EXPERIENCES_FOR_CONSOLIDATION`未満 | 構造的・非異常(母数の問題、個々のexperienceの内容とは無関係) |
| `likely_aged_out_of_window` | 現時点でこのExperienceより新しいexperienceが`_CONSOLIDATION_SCAN_WINDOW`件以上存在する(近似、7.4節の限界参照) | 構造的だが、**カバレッジの穴**として要監視(意図的とは言い切れない) |
| `evaluated_not_promoted` | 上記いずれにも該当しない(=機会は与えられたが昇格しなかった) | 大半は健全な非昇格(裏付け不足)だが、稀な見逃しの可能性を排除できない — これ以上の自動判別はR-3のスコープ |

`raw_completion_rate`(単純到達率)に加え、`not_yet_eligible`・`system_wide_insufficient_volume`(=個々のExperienceの問題ではありえないと機械的に断定できる2種類)を母数から除外した`eligible_completion_rate`を併せて算出する。`likely_aged_out_of_window`は意図的に母数から除外していない — これはB2報告書5節が既に指摘していた「再スキャン方式の線形コスト」懸念の顕在化でもあり、「意図的な設計」と「カバレッジの穴」の中間的な性質を持つため、あえて母数に残して`eligible_completion_rate`に反映させることで、この問題が実際に指標へ影響していることを可視化する判断とした。

いずれの率も、`eligible_count=0`(比較対象が1件もない)の場合は`0.0`ではなく`None`を返す — 「非到達がゼロ件で満点」なのか「そもそも比較対象がない」のかを混同しないため(`eval_metrics.py`の`response_error_rate`が`sample_size=0`を明示するのと同じ設計判断)。

### 7.3 直近の想定バッチ実行時刻の算出

`proactive/scheduler.py`の`episode_consolidate`ジョブ定義(`CronTrigger(day_of_week="sun", hour=4, minute=55, timezone=tz)`)をそのままコード化し、`settings.sigmaris_timezone`(デフォルト`Asia/Tokyo`)基準で「現在時刻から見て直近の過去(または同時刻)の日曜4:55」を算出する(`cycle_health_runner._last_scheduled_consolidation_at()`)。

**既知の限界(判断根拠として明記)**: この関数はスケジュール定義から機械的に算出しているだけで、実際にそのバッチジョブが指定時刻に本当に実行されたか(プロセスダウン等で実行されなかった可能性)までは確認できない。また`scheduler.py`側のスケジュールが将来変更された場合、`cycle_health_runner.py`のマジックナンバー(曜日・時・分)を手動で追随させる必要がある——2箇所への値の分散はリスクだが、`scheduler.py`側は`APScheduler`の`CronTrigger`オブジェクトとして構築時にしか値を持たず、実行時に他モジュールから値を読み出せる形になっていないため(既存コードの構造上の制約)、今回は追随が必要な既知の技術的負債として明記するに留めた。

### 7.4 「aged_out」判定の近似についての限界

`likely_aged_out_of_window`の判定は、「現時点で、このexperienceより新しいexperienceが何件あるか」を数えることで、過去のバッチ実行時点で窓の外にあった可能性を**近似**している。過去の各バッチ実行時点でのexperience総数の履歴は保持されていない(スナップショットテーブルが存在しない)ため、これは正確な判定ではなく近似であることを明記する。

---

## 8. RC-2: Temporal Consistency Scoreの算出ロジック

### 8.1 検出する矛盾の種類

**(a) `chat_messages`の順序矛盾**: `list_chat_messages()`が返す`message_order`昇順の配列に対し、隣接するメッセージ間で`created_at`が後退していないか(前のメッセージより後のメッセージの`created_at`が古くないか)を確認する。1件でも後退があれば違反として記録する。`docs/sigmaris/phase_ba4_report.md`17章の「タイムスタンプ崩壊」バグ(全メッセージの`created_at`が保存のたびに現在時刻へ収束する)が動機であり、その修正後にこの種の矛盾が実際に解消されているかを継続的に確認できる指標として設計した。

**(b) `user_fact_items`(event種別)と`sigmaris_experience`の順序矛盾**: `memory_kind='event'`かつ`source_experience_ids`を持つfact(=統合由来のevent fact)について、そのfactの`created_at`が、参照している全experienceの`created_at`の最大値より古くないかを確認する。`consolidate_episodic_memory()`は既存のexperienceを読み取ってから新規factをINSERTするため、factが参照するexperienceより古いことは時系列的にありえない(=検出できれば確実な矛盾)。

**除外した対象とその判断根拠**: 直接会話由来(`memory_extractor.py`経由、`thread_id`/`invocation_id`のみを持つ)のevent factは、この矛盾検出の対象外とした。R-1の棚卸しで確認した通り、fact抽出(`_extract_facts_bg`)とepisode検出(`_cognitive_layer_bg`)は同一ターン内で並行実行される独立したfire-and-forgetタスクであり、どちらのLLM呼び出しが先に完了するかは保証されていない。したがって、同一ターンのfactとexperienceの間で数百ミリ秒〜数秒単位の前後関係が入れ替わることは**正常運用でも起こりうるレースコンディション**であり、これを「矛盾」として検出するのは誤検知になる。統合由来(`source_experience_ids`)の場合のみ、参照先のexperienceが必ず過去に確定済みという厳密な前後関係が成り立つため、この場合に限定して検出対象とした。

### 8.2 スコアの合成方法

(a)(b)それぞれについて `1 - (違反件数 / 検査件数)` を計算し、**検査件数を重みとした加重平均**を最終スコアとする。どちらか一方の検査件数が0件の場合はもう一方のみでスコアを算出し、両方0件の場合はスコア自体を`None`にする(「矛盾ゼロで満点」と「そもそも何も検査していない」を混同しないため)。標準出力・戻り値の両方で、検査件数を必ず併記する設計にした(要件「指標の数値を短絡的に決めつけない」に対応)。

### 8.3 「タイムスタンプ崩壊」の参考値(スコアには非算入)

`chat_messages`の順序チェックとは別に、同一スレッド内で3件以上のメッセージが完全に同一の`created_at`を持つ「崩壊クラスタ」に属するメッセージの割合(`chat_collapsed_timestamp_ratio`)を参考値として算出する。**これは順序違反(`created_at`が後退している)ではなく、単に解像度が失われている状態**であり、直接のスコア算入対象にはしていない——新規の1ターン分(ユーザー発言+アシスタント応答)がDBの`now()`デフォルトにより同一トランザクション時刻を共有するのは正常な挙動であるため、2件までの共有は「崩壊」に数えない(3件以上のみを数える)という閾値にした。この値は、過去の汚染データ(修正前に蓄積された、スレッド全体が同一時刻に収束したメッセージ群)が現在どの程度残っているかを可視化する目的の指標であり、指示書が要求した「いつ以降のデータか」という期間情報とあわせて、既存バグの残存状況を運用者が把握できるようにした。

---

## 9. 実行方法

```bash
cd backend
python scripts/run_cycle_health.py
python scripts/run_cycle_health.py --window-days 60
```

`run_eval.py`(C-mini/C-full)とは完全に独立したスクリプトとして新設した。標準出力の見出し(「Phase R-2 循環健全性指標 (RC指標。C-mini/C-fullとは別系統)」)で明示的に区別している。C-miniのように`sigmaris_eval_runs`への永続化は行っていない(10章参照)。

必要な環境変数は`run_eval.py`と同一(`SIGMARIS_REFRESH_TOKEN`等でのJWT取得、`SUPABASE_SERVICE_ROLE_KEY`で`sigmaris_experience`等のservice-role専用テーブルを読む)。

---

## 10. テスト結果

いずれもモック/純粋関数の直接呼び出し(`unittest`、実DB未接続)。scratchディレクトリに作成(`backend/tests/`には追加していない、既定の方針通り)。

```
Rc1ClassifyExperienceReachTests (6件)
  PASS: 到達済みexperienceがreached=Trueと判定されること
  PASS: 直近バッチ実行時刻より後に作られたexperienceがnot_yet_eligibleになること
  PASS: 総experience数が閾値未満のとき、経過時間に関わらずsystem_wide_insufficient_volumeになること
  PASS: 現時点で窓サイズ以上の新しいexperienceが存在する場合にlikely_aged_out_of_windowになること
  PASS: 上記いずれにも該当しない場合にevaluated_not_promotedへフォールバックすること
  PASS: eligible_completion_rateがnot_yet_eligible/insufficient_volumeのみを母数から除外すること
        (aged_outは母数に残ること、raw_completion_rateとの差異を含め検証)

Rc2ChatOrderTests (3件)
  PASS: message_order順に対するcreated_atの後退を検出すること
  PASS: 単調増加する場合は違反なしとなること
  PASS: 同一created_atの共有が2件までは崩壊とみなされず、3件以上で崩壊率に計上されること
        (かつ崩壊は順序違反としてはカウントされないこと)

Rc2EventExperienceTests (3件)
  PASS: factが参照するexperienceより古いcreated_atを持つ場合に矛盾検出されること
  PASS: factが全experienceより新しい場合は矛盾なしとなること
  PASS: 参照experienceが0件のfactはスキップされ、矛盾として扱われないこと

Rc2CompositeScoreTests (3件)
  PASS: 両チェックとも検査件数0件のときscore=Noneになること
  PASS: 片方のみ検査件数がある場合、そちらのみでスコアが算出されること
  PASS: 両方に検査件数がある場合、検査件数による加重平均になること

LastScheduledConsolidationTests (3件)
  PASS: 水曜日から直近の過去の日曜4:55を正しく算出すること
  PASS: 日曜4:55より前の時刻では前週の日曜4:55になること
  PASS: 日曜4:55以降の時刻では当日の日曜4:55になること

RunCycleHealthIntegrationTests (1件)
  PASS: run_cycle_health()が全依存関数をモックした状態で、RC-1・RC-2両方の
        戻り値を正しい形状・値で組み立てること(エンドツーエンドの配線確認)

19 passed
```

既存の`backend/tests/`(16件)を変更前後で再実行し、リグレッションがないことを確認した。

```
16 passed (変更前)
16 passed (変更後)
```

**実モデルAPI・実DBでの検証は行っていない。** 注意事項の通り、追加のサーバーアクセス・APIキー取得は試みていない。

---

## 11. 実データでの参考値

**取得していない。** この環境からは本番Supabase・サーバーアクセスがなく、指示書の「サーバーアクセスができない場合は見送ってよい」という許容規定に従い、実データでの計測は運用者側での実行に委ねる。運用者が`python scripts/run_cycle_health.py`を実行した際は、特に以下を確認することを推奨する。

1. `reason_counts`の内訳(`evaluated_not_promoted`が大半であれば健全、`likely_aged_out_of_window`が目立つ場合は再スキャン窓の設計見直しを検討する価値がある)。
2. `chat_collapsed_timestamp_ratio`(phase_ba4_report.md 17章の修正前に蓄積されたスレッドがどの程度残っているかの目安)。
3. `chat_order_violations`が1件でも出た場合、その`thread_id`を`chat_messages`で直接確認し、17章の修正が本当に本番へ適用されているかを検証する材料にする。

---

## 12. 気づいた懸念点・R-3への申し送り

1. **RC結果の永続化は行っていない(意図的なスコープ外判断)。** 指示書の要件3は「CLIから実行可能な形」のみを要求しており、C-mini(`sigmaris_eval_runs`)のような永続化・前回比較機能は明示的に要求されていなかったため、今回は追加していない。ただしPDCA運用の実効性を考えると、次回実行時との差分比較(`run_eval.py`の`_fmt_delta`相当)は有用性が高いと考えられる。R-3で残り3指標を実装する際、`sigmaris_cycle_health_runs`のような新規テーブルを設計し、RC-1〜5全てをまとめて永続化する形にするのが、テーブルを1指標ずつ増設するより筋が良いと判断し、あえて本タスクでは見送った。
2. **`_last_scheduled_consolidation_at()`はスケジュール定義のコード上の重複(`scheduler.py`と`cycle_health_runner.py`)を抱えている(7.3節)。** 将来`scheduler.py`側のジョブ時刻を変更する際は、このファイルの`_CONSOLIDATION_WEEKDAY`/`_CONSOLIDATION_HOUR`/`_CONSOLIDATION_MINUTE`も同時に更新する必要がある——見落としやすい依存関係として記録しておく。
3. **`likely_aged_out_of_window`の判定は近似であり(7.4節)、実際にこの理由に分類されたexperienceが本当に「もう二度と評価されない」状態なのかは、過去のバッチ実行履歴を保持する仕組みがない限り確定できない。** もしRC-1の運用でこの理由が無視できない割合を占めることが分かった場合、`consolidate_episodic_memory()`自体の再スキャン方式(cursorなし、直近100件固定)を見直す動機になりうる——これはR-2のスコープ外だが、R-1のphase_b2由来の懸念点(既出)と合わせて優先度を検討する価値がある。
4. **RC-2のchat_messages順序チェックは、`chat_thread_limit`(デフォルト200件)を超えるスレッド数がある場合、超過分は検査対象から漏れる。** 単一テナント運用の現在の規模では実害は小さいと考えられるが、スレッド数が増えた場合は上限の見直しが必要になる。
5. **残り3指標(R-3)に向けて**: 「信念の安定性」はおそらく`sigmaris_user_preference_patterns`の`pattern_statement`が週次実行を跨いでどれだけ変動するかを追跡する形になると想定され、「方策と信念の一致度」はB16の`evidence_refs`とB14の`supporting_decision_ids`が指す決定群の重なりを見る形になりそうだが、いずれも本タスクでは設計に着手していない。「循環破損の自動検知」は、本タスクの7.2節で意図的に踏み込まなかった「`evaluated_not_promoted`の中に本当の見逃しが混ざっているか」の判定と直接関係する——RC-1の`evaluated_not_promoted`件数の推移を監視し、急増があれば要調査、という運用的な検知から始めるのが低コストだと考えられる。

---

# Phase R-3 実施報告: RC指標の完成(信念の安定性・方策整合性・循環破損の自動検知)

**作業ブランチ:** `phase-r3-cycle-health-complete`(mainから新規作成)
**範囲:** RC-3(Belief Stability Index)・RC-4(Policy-Belief Alignment)・RC-5(Cycle Break Detection)の実装、および全RC指標(RC-1〜5)の永続化テーブル。これをもってPhase R(R-1〜R-3)全体が完了する。

---

## 13. RC-3: Belief Stability Indexの算出ロジック

### 13.1 前提として発見した制約: `sigmaris_user_preference_patterns`に履歴が存在しない

設計に着手する前にB14の書き込み経路(`decision_log._upsert_preference_pattern()`)を確認したところ、既存の`pattern_key`への2回目以降の書き込みは**その場でのUPDATE**であり、更新前の`pattern_statement`は一切保持されないことが分かった(`supporting_decision_ids`は和集合として蓄積されるが、文言そのものの履歴は残らない)。

この制約のもとで「信念が覆ったか」を判定する方法として、以下2案を検討した。

- **案A(不採用)**: B14の書き込み経路自体に履歴テーブル(例: `sigmaris_preference_pattern_history`)を追加し、更新のたびに旧`pattern_statement`を記録する。
- **案B(採用)**: 既存の書き込み経路には一切手を加えず、**RC計測自身が実行のたびに現在の状態のスナップショットを保存し、次回実行時に前回スナップショットとの差分を見る**。

案Bを採用した判断根拠: 案Aは指示書が要求していない範囲(B14自体の書き込みロジック変更)まで踏み込むことになり、「既存機能(Phase B全体)に悪影響を与えないこと」という要件4に対するリスクが増える。一方、本タスクは元々RC-1〜5全体の永続化テーブルを新設する予定であり(要件4)、**そのテーブル自身に「今回の信念パターンのスナップショット」を保存させれば、既存のB14コードには一切触れずに済む**。この方が変更範囲が小さく、判断根拠も単純である。

この設計の直接の帰結として、**RC-3は初回実行時(比較対象となる前回スナップショットが存在しない)は必ず`score=None`になる**。これは制約であり、CLI出力・戻り値の両方で明示している(「N/A (前回実行のスナップショットが存在しないため算出不能)」)。

### 13.2 「単発のノイズ」と「正当な信念の変化」の区別方法(判断根拠)

ある`pattern_key`について、前回スナップショットと今回とで`pattern_statement`の文字列が異なる場合を「反転(flip)」とする。反転それぞれについて、`evidence_count`(裏付けとなる決定の件数)が前回からどれだけ増えたか(`evidence_growth`)を見て、以下のように分類する。

- `evidence_growth >= 2`(B14自身の`_MIN_SUPPORTING_DECISIONS`と同じ値): **evidenced**(十分な新規裏付けを伴う、正当な信念の変化の可能性が高い)
- それ未満: **unsupported**(裏付けがほとんど増えていないのに文言だけが変わった、ノイズの疑いが強い)

**この判定は完全ではないことを明記する。** 意味的な矛盾検出(「スピード重視」→「コスト重視」のような実質的な反転)ではなく、単純な文字列不一致で「反転」を検出しているため、LLMが同じ内容を単に違う言い回しで再生成しただけのケース(実質的には反転ではない)も"反転"としてカウントされうる。これは実モデルAPIでの検証ができない本タスクの制約下での意図的な簡略化であり、意味的な同一性判定にはLLM呼び出しが必要になる(B2/B14の既存の重複判定と同じ限界)。将来、実運用でこの誤検出が無視できない割合を占めることが分かれば、簡単な正規化(空白除去等)や、埋め込みベクトルによる類似度判定(B1が既に持つembeddingインフラの転用)を検討する価値がある。

### 13.3 スコアの算出式

```
score = 1 - (unsupported_flip_count / comparable_pattern_count)
```

分母を「反転した件数」ではなく「比較可能な全pattern_key数」にした判断根拠: 反転件数のみを分母にすると、「10件中1件だけ根拠不十分な反転、残り9件は安定」というケースと「1件しかない信念が根拠不十分に反転」というケースが同じ0.0という極端な値になり、大多数が安定していたという事実を反映できない。比較可能な全件数を分母にすることで、「安定している信念が多いほどスコアが高くなる」という直感的な挙動になる。

---

## 14. RC-4: Policy-Belief Alignmentの算出ロジック

### 14.1 R-1トレース関数の活用(要件2への直接対応)

各`sigmaris_goal_alignment_flags`行について、R-1で実装した`cycle_trace.trace_policy_to_evidence(flag_id)`をそのまま呼び出し、`evidence_decisions`(そのフラグの`evidence_refs`のうちdecision_log由来と判明したもの)を取得する。これがフラグの「根拠決定群」となる。

B14側は、`decision_log.get_active_preference_patterns(limit=100)`で取得した全アクティブpatternの`supporting_decision_ids`から、`decision_id -> {そのdecisionを根拠にしているpattern_keyの集合}`という逆引きインデックスを構築する。

### 14.2 alignment_ratioの算出

フラグの根拠決定群のうち、上記の逆引きインデックスに1件でも登場する(=いずれかのBelief patternからも根拠として参照されている)決定の割合を`alignment_ratio`とする。

```
alignment_ratio = |flagの根拠決定 ∩ (いずれかのpatternの根拠になっている決定)| / |flagの根拠決定|
```

`best_matching_pattern_key`(最も多くヒットしたpattern_key)も参考情報として記録するが、スコア自体には使わない。

### 14.3 スコアの解釈にあたっての注意(判断根拠として明記)

`alignment_ratio`が低い場合、以下2つの異なる状況のどちらであるかは、この指標単体では判別できない。

1. **B16がB14未反映の新しい材料から乖離を検出した**(健全: B14は週次で信念を合成するため、直近の決定がまだ信念に反映されていないタイムラグは正常)
2. **B16の判定が、実際に確立している判断傾向とずれている**(要注意: 目標整合性チェックの妥当性そのものに疑問符がつく)

指示書は「この指標が低い場合、B16の目標整合性チェックが実際の判断傾向を正しく反映できていない可能性を示唆する」としているが、上記1のタイムラグ由来の低下と完全に切り分けることは、当面の実装では不可能である。運用上は、`alignment_ratio`が低い状態が**複数回の実行にわたって続く**フラグ(=タイムラグでは説明できない)にのみ注目するのが妥当と考えられる——ただし、この「複数回にわたる低alignment_ratioの継続監視」自体はRC-5(循環破損の自動検知)と概念的に重なるため、本タスクでは実装せず、次節の懸念点として申し送る。

スコアは、評価可能な(根拠決定が1件以上ある)フラグの`alignment_ratio`のマクロ平均。評価可能なフラグが1件もなければ`None`。

---

## 15. RC-5: Cycle Break Detectionの算出ロジック

### 15.1 検知方式(判断根拠)

指示書が提案した通り、「直近の測定値と過去の平均値を比較し、閾値を超えた乖離があれば検知する」という単純な閾値ベースの方式を採用した。より高度な統計的異常検知(変化点検出、季節性を考慮した予測区間等)も検討したが、以下の理由から見送った。

1. **実データがまだ存在しない。** 高度な手法のパラメータチューニングには実際の運用データの分布が必要だが、この環境からは取得できない(0章・注意事項の制約)。単純な閾値方式であれば、後から実データを見て閾値を調整するだけで済む。
2. **要件3(RC-1・RC-2の急激な悪化の検知)がそもそも「急激な」悪化に限定している。** 緩やかなトレンドの検知(変化点検出が本来得意な領域)は要求されていない。

### 15.2 対象指標(要件通りRC-1・RC-2のみ)

RC-1は`eligible_completion_rate`(`raw_completion_rate`ではない——R-1・R-2で確立した「タイミング/母数由来の非到達を除いた方が実態に近い」という設計方針をそのまま踏襲)、RC-2は`score`を対象とする。RC-3・RC-4は指示書の要件3が明示的に対象外としているため実装していない(判断根拠として、RC-3は初回実行後最低2回分のデータが必要でサンプルが少なく、RC-4も同様に単一実行あたりのフラグ件数が少ない=閾値ベースの単純比較には時期尚早、という理由も併せて記録しておく)。

### 15.3 判定方法

各指標を独立に判定する。

- 過去の実行回数が`min_history`(=3、B2/B14の「recurring patternと認めるための最低サンプル数」の考え方をそのまま踏襲)未満、または今回の値が`None`の場合: `checkable=False`
- 過去の値の単純平均を`baseline`とし、`baseline - current`が`drop_threshold`(=0.2、絶対値で20ポイント)を超えていれば`broke_threshold=True`

全体のstatusは、**判定可能な指標が1つもない場合のみ`insufficient_history`**(「異常なし」と同一視しないための明示的な区別)、判定可能な指標のうち1つでも閾値を超えていれば`break_detected`、それ以外は`healthy`とする。

**`drop_threshold=0.2`は未検証の暫定値であることを明記する。** 実データでの分布が分からない状態での経験的な選択であり、運用開始後にfalse positive/false negativeの発生状況を見て調整が必要になる可能性が高い(B1の`match_threshold`等、他の多くのB群暫定チューニング定数と同じ性質の懸念)。

### 15.4 通知方法の検討(実装は見送り、判断根拠のみ記載)

指示書の指定通り、通知の実装自体は行っていない。検討した結果は以下の通り。

- 既存の`app.services.proactive.notifier.get_notifier()`(Pushover/LogNotifierを抽象化した`send(title, message)`インターフェース)がそのまま使える状態にある。`run_cycle_health.py`の`rc5["status"] == "break_detected"`の分岐に`await get_notifier().send(...)`を1行追加するだけで統合できる。
- **今回実装しなかった判断根拠**: (a) 指示書が明示的に見送りを許容している、(b) RC-5自体が`drop_threshold`という未検証の暫定値に依存しており、実データでの調整前に通知を有効化すると誤報が海星さんに直接届くリスクがある、(c) 現状`run_cycle_health.py`は手動実行のCLIであり(週次バッチのスケジュールにはまだ組み込まれていない)、定期実行されない限り「検知はしたが誰も見ない」状態になるため、通知の実装よりも先に「いつ・どうやってこのスクリプトを定期実行するか」という運用設計が必要——これは本タスクのスコープ外である。

将来この2点(閾値の実データ調整、定期実行の仕組み)が整った段階で、`proactive/scheduler.py`に`run_cycle_health`相当のジョブを追加し、`break_detected`時にのみ通知する、という統合が自然な次のステップになると考えられる。

---

## 16. 永続化テーブルの設計

`supabase/migrations/202607220048_cycle_health_runs.sql`(新規、未適用)で`sigmaris_cycle_health_runs`を追加した。

### 16.1 設計方針(判断根拠)

- **`sigmaris_eval_runs`(C-mini/C-full)・`sigmaris_improvement_cycles`(SB-7)とは別の新規テーブル**(要件4通り)。RC指標は「循環そのものの機能度」を測るものであり、記憶検索精度(C-mini/C-full)や自己改善サイクル(SB-7)とは測定対象が異なるため、テーブルレベルで明確に分離した。
- **RC-1〜5それぞれのヘッドライン数値は実列として持つ**(`sigmaris_eval_runs`が`memory_precision`等を実列にしているのと同じ設計判断)。「直近10回のrc2_scoreの推移」のような集計がプレーンなSQLで書けることを優先した。
- **`details` jsonbに、次回実行のRC-3計算に必要な`belief_snapshot`(今回の`pattern_key`別`pattern_statement`/`evidence_count`)、およびRC-3の反転一覧・RC-4のフラグ別alignment内訳・RC-5の各指標の判定詳細を保存する**。`sigmaris_eval_runs.details`(`per_query`・`duplicate_clusters`等)と同じ「ヘッドラインは列、詳細はjsonb」という分割を踏襲。
- **service_role_only RLS**(`sigmaris_decision_log`等と同じ、Sigmaris自身の測定データでありユーザー所有コンテンツではないため)。
- **更新(UPDATE)を行わない、追記専用テーブル**。`sigmaris_eval_runs`と同じ「1回の実行=1行」という設計で、既存行を書き換える経路は用意していない。

### 16.2 読み取り/書き込みの役割分担

`eval_runner.run_eval()`が書き込みを一切行わず`scripts/run_eval.py`側に委ねているのと同じ分担を踏襲した。ただし、RC-3(前回スナップショットとの比較)・RC-5(過去値との比較)は**計測そのものに過去の実行結果が必要**であるため、`cycle_health_runner.run_cycle_health()`内で`get_recent_cycle_health_runs()`による**読み取り**は行う。**書き込み**(`record_cycle_health_run()`)は`scripts/run_cycle_health.py`側でのみ行い、`--dry-run`で省略可能にした(`run_eval.py`と同じ挙動)。

---

## 17. `run_cycle_health.py`の拡張内容

- RC-3・RC-4・RC-5の標準出力セクションを追加。RC-3はスナップショット不在時に明示的に「N/A (次回実行以降で算出される)」と表示し、RC-5は`insufficient_history`を「異常なし」と混同しないよう明記した文言にした。
- `--dry-run`フラグを追加(R-2時点では永続化自体がなかったため存在しなかった)。指定時は`sigmaris_cycle_health_runs`への書き込みを行わない。
- `--notes`フラグを追加(`run_eval.py`と同じ、実行に任意のメモを付けられる)。
- `rc5.status == "break_detected"`の場合、15.4節の判断根拠に基づき、通知は送らないが標準出力上で明示的に警告表示する分岐を追加した。

---

## 18. テスト結果

いずれもモック/純粋関数の直接呼び出し(`unittest`、実DB未接続)。scratchディレクトリに作成(`backend/tests/`には追加していない、既定の方針通り)。

```
Rc3BeliefStabilityTests (6件)
  PASS: 前回スナップショットが無い場合score=Noneになること
  PASS: 文言が変化していない場合は反転とみなされないこと
  PASS: 根拠(evidence)がほぼ増えていない反転がunsupportedとして減点されること
  PASS: 十分な根拠増加を伴う反転はevidencedとして減点されないこと
  PASS: 少数の不安定な信念が全体スコアを過度に押し下げないこと
        (4件中1件のunsupported flipでscore=0.75になること)
  PASS: 前回スナップショットに存在しない新規pattern_keyは比較対象外になること

BuildBeliefSnapshotTests (1件)
  PASS: pattern_key別のスナップショットが正しく構築されること

Rc4PolicyBeliefAlignmentTests (4件)
  PASS: 根拠決定が全てBelief patternと重なる場合alignment_ratio=1.0になること
  PASS: 重なりが無い場合alignment_ratio=0.0、best_matching_pattern_key=Noneになること
  PASS: 根拠決定が0件のフラグはalignment_ratio=None(スコア対象外)になること
  PASS: 評価対象フラグが1件も無い場合score=Noneになること

Rc5CycleBreakTests (5件)
  PASS: どちらの指標も履歴不足のときinsufficient_historyになること
  PASS: 有意な悪化が無いときhealthyになること
  PASS: RC-1が大きく悪化したときbreak_detectedになり、broke_metricsに正しく記録されること
  PASS: 片方の指標のみ判定可能でも、その指標だけでbreak_detectedと判定できること

CycleHealthRunsStoreTests (2件)
  PASS: record_cycle_health_run()が正しい形状のペイロードでPOSTすること
        (rc1_eligible_completion_rate等のヘッドライン列、details)
  PASS: 設定不備等の失敗時、get_recent_cycle_health_runs()が例外を投げず
        空リストを返すこと(record_eval_run系と同じベストエフォート方針)

RunCycleHealthRc345IntegrationTests (1件)
  PASS: run_cycle_health()が、前回スナップショットとの比較によるRC-3、
        R-1トレース関数経由のRC-4、履歴比較によるRC-5を、それぞれ正しい
        入力で呼び出し正しい値を組み立てること(エンドツーエンドの配線確認)

18 passed
```

既存の`backend/tests/`(16件)、およびR-1・R-2で作成したscratchテスト(計31件)を含め、全て再実行しリグレッションがないことを確認した。

```
16 passed (backend/tests/)
65 passed (backend/tests/ 16件 + R-1 12件 + R-2 19件 + R-3 18件、合算実行)
```

**実モデルAPI・実DBでの検証は行っていない。** 注意事項の通り、追加のサーバーアクセス・APIキー取得は試みていない。マイグレーション(`202607220048_cycle_health_runs.sql`)は作成のみ、適用は運用者側に委ねる。

---

## 19. Phase R(R-1〜R-3)全体の振り返り

### 19.1 各タスクが達成したこと

| タスク | 達成したこと |
|---|---|
| R-1 | 単一の新規`cycle_id`は導入せず、既存の疎結合な参照(`thread_id`/`invocation_id`/`source_experience_ids`/`memory_refs`/`supporting_decision_ids`/`evidence_refs`)の棚卸しと、唯一見つかった欠落(`goal_fact_ids`)の補完、それらを辿る読み取り専用トレース関数(`cycle_trace.py`)を実装した |
| R-2 | R-1のトレース関数・参照連鎖を使い、循環完了率(RC-1)・時間的一貫性(RC-2)という最初の2指標を実装した |
| R-3(本タスク) | 残り3指標(RC-3信念の安定性・RC-4方策整合性・RC-5循環破損検知)を実装し、RC-1〜5全てを保存する永続化テーブルを新設した |

### 19.2 一貫していた設計哲学

3タスクを通じて共通していたのは、以下の姿勢である。

1. **新しい統合の仕組みを作るより、既存の仕組みを尊重して繋ぐ**: R-1で単一`cycle_id`方式を明示的に破棄し参照連鎖方式に転換したことが最も顕著な例だが、R-3のRC-3設計(B14の書き込み経路に手を加えず、RC計測自身がスナップショットを持つ)も同じ哲学の延長線上にある。
2. **指標がNoneになりうることを恐れず、0.0/1.0と混同しない**: `eval_metrics.py`のsample_size=0の扱いに始まり、RC-1のeligible_completion_rate、RC-2のscore、RC-3のスナップショット不在、RC-4の評価対象0件、RC-5のinsufficient_historyまで、「測定できなかった」ことを「良好だった」から明確に区別する設計を一貫して維持した。
3. **単一の数値の裏にある「なぜ」を常に問う**: 「到達率が低い=悪い」「スコアが低い=悪い」という短絡評価を避け、RC-1の4分類、RC-2の2種類の矛盾の切り分け、RC-3のevidenced/unsupportedの区別、RC-4のalignment_ratioの二重の解釈可能性、RC-5のinsufficient_history/healthy/break_detectedの3値化など、常に「なぜその数値になったか」を追加情報として持たせた。

### 19.3 Phase R全体で残っている懸念事項の総まとめ

以下は各タスクの懸念点セクション(6章・12章)から特に重要なものの再掲・統合である。

1. **実データでの検証が一度もできていない。** R-1〜R-3を通じ、この環境からはサーバーアクセス・APIキーが一切得られなかった(注意事項の許容規定通り)。RC-1〜5のロジック・テストは全てモックベースであり、実際の`sigmaris_experience`・`user_fact_items`・`sigmaris_decision_log`・`sigmaris_goal_alignment_flags`のデータに対して一度も実行されていない。**運用者側での実行が、Phase R全体にとって最優先の次のアクションである。**
2. **3件の未適用マイグレーション**(`202607220047_goal_alignment_fact_refs.sql`・`202607220048_cycle_health_runs.sql`、およびR-1で修正した既存関数)が本番に適用されるまで、`goal_fact_ids`・`sigmaris_cycle_health_runs`関連の機能は実質的に動作しない。
3. **RC-5の`drop_threshold=0.2`は未検証。** 実データ蓄積後、早期に見直しが必要になる可能性が高い唯一の「暫定チューニング定数」。
4. **RC-3は最低2回の実行(初回はスナップショット取得のみ)を経ないと意味のある値を返さない。** 運用者は、マイグレーション適用後に`run_cycle_health.py`を最低2回(できれば週1回程度の間隔で)実行して初めてRC-3の実質的な運用が始まることを理解しておく必要がある。
5. **RC-5の通知統合、および`run_cycle_health.py`自体の定期実行の仕組みは未整備。** 15.4節で述べた通り、これは意図的なスコープ外判断だが、Phase Rの成果を実際に「壊れたら気づける」状態にするには、この2点の整備が次の自然なステップになる。
6. **RC-4のalignment_ratioは、タイムラグ由来の低下と、実際の不整合由来の低下を区別できない**(14.3節)。この区別が必要になった場合、「複数回の実行にわたる継続的な低スコア」を検知する仕組みが必要になるが、これはRC-5の枠組みをRC-4にも拡張する形になると考えられ、独立した後続タスクの候補として記録しておく。
7. **RC-1の`likely_aged_out_of_window`判定(R-2由来)・RC-3の文字列完全一致による反転検出(13.2節)は、いずれも「本来はより精緻な判定が可能だが、この環境の制約(実LLM検証不可)下では簡略化した」という共通の性質を持つ。** 実モデルAPIでの運用が可能になった段階で、両者とも精度向上の余地があることを記録しておく。

Phase R(R-1〜R-3)はここで完了とする。RC指標の実運用(定期実行・実データでの検証・閾値調整)は、独立した運用タスクとして今後継続する必要がある。
