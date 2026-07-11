# Temporal Layer Step 1: memory_kind分類とvalid_time(Bi-temporal)の導入

**実装日**: 2026-07-11
**関連**: `docs/sigmaris/bug_inventory.md`(直近の一連の修正、memory_extractor.py/decision_log.py/experience_layer.py/B9/B14/B16の文脈供給修正)

## 0. 背景・目的

海星さんから、「シグマリスが、数日前の出来事を今日起きたことのように繰り返し報告する」という問題が指摘された。記憶の内容自体は正確だが、「これがいつの情報で、今も有効か」という時間的性質を記憶の種類によって区別していないことが根本原因と判断し、以下を実装した。

1. `user_fact_items`に`memory_kind`列（`event`|`state`|`trait`）を追加し、`memory_extractor.py`の抽出時に分類させる
2. `event`種別は既存のB17減衰フレームワークの枠内で、カテゴリに関わらず90日を目安としたより速い減衰を適用する
3. `state`種別には`valid_from`（現実世界でいつから真か）と`superseded_by`（A3のdecision_log supersedeパターンを踏襲した自己参照FK）を導入し、矛盾する新情報が来た場合は削除ではなく無効化する

本タスクでは一切のコード修正は行った（前回までのタスクと異なり、これは実装タスクである）。マイグレーションは作成のみ、適用は運用者に委ねている。

---

## 1. memory_kind分類ロジックの実装詳細

### 1.1 スキーマ

`supabase/migrations/202607220045_temporal_memory_layer.sql`で以下を追加した（作成のみ、適用は運用者側で実施すること）。

```sql
alter table public.user_fact_items
  add column if not exists memory_kind text check (memory_kind in ('event', 'state', 'trait')),
  add column if not exists valid_from  timestamptz,
  add column if not exists superseded_by uuid references public.user_fact_items(id);
```

いずれもNULL許容。**既存データへの遡及的な分類付けは行っていない**（本タスクの明示的なスコープ外）ため、既存の全行は`memory_kind=NULL`のままであり、後述の通りこれは「本機能導入前と全く同じ挙動」を意味する。

### 1.2 `memory_extractor.py`のプロンプト拡張

`_PROMPT`に、`category`の説明ブロックと同じ形式で`memory_kind`の3分類を明示的に列挙した（依頼書の定義をほぼそのまま踏襲）:

```
memory_kindは必ず次の3種類のいずれか一つとし、自由記述は禁止します:
- event: 一時的な出来事（例:「今日AdFlow AIの実装で詰まった」「先週旅行に
  行った」）。今は事実でも、時間が経つとともに古い情報になっていくもの
- state: 現在の状態、常に最新の1つだけが正である情報（例:「Phase Bは完了
  している」「今は札幌に住んでいる」）。新しい情報が来たら古い情報を置き
  換えるべきもの
- trait: 判断傾向・好み（例:「スピード重視で判断する」「猫が好き」）。継
  続的な性格・嗜好を表すもの
```

JSON出力の`facts[]`各要素に`"memory_kind": "event | state | trait のいずれか一つ"`を追加した。既存の`category`/`key`/`value`/`confidence`/`reason`フィールドの形式・意味は一切変更していない（要件「既存の抽出ロジック・出力形式への影響を最小限にすること」に対応）。

**バリデーション方針**: `memory_kind`はLLMが省略する、または3値以外の文字列を返す可能性を考慮し、`_VALID_MEMORY_KINDS = {"event", "state", "trait"}`に含まれない値は**factそのものを棄却せず**、`memory_kind=None`（未分類）として扱う。理由: これは新規の任意分類であり、分類に失敗したという理由で事実の記録そのものを失うのは、分類精度の未熟さに比べて損失が大きいと判断した（`category`の必須バリデーション——不正なcategoryのfactは丸ごとスキップされる——とは意図的に非対称な扱いにしている。categoryはDBのCHECK制約upsertが失敗する必須情報だが、memory_kindはNULL許容でありスキップの必要がない）。

