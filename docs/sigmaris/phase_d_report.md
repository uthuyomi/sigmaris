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

---

# 古い self_improvement.py の削除、+ Phase D-2(仮説生成)実施報告

**作業ブランチ:** `phase-d2-hypothesis-generation`(mainから新規作成)
**範囲:** (1) Constitution(S-4)の管理下に無かった旧`self_improvement.py`一式の削除、(2) 一時停止していたPhase D-2(仮説生成)の実装。依頼書の指示通り、削除を完了・確認してから、D-2に着手した(並行作業は行っていない)。

---

## 8. 前回タスクでの一時停止の経緯(前提の再確認)

前回のPhase D-2着手時、Constitution(S-4)との連携方法を確認する過程で、`backend/app/services/self_improvement.py`という、以下の性質を持つ既存機能を発見した。

- `POST /api/agent/self/improve`(`SelfImprovementAgent.analyze()`): 監査ログ(`agent_invocation_audit_logs`)と自己モデルを分析し、LLM(`TaskType.SELF_REFLECT`)で改善提案のJSONを生成
- `POST /api/agent/self/apply`(`SelfImprovementAgent.apply_improvement()`): 提案を**実際に実行**する——`persona`種別は`docs/persona.md`へ直接書き込み、`code`種別はGitHub上に実際のブランチ・コミット・PRを作成
- **`constitution_guard.py`・`requires_approval()`への参照が一切無い**——S-4以降のConstitution管理下に組み込まれていない、古い実験的機能
- ゲートは`SELF_IMPROVEMENT_ENABLED`(デフォルトfalse)・`AGENT_SECRETS`ヘッダー認証・危険ファイルのブロックリスト・日次PR数上限の4つのみ

運用者と協議した結果、「Constitutionの管理下に無く、無検証で実行できる」という性質上、Phase Dのより慎重なパイプライン(D-1: 根拠収集 → D-2: 仮説生成 → 将来のD-3以降で優先順位付け・検証)へ完全に置き換えることが決定し、本タスクで削除する運びとなった。

---

## 9. `self_improvement.py`削除の実施内容

### 9.1 削除前の最終確認結果

指示書の指示通り、削除直前に改めて参照元を確認した。

```
grep -r "self_improvement|SelfImprovementAgent|ImprovementProposal|ApplyResult" backend/
→ backend/app/routes/agent.py (import + 2エンドポイント)
→ backend/app/config.py (self_improvement_enabled, github_token, github_repo)
→ backend/app/services/self_improvement.py (本体)
```

3ファイルのみで、他のPhase(R/G/S/D-1)・B群のいずれからも参照されていないことを再確認した(前回タスクでの調査結果と一致)。リポジトリ全体を対象にした確認でも、`docs/sigmaris/phase_c_mini_report.md`(過去のインシデント調査報告、2026-07-06のLOCAL_LLM_ENABLEDバグ調査で当時の影響範囲として`self_improvement.py`を挙げているだけの、履歴的な記録)以外に参照は無かった——この履歴的記録は「その時点で何が真実だったか」の記録であるため、変更していない。

### 9.2 削除した内容

1. **`backend/app/services/self_improvement.py`を削除**(449行)。
2. **`backend/app/routes/agent.py`**: `from app.services.self_improvement import ImprovementProposal, SelfImprovementAgent`のimportと、`POST /self/improve`・`POST /self/apply`の2エンドポイント(`ApplyProposalRequest`モデルを含む)を削除。
3. **`backend/app/config.py`**: `self_improvement_enabled`・`github_repo`を削除。**`github_token`は削除していない**——`research_agent.py`(GitHubトレンドリポジトリ検索、レート制限緩和用ヘッダー)が独立に使用していることを確認したため(依頼書「AGENT_SECRETSが他の機能でも共有されている場合は、この機能専用の部分のみを慎重に取り除くこと」の精神を、`github_token`にも適用した)。同様に**`AGENT_SECRETS`自体は一切変更していない**——`_verify_agent()`は`/self/model`・`/self/reflect`・`/facts/items`等、他の多数のエージェント向けエンドポイントで共有されているため。
4. **`backend/env.example`**: `SELF_IMPROVEMENT_ENABLED`・`GITHUB_REPO`の行を削除、`GITHUB_TOKEN`は`research_agent.py`用である旨のコメントを付けて維持。
5. **`docs/IMPLEMENTATION_STATUS.md`**: 削除によって内容が事実と異なることになった箇所(機能一覧表の行・エンドポイント一覧の2行・ファイル行数表の行・環境変数表の3行・「設定が必要な環境変数」表の1行・「自己改良の自動サイクル」という今後の実装予定の1項目)を削除・修正した。**判断根拠**: このドキュメント自体が、Phase A〜S/D全体を通じて一度も更新されないまま凍結された、非常に古いスナップショットである(行数の記載が現状と大きく乖離している箇所が多数ある、Phase A〜Dへの言及が一切無い等)。本タスクの変更で新たに事実と異なることになった`self_improvement.py`関連の記述のみを修正し、それ以外の古さについては範囲外として一切手を加えていない。

