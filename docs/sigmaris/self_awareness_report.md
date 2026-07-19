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

---

# Self-3 実施報告: 応答生成への注入、及び定期的な更新(自己認識の自動更新、最終段階)

**作業ブランチ:** `self-3-capability-injection`(mainから新規作成)
**範囲:** Self-2が`sigmaris_capability_summaries`へ保存した一人称の日本語要約を、(1)実際の応答生成へ選択的に注入し、(2)Self-1・Self-2を既存の定期実行の仕組みへ組み込んで週次で自動更新されるようにする。これをもって、Self-1〜3(自己認識の自動更新)全体が完了する。

---

## 15. 応答生成への注入方法

### 15.1 注入経路の特定

着手前に、実際にチャット応答が生成される経路を調査した。本番で使われる経路(`/api/orchestrator/chat`)は、`orchestrator/service.py::run_orchestrator_chat()`/`run_orchestrator_chat_stream()`が、`self_model_context`・`goal_alignment_context`等、複数の`_build_*_context()`関数の出力を`orchestrator/schedule_agent_client.py::_build_system_override()`で1本の文字列(`system_override`)に結合し、HTTP経由(ループバック、`/api/agent/chat/complete`)で`chat.py::run_chat_completion()`へ渡す。そこで`system_override`は`chat.py`の`system`引数となり、最終的に`chat_prompts.py::build_system_prompt()`の`base_system`引数として、実際のOpenAI呼び出し用プロンプトへ組み込まれる。

この経路の**どこにも新しい注入ポイントを新設せず**、既存の`_build_self_model_context()`・`_build_goal_alignment_context()`等と全く同じパターン(=`_build_capability_context()`という新しい純粋関数を追加し、`_build_system_override()`の引数を1つ増やす)で統合した。

### 15.2 選択的注入を採用した判断根拠

依頼書1章「必要に応じて(例えば"自分は何ができるか"に関連する質問が検出された場合にのみ)注入するという選択的な注入も検討すること」に対し、**選択的注入を採用した(全ターン常時注入はしない)。**

判断根拠:

1. **`_MAX_SYSTEM_OVERRIDE_CHARS = 4000`という既存の上限**(`schedule_agent_client.py`)に対し、8領域分の要約(1領域あたり2〜3文)を毎ターン無条件に追加すると、他の既存コンテキスト(自己モデル・判断傾向・目標整合性等)を圧迫し、`_trim_context()`による既存コンテキストの切り詰めを誘発しかねない。
2. **多くの会話ターンでは、シグマリス自身の機能一覧は本質的に無関係な情報である。** 「明日の予定を入れて」のようなターンにまで機能一覧を注入することは、無駄なトークン消費であり、H-1が既に確立した「聞かれていないことは言わない」という応答スタイルの精神にも反すると判断した。

### 15.3 検知方法: 新しいLLM呼び出しを追加しない、キーワード一致方式

`capability_summary.py::detect_capability_question()`を新設した。**軽量なキーワード一致のみで判定し、新しいLLM分類呼び出しは追加していない。**

**判断根拠**: `chat_routing.py::classify_chat_intent()`という、毎ターン発生する既存のnano-tier意図分類が既に存在するが、その分類軸(`event_lookup`/`mobility_plan`/`schedule_import`/`calendar_write`/`sync_control`)は、いずれも予定管理という別の関心事のためのものであり、「自分は何ができるか」という自己参照的な質問は、この分類のどのカテゴリにも自然に対応しない。新しいLLM呼び出しをもう1つ毎ターン追加するより、`chat_routing.py`の`CALENDAR_WRITE_KEYWORDS`等が既に採用している「軽量なキーワード一致」という、このコードベース一貫の設計哲学をそのまま踏襲する方が、依頼書「既存資産の再利用」の精神に沿うと判断した——追加のLLM呼び出し・追加のレイテンシ・追加のコストを、一切発生させない。

キーワードには、依頼書の例そのもの(「ツイート」)に加え、「何ができる」「できること」「あなたの機能」等、一般的な自己参照的表現を含めた(全文は`capability_summary.py`参照)。過検知・見逃しの両方がありうるヒューリスティックであることは、Safety-3・Self-1が採用してきた同種の設計と同じ前提を踏襲する。

### 15.4 実装フロー(`_maybe_build_capability_context()`)

