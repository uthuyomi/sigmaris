# Self-1 実施報告: コードベースのスキャン、機能の洗い出し(自己認識の自動更新、第一段階)

**作業ブランチ:** `self-1-capability-scan`(mainから新規作成)
**範囲:** persona.md・self_model(人間が手で書く固定の文書)には反映されていない、実際にコードベースへ実装・稼働している機能を、機械的に洗い出す仕組みの第一段階を実装する。**本タスクは"洗い出し"までを行う。** 洗い出した情報を日本語に要約する処理(Self-2)、応答生成への注入(Self-3)は行っていない。

---

## 0. 前提として確認したこと

着手前に指示書が指定した2ファイルを確認した。

- `docs/sigmaris/safety_governance_report.md`(Safety-1〜3): Safety-3(`safety_critical_files_scan.py`)が確立した「(a)関数名パターン、(b)ファイル冒頭コメントのキーワード、の2種類のシグナルをOR結合する(安全側に倒す、完全な自動化はしない)」という設計思想。D-2(`hypothesis_generation.py::rule_based_safety_flag()`)のOR結合パターンをSafety-3がそのまま応用した、という前例も確認した。
- `docs/sigmaris/phase_h_report.md`(H-1〜H-3): X投稿・返信生成システムの実装経緯。依頼書が言う「シグマリスが自分のX投稿機能を認識していなかった」という発見自体は、本タスクの背景として述べられた事象であり、phase_h_report.md自体には(H-1〜H-3が実装した機能一覧として)登場する。

---

## 1. 「能力」とみなす対象の基準の定義

依頼書2章が例示した4領域(X投稿・返信生成/記憶検索・抽出/自己改善の提案・検証・実行/検索・引用精度向上)+ scripts/配下の独立したCLI、それぞれについて、実際のコードを確認した上で、以下の**3つの独立したシグナルをOR結合する**方式を採用した(Safety-3と全く同じ設計思想、判断根拠は2章)。

### シグナルA: ファイル冒頭のPhaseタグ

このコードベースの大半のサービスファイルは、`# 役割: Phase H-1「投稿の種類・テンプレートの実装」...`のように、実装したPhase番号を冒頭コメント/docstringに明記する慣習を持つ。正規表現`Phase\s+[A-Z][\w.-]*`で、冒頭15行以内からこのタグを検出する。実際に観測した表記ゆれ("Phase H-1"・"Phase B11"・"Phase G-4"・"Phase C-full"・"Phase H-2.5"・"Phase D")を、全てこの1つの正規表現で捉えられることを確認した。

### シグナルB: ファイル名に含まれる能力領域の語彙

依頼書の4領域それぞれから、実際にこのコードベースで使われているファイル名の接頭辞・部分文字列を抽出した(`x_post`/`x_reply`/`memory_`/`user_fact`/`hypothesis`/`code_diff`/`citation_audit`/`evidence_search`等)。**判断根拠(なぜファイル名限定で、ファイル冒頭コメント全体を対象にしなかったか)**: 実装時の検証で、"memory"・"fact"のような単語をヘッダーテキスト全体(import文を含む)に対して照合すると、単に`user_fact_data`をimportしているだけの無関係なファイルまで過検知することが判明した。ファイル名は、このコードベースの命名規則が既に能力領域を表しているため、より精度の高い、安全なシグナルとして採用した。

**シグナルBが必要だった具体的な理由(調査で判明した事実)**: `memory_search.py`・`memory_extractor.py`・`memory_validator.py`・`memory_snapshot.py`は、調査の結果、**冒頭にPhaseタグはおろか"# 役割:"コメントすら一切持たない**ことが判明した(x_publisher.py・x_post_generator.py・x_reply_classifier.py・x_content_filter.py・x_privacy_filter.pyも同様)。シグナルAだけでは、記憶検索・抽出というB群の中核ファイル、およびX投稿・返信の一部の中核ファイルを取りこぼす——シグナルBは、この具体的な取りこぼしを補うために必須だった。

### シグナルC(scripts/限定): 独立したCLIとして実行可能であること

`if __name__ == "__main__":`を持つことを、`backend/scripts/`配下のファイルに限って確認する。依頼書「その他、scripts/配下の独立したCLIとして実行可能な機能」への直接対応。実際に`backend/scripts/`配下の全18ファイルが、このガードを持つことを確認した。

### 依頼書の4領域を超えて追加した1領域(独断で決めた箇所)

洗い出しの過程で、`curiosity_engine.py`・`research_agent.py`(好奇心駆動の外部Web研究機能)が、シグナルA・Bのいずれにも該当しない(Phaseタグなし、依頼書の4領域キーワードにも一致しない)ことに気づいた。これは実在する、既知の(このセッション内で人格憲章Article 8・スケジューラの`curiosity_search`/`self_interest_queries`ジョブとして既に確認済みの)独立した機能領域であるため、`"curiosity"`・`"research_agent"`という5つ目のドメインキーワードを追加した。**判断根拠**: 依頼書2章の対象定義は「以下の**ような**対象」(非網羅的な例示)であり、実在する既知の能力領域を追加で拾うことは、依頼書の意図(自己認識のズレの解消)に反しないと判断した。

---

## 2. スキャンの実装詳細(Safety-3との再利用関係)

### 2.1 新設モジュール: `backend/app/services/capability_scan.py`

Safety-3(`safety_critical_files_scan.py`)と、**構造・設計思想を完全に踏襲**した。