### 9.3 判断根拠が必要だった箇所

- **`github_token`を残す判断**: 削除するとresearch_agent.pyのGitHub検索が(トークン無しでも動作はするが)レート制限に晒されやすくなる。依頼書が明示的に警告していた「共有設定を慎重に扱う」の直接的な該当ケースであり、grepで実際の使用箇所を確認した上で残す判断をした。
- **`docs/IMPLEMENTATION_STATUS.md`の扱い**: 全面的な現状復旧(他の古い記述も含めた全面更新)はスコープ外と判断した。本タスクの変更によって「新たに嘘になった」記述だけを修正する、という限定的な範囲にとどめた。

---

## 10. 削除後の動作確認結果

- `python -c "import app.routes.agent"` が例外なく成功することを確認(importエラーが無いことの直接確認)。
- `grep`によるリポジトリ全体の再確認で、`self_improvement`・`SelfImprovementAgent`・`ImprovementProposal`・`self/improve`・`self/apply`のいずれも、コード上に一切残っていないことを確認(前述の履歴的記録1件を除く)。
- 既存の`backend/tests/`(16件)・S/R/G/D-1系の全scratchテスト(276件)を削除前後で再実行し、**リグレッションが無いことを確認した**(元々`self_improvement.py`を参照するテストは1件も存在しなかったため、テスト内容自体に変更は無い)。

```
292 passed, 4 subtests passed(削除後、backend/tests/ + 全scratchテスト合算)
```

---

## 11. Phase D-2(仮説生成)の実装詳細

削除の完了・確認後、前回一時停止していたPhase D-2の実装に着手した。前回の指示書(仮説生成のロジック・検証ステップ・Constitution連携)の内容をそのまま踏襲した。

### 11.1 仮説生成のロジック(プロンプト設計、根拠との対応関係の持たせ方)

新設: `backend/app/services/hypothesis_generation.py`(生成・フィルタ・検証・Constitution連携の中核ロジック)・`hypothesis_generation_runner.py`(I/O)・`hypothesis_store.py`(永続化)。既存の3層分離パターンを踏襲した。

**D-1のsigmaris_evidence_bundlesとの接続**: `evidence_aggregation_store.get_recent_evidence_bundles(limit=1)`で直近1回分のbundleを取得し、既にpriority_score降順で保存済みの`items`から上位N件(デフォルト5件、`--top-n`で変更可)を対象にする。**根拠1件につき仮説1件を生成する1:1対応**にした判断根拠: 複数の根拠を1つの仮説にまとめると、後段の「根拠との対応関係の検証」(11.2節)が、どの根拠との対応を検証すればよいか曖昧になる。1:1対応にすることで、仮説オブジェクト自体が常に単一の`source_evidence_category`/`source_evidence_title`を持ち、要件2(根拠との対応関係を明確に持つこと)を構造的に満たす設計にした。

**LLM呼び出し**: `TaskType.HYPOTHESIS_GENERATION`(新設、advanced tier)。**nano tierにしなかった判断根拠**: G-1〜G-4は「検索要否の判定」「証拠の構造化」等、分類・抽出に近い性質のタスクだったのに対し、D-2の仮説生成は「シグマリス自身のアーキテクチャに対して、何をどう変えるべきかを設計する」という、config.pyが`openai_advanced_model`に既に与えている役割(`自己反省・設計・週次レビュー`)そのものに該当すると判断した。ローカルLLM(Ollama)には**ルーティングしない**設定にした——`COMPLEX_REASONING`/`EVAL_JUDGE`/`EVAL_GENERATION`と同じ「品質が重要で、レイテンシに制約が無いオフラインCLI」という性質を踏襲した判断。