```
1. detect_capability_question(最新のユーザー発話) が False
   → 即座に None を返す。DBアクセス・キャッシュ参照は一切発生しない。
2. True の場合のみ、_cached_capability_summaries() で
   sigmaris_capability_summaries を取得(キャッシュ経由、16章参照)。
3. _build_capability_context() で、取得した全ドメインの要約を
   「[シグマリス自身の機能一覧(自己認識)]」という見出し付きの
   箇条書きへ整形する。
```

`run_orchestrator_chat()`・`run_orchestrator_chat_stream()`の両方(非ストリーミング・ストリーミングの双子関数)に、既存の`persona_context`・`relationship_duration_context`等と並ぶ形で、同じパターンで追加した。

---

## 16. キャッシュへの影響確認結果

### 16.1 Phase A2の並び順原則への対応: `persona_context`の直後に配置

`_build_system_override()`内で、`capability_context`を**`persona_context`の直後、`user_profile_context`より前**に配置した。

**判断根拠**: 依頼書1章「能力の要約は頻繁には変わらない性質のものであるため、"時々更新される、準固定の部分"として扱えないか検討すること」に対応した。Self-2の要約は、週次の`self_awareness_update`ジョブ(17章)でのみ更新されるため、更新頻度は`persona_context`(persona.mdの手動編集時のみ変化)に次いで安定しており、`self_model_context`(日次反省で更新されうる)・`preference_patterns_context`(週次だが会話内容に応じて変わりうる)よりも安定している。Phase A2が確立した「更新頻度が低いものほど前方に置く」という原則に、最も忠実な位置を選んだ。

### 16.2 実測による検証(3点)

`_build_system_override()`を直接呼び出し、以下を実測した(16章参照、テストで直接検証)。

1. **`capability_context`が`None`(選択的注入が発火しない、大多数のターン)の場合、既存の呼び出し(`capability_context`引数を渡さない場合)と、出力が完全にバイト一致すること**を確認した。既存の挙動(=大多数のターン)に、一切の変化・退行が無いことの直接証明。
2. **`capability_context`が実際に存在する場合でも、`persona_context`より前の部分(プレフィックス)は一切変化しないこと**を確認した(共有プレフィックス長 ≥ `persona_context`の長さ)。`capability_context`は、既存のどのコンテキストより前には挿入されないため、それより前のキャッシュ可能なプレフィックスを短くすることは無い。
3. **既存の`_MAX_SYSTEM_OVERRIDE_CHARS = 4000`の切り詰めが、`capability_context`を含めた場合でも引き続き機能すること**を確認した(既存の`ScheduleAgentClientTests::test_system_override_is_capped_for_agent_request_schema`は無変更のまま引き続きパスすることも確認済み)。

### 16.3 「毎ターン発生する追加コスト」について

選択的注入により、**`detect_capability_question()`自体(文字列の部分一致、DBアクセスなし)は毎ターン発生するが、これはコストと呼べるほどの処理ではない**(既存の`CALENDAR_WRITE_KEYWORDS`等と同じ計算量)。DBアクセス(`_cached_capability_summaries()`)は、キーワードが一致したターンにのみ発生し、かつ24時間キャッシュ(16.4節)により、同一プロセス内では実質的に週1回程度の頻度に抑えられる。

### 16.4 キャッシュTTLの設計(既存の5分キャッシュとは別枠)

`orchestrator/service.py`の既存の`_cache_get()`/`_cache_set()`(5分TTL、`facts`等の毎ターン変わりうるデータ用)とは別に、**`_CAPABILITY_CACHE_TTL = 86400.0`(24時間)という、大幅に長いTTLを新設した**。既存の`_cache_get()`にオプション引数`ttl`を追加する形で拡張し(デフォルト値は既存の5分のまま、既存の全呼び出し元は無変更で動作)、この新しいキャッシュ専用のTTLを渡せるようにした。

**24時間を選んだ判断根拠**: Self-2の要約は週次でしか変わらないため、理論上は「次の週次ジョブまでキャッシュしっぱなし」でも問題ないが、依頼書の「日次のキャッシュのような扱い」という例示に沿い、日次相当のTTLを採用した。**加えて、週次ジョブ(17章)自身が、更新直後に`invalidate_capability_summary_cache()`を呼び出し、このTTLの経過を待たずにキャッシュを即座に破棄する**ため、実運用では「TTLが切れるのを待って古い要約を返し続けてしまう」という状況は基本的に発生しない——24時間というTTLは、あくまで安全側のフォールバック上限という位置づけである。

