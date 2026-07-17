# Phase D-1 実施報告: 根拠収集(改良提案エンジンの、材料集約層)

**作業ブランチ:** `phase-d1-evidence-aggregation`(mainから新規作成)
**範囲:** Phase R(RC指標)・Phase G(Grounding継続測定)・Phase S-2(Mastery Driveの言語化)・`bug_inventory.md`(過去のインシデント記録)という既存4資産を読み取り、カテゴリ分類・簡単な優先順位付けを行った上で構造化された根拠として出力する層。**改良案の生成(仮説生成)は次タスク(D-2)のスコープであり、本タスクでは一切行っていない。**

---

## 0. 前提として確認したこと

着手前に指示書が指定した3ファイルを確認した。

- `docs/sigmaris/phase_s_report.md`(S-2、15章): Mastery Driveの「言語化」が、RC-1/RC-2/RC-5の生値から`goal_proposal.py::_act_on_mastery()`が決定的なテンプレート文を組み立て、`sigmaris_experience`へ`category="proposal"`・`experience_type="unresolved"`として記録される、という実装内容を確認した。
- `docs/sigmaris/phase_r_report.md`(RC指標、特に15章): RC-5(Cycle Break Detection)が既に「直近実行群の平均からの単純な閾値比較」という仕組みを実装済みであることを確認した。この仕組みをそのまま再利用できるかを2章で検討した。
- `docs/sigmaris/bug_inventory.md`(特に4章「問題一覧表」): 過去のインシデントが、`| # | 概要 | 出典 | 深刻度 | 推定根本原因 | 優先度目安 |`という定型的なMarkdownテーブルに既にまとまっていることを確認した。

---

## 1. 根拠収集の実装詳細(各データソースからの読み取り方法)

新設ファイル: `backend/app/services/evidence_aggregation.py`(純粋関数、I/Oなし)・`evidence_aggregation_runner.py`(I/O)・`evidence_aggregation_store.py`(永続化)。`cycle_health_metrics.py`/`cycle_health_runner.py`/`cycle_health_runs_store.py`(Phase R)、`grounding_health_metrics.py`/`grounding_health_runner.py`/`grounding_health_runs_store.py`(Phase G-5)と同じ3層分離をそのまま踏襲した。

### 1.1 Phase R(RC指標)

`cycle_health_runs_store.get_recent_cycle_health_runs(limit=N)`をそのまま呼び出す(新しい関数は追加していない)。`sigmaris_cycle_health_runs`の実列(`rc1_eligible_completion_rate`・`rc2_score`・`rc3_score`・`rc4_score`)を、2章の悪化判定にそのまま渡す。

### 1.2 Phase G(Grounding指標)

`grounding_health_runs_store.get_recent_grounding_health_runs(limit=N)`をそのまま呼び出す。`citation_precision`・`contradiction_rate`を2章の悪化判定に渡す(`search_trigger_rate`は意図的に対象外——2.3節参照)。

### 1.3 Mastery Driveの言語化内容

`experience_layer.get_recent_experiences(limit=N, experience_type="unresolved", category="proposal")`をそのまま呼び出す。この関数は既にPhase R-2時点で実装済みの汎用フィルタ機構であり、新しい引数・新しいクエリロジックは一切追加していない。S-2が`_act_on_mastery()`で組み立てた`title`/`description`/`context`(rc1/rc2/rc5の生値)をそのまま根拠として取り込む。

### 1.4 `bug_inventory.md`(過去のインシデント記録)

依頼書は「ドキュメントのみの場合は、本タスクでは無理に構造化せず、参照方法を報告するに留めてよい」と明示的に許容していたが、`bug_inventory.md`の4章「問題一覧表」が既に十分定型的なMarkdownテーブルであることを確認できたため、**簡易的なテキストベースの構造化を試みた**(判断根拠は2.4節参照)。

`orchestrator/persona_loader.py::load_persona()`が確立していた「`docs/`配下の実運用ドキュメントを、複数の候補パスを順に試しながらファイルシステムから直接読む」という前例をそのまま踏襲し、`evidence_aggregation_runner.py::_find_bug_inventory_path()`で同じパターンを実装した(`Path(__file__).resolve().parents[3] / "docs" / "sigmaris" / "bug_inventory.md"`、および`/app/docs/sigmaris/bug_inventory.md`のDocker想定フォールバック)。**persona_loader.pyと異なりmtimeキャッシュは実装していない** — 本タスクの利用シーンは手動実行のオフラインCLIのみであり、persona_loader.pyのような会話ターンごとの高頻度呼び出しではないため、キャッシュの必要性が薄いと判断した(判断根拠)。