**プロンプトが要求するJSON出力**(依頼書が明記した4項目 + Constitution連携用の2項目):
```json
{
  "title": "短い見出し",
  "what_is_problem": "何が問題か(根拠の要約)",
  "why_problem": "なぜそれが問題と考えられるか",
  "how_to_improve": "どう改善すればよいか、という具体的な方向性(実装詳細ではない)",
  "expected_metric_improvements": ["RC-1", "Citation Precision", ...],
  "touches_safety_mechanism": true または false,
  "safety_mechanism_note": "触れる場合、どの安全機構にどう関わるか"
}
```
`title`・`what_is_problem`・`how_to_improve`のいずれかが空の場合は、生成自体を破棄する(`generate_hypothesis()`がNoneを返す)——不完全な仮説をそのまま後段へ流さないための、生成直後の最小限の構造チェック。

### 11.2 仮説の質を保つための検証ステップの実装内容

依頼書が要求した2種類の検証を、独立した2段階として実装した。

**(a) ルールベースの簡易フィルタ**(`is_vague_or_unsupported()`、LLM呼び出しなし):
1. **抽象性チェック**: `how_to_improve`が20文字未満、または「もっと良くする」「最適化する」等の定型句(`_VAGUE_PHRASES`)を除去した残りが15文字未満の場合、抽象的すぎると判定して除外する。
2. **根拠グラウンディングチェック**: `what_is_problem`が、根拠(`item.title`・`item.details`)と**字句レベルで最低限の重なり**を持つかを確認する。形態素解析等の重量級の依存は追加せず、正規表現による簡易トークン化(英数字連続・2文字以上の漢字/カタカナ連続)で字句集合を作り、共通集合が空なら「根拠と無関係」と判定して除外する。**判断根拠(意味解析をしない理由)**: 依頼書「過度に複雑な仕組みを避ける」という、このコードベース一貫の方針を踏襲した。字句レベルの重なりが無い仮説は、そもそも(b)のLLM検証にかける前の段階で明らかにおかしいと判断できるため、コストの低いルールベースを先に置く設計にした。

**(b) LLMによる根拠対応関係の検証**(`critique_hypothesis_correspondence()`、Self-Critique方式の応用): 依頼書「Phase Gで確立した、Self-Critique検証の考え方を、応用できないか検討する」に対応。G-3の`self_critique.py`と同じ「生成とは独立した視点(批評家)」パターンをそのまま踏襲し、`TaskType.HYPOTHESIS_CRITIQUE`(新設、nano tier、G-3のSELF_CRITIQUEと同じ位置づけ)で、仮説の`what_is_problem`/`why_problem`が根拠から論理的に導けるかを判定させる。**G-3の3階層判定(no_contradiction/minor_mismatch/clear_contradiction)をそのまま流用しなかった判断根拠**: 依頼書が「簡易的にチェックする仕組み」と明記しており、G-3ほど精緻な階層化は過剰と判断した。`grounded: true/false`の二値判定にとどめ、G-3より単純化した——このコードベースの「既存パターンを機械的にコピーするのではなく、要求される精度に応じて簡略化してよい」という前例(G-5がPhase Rの4指標中2指標のみを対象にしたRC-5の踏襲等)に沿った判断。

**fail-open方針**: 批評LLM呼び出し自体が失敗した場合は`grounded=True`側に倒す(self_critique.pyの`critique_response()`と同じ理由——批評の失敗と仮説の妥当性は無関係であり、一時的なAPI障害で正常な仮説まで毎回捨てる方が有害)。

いずれかの検証で除外された仮説はDBに永続化されない(12章参照)。除外件数はCLIの標準出力・戻り値の両方でカウントとして可視化する(`filtered_vague_count`・`filtered_ungrounded_count`)。

### 11.3 Constitution連携の実装内容

`rule_based_safety_flag()` + LLMの自己申告(`touches_safety_mechanism`)を**OR結合**した(要件4)。

**キーワード源**: 新しい安全機構リストを作らず、**S-4の棚卸し結果(`docs/sigmaris/phase_s_report.md` 28.1節)とConstitution本文(`docs/sigmaris/constitution.md`)をそのまま再利用した**——`response_guard.py`・`memory_confidence.py`(B11)・`constitution_guard.py`・`self_critique.py`(G-3)・`citation_audit.py`(G-4)・`dissent.py`(S-3)・`executive_gate.py`(S-1)・persona.md 9章/10章・`constitution.md`・「憲法」等。加えて、`docs/sigmaris/constitution.md` Article 6を読み直した際、Article 6の「必ず承認が必要なこと」に**`persona.md`の更新**という項目が(S-4報告書がまとめた「8項目→4カテゴリ」の要約には出てこない形で)含まれていることに気づいた——これは前回発見した`self_improvement.py`が実際に犯していた違反そのものであり、キーワードリストに persona.md 9章/10章 への言及を含めることで、この観点も間接的にカバーされるようにした。

