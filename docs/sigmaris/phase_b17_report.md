# Phase B17 実施報告: Memory Importance Learning(既存importance_scoreの活用範囲拡張)

**目的:** `user_fact_items.importance_score`(既存列)の活用範囲を、検索順位・忘却耐性まで一貫して拡張する。新規機能の追加ではなく既存シグナルの活用範囲拡張という位置づけ。
**作業ブランチ:** `phase-b17-importance-learning`(Phase A0〜A5・C-mini・JWT永続化・LLMRouter修正・FREE LIMIT削除・B1・B4がマージ済みの`main`から新規作成)
**範囲:** B14・B13等、他のB群機能には着手していない。

---

## 0. baseline値の性質について(B1・B4と同様、指示書の注意事項の遵守)

指示書の通り、本タスクの効果確認は主に**「重要度の高い記憶が実際に優先される・消えにくくなるか」という機能テストで行い**、C-miniのスコア変動をもって成否を判断していない。`run_eval.py`の数値(取得できた場合)は参考値としてのみ扱う。

---

## 1. 現状の`importance_score`の使われ方(再確認)

### 発見: `importance_score`は現状「per-fact学習値」ではなく「カテゴリ層の代理値」である

`202606270019_trend_memory.sql`の`set_fact_category_defaults()`トリガーを確認したところ、**`importance_score`はBEFORE INSERTトリガーによって、渡された値に関係なくcategoryから機械的に上書きされる**設計だった(goals=1.0, health=0.9, profile=0.8, relationships=0.8, finance=0.7, lifestyle=0.6, preferences=0.5, devices=0.4, environment=0.4)。つまり現時点では、同じcategoryのfactは全て同じ`importance_score`を持つ — 個々の記憶内容の重要性を反映した学習値ではなく、**カテゴリの粗い優先順位付け**に近い。

この点はタスクの前提(「Memory Importance Learning」という名称が示唆する、個別に学習される重要度)とは異なる現状である。**本タスクのスコアは「importance_scoreの計算方法を変える」ことではなく「既存のimportance_score(現状はカテゴリ代理値)の活用範囲を広げる」ことだったため、トリガー自体には触れていない。** ただしこの制約は5章・4章で改めて触れる。

### 既存の使用箇所

| 箇所 | 用途 | 変更要否 |
|---|---|---|
| `user_fact_data.py::build_facts_context()` | `importance_score × confidence`降順で上位N件抽出 | 変更不要(既存のまま) |
| `memory_validator.py` Phase 3(論理削除) | `importance_score × confidence < 0.1`で論理削除 | **既に実装済みと確認**(コード変更不要、2章参照) |
| `memory_validator.py` Phase 1(信頼度減衰) | category別の`_DECAY_RULES`のみ、importance_score未考慮 | **今回実装**(3章) |
| `search_fact_memory`/`search_fact_memory_trgm` RPC | `importance_score`を一切返していなかった | **今回追加**(4章) |

---

## 2. 検索順位への反映(B1のハイブリッド検索との統合)

### RPCの変更(マイグレーション`202607090031_importance_weighted_search.sql`、未適用)

`search_fact_memory`・`search_fact_memory_trgm`の両RPCが`importance_score`を一切返していなかったため、`RETURNS TABLE`に列を追加した。PostgreSQLは`CREATE OR REPLACE FUNCTION`で戻り値の列構成を変更できないため、`DROP FUNCTION`してから再作成する形にした。

### `memory_search.py::_merge_hybrid_results()`への重み付け実装

```python
_IMPORTANCE_RANKING_WEIGHT = 0.15  # importance_score=1.0で最大+15%のスコア倍率

def _importance_weighted_score(base_score, row):
    importance = row.get("importance_score")
    importance = float(importance) if importance is not None else 0.5
    return base_score * (1.0 + importance * _IMPORTANCE_RANKING_WEIGHT)
```

RRFスコア・高信頼度トライグラムヒットのスコア、両方にこの重みを掛けてから最終順位を決定する。**ただし「近接完全一致ティア」(トライグラム類似度0.5以上)と「通常のRRFティア」という2段構造(B1で実装済み)は維持し、重要度による並べ替えは各ティアの**内部**でのみ行う** — importance_scoreがどれほど高くても、通常のRRFティアの結果が近接完全一致ティアを飛び越えて上位に来ることはない。

### 判断根拠: 係数0.15を選んだ理由と、試した値