---

## 2. event種別の減衰ロジックへの組み込み方法

### 2.1 設計方針: 条件分岐の追加（新テーブル不要）

依頼書の指示通り、`memory_validator.py`の既存減衰フレームワークへの条件分岐追加で対応した。新規テーブルは作成していない。

```python
_EVENT_DECAY_RULE: tuple[int, float] = (90, 0.5)

def _decay_rule_for(category: str, memory_kind: str | None) -> tuple[int | None, float]:
    if memory_kind == "event":
        return _EVENT_DECAY_RULE
    return _DECAY_RULES.get(category, (None, 1.0))
```

`memory_kind == "event"`の場合、**カテゴリに関わらず**`_EVENT_DECAY_RULE`（90日、減衰係数0.5）を使う。それ以外（`state`・`trait`・`None`＝既存の全行）は、これまで通り`_DECAY_RULES`のカテゴリ別ルールをそのまま使う——**既存の`state`/`trait`扱いの事実、および全既存データの減衰挙動は一切変更していない**（要件4「trait種別は既存のB14の挙動に影響を与えないこと」、要件5に対応）。

**減衰係数0.5の判断根拠**: 依頼書は「90日を目安としたTTL的な減衰」とのみ指定しており、具体的な減衰係数（confidenceに掛ける倍率）は明記していなかった。既存の`_DECAY_RULES`の減衰係数は0.5（health、最も急激）〜0.9（environment、最も緩やか）の範囲にある。eventは「一時的な出来事」という定義上、既存カテゴリの中で最も急激な減衰（health=0.5）と同程度、またはそれ以上に速く忘れられるべきだと判断し、0.5を採用した。B17の重要度による減衰緩和（`_importance_adjusted_decay`）は既存の仕組みをそのまま適用しており、依頼書の「重要度が高いeventは減衰しにくくなる(そのままでよい)」を満たしている。

### 2.2 バッチ処理と検索ランキングの両方に反映（設計上の重要な判断）

`memory_validator.py`には減衰を実際に適用する2つの経路がある。

1. **`validate_all_facts()`（日次バッチ）**: `confidence`列を実際に書き換える。Phase 1の減衰ループを`_decay_rule_for()`経由に変更した。
2. **`compute_freshness_multiplier()`（Phase B8、検索ランキング用のリアルタイム関数）**: DBを書き換えず、検索結果の並び順にのみ影響する。

このモジュール自身の既存コメントが「search ranking and the daily validate_all_facts() batch job can never disagree about what "old" means」という不変条件を明記していたため、**event判定を(1)だけに適用して(2)を変更しないと、この不変条件が壊れる**（バッチ処理では速く減衰するeventが、検索ランキングでは従来通りカテゴリ基準で扱われ、両者が食い違う）と判断した。

このため、`compute_freshness_multiplier()`に`memory_kind: str | None = None`（デフォルト値ありのオプション引数、既存呼び出し元との後方互換性を維持）を追加し、`_decay_rule_for()`を共有する形にした。ただし、この関数の唯一の呼び出し元である`memory_search.py::_freshness_weighted_score()`は検索RPCの結果行（`row`）から値を読み取る設計のため、**検索RPC（`search_fact_memory`/`search_fact_memory_trgm`）のRETURNS TABLEに`memory_kind`列を追加する必要があった**。

この2RPCは過去4回、出力列追加のたびに「DROP FUNCTION + CREATE FUNCTION」が必要だった（`202607150037_time_aware_search.sql`のコメントが自ら数えている）。今回で5回目としてこのパターンを踏襲し、`memory_kind`を新しい出力列として追加した。これは依頼書が明示的に要求した範囲を超える判断だが、「search ranking and the daily batch job must never disagree」という既存の設計不変条件を壊さないために必要と判断した（判断根拠として明記する）。

---

## 3. state種別のvalid_from/superseded_byの実装詳細

### 3.1 重要な設計上の発見: 既存のUNIQUE制約がsupersedeパターンと構造的に矛盾する

