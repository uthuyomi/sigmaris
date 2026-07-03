# Phase B13 実施報告: 暗黙フィードバックによる検索ランキング個人最適化

**目的:** `sigmaris_decision_log.memory_refs`(海星さんの決定が実際に参照した記憶)を暗黙の採用シグナルとして検索ランキングにフィードバックする。
**作業ブランチ:** `phase-b13-implicit-feedback`(Phase A0〜A5・C-mini・JWT永続化・LLMRouter修正・FREE LIMIT削除・B1・B4・B17・B14がマージ済みの`main`から新規作成)
**範囲:** 指示書の制約通り、`memory_refs`以外の新しいUI・フィードバック収集機構は新設していない。B2等、他のB群機能には着手していない。

---

## 0. baseline値の性質について(B1・B4・B14・B17と同様)

指示書の通り、`run_eval.py`の参考値取得を試みたが、この環境からは実行できなかった(`backend/.env`に実クレデンシャル無し、`sigmaris@192.168.179.11`へのSSHも接続タイムアウト — 過去のタスクと同一の制約)。効果確認は5章のテスト(採用回数の集計・ランキングへの反映)を主とした。

---

## 1. `memory_refs`の実際の形式と、採用回数集計ロジックの実装詳細

### 形式の確認

`sigmaris_decision_log.memory_refs`は、`decision_log.py::detect_and_record_decision()`(Phase A3)が`fact_lookup`(`"category/key"` → `user_fact_items.id`)経由で解決した**`user_fact_items.id`のjsonb配列**である(`log_decision()`の`payload["memory_refs"] = memory_refs or []`)。Phase B4で追加された`thread_id`/`invocation_id`と組み合わせることで、「どの記憶が、どの会話のどのターンで下された決定に使われたか」まで遡れることも確認した。

### 採用回数集計: `decision_log.py::recompute_adoption_counts()`(新規)

**週次バッチ**(既存の`preference_pattern_extract`(Sunday 4:45、B14)の直後、4:50に配置)として実装した。判断根拠:

- B14と全く同じ理由(決定は本質的に低頻度、`sigmaris_decision_log`書き込みのたびに全件再集計するのは無駄が大きい)。
- 同じ`sigmaris_decision_log`を読む処理(`decision_analyze`・`preference_pattern_extract`)と隣接した時間帯に配置することで、運用上の一貫性を保った。

### 集計ロジック

```python
counts: dict[str, int] = {}
for decision in decisions:
    refs = decision.get("memory_refs")
    if not isinstance(refs, list):
        continue
    for fact_id in set(refs):  # 同一決定内の重複参照は1回として数える
        counts[fact_id] = counts.get(fact_id, 0) + 1
```

**「同一決定内で同じ記憶が複数回参照されても1回としてカウントする」設計にした。** 採用シグナルの意味は「何個の**独立した決定**がこの記憶に依拠したか」であり、1つの決定記録内での言及回数を積み増す設計にすると、たまたま同じ決定文の中で同じfactに複数回触れただけのケースで不当に強いシグナルになってしまうため。5章のテストで、`fact-A`が3決定にまたがって参照され(うち1決定では2回言及)、正しく3(4ではなく)としてカウントされることを確認した。

### 走査範囲: 直近500件の決定(全件走査ではない)

`update_fact_embeddings()`のような完全なページネーションループではなく、`get_recent_decisions(limit=500)`による単発の大きめのページ取得に留めた。判断根拠: 指示書自身が「過大な機能を作らないこと」と釘を刺しており、現状の決定件数はごく少数と見込まれる(Phase C-mini・B14で繰り返し確認されている制約)。500件は当面十分に大きい余裕を持たせた値であり、本格的なページネーションを今実装するのは時期尚早と判断した。決定件数が将来大きく増えた場合は、この上限の見直しが必要になる(6章で言及)。

### 書き込み方式: service-roleヘッダーで直接`user_fact_items`へ

`decision_log.py`の既存パターン(`_svc_headers()`、service-roleでの直接REST呼び出し)をそのまま流用し、`user_fact_items`へservice-role権限でPATCHする形にした。この関数はユーザーセッション(JWT)を持たないバッチジョブであり、シグマリス自身が導き出した理解を書き戻す処理という性質上、`user_fact_items`の通常のユーザーRLS経路(JWT必須)を経由する必要はないと判断した。

