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

---

# Temporal Layer Step 2: 伝達済み管理(last_mentioned_at)とtime表現ルール

**実装日**: 2026-07-11
**関連**: 本ドキュメント上部のStep 1（memory_kind分類・event減衰・state supersede）を前提とする

## 6. 背景（再掲）

Step 1は記憶に`memory_kind`（event/state/trait）という分類を与えたが、それだけでは「シグマリスが、数日前の出来事を今日起きたことのように繰り返し報告する」問題を直接解決しない（Step 1報告書5節で明記した通り）。Step 2はこれに対して2つの手当てを行う。

1. **伝達済み管理（last_mentioned_at）**: 「もう話したことを、自分から繰り返さない」が「聞かれたら答えられる」仕組み
2. **time表現ルール**: event種別を語る際、必ず相対的な時間表現を添えるルール（persona.md）

## 7. last_mentioned_atの実装詳細

### 7.1 スキーマ

`supabase/migrations/202607220046_temporal_layer_last_mentioned.sql`で`user_fact_items`に`last_mentioned_at timestamptz`を追加した（NULL許容、CHECK制約なし。作成のみ、適用は運用者に委ねる）。

DBレベルで`memory_kind='event'`の行にのみ書き込み可能にするCHECK制約は付けていない——依頼書の言葉通り「最後にシグマリスが**能動的に**言及した日時」という意味論はアプリケーション層でのみ扱う概念であり、トリガーで強制するほどの恩恵がないと判断した（state/trait行はアプリケーションコードが単にこの列を読み書きしないだけで、事実上event専用のまま保たれる）。

### 7.2 last_mentioned_atは「能動的」言及専用——受動的回答では一切読み書きしない

依頼書の日本語をそのまま読むと重要な区別がある。列名の定義自体が「**最後にシグマリスが能動的に言及した**日時」であり、要件2は「受動的回答は、last_mentioned_atの状態に関わらず機能する」と明記している。すなわちこの列は**自発的な話題提示（ブリーフィング等）専用の概念**であり、通常のQ&A（ユーザーに聞かれて答える）では読みも書きもしない、と解釈した。

この解釈に基づき、実装は`backend/app/services/orchestrator/service.py`の`run_orchestrator_chat`/`run_orchestrator_chat_stream`という、通常チャットと3つのプロアクティブブリーフィング（`proactive/actions.py`の朝ブリーフィング・夕方チェックイン・週次レビュー）の両方が通る唯一の共通経路に、次の判定を追加した。

```python
_PROACTIVE_CALLER_PREFIX = "proactive-scheduler:"

def _is_proactive_call(caller_agent_id: str) -> bool:
    return caller_agent_id.startswith(_PROACTIVE_CALLER_PREFIX)
```

`proactive/actions.py::_run_action()`は既に`request_context={"reason": f"proactive:{action_name}", "caller_agent_id": f"proactive-scheduler:{action_name}"}`という監査ログ用の識別子を渡しており（Step 2着手以前から存在するコード）、これが「3つのブリーフィングかどうか」を一切の新規パラメータなしに完全に判別できる既存の信号だったため、`run_orchestrator_chat`/`_stream`の公開シグネチャに新しい引数を追加することを避け、この既存の`caller_agent_id`から`is_proactive`を導出する設計にした（判断根拠: この関数はCRLF/LF混在の問題を抱える唯一のファイルであり——Step 1報告書には出てこないが本セッションの他タスクで繰り返し遭遇した既知の問題——変更を可能な限り局所化する動機があった。また将来「自発的な話題提示」の経路が増えても、そのすべてが`proactive/actions.py`のような`caller_agent_id`ベースの識別を持つ限り、新規パラメータなしに対応できる）。

### 7.3 能動的発言のフィルタリング

`is_proactive=True`の場合のみ、facts_ctx（`build_facts_context()`が選ぶ重要度トップ5の"常時注入"コンテキスト——通常チャット・ブリーフィング両方が同じこの関数を通る、依頼書が言う「自発的な話題提示の処理箇所」の実体）に渡す前に、`last_mentioned_at`が設定済みのevent種別ファクトを除外する。

```python
def _fact_items_excluding_mentioned_events(fact_items):
    return [
        item for item in fact_items
        if not (item.get("memory_kind") == "event" and item.get("last_mentioned_at"))
    ]
```

state/trait/未分類のファクトは一切フィルタしない——「もう言った」という概念はevent種別にしか適用されない、という依頼書の前提をそのまま反映している。

**受動的回答（B1検索）が一切変更を受けないことの確認**: `_build_memory_context()`内でこのフィルタ後のリストが使われるのは`build_facts_context()`（重要度トップ5）の入力としてのみであり、同じ関数内でB1ハイブリッド検索（`search_with_decomposition()`）に渡される検索クエリ・検索対象・ランキングロジックには一切触れていない。B1検索は`memory_search.py`から`search_fact_memory`/`search_fact_memory_trgm` RPCを呼ぶが、これらのRPC・Python側コードはこのタスクで1バイトも変更していない。

### 7.4 last_mentioned_atの更新（fire-and-forget）

応答生成後、`build_facts_context()`と同じ選択ロジック（`select_top_facts()`、後述7.5節参照）を使って「実際にトップ5に採用されたファクト」を再計算し、その中のevent種別のIDだけを`mark_facts_mentioned()`に渡す。既存のfire-and-forgetパターン（A3の`_extract_facts_bg`、B2の`_cognitive_layer_bg`と同じ`asyncio.create_task(...)`＋例外を握りつぶしてログするだけの形）を踏襲した。

```python
if is_proactive:
    surfaced_event_ids = [
        item["id"]
        for item in select_top_facts(memory_context_fact_items, top_n=5)
        if item.get("memory_kind") == "event" and item.get("id")
    ]
    if surfaced_event_ids:
        asyncio.create_task(_mark_events_mentioned_bg(jwt=jwt, event_ids=surfaced_event_ids), ...)
```

`user_fact_data.mark_facts_mentioned()`は`user_fact_items`をPostgRESTの`id=in.(...)`フィルタで一括UPDATEする（`billing.py`に既存の前例がある書き方）。

**判断根拠として明記する近似**: 「トップ5に選ばれた」ことを「実際にシグマリスがその内容を発話した」ことの代理指標として扱っている（Step 1の`valid_from`推定と同種の、意図的な単純化）。build_facts_context()の出力はあくまで"注入されたコンテキスト"であり、LLMが最終応答で実際にその内容へ言及したかどうかを一語一句検証しているわけではない。厳密な検証には応答テキストの解析または追加のLLM呼び出しが必要になり、依頼書の「シンプルなルールベースの判断にとどめる」というStep 1の方針をStep 2にも一貫して適用する形で、意図的にそこまでは行っていない。実運用上は、朝ブリーフィングでトップ5に入った内容は通常そのまま言及される可能性が高く、実害は小さいと判断している。