**OR結合(安全側に倒す設計)**: Phase G-1の`merge_llm_search_judgment()`(ルールベースとLLM判定をOR結合し、再現率を優先する)と同じ設計判断を踏襲した。キーワード一致は意味解析を行わないため、「安全機構に言及しているが、実際には無関係な文脈」という誤検知もありうるが、依頼書の「疑わしい場合は慎重に扱う」という趣旨に照らし、**見逃しよりも過検知を許容する**方針にした。

**`constitution_guard.requires_approval()`を直接は使わなかった判断根拠**: `requires_approval()`は`CAPABILITY_APPROVAL_REQUIRED_CATEGORIES`(delete_data/external_transmission/code_change/credential_access)という、**既に実行されようとしている行動**を分類するための関数であり(`goal_proposal.py`の`_ActionOutcome.capability_category`が実際の行動に紐づく)、D-2は行動を一切実行しない(要件5)。仮説は「まだ実行されていない提案テキスト」であり、`requires_approval()`が前提とする「行動カテゴリの判定」とは意味的に異なるため、**別の関数(`rule_based_safety_flag()`)として独立に実装した**。将来D-3以降で、ある仮説が実際に行動として実行される段階に進む場合は、その時点で`capability_category`を明示的に割り当て、`requires_approval()`による承認ゲートを通す設計になる想定であり、この2つの関数の役割分担は意図的に維持すべきと考える(14章の申し送り事項参照)。

**フラグが立った仮説の扱い**(要件4後半): `requires_special_review=True`を仮説に付与し、`safety_review_reason`(キーワード一致理由 + LLM自己申告理由を結合)を記録する。優先順位付けは、複雑な重み付け式ではなく**「非フラグ群を先に、フラグ群を後に」という単純な並べ替え**にとどめた(D-1の`aggregate_evidence()`が確立した「シンプルな基準にとどめる」という判断をそのまま踏襲)。

### 11.4 出力形式・永続化

`sigmaris_hypotheses`(新設、未適用)は、D-1の`sigmaris_evidence_bundles`(1回の実行=1行、根拠は`items` jsonbにまとめる集約run形)とは異なり、**1件の仮説=1行という粒度の細かいログ形**にした。**判断根拠**: `sigmaris_citation_audit_log`(Phase G-4、claim単位の監査ログ)が既に確立した「個々の項目を後から独立に検索・集計したい場合は、run単位ではなくitem単位で行を分ける」という前例を踏襲した——D-3(優先順位付け・検証可能性の評価、未実装)が、個々の仮説を単独で参照・更新したくなる可能性が高いと判断したため。`evidence_bundle_id`は`sigmaris_citation_audit_log`の`thread_id`と同じ、**FK制約の無いソフトな参照**とした(Sigmaris自身の派生データであり、現状の設計ではjoinを一切行わないため)。

**除外された候補はDBに一切残らない**——CLIの標準出力・戻り値の集計値(`generated_count`/`filtered_vague_count`/`filtered_ungrounded_count`/`kept_count`)のみが、除外の記録となる。

実行方法: `python scripts/run_hypothesis_generation.py [--top-n N] [--dry-run]`。

---

## 12. テスト結果

`test_phase_d2_hypothesis_generation.py`として32件のテストを作成した(scratchディレクトリ)。