ファイルが見つからない場合は例外を投げず、警告ログを出した上で「繰り返し発生する問題」カテゴリを0件のまま続行する(fail-openの一貫した方針)。

---

## 2. カテゴリ分類・優先順位付けのロジック

### 2.1 測定指標の悪化(`metric_degradation`)

**新しい悪化検知ロジックを新設せず、RC-5(`cycle_health_metrics.py`)が既に実装していた閾値比較を再利用した。** RC-5専用の内部関数だった`_check_metric_drop()`を、名前の`_`を外した`check_metric_drop()`として公開関数へ格上げした(**実装・挙動は一切変更していない**、リネームとdocstring追加のみ)。呼び出し元は`detect_cycle_break()`内の1箇所のみで、影響範囲は最小限であることを確認済み(`grep`で確認、既存の`RunCycleHealthRc345IntegrationTests`等が変更なしで通ることも4章で確認)。

対象にした指標と、それぞれの母数・閾値は以下の通り。

| 指標 | 出典 | 方向 | 母数(最低履歴数) | 落ち込み閾値 |
|---|---|---|---|---|
| RC-1(`rc1_eligible_completion_rate`) | Phase R | 高いほど良い | 3 | 20ポイント |
| RC-2(`rc2_score`) | Phase R | 高いほど良い | 3 | 20ポイント |
| RC-3(`rc3_score`) | Phase R | 高いほど良い | 3 | 20ポイント |
| RC-4(`rc4_score`) | Phase R | 高いほど良い | 3 | 20ポイント |
| Citation Precision | Phase G | 高いほど良い | 3 | 20ポイント |
| Contradiction Rate | Phase G | **低いほど良い**(`1 - x`で反転してから判定) | 3 | 20ポイント |

**閾値をRC-5と全く同じ値(最低履歴数3・落ち込み20ポイント)に揃えた判断根拠**: RC-5がこの値を導入した時点で既に「未検証の暫定値」と明記されている(`phase_r_report.md` 15.3節)。指標ごとに別々の未検証の値を新設するより、既存の1つの暫定値に揃えておく方が、将来まとめて実データを見て調整する際に扱いやすいと判断した。

**Search Trigger Rateは意図的に対象外とした。** Phase G-5の報告書自身が「低い/高いは必ずしも良し悪しではない」と明記しており、方向性が不明な指標を機械的に「悪化」と判定することは、G-5が確立した「短絡的な良し悪し判定を避ける」という設計哲学に反すると判断した——これは要件4(既存機能への悪影響回避)を、指標解釈の一貫性という観点にも拡大解釈して適用したものである。

**優先順位付けの基準(依頼書の例示をそのまま採用)**: 依頼書が例示した「複数の指標に、同時に悪影響を与えているものを、優先する」を、そのまま`priority_score`の核にした——**同一実行内で同時に閾値を超えて悪化した指標の数**を`priority_score`とする(RC系とGrounding系は別々に数える、同時に集計している実行が別テーブルであるため)。2つ以上同時に悪化した場合は`severity="high"`、1つのみなら`severity="medium"`とする、というシンプルな2段階のルールにとどめた(依頼書「過度に複雑なスコアリングは避け、シンプルな基準とする」に対応)。

### 2.2 繰り返し発生する問題(`recurring_problem`、`bug_inventory.md`由来)

**「同種の問題が複数回記録されているもの」の判定方法**: `bug_inventory.md`の問題一覧表の「出典」列には、その問題が言及されている報告書ファイル名(例: `phase_b9_report.md`)が記載されている。1行の「出典」欄に**異なる複数の`.md`ファイル名が登場する場合**、それは「同種の問題が複数の独立した報告書で繰り返し指摘されている」ことを意味すると判断した。

実例: `bug_inventory.md` #6「B群6機能が同一パイプラインを重複実装」は`phase_b9_report.md`・`phase_b16_report.md`・`phase_b_summary.md`の3つに渡って言及されており、これは実際に3回の異なる報告書で繰り返し指摘されている問題である。一方「本タスク2.1節」のような自己参照(`bug_inventory.md`自身の章番号)は`.md`ファイル名を含まないため、この判定には数えられない——「今回新規発見した」問題と「以前から繰り返し記録されている」問題を、`.md`ファイル名の出現パターンだけで区別する、意味解析を伴わないシンプルな基準にした。

解決済み(概要・深刻度欄に「修正済み」「解決済み」「解消済み」「対応不要」「対応済み」のいずれかの記載がある)行は除外する——依頼書「実際の改良案の生成は次タスク」の範囲外である、既に対応済みの事項をD-2に渡す意味がないと判断したため。

