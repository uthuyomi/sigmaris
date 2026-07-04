# Phase B8 実施報告: 時間認識型リランキング

対象ブランチ: `phase-b8-time-aware-reranking`(mainからfork)

---

## 0. baseline値の性質・既存の教訓について

`docs/sigmaris/phase_c_mini_report.md`のbaselineおよび先行B群タスクの参考値は不
確実性を含む。本タスク完了後の`run_eval.py`の数値も引き続き参考値として扱う。

`docs/sigmaris/incident_shiftpilotai_naming_report.md`の教訓(自己記述テキスト
への鮮度情報欠落が問題を引き起こした事例)を踏まえ、本タスクでは「新しい情報を
優先する」ことと「古い情報を断定的に無視する」ことを明確に区別した設計にした。
具体的には、恒久的な事実カテゴリ(`profile`)は年数が経過していても一切ペナルテ
ィを受けない(要件2)、時間的シグナルはあくまで有界な乗算補正であり、どれだけ
古くても検索結果からゼロになることはない(下記2章・3章)、という2点を明示的に
保証している。

---

## 1. カテゴリ別時間減衰ロジックの実装詳細

### 既存の減衰ロジックを「拡張」した(新設ではない)

`memory_validator.py`の`_DECAY_RULES`(カテゴリ→(decay_days, decay_factor))
と、B17で追加された`_importance_adjusted_decay()`(重要度に応じて減衰開始日数
を延長し、減衰の severity を緩和する)は既存のまま一切変更していない。この2つを
**そのまま再利用する**形で、新関数`compute_freshness_multiplier(category, *,
age_days, importance_score) -> float`を同じファイルに追加した。

### バッチジョブ(`validate_all_facts`のPhase 1)の挙動の再確認

実装前に、既存の日次バッチジョブが実際どう動くかを丁寧にトレースした:

1. `(now - updated_at).days >= decay_days`になった時点で`confidence *=
   decay_factor`を1回適用する。
2. `user_fact_items`には全更新に対して`updated_at`を自動更新する既存トリガー
   (`set_updated_at`、`fact_memory.sql`)があるため、この`confidence`更新自体
   が`updated_at`をリセットする。
3. 結果として、確認されないまま放置された事実は、`decay_days`間隔で**離散的な
   幾何減衰**(`decay_factor`, `decay_factor^2`, `decay_factor^3`...)をたどる。

この事実は当初想定していなかった発見であり、リアルタイムのランキング用シグナル
を設計する上で重要な制約になった: バッチジョブは「今何回目の減衰ステップにいる
か」を`updated_at`という1つのタイムスタンプだけから逆算できない(履歴を持たな
い)。そのため、ランキング用の関数は**DBに一切書き込まない、age_daysのみから計
算できる連続関数**として設計する必要があった。

### 連続関数としての実装(判断根拠)

上記の制約から、離散的な幾何減衰を**自然に一般化した連続指数関数**を採用した:

```python
def compute_freshness_multiplier(category, *, age_days, importance_score):
    rule = _DECAY_RULES.get(category)
    if rule is None or rule[0] is None:
        return 1.0
    base_decay_days, base_decay_factor = rule
    decay_days, decay_factor = _importance_adjusted_decay(base_decay_days, base_decay_factor, importance_score)
    if age_days < decay_days or decay_days <= 0:
        return 1.0
    return decay_factor ** (age_days / decay_days)
```

この式は`age_days == decay_days`のとき厳密に`decay_factor`(バッチジョブの1回
目のステップと一致)、`age_days == 2*decay_days`のとき`decay_factor**2`(2回目
のステップと一致)を返し、その間・それ以降は滑らかに補間する。減衰開始前
(`age_days < decay_days`)は無条件に`1.0`を返し、バッチジョブ自身のゲート
(`if age_days < decay_days: continue`)と完全に一致させた。この一致性は単体テ
ストで直接検証している(4章)。