```
TaskTypeTierTests (4件)
  PASS: HYPOTHESIS_GENERATIONがadvanced tierへ正しくルーティングされること
  PASS: HYPOTHESIS_CRITIQUEがnano tierへ正しくルーティングされること
  PASS: HYPOTHESIS_GENERATIONがローカルLLM対象から除外されていること
  PASS: HYPOTHESIS_CRITIQUEはSELF_CRITIQUEと同様ローカルLLM対象であること

GenerateHypothesisTests (4件)
  PASS: 正常なJSON応答が正しくパースされること
  PASS: 必須フィールド欠損時にNoneを返すこと
  PASS: LLM呼び出し失敗時にNoneを返すこと(fail-open)
  PASS: JSON応答がdict以外の形の場合にNoneを返すこと

IsVagueOrUnsupportedTests (5件)
  PASS: 具体的で根拠と整合する仮説は除外されないこと
  PASS: 定型句のみのhow_to_improveが除外されること
  PASS: 短すぎるhow_to_improveが除外されること
  PASS: 【重要】根拠(title/details)と字句レベルで一切重ならない
        what_is_problemが「根拠のない仮説」として除外されること
  PASS: 定型句を含んでいても十分な具体性があれば除外されないこと

CritiqueHypothesisCorrespondenceTests (3件)
  PASS: grounded=trueが正しくパースされること
  PASS: grounded=falseが正しくパースされること
  PASS: LLM呼び出し失敗時、fail-openでgrounded=true側に倒れること

RuleBasedSafetyFlagTests (4件)
  PASS: 安全機構への言及が無ければフラグが立たないこと
  PASS: response_guard.pyへの言及でフラグが立つこと
  PASS: B11/ヘッジへの言及でフラグが立つこと
  PASS: 「緩和」等の弱化キーワード単体でもフラグが立つこと

FinalizeHypothesisTests (4件)
  PASS: grounded=falseの場合Noneを返す(除外)こと
  PASS: 安全でgrounded済みの仮説はrequires_special_review=falseになること
  PASS: 【重要】LLMが自己申告しなくても、ルールベース側の一致だけで
        requires_special_review=trueになること
  PASS: 【重要】ルールベースが一致しなくても、LLMの自己申告だけで
        requires_special_review=trueになること(OR結合の両方向を直接検証)

RunHypothesisGenerationTests (4件)
  PASS: evidence bundleが0件の場合、LLM呼び出しを一切せず空結果を返すこと
  PASS: 【重要】要レビューフラグが立った仮説が、通常の仮説より必ず
        後ろに並ぶこと(生成順序に依らず並べ替えられることを直接検証)
  PASS: 抽象的な仮説・対応関係の検証に失敗した仮説が、それぞれ正しく
        カウントされ、最終結果から除外されること
  PASS: 不正な形のevidence item(D-1由来のデータ破損等を想定)が
        クラッシュせずスキップされること

RecordHypothesesTests (4件)
  PASS: 空リストの場合HTTP通信すら発生させないこと
  PASS: 正しいペイロード形状でバルクPOSTされること
  PASS: HTTP失敗時、例外を伝播させず空リストを返すこと
  PASS: get_recent_hypotheses()が失敗時に空リストを返すこと

32 passed
```

`scripts/run_hypothesis_generation.py --help`の実行により、CLIの引数解析・ヘルプテキスト表示が正しく機能することも確認した。

既存の`backend/tests/`(16件)・削除前後で確認済みのS/R/G/D-1系全scratchテスト(276件)を含め、全て再実行しリグレッションが無いことを確認した。

```
32(本タスク) + 292(既存、self_improvement.py削除後の状態) = 324 passed, 4 subtests passed(合算実行)
```

**実モデルAPI・実データベースでの検証は行っていない。** テストは`get_llm_router()`・`supabase_rest`のHTTPクライアントをモックする形にとどまる(依頼書の注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない)。マイグレーション(`202607260053_hypotheses.sql`)は作成のみ、適用は運用者側に委ねる。

### 生成される仮説のサンプル(テストコードより、実際にモジュールへ渡した入出力の一例)

**入力(D-1由来の根拠、metric_degradation)**:
```
category: metric_degradation
title: RC-1(循環完了率)の悪化
description: RC-1が過去平均90%から50%まで低下している。
severity: medium
details: {"metric": "rc1_eligible_completion_rate", "current": 0.5, "baseline": 0.9}
```

**期待される出力形状(LLM生成、テストでモックした値の一例)**:
```json
{
  "title": "RC-1低下の原因調査",
  "what_is_problem": "RC-1(循環完了率)が過去平均90%から50%まで低下している",
  "why_problem": "ExperienceからMemoryへの到達を妨げる要因が生じている可能性がある",
  "how_to_improve": "consolidate_episodic_memory()の再スキャン窓とバッチ実行間隔を見直し、aged_out理由の内訳を継続的にログへ残すようにする",
  "expected_metric_improvements": ["RC-1"],
  "touches_safety_mechanism": false,
  "safety_mechanism_note": ""
}
```

**Constitutionに触れる仮説の例(フラグが立つケース)**: `how_to_improve`に「constitution_guard.pyの承認フローを一部バイパスする」を含む仮説は、`rule_based_safety_flag()`が`constitution_guard`キーワードへの一致を検出し、LLMの自己申告が無くても`requires_special_review=True`となり、出力の末尾に配置される(テストで直接検証済み)。