優先順位付けは`深刻度の重み(高=3/中=2/低=1) + 複数回記録ボーナス(常に+1、このカテゴリに残っている時点で条件を満たしている)`というシンプルな加算のみ。

### 2.3 Mastery Driveの言語化内容(`mastery_proposal`)

新しい言語化・新しい判定ロジックは一切追加せず、S-2が既に`sigmaris_experience.context`へ保存済みの生値(`rc1_eligible_completion_rate`・`rc2_score`・`rc5_status`)を、そのまま取り込むだけの層とした。

優先順位付けのために、`goal_proposal.py::_format_mastery_lines()`が実際に使っている閾値(RC-1/RC-2 < 0.8、RC-5 == `"break_detected"`)を再利用し、「何個の悪化シグナルが、その改善提案の根拠になっていたか」を`priority_score`とした。RC-5が`break_detected`の場合は無条件で`severity="high"`とする(RC-5自体が「循環の急激な悪化」という緊急性の高い信号のため)。

**重要な既知の結合として明記する**: この閾値(0.8・`break_detected`)は`goal_proposal.py`側の定数を、値としてそのままコピーしたものであり、import して共有する形にはしていない。判断根拠は、`goal_proposal.py`側の関数が`DriveState`オブジェクトを引数に取るのに対し、ここでは`sigmaris_experience.context`(既に保存済みのflat dict)を扱っており型が異なるため素直に共有できないこと、また`evidence_aggregation.py`(根拠収集)から`goal_proposal.py`(行動実行)への依存を新設するのは責務の向きとして逆転していると判断したためである。**`goal_proposal.py`側の閾値が将来変更された場合、この優先順位付けのスコアが実際の提案内容とわずかにずれる可能性がある**——6章の懸念点として記録する。

### 2.4 全体の優先順位付け(`aggregate_evidence()`)

3カテゴリから集めた`EvidenceItem`を1つのリストにまとめ、`priority_score`の降順でソートするのみ。カテゴリ間で`priority_score`のスケールが完全には揃っていない(measurement系は「同時悪化した指標数」、bug_inventory系は「深刻度+1」、mastery系は「悪化シグナル数」)ことは認識した上で、**あえて統一していない**——依頼書「過度に複雑なスコアリングは避ける」という制約のもとでは、無理に単一の重み付け式に統合するより、各カテゴリの`priority_score`の由来を`details`にそのまま残し、D-2側が必要に応じてカテゴリごとに扱いを変えられる形の方が誠実だと判断した(判断根拠、6章にも申し送り)。

---

## 3. 出力形式の設計

`EvidenceBundle`(`items: list[EvidenceItem]`、`sources_checked: dict`)という構造で、各`EvidenceItem`は以下のフィールドを持つ。

```python
@dataclass
class EvidenceItem:
    category: str        # "metric_degradation" | "recurring_problem" | "mastery_proposal"
    source_system: str    # "phase_r" | "phase_g" | "phase_s_mastery" | "bug_inventory"
    title: str
    description: str
    severity: str | None  # "high" | "medium" | "low" | None
    priority_score: int
    details: dict[str, Any]  # 元データへのトレーサビリティ(experience_id等)を含む
```

**永続化テーブルを新設した判断根拠(依頼書「JSON、または専用のテーブル」の後者を採用)**: D-1自身の出力(集約済みの根拠一覧)は、Phase R/Gのような「既存データから指標を再計算する」性質ではなく「既存データを読み集約した結果そのもの」であり、新しいテレメトリの収集ではない。次タスク(D-2)がこの出力をそのまま読み取り口として使えるよう、Phase R/Gと同じ「1回の実行=1行」の永続化テーブル(`sigmaris_evidence_bundles`)として設計した。

`supabase/migrations/202607250052_evidence_bundles.sql`(新規、未適用)。ヘッドライン件数(`phase_r_runs_checked`等・カテゴリ別件数)は実列、根拠の全リストは`items` jsonbに保存する——`sigmaris_grounding_health_runs`・`sigmaris_cycle_health_runs`と同じ「ヘッドラインは列、詳細はjsonb」という設計を踏襲した。**Phase R/G/C-mini/C-fullとは別の新規テーブル**とした判断根拠も、それらの既存マイグレーションコメントが述べる理由(測定対象の異なる指標・データを1つのテーブルに混在させると、読み取り時にどの系統の行か曖昧になる)をそのまま踏襲している。