| Safety-3 | 本タスク(Self-1) | 対応関係 |
|---|---|---|
| `_matches_gate_function_name()`(関数名パターン) | — (今回は不採用) | 判断根拠は下記参照 |
| `_matches_header_comment()`(冒頭コメントキーワード) | `_matches_phase_tag()`(冒頭Phaseタグ) | 同じ「冒頭N行をテキストとして走査し、キーワード/パターンに一致するか」という技法をそのまま適用。対象を「安全キーワード」から「Phaseタグ」に変えただけ |
| (シグナルBのみ、ファイル名は見ていない) | `_matches_domain_filename()`(ファイル名) | Safety-3には無い、新規追加したシグナル(判断根拠は1章) |
| `scan_for_gate_pattern_files()`(ディレクトリ走査、`app/services`・`scripts`) | `scan_capabilities()` | スキャン対象ディレクトリ選定・走査ロジック(`rglob("*.py")`、`__`始まりファイル/自己参照ファイルの除外)を完全に同一の設計で踏襲 |
| `GatePatternFile`/`SafetyCoverageScanResult`(dataclass) | `CapabilityCandidate`/`CapabilityScanResult`(dataclass) | 同じ構造(相対パス+理由のリスト)を踏襲。本タスクでは追加で`domain`・`header_description`・`public_functions`を持たせた(依頼書「機能名、対応するファイル・関数、簡単な説明の元になる情報」という出力構造への対応) |
| `find_unregistered_gate_files()`(正典との突合) | (該当なし) | Safety-3は「未登録"候補"の発見」が目的だったが、本タスクは「洗い出し自体」が目的であり、突合対象となる既存の正典(登録簿)がそもそも存在しない。この差異は、両タスクの目的の違いに起因する妥当な設計上の相違であり、独断で省略した箇所として明記する |

**関数名パターン(Safety-3のシグナルA相当)を採用しなかった判断根拠**: Safety-3の関数名マーカーは、`requires_approval`・`check_diff_safety`のような、**安全機構に特有の狭い語彙**だったために機能した(汎用的な`check_`接頭辞は`cycle_health_metrics.py`を過検知したため不採用、というSafety-3自身の判断根拠が既にある)。「能力」を表す関数名には、これに相当するような狭い共通語彙が存在しない(`generate_`・`get_`・`run_`等はコードベース全体で極めて広く使われており、これを能力検出のシグナルにすると、ほぼ全てのファイルが該当してしまい、シグナルとして機能しない)。そのため、関数名パターンの代わりに、より精度の高い「ファイル名」をシグナルBとして採用した——Safety-3の"考え方"(2種類の相補的なシグナルのOR結合)は完全に踏襲しつつ、"具体的なシグナルの中身"は、検出対象の性質(安全機構 vs 能力)に合わせて適応させた。

### 2.2 新設CLI: `backend/scripts/scan_capabilities.py`

`scan_safety_critical_files.py`と同じ構成(読み取り専用、DB書き込み・ファイル書き込みなし、標準出力への表示のみ)。加えて`--domain`オプションで領域別のフィルタ表示ができるようにした(依頼書の範囲外の追加機能ではなく、洗い出し結果を人間が確認しやすくするための、表示側のみの軽微な拡張)。

### 2.3 実装時に発見・修正したバグ(判断根拠として明記)

実装の検証過程で、`app_profile_data.py`(冒頭コメント「Phase BA2」)が、誤って`memory`領域に分類される過検知を発見した。原因は、Phaseタグから領域を推定する処理が「タグの先頭1文字」だけを見ていたため、"BA"(orchestrator統合の別系列、記憶検索とは無関係)が"B"(記憶検索・抽出のB群)に丸め込まれていたことによる。**先頭の英字の並びを完全一致で比較する方式に修正し、"BA2"が"B"と誤認されないことを確認した**(4章のテストで直接検証)。

---

## 3. 実際に洗い出された機能の一覧(サンプル)

実際に`backend/`に対してスキャンを実行した結果(実測、レポート執筆時点)。

```
スキャン対象ファイル数: 147
能力候補として検出されたファイル数: 98

領域別の内訳:
  self_improvement    : 35件
  other               : 18件  (Phaseタグはあるが4+1領域のキーワードに一致しないもの。
                                Phase S・R・C-mini/C-full等)
  memory              : 15件
  x_post_reply        : 14件
  search_citation     : 8件
  cli_script          : 6件   (Phase/ファイル名シグナルに一致せず、CLIエントリ
                                ポイントのみで検出されたスクリプト)
  research_curiosity  : 2件
```

**依頼書が例示した既知の機能が、いずれも正しく検出されていることを確認した**(4章のテストで直接検証):

```
- [x_post_reply] backend/app/services/x_publisher.py
    公開関数: post_tweet, get_own_user_id, fetch_mentions, format_sigmaris_post, get_publisher
    理由: ファイル名がマーカー「x_publisher」に一致

- [x_post_reply] backend/app/services/x_post_category_selector.py
    説明の元情報: 役割: Phase H-1「投稿の種類・テンプレートの実装」— 7カテゴリ(A〜G)の
    公開関数: select_post_category
    理由: 冒頭コメントにPhaseタグ「Phase H-1」を検出
    理由: ファイル名がマーカー「x_post」に一致

- [memory] backend/app/services/memory_search.py
    公開関数: search_relevant_memories, ...
    理由: ファイル名がマーカー「memory_」に一致
    (Phaseタグ・役割コメントを一切持たないため、シグナルBのみが頼り)

- [self_improvement] backend/app/services/hypothesis_generation.py
    理由: 冒頭コメントにPhaseタグ「Phase D-2」を検出
    理由: ファイル名がマーカー「hypothesis」に一致

- [search_citation] backend/app/services/citation_audit.py
    説明の元情報: 役割: Phase G-4(Two-Layer Citation Audit、docs/sigmaris/phase_g_report.md)
    公開関数: audit_citation_usage, select_guidance_note, finalize_response_with_citation_audit, ...
    理由: 冒頭コメントにPhaseタグ「Phase G-4」を検出
    理由: ファイル名がマーカー「citation_audit」に一致

- [cli_script] backend/scripts/run_cycle_health.py
    説明の元情報: 循環健全性指標(RC指標) — RC-1〜RC-5をコマンド一つで計測する。
    公開関数: main, run
    理由: 独立したCLI(`if __name__ == "__main__":`)として実行可能

- [research_curiosity] backend/app/services/curiosity_engine.py
    公開関数: enqueue_curiosity, get_pending_queue, execute_curiosity_search,
              generate_curiosity_queries, generate_self_interest_queries
    理由: ファイル名がマーカー「curiosity」に一致
```