実装前の調査で、`user_fact_items`には`unique (user_id, category, key)`という**テーブル全体に対する**一意制約が存在することを確認した。この制約がある限り、「同じ(category, key)で新しい行をINSERTし、古い行を残す」というsupersedeパターン（A3のsigmaris_decision_logが採用している設計）は、`user_fact_items`では**構造的に不可能**である——古い行が存在する状態で同じキーの新しい行をINSERTしようとすると、UNIQUE制約違反で失敗する。

この矛盾を解消するため、マイグレーションで以下を行った。

```sql
alter table public.user_fact_items
  drop constraint if exists user_fact_items_user_id_category_key_key;

create unique index if not exists idx_user_fact_items_active_unique
  on public.user_fact_items (user_id, category, key)
  where superseded_by is null;
```

すなわち、「テーブル全体で一意」から「**アクティブな（supersededでない）行の中でのみ一意**」という**部分ユニークインデックス**に切り替えた。これはPostgreSQLにおける「ソフトバージョニングされた自然キー」の標準的な実装パターンである。

**リスクと運用者への確認依頼**: `drop constraint if exists`の制約名`user_fact_items_user_id_category_key_key`は、元のマイグレーション（`202606240016_fact_memory.sql`）が無名のテーブルレベル制約として`unique (user_id, category, key)`を宣言していたことから、PostgreSQLのデフォルト命名規則（`<テーブル>_<列1>_<列2>_<列3>_key`）に基づいて推測したものである。同テーブルの単一列CHECK制約（`user_fact_items_category_check`等）の命名パターンと一致することから妥当性は高いと考えているが、**実際にこの名前が正しいかは、この環境からは確認できない**。`drop constraint if exists`は名前が違っていても安全に無視される（エラーにはならない）が、その場合は古い制約が残り続け、state supersedeのINSERTが本番で静かに失敗する（Pythonの例外ハンドリングでキャッチされログに残るのみで、データ破損はしないが機能が動かない）ことになる。

運用者側でマイグレーション適用後、以下のクエリで実際に制約が置き換わったことを確認することを強く推奨する。

```sql
-- 期待される結果: 古い制約(user_fact_items_user_id_category_key_key)が
-- 存在せず、新しい部分インデックス(idx_user_fact_items_active_unique)が
-- 存在すること
select conname from pg_constraint
where conrelid = 'public.user_fact_items'::regclass and contype = 'u';

select indexname, indexdef from pg_indexes
where tablename = 'user_fact_items' and indexname = 'idx_user_fact_items_active_unique';
```

### 3.2 `upsert_fact_item` RPCのsupersede分岐

`p_memory_kind`・`p_valid_from`を末尾のデフォルト引数として追加した（既存の`jsonb`戻り値のため、他パラメータ追加時と同様`DROP`不要、`CREATE OR REPLACE`のみで対応可能——`202607120034_episode_consolidation.sql`が既に確立した判断根拠をそのまま踏襲）。

分岐ロジック:

```sql
select id, value into v_existing_id, v_old_value
from user_fact_items
where user_id = v_user_id and category = p_category and key = p_key
  and superseded_by is null;  -- アクティブな行のみを見る

if v_existing_id is not null and p_memory_kind = 'state' and v_old_value is distinct from p_value then
  -- 矛盾するstate: 新しい行をINSERTし、古い行のsuperseded_byを新しいidに設定
  insert into user_fact_items (..., memory_kind, valid_from) values (..., 'state', coalesce(p_valid_from, now()))
    returning id into v_item_id;
  update user_fact_items set superseded_by = v_item_id where id = v_existing_id;
elsif v_existing_id is not null then
  -- 既存の全動作: 値が同じstate、またはevent/trait/未分類 → その場でUPDATE
  update user_fact_items set value = p_value, ... where id = v_item_id;
else
  -- 既存の全動作: 新規INSERT
  insert into user_fact_items (...) values (...) returning id into v_item_id;
end if;
```