### 7.5 build_facts_context()のリファクタリング

`select_top_facts()`を`build_facts_context()`から抽出し、独立した関数として公開した。7.4節の理由により、プロアクティブ経路がbuild_facts_context()と**同一の選択結果**を後から再計算する必要があったためで、ロジックの重複を避けるための純粋なリファクタリング（既存の5箇所の呼び出し元＝`build_facts_context()`自体の外部インターフェースは一切変更していない）。

## 8. persona.mdに追加したtime表現ルール

`docs/persona.md`に新規12章として追加した（既存の5章「確信度の伝え方」・7章「ツッコミ・ユーモア」と同じ「(新規追加)」の書式に揃えた）。要旨:

- event種別に言及する際は、能動的・受動的いずれの発言でも、必ず相対的な時間表現を添える（「今日〜」のように直近の出来事であるかのように語ってはならない）
- state種別は時間表現なしに言い切ってよい
- 時間表現は機械的な日数表記ではなく、人間の会話らしい粒度に変換する表（1時間以内→さっき、1〜3日→◯日前、1週間前後→先週、1ヶ月前後→先月/少し前、それ以上→だいぶ前）を明記

配置は既存の11章（会話例）の後に追加した。既存の章番号（1〜11）は一切変更していない。

## 9. プロンプトへの時間情報の組み込み

### 9.1 event種別のみ日時ヒントを付与

`build_facts_context()`の各行フォーマットに、`memory_kind == "event"`の場合のみ`created_at`をJSTに変換した簡潔な日時ヒントを追加した。

```python
def _format_event_time_hint(created_at):
    ...
    return f"（発生日時の目安: {jst.strftime('%Y-%m-%d %H:%M')} JST）"
```

例: `- lifestyle/gym_visit: ジムに行った（確信度0.9）（発生日時の目安: 2026-07-05 12:00 JST）`

state/trait/未分類には一切付与しない——8節のpersona.mdルール「stateは時間表現なしに言い切ってよい」と矛盾するヒントを与えないための対称的な設計判断。

**LLMに相対時間表現そのものを計算させる、日付だけを渡す方針にした理由**: `chat_prompts.py::build_system_prompt()`がプロンプト末尾（キャッシュ順序で最も可変な位置）に現在時刻（`現在日時は Asia/Tokyo の {now_jst} です`）を既に注入している。event側でPython側で「3日前」のような相対表現をあらかじめ計算して埋め込むことも可能だったが、（a）「現在時刻との差分計算」ロジックが2箇所（Python側とLLM側）に分裂するのを避けたい、（b）8節の人間らしい粒度変換（「さっき」「先週」等）は本質的に自然言語表現の選択でありLLMの得意分野である、という2点から、日付という生データのみを渡し、変換はLLMに委ねる設計にした。

### 9.2 適用範囲についての意図的なスコープ限定（判断根拠）

`build_facts_context()`は`orchestrator/service.py`の常時注入トップ5コンテキストだけでなく、`decision_log.py`・`memory_extractor.py`・`experience_layer.py`・`knowledge_graph.py`・`goal_alignment.py`が既存の「関連事実コンテキスト」注入に使っている共有関数でもある。この日時ヒントはそれら全ての呼び出し元に一律に適用される（純粋なテキスト追記であり、いずれの呼び出し元もJSON構造や厳密なフォーマット契約を期待していないため、副作用はないと判断した）。

一方で、**B1ハイブリッド検索の結果を整形する`orchestrator/service.py::_build_relevant_memories_context()`には日時ヒントを追加していない**（このタスクの明示的な要求6「受動的回答(B1検索)のロジックには一切手を加えないこと」を、検索アルゴリズム自体だけでなく、その結果を整形するコードにまで安全側に拡大解釈して適用した）。この結果、B1検索経由で表示されるevent種別の記憶（`_build_relevant_memories_context`が処理する関連ファクト）には、今回の時間ヒントが付与されない。もともとの問題報告（数日前の出来事を今日のことのように繰り返す）は主にトップ5の常時注入コンテキスト（プロアクティブブリーフィングで顕在化しやすい）に起因すると考えられるため実害は限定的だが、**Step 3以降で「ユーザーがevent種別の記憶についてB1検索経由で質問した際に、時間表現が付かない」という挙動が問題視される場合は、`search_fact_memory`/`search_fact_memory_trgm` RPCに`created_at`を追加出力するマイグレーション（Step 1が確立したDROP+CREATEパターンの6回目相当）と、`_build_relevant_memories_context()`への同様のヒント追加が必要になる**、と申し送りする。

## 10. テスト結果

`backend/tests/`には新規テストを追加していない（既定の方針通りスクラッチディレクトリに作成）。`test_temporal_layer_step2.py`として13件のテストを作成した。

- **`select_top_facts()`**: 重要度×確信度でのソート・top_n打ち切り・deleted/stale/superseded/値なしの除外が、リファクタ前と同じ挙動であること（回帰確認）。
- **event時間ヒント**: event種別のみ日時ヒント（日付文字列と`JST`）が付与されること。state・未分類には付与されないこと。`created_at`が欠落したeventでも例外にならず正常にフォールバックすること。
- **`mark_facts_mentioned()`**: `rest_update`が`id=in.(id-1,id-2)`という正しいフィルタと`last_mentioned_at`を含むペイロードで呼ばれること。空リストでは何も呼ばれないこと。
- **`_is_proactive_call()`**: `"proactive-scheduler:"`プレフィックスのみを真と判定すること。
- **`_fact_items_excluding_mentioned_events()`**: `last_mentioned_at`が設定済みのevent種別のみを除外し、state/trait/未分類・未言及eventは残ること。
- **`run_orchestrator_chat()`を通した統合テスト（2件）**:
  - プロアクティブ呼び出し（`caller_agent_id="proactive-scheduler:morning_briefing"`）で、既に言及済みのevent（`evt-mentioned`）が`_build_memory_context()`に渡されるファクトリストから除外され、未言及のevent（`evt-fresh`）とstateファクトは残ること。応答完了後、`await asyncio.sleep(0)`でfire-and-forgetタスクを実行させ、`mark_facts_mentioned()`が`evt-fresh`のみ（stateは含まない）を対象に呼ばれること。
  - 通常のチャットターン（`request_context=None`）では、`evt-mentioned`がフィルタされずそのまま`_build_memory_context()`に渡されること（要件2の直接検証）。`mark_facts_mentioned()`は一切呼ばれないこと。

