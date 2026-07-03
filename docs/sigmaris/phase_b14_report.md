# Phase B14 実施報告: 意思決定パターンのモデリング(差別化の核)

**目的:** `sigmaris_decision_log`の蓄積から、海星さんの判断傾向(判断軸)を抽出・保持し、新規の提案・応答に反映できるようにする。
**作業ブランチ:** `phase-b14-decision-pattern-modeling`(Phase A0〜A5・C-mini・JWT永続化・LLMRouter修正・FREE LIMIT削除・B1・B4・B17がマージ済みの`main`から新規作成)
**範囲:** B13等、他のB群機能には着手していない。`importance_score`は背景章の前提通り、判断軸の抽出根拠として一切使用していない。

---

## 0. baseline値・効果測定の性質について(指示書の注意事項の遵守)

指示書の通り、本タスクはC-miniの3指標では効果測定できない領域(事実想起ベンチマークでは点数化されない判断軸の学習)であるため、**C-miniのスコアではなく定性テスト(5章)を主たる効果確認とした。** `run_eval.py`の参考値取得も試みたが、この環境からは実行できなかった(0章末尾参照、過去のタスクと同一の制約)。

---

## 1. 判断傾向の抽出ロジックの実装詳細

### 既存の`analyze_decision_patterns()`とは別に、新規関数を実装した(判断根拠)

`decision_log.py`には既に`analyze_decision_patterns()`(Sunday 4:30スケジュール実行)が存在していたが、詳細を確認したところ、これは**シグマリス自身の行動分布**(`proposal_rate`・`refusal_rate`など、シグマリスが何を提案し何を拒否したかの比率)を分析するものであり、**海星さん自身の判断軸**を抽出するものではなかった。加えて、この関数は結果をどこにも永続化していなかった(呼び出し元の`scheduler.py::_decision_analyze()`がログ出力するだけ)。

このため、**既存関数を拡張・流用せず、新規に`extract_preference_patterns()`を実装した。** 既存関数と混同しないよう、プロンプト・保存先・目的を完全に分離している。既存の`analyze_decision_patterns()`は一切変更していない(要件5)。

### 抽出頻度: 週次バッチ(既存の`_decision_analyze`ジョブと同じSunday、直後の4:45に配置)

「毎回のdecision_log書き込み時」ではなく「定期バッチ」を選んだ。判断根拠:

1. 決定(`decision_type`に関わらず全体)は、チャットの1ターンごとに発生する`memory_extractor`のfact抽出等と比べて**本質的に低頻度**(Phase A3の`detect_and_record_decision`は「実際に決定・方針転換が含まれる場合のみ」記録するため)。毎回LLM分析を走らせるのは無駄が大きい。
2. 「複数の決定に共通するパターン」を見つけるという目的上、1件の新規決定が追加されるたびに全体を再分析する必要性は薄い。既存の`_decision_analyze`(Sunday 4:30)と同じ週次カデンスに揃えることで、同じ`sigmaris_decision_log`を対象とする分析処理を近い時間帯にまとめ、運用上の一貫性を保った。

### 抽出プロンプトの設計

```
_EXTRACT_PREFERENCE_PROMPT:
- decision_type=policy_change を主対象とし、それ以外(proposal/refusal等)は
  reason/outcomeに価値観が読み取れれば参考にしてよいと明示
- 「1件の決定だけを根拠に傾向を導き出さないこと」を明示的な制約として記載
- 各傾向に、根拠とした決定のidを全て列挙させる(下記2章・3章参照)
- 根拠が薄ければ patterns: [] を返してよいと明示(データ不足の正直な扱い)
```

### データ不足時のハンドリング(2段階のガード)

1. **総件数ガード**: `sigmaris_decision_log`の総件数が`_MIN_DECISIONS_FOR_ANALYSIS`(3件)未満の場合、**LLMを一切呼び出さずに**`insufficient_data: true`を返して終了する(「複数の決定に共通するパターン」を探すこと自体が3件未満では原理的に無意味なため、コストをかけずに早期リターンする設計)。
2. **傾向単位のガード**: LLMが返した各候補傾向について、`supporting_decision_ids`が`_MIN_SUPPORTING_DECISIONS`(2件)未満なら**保存せず破棄する**。さらに、LLMが返したidが実際に送信した決定記録の中に存在するかを検証し(存在しないidは**信用せず除外**)、除外後に2件未満になった場合も破棄する。LLMの出力を無条件には信頼しない設計にした(5章のテストで、存在しないidを1件混ぜた場合に正しく破棄されることを確認済み)。