**分岐の判断根拠**: supersedeが発生するのは「`memory_kind='state'`かつ既存行があり、かつ値が実際に異なる」場合のみに限定した。値が同一の場合（単なる再確認）や、`event`/`trait`/未分類の場合は、**修正前と完全に同じ「その場でUPDATE」の挙動**を維持している。これにより要件4（trait種別への無影響）・要件5（既存機能への無影響）を満たす。

### 3.3 `memory_extractor.py`側の対応

- `upsert_fact_item()`（Pythonラッパー）に`memory_kind`・`valid_from`引数を追加し、RPCへそのまま渡す。
- **確信度スキップゲートの例外**: 既存のロジックは「新しい事実の確信度が既存より低ければ、upsertそのものをスキップする」というものだった。しかしstate種別で「確信度は低いが値が矛盾している」新情報が来た場合、このスキップによってRPCのsupersede分岐に到達する前に処理が止まってしまい、機能が働かなくなる。そのため、**`memory_kind == 'state'`の場合のみ**この確信度スキップを回避するよう変更した。event/trait/未分類は元のスキップ挙動を維持している（これも判断根拠として明記する独自の実装判断であり、テストで両方の分岐を確認した——4.節参照）。

### 3.4 `valid_from`のルールベース推定

依頼書の「シンプルなルールベースの判断にとどめてよい。過度に複雑な自然言語時間解析は行わないこと」という指示に従い、新規の依存ライブラリを一切導入せず、**固定の相対日付フレーズの部分文字列マッチ**のみで実装した。

```python
_RELATIVE_DATE_PHRASES: list[tuple[str, int]] = [
    ("一昨日", -2), ("おととい", -2), ("昨日", -1), ("今日", 0), ("本日", 0),
    ("先週", -7), ("来週", 7), ("今週", 0),
    ("先月", -30), ("来月", 30), ("今月", 0),
]
```

会話テキストにこれらのフレーズが含まれていれば、`datetime.now(UTC) + timedelta(days=offset)`で`valid_from`を推定する。最初にマッチしたフレーズを採用し、それ以上複雑な解析（複数の時間表現の整合性判断等）は行わない。マッチするフレーズが1つもない場合は`valid_from=None`とし、RPC側の`coalesce(p_valid_from, timezone('utc', now()))`により**現在時刻がそのまま採用される**——これは依頼書が明示的に許容しているフォールバック（「会話から推定できない場合はcreated_atと同じ値でよい」）そのものである。

### 3.5 無効化されたstateをアクティブな読み取りから除外

supersedeでリンクを張るだけでは不十分で、**superseded状態のfactが依然として検索・コンテキスト注入に使われてしまえば、この機能は問題を何も解決しない**（「古い情報を最新のことのように報告する」という当初の問題がそのまま残る）。以下3箇所で除外処理を追加した。

1. **`get_fact_items`/`get_fact_items_with_embeddings`/`get_fact_items_for_user`の`active_only=True`フィルタ**: 既存の`is_deleted=eq.false,is_stale=eq.false`に`superseded_by=is.null`を追加した。この3関数は`memory_extractor.py`・`decision_log.py`・`testset_gen.py`など、これまでの一連の修正で「現在アクティブな事実一覧が欲しい」という意図で広く使われている既存の共通経路であり、ここに1箇所追加するだけで、個別の呼び出し元をすべて改修する必要がなく波及させられると判断した（decision_logのsupersedeパターンが「呼び出し元ごとに`if not d.get("superseded_by")`でフィルタする」という個別対応だったのとは異なる設計判断——`active_only`という既存の明確な意味論に相乗りする方が、実装漏れのリスクが低いと判断した）。
2. **`build_facts_context()`**: `is_deleted`/`is_stale`と同じ場所に`superseded_by`のチェックを追加。この関数は渡されたリストをそのまま処理する純粋関数のため、`active_only=True`を経由していない呼び出し元に対する防御的な二重チェックとして機能する。
3. **`search_fact_memory`/`search_fact_memory_trgm` RPC**: 2.2節で述べた通り、WHERE句に`superseded_by is null`を追加した。