`backend/scripts/run_evidence_aggregation.py`から実行可能(`--limit`・`--notes`・`--dry-run`)。`run_cycle_health.py`/`run_grounding_health.py`と同じCLI設計。

---

## 4. テスト結果

`test_phase_d1_evidence_aggregation.py`として27件のテストを作成した(scratchディレクトリ)。

```
CheckMetricDropPublicApiTests (2件)
  PASS: リネーム後もcheck_metric_drop()が、RC-5が使っていた挙動
        (履歴不足時はcheckable=False、閾値超えの落ち込みでbroke_
        threshold=True)と完全に同じであること

BuildMetricDegradationItemsTests (7件)
  PASS: 実行が0件の場合は空リストを返すこと
  PASS: RC指標が1つだけ悪化した場合、severity=medium・priority_score=1
        になること
  PASS: RC指標が2つ同時に悪化した場合、両方ともseverity=high・
        priority_score=2になり、co_degraded_withに互いが記録されること
        (「複数指標の同時悪化を優先する」という要件の直接検証)
  PASS: 健全なRC指標からは根拠が生成されないこと
  PASS: Grounding指標(citation_precision)の悪化が検出されること
  PASS: 【重要】contradiction_rateの"増加"(低いほど良い方向への悪化)が、
        1-x反転を経て正しく悪化として検出され、表示値は反転前の
        直感的な値に戻されていること
  PASS: search_trigger_rateがどれだけ変動しても、一切根拠が生成され
        ないこと(G-5の「方向性不明」判断の継承を直接検証)

BuildMasteryProposalItemsTests (3件)
  PASS: 空リストは空リストを返すこと
  PASS: 悪化シグナルが1つのみの場合severity=lowになること
  PASS: RC-5がbreak_detectedの場合、他のシグナル数によらずseverity=high
        になること
  PASS: contextが欠損していてもクラッシュせずpriority_score=0になること

ParseBugInventoryTableTests (2件)
  PASS: サンプルテーブルの全データ行が正しくパースされること
  PASS: 「## 4. 問題一覧表」セクションが存在しない場合は空リストに
        なること

BuildRecurringProblemItemsTests (5件)
  PASS: 複数出典でも「修正済み」等の解決済みマーカーがある行は除外
        されること
  PASS: 単一出典の未解決行は除外されること
  PASS: 【重要】「本タスク2.1節・6.2節」のような自己参照のみの行は、
        .mdファイル名を含まないため複数回記録として数えられないこと
  PASS: 複数出典・未解決の行が正しくseverityとsource_filesを持って
        含まれること
  PASS: priority_scoreが「深刻度の重み+複数回記録ボーナス」の通りに
        算出されること

AggregateEvidenceTests (2件)
  PASS: 全カテゴリの根拠がpriority_score降順にソートされ、
        sources_checkedが正しく件数を反映すること
  PASS: bug_inventory_markdown=Noneでもクラッシュせず、該当カテゴリが
        0件になること

RunEvidenceAggregationTests (2件)
  PASS: 3つのDBソース+ファイル読み取りが正しく組み合わされること
        (get_recent_experiencesへlimit/experience_type/categoryが
        正しく渡ることを含む)
  PASS: bug_inventory.mdが見つからない場合もクラッシュせず、
        items=[]で完走すること

RecordEvidenceBundleTests (3件)
  PASS: 正しいペイロード形状でPOSTされること
  PASS: HTTP失敗時、例外を伝播させずNoneを返すこと
  PASS: get_recent_evidence_bundles()が失敗時に空リストを返すこと

27 passed
```