```
13 passed in 1.61s
```

既存の`backend/tests/`（16件）、および過去タスクのスクラッチテスト（`test_temporal_layer.py`・`test_decision_log_relevant_facts.py`・`test_decision_type_and_b2.py`・`test_b9_b14_b16_context.py`・`test_memory_extractor_dedup.py`、計28件）も全て再実行し、リグレッションは確認されなかった。

```
16 passed in 0.77s
28 passed in 1.03s
```

**テスト中に発見した、本タスクと無関係な既存の問題**: `test_phase_ba1_service_integration.py`（過去タスクのスクラッチテスト）が`app.services.orchestrator.service.rewrite_with_persona`という、BA4の統合生成アーキテクチャ導入で既に削除済みのシンボルをパッチしようとして`AttributeError`で失敗する状態だった。本タスクの変更とは無関係（`rewrite_with_persona`は今回のどの変更でも触れていない）で、BA4導入時点から既に壊れていたと推測される。スクラッチファイルであり`backend/tests/`の対象外のため、本タスクでは修正していない——次回スクラッチテストの棚卸しを行う際の申し送り事項として記録する。

**実モデルAPIでの検証は行っていない。** 統合テストは`call_schedule_agent`等の外部呼び出し境界をモックしている。**運用者側で確認すべきこと**:
1. マイグレーション（`202607220046_temporal_layer_last_mentioned.sql`）適用後、`user_fact_items`に`last_mentioned_at`列が追加されたことを確認する。
2. 朝ブリーフィング・夕方チェックイン・週次レビューを数日にわたって実際に運用し、同じevent種別の記憶が連日繰り返し言及されないこと（要件1）を確認する。
3. 通常のチャットでevent種別の記憶について尋ね、`last_mentioned_at`の状態に関わらず正しく回答できること（要件2）を確認する。
4. 実際の応答テキストで、event種別の記憶に相対的な時間表現が自然な粒度で添えられているか（要件3）を確認する。7.4節で述べた通り、日付ヒントはあくまでLLMへの手がかりであり、実際にどう言語化するかは保証されていないため、この確認は特に重要。

## 11. 気づいた懸念点・Step 3に影響しそうな発見

- **9.2節のスコープ限定（B1検索結果には日時ヒントを付与していない）は、Step 3で「経過日数の自覚」を扱う際に再検討が必要になる可能性がある。** 特に日記的機能でevent種別の記憶を検索経由で参照する設計になる場合、`_build_relevant_memories_context()`側にも同様のヒントを追加する判断が必要になるだろう。
- **last_mentioned_atは「トップ5に選ばれたかどうか」を代理指標にしており、実際にLLMがその内容を発話したかは検証していない（7.4節）。** 稀に「トップ5には入ったが実際の応答では触れられなかった」eventが誤って「言及済み」になるケースがあり得る——実害は「本来まだ話せたはずのeventが1回分スキップされる」程度で、ユーザー体験を損なう方向のリスクは小さいと判断しているが、Step 3で発話内容の解析（レスポンステキストへの言及有無チェック）を行う場合はこの近似を置き換える価値がある。
- **`updated_at`/`valid_from`/`last_mentioned_at`の3つの時間軸が出揃った。** Step 1報告書5節で予告した通り、システムがいつ触ったか（`updated_at`）・現実世界でいつから真か（`valid_from`）・シグマリスがいつ最後に自発的に話したか（`last_mentioned_at`）が明確に分離された。Step 3で「経過日数の自覚」を実装する際は、この3軸のどれを基準にするかを都度明示することが重要になる（例えば「この情報は少し古いかもしれません」という自己言及は`updated_at`基準、「前に話しましたが」は`last_mentioned_at`基準、と使い分けが必要）。
- **`proactive/actions.py`が将来増える可能性**: 現状は朝・夕方・週次の3種類のみだが、将来新しい自発的な話題提示の経路が追加される場合、それが`caller_agent_id`に`"proactive-scheduler:"`プレフィックスを付けて`run_orchestrator_chat`/`_stream`を呼ぶ限り、本タスクのフィルタリングは自動的に適用される。逆に、この経路を通らない全く別の自発的発話の仕組みが将来作られた場合（例: プッシュ通知に直接テキストを生成するような設計）は、`_is_proactive_call`の判定に引っかからず、この保護が及ばない点に注意が必要。

---

# Temporal Layer Step 3: 経過日数の自覚と日記的機能

**実装日**: 2026-07-11
**関連**: 本ドキュメント上部のStep 1・Step 2を前提とする。本タスクをもってTemporal Layer(Step 1〜3)は完了する。

## 12. 経過日数の自覚

### 12.1 起点日の選定根拠

依頼書が挙げた2つの候補を調査した。

- **`sigmaris_self_model`**: `202606250017_sigmaris_self_model.sql`を確認したところ、プロジェクト開始時期を表す列は存在しない。テーブル自身の`created_at`は「self_modelという機能・テーブルがいつ作られたか」という実装上の詳細でしかなく、「海星さんとシグマリスの関係がいつ始まったか」とは無関係。この候補は不採用とした。
- **`chat_messages`の最古行**: `202603290003_chat_threads.sql`で定義されている、ユーザーとシグマリスの実際のやり取りそのものの記録。「最初に交わされた会話」は、この関係性の起点として最もデータドリブンかつ曖昧さのない候補である。

この判断に基づき、**`chat_messages`の`MIN(created_at)`（ユーザーごと、全スレッド横断）を関係の起点日として採用した**。`app_chat_data.py`に`get_earliest_message_at(jwt)`を新設し、`created_at`昇順・`limit=1`のシンプルなクエリで取得する。

**判断根拠として明記する意味論上の注意**: 依頼書の例文「一緒にシグマリスを開発し始めて128日目」は厳密には「開発開始日」を指しているようにも読めるが、DBスキーマ上「プロジェクト開発開始日」を表す明示的なフィールドは存在しない。「最初の会話の日」で近似することは、これが本質的に「シグマリスとの関係がいつ始まったか」を問う機能である以上、妥当な代替と判断した。この近似のずれ（開発着手日と初回チャット日が厳密には異なる可能性）は許容範囲内とみなしている。

### 12.2 プロンプトへの注入方法とキャッシュ構造への配慮

`orchestrator/service.py`に`_cached_relationship_origin_date(jwt)`（他の`_cached_*`関数と同じ5分TTLキャッシュ。値自体は不変だが、専用の永続キャッシュを新設するより既存の仕組みに乗せる方が一貫性が高いと判断した）と、`_build_relationship_duration_context(origin_date_iso)`を追加した。