---

## 17. 定期実行の頻度・時間帯の設定、判断根拠

### 17.1 頻度: 週1回(日曜)

依頼書2章「機能が頻繁に追加される日々の開発のペースとコストのバランスを考慮し提案すること」に対し、**週1回**を選んだ。

**判断根拠**:
1. このセッション自体の実績(Safety-1〜3、Phase S-5・S-6、Self-1〜3)を振り返ると、1つのPhaseが完了するペースは数日〜1週間に1件程度であり、毎日再スキャンしても差分が無い日が大半になる。一方、月1回では、「今日、何ができるか」との乖離が最大で1か月近く放置されうる——これは依頼書の背景そのもの(自己認識のズレ)を再発させかねない。
2. 既存の`experience_analyze`・`decision_analyze`・`knowledge_graph_extract`・`preference_pattern_extract`等、Phase RやB群の「振り返り・集約」系のバッチジョブが、いずれも同じ「週次(日曜)」という頻度規約を既に採用している。Self-1・Self-2も「コードベース全体を俯瞰して要約し直す」という、性質の近い振り返り系のバッチであるため、既存の頻度規約にそのまま合わせることが、運用上の一貫性の観点で妥当と判断した。
3. コスト面では、Self-2のLLM呼び出しは、nano tierで1回あたり8ドメイン分(現時点)——日次実行でも致命的なコストにはならないが、「頻繁な開発ペースに対して過剰でも過少でもない」バランスとして、既存の週次バッチと揃える方針を優先した。

### 17.2 時間帯: 日曜5:55(既存ジョブとの重複回避)

既存の日曜早朝バッチ(4:00の`experience_analyze`から始まり、5:45の`safety_governance_scan`まで)の**直後**、かつ毎日6:15に実行される`curiosity_search`の**前**という、既存のスケジュールが既に持っていた「5:45〜6:15」という30分の空き時間に、**5:55**として配置した。`safety_governance_scan`から10分の余裕、`curiosity_search`まで20分の余裕を残す——既存のジョブ群が採用してきた「5〜15分間隔」という配置慣習とも整合する。

実際に、他のいずれのジョブも日曜5:55には登録されていないことを、既存の全`add_job()`呼び出しを列挙して確認した(19章のテストで直接検証)。

### 17.3 実装: 既存パターンをそのまま踏襲

`_self_awareness_update()`ジョブ(`proactive/scheduler.py`)は、既存の`_safety_governance_scan()`等と全く同じ、try/except一段構えのfire-and-forgetパターンを踏襲した。Self-1(`generate_capability_summaries()`)を呼び、返ってきた各ドメインの要約を`record_capability_summary()`でDBへ記録し、最後に`orchestrator/service.py::invalidate_capability_summary_cache()`を呼んでプロセス内キャッシュを即座に破棄する。

---

## 18. 動作確認の結果

実モデルAPIでの検証は行っていない(注意事項の通り、追加のAPIキー取得は試みていない)。依頼書「テスト環境での確認でよい」に従い、**実際の`_build_system_override()`・`_maybe_build_capability_context()`を、モックしたDB層(Self-2が生成しうる、現実的なX投稿機能の要約)で駆動する、end-to-endのシミュレーションテスト**で確認した。

### 18.1 シミュレーションの入力

Self-2が実際に生成しうる、H-1〜H-3(X投稿・返信システム)の要約の一例を、`sigmaris_capability_summaries`から取得したものとして与えた:

```python
fake_summaries = [
    {
        "domain": "x_post_reply",
        "summary_text": "私は自分の言葉でX(旧Twitter)に投稿したり、来た返信に反応したりする仕組みを持っている。",
    },
]
messages = [{"role": "user", "content": "今日は何をツイートする予定?"}]
```

### 18.2 実際の処理結果

1. `detect_capability_question("今日は何をツイートする予定?")` → **True**(「ツイート」キーワードに一致)。
2. `_maybe_build_capability_context(messages)` → `_cached_capability_summaries()`を実際に呼び出し(モック経由)、以下の`capability_context`を生成:
   ```
   [シグマリス自身の機能一覧(自己認識)]
   - 私は自分の言葉でX(旧Twitter)に投稿したり、来た返信に反応したりする仕組みを持っている。
   ```