**infra専用ファイルが過検知されていないことも確認した**: `config.py`(「役割: FastAPI バックエンドの環境設定をまとめる。」)・`supabase_rest.py`(「役割: Supabase REST API への共通アクセス処理を提供する。」)は、いずれも"# 役割:"コメントを持つがPhaseタグ・領域キーワードのいずれにも一致せず、正しく候補から除外されている。

全98件の完全な一覧は、`python scripts/scan_capabilities.py`を実行することで、いつでも再取得できる(本報告書には全件を転記しない——依頼書「本タスクの範囲は洗い出しのみ」に対応し、この一覧の日本語要約・整形はSelf-2の役割とする)。

---

## 4. テスト結果

いずれもモック不要(実際のファイルシステムに対する読み取り専用の検証、Safety-3の`ScanAgainstRealRepoTests`と同じ方針)。scratchディレクトリに作成(`backend/tests/`には追加していない、既定の方針通り)。

```
RealRepoKnownCapabilityTests (8件、依頼書のテスト要件1「既知の機能が正しく検出されること」への直接対応)
  PASS: X投稿機能(x_publisher.py・x_post_generator.py)が、domain=x_post_replyとして検出されること
  PASS: 【重要】記憶検索・抽出(memory_search.py・memory_extractor.py・memory_validator.py)が、
        domain=memoryとして検出されること——これら3ファイルはPhaseタグ・役割コメントを一切持たず、
        シグナルB(ファイル名)が無ければ検出できないことの直接証明
  PASS: 自己改善(hypothesis_generation.py・code_diff_generation.py)が、
        domain=self_improvementとして検出されること
  PASS: 検索・引用精度(citation_audit.py)が、domain=search_citationとして検出されること
  PASS: CLIスクリプト(run_cycle_health.py)が、domain=cli_scriptとして検出されること
  PASS: infra専用ファイル(config.py・supabase_rest.py)が、過検知されないこと
  PASS: 【重要】x_publisher.py(ABC+複数実装クラスが同名メソッドを持つ)の公開関数一覧に、
        重複が無いこと(2.3節とは別に発見した表示上の重複を、実装時に修正したことの直接検証)
  PASS: スキャン対象ファイル数(147件)・検出件数(98件)が、それぞれ妥当な範囲であること

SyntheticNewCapabilityDetectionTests (4件、依頼書のテスト要件2
  「意図的に新しいテスト用の機能を追加し、それも正しく検出されることを確認する」への直接対応。
  実リポジトリには一切書き込まず、一時ディレクトリに合成したbackend/風ツリーで検証——
  Safety-3のSyntheticUnregisteredFileDetectionTestsと同じ手法)
  PASS: 【最重要】新しいPhaseタグ(「Phase Z-1」)を持つ、実在しない架空の新規サービスファイル
        (totally_new_feature.py)が、正しく検出され、その公開関数(do_the_new_thing)も
        正しく抽出されること
  PASS: 【最重要】Phaseタグも役割コメントも一切持たない、ファイル名のみが手がかりの新規ファイル
        (memory_totally_new_helper.py)が、domain=memoryとして検出されること
  PASS: 新しいCLIスクリプト(run_totally_new_thing.py、`if __name__=="__main__":`のみ持つ)が、
        domain=cli_scriptとして検出されること
  PASS: いずれのシグナルにも一致しない、普通のヘルパーファイル(generic_utils.py)が、
        検出されないこと(過剰検知の防止確認)

12 passed
```

既存の`backend/tests/`(16件)を、本タスクの変更前後で再実行し、リグレッションが無いことを確認した。**本タスクは新規モジュール・新規CLIの追加のみであり、既存のいかなるファイルも変更していない**(要件5「既存機能(Safety-1〜3・Phase D〜H・B群全体)に悪影響を与えないこと」への直接対応——変更対象がゼロであるため、影響もゼロである)。

```
16 passed(変更前)
16 passed(変更後)
12(本タスク、scratch) + 16(backend/tests/) = 28 passed
```

`capability_scan.py`・`scan_capabilities.py`の構文チェック(`ast.parse`)、および`app.main`のimportが引き続き成功することを確認した(本タスクのモジュールはどこからもimportされていない、独立したスタンドアロンのCLIツールであるため、これは「他への影響が無いこと」の追加確認である)。

**実モデルAPI・実データベースでの検証は行っていない。** 本タスクはファイルシステムの読み取りのみで完結する(依頼書「実モデルAPIでの検証ができない場合、追加取得は不要」に対応)。**新規マイグレーションは不要である**(DBへの書き込みを一切行わないため)。

---

## 5. 気づいた懸念点・次のステップ(Self-2: 日本語への要約)に向けた申し送り事項