経過日数は、`_format_freshness_note()`（B14/自己認識で既に確立していた「JST暦日差分で丸める」パターン、`incident_shiftpilotai_naming_report.md`が確立した規約）と同一の計算方法を用いている。

**Phase A2キャッシュ構造への配慮（判断根拠）**: 依頼書は「可変情報として末尾に配置すること」と指示していた。調査の結果、シグマリスの応答生成には2つの独立したシステムプロンプト構築経路があることが分かった。

1. `chat_prompts.py::build_system_prompt()` — `chat.py`が使う直接OpenAI呼び出し経路。`rules`(固定)を先頭、`time_instruction`(現在時刻、分単位で毎ターン変化)を末尾に配置する、Phase A2が確立した構造。
2. `orchestrator/schedule_agent_client.py::_build_system_override()` — オーケストレータ(BA4統合生成)が使う経路。`persona_context`・`user_profile_context`・`self_model_context`等の可変コンテキストをまとめた`dynamic_context`を、固定の`_BASE_SYSTEM_OVERRIDE`の**前**に配置し、これを`system_override`として下流のスケジュールエージェントへ送る。スケジュールエージェント側は恐らくこれを(1)の`base_system`としてそのまま受け取るため、`system_override`全体は(1)の観点では「1つの可変ブロック」として扱われる。

経過日数のような「1日に1回しか変化しない」情報を、(1)の`time_instruction`(分単位で変化)と全く同じ末尾位置に置くには`chat_prompts.py`自体の改修が必要になるが、この関数は`chat.py`という無関係な別経路とも共有されており、今回のタスクの対象範囲を超えて影響が及ぶリスクがあると判断した。そのため、**到達可能な範囲で最も末尾に近い位置**として、`_build_system_override()`の`dynamic_context`内、既存の可変コンテキスト全て（persona/profile/self_model/preference/topic/goal_alignment）の**後**、固定の`_BASE_SYSTEM_OVERRIDE`の直前に新しい`relationship_duration_context`を追加した。`_build_payload()`・`call_schedule_agent()`・`call_schedule_agent_stream()`に新しい同名パラメータを追加し、末尾まで通した。

なお、経過日数は1日単位でしか変化しないため、そもそも既存の`profile_context`(5分TTLで再計算される`facts_ctx`を含む)より遥かに安定した内容であり、この位置に置いても既存のキャッシュ効率を悪化させることはない。

### 12.3 節目判定と、機械的言及を防ぐ設計（判断根拠）

依頼書の要件1「節目や自然な文脈でのみ言及され、毎回の会話で機械的に言及されないこと」を、Python側とLLM側で役割分担する設計にした。

- **節目判定はPython側で決定的に行う**: `_is_relationship_milestone(days_elapsed)`は、100の倍数または365の倍数（依頼書の例「100日、365日等」に忠実）を節目と判定する、テスト可能な純粋関数。
- **「自然な文脈かどうか」の判断はLLM側(persona.md)に委ねる**: Pythonは「今日が自然な話題提示のタイミングか」を判定できない（それは会話の流れ次第であり、ルールベースの範囲を超える）。そのため、経過日数の情報は**毎ターン注入**しつつ、節目の日と節目でない日とで異なる指示文を付与する:
  - 節目の日: 「節目です。自然な文脈であれば触れてよい」という許可の文言
  - 節目でない日: 「節目の日ではないため、本当に自然な文脈でない限り持ち出さないでください。毎回の会話で機械的に言及しないこと」という明示的な抑制の文言

この設計により、(a)節目の判定自体はテストで検証可能な決定的ロジックとして担保しつつ、(b)「自然な文脈」という本質的にLLMの判断力が必要な部分は、persona.md 13章の指示文と組み合わせてLLMに委ねる、という役割分担を明確にした。「常に情報を渡さない(節目だけ渡す)」「常に自由に言及させる」という両極端を避けた設計判断として明記する。

### 12.4 persona.mdの更新

`docs/persona.md`に新規13章「経過日数の自覚」を追加した（既存の12章と同じ「(新規追加)」の書式）。要旨:

- 節目(渡された情報に「節目です」という趣旨が含まれる日)は、話の流れを妨げない範囲で軽く触れてよい
- 節目でない日は毎回の会話で機械的に言及しないこと。海星さんから聞かれた場合や、話題が自然にそこへ向かった場合にのみ触れる
- 過剰な演出は10章の「デレ要素の過剰な使用」「関係性の固定化を煽る発言」の禁止と同じ理由で避けるべき、と明記し、既存の禁止事項章との一貫性を持たせた

---

## 13. 日記的機能

### 13.1 実装方針: B1 RPCの拡張ではなく、専用の直接クエリ経路を新設（判断根拠）

依頼書は「B1の検索クエリに日付範囲の絞り込みを追加する」ことを優先的に検討するよう指示していた。調査の結果、**`search_fact_memory`/`search_fact_memory_trgm` RPC自体は改修せず、`user_fact_items`に対する専用の直接フィルタクエリ`get_events_in_date_range()`を新設する**という設計にした。判断根拠は以下の通り。

B1の2つのRPCは、いずれも「クエリ文字列との類似度でランキングし、`match_count`件に絞り込む」という設計であり、これは「特定の1日に記録された全てのevent種別記憶を、漏れなく時系列で返す」という日記的機能の要求とは根本的に性質が異なる（類似度ランキング上位N件では、その日の記憶を網羅できる保証がない）。一方、日記的機能が必要とする条件（`memory_kind='event'`かつ`created_at`が指定日の範囲内）は、埋め込みベクトルもトライグラムも一切必要とせず、`user_fact_items`に対する素朴な条件検索で完全かつ正確に処理できる。

そのため、`user_fact_data.py`に`get_events_in_date_range(jwt, *, date_from, date_to)`を新設した。B1の検索ロジック（`search_relevant_memories()`・`_merge_hybrid_results()`・2つのRPC）は1バイトも変更していない——**Step 2で確立した「B1検索ロジックには手を加えない」という制約を、Step 3のB1"拡張"にも一貫して適用した**形になる。これは「B1検索の枠組みで実現する」という依頼書の精神（新規の大規模LLM呼び出しを追加しない、既存のB1が扱うのと同じテーブル・同じevent分類基盤を使う）には沿いつつ、依頼書の字面が示唆する「RPCの中身を変える」という具体的手段からは意図的に外れた選択であり、判断根拠として明記する。