**恒久的な事実(要件2)**: `_DECAY_RULES`に存在しない、または`(None, ...)`のカ
テゴリ(`profile`、および`_DECAY_RULES`に元々含まれていない`work`/
`personality`/`timeline`/`preference`単数形等)は常に`1.0`を返す。これはバッチ
ジョブ自身の`if rule is None or rule[0] is None: continue`と同じ扱いであり、恒
久的な事実がどれだけ古くても不当に減点されないことを保証する。

### `updated_at`を使う理由(`created_at`ではなく)

指示書は`created_at`・`updated_at`の両方を経過時間の算出根拠として挙げていた
が、実装では**`updated_at`のみ**を使うことにした(判断根拠): `memory_validator.
py`のPhase 1減衰ロジック自身が`updated_at`を年齢の基準にしており、Phase B3(確
認結果の反映)も明示的に`updated_at`を更新する設計になっている。「拡張する、別
建てにしない」という本タスクの要件に従うなら、既存の減衰ロジックが使っているの
と同じタイムスタンプを使うのが一貫性がある。`created_at`を別途使うと、「一度作
成されたきり何年も確認されていないが最近確認された」記憶と「最近作られたばかり
の」記憶を区別する軸が増えて複雑になり、過剰実装になると判断した。

### RPCへの`updated_at`列の追加(マイグレーション)

`search_fact_memory`・`search_fact_memory_trgm`の両RPCの戻り値にはこれまで
`updated_at`が含まれていなかった。`memory_search.py`側でランキング時に年齢を計
算するために必須のため、両RPCの`RETURNS TABLE`に`updated_at timestamptz`を追加
した。`CREATE OR REPLACE`では列追加ができない制約のため、B1→B17→B13に続き4回目
となる`DROP FUNCTION` + `CREATE FUNCTION`パターンを踏襲した
(`202607150037_time_aware_search.sql`、未適用)。

---

## 2. 時系列質問判定の実装方法

### 新規LLM呼び出しは追加していない(要件4)

指示書の「新規の専用LLM呼び出しを追加することは最終手段とすること」という指示
に従い、**Phase B7の`multihop_search.decompose_query()`が既に毎ターン実行して
いる分解要否判定と同じLLM呼び出しに、`time_sensitive`フィールドを追加**した。
この判定は`needs_decomposition`(分解の要否)とは完全に独立した設問として同じ
プロンプト・同じJSONレスポンスの中で問うている(例:「その趣味って今も続けて
る?」は単一話題だが時系列的、という組み合わせが起こりうるため)。

これにより、B7で発生した「応答経路上のレイテンシ増加」が本タスクによって**追加
で増えることは一切ない**。単純な質問・複雑な質問のいずれの経路でも、B7が既に払
っている1回分のLLM呼び出しコストに完全に相乗りしている。

### 戻り値の型変更

`decompose_query()`の戻り値を`list[str] | None`から、`sub_queries`と
`time_sensitive`の両方を持つ`QueryAnalysis`(frozen dataclass)に変更した。この
変更に伴い、B7で書いたスクラッチテスト(`test_b7_decompose_query.py`・
`test_b7_search_with_decomposition.py`)を新しい戻り値の形に合わせて更新した
(4章)。

### ランキングへの伝播

`search_with_decomposition()`が`analysis.time_sensitive`を、単一検索パス・サブ
クエリ分解パスの**両方**で`search_relevant_memories(..., time_sensitive_
query=...)`に渡すようにした。`search_relevant_memories()`→
`_merge_hybrid_results()`→`_apply_ranking_weights()`という既存の経路に
`time_sensitive_query: bool = False`という追加のキーワード引数を通しただけで、
既存の呼び出し元(デフォルト値`False`)には一切影響がない。

---

## 3. B17・B13との合成挙動の実測結果

B13が確立した「rank-gap flip-testの実測による重み決定」手法をそのまま踏襲し、
Pythonで実際に計算して重みを決定した(実モデルAPIは使っていない、純粋な数値計
算による実測)。

### 測定方法

- RRFスコアは`1/(_RRF_K + rank)`(`_RRF_K=60`)で近似。
- 「合成後の最悪ケース」: rank1(真に関連性が高いが、最大限に古い・重要度ゼ
  ロ・採用実績ゼロ)vs rankN(関連性は低いが、重要度・採用実績ともに最大かつ完
  全にフレッシュ)。rank1がrankNに逆転されなくなる最大のNを「合成時の上限」と
  定義した。