---

## 13. Phase D(D-1〜D-2、現時点まで)を通じての振り返り

| タスク | 到達点 |
|---|---|
| D-1 | Phase R・Phase G・Phase S-2(Mastery Drive)・bug_inventory.mdという既存4資産から根拠を集約・分類・優先順位付けし、`sigmaris_evidence_bundles`へ構造化して保存 |
| (中間) | 旧`self_improvement.py`(Constitution管理外の実験的機能)を発見・報告・削除 |
| D-2(本タスク) | D-1の根拠から、LLMで具体的な改良仮説を生成し、ルールベース+LLMの二段階検証、Constitution連携によるフラグ立てを行い、`sigmaris_hypotheses`へ保存 |

一貫していた設計哲学は、D-1報告書5.2節で述べた3点(新しい仕組みより既存資産の再利用・Noneや除外を恐れない・単一の数値/判定の裏にある「なぜ」を問う)に加え、D-2では**「まだ何も実行されていないことの徹底」**が新たに加わった。仮説はテキストとして生成・保存されるのみで、`goal_proposal.py`のような実行経路(`record_experience()`相当の確定操作)を一切持たない——これは要件5の直接的な帰結だが、`self_improvement.py`削除という前段の作業を経たことで、この徹底の重要性がより具体的な形で裏付けられたと言える。

---

## 14. 気づいた懸念点・次のステップ(D-3)に向けた申し送り事項

1. **字句レベルの根拠グラウンディングチェック(11.2節)は、形態素解析を伴わない簡易ヒューリスティックである。** 意味は同じだが表記が異なる場合(例: 「循環完了率」と「Cycle Completion Rate」)は、重なりが検出されず誤って除外される可能性がある。実運用でこの誤検出が無視できない割合を占めることが分かれば、B1が既に持つembeddingインフラを使った類似度判定への置き換えを検討する価値がある(Phase R-3のRC-3が既に同種の限界を明記している、13.2節の反転検出と同じ性質の簡略化)。
2. **`rule_based_safety_flag()`のキーワード一致は意味解析を伴わないため、過検知(false positive)の余地がある。** 「見逃しより過検知を許容する」という意図的な設計だが、運用開始後にフラグ率が高すぎることが分かれば、キーワードリストの精緻化(除外パターンの追加等)を検討する必要がある。
3. **Constitution本文(Article 6)に「persona.mdの更新」という承認必須項目があることが、S-4報告書の要約(8項目→4カテゴリ)には明示的に反映されていない。** 本タスクではキーワードリストへの間接的な反映(persona.md 9章/10章への言及)にとどめたが、`constitution_guard.py`の4カテゴリ自体に`persona_update`を独立したカテゴリとして追加すべきかどうかは、本タスクのスコープ外の判断であり、次タスク以降で改めて検討する価値がある。
4. **`sigmaris_hypotheses`は除外された候補を保持しないため、「どのような仮説が生成されては消えていったか」という傾向分析ができない。** D-3以降で、仮説生成プロンプト自体の改善(何が「良い仮説」かのチューニング)が必要になった場合、除外理由の分布を追跡できる仕組み(除外もdetailsとして保存する等)を検討する余地がある——本タスクでは意図的にスコープ外とした(依頼書が要求したのは生成・検証・フラグ立てのみ)。
5. **D-3(優先順位付け・検証可能性の評価)に向けて**: 依頼書の想定通り、D-2はあくまで「根拠1件→仮説1件」の変換層にとどまり、複数の仮説間の相対的な優先順位付けや、「この仮説は本当に検証可能か(A/Bテスト可能か等)」という評価は行っていない。`sigmaris_hypotheses.requires_special_review`で要レビュー分は既に区別できる状態にあるため、D-3は「通常の仮説群の中でどれを優先するか」「要レビュー分をどう人間の確認フローに乗せるか」という2つの異なる問いに取り組むことになると想定される。

---

## 15. マージについて

「テスト・検証」章の要件をすべて満たしていることを確認した(削除後の既存テスト回帰確認・self_improvement.pyへの参照が完全に消えていることの確認・D-2の生成/フィルタ/検証/Constitution連携それぞれの動作確認、いずれも達成)。既存機能(D-1・Phase R・Phase G・Phase S・B群全体)への悪影響も、削除直後とD-2実装後の両時点での全テスト再実行によって確認した。依頼書の指示通り、確認を待たずmainへマージ・プッシュする。