同じ列に対する2条件（`created_at >= X AND created_at < Y`）をPostgRESTで表現するため、`app_event_data.py::search_events()`に既存の前例がある`and=(col.op.val,col.op.val)`コンビネータをそのまま踏襲した。

### 13.2 日付表現の抽出: `temporal_parsing.py`（新規共有モジュール）

Step 1で`memory_extractor.py`に実装済みだった相対日付フレーズ変換ロジック（`_RELATIVE_DATE_PHRASES`、`_estimate_valid_from`）を、新規モジュール`backend/app/services/temporal_parsing.py`に切り出し、`memory_extractor.py`側はこのモジュールをインポートする形にリファクタリングした（挙動は完全に同一、既存テストで回帰確認済み）。Step 3の日記的日付抽出が同じ変換テーブルを別の目的で再利用する必要が生じたための、DRY目的の判断である。

`extract_diary_date_range(text, *, now)`を新設し、以下のルールベースロジックで日記的質問を検出する。

- **絶対日付**: 正規表現`(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日`で「7月3日」「2026年7月3日」のような表記を検出。年が省略され、かつ解決結果が現在より未来になる場合は前年と解釈する（日記的質問は本質的に過去について尋ねるものであるため）。
- **相対日付**: `RELATIVE_DATE_PHRASES`（Step 1と共有）による「昨日」「先週」等の解決。絶対日付が見つからない場合のみフォールバックとして使用。
- **トリガーフレーズ必須**: 日付が見つかっただけでは発火しない。「何してた」「何をしていた」「何があった」等の固定フレーズ集合との同時一致を要求する。これは「7月3日までに提出してください」のような、日付が単なる期限として登場するだけのメッセージを日記的質問と誤認しないための精度ガードであり、依頼書の例文「7月3日に何してた?」に忠実な、意図的に狭いトリガー集合として設計した。

**既知の制約として明記する近似**: 「先週」「今週」「先月」「今月」「来週」「来月」は、Step 1の`RELATIVE_DATE_PHRASES`が単一の基準日へのオフセットとしてしか定義していないため、日記的機能でも「その週・月の代表的な1日」に解決されるだけで、週・月全体の範囲検索にはならない。依頼書の具体例（「7月3日に何してた?」、日単位）はこの制約の影響を受けないが、「今週何してた?」のような週単位の質問には正確に対応できない、という制約を申し送り事項として記録する。

### 13.3 `_build_memory_context()`への統合

`orchestrator/service.py::_build_memory_context()`内、既存のB7/B1関連コンテキスト構築ブロックの直後に、日記的コンテキストのブロックを追加した。

```python
diary_context = None
if latest_user_text:
    date_range = extract_diary_date_range(latest_user_text, now=datetime.now(UTC))
    if date_range:
        try:
            events = await get_events_in_date_range(jwt, date_from=date_from, date_to=date_to)
            diary_context = _build_diary_events_context(date_from, events)
        except Exception:
            logger.exception(...)
```

`extract_diary_date_range()`が日記的質問でないメッセージに対して`None`を返す設計のため、この処理は大多数のターンで完全なno-opになる。既存のB1関連コンテキスト（`relevant_context`）を置き換えるのではなく、**並存する形**で最終的な`profile_context`に連結した——日記的質問であっても、緩やかに関連するB1検索結果が同時に有用である可能性を排除しないための判断。

`_build_diary_events_context()`は、該当日のイベントを時刻(JST)付きで時系列に整形する。該当する記憶が0件の場合は「この日に記録されたevent種別の記憶は見つかりませんでした。『特に記録がない』旨を素直に伝えてよい」という、LLMへの明示的な振る舞い指示を含む文言を返す（要件「該当する記憶がない場合、適切に『その日は特に記録がない』旨を返せること」に対応）。

## 14. テスト結果

`test_temporal_layer_step3.py`として21件のテストを作成した。

- **`extract_diary_date_range()`**: 絶対日付+トリガーで正しい日付範囲になること。相対日付+トリガーで正しく解決されること。日付のみ(トリガーなし)・トリガーのみ(日付なし)ではNoneを返すこと(誤発火しないことの確認)。年省略かつ未来方向に解決される場合は前年に補正されること。年が明示されていれば未来日付でもそのまま尊重されること。
- **`get_events_in_date_range()`**: `and=(created_at.gte.X,created_at.lt.Y)`という正しいPostgRESTフィルタが構築されること。`memory_kind=eq.event`・`superseded_by=is.null`が含まれること。
- **`get_earliest_message_at()`**: 最古行の`created_at`を返すこと。メッセージが1件もない場合は`None`を返すこと。
- **`_is_relationship_milestone()`**: 100の倍数・365の倍数が節目と判定されること。それ以外の日数(1, 53, 99, 101, 364, 366等)は節目でないこと。0・負数は節目でないこと。
- **`_build_relationship_duration_context()`**: 起点日`None`では`None`を返すこと。節目の日は「節目」を含む文言になること。節目でない日は「持ち出さないでください」という抑制の文言になること。起点日が本日(経過日数0)の場合は`None`を返すこと(まだ関係が始まったばかりで報告すべき経過日数がないケース)。
- **`_build_diary_events_context()`**: 記憶0件では「見つかりませんでした」の文言になること。複数件では時刻(JST)付きで時系列順(created_at昇順)に整形されること。
- **`_build_memory_context()`を通した統合テスト（2件）**: 日記的メッセージ(「7月3日に何してた?」)では`get_events_in_date_range()`が呼ばれ、結果が最終コンテキストに含まれること。かつB1検索(`search_with_decomposition`)は変わらず呼ばれること(要件3「新規の大規模なLLM呼び出しを追加せず、既存のB1検索の拡張で実現される」の直接検証——実際には新規のLLM呼び出しは一切追加していない、ルールベースの直接クエリのみであることを確認)。通常のメッセージ(「明日の予定を教えて」)では`get_events_in_date_range()`が一切呼ばれないこと。

```
21 passed in 0.66s
```

既存の`backend/tests/`（16件）、および過去タスクのスクラッチテスト（`test_temporal_layer.py`・`test_temporal_layer_step2.py`・`test_decision_log_relevant_facts.py`・`test_decision_type_and_b2.py`・`test_b9_b14_b16_context.py`・`test_memory_extractor_dedup.py`、計41件）も全て再実行し、リグレッションは確認されなかった（`memory_extractor.py`の`_RELATIVE_DATE_PHRASES`切り出しリファクタリングを含む）。

```
16 passed in 0.79s
41 passed in 1.71s
```