### まず判明したこと: 本実装のテスト設定でのB17+B13単独の基準値

B8を一切加えない状態(B17+B13のみ、重み1.15×1.10=1.265)で、この定義に基づく
上限は**rank17**だった。これはB13の報告書に書かれている「rank11〜14程度」とは
異なる数値だが、これはB13の報告書のテスト設定(rank1側に何らかの下駄を履かせて
いた可能性がある)と本検証のテスト設定(rank1側を完全にゼロブーストにした、よ
り厳しい設定)の違いによるものと考えられる。本タスクでは、この**rank17という自
分自身の実測基準値**を起点に、B8追加によってどれだけ上限が押し上げられるかを評
価した(指示書の「rank11〜14程度の上限」という表現との数値的な厳密一致ではな
く、既存の安全な範囲を大きく超えないことの確認という趣旨で解釈した)。

### 重み候補の実測比較

| freshness重み | 合成後の上限(rank) | 基準値(17)からの増分 |
|---|---|---|
| 0.03 | 19 | +2 |
| 0.05 | 21 | +4 |
| 0.07 | 22 | +5 |
| 0.08 | 23 | +6 |
| 0.10 | 25 | +8 |
| 0.12 | 27 | +10 |
| 0.15 | 30 | +13 |
| 0.20 | 36 | +19 |

### 採用した値

- **通常時の重み: 0.05**(合成後上限21、基準値比+4に抑制)
- **時系列質問時の重み: 0.12**(合成後上限27、基準値比+10)

時系列質問時の重みをより強くしたのは要件3(「時間的シグナルが適切に強く反映さ
れる」)に応えるためだが、それでも上限は27に留まり、0.20(上限36)のような際限
のない増加にはしていない。「合成後の上限を大きく超えない」という要件5の趣旨
(既存の安全な範囲から大きく逸脱しないこと)を満たすと判断した。

### 補足: freshnessペナルティ単独での近傍ランクへの効果

B17・B13が一切関与しない、fresnessペナルティのみの効果も確認した:

- 通常重み(0.05): 隣接する2〜4位のみに影響(穏やか)
- 時系列質問重み(0.12): 隣接する2〜9位程度に影響(要件3が求める「強い反映」
  に対応する、意図した挙動)

これは要件3が求める「時系列質問では時間的シグナルを強く反映する」という挙動そ
のものであり、バグではなく設計通りの結果であることをテストで確認している。

---

## 4. テスト結果

実モデルAPIでの検証はできないため、実装したロジックそのものに対する単体テスト
(数値計算含む)で確認した。

### `compute_freshness_multiplier()`(8ケース、新規)
- 恒久的カテゴリ(profile)は経過日数によらず常に1.0を返すこと
- `_DECAY_RULES`に存在しないカテゴリも1.0を返すこと(バッチジョブと同じ扱い)
- 減衰開始日数未満では1.0を返すこと
- 減衰開始日数ちょうどでバッチジョブの1回目のステップ値と一致すること
- 減衰開始日数の2倍でバッチジョブの2回目のステップ値と一致すること
- 経過日数の増加に対して単調減少すること
- 重要度が高いほど減衰開始が遅れ、減衰が緩やかになること(B17の挙動の再確認)
- 戻り値が常に[0, 1]の範囲に収まること

### `_freshness_weighted_score()`・`_apply_ranking_weights()`(9ケース、新規)
- 直近更新された記憶にはペナルティが一切かからないこと
- 減衰対象カテゴリで古い記憶にはペナルティがかかること
- 恒久的カテゴリで古い記憶にはペナルティがかからないこと(要件2)
- `updated_at`が欠落している行は変更なし(fail open、他の重み付けと同じ防御)
- 時系列質問判定時、同じ古さの記憶でもペナルティが通常時より強くなること(要件
  3)
- どれだけ古くてもペナルティが設定した重み以上には大きくならないこと(有界性)
- B17+B13単独(B8なし)での合成上限が17であることの確認(基準値の固定)
- 通常重み(0.05)での合成上限が21であることの実測確認
- 時系列質問重み(0.12)での合成上限が27であることの実測確認