3. この`capability_context`を含めて`_build_system_override()`を実際に呼び出した結果、生成された`system_override`(実際にOpenAIへ渡されるプロンプトの一部になる文字列)に、**「X(旧Twitter)に投稿」という、H-1〜H-3の機能への言及が実際に含まれること**を確認した。

**これにより、「今日、何をツイートする予定か」という質問に対し、シグマリスが実際に呼び出すプロンプトの中に、既に実装済みのX投稿機能への言及が含まれる状態になっていることを、機械的に確認できた。** 実際にLLMがこの文脈を踏まえてどう返答するかは、実モデルでの検証が必要であり未検証だが、**「自分のX投稿機能を認識していない」という、依頼書の背景で述べられた問題の直接的な原因(=プロンプトにその情報が存在しなかったこと)は、構造的に解消されている**と言える。

### 18.3 対照確認: 無関係な質問では注入されないこと

「明日の天気を教えて」という無関係な質問では、`_cached_capability_summaries()`が一切呼ばれず(DBアクセスなし)、生成された`system_override`に「シグマリス自身の機能一覧」という見出しが一切含まれないことも、同じテストで確認した(15.2節の選択的注入の設計が、意図通り機能していることの直接証拠)。

---

## 19. テスト結果

いずれもモック(実DB・実LLM未接続、`unittest`)。scratchディレクトリに作成(`backend/tests/`には追加していない、既定の方針通り)。

```
DetectCapabilityQuestionTests (3件)
  PASS: 【最重要】依頼書の例文そのもの("今日、何をツイートする予定か教えて")が
        検出されること
  PASS: 一般的な自己参照的質問("あなたには何ができるの?"等)が検出されること
  PASS: 通常の会話("明日の予定を入れて"等)が検出されないこと(過剰検知の防止確認)

BuildCapabilityContextTests (3件)
  PASS: 全ドメインの要約が、一人称の箇条書きとして整形されること
  PASS: 要約が0件の場合Noneを返すこと
  PASS: summary_textが空白のみの行はスキップされること

MaybeBuildCapabilityContextTests (2件、選択的注入の直接検証)
  PASS: 【重要】質問が検出されない場合、DBアクセス(_cached_capability_
        summaries)が一切発生しないこと
  PASS: 質問が検出された場合、DBアクセスが発生し、正しくcapability_context
        が構築されること

CacheTTLAndInvalidationTests (2件)
  PASS: 24時間キャッシュにより、2回連続の呼び出しでDBアクセスが1回のみに
        なること
  PASS: 【重要】invalidate_capability_summary_cache()を呼ぶと、次回の呼び出しで
        必ず新しい値が再取得されること(週次ジョブによる即時反映の直接検証)

PhaseA2CacheSafetyTests (3件、依頼書要件2「Phase A2のキャッシュ構造に
  悪影響を与えないこと」への直接対応)
  PASS: 【最重要】capability_contextが無い場合(大多数のターン)、既存の
        呼び出しとバイト単位で完全に一致すること(退行が無いことの直接証明)
  PASS: 【最重要】capability_contextが有る場合でも、persona_contextまでの
        プレフィックスが変化しないこと
  PASS: 既存の4000文字上限が、capability_context込みでも引き続き機能すること

SchedulerJobRegistrationTests (1件、依頼書要件4への直接対応)
  PASS: self_awareness_updateジョブが登録され、既存のどのジョブとも
        日曜5:55で重複しないこと

EndToEndSimulationTests (2件、依頼書のテスト要件「X投稿機能についての
  質問で正しい応答が生成されることの確認」への直接対応、18章参照)
  PASS: 【最重要】"今日は何をツイートする予定?"という質問で、実際に
        構築されたsystem_overrideに、X投稿機能への言及が含まれること
  PASS: 無関係な質問では、機能一覧への言及が一切含まれないこと

16 passed
```

既存の`backend/tests/`(16件、`test_service.py`・`test_schedule_agent_client.py`を含む)を、本タスクの変更前後で再実行し、**一切のテスト修正なしで全てパスすることを確認した。**

```
16 passed(変更前)
16 passed(変更後)
```