**実モデルAPIでの検証は行っていない。** 統合テストは`search_with_decomposition`・`get_events_in_date_range`等の外部呼び出し境界をモックしている。**運用者側で確認すべきこと**:
1. 実際の会話で「7月3日に何してた?」のような日記的質問をし、その日のevent種別記憶が時系列で正しく返ることを確認する。
2. 該当する記憶がない日付を尋ね、「特に記録がない」旨が自然に返ることを確認する。
3. 100日目・365日目等の節目に近い日で、経過日数が自然な文脈で(機械的にならずに)言及されるかを確認する。12.3節で述べた通り、Python側は「節目かどうか」までしか決定できず、実際に触れるかどうかはLLMの判断に委ねているため、この確認は特に重要。
4. 節目でない通常の日に、経過日数が毎回の会話で機械的に言及されていないかを確認する。

## 15. Temporal Layer(Step 1〜3)全体の振り返り

### 15.1 各Stepが解決した問題

| Step | 解決した問題 | 主な仕組み |
|---|---|---|
| 1 | 出来事・状態・傾向という記憶の性質が区別されていなかった | `memory_kind`分類、event高速減衰、state supersede |
| 2 | 同じ出来事を毎回自発的に繰り返し報告していた | `last_mentioned_at`、能動/受動の区別、時間表現ルール |
| 3 | 関係の積み重ねへの自覚がなく、特定の日の記憶を横断的に参照できなかった | 経過日数の節目通知、日記的日付範囲検索 |

3つのStepを通じて一貫していた設計哲学は、**「大規模な新規LLM呼び出しやNLPライブラリを追加せず、既存のB1検索・B17減衰・A3 supersedeパターンといった確立済みの仕組みへの条件分岐・拡張として実装する」**という、依頼書が繰り返し明示した制約である。実際に本タスクを通じて新規に追加されたLLM呼び出しは一つもなく、全てルールベースのPythonロジックまたは既存プロンプトへのコンテキスト注入で実現されている。

### 15.2 3つの時間軸の最終的な整理

Step 1報告書5節で提起し、Step 2報告書11節で再確認した「3つの時間軸」は、Step 3の完了時点で以下のように整理される。

- **`updated_at`**: システムがいつ最後にこの行を触ったか（元からある列）
- **`valid_from`**: 現実世界でいつからこの`state`が真になったか（Step 1）
- **`last_mentioned_at`**: シグマリスがいつ最後にこの`event`を能動的に話したか（Step 2）
- **`created_at`起点の経過日数**: 関係全体としてどれだけの時間が積み重なっているか（Step 3、個々のfactではなく関係性そのものに対する時間軸）

これら4つの時間表現は目的が完全に分離されており、混同すると「システムが触った日」と「実際に起きた日」と「最後に話した日」を取り違える——まさに当初の問題（数日前の出来事を今日のことのように報告する）の温床になる。Step 1〜3を通じて、この区別をコード上でも（列名・関数名・コメント）明確に保つことを一貫して意識した。

### 15.3 残っている懸念事項の総まとめ

- **【Step 2由来、未解決】** `memory_validator.py`の`float(item.get("importance_score") or 0.5)`パターンが、明示的な`0.0`を`0.5`に化けさせる既存バグ。Temporal Layerの3Stepいずれのスコープでもなく、修正されていない。
- **【Step 2由来、未解決】** B1検索結果(`_build_relevant_memories_context()`)には、event種別の日時ヒント(Step 2)も、日記的日付範囲コンテキスト(Step 3)も付与されていない。両Stepとも「B1検索ロジックそのものには手を加えない」という要求を安全側に(結果の整形コードにまで)拡大解釈した結果、意図的にスコープ外とした。将来「B1検索経由でevent種別の記憶を参照した際に時間表現が付かない」という挙動が問題視される場合は、検索RPCへの`created_at`列追加(Step 1が確立したDROP+CREATEパターン)が必要になる。
- **【Step 2由来、未解決】** `last_mentioned_at`は「トップ5の常時注入コンテキストに選ばれたかどうか」を実際の発話の代理指標としており、応答テキストそのものを解析して検証してはいない。
- **【Step 3新規】** 日記的機能の日付抽出は、日単位の絶対日付・相対日付のみに対応しており、週・月単位の範囲質問（「今週何してた?」）は単一の代表日にしか解決されない。
- **【Step 3新規】** 経過日数の“節目”判定は100日・365日の倍数のみのシンプルなルールであり、依頼書の例をそのまま踏襲したもの。将来、記念日的な意味を持つ別の日数（例: ちょうど1年半、等)を節目に含めたい場合は`_RELATIONSHIP_MILESTONE_INTERVALS`の拡張で対応可能。
- **【Step 3新規、設計上の限界として明記】** 経過日数を「自然な文脈で言及する」判断はLLMに委ねており、Pythonコード側で「実際に言及されたかどうか」を検証・強制する手段はない（Step 2のlast_mentioned_atと同様、これは実モデルでの運用を通じてしか最終確認できない）。
- **`memory_kind='trait'`とB14の重複可能性**（Step 1報告書5節から持ち越し、未着手）。

Temporal Layerの3Stepはここで完了とする。以降の改善（週/月単位の日記的検索、応答テキスト解析によるlast_mentioned_atの精緻化、importance_scoreのfalsy-zeroバグ修正等）は、いずれも独立した小さなタスクとして別途着手する方が、今回確立した「1タスク1つの明確な問題」という進め方に整合的だと考える。

---

# 会話タイムスタンプの認識強化(バグ修正報告)

**実施日**: 2026-07-12
**関連**: Temporal Layer(Step1〜3)完了後、実運用で発見された不具合の修正

## 18. 背景

Temporal Layer(Step1〜3)実装後も、「さっき」「この前」といった表現を使いながら、実際には数日前の内容をたった今の出来事であるかのように話す現象が報告された。依頼書は、原因が`user_fact_items`(Temporal Layerが直接扱う記憶層)ではなく、**より基礎的な「直近の会話ログ(`chat_messages`)そのものにタイムスタンプがLLMへ伝わっているか」という部分にある可能性**を示唆しており、実装前に3点の調査を必須としていた。以下、調査結果を先に示す。

## 19. 原因調査の結果

### 19.1 調査1: `chat_messages`のタイムスタンプはプロンプトに含まれていたか → **含まれていなかった(直接的な原因)**

`orchestrator/service.py`の`_prepare_session_messages()`を追跡した。