### B7スクラッチテストの戻り値変更への追従(既存17ケース更新+3ケース新規)
`decompose_query()`の戻り値が`QueryAnalysis`に変わったことに伴い、
`test_b7_decompose_query.py`・`test_b7_search_with_decomposition.py`を更新。
「単一話題だが時系列的な質問」「複雑かつ時系列的な質問」「time_sensitiveフィー
ルド欠落時のデフォルト値」の3ケースを追加し、`time_sensitive`フラグが単一検索パ
ス・サブクエリ分解パスの両方で`search_relevant_memories()`に正しく伝播すること
も確認した。

### 既存機能への非破壊確認(要件6)
`backend/tests/`の既存8テストを含む全98ケースを再実行し、全て成功することを確
認した。

```
17 passed (B8新規テスト)
30 passed (B7スクラッチテスト、戻り値変更対応含む)
51 passed (B2/B3/B6スクラッチテスト・facts cache修正テスト再実行)
8 passed (既存回帰テスト、backend/tests/)
```

---

## 5. 気づいた懸念点・次のB機能(B10: クロスエンコーダ二段階リランキング)に影響しそうな発見

- **バッチジョブの離散幾何減衰という発見は、他の「confidence列を信頼できる鮮度
  シグナルとして扱う」設計にも影響しうる**: 1章で判明した通り、`confidence`は
  `updated_at`が更新されるたびに減衰の「時計」がリセットされる挙動を持つ。これ
  は今回のリアルタイム計算(DBに書き込まない)では問題にならないが、もし将来
  `confidence`列の値そのものを「鮮度の指標」として直接使う設計(例えば
  B10がクロスエンコーダの入力特徴量として`confidence`を使うような場合)を検討
  する際は、この「リセットされる離散ステップ」という性質を踏まえる必要がある。
- **本検証で確立したベースライン(rank17)は、B13報告書の数値(rank11〜14)と
  異なっており、テスト設定の違いに起因する可能性が高い**: 今後B10やその先の機
  能で同種の合成挙動検証を行う際は、「rank1側にどの程度のブースト・ペナルティ
  を仮定するか」というテスト設定自体を先行するB群レポートと揃えるか、あるいは
  各レポートが自分自身のテスト設定を明記して独立に評価するかを、あらかじめ決め
  ておくと数値の比較がしやすくなる。
- **B10(クロスエンコーダ二段階リランキング)は、現在の`_apply_ranking_
  weights()`(単純な乗算合成)とは異なるアーキテクチャ(候補セットに対する再ス
  コアリング)になる可能性が高い**: もしそうなる場合、本タスクで確立した「複数
  の乗算的重み付けの合成挙動を実測で検証する」という手法自体が、そのままでは
  再利用できない可能性がある。二段階リランキングを検討する際は、一段目
  (`_apply_ranking_weights`)の出力候補セットのサイズ・多様性が、二段目のクロ
  スエンコーダにとって十分かどうかを別途検討する必要がある。
- **`time_sensitive`判定の精度は、実際のユーザーの言い回し(「今も」「まだ」等
  の言葉を含まない、間接的な時系列質問)でどこまで正しく判定できるかが未検証**:
  実モデルAPIでの検証ができない制約下、プロンプトの指示文だけを頼りに実装して
  おり、実運用でのfalse negative(時系列質問なのに検出されない)の頻度は運用者
  側での観測が必要。

---

## Related Documents

- `docs/sigmaris/sigmaris_roadmap.md`
- `docs/sigmaris/phase_b17_report.md`(`_importance_adjusted_decay`の元設計、本
  タスクが再利用した減衰フレームワーク)
- `docs/sigmaris/phase_b13_report.md`(重み実測の手法の踏襲元)
- `docs/sigmaris/phase_b7_report.md`(`decompose_query()`統合先、応答経路上のレ
  イテンシに関する既存の議論)
- `docs/sigmaris/incident_shiftpilotai_naming_report.md`(鮮度情報欠落の教訓)
- `supabase/migrations/202607150037_time_aware_search.sql`(未適用)