---

## 2. 保持先のテーブル設計とその判断根拠

**新規テーブル`sigmaris_user_preference_patterns`を作成した(マイグレーション`202607100032_user_preference_patterns.sql`、未適用)。**

```sql
create table public.sigmaris_user_preference_patterns (
  id                            uuid primary key default gen_random_uuid(),
  pattern_key                   text not null unique,
  pattern_statement             text not null,
  supporting_decision_ids       jsonb not null default '[]'::jsonb,
  evidence_count                integer not null default 0,
  first_detected_at             timestamptz not null default timezone('utc', now()),
  last_confirmed_at             timestamptz not null default timezone('utc', now()),
  last_analyzed_decision_count  integer not null default 0,
  created_at / updated_at       timestamptz ...
);
```

### 判断根拠: `sigmaris_self_model`の拡張ではなく新規テーブルを選んだ

指示書の推奨通り、`sigmaris_self_model`(シグマリス自身の自己記述)と混同しないよう、別テーブルにした。加えて:

- `sigmaris_self_model`は**単一行**(バージョン管理される1つの自己記述文)。一方、海星さんの判断軸は「速度重視」「OSS好き」「長期保守性重視」のように**複数の独立した軸**として存在するのが自然であり、`user_fact_items`や`sigmaris_decision_log`同様、**1傾向=1行**のリスト構造が適切と判断した。
- **RLSは`service_role_only`とした**(`sigmaris_decision_log`・`sigmaris_self_model`・`sigmaris_experience`と同じパターン)。理由: このテーブルはシグマリスが海星さんについて導き出した**内部的な理解**であり、ユーザーが直接CRUDする対象ではない(バックエンドのバッチジョブのみが書き込む)、という性質が`user_fact_items`(ユーザー起点でRLSスコープされる事実)よりも`sigmaris_decision_log`等の「認知レイヤー」データ群に近いと判断した。

### `pattern_key`によるupsert方式(根拠件数は蓄積される)

同じ`pattern_key`が再度検出された場合、既存行の`supporting_decision_ids`と新規のものをマージし(重複排除)、`evidence_count`を更新する。これにより、ある傾向が最初は2件の根拠で検出されても、その後の週次実行で新しい決定が同じ傾向を裏付けるたびに根拠が積み上がっていく設計にした(2章のテストで、既存2件+新規2件(1件重複)→3件にマージされることを確認済み)。

### 根拠決定への参照(要件3、Phase B4の出所情報活用)

`supporting_decision_ids`(jsonb配列)に`sigmaris_decision_log.id`をそのまま格納している。Phase B4で追加した`thread_id`/`invocation_id`をこの配列の各要素から`sigmaris_decision_log`を引くことで辿れるため、「なぜこの傾向が導かれたか」を実際の会話まで追跡可能にしている(Phase B4の出所トラッキングの直接的な活用)。

---

## 3. 応答への反映方法

### プロンプトへの組み込み方: `chat_prompts.py`の固定ルールには追加せず、既存の動的コンテキストパイプに新規の第3のパイプとして追加した

`orchestrator/service.py`が`self_model_context`(シグマリス自己認識)・`user_profile_context`(記憶・fact)と同じ仕組みで`preference_patterns_context`を構築し、`schedule_agent_client.py::_build_system_override()`(既存の2パラメータに1つ追加)を通じてプロンプトに注入する。

**`chat_prompts.py`の`rules`配列(固定・毎ターン必ず含まれる、Phase A2のキャッシュ最適化の対象)には一切追加していない。** 判断根拠:

1. `rules`はOpenAIのプレフィックスキャッシュの要であり(Phase A2)、判断傾向が1件も無い間(現状のように`sigmaris_decision_log`のデータが少ない状態、6章参照)でも常に固定コストのトークンを消費するのは無駄と判断した。
2. `preference_patterns_context`は`self_model_context`と同様、**該当データが存在する場合のみ**注入される可変コンテキストであり(`_build_preference_patterns_context()`はパターンが空なら`None`を返す)、このパイプに載せる方が自然。

