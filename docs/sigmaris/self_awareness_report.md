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