---

## 4. テスト結果

`backend/tests/`には新規テストを追加していない（既定の方針通り、スクラッチディレクトリに作成）。10件のテストを作成し、以下を確認した。

- **memory_kind分類**: `event`種別が`upsert_fact_item()`に正しく渡ること。不正な`memory_kind`値がfact自体を棄却せず`None`に縮退すること。
- **valid_from推定**: 「昨日から札幌に住んでいる」という会話から、実際に前日の日時が`valid_from`として渡ること。相対日付フレーズがない場合は`valid_from=None`（RPCが"now"にフォールバック）のままであること。
- **確信度スキップゲートの例外**: `memory_kind='state'`で確信度が既存より低い矛盾情報が、スキップされずに`upsert_fact_item()`まで到達すること。**回帰確認として**、`event`種別では元通りスキップされること。
- **event減衰**: `_decay_rule_for("devices", "event")`が、devicesカテゴリの緩やかな減衰ルール（180日/0.8）ではなく`_EVENT_DECAY_RULE`（90日/0.5）を返すこと。`state`/`trait`/`None`では引き続きカテゴリ別ルールが使われること（回帰確認）。`compute_freshness_multiplier()`とバッチの`validate_all_facts()`の両方で、同一の年齢・カテゴリの事実がevent分類の有無で異なる減衰結果になることを直接確認した。
- **superseded除外**: `build_facts_context()`が`superseded_by`が設定された行をコンテキストから除外すること。

```
10 passed in 0.69s
```

既存の`backend/tests/`（16件）、および前回までの一連のタスクで作成したスクラッチテスト（`test_decision_log_relevant_facts.py`・`test_decision_type_and_b2.py`・`test_b9_b14_b16_context.py`・`test_memory_extractor_dedup.py`、計18件）も全て成功し、リグレッションは確認されなかった。

```
16 passed in 0.74s
18 passed in 0.80s
```

**テスト作成中に発見した、本タスクと無関係な既存の挙動**: `memory_validator.py`の複数箇所で使われている`float(item.get("importance_score") or 0.5)`というパターンは、`importance_score`が明示的に`0.0`（floatのゼロ）の場合も`None`/未設定と同様に扱い、暗黙に`0.5`にフォールバックしてしまう（Pythonの`or`演算子が`0.0`をfalsyと評価するため）。本タスクのテスト作成中にこの挙動に実際に遭遇し、テスト側のimportance_score値を調整することで対応した。**この修正は本タスクのスコープ外として行っていない**が、次タスクへの申し送り事項として6章に記録する。

**実モデルAPIでの検証は行っていない。** 本タスクの注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない。**運用者側で確認すべきこと**:
1. マイグレーション適用後、3.1節のクエリでUNIQUE制約の置き換えが正しく行われたことを確認する。
2. 次回以降の会話で、`user_fact_items`に`memory_kind`が実際に分類されて記録されているか（`select category, key, memory_kind, count(*) from user_fact_items where memory_kind is not null group by 1,2,3`等）を確認する。
3. state種別の矛盾する新情報を意図的に会話で伝え、`superseded_by`が正しくリンクされ、古い行の値がそのまま残っていること（削除されていないこと）を確認する。
4. `run_eval.py`（SB-3、`memory_duplicate_rate`）を再実行し、この機能が重複率に悪影響を与えていないかを確認する（本タスクは重複防止機構そのものではないが、supersedeによる行数増加が誤って「重複」としてカウントされないかは、SB-3のクラスタリングロジックがsuperseded_byを考慮していないため、次章で懸念点として記録する）。

---

## 5. Step 2（伝達済み管理、last_mentioned_at）に影響しそうな発見・気づいた懸念点