**既存テストが無修正でパスした理由(設計上の裏付け)**: `test_service.py`の既存テストは、いずれもメッセージ内容が`{"role": "user", "content": "hello"}`等、自己参照的なキーワードを一切含まない。選択的注入の設計(15.2節)により、これらのテストでは`detect_capability_question()`が常にFalseを返し、本タスクで追加した新しいDBアクセス経路(`_cached_capability_summaries()`)が一切実行されない——そのため、既存テストのモック構成(`_patch_common()`)に、本タスクのための追加のモックを一切加える必要がなかった。`test_schedule_agent_client.py`の既存テストも、`capability_context`を渡さないキーワード呼び出しのままであり、新しい引数のデフォルト値(`None`)により無変更で動作する。

```
16(本タスク、scratch) + 11(Self-2、scratch) + 12(Self-1、scratch) + 16(backend/tests/) = 55 passed
```

`orchestrator/service.py`・`orchestrator/schedule_agent_client.py`・`proactive/scheduler.py`の構文チェック(`ast.parse`)、および`app.main`のimportが引き続き成功することを確認した。

**実モデルAPI・実データベースでの検証は行っていない。** 注意事項の通り、追加のサーバーアクセス・APIキー取得は試みていない。**本タスクは新規マイグレーションを必要としない**(Self-2が新設した`sigmaris_capability_summaries`をそのまま読むだけで、新しいテーブル・列は追加していない)。

---

## 20. Self-1〜3全体を通じての振り返り

### 20.1 各タスクの到達点

| タスク | 到達点 | 主な設計判断 |
|---|---|---|
| Self-1 | Safety-3のOR結合ヒューリスティックを応用し、98件の能力候補をコードベースから機械的に洗い出した | 関数名パターンの代わりにファイル名パターンを採用(能力を表す関数名には安全機構ほど狭い共通語彙が無いため) |
| Self-2 | 98件を8領域へグループ化し、配線状態(3件の未配線を発見)を区別した一人称の日本語要約を、nano-tier LLMで生成・保存した | self_modelの拡張ではなく新テーブル(更新契機が根本的に異なるため)。"other"領域を絞り込み、autonomy/self_monitoringを新設、eval/benchmark系は除外 |
| Self-3 | 要約を、既存のコンテキスト注入パターンへ選択的に統合し、週次の自動更新を既存のスケジューラへ組み込んだ | 新しいLLM分類を追加せず、キーワード一致で選択的注入。Phase A2の並び順原則に従い`persona_context`の直後へ配置。24時間キャッシュ+即時invalidateの二段構え |

### 20.2 3タスクを通じて一貫した設計哲学

Safety-1〜3・Phase S全体と同じく、**「新しい重量級の仕組みを一切作らず、既存の資産・既存のパターンを、新しい目的に応用する」という哲学**を、Self-1〜3でも一貫して守った。

- Self-1: Safety-3のスキャナー設計をそのまま応用(新しい静的解析基盤は作らない)
- Self-2: `TaskType.SUMMARIZE`と同じnano tierをそのまま踏襲(新しいモデル階層は作らない)、`self_model.py`が既に持つ「関連するが別の関心事は別テーブル」という前例を踏襲
- Self-3: 既存の`_build_*_context()`パターン・既存の`_cache_get()`/`_cache_set()`・既存のスケジューラのfire-and-forgetパターンを、いずれも新設せずそのまま拡張

結果として、**Self-1〜3を通じて新設されたテーブルは`sigmaris_capability_summaries`の1つのみ**であり、新しい判定アルゴリズム・新しいモデル階層・新しい定期実行基盤は、いずれも一度も作られていない。

### 20.3 依頼書の背景が問題視した状況は、構造的に解消されたか

**「今日、何をツイートする予定か」という質問に対し、シグマリスが実際に呼び出すプロンプトへ、X投稿機能への言及が実際に含まれることを、18章で機械的に確認した。** これは、依頼書が問題視した「実装済みの機能を、シグマリス自身が認識していない」という状態への、直接的な対応になっている。

ただし、以下の点は正直に記録しておく。