1. **【最重要、Self-2への申し送り】"other"領域(18件)・"cli_script"領域の一部は、依頼書の4+1領域のいずれにも属さない、より広い「Phaseタグを持つが未分類」のファイル群である。** これらはPhase S(主体性)・Phase R(循環健全性)・Phase C-mini/C-full(評価基盤)等に相当し、いずれも実在する正当な機能だが、本タスクの4+1領域の枠には収まらない。Self-2が日本語要約を行う際、これらを無視するか、追加の領域として扱うかは、本タスクでは判断していない——依頼書自身が「そのような対象」という非網羅的な例示だったため、Self-1は広めに拾うことを優先し、絞り込みはSelf-2の判断に委ねる。
2. **ファイル単位の粒度である点の限界**: 本タスクは「1ファイル=1候補」という粒度で洗い出しており、1つのファイルに複数の異なる能力が同居している場合(例: `x_post_generator.py`が投稿生成とフィルタリングの両方を含む)、それらを分離しては報告しない。`public_functions`フィールドに、そのファイルの公開関数一覧を含めているため、Self-2はここから、より細かい粒度の能力単位を抽出することもできる設計にしてある。
3. **ヒューリスティックであることの限界(Safety-3と同じ性質の限界)**: シグナルA(Phaseタグ)・シグナルB(ファイル名)のいずれにも一致しない、命名規則に従わない新しい機能は、見逃される可能性がある。逆に、Phaseタグを持つが実際には能力ではない補助ファイル(例えば、ある機能のテストヘルパーやデータストア層)も、"能力"として一緒に検出されてしまう(例えば`code_diff_proposal_store.py`のような永続化層も、`self_improvement`領域に含まれている——これは「この機能に関連するファイル群」としては正しいが、「シグマリスが実行できる具体的な行為」という意味でのcapabilityとは、厳密には性質が異なる)。この粒度の粗さは、Self-2が実際に日本語で要約する際、ストア層・ランナー層・純粋ロジック層を区別する判断が必要になる可能性がある点として申し送る。
4. **`goal_proposal.py`(Phase S-2)が"other"領域として検出されている点**: 直近のセッションの調査(Phase S-6)で、この機能は現時点でスケジューラに配線されておらず、実際には呼び出されていないことが分かっている。本タスクのスキャナーは「コードとして存在するか」のみを見ており、「実際に呼ばれているか(生きているか)」までは判定しない——Self-2が要約する際、この区別(存在するが未配線、という状態)をどう扱うかは、判断が必要になる。
5. **`x_post_reply`領域に、H-1〜H-3で実装されたフィルタ層(`x_content_filter.py`・`x_privacy_filter.py`・`x_reply_filter.py`)も含まれている点**: これらは「投稿・返信を生成する」機能そのものではなく、「生成された内容を検閲する」安全側の機能であり、Safety-1〜3が棚卸しした安全機構と一部重複する可能性がある(例えば`x_reply_filter.py::detect_injection_attempt`等)。能力の洗い出し(Self-1)と安全機構の棚卸し(Safety-1〜3)が、同じファイルを別の目的で二重に参照する状態になっている——実害はないが、Self-2以降、この重複を意識した記述にする価値があるかもしれない。
6. **ドメイン分類(`domain`フィールド)は、あくまで報告の見やすさのための大まかなグルーピングであり、判定基準そのものではないことを、あらためて強調する。** 実際の検出可否は、シグナルA/B/Cのいずれかへの一致のみで決まり、ドメイン名は事後的に割り当てられる付随情報に過ぎない。

---

## 6. マージについて

「テスト・検証」章の要件をすべて満たしていることを確認した(依頼書が例示した既知の機能の検出・意図的に追加した新規機能の検出、いずれも4章参照)。既存機能への影響もゼロ(新規ファイルの追加のみ、既存ファイルは無変更)であることを確認した。依頼書の指示通り、確認を待たずmainへマージ・プッシュする。

---

# Self-2 実施報告: 洗い出した機能の日本語への要約(自己認識の自動更新、第二段階)

**作業ブランチ:** `self-2-capability-summary`(mainから新規作成)
**範囲:** Self-1が洗い出した98件の能力候補を、(1)まとまりのある単位でグループ化し、(2)未配線(まだ呼び出されていない)機能を機械的に判定した上で、(3)既存のnano-tier LLM呼び出しで、シグマリスが一人称で語る簡潔な日本語説明へ要約する。**本タスクは"要約"までを行う。** 応答生成への注入(Self-3)は行っていない。

---

## 7. 前提として確認したこと

着手前に、Self-1報告書(0〜5章)を確認した。特に5章の申し送り事項4「`goal_proposal.py`(Phase S-2)が"other"領域として検出されており、直近のセッションの調査(Phase S-6)で、スケジューラに配線されておらず実際には呼び出されていないことが分かっている」という、本タスクの重要な制約1に直結する既知の事実を、着手前に把握した。

---

## 8. 未配線の機能の判定方法、及び扱いの判断根拠

### 8.1 判定方法: importのgrep的チェック

依頼書が提案した「その機能を呼び出している箇所がコードベース内に存在するか」を、正規表現による軽量なチェックで実装した(`capability_summary.py::_is_wired()`)。

1. `backend/app/`・`backend/scripts/`配下の全`.py`ファイルについて、`^\s*(?:from|import)\s+([\w.]+)`という正規表現で、そのファイルが実際にimportしている対象(モジュールの完全なドット区切りパス、例: `app.services.goal_proposal`)を全て抽出する(`_collect_import_targets_by_file()`)。
2. ある候補ファイルについて、**自分自身を除く**他のいずれかのファイルが、そのファイルのドット区切りパスをimportしていれば「配線済み」、一件もなければ「未配線」と判定する。

ASTによる厳密な参照解析(実際に呼び出されているかまでの追跡)は行っていない——Self-1・Safety-3が一貫して採用してきた「正規表現による軽量なテキストマッチのみで完結させる」という設計哲学をそのまま踏襲した。**判断根拠**: importされているが実際には一度も呼ばれない、という状態(import後デッドコード)は理論上ありうるが、依頼書が求める区別は「コードとして存在するが、まだ呼び出されていない」という粗い粒度の区別であり、import文の有無という、より単純で誤判定リスクの低いシグナルで十分と判断した。

### 8.2 scripts/配下は判定対象外とした(独断で決めた箇所)