1. **RRFスコアはランク位置に基づく(生の類似度差ではない)ため、「同程度の関連度」を「ランクの近さ」として捉える必要がある。** これは実装中に再確認した重要な事実である。rank1とrank2のRRFスコア差は約1.6%程度と非常に小さいため、小さな重みでも隣接ランクの逆転には十分に効く。逆にどれだけ重みを上げても、ランクが十分離れていれば逆転しない(下記の実測データ参照)。
2. **`0.10`・`0.15`・`0.30`の3つを実際にコードで試し、「rank1(importance=0.0, 最不利条件)」対「rankN(importance=1.0, 最有利条件)」がNをいくつまで離すと逆転しなくなるかを実測した:**

   | rank差(N) | w=0.10で逆転するか | w=0.15で逆転するか | w=0.30で逆転するか |
   |---|---|---|---|
   | 7 | する | する | する |
   | 8 | **しない** | する | する |
   | 10 | しない | する | する |
   | 11 | しない | **しない** | する |
   | 19 | しない | しない | する |
   | 20 | しない | しない | **しない** |

   （importance側を最有利・最不利の極端な組み合わせにしているため、実運用でこれより逆転しやすいことはない — 実際の重要度差はここまで極端になることは稀）

3. **`0.15`を採用した根拠:** `0.30`はrank差19という、実用上「明らかに無関係」と言えるほど離れた候補まで逆転し得る大きさであり、要件3(関連度の正確性を損なわない)に対するリスクが大きいと判断した。`0.10`はrank差7までしか逆転させられず、`search_relevant_memories`の既定`limit=5`前後の候補プール内での「僅差の逆転」という当初の狙いに対してやや保守的すぎると判断した(limit=5の範囲内でも8番目・10番目相当の僅差候補まで拾えなくなる)。`0.15`はrank差10程度までを逆転可能範囲としており、`limit=5`という実際の検索件数に対して「近い順位の僅差」を拾いつつ、rank差20のような明確な差は一貫して逆転させない、というバランス点として選んだ。

---

## 3. 忘却耐性への反映(memory_validator.pyとの統合)

### Phase 1(信頼度減衰)に importance_score を組み込んだ

```python
_IMPORTANCE_DECAY_ONSET_EXTENSION = 1.0     # importance=1.0で減衰開始までの日数が最大2倍に延長
_IMPORTANCE_DECAY_SEVERITY_DAMPENING = 0.5  # importance=1.0で減衰の下げ幅(1-decay_factor)が最大50%緩和

def _importance_adjusted_decay(base_decay_days, base_decay_factor, importance_score):
    importance = max(0.0, min(1.0, importance_score))
    effective_days = round(base_decay_days * (1.0 + importance * _IMPORTANCE_DECAY_ONSET_EXTENSION))
    severity = 1.0 - base_decay_factor
    dampened_severity = severity * (1.0 - importance * _IMPORTANCE_DECAY_SEVERITY_DAMPENING)
    effective_factor = 1.0 - dampened_severity
    return effective_days, effective_factor
```

例(health category, base_decay_days=30, base_decay_factor=0.5):
- `importance=0.0`: 変化なし(30日, factor=0.5)
- `importance=1.0`: 減衰開始が60日に延長、減衰時の下げ幅が0.5→0.25に緩和(factor=0.75)

**完全な免除にはしていない**(要件3の通り)。importance=1.0でも、十分に時間が経てば(この例では60日超)減衰は発生する。効果はあくまで「開始を遅らせる・下げ幅を緩める」であって「止める」ではない。

### Phase 2(矛盾検出)には一切手を加えていない

指示書の要件3「重要度が高くても明らかに矛盾する情報が出てきた場合の矛盾検出まで無効化しないよう注意する」に従い、`_check_contradiction()`・矛盾フラグ処理は完全に元のまま。5章のテストで、importance_score=1.0のfactでも矛盾が検出され`is_stale=True`が正しく設定されることを直接確認した。

### Phase 3(論理削除)は変更不要と確認した

`importance × confidence < _FORGET_THRESHOLD`で論理削除、というロジックは**既にPhase 17着手前から実装済み**だった。5章で、低importance×confidenceのfactは論理削除され、高importanceのfactは生き残ることを実際に確認した(コード変更なし、確認のみ)。

---

## 4. Phase B12(将来の検索後圧縮)への申し送り事項

B12(検索後の圧縮)は未実装のため、今回は実装を行っていない(指示書の通り、設計上の配慮のみ)。B12着手時に踏まえてほしい点:

1. **圧縮対象の選定には`importance_score`をそのまま使える。** `search_fact_memory`/`search_fact_memory_trgm`のRPCが今回`importance_score`を返すようになったため(2章)、圧縮ロジックが検索結果を受け取る時点で既にこの情報にアクセスできる。追加のDB呼び出しは不要なはず。
2. **1章の制約(importance_scoreがカテゴリ代理値であること)がB12にも影響する。** 圧縮の優先順位付けをcategoryの粗い区分に頼ることになる点は、B12が「本当に重要な個々の記憶」を狙って残すことを目指すなら不十分かもしれない。B12着手前、またはB14(意思決定パターンのモデリング)と合わせて、`importance_score`をより細かく学習・調整する仕組み(例えば、参照頻度・decision_logからの被参照回数等を反映する)を検討する価値がある。
3. **圧縮対象からの除外基準として、今回の減衰緩和(3章)と同じ`_IMPORTANCE_DECAY_SEVERITY_DAMPENING`的な考え方(閾値ベースでなく連続的な緩和)を踏襲すると一貫性が保てる。** 「importance_score上位N件は圧縮対象外」という単純なカットオフより、連続的な重み付けの方が、これまでのB17・B1の設計方針と整合する。