1. **選択的注入である以上、`detect_capability_question()`のキーワードに一致しない表現(例えば、依頼書の例文と大きく異なる言い回し)では、注入自体が発生しない。** ヒューリスティックの限界は、Safety-3・Self-1から一貫して受け継いだ前提であり、本タスクで解消したわけではない。
2. **実際にLLMがこの文脈をどう扱うか(要約の内容を正確に踏まえて回答するか、無視してしまわないか)は、実モデルでの検証ができていない。** 構造的にプロンプトへ情報が含まれることは確認したが、それが実際の応答品質にどう反映されるかは未検証のまま申し送る。
3. **8領域のうち、実際に選択的注入で使われるのは「その質問に関連する領域を含む全要約」であり、質問の内容(例: X投稿について)に応じて関連する領域だけに絞り込む、という、より精緻な選択は行っていない。** 現状は「自己参照的な質問だと判定されたら、8領域全ての要約をまとめて注入する」という、粗い粒度の選択的注入である。将来、領域単位でも選択的にする(例えば「ツイート」というキーワードが検出されたら`x_post_reply`領域のみ注入する)ことで、注入する文字数をさらに減らせる可能性がある——本タスクでは、依頼書が「選択的な注入も検討する」と述べた対象を「注入するかどうか」の二値と解釈し、領域単位の絞り込みまでは実装しなかった(判断根拠として明記する)。

### 20.4 今後の課題として残るもの

1. Self-2の申し送り事項3(`self_improvement`領域の粒度が粗い)・4(`cli_script`領域を注入対象に含めるかの判断)は、本タスクでは変更せず、Self-2の判断をそのまま引き継いだ。
2. 20.3節3点目で述べた、領域単位での選択的注入の精緻化。
3. 実モデルAPIでの、要約プロンプトのルール遵守率・実際の応答品質の検証(Self-2・Self-3を通じて未検証のまま)。
4. Self-1の未配線判定(importの有無のみ)・Self-2の除外判断(bench/eval系)は、いずれも本タスクでは見直していない——Self-1〜2が確立した状態をそのまま前提とした。

以上により、Self-1〜3(自己認識の自動更新)は要件をすべて満たし、依頼書の指示通りmainへマージする。

---

# 追加報告: Self-1・Self-2の手動実行(Sigmaris Live・CLIチャット削除の反映)

**本タスクの背景**: Sigmaris Live(Live-1〜7)・CLIチャットツールの削除等、複数の変更を行った当日のうちに、週次(日曜5:55)の自動更新を待たず、自己認識を最新化したい、という依頼を受けて実施した。**コードの変更は不要である前提で着手し、実際に、既存の仕組みをそのまま使うだけで完結した(新規の実行手段は作っていない)。**

## 1. 正しい実行方法(今後の手動実行のための記録)

`backend/app/services/proactive/scheduler.py`(359-414行目)を確認した結果、週次ジョブ`_self_awareness_update()`は、以下の3関数を順に呼んでいるだけであることを確認した。

1. `generate_capability_summaries(backend_root)`(`app/services/capability_summary.py`) — Self-1(スキャン)+Self-2(要約)をまとめて実行
2. `record_capability_summary(...)`(`app/services/capability_summary_store.py`) — 結果を`sigmaris_capability_summaries`へ保存
3. `invalidate_capability_summary_cache()`(`app/services/orchestrator/service.py`) — Self-3が使う、24時間TTLのプロセス内キャッシュを即座に破棄

**この3ステップを、手動で、全く同じ順序・同じロジックで実行する、既存のCLIスクリプトが、既に用意されていた。**

```bash
cd backend
python scripts/generate_capability_summaries.py
```

`backend/scripts/generate_capability_summaries.py`(既存ファイル、本タスクで新規作成したものではない)は、上記1・2を、スケジューラの`_self_awareness_update()`と全く同じ関数呼び出しで実行し、結果を人間が読める形式で標準出力にも表示する。**キャッシュ無効化(3.)だけは、このスクリプト単体では行われない**——これは、スクリプトがバックエンドのプロセスの外から実行される、独立したCLIであるため、実行中のuvicornプロセスの、インメモリキャッシュには直接手が届かないからである。**この処理系は、24時間TTLのキャッシュを持つ(`app/services/orchestrator/service.py`)ため、スクリプト実行後、最大24時間は、古い要約がキャッシュから返され続ける可能性がある。** 即座に反映させたい場合は、バックエンドプロセス自体を再起動する(uvicornの再起動により、インメモリキャッシュは自然に空になる)ことを、あわせて推奨する。