### ヘッジの実装: persona.md 5章の3階層をそのままコードに落とし込んだ

```python
_PREFERENCE_PATTERN_HYPOTHESIS_MAX_EVIDENCE = 3

def _build_preference_patterns_context(patterns):
    ...
    tier = "仮説層(要ヘッジ)" if evidence_count <= 3 else "傾向層(柔らかい言い切り可)"
    lines.append(f"- {statement} (根拠決定{evidence_count}件、{tier}、{freshness_note})")
```

persona.md 5章の「事実層/傾向層/仮説層」のうち、判断傾向は**性質上「事実層」に到達することがない**(必ず推測)ため、「仮説層」と「傾向層」の2段階のみをマッピングした。根拠件数が`_MIN_SUPPORTING_DECISIONS`(2)ギリギリの間は仮説層(「もしかしたら〜かもしれません」)、根拠が積み上がって4件以上になったら傾向層(「〜な傾向がありますね」)に格上げされる。**どちらの階層でも「断定してはいけない」「決めつける口調にしない」という指示は共通して含めており**(3章のテストで確認)、傾向層に上がっても事実層相当の言い切りにはならないようにした。

### 鮮度情報の実装(self_modelの教訓を踏襲)

`docs/sigmaris/incident_shiftpilotai_naming_report.md`で修正した`_format_self_model_freshness()`(日単位の相対鮮度ラベル)を、**汎用ヘルパー`_format_freshness_note()`にリネームして両方の機能から共有**した。self_model・preference_patternsのどちらも「いつのデータか分からないまま断定的に使われる」という同種の問題を抱えうるため、同じロジックを再利用する形にした(コードの重複を避け、将来同種の機能が増えた場合にも同じ関数を使い回せる)。判断傾向の各行には`(根拠決定N件、仮説層/傾向層、最終更新: N日前)`という形式で、根拠件数と鮮度の両方を必ず含めている(要件4)。

---

## 4. データ不足時のハンドリング方法とテスト結果

いずれもモック(実DB・実LLM未接続)。

### 抽出ロジック

```
PASS: 2 decisions (< min 3) -> extraction skipped entirely, no LLM call, insufficient_data=True
PASS: a candidate pattern with only 1 supporting decision is found but NOT stored
PASS: a pattern with 3 supporting decisions is stored with all supporting ids preserved
PASS: an LLM-invented decision id (not present in the actual decision set) is filtered out
```

要件1(複数決定からの傾向抽出)・要件2(データ不足の正直な扱い)を直接検証している。1つ目のケースは、決定が2件しかない状態でLLM呼び出しすら発生しないことを確認しており、無駄なコスト・無理な結論付けの両方を防いでいることを示す。4つ目は、LLMの出力を無条件に信頼しない設計(存在しない決定idを混入させた場合に正しく検出・除外される)を確認している。

### 保存ロジック(evidence蓄積)

```
PASS: _upsert_preference_pattern() creates a new row when pattern_key doesn't exist yet
PASS: _upsert_preference_pattern() merges new evidence into an existing pattern without losing prior evidence or duplicating overlaps
```

要件3(根拠決定への参照)を直接検証している。

### 応答反映(ヘッジ)

```
PASS: no stored patterns -> no context injected at all
PASS: evidence_count=2 (<=3) -> tagged 仮説層 (must-hedge tier)
PASS: evidence_count=8 (>3) -> softer 傾向層 tier, but the 'never flatly assert' instruction still applies
PASS: both evidence count and freshness (staleness) are shown per pattern
```

要件4(鮮度・確信度に応じたヘッジ)を直接検証している。

### 既存機能への非破壊確認(要件5)

- `backend/tests/`(既存8件)全てPASS、`import app.main`成功(循環importの懸念があったため個別に確認済み — `decision_log.py`の依存チェーンは`orchestrator`に触れないため問題なし)。
- Phase B1・B4・B17・Phase C-miniの既存テストを全て再実行し、全てPASSすることを確認した(`_format_self_model_freshness`のリネームを含む変更が既存機能に影響していないことを直接確認)。
- 既存の`analyze_decision_patterns()`・`log_decision()`・`detect_and_record_decision()`には一切変更を加えていない。