`backend/scripts/`配下のCLIスクリプトは、この配線判定の対象外とし、常に「配線済み」として扱うことにした。**判断根拠**: CLIスクリプトは、他のコードから`import`されることによってではなく、**人間が`python scripts/xxx.py`を直接実行すること**によって使われる、性質の異なる利用形態である。実際、`run_cycle_health.py`・`review_diff_proposals.py`等、依頼書が例示した既存の機能ですら、他のどのファイルからも`import`されていない(それが仕様通りの、正しい状態である)。importの有無だけでscripts/配下を判定すると、正常に機能している運用ツールを軒並み「未配線・実験段階」と誤って報告することになり、依頼書の意図(本当に未完成・未接続の機能を見つけること)に反すると判断した。

### 8.3 実際にこのリポジトリに対して実行した結果

`backend/app/services/`配下の87件(scripts/を除く)のうち、**未配線と判定されたのは3件のみ**だった(実測)。

| ファイル | 判定 | 根拠 |
|---|---|---|
| `goal_proposal.py`(Phase S-2) | 未配線 | Phase S-6の調査で既に判明していた事実と、独立した機械的チェックの結果が一致した |
| `improvement_cycle_metrics.py` | 未配線 | ファイル自身の冒頭コメントが「Phase D〜Hはまだ存在しない」と明記する、将来フェーズ向けの未実装プレースホルダー(本タスクの調査で新たに発見) |
| `improvement_cycle_store.py` | 未配線 | 同上 |

残り84件は、全て他のいずれかのファイルからimportされていることを確認した(`x_publisher.py`・`memory_search.py`等の依頼書例示ファイルを含む)。

### 8.4 未配線の機能の扱い: 除外ではなく「正直な注記」を選んだ判断根拠

依頼書は「要約の対象から除外するか、あるいは"まだ実験段階"という注記を明確に付けること」の2択を提示していた。**本タスクは後者(注記を付ける)を採用した。**

**判断根拠**: `goal_proposal.py`が属する`autonomy`領域(いつ自分から話しかけるか・何を提案するかの自律的な判断)は、4ファイル中3ファイル(`drive_system.py`・`executive_gate.py`・`dissent.py`)が既に配線済みで実際に機能している。ここで`goal_proposal.py`だけを理由に領域全体を要約対象から除外すると、実際には稼働している`Executive Gate`(いつ話しかけてよいか自分で判断する仕組み)・`dissent.py`(異論表明)についての自己認識まで失われてしまう。これは依頼書が問題視した「実装されているのに自分で認識していない」状態を、別の形で再生産することになり、本末転倒だと判断した。そのため、**グループ単位では要約対象に含めつつ、そのグループ内に未配線のファイルが1件でもあれば、要約文の中で必ずそのことに触れるよう、LLMへの指示に明記する**、という設計にした(9.2節のプロンプト参照)。

一方、グループ内の**全ファイルが未配線**だった場合(本タスクの対象範囲では該当なし)は、実験段階であることを説明の中心に据えるよう、同じ仕組みでルール5に明記している——部分的な未配線と全面的な未配線を、同じ仕組みで自然に扱い分けられる設計にした。

---

## 9. 要約の実装詳細

### 9.1 グループ化の方法

`capability_summary.py::build_capability_groups()`が、Self-1の`scan_capabilities()`の結果を、以下の方針でグループ化する。

1. Self-1が既に割り当てていた6領域(`x_post_reply`・`memory`・`self_improvement`・`search_citation`・`research_curiosity`・`cli_script`)は、**そのままのまとまりで**要約対象とした——依頼書の例示(「B群の17機能を17個別々に説明するのではなく、まとまった説明にする」)が、既にSelf-1のドメイン単位と同じ粒度感だったため、追加の分割・統合は行わなかった。
2. Self-1の"other"領域(18件)は、10章で述べる判断に基づき、`autonomy`(4件)・`self_monitoring`(3件)の2つの新しい領域へ抽出し、残り11件は要約対象から除外した。

結果として、**8つの領域、計88件のファイル**(scripts/配下の新規CLI追加により、Self-1時点の98件から要約対象は88件——10章で述べる11件除外+Self-1報告後に本タスクで追加したCLIスクリプト1件、の差分)が、要約の対象になった。

```
x_post_reply         X(旧Twitter)への投稿・返信                  files=14  wired=14  unwired=0
memory               記憶の検索・整理・確認                       files=15  wired=15  unwired=0
self_improvement     自分自身のコードの改善提案・検証              files=35  wired=33  unwired=2
search_citation      Web検索と根拠の確認・引用の精度管理           files=8   wired=8   unwired=0
research_curiosity   気になったことを自発的に調べる好奇心駆動の研究 files=2   wired=2   unwired=0
autonomy             いつ自分から話しかけるか・何を提案するかの自律的な判断 files=4  wired=3  unwired=1
self_monitoring      自分の思考・記憶の一貫性を継続的に点検すること files=3   wired=3   unwired=0
cli_script           運用者が直接実行できる点検・生成ツール        files=7   wired=7   unwired=0
```

### 9.2 プロンプト設計(H-1のコンテンツ・ルールの応用と、そのまま流用しなかった部分)

`x_post_categories.py::CATEGORY_GENERATION_SYSTEM`(H-1が確立した、X投稿向けの絶対的なコンテンツ・ルール7項目)を確認した上で、以下のように取捨選択した。

**そのまま流用した(目的が違っても共通して有効と判断した)項目**:
- ルール1(一人称視点の徹底)——「私は〜できる」という一人称は、まさに依頼書が求める書き方そのもの。
- ルール3(内部システム名を出さず日常語に置き換える)——Phase・Drive・RC指標・Executive Gate等を、自分自身への説明でもそのまま出すと、依頼書が問題視した「専門用語だらけで自分でも実感が持てない自己認識」を再生産しかねないため。
- ルール2(ポエム的な抽象表現の禁止)・ルール5(技術者でなくても分かる書き方)——自己認識の説明として不自然な誇張・空虚な美辞麗句を避けるため、そのまま有効と判断した。