- **SB-3（`memory_duplicate_rate`、`eval_metrics.py::compute_memory_duplicate_rate()`）が`superseded_by`を考慮していない。** 同関数は`user_fact_items`の全アクティブ事実（embeddingを持つもの）に対して全ペアのコサイン類似度を計算するが、supersedeされた古いstate行と新しいstate行は、定義上ほぼ同じ内容（同じcategory/key、意味的に類似したvalue）になりやすく、**意図的に「重複」として検出されてしまう可能性が高い**。ただし今回の変更により`get_fact_items_with_embeddings(active_only=True)`はsuperseded行を自動的に除外するようになったため（3.5節）、SB-3が`get_fact_items_with_embeddings`経由でデータを取得している限りは影響を受けない。`eval_runner.py`の実装を確認したところ`get_fact_items_with_embeddings`を使っており、この経路では問題ないと判断したが、念のため4節の運用者向け確認事項に含めた。
- **Step2（last_mentioned_at、伝達済み管理）との関係**: 今回`valid_from`（現実世界でいつから真か）を導入したが、これは「シグマリスがいつこの情報を**最後に伝えたか**」（Step2が扱う想定の概念）とは別軸の情報である。Step2を設計する際は、「`updated_at`（システムがいつ最後に触ったか）」「`valid_from`（現実世界でいつから真か、今回追加）」「`last_mentioned_at`（ユーザーにいつ最後に話したか、Step2で追加予定）」の3つの時間軸が独立して存在することになる点に注意が必要。特に「数日前の出来事を今日起きたことのように報告する」という当初の問題は、実は`valid_from`（Step1）だけでは完全には解決しない可能性がある——event種別のfactの`valid_from`は今回明示的に設定していない（3.4節のルールベース推定は`memory_kind='state'`の場合のみ発動する設計にした。event自体にも同様の推定を適用すべきか検討したが、eventは「一時的な出来事」という定義上、抽出された瞬間＝出来事が起きた瞬間である可能性が高く、そもそも`created_at`が実質的な発生日時を表すことが多いと判断し、依頼書の設計（stateにのみvalid_from）に厳密に従った）。「今日起きたことのように報告する」問題の直接的な解決には、event/stateの`valid_from`/`created_at`と、応答生成時にそれを「いつの話か」として言語化するロジック（persona.mdの指示やプロンプト側の工夫）が別途必要であり、これはStep1のスコープ外（スキーマ・分類・減衰・supersedeの基盤整備まで）である点を明記しておく。
- **`memory_validator.py`の`float(item.get("importance_score") or 0.5)`が明示的な0.0を0.5に化けさせる既存の挙動**（4節で発見）。本タスクとは無関係だが、次タスクで修正を検討する価値がある（`item.get("importance_score")`が`None`の場合のみ`0.5`にフォールバックし、`0.0`はそのまま`0.0`として扱うよう`is None`判定に変更する、という小さな修正で直せる）。
- **`decision_log.py`のsupersedeパターン（A3、`sigmaris_decision_log.superseded_by`）は「呼び出し元がフィルタする」設計だったが、今回の`user_fact_items`向けsupersedeは「DBクエリ層（`active_only`）で一元的にフィルタする」設計にした。** 同じ「supersede」という概念が、2つのテーブルで異なるフィルタリング責務の置き方をしていることになる。将来的にこの非対称性が混乱を招く可能性があるため、次タスクで両者の設計方針を統一するか、あるいは意図的な違いとして文書化するかを検討する価値がある（decision_logは常に少数の呼び出し元しか持たないため呼び出し元フィルタで十分だったが、user_fact_itemsは非常に多くの読み取り経路を持つため、今回はクエリ層フィルタを選んだ、という違いがある）。
- **`memory_kind='trait'`は、既存の`preferences`カテゴリや、B14の`sigmaris_user_preference_patterns`と概念的に重複しうる。** 依頼書の指示通り今回はラベル付けのみで新規ロジックは実装していないが、将来的に「`memory_kind='trait'`の`user_fact_items`行」と「B14が抽出する`sigmaris_user_preference_patterns`行」の関係（同じ情報が二重に記録される可能性はないか等）を整理する価値があるかもしれない。