---

## 5. テスト結果

いずれもモック(実DB未接続)。

### 検索順位への重み付け

```
PASS: near-tie in relevance broken in favor of higher importance_score
PASS: a genuinely large rank gap (1 vs 20) is NOT overridden even by the maximum possible importance boost
PASS: rows missing importance_score entirely default to the neutral 0.5, no crash
PASS: importance also reorders within the high-confidence trigram tier
PASS: importance never lets an RRF-tier result outrank a high-confidence keyword-tier result
```

要件1(同程度の関連度での優先順位反映)・要件3(関連度の正確性を損なわない)・要件4(B1のティア構造を壊さない)を直接検証している。2つ目のケースは、RRFがランクベースであるという1章末尾で触れた特性を踏まえ、rank1とrank20という明確な差が最大重要度ブーストでも覆らないことを確認した。

### 忘却耐性への調整

```
PASS: importance=0.0 -> unchanged; importance=1.0 -> onset doubled, severity halved
PASS: 45日経過時点で importance=0.0 のfactは減衰したが importance=1.0 のfactはまだ減衰しなかった
PASS: importance=1.0でも100日経過後は減衰する(免除ではない、緩和のみ)
PASS: 矛盾検出はimportance_scoreに関わらず機能する(要件3)
PASS: Phase 3(論理削除)が既にimportance-awareであることを確認(コード変更なし)
```

要件2(高importanceは減衰・論理削除の対象になりにくい)・要件3(矛盾検出は損なわれない)を直接検証している。

### 既存機能への非破壊確認(要件4)

- `backend/tests/`(既存8件)全てPASS、`import app.main`成功。
- Phase B1のハイブリッド検索テスト(`_merge_hybrid_results`・`search_relevant_memories`)を再実行し、importance重み付け追加後も全てPASSすることを確認した。
- Phase B4の出所トラッキングテストを再実行し、影響がないことを確認した。
- Phase C-miniの`eval_runner`テストを再実行し、`search_relevant_memories`の呼び出し契約に変更がないことを確認した。

### C-mini参考値

**この環境からは実行できなかった。** `backend/.env`に実クレデンシャルが無く、`sigmaris@192.168.179.11`へのSSHも`Permission denied`のままだった(過去のタスクと同一の制約、再確認済み)。

---

## 6. 気づいた懸念点・次のB機能(B14: 意思決定パターンのモデリング)に影響しそうな発見

1. **`importance_score`が現状カテゴリ代理値でしかない(1章)ことは、B14にも影響しうる。** B14は「decision_logの蓄積から判断傾向を抽出する」ことが目的だが、もし将来importance_scoreをより細かく調整する仕組みを作る場合、decision_logとの関連(どの記憶が実際に決定に使われたか、Phase B4の`memory_refs`)を手がかりにできる可能性がある。B14着手時に、B4で追加した出所トラッキングと組み合わせて検討する価値がある。
2. **`_IMPORTANCE_RANKING_WEIGHT`(0.15)・`_IMPORTANCE_DECAY_ONSET_EXTENSION`(1.0)・`_IMPORTANCE_DECAY_SEVERITY_DAMPENING`(0.5)は全て実データでの検証ができていない暫定値。** Phase A5・B1と同様、実際の検索結果・減衰挙動を見ながらのチューニングが今後必要になる。
3. **RRFがランクベースであるという特性(2章)は、今後B群で検索スコアリングに手を入れる際に毎回考慮する必要がある。** 生の類似度の差がどれだけ大きくても、RRFに変換された時点でその情報の大部分が失われる。将来、より細かい重み付けが必要になった場合、RRFではなく生スコアの加重和(weighted sum)方式への切り替えを検討する余地がある。
4. **importance_scoreを返すRPC変更(2章)は、B1のマイグレーション(`search_fact_memory_trgm`)に続く2回目のRPC再定義。** 今後もRPCの戻り値を拡張する機会が増えることが予想されるため、`DROP FUNCTION`+`CREATE FUNCTION`のパターンをテンプレート的に使えることが分かった(`CREATE OR REPLACE`では列追加ができないという制約は、今後のPhase Bタスクでも繰り返し発生しうる)。

---

## Related Documents

- [phase_b1_report.md](phase_b1_report.md) — ハイブリッド検索マージロジックの基盤
- [phase_b4_report.md](phase_b4_report.md) — 出所トラッキング、B14への申し送りの接続点
- [sigmaris_roadmap.md](sigmaris_roadmap.md) — Phase B群全体の計画、B17→B14の順序