**採用シグナルが1件も無い場合は、`user_fact_items`への書き込みを一切行わない**(5章のテストで確認)。既存の`adoption_count`のデフォルト値(0)がそのまま維持される。

---

## 2. ランキングへの重み付けの実装詳細(係数・検証結果)

### 実装: B17の重み付け機構と合成する形で実装した

```python
_MIN_ADOPTION_COUNT_FOR_BOOST = 2   # B14の_MIN_SUPPORTING_DECISIONSと同じ値、同じ理由で採用
_ADOPTION_COUNT_SATURATION = 5      # これ以上は追加ブーストなし(頭打ち)
_ADOPTION_RANKING_WEIGHT = 0.10     # 4章の実測で決定

def _adoption_weighted_score(base_score, row):
    adoption_count = int(row.get("adoption_count") or 0)
    if adoption_count < _MIN_ADOPTION_COUNT_FOR_BOOST:
        return base_score  # 閾値未満は完全に無加点
    normalized = min(adoption_count, _ADOPTION_COUNT_SATURATION) / _ADOPTION_COUNT_SATURATION
    return base_score * (1.0 + normalized * _ADOPTION_RANKING_WEIGHT)

def _apply_ranking_weights(base_score, row):
    score = _importance_weighted_score(base_score, row)  # B17
    score = _adoption_weighted_score(score, row)          # B13
    return score
```

`_merge_hybrid_results()`内の2箇所(近接完全一致ティア・RRFティアそれぞれの並べ替えキー)を、B17時点の`_importance_weighted_score`直呼びから`_apply_ranking_weights`(B17+B13の合成)に置き換えた。**B17が実装したティア構造(近接完全一致ティアを跨がない)はそのまま維持されている**(乗算での合成のため、ティア境界を越える動きは発生しない)。

### 閾値`_MIN_ADOPTION_COUNT_FOR_BOOST=2`の根拠

B14の`_MIN_SUPPORTING_DECISIONS`と同じ値・同じ理由(1件だけの採用実績は偶然の可能性を排除できないため信号として弱すぎる、2件以上の独立した決定が同じ記憶に依拠していれば実質的な裏付けとみなせる)を踏襲した。B群全体で「根拠が薄い場合の最低ライン」の考え方を統一する目的もある。

### 重み係数の実測(B17と同じ手法)

B17と同じ「rank1(最不利条件)vs rankN(最有利条件)」がどこまで離れると逆転しなくなるかを実測した。

**adoption重みのみ単独(importanceは中立0.5)の場合:**

| rank差(N) | w=0.05 | w=0.10 | w=0.15 |
|---|---|---|---|
| 5〜7 | しない | する | する |
| 8〜10 | しない | **しない** | する |
| 11以上 | しない | しない | しない |

`w=0.05`は単独ではrank差5すら逆転させられず、近接タイを崩すという当初の目的に対して弱すぎると判断した。`w=0.15`はB17のimportance重みと同じ大きさになり、下記の合成時の上限が大きくなりすぎる懸念があった。

**B17(importance=0.15、最大)とB13(adoption、各候補値)を両方最大同時発動させた最悪ケース:**

| rank差(N) | aw=0.05 | aw=0.10 | aw=0.15 |
|---|---|---|---|
| 5〜11 | する | する | する |
| 15 | しない | する | する |
| 19〜20 | しない | しない | する |

**`0.10`を採用した根拠:** 単独では rank差7〜8程度までの近接タイを崩せる実用的な強さを持ちながら(要件2に対応)、B17との合成最悪ケースでもrank差15で頭打ちになり、rank差20(明らかに無関係と言えるレベルの差)までは逆転しない(要件を上回る安全マージン)。`0.15`を採用した場合、合成最悪ケースがrank差19まで逆転可能になり、B17が慎重に守ろうとした「大きな関連度差は覆さない」という原則に対するマージンが薄くなりすぎると判断した。

---

## 3. データ不足時の閾値設定とその根拠

2章で述べた`_MIN_ADOPTION_COUNT_FOR_BOOST=2`に加え、**「不採用」を示すネガティブシグナルは一切実装していない**(要件4、方針章の制約)。検索候補に含まれたが後続の決定の`memory_refs`に現れなかった記憶は、`adoption_count`が単に0のまま(=閾値未満=無加点)であり、これは「不採用と判定された」のではなく「まだ明確な採用シグナルが無い」という状態に過ぎない。5章のテストで、`adoption_count=0`の記憶が、B13適用前と全く同じスコアで扱われることを直接確認した(ペナルティが一切発生しないことの確認)。