必要な環境変数(`backend/.env`に設定されている必要がある、スクリプル冒頭のdocstringに明記済み):
- `OPENAI_API_KEY`(Self-2の要約生成、nano tier)
- `NEXT_PUBLIC_SUPABASE_URL`・`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`・`SUPABASE_SERVICE_ROLE_KEY`(`sigmaris_capability_summaries`への記録)

**このローカル開発環境(Windows)の`backend/.env`には、上記のいずれも設定されていない**(`AGENT_SECRETS`・`LOCAL_LLM_ENABLED`・`OLLAMA_BASE_URL`・`OLLAMA_EMBED_MODEL`の4項目のみ)ため、**本タスクの実際の実行(本番のSupabase・OpenAI環境に対する実行)は、私(Claude)からは行えなかった。** また、`/api/agent/proactive/trigger`(既存のリモートトリガー用エンドポイント)を確認したが、`action="research"`のみに対応するよう、意図的に絞り込まれており(Phase S-6での設計判断)、Self-1・Self-2に相当するアクションは存在しなかった。これらの事情を運用者へ報告し、**運用者ご自身が、サーバー上で、上記コマンドを実行する**、という方針で合意した。

## 2. 実行前に判明した、重要な事前確認事項: Self-1の検出範囲に関する制約

運用者への報告・実行依頼に先立ち、**「実行すれば、本当にSigmaris Liveが認識され、CLIチャットの言及が無くなるのか」を、コードと、実際のスキャン結果の両方で確認した。**

### 2.1 CLIチャットツールの削除は、そもそもSelf-1の走査対象外だった

`capability_scan.py`(43-65行目、`_SCAN_SUBDIRS`)を確認した結果、Self-1のスキャン対象は、`backend_root`(=`backend/`)配下の`app/services`・`scripts`の2ディレクトリに、固定で限定されている。**削除したCLIチャットツール(`sigmaris_chat.py`等)は、`backend/scripts/`ではなく、リポジトリ直下(`backend/`と同階層)の`scripts/`に存在していた**(`docs/sigmaris/cli_chat_investigation.md`で確認済みの、その通りの配置)——**つまり、Self-1は、削除前から、これらのファイルを一度も走査したことが無い。** 削除後に「CLIチャットの言及が無い」ことが確認できたとしても、それはSelf-1が削除を正しく検知したからではなく、そもそも検知範囲の外にあった、という点を、正直に記録しておく。

### 2.2 Sigmaris Liveは、現在の検出シグナルのいずれにも一致しない(実際にスキャンして確認)

Self-1の検出ロジック(`capability_scan.py`)は、以下の3シグナルのOR結合である。

- シグナルA: ファイル冒頭15行以内の「Phase 英大文字...」というタグ(`_PHASE_TAG_RE = re.compile(r"Phase\s+[A-Z][\w.-]*")`)
- シグナルB: ファイル名に含まれる、既知の領域語彙(`_DOMAIN_FILENAME_MARKERS`、`x_post`・`memory_`・`hypothesis`等、26個の固定マーカー)
- シグナルC(`scripts/`限定): `if __name__ == "__main__":`を持つ、独立したCLIであること

Sigmaris Liveの実装ファイル(`app/services/live_events.py`・`live_detail_masking.py`・`live_event_details.py`)を、実際に目視で確認した結果、いずれも冒頭コメントは「Sigmaris Live」「Live-1」「Live-2」「Live-4」のような、このプロジェクト独自の命名を使っており、**シグナルAが要求する「Phase 英大文字」という表記は、1つも含まれていなかった。** ファイル名(`live_events`・`live_detail_masking`・`live_event_details`)も、シグナルBの26個のマーカーのいずれとも一致しない。さらに、Sigmaris Liveの新設エンドポイント自体(`/live/stream`・`/live/detail`)は`app/routes/agent.py`に実装されており、**`app/routes/`は、そもそもSelf-1の走査対象ディレクトリに含まれていない。**

**推測に頼らず、実際にSelf-1の読み取り専用スキャナー(`scan_capabilities.py`、DBへの書き込み・外部API呼び出しを一切行わないため、ローカル開発環境で安全に実行できる)を、実際に実行して確認した。**

```
$ cd backend && python scripts/scan_capabilities.py
スキャン対象ファイル数: 152
能力候補として検出されたファイル数: 99
領域別の内訳:
  self_improvement    : 35件
  other               : 18件
  memory              : 15件
  x_post_reply        : 14件
  search_citation     : 8件
  cli_script          : 7件
  research_curiosity  : 2件
```