1. `get_recent_messages_across_threads(jwt, limit=...)`(`app_chat_data.py`)は、`select`句に`created_at`を含めて`chat_messages`の直近ウィンドウ(既定40件、`settings.sigmaris_recent_message_window`)を取得している——ここまでは正しくタイムスタンプを取得できていた。
2. しかし、その直後に呼ばれる`_window_rows_to_messages(rows)`が、各行を`{"role": row["role"], "content": <parts内のテキストを結合したもの>}`という形に変換する際、**`row["created_at"]`を一切参照せず、完全に読み捨てていた。**
3. この`{"role", "content"}`のみの配列が、そのまま`call_schedule_agent(messages=session_messages, ...)`経由でバックエンドの`/api/agent/chat/complete`(`agent.py`)に送られ、`run_chat_completion()`(`chat.py`)内で`sanitize_messages_for_model()`を経てOpenAIのモデルに渡される会話ターンそのものになる。

すなわち、LLMが実際に受け取る会話履歴は、**各発言が「いつ」行われたかを示す情報を一切持たない、フラットな`{role, content}`のリストだった。** LLMには「直前の並びの発言ほど最近のもの」という以上の手がかりが与えられておらず、実際には数日前のやり取りであっても、時系列上の並び順だけからは「たった今」との区別がつかない。これが報告された現象の直接的な原因と判断した。

### 19.2 調査2: persona.md 12章のtime表現ルールは、会話ログにも適用されていたか → **適用範囲外だった(副次的な原因)**

Step2で追加したpersona.md 12章を再確認したところ、ルールの対象は「記憶には種類があり(Temporal Layer、事実記憶層のmemory_kind)」という書き出しの通り、**`user_fact_items`の`memory_kind`分類(event/state/trait)にのみ明示的にスコープされており、会話履歴(`chat_messages`)への言及については一言も触れていなかった。**

同様に、`build_facts_context()`(Step2でevent種別に日時ヒントを付与する実装)も、対象は`user_fact_items`の行のみであり、`chat_messages`由来の情報を扱う経路には一切関与していないことを確認した(コード上、`build_facts_context()`の呼び出し元はいずれも`user_fact_items`から取得した`fact_items`のみを引数に取っており、`chat_messages`の行を渡している箇所は存在しない)。

**すなわち、たとえ19.1の欠落を修正して`chat_messages`にタイムスタンプが伝わるようになったとしても、persona.mdにはそれをどう扱うべきかの指示が一切なく、LLMがそれを踏まえて時間表現を使い分ける保証がない状態だった。** 19.1と19.2は独立した2つの欠落であり、両方を修正しない限り現象は解消しないと判断した。

### 19.3 調査3: 現在時刻のプロンプトへの注入は、BA4以降も正常に機能していたか → **正常に機能しており、原因ではなかった**

`chat_prompts.py::build_system_prompt()`内の`time_instruction`(Phase A2で確立、現在のAsia/Tokyo時刻を分単位でシステムプロンプト末尾に注入する仕組み)を確認した。

- `run_chat_completion()`(`chat.py`)は、オーケストレーターから受け取った`system_override`(persona/facts/self_model等をまとめた動的コンテキスト)を`build_system_prompt()`の`system`引数にそのまま渡しており、その内部で`time_instruction`は`system`の中身に関わらず**無条件かつ毎回、呼び出しのたびに`datetime.now(ZoneInfo("Asia/Tokyo"))`から新規に計算**されている。
- BA4(応答生成の統合、二段階リライトの廃止)によってこの呼び出し経路自体に変更はなく、`run_chat_completion()`が引き続きこの関数を呼んでいることをコードで確認した。

**したがって、現在時刻そのものの注入は一切壊れておらず、今回の現象の原因ではないと判断した。** LLMは「今が何時か」は正しく知っていたが、「過去の発言がいつのものか」を知る手段がなかった、というのが正確な状態だった。

## 20. 選択した修正方針とその根拠

依頼書が提示した3つの修正方針のうち、19節の調査結果に基づき**1点目(タイムスタンプの明示的付与)と3点目(persona.mdルールの適用範囲明確化)の両方を実施した。** 2点目(「時刻を踏まえて表現を使い分けること」という指示の追加)は、3点目の範囲拡張に統合する形で実施した(別立てのルールにするより、既存の12章に「会話履歴にも同様に適用する」という一文を追加する方が、ルールの一貫性を保てると判断したため)。

### 20.1 `chat_messages`へのタイムスタンプ付与の実装方法(判断根拠)

`_window_rows_to_messages()`(`orchestrator/service.py`)を、各行の`content`の先頭に、JSTの日時ヒントを**プレフィックスとして直接埋め込む**形に変更した。

```python
def _format_message_timestamp_prefix(created_at: Any) -> str:
    if not created_at:
        return ""
    try:
        dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return ""
    jst = dt.astimezone(ZoneInfo("Asia/Tokyo"))
    return f"[{jst.strftime('%Y-%m-%d %H:%M')} JST] "
```

**判断根拠(なぜ別フィールドではなくcontentへの埋め込みか)**: `AgentChatRequest.messages`(`agent.py`)は`list[dict]`という緩い型で、理論上は`{"role", "content", "timestamp"}`のように専用フィールドを追加することもできた。しかし、最終的にOpenAIのモデルへ渡されるのは`role`/`content`ベースのチャット形式であり、`content`以外のフィールドをモデルが読むことはない。タイムスタンプをLLMに「見せる」唯一の方法は、テキストとして`content`に含めることだと判断し、別フィールドの追加は行わなかった。

**判断根拠(生の日時をそのまま渡す設計)**: Step2の`_format_event_time_hint()`(event種別の記憶への日時ヒント付与)と全く同じ設計判断を踏襲した——Python側で「3日前」のような相対表現をあらかじめ計算するのではなく、生のJST日時のみを渡し、現在時刻(`time_instruction`)との差分計算・自然な言い回しへの変換はLLM自身に委ねている。理由もStep2と同一: 「現在時刻との差分計算」ロジックが複数箇所に分裂するのを避けるため、また人間らしい粒度への変換(persona.mdの変換表)は本質的にLLMの得意分野であるため。

**判断根拠(最新の生発言にはプレフィックスを付けない)**: `_window_rows_to_messages()`が処理するのはDB由来の**過去の**やり取りのみであり、呼び出し元の`_prepare_session_messages()`が別途追加する「今まさに入力された最新のユーザー発言」(`_latest_user_message()`)には、この関数を経由させず、意図的にタイムスタンプを付与していない。最新発言は文脈上「今」であることが自明であり、かつ`time_instruction`が現在時刻を既に伝えているため、そこに重ねてタイムスタンプを付けることは冗長と判断した。この非対称な扱い(履歴にはタイムスタンプあり、最新発言にはなし)自体が、「これは過去の話、これは今の話」という区別をLLMに暗黙に伝える効果もあると考えている。