---

## 4. テスト結果

いずれもモック(実DB未接続)。

### 採用回数の集計

```
PASS: fact-A referenced across 3 decisions (once twice within one) counts as 3, not 4
PASS: no memory_refs anywhere -> zero writes to user_fact_items
```

要件1(正しい集計)を直接検証している。

### ランキングへの反映

```
PASS: near-tie in relevance broken in favor of higher adoption_count
PASS: adoption_count=1 (below minimum 2) gets no boost at all, pure relevance still wins
PASS: adoption_count=0 (or entirely missing, pre-migration) never penalizes a result
PASS: adoption_count beyond the saturation point (5) doesn't crash and both entries are ranked
PASS: combined B17+B13 boosts, both maxed simultaneously, still do not override a genuinely
      large (rank 1 vs rank 20) relevance gap
```

要件2(採用回数の多い記憶が優先される)・要件3(閾値未満は過大優先されない)・要件4(不採用の断定的扱いをしていない)・要件5(B17との合成でも既存原則を破らない)を直接検証している。

### 既存機能への非破壊確認(要件5)

- `backend/tests/`(既存8件)全てPASS、`import app.main`成功。
- Phase B1・B4・B14・B17・Phase C-miniの既存テストを全て再実行し、全てPASSすることを確認した(`_merge_hybrid_results`の並べ替えキー変更が既存の挙動に影響していないことを直接確認)。

---

## 5. 気づいた懸念点・次のB機能(B2: エピソード記憶/意味記憶の分離)に影響しそうな発見

1. **`memory_refs`はPhase A3稼働以降にしか蓄積されておらず、かつLLMRouterのバグ(Phase C-mini発見)の影響を受けていた可能性がある。** B14の報告と同様、現時点でどれだけの採用シグナルが実際に蓄積されているかはこの環境から確認できない。データが少ない間は本機能もほぼ無風で動作する(2章の閾値ガードにより)。
2. **`get_recent_decisions(limit=500)`という固定上限(1章)は、決定件数が今後大きく増えた場合に見直しが必要になる。** 現時点では過大な実装を避ける判断を優先したが、将来的にはページネーションを検討する余地がある。
3. **B2(エピソード記憶/意味記憶の分離)との関係**: `sigmaris_experience`(エピソード記憶)には現状`memory_refs`に相当する参照機構が無い(Phase B4の報告で「`sigmaris_experience`は`related_fact_ids`を持つが実際の書き込み元が乏しい」ことに触れた)。B2でエピソード記憶と意味記憶(`user_fact_items`)の役割を整理する際、本機能(採用シグナルによる検索ランキング)が`sigmaris_experience`側にも拡張可能か検討する価値がある。
4. **明示的な採用/不採用シグナル(UI評価ボタン等)の追加価値について、所見を述べる。** 本タスクで実装した`memory_refs`ベースの暗黙シグナルは、**「決定に至った」という比較的まれなイベントにしか紐づかない**ため、シグナルの発生頻度自体がdecision_logの蓄積ペースに強く依存する。もし将来、応答ごとに軽量な評価(例えば「参考になった」ボタン)を追加できれば、はるかに高頻度なフィードバックが得られ、`adoption_count`のような遅行指標だけに頼らない、より即時性の高い個人最適化が可能になると考えられる。ただし本タスクの指示書が明確に禁じている通り、これは新しいUI・収集機構の新設を伴うため、今回は実装せず、次のB群タスク検討時の材料として申し送る。

---

## Related Documents

- [phase_b4_report.md](phase_b4_report.md) — `memory_refs`・出所トラッキングの基盤
- [phase_b14_report.md](phase_b14_report.md) — 同じ`sigmaris_decision_log`を情報源とする週次バッチの先例、`_MIN_SUPPORTING_DECISIONS`の閾値設計
- [phase_b17_report.md](phase_b17_report.md) — 重み付け機構・実測による係数決定手法の先例
- [sigmaris_roadmap.md](sigmaris_roadmap.md) — Phase B群全体の計画、B13→B2の順序