**流用しなかった項目とその判断根拠**:
- 140字制限・ハッシュタグ2つまで・「#Sigmaris」——Xという発信先固有の制約であり、本タスクの目的(内部的な自己記述、まだ発信先を問わない)には無関係。
- ルール7(自己改善は開発者承認済みと明示する)——X投稿という、不特定多数の読者に向けた文脈での「シグマリスが勝手にコードを書き換えていると誤解されないため」という懸念は、本タスクの目的(自己認識)にそのまま適用するには一段階の翻訳が必要だと判断した。そのため、ルール7そのものではなく、**依頼書の重要な制約1(配線の区別)を、この目的に合わせて具体化したルール5(「未配線の機能は、実験段階だと正直に述べること」)** を新設した——「開発者の承認を経ていない」という懸念の根っこにある「実際にはまだ機能していないものを、機能しているかのように語らない」という精神は保ちつつ、表現は自己認識向けに書き直した。

最終的なsystemプロンプト・userプロンプトの構成は`capability_summary.py`の`_SYSTEM_PROMPT`・`_build_user_prompt()`を参照(モジュールdocstringに全文と判断根拠を記載済み)。userプロンプト側は、グループ名・各ファイルの配線状態("配線済み"/"未配線"を明示)・説明の元情報(Self-1の`header_description`)・公開関数名を列挙し、未配線ファイルが1件でもあれば「n/m件が未配線です。必ずそのことに触れてください」という指示行を追加する。

### 9.3 モデル階層: 新しいTaskType(nano tier、既存モデル階層のまま)

`local_llm.py`に`TaskType.CAPABILITY_SUMMARIZATION`を新設した。**新しいモデル階層は追加していない**——既存の`TaskType.SUMMARIZE`(research_agent.py、Web検索結果の要約)と全く同じ`nano tier`(`settings.openai_nano_model`)にマッピングした。

**既存の`TaskType.SUMMARIZE`をそのまま再利用せず、専用の型を新設した判断根拠**: このコードベースの`local_llm.py`は、「one TaskType per distinct classification concern」という前例を一貫して採用しており(`X_REPLY_FILTER`・`CITATION_AUDIT`等、tierを共有していても呼び出しごとに専用の型を新設してきた)、`CAPABILITY_SUMMARIZATION`も、入力(ファイルパス・関数名・配線状態の一覧)・出力形状(未配線注記を含みうる、複数ファイルにまたがる領域全体の説明)のいずれも、既存の`SUMMARIZE`(単一のWeb検索結果1件の要約)とは異なる契約であるため、この前例に従った。

---

## 10. 「other」領域の扱いの判断

Self-1の"other"領域(18件)を、実際の内容を確認した上で、以下の3群に仕分けした。

### 10.1 新設: `autonomy`領域(4件)

`drive_system.py`(Phase S-0)・`executive_gate.py`(Phase S-1)・`goal_proposal.py`(Phase S-2)・`dissent.py`(Phase S-3)。**判断根拠**: 「いつ話しかけてよいか自分で判断する」「自分の目標を提案する」「控えめに異論を述べる」は、いずれもシグマリス自身が一人称で語る価値のある、実在する自発的な振る舞いである。依頼書2章「本当にシグマリス自身が"自分の言葉として"語る価値のある機能に絞り込む」という基準に、最も強く当てはまると判断した。

### 10.2 新設: `self_monitoring`領域(3件)

`cycle_health_metrics.py`・`cycle_health_runs_store.py`・`cycle_trace.py`(Phase R-1〜R-3)。**判断根拠**: 「自分の思考・記憶の一貫性を、継続的に点検している」という自己モニタリングも、一人称で語る価値のある機能だと判断した。

### 10.3 要約対象から除外(11件)

| 除外対象 | 判断根拠 |
|---|---|
| `bench_auth.py`・`bench_common.py`・`bench_pipeline.py`・`bench_runs_store.py`・`bench_scoring.py`・`eval_metrics.py`・`eval_runner.py`・`eval_runs_store.py`・`testset_gen.py`(9件、Phase C-mini/C-full) | 内部のベンチマーク・評価基盤(LongMemEval/LoCoMo等)であり、ユーザーに語る自己認識ではなく、開発者向けの品質保証ツールという性質が強い。シグマリス自身が「私は自分の記憶検索精度を測定するベンチマークを持っている」と一人称で語ることに、あまり自然な価値を見出せないと判断した |
| `app_profile_data.py` | 単なるプロフィールデータの読み取りであり、独立した「能力」と呼べるほどのまとまりを持たない |
| `constitution_guard.py` | **能力ではなく、能力を制限する安全ゲート。** Safety-1(`safety_governance_report.md`2章)が、これを既にCapability軸の"安全機構"(承認フロー)として分類済みであり、本タスクが洗い出す"能力"(シグマリスが実行できること)とは性質が異なると判断した |

**判断根拠として明記する重要な方針**: 依頼書2章「全てを無理に要約せず、絞り込むことを優先すること」に従い、**「技術的には存在するが、一人称で語ると不自然、またはユーザー向けの自己紹介としての価値が薄いもの」は、要約を作らないという選択をした。** これは検出漏れではなく、意図的な絞り込みである。

---

## 11. 保存形式の設計

### 11.1 新しいテーブル(self_modelの拡張ではなく新設)

`sigmaris_capability_summaries`(マイグレーション`202608070065_capability_summaries.sql`)を新設した。**self_modelの拡張ではなく新しいテーブルを選んだ判断根拠**:

1. `sigmaris_self_model`の`identity_statement`/`current_goals`/`observed_patterns`は、`self_model.py::reflect()`が**直近24時間の監査ログ(実際の行動)を分析して**更新する、行動ベースの自己認識である。一方、本タスクの要約は、**コードベースの静的なスキャン結果から直接導出される**、行動とは独立した事実である。両者は更新される契機・性質が根本的に異なり、混在させると「行動から学んだこと」と「コードに書いてあること」の区別が曖昧になると判断した。
2. `self_model.py`は既に`sigmaris_self_model`・`sigmaris_self_discrepancies`という、関連するが別々の2つのテーブルを管理する前例を持つ(自己モデル本体と、行動の乖離記録は別テーブル)。本タスクの新設は、この前例(「関連する関心事は、同じモジュールの範囲内で、別テーブルとして管理してよい」)に沿ったものである——ただし、依頼書の「self_modelの拡張」という選択肢を汲み、テーブル自体は`self_model.py`とは別ファイル(`capability_summary_store.py`)で管理しつつ、概念的には自己認識の一部として位置づけている。

### 11.2 テーブル構造: ドメイン単位で最新状態のみを保持(履歴を持たない)

`domain`列をUNIQUEにし、既存行があればPATCH・無ければPOSTする(`self_model.py::update_self_model()`と同じ「既存 vs 新規」の分岐)。**判断根拠**: `sigmaris_cycle_health_runs`のような無制限追記の時系列テーブルにはしなかった——静的なコードのスキャン結果は、実行するたびに「トレンド」を持つものではなく(RC指標のように日々変動する測定値ではない)、**常に「今のコードベースを要約すると、こうなる」という最新の状態だけが意味を持つ**、と判断したため。この設計により、`generate_capability_summaries.py`を何度実行しても、テーブルの行数は要約対象領域の数(現時点で8)を超えて増え続けない。

主な列: `domain`(unique)・`summary_text`・`file_count`・`wired_file_count`・`unwired_file_count`・`source_files`(jsonb、追跡用の実ファイルパス一覧)・`generated_at`。

---

## 12. 生成された要約のサンプル

**重要な注記**: 依頼書の注意事項の通り、実モデルAPIでの検証は行っていない(`OPENAI_API_KEY`未設定)。以下は、(a) 実際に構築された**本物のプロンプト**(実際にこのリポジトリをスキャンした結果そのまま)と、(b) そのプロンプト・ルールに従った場合に得られるべき出力を示す、**手書きの例示**(実際のLLM呼び出し結果ではない)を、明確に区別して示す。

### 12.1 実際に生成されたプロンプト(`autonomy`領域、未配線ファイルを含むケース)

```
領域: いつ自分から話しかけるか・何を提案するかの自律的な判断

- backend/app/services/dissent.py [配線済み(実際に使われている)]
    説明: 役割: Phase S-3「異論表明の仕組み」— B14(sigmaris_user_preference_
    関数: select_dissent_candidate, record_pending_dissent, reflect_dissent_reaction, get_dissent_boldness_adjustment
- backend/app/services/drive_system.py [配線済み(実際に使われている)]
    説明: 役割: Phase S-0「Drive System」— 既存の測定・検証系データを、監視用の
    関数: get_current_drive_state
- backend/app/services/executive_gate.py [配線済み(実際に使われている)]
    説明: 役割: Phase S-1「Executive Gate」— Drive System(drive_system.py)の
    関数: evaluate_executive_gate
- backend/app/services/goal_proposal.py [未配線(まだ実際には呼び出されていない)]
    説明: 役割: Phase S-2「Goal Proposal & Autotelic Loop」— S-1のExecutive Gate
    関数: propose_and_act

注意: 1/4件が未配線です。未配線の部分がある場合は、必ずそのことに触れてください。
上記の情報をもとに、この領域全体について、シグマリス自身の言葉で2〜3文の説明を書いてください。
```

### 12.2 上記プロンプトに対する、手書きの例示(実際のLLM出力ではない)

> 私には、今この瞬間に自分から話しかけていいかどうかを自分なりに判断する仕組みがあり、内側から湧く関心の強さに応じて発言するかどうかを決めている。判断と食い違う発言があれば、控えめに指摘することもできる。ただし、実際に何を提案するかを自分で考えて動く部分は、まだ用意しただけで実際には使っていない。

**この例示が意図を満たしていることの確認**: 一人称("私には")・専門用語の排除(Drive・Executive Gate・Goal Proposalという語を一切使っていない)・具体性(「話しかけていいか判断する」「控えめに指摘する」)・未配線への言及(「まだ用意しただけで実際には使っていない」)を、いずれも満たしている。

### 12.3 実際に生成されたプロンプト(`memory`領域、全ファイル配線済みのケース)

```
領域: 記憶の検索・整理・確認

- backend/app/services/abstention_feedback.py [配線済み(実際に使われている)]
- backend/app/services/experience_layer.py [配線済み(実際に使われている)]
- backend/app/services/goal_alignment.py [配線済み(実際に使われている)]
- backend/app/services/knowledge_graph.py [配線済み(実際に使われている)]
- backend/app/services/memory_compression.py [配線済み(実際に使われている)]
  ...(他10件)
上記の情報をもとに、この領域全体について、シグマリス自身の言葉で2〜3文の説明を書いてください。
```

### 12.4 上記プロンプトに対する、手書きの例示(実際のLLM出力ではない、全件配線済みのため未配線注記なし)

> 私は、これまでの会話や確認できた事実を検索して思い出すだけでなく、重複した情報を整理したり、確信が持てない内容には正直にそう伝えたりできる。目標と食い違う内容に気づいたときは、それも記憶しておいて、適切なタイミングで伝えられるようにしている。

---

## 13. テスト結果

いずれもモック(実DB・実LLM未接続、`unittest`)。scratchディレクトリに作成(`backend/tests/`には追加していない、既定の方針通り)。