**実際の`bug_inventory.md`ファイルに対するパーサーの動作確認**: モックテストとは別に、実際の`docs/sigmaris/bug_inventory.md`を読み込んで`parse_bug_inventory_table()`を直接実行し、全23行(#1〜#20、うち1b/1c/2bを含む)が正しくパースされること、および「複数回記録」として#6・#11・#17の3件が正しく抽出されることを確認した(既に解決済みとマークされている#1・#1b・#2・#5・#8・#19・#20は、複数出典であっても正しく除外された)。

既存の`backend/tests/`(16件)・S/R/G/BA4系・直近のPhase Vis改称タスクを含む全scratchテスト一式を、本タスクの変更(`cycle_health_metrics.py`のリネームを含む)前後で再実行し、リグレッションがないことを確認した。

```
292 passed, 4 subtests passed(backend/tests/ + 全scratchテスト、合算実行、本タスクの27件を含む)
```

`scripts/run_evidence_aggregation.py --help`の実行により、CLIの引数解析・ヘルプテキスト表示が正しく機能することも確認した。

**実モデルAPI・実データベースでの検証は行っていない。** テストは`supabase_rest`のHTTPクライアントをモックする形にとどまる(依頼書の注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない)。マイグレーション(`202607250052_evidence_bundles.sql`)は作成のみ、適用は運用者側に委ねる。

---

## 5. Constitution(S-4)の範囲についての確認

依頼書の重要な注意事項「本フェーズは正式な安全性・ガバナンスの柱(Phase H完了後に実装予定)がまだ存在しない状態で進めている。既存のConstitutionの範囲を超える判断は行わず、疑わしい場合は必ず報告すること」に対する確認結果を明記する。

本タスクで実装した3つのモジュール(`evidence_aggregation.py`・`evidence_aggregation_runner.py`・`evidence_aggregation_store.py`)は、いずれも**既存データの読み取り・集約・新規テーブルへの記録のみ**を行い、以下のいずれにも該当しない。

- `sigmaris_constitution`(S-4)が定めるCapability(能力の一線)のいずれか(データ削除・外部送信・コード変更・認証情報アクセス)
- 既存のユーザー向けデータ(`user_fact_items`・`chat_messages`等)への書き込み・変更
- 会話応答経路への新規介入

`constitution_guard.requires_approval()`によるゲートは、`goal_proposal.py`の`_ActionOutcome.capability_category`のように、実際に行動を実行する層にのみ存在する。D-1は「読み取って集約するだけ」の層であり、S-4が定める承認フローの対象となる行動を一切生成しないため、**Constitution Article 6のゲートを新たに通す必要はないと判断した**。この判断が疑わしいと感じられる場合は、D-2(実際に改良案=行動候補を生成する段階)着手前に、改めてConstitutionとの整合を確認することを強く推奨する——D-1はあくまで「材料を並べるだけ」であり、D-2以降で「その材料から何をするか」を決める段階に入った時点で、Capabilityの一線の検討が本格的に必要になる。

---

## 6. 気づいた懸念点・次のステップ(D-2: 仮説生成)に向けた申し送り事項

1. **`bug_inventory.md`のテーブルパーサーは、表フォーマットへの依存が強いベストエフォート実装である。** 列数・列順・見出し文字列(「## 4. 問題一覧表」)が変わった場合、パーサーは静かに0件を返す(例外は投げない設計)。次に`bug_inventory.md`を更新するタスクがあれば、この依存関係を意識する必要がある。
2. **Mastery Drive優先順位付けの閾値(0.8・`break_detected`)は`goal_proposal.py`からのコピーであり、import による共有ではない(2.3節)。** 両者が将来ずれる可能性がある既知の技術的負債として記録する。
3. **`priority_score`のスケールはカテゴリ間で統一されていない(2.4節)。** D-2が3カテゴリを横断して単一のランキングを作りたい場合、この生スコアをそのまま使うのではなく、カテゴリごとの正規化(例: カテゴリ内での相対順位に変換する等)を検討する価値がある。
4. **「測定指標の悪化」は、Phase R/G双方とも実行回数が3回未満の間は一切検出できない(`_DEGRADATION_MIN_HISTORY=3`)。** 運用開始直後は`metric_degradation`カテゴリが恒常的に0件になる——これは「問題なし」ではなく「まだ判定できない」であり、6.4節の「0件は問題なしを意味しない」という`run_evidence_aggregation.py`自身の標準出力の注意書きと整合させている。
5. **`sigmaris_evidence_bundles`は、Phase R/Gと同じく「直近の実行」を毎回独立に計算し直す設計であり、実行間の差分比較(前回のbundleと比べて根拠がどう変わったか)は実装していない。** D-2が「前回検討済みの根拠を除外して差分だけを見る」ような運用をしたくなった場合、`get_recent_evidence_bundles()`(既に用意済み)を使った比較ロジックの追加を検討する余地がある。
6. **D-2着手前に、5章で述べたConstitution整合性の再確認を強く推奨する。** D-1は読み取り専用だが、D-2は「何を改良すべきか」という仮説を生成する段階であり、その仮説の内容次第ではCapabilityの一線に関わる可能性がある。

---

## 7. マージについて

「テスト・検証」章の要件をすべて満たしていることを確認した(4つのデータソースからの根拠収集・優先順位付けの意図通りの動作・既存テストの回帰確認、いずれも達成)。既存機能(Phase R・Phase G・Phase S・B群全体)への悪影響がないことも、`cycle_health_metrics.py`のリネーム前後での全テスト再実行によって確認した。依頼書の指示通り、確認を待たずmainへマージ・プッシュする。