---

## 5. 現時点での`sigmaris_decision_log`の蓄積件数と本機能の実用性の所見

**この環境からは確認できなかった。** `backend/.env`に実クレデンシャルが無く、`sigmaris@192.168.179.11`へのSSHも接続タイムアウトのままだった(過去のタスクと同一の制約、再確認済み)。

指示書自身が「LLMRouterのバグの影響もあり、まだ十分な件数が蓄積されていない可能性が高い」と明記している通り、`_MIN_DECISIONS_FOR_ANALYSIS`(3件)にすら届いていない可能性は十分にある。その場合、本機能は`insufficient_data: true`を返し続けるだけで、`sigmaris_user_preference_patterns`には何も書き込まれない — **これは実装のバグではなく、意図した通りの正しい挙動である。**

**実用性の所見**: 本機能は「データが溜まれば自動的に機能し始める」設計にしてあるため、今すぐ有効な傾向を返せなくても実装として無駄にはならない。むしろ、Phase A3(decision_log本稼働)・Phase C-mini(LLMRouterバグ修正)を経て今後decision_logへのデータ蓄積が正常化していけば、追加のコード変更なしに本機能が実質的に「立ち上がる」はずである。運用者には、`sigmaris_decision_log`のデータが数週間分蓄積された時点で、`preference_pattern_extract`ジョブのログ(Sunday 4:45)を確認し、実際にパターンが抽出され始めているかを見ていただくことを推奨する。

---

## 6. 気づいた懸念点・次のB機能(B13: 暗黙フィードバック)に影響しそうな発見

1. **`decision_type=policy_change`が実際にどの程度の頻度で記録されているか、この環境からは分からない。** もし`policy_change`型の決定がほとんど無く、大半が`proposal`/`refusal`等のシグマリス側行動記録に偏っている場合、本機能が抽出する「傾向」の精度・関連性が下がる可能性がある。B13(暗黙フィードバック)は「提案の採用/不採用ログ」を扱うため、`proposal`/`refusal`型の決定と直接関係が深い — B13着手時に、本機能とデータソースが重複する部分がないか確認する価値がある。
2. **`_MIN_DECISIONS_FOR_ANALYSIS`(3)・`_MIN_SUPPORTING_DECISIONS`(2)は実データでの検証ができていない暫定値。** decision_logの蓄積が進んだ段階で、これらの閾値が厳しすぎる(なかなか傾向が出てこない)か緩すぎる(こじつけ気味の傾向が出てくる)かを実際に観察して調整する必要がある。
3. **抽出頻度を週次にしたこと(1章)により、新しい決定が記録されてから傾向に反映されるまで最大1週間のタイムラグがある。** これは意図した設計(コスト削減・低頻度データへの適合)だが、もし将来「直近の決定をすぐ傾向に反映してほしい」というニーズが出てきた場合、B13の「暗黙フィードバック」の実装と合わせて、より即時性の高い更新経路を検討する余地がある。
4. **`preference_patterns_context`は`orchestrator/service.py`の2つの呼び出し経路(`run_orchestrator_chat`・`run_orchestrator_chat_stream`)双方に配線したが、実際にプロンプトへ注入された状態でのLLM応答は実モデルで検証できていない。** ヘッジの指示文自体はテストで確認済みだが、LLMが実際にその指示に従って自然な日本語で応答するかは、実運用で確認が必要。

---

## Related Documents

- [phase_b4_report.md](phase_b4_report.md) — 根拠決定への参照で活用した出所トラッキングの基盤
- [phase_b17_report.md](phase_b17_report.md) — `importance_score`を判断軸抽出に使わない、という本タスクの前提の発端
- [incident_shiftpilotai_naming_report.md](incident_shiftpilotai_naming_report.md) — `_format_freshness_note()`(旧`_format_self_model_freshness`)の元実装
- [sigmaris_roadmap.md](sigmaris_roadmap.md) — Phase B群全体の計画、B14→B13の順序