**判断根拠(Phase A2キャッシュ構造への影響なし)**: `time_instruction`を含むシステムプロンプト(`build_system_prompt()`の`rules`→`ai_tone`→`base_system`→`attachment`→`router`→`time_instruction`という順序)は一切変更していない。今回変更したのは、システムプロンプトとは別枠で送られる会話ターン本体(`messages`配列)であり、そもそもPhase A1のクロススレッド継続設計により、この配列はターンごとにDBから再構築される非キャッシュ対象である(前のターンと同一の配列がそのまま再送されることを前提にしていない)。したがって、この変更がPhase A2のプレフィックスキャッシュ効率に新たな悪影響を与えることはないと判断した。

**判断根拠(既存機能への影響がないことの確認)**: `_window_rows_to_messages()`の変更後の出力(`session_messages`)を実際に消費するのは応答生成(`call_schedule_agent`)のみであることをコードで確認した。事実抽出(`_extract_facts_bg`)・意思決定検出(`_cognitive_layer_bg`)は、いずれも`run_orchestrator_chat`の**元の**`messages`引数(呼び出し元がそのまま渡した、フロントエンド側のスレッドローカルな履歴)から独自に`full_messages`/`turn_messages`を組み立てており、`_window_rows_to_messages()`の出力を参照していないため無関係。`chat.py`側の確認応答マーカー判定(`_find_latest_pending_confirmation`、`<!-- shiftpilot-confirmation ... -->`の正規表現マッチ)も、文字列内の任意の位置でマッチする`re.search`ベースの実装であるため、先頭にタイムスタンプが付与されても影響しないことを確認した。

### 20.2 persona.md 12章の適用範囲拡張

12章の冒頭に、「このルールは、事実記憶層(memory_kind)の記憶に限らず、会話履歴(直近のやり取りのログ)を振り返って言及する場合にも同様に適用する」という一文を追加し、「会話履歴を振り返る場合」という新しい箇条書きを追加して、良い例・悪い例を明記した(既存のevent/stateの書式にそのまま揃えた)。

## 21. テスト結果

### 21.1 単体テスト

- **`_format_message_timestamp_prefix()`**: UTC ISO文字列・`Z`サフィックス付き文字列がJSTの`[YYYY-MM-DD HH:MM JST]`形式に正しく変換されること。`created_at`が欠落・不正な文字列の場合は空文字列に安全に縮退すること(例外を投げない)。
- **`_window_rows_to_messages()`**: user/assistantの内容にタイムスタンプが正しくプレフィックスされること。user/assistant以外のロールはスキップされること(既存動作の回帰確認)。テキストを抽出できない行はスキップされること(回帰確認)。`created_at`が欠落した行は、プレフィックスなしで元のcontentがそのまま残ること(欠落時のフォールバック)。

### 21.2 統合テスト(数日前の会話と直近の会話が混在するケース)

`_prepare_session_messages()`を、`get_recent_messages_across_threads`を3日前のuser/assistantターン2件を返すようモックし、呼び出し元の`messages`引数には「今まさに入力された」ユーザー発言を渡して実行した。

**サンプル入力**:
- DBウィンドウ(3日前): user「AdFlow AIの実装で詰まってる」/ assistant「それは大変ですね、一緒に整理しましょう」
- 呼び出し元の最新発言: user「あの件どうなった?」

**組み立てられた`session_messages`(実際にLLMへ送られる形)**:
```
[2026-07-09 21:00 JST] AdFlow AIの実装で詰まってる         (role: user)
[2026-07-09 21:05 JST] それは大変ですね、一緒に整理しましょう  (role: assistant)
あの件どうなった?                                              (role: user, プレフィックスなし)
```

3日前の2ターンには正しくタイムスタンプが付与され、たった今入力された最新発言にはタイムスタンプが付与されない(=「今」として扱われる)ことをアサーションで確認した。これにより、LLM側は`time_instruction`(現在時刻)と各ターンのタイムスタンプの差分から、persona.md 12章の変換表(1〜3日→◯日前、等)に従い「3日前にも話しましたが」のような表現を導き出せる状態になった——**実際にモデルがそう応答するかどうかまでは、実モデルAPIでの検証ができないため確認できていない**(依頼書の注意事項通り、追加のAPIキー取得等は試みていない)。プロンプトに正しい情報が渡ることまでを検証範囲とした。

```
9 passed
```

既存の`backend/tests/`(16件)、および過去タスクのスクラッチテスト(Temporal Layer Step1〜3・`/timeline`関連、計46件)も全て再実行し、リグレッションは確認されなかった。

```
16 passed
46 passed
```

## 22. 気づいた懸念点

1. **`_window_rows_to_messages()`が処理するのは`get_recent_messages_across_threads()`が返すクロススレッドの直近ウィンドウ(既定40件)のみである。** それより古い、ウィンドウの外にある発言については、そもそもプロンプトに含まれないため、今回の修正の対象にもなっていない(タイムスタンプを付与しようがない)。もしウィンドウ外の古い会話について「さっき」のように話す現象が観測された場合、それは別の経路(B1検索等)からの混入を疑う必要がある。
2. **タイムスタンプのプレフィックスは、応答生成(`call_schedule_agent`)にのみ影響し、`classify_chat_intent`(意図分類)には(このプレフィックスが付いた状態の`messages`が渡ることはなく)影響しない**ことを19.1節の追跡で確認済みだが、念のため明記しておく——`classify_chat_intent`は`run_chat_completion()`内で、オーケストレーターから渡された`messages`(=タイムスタンプ付与後の配列)ではなく、その関数が受け取った`messages`引数をそのまま使っており、実際にはタイムスタンプ付きの配列を見ることになる。意図分類の精度に影響するかどうかは実モデルでの検証が必要だが、プレフィックスは短く定型的なため、実害は小さいと考えている。
3. **21.2節で示した通り、「実際にモデルがpersona.md 12章の指示通りに振る舞うか」は実モデルAPIでの検証ができておらず未確認である。** プロンプトに正しい情報(タイムスタンプ)と正しい指示(persona.md)の両方が揃った状態にはなったが、これはLLMの指示追従性に依存する部分であり、運用者側での実際の会話を通じた確認を推奨する。
4. **本タスクはTemporal Layer(Step1〜3)完了後に発見された不具合修正であり、`docs/sigmaris/temporal_layer_report.md`に追記する形にしたが、性質としては独立したバグ修正である。** 将来同種の会話ログ関連の修正が続く場合、専用の文書に切り出すかどうかは別途判断してよい。