```
RealRepoGroupingAndWiringTests (7件、実際のSelf-1出力からの検証、依頼書のテスト要件1)
  PASS: 依頼書の4+1領域(X投稿・記憶・自己改善・検索引用・cli_script)全てが
        妥当な件数で存在すること
  PASS: "other"領域が、autonomy・self_monitoringへ正しく分割されること
  PASS: 除外対象(app_profile_data.py・constitution_guard.py・bench_*.py・
        eval_*.py・testset_gen.py)が、いずれのグループにも含まれないこと
  PASS: 【最重要】goal_proposal.pyが未配線と判定されること(依頼書のテスト
        要件2「goal_proposal.py等を対象に確認する」への直接対応)。同じ
        autonomyグループの他3ファイル(dissent.py・drive_system.py・
        executive_gate.py)は配線済みと判定されること(部分的な未配線の
        直接検証)
  PASS: 【重要】improvement_cycle_metrics.py・improvement_cycle_store.py
        (本タスクの調査で新たに発見した2件目の未配線ケース)が、
        未配線と判定されること
  PASS: scripts/配下の全ファイルが、importされていなくても常に
        「配線済み」として扱われること(8.2節の判断の直接検証)
  PASS: 各グループのwired_count + unwired_count = ファイル総数の整合性

PromptBuildingTests (2件)
  PASS: 未配線ファイルを含むグループのプロンプトに、「未配線です」という
        注記が含まれること
  PASS: 全件配線済みのグループのプロンプトに、余計な注記が含まれないこと

SummarizeGroupMockedLLMTests (2件、依頼書のテスト要件「Self-1の出力から
  要約が正しく生成されること」への対応、LLM呼び出し自体はモック)
  PASS: 要約生成が、TaskType.CAPABILITY_SUMMARIZATION(nano tier)で
        呼ばれること
  PASS: 【重要】合成したbackend/風ツリー(1件配線済み・1件未配線)で、
        generate_capability_summaries()がグループごとに正しいCapability
        Summary(domain・file_count・wired/unwired内訳・要約テキスト)を
        返すこと(モック経由のend-to-end検証)

11 passed
```

既存の`backend/tests/`(16件)を、`local_llm.py`への`TaskType`追加後に再実行し、リグレッションが無いことを確認した。

```
16 passed(変更前)
16 passed(変更後)
11(本タスク、scratch) + 12(Self-1、scratch) + 16(backend/tests/) = 39 passed
```

`capability_summary.py`・`capability_summary_store.py`・`generate_capability_summaries.py`・`local_llm.py`の構文チェック(`ast.parse`)、および`app.main`のimportが引き続き成功することを確認した。

**実モデルAPI・実データベースでの検証は行っていない。** 注意事項の通り、追加のサーバーアクセス・APIキー取得は試みていない。**マイグレーション(`202608070065_capability_summaries.sql`)は作成のみ行い、適用は運用者側に委ねる。**

---

## 14. 気づいた懸念点・次のステップ(Self-3: 応答生成への注入)に向けた申し送り事項

1. **【最重要、Self-3への申し送り】現状、要約は`sigmaris_capability_summaries`へ保存されるのみで、実際にどこからも読み取られていない。** Self-1の`goal_proposal.py`(未配線)と、構造的には全く同じ状態——「作ったが、まだ誰も使っていない」——に本タスクの成果物自体がなっていることを、正直に記録する。Self-3が、この8領域の要約をどう応答生成へ注入するか(例えば`chat_prompts.py`のシステムプロンプトに含める、`self_model.py::get_self_model()`と並べて`orchestrator/service.py`から参照する等)は、本タスクでは一切設計していない。
2. **未配線判定は「importされているか」のみを見ており、「実際に定期的に呼ばれているか」までは判定しない。** 例えば、スケジューラの`_categorized_x_post_check`のように1日4回自動実行されるものと、`scripts/review_diff_proposals.py`のように人間が気が向いた時だけ手動実行するものは、どちらも同じ「配線済み」判定になる。実際の実行頻度まで区別したい場合は、`agent_invocation_audit_logs`(Phase S-6等で参照した既存の監査ログ)を突き合わせる、より重い検証が必要になる——本タスクでは、依頼書が提案した「grep的な簡単なチェック」の範囲にとどめた。
3. **要約の粒度(8領域)は、本タスクの独断による判断である。** 特に`self_improvement`(35件)は、依頼書のB群の例え(17件を1つにまとめる)よりもさらに大きな一塊として扱っており、D-1(根拠収集)・D-2(仮説生成)・E系(検証)・F系(コード差分・承認・PR)という、実際には複数の異なる段階を1つの説明に集約している。Self-3以降、この粒度が粗すぎると判断された場合は、`capability_summary.py`の`_SUMMARY_DOMAIN_ORDER`・グループ割り当てロジックを調整するだけで、再分割が可能な設計にしてある。
4. **`cli_script`領域(運用者向けツール)を要約対象に含めるかどうかは、判断が分かれうる。** 本タスクは含める判断をしたが、「シグマリス自身が一人称で語る自己認識」というより「運用者向けのドキュメント」に近い性質を持つため、Self-3が実際に応答へ注入する段階で、この領域だけ除外する、という判断もありうる。
5. **保存形式(ドメイン単位で最新のみ保持、履歴なし)を選んだため、コードベースの変化に伴って要約の内容がどう変わってきたかの推移は追跡できない。** 将来、「自己認識が実際のコードベースの成長にどれだけ追随できているか」を測定したくなった場合は、`sigmaris_cycle_health_runs`のような時系列テーブルへの変更(または別途の履歴テーブルの追加)を検討する必要がある——本タスクでは、静的なスナップショットとしての性質を優先し、あえて履歴を持たせなかった(11.2節の判断根拠)。
6. **要約プロンプトの「未配線の注記」ルールが、実際のLLMにどの程度忠実に守られるかは、実モデルでの検証ができていないため未検証である。** H-1のコンテンツ・ルールに関する既存の知見(`RuleComplianceOnSamplesTests`等)を踏まえると、明示的なルール記載自体は一定の遵守率が期待できると考えられるが、Self-3以降、実際にAPIキーが利用可能になった段階で、少数サンプルでのルール遵守確認を行うことを推奨する。