出力全体を"live"という文字列で検索した結果、**一致は0件だった**——Sigmaris Live関連のファイルは、検出された99件のいずれにも含まれていない。`cli_script`領域(7件)の内訳も確認したが、いずれも既存の評価・安全性スキャン系のスクリプト(`generate_eval_testset.py`・`run_cycle_health.py`等)であり、`sigmaris_chat`関連の言及も0件だった(2.1節の通り、そもそも走査対象外のため当然の結果ではある)。

**結論: 今回、Self-1・Self-2を実行しても、既存の検出ロジックのままでは、「Sigmaris Liveという機能を持っている」という情報は、自己認識(`sigmaris_capability_summaries`)には反映されない。** これは、スキャン結果が古い(実行タイミングの問題)のではなく、**検出シグナル自体が、Sigmaris Liveの命名規則(「Phase」ではなく「Live-N」)・実装場所(`app/routes/`)を、そもそも想定していない**という、構造的な検出範囲の制約である。

### 2.3 運用者との合意: 今回はそのまま実行し、検出範囲の拡張は別タスクとする

上記2点(CLIチャットの不在は当然の結果であり、Sigmaris Liveは今回実行しても反映されない)を、実行前に運用者へ報告した。**検出ロジック自体の拡張(`capability_scan.py`へ、Live系のPhaseタグ相当の表記・ファイル名マーカーを追加する等)は、依頼書が想定した「実行手段が無ければ最小限の追加を検討する」という範囲を超える、既存の判定アルゴリズムそのものへの変更であるため、本タスクの範囲には含めず、別タスクとして扱うべきと判断した。** 運用者と協議した結果、**「今回はそのまま実行し(他の領域の要約は正しく最新化されるため、無意味ではない)、Sigmaris Liveの検出は、別タスクで対応する」という方針で合意した。**

## 3. 実行結果

<!-- 運用者が、サーバー上で `cd backend && python scripts/generate_capability_summaries.py` を実行した後、
     その標準出力をここに追記し、以下を確認する:
     - スキャンされたファイル数・検出された能力候補数(Self-1)
     - 各領域の要約テキストの内容、及び sigmaris_capability_summaries への記録件数(Self-2)
     - 2.1〜2.2節で予測した通り、CLIチャットの言及が無く、Sigmaris Liveの言及も無いことの、実際の確認結果 -->

**(運用者による実行待ち。実行後、出力を共有いただき次第、本節を更新する。)**

## 4. 動作確認(シミュレーション)

<!-- 実行結果を受けて、以下を追記する:
     - 「Sigmaris Liveという機能は持っていますか?」「CLIチャットツールはありますか?」という
       趣旨の質問に対し、実際にsigmaris_capability_summariesへ記録された要約テキストの内容から、
       何が答えられ、何が答えられないかを確認する
     - 2.2節の通り、Sigmaris Liveへの言及は今回の実行では追加されない見込みのため、その通りに
       なることを、実際の記録内容で確認する(またはCLIチャットの言及が無いこと自体は確認する) -->

**(3章の実行結果を受けて、追記する。)**

## 気づいた懸念点

1. **Self-1の検出範囲(Phaseタグ・26個の固定ファイル名マーカー・`app/services`+`scripts`のみ)は、このプロジェクトの初期の命名慣習(Phase A〜Sのタグ付け)を前提にしており、Sigmaris Live以降に確立された「Live-N」という、別の命名系列には対応していない。** 今後も、新しい機能群が、既存のPhase命名規則を使わずに実装される場合(例えば、今後のタスクで新しい呼称の系列が生まれた場合)、同様の検出漏れが起きうる。次のタスクとして、`capability_scan.py`のシグナルへ、「Live-」プレフィックスや、`app/routes/`ディレクトリも走査対象に含める、といった拡張を検討することを推奨する。
2. **キャッシュのTTL(24時間)により、スクリプト実行直後でも、既に走っているバックエンドプロセスの応答には、最大24時間、古い要約が使われ続ける可能性がある。** 即座に反映させたい場合は、バックエンドプロセスの再起動もあわせて行うことを、1章に明記した。
3. **本タスクの「実行」自体(2章)は、運用者による実施を待っている状態である。** 3・4章は、実行結果を受け取り次第、追記する。
