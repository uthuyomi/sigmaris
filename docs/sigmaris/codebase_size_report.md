# 全体ソースコード量の調査

**調査日**: 2026-07-14
**性質**: 本ドキュメントは調査・集計のみを目的とする。**この調査タスクの中では一切のコード変更を行っていない。**
**対象コミット**: `2f9ab60`(main、Phase R-3完了時点)

---

## 0. 調査の前提と使用ツール

- 行数集計には[`cloc`](https://github.com/AlDanial/cloc)(v2.06)を使用した。ローカル環境に未インストールだったため、`npx --yes cloc <path> --vcs=git` の形で都度取得して実行した(`pip install cloc`は別のPythonパッケージ(0.2.5、CLI無し)がヒットし目的のツールではなかったため不採用。判断根拠として明記する)。
- `--vcs=git`オプションにより、gitで追跡されているファイルのみを対象とした(`.venv`・`node_modules`・`__pycache__`・`.next`等のビルド成果物・依存関係は自動的に除外される)。
- `frontend/package-lock.json`(16,627行、自動生成ファイル)は「ソースコード」の実態を歪めるため、`--not-match-f='package-lock\.json$'`で明示的に除外し、別途注記した。
- 再現用コマンド例:
  ```bash
  npx --yes cloc backend --vcs=git
  npx --yes cloc frontend --vcs=git --not-match-f='package-lock\.json$'
  npx --yes cloc supabase/migrations --vcs=git
  npx --yes cloc backend/tests --vcs=git
  ```
- 時系列調査(6章)では、`git worktree add --detach <tmp> <commit>`で対象コミット時点のスナップショットを一時的な作業ツリーに展開し、そこに対して`cloc`を実行した後、`git worktree remove`で破棄した。**現在の作業ツリー(mainブランチ)には一切変更を加えていない。**

---

## 1. 全体の行数集計

### 1.1 `backend/`

| 言語 | ファイル数 | 空行 | コメント行 | コード行 | 総行数 |
|---|---:|---:|---:|---:|---:|
| Python | 113 | 3,484 | 4,010 | 18,434 | 25,928 |
| JSON | 1 | 0 | 0 | 117 | 117 |
| TOML | 2 | 7 | 4 | 50 | 61 |
| Text | 4 | 1 | 0 | 36 | 37 |
| Dockerfile | 1 | 6 | 0 | 12 | 18 |
| **合計** | **121** | **3,498** | **4,014** | **18,649** | **26,161** |

Pythonのコメント率(コメント行 / コード行)は約21.8%。B群・Temporal Layer・Phase Rを通じて「判断根拠をコード内コメントに残す」という一貫した方針(各Phaseレポートで繰り返し明記)の結果と考えられる。

### 1.2 `frontend/`

`package-lock.json`(16,627行、自動生成)を除く。

| 言語 | ファイル数 | 空行 | コメント行 | コード行 | 総行数 |
|---|---:|---:|---:|---:|---:|
| TypeScript(`.ts`+`.tsx`) | 134 | 1,277 | 155 | 10,955 | 12,387 |
| CSS | 1 | 45 | 0 | 320 | 365 |
| JSON(設定ファイル、`package.json`等) | 4 | 0 | 0 | 123 | 123 |
| JavaScript | 3 | 14 | 2 | 100 | 116 |
| SVG | 5 | 0 | 0 | 5 | 5 |
| **合計** | **147** | **1,336** | **157** | **11,503** | **12,996** |

内訳: `.ts`(ロジック・設定)88ファイル、`.tsx`(Reactコンポーネント)46ファイル(cloc上は両方とも「TypeScript」として合算表示される)。

コメント率は約1.4%とbackendより大幅に低い——backendほど「判断根拠をコメントで残す」という慣習が徹底されていない、または単にフロントエンドのコード量自体が少なく複雑な判断根拠を要する箇所が少ないためと考えられる(判断は下していない、観察のみ)。

`package-lock.json`(16,627行)は自動生成ファイルであり実質的なソースコードではないため、上記合計には含めていない。含めた場合の`frontend/`全体の行数は29,623行(=12,996+16,627)になる。

### 1.3 その他のディレクトリ(参考)

`backend/`・`frontend/`以外にもソースコードは存在する。指示書の主対象ではないが、全体像として記録する。

| ディレクトリ | 内容 | ファイル数 | コード行 | 総行数 |
|---|---|---:|---:|---:|
| `supabase/migrations/` | SQLマイグレーション | 48 | 2,170 | 3,093 |
| `wearos/` | Pixel Watch向けKotlinアプリ | 14(cloc対象、Kotlin/Shell/Gradle/XML/Markdown/Properties) | 1,114 | 1,372 |
| `scripts/`(リポジトリルート) | 運用スクリプト(`apply_migration.py`等) | 3 | 1,325 | 1,738 |

(マイグレーションの詳細は4章、`scripts/`はbackend側の`backend/scripts/`とは別のリポジトリルート直下のディレクトリであることに注意。)

### 1.4 コア「製品コード」の総計(backend + frontend + migrations)

| | ファイル数 | コード行 | 総行数 |
|---|---:|---:|---:|
| backend(Python + 付随設定) | 121 | 18,649 | 26,161 |
| frontend(lockfile除く) | 147 | 11,503 | 12,996 |
| migrations(SQL) | 48 | 2,170 | 3,093 |
| **合計** | **316** | **32,322** | **42,250** |

---

## 2. ファイル数・ディレクトリ構造の集計

### 2.1 `backend/app/` 直下

| ディレクトリ | .pyファイル数 |
|---|---:|
| `services/`(サブディレクトリ含む) | 86 |
| `routes/` | 8(うち`__init__.py`1件) |
| `schemas/` | 4 |
| `main.py`・`config.py`・`__init__.py`(直下) | 3 |

### 2.2 `backend/app/services/` の内訳

| | .pyファイル数 |
|---|---:|
| 直下(トップレベル) | 73 |
| `orchestrator/`(サブディレクトリ) | 8 |
| `proactive/`(サブディレクトリ) | 5 |
| **合計** | **86** |

`orchestrator/`の内訳: `__init__.py`・`agent_registry.py`・`audit.py`・`persona_loader.py`・`persona_rewriter.py`(R-1調査でデッドコードと判明済み、`bug_inventory.md`参照)・`response_guard.py`・`schedule_agent_client.py`・`service.py`(3章参照)。

`proactive/`の内訳: `__init__.py`・`actions.py`・`jwt_manager.py`・`notifier.py`・`scheduler.py`。

### 2.3 B群・BA群・Temporal Layer・Phase R関連ファイルの実態

**重要な前提**: このコードベースでは、多くのB機能が「1機能=1新規ファイル」ではなく、**既存の共有ファイルへの拡張**として実装されている(例: B13・B14は`decision_log.py`に、B8は`memory_search.py`に、B17は`user_fact_data.py`/`memory_validator.py`に統合)。そのため「B群のファイル数」を単純にカウントすることはできない。判明している範囲でのマッピングと行数(コード行、cloc計測)を以下に示す。

| 機能/Phase | 主なファイル | コード行 |
|---|---|---:|
| B1(ハイブリッド検索)・B8(時間認識リランキング)の一部 | `memory_search.py` | 322 |
| B2(エピソード/意味記憶分離) | `experience_layer.py` | 410 |
| B3(記憶自己検証) | `active_inquiry.py` | 298 |
| B6(話題遷移トラッキング) | `topic_tracker.py` | 148 |
| B7(マルチホップ分解検索) | `multihop_search.py` | 146 |
| B9(ナレッジグラフ) | `knowledge_graph.py` | 312 |
| B10(クロスエンコーダリランキング) | `memory_rerank.py` | 79 |
| B11(較正済み棄権) | `memory_confidence.py` | 48 |
| B12(検索後圧縮) | `memory_compression.py` | 85 |
| B13(暗黙フィードバック)・B14(意思決定パターン)・A3(decision_log本体) | `decision_log.py` | 601 |
| B15(個人別棄権閾値) | `abstention_feedback.py` | 113 |
| B16(長期ゴール整合性) | `goal_alignment.py` | 322 |
| B17(重要度学習)の一部・全般の事実CRUD | `user_fact_data.py` | 300 |
| memory_validator(B17減衰・B5ダッシュボード基盤) | `memory_validator.py` | 257 |
| Temporal Layer(相対日付解析、Step1・Step3で共有) | `temporal_parsing.py` | 64 |
| C-mini/C-full(SB-1〜7測定基盤) | `eval_metrics.py`・`eval_runner.py`・`eval_runs_store.py` | 185+92+82=359 |
| Phase R(R-1トレース関数、R-2/R-3 RC指標) | `cycle_trace.py`・`cycle_health_metrics.py`・`cycle_health_runner.py`・`cycle_health_runs_store.py` | 69+400+199+89=757 |
| BA4(応答生成統合)の中核 | `orchestrator/service.py`(3章参照) | 1,145 |

**B4(出所トラッキング)には対応する専用ファイルが存在しない** — `thread_id`/`invocation_id`という列とパラメータが複数の既存ファイル(`user_fact_data.py`・`experience_layer.py`・`decision_log.py`)に横断的に追加される形で実装されているため。同様に**BA1〜BA3も専用ファイルを持たず**、既存ファイル(`orchestrator/service.py`・`active_inquiry.py`等)への変更として実装されている。

Phase R関連(`cycle_trace.py`・`cycle_health_*.py`)は本タスク実施時点で合計757コード行、4ファイル——直近3タスク(R-1〜R-3)で新規に追加された、比較的まとまった規模の独立サブシステムである。

### 2.4 `frontend/src/` の内訳

| ディレクトリ | ファイル数 |
|---|---:|
| `app/`(Next.js App Router、ページ・APIルート) | 45 |
| `lib/` | 38 |
| `components/`(うち`ui/`shadcn系が6) | 33 |
| `i18n/` | 18 |

---

## 3. 突出して大きいファイルの上位10件

cloc `--by-file-by-lang`の出力を、backend/frontend(コード行ベース)横断でソートした。

| # | ファイル | コード行 | コメント行 | 空行 | 総行数 |
|---|---|---:|---:|---:|---:|
| 1 | `backend/app/services/orchestrator/service.py` | 1,145 | 376 | 181 | **1,702** |
| 2 | `backend/app/services/chat.py` | 1,029 | 49 | 84 | 1,162 |
| 3 | `backend/app/routes/agent.py` | 922 | 57 | 170 | 1,149 |
| 4 | `backend/app/services/research_agent.py` | 643 | 23 | 103 | 769 |
| 5 | `backend/app/services/decision_log.py` | 601 | 196 | 102 | 899 |
| 6 | `frontend/src/components/tool-fallback.tsx` | 565 | 1 | 58 | 624 |
| 7 | `backend/app/services/x_post_generator.py` | 518 | 29 | 107 | 654 |
| 8 | `backend/app/services/chat_tools.py` | 459 | 40 | ― | 499 |
| 9 | `frontend/src/components/thread.tsx` | 414 | 44 | ― | 458 |
| 10 | `backend/app/services/experience_layer.py` | 410 | 190 | 72 | 672 |

(独立して`wc -l`でも上位3件の総行数を検証済み: `orchestrator/service.py`=1,702行、`chat.py`=1,162行、`routes/agent.py`=1,149行。一致を確認した。)

### `orchestrator/service.py`について(指示書が特に確認を求めた箇所)

**現在1,702行(コード行1,145行、コメント376行、空行181行)。** これは、backend全体(113 Pythonファイル)の中で最大のファイルであり、2位の`chat.py`(1,162行)より500行以上大きい。

`docs/sigmaris/phase_r_report.md`・過去の各Phaseレポートで確認できる通り、このファイルはPhase A1(セッション継続)で作成されて以降、A3(decision_log連携)・BA1〜BA4(応答生成統合・ファイア&フォーゲット処理の集約)・B2(エピソード検出の呼び出し)・B3(自己検証質問の差し込み)・B6(話題遷移)・B7(マルチホップ)・Temporal Layer Step1〜3(memory_kind・last_mentioned_at・経過日数)・Phase R-1(cycle_idからの転換、参照連鎖)を通じて一貫して拡張対象になり続けてきた、**このコードベースで最も責務が集中しているファイル**である。7章で詳述する通り、これは今回の調査で確認できた最も顕著な懸念点である。

---

## 4. マイグレーションファイルの集計

- ファイル数: **48件**(`supabase/migrations/`)
- 総行数: **3,093行**(コード2,170行 + コメント585行 + 空行338行)
- 1ファイルあたりの平均: 約64行(総行数ベース)

最も古いマイグレーションは`202603...`系(Phase A以前の初期スキーマ)、最新は本タスク実施時点で`202607220048_cycle_health_runs.sql`(Phase R-3、未適用)。ファイル名の日付プレフィックスは実際の作成日と厳密には一致しない場合がある(同日に複数件作られる際は末尾の連番のみが進む)ことは、過去のレポート(`phase_c_mini_report.md`等)でも触れられている通り。

---

## 5. テストコードの規模

### 5.1 `backend/tests/`(コミット済み、恒久的なテスト)

| | 件数 |
|---|---:|
| ファイル数 | 7 |
| `def test_`関数の総数 | 16 |
| コード行 | 392 |
| 総行数 | 464 |

内訳:
- `backend/tests/test_memory_snapshot.py`
- `backend/tests/orchestrator/test_audit.py`
- `backend/tests/orchestrator/test_response_guard.py`
- `backend/tests/orchestrator/test_schedule_agent_client.py`
- `backend/tests/orchestrator/test_service.py`
- (`__init__.py` × 2)

この16件は、本ドキュメント調査時点まで一貫して「16 passed」として全Phaseレポートに登場し続けており、Phase A以降ほとんど増加していない。

### 5.2 「scratchテスト」の扱いについて

各Phaseレポート(B2・B4・Temporal Layer・R-1〜R-3等、ほぼ全件)が明記している通り、このプロジェクトでは新機能ごとに作成されるテストの大半が**「セッションスコープのスクラッチディレクトリ」に作成され、`backend/tests/`にはコミットされない**方針が一貫して採られてきた。理由は各レポートで「既定の方針通り」と繰り返し言及されている。

**この方針の帰結として、scratchテストは実行セッション終了とともに失われ、現在のリポジトリには一切残っていない。** そのため、過去に実際に書かれたscratchテストの総量をこの調査から直接集計することはできない。代わりに、各Phaseレポートの本文に記録された「N passed」という実行結果の記述から、規模感を間接的に把握できる。

各レポートに記録された「N passed」を横断的に確認したところ、以下のような推移が見られた(**これは実測ではなく、各レポートに残された実行ログの記述からの読み取りであることを明記する**)。

- 個別タスクの新規テスト: おおむね数件〜20件程度(例: Phase B2「14 passed」、Temporal Layer Step1「10 passed」、Phase R-1「12 passed」)
- 既存scratchテストを含めた累積再実行: セッションが進むにつれて増加し、本ドキュメント作成の直前(Phase R-3完了時点)の報告では「65 passed」(`backend/tests/`16件 + R-1のscratch12件 + R-2のscratch19件 + R-3のscratch18件、の合算実行)に達していた

**懸念点として記録する**: この運用は「その場では網羅的に検証しているが、リグレッション防止としては`backend/tests/`の16件しか将来に引き継がれない」という構造的な特性を持つ。次回以降の変更が、過去のPhaseで確認済みだったはずの挙動(例: R-1のトレース関数、Temporal Layerの各Step)を壊しても、`backend/tests/`の16件がその挙動を直接検証していない限り、自動テストでは検知できない。7章でも改めて触れる。

### 5.3 `frontend/`のテスト

**0件。** `frontend/`配下に`.test.ts`/`.test.tsx`/`.spec.ts`/`__tests__/`のいずれのパターンも存在しない。`frontend/src/app/api/push/test/route.ts`という「test」を含むパスが1件あるが、これはプッシュ通知の動作確認用APIルートであり、自動テストではない。

---

## 6. 時系列での増加傾向

git履歴から、以下4つのマイルストーン時点のコミットを特定し(コミットメッセージ・`phase_b_summary.md`等の記述を根拠とした)、`git worktree`で各時点のスナップショットを展開して`cloc`を実行した。

| マイルストーン | コミット | 日付 | 根拠 |
|---|---|---|---|
| Phase A完了 | `479659a`(Phase A5) | 2026-07-03 | コミットメッセージ「Phase A5: RAG embedding generation falls back to OpenAI...」、これ以降A系コミットなし |
| Phase B完了 | `ee8bd6d`(Phase B5) | 2026-07-05 | コミットメッセージに明示的に「(Phase B complete)」と記載 |
| Phase BA完了(付随バグ修正含む、近似) | `fe65052` | 2026-07-10 | BA1〜BA4本体の変更が完了し、Temporal Layer Step1着手前の最終コミット。「Phase BA完了」を示す明示的なコミットメッセージは無いため、**Temporal Layer開始直前を近似的な境界として採用した**(判断根拠として明記) |
| 現在 | `2f9ab60`(Phase R-3完了・マージ後) | 2026-07-14 | 本調査時点のHEAD |

### 6.1 backend(Pythonのみ)

| マイルストーン | .pyファイル数 | コード行 | コメント行 | 空行 | 総行数 |
|---|---:|---:|---:|---:|---:|
| Phase A完了 | 80 | 12,173 | 912 | 2,166 | 15,251 |
| Phase B完了 | 94 | 15,087 | 2,298 | 2,790 | 20,175 |
| Phase BA完了(近似) | 107 | 16,975 | 3,140 | 3,179 | 23,294 |
| 現在 | 113 | 18,434 | 4,010 | 3,484 | 25,928 |

Phase A→現在で、ファイル数は+41%(80→113)、コード行数は+51%(12,173→18,434)、**コメント行数は+340%(912→4,010)**——ファイル数・コード行数の伸びに対してコメント行の伸びが著しく大きい。これは「判断根拠をコード内コメントに残す」という方針がPhase A以降、B群・Temporal Layer・Phase Rと進むにつれて一貫して強化されてきたことの定量的な裏付けと考えられる。

### 6.2 frontend(TypeScript、lockfile除く)

| マイルストーン | ファイル数 | コード行 | 総行数(SUM) |
|---|---:|---:|---:|
| Phase A完了 | 144 | 12,415 | 12,962 |
| Phase B完了 | 145 | 12,504 | 13,051 |
| Phase BA完了(近似) | 145 | 12,519 | 13,066 |
| 現在 | 134 | 10,955 | 12,996 |

**Phase BA完了時点から現在にかけて、frontendのコード行数がむしろ減少している**(12,519→10,955、-1,564行)。これはコードの衰退ではなく、`6d86798`(2026-07-12)「Remove legacy /sigmaris, orphaned landing page, and Stripe billing UI」というクリーンアップコミットにより、旧`/sigmaris`ページ・孤立したランディングページ・Stripe課金UI(`billing-panel.tsx`・`landing-page-content.tsx`・関連i18nファイル等、計16ファイル)が削除されたことが直接の原因であることをgit履歴で確認した。**backendが一貫して増加し続ける一方、frontendは不要になった機能を実際に削除する形でネットの行数を減らした**、という対照的な傾向が見られた。

### 6.3 マイグレーション件数

| マイルストーン | ファイル数 |
|---|---:|
| Phase A完了 | 27 |
| Phase B完了 | 40 |
| Phase BA完了(近似) | 44 |
| 現在 | 48 |

---

## 7. 気づいた懸念点

1. **`orchestrator/service.py`への責務集中(最重要)**: 3章で述べた通り、1,702行(コード1,145行)は突出しており、backend全体で唯一「2位の1.5倍近い」規模を持つファイルである。会話ターンの認証・コンテキスト構築・スケジュールエージェント呼び出し・fire-and-forgetタスクの起動(記憶抽出・認知レイヤー・イベント既読マーキング)が、非streaming/streaming双方の経路でほぼ並行に実装されており(`run_orchestrator_chat`/`run_orchestrator_chat_stream`のコード重複が多い)、単一責任の原則から見て明確にリファクタリング候補である。ただし本タスクはコード変更を行わない調査タスクであるため、リファクタリングの実施は次タスクの判断に委ねる。
2. **backend/testsが実質的に増えていない**: Phase A完了時点から現在まで、`backend/tests/`は16件のテスト関数のまま変化していない一方、backendのコード行数は+51%増加した。5.2節で述べた通り、実際の検証作業(scratchテスト)は各Phaseで大量に行われているが、それらは将来に引き継がれない。**コード量に対するリグレッション防止テストの比率が、時間とともに相対的に薄まり続けている**ことを定量的に確認できた——これはPhase R-3レポート(19.3節)でも「懸念点」として触れられていたが、今回の調査で数値として裏付けられた形になる。
3. **frontendのテストがゼロ件**: 5.3節の通り、自動テストが一切存在しない。B5(記憶ダッシュボード)を含む45件の`app/`配下ページ・33件の`components/`が、型検査・lint以外の自動検証を持たない状態にある(過去のレポートでも「実ブラウザでの確認が必要」と繰り返し指摘されている点と符合する)。
4. **ドキュメント(`docs/sigmaris/`)の分量がコード本体に匹敵する規模になっている**: 52ファイル・15,402行——これは`frontend/`のソースコード全体(12,996行)より多く、`backend/`のPythonコード(25,928行)の約59%に相当する。各タスクが「調査→報告書作成→(必要なら)実装→報告書更新」というプロセスを徹底してきた結果であり、それ自体は判断根拠の透明性という観点で強みだが、**ドキュメント同士の重複・矛盾が発生するリスクも比例して増大する**(実際、本タスクの過程で複数のレポートが「前回の申し送り事項」を参照・更新し続ける構造になっており、どの記述が最新かを追うコストが増している)。ドキュメントの整理・要約(サマリーのサマリー)を検討する価値があるかもしれない。
5. **B4(出所トラッキング)・BA1〜BA3が専用ファイルを持たない**という2.3節の観察は、必ずしも悪いことではない(過剰な新規ファイル乱立を避けているとも言える)が、「特定の機能がどこに実装されているか」をコードのみから把握することを難しくしている。`docs/sigmaris/`の各レポートがこの実装場所の対応関係を記録する、事実上唯一の手段になっている点は、4番目の懸念点(ドキュメント依存度の高さ)と表裏一体である。
6. **リポジトリに`__pycache__`/`.pyc`ファイルが32件、誤ってgit管理下に入っている**(`backend/.gitignore`に`__pycache__/`の記載はあるものの、それ以前にコミットされたファイルは追跡が続いている)。コード量の集計には影響しない(cloc/wcの対象外)が、リポジトリの衛生状態としては軽微な改善余地として記録する。

---

## 8. 集計に使用したコマンドの再現手順(まとめ)

```bash
# 1. cloc取得(インストール済みでない場合)
npx --yes cloc --version

# 2. backend/frontend/migrations/testsの行数集計
npx --yes cloc backend --vcs=git
npx --yes cloc frontend --vcs=git --not-match-f='package-lock\.json$'
npx --yes cloc supabase/migrations --vcs=git
npx --yes cloc backend/tests --vcs=git

# 3. ファイル単位の詳細(上位ファイル特定用)
npx --yes cloc backend --vcs=git --by-file-by-lang --csv --quiet > backend_by_file.csv
npx --yes cloc frontend --vcs=git --not-match-f='package-lock\.json$' --by-file-by-lang --csv --quiet > frontend_by_file.csv

# 4. 時系列比較(例: Phase A完了時点)
git worktree add --detach /tmp/wt-phaseA 479659a
npx --yes cloc /tmp/wt-phaseA/backend --vcs=git
npx --yes cloc /tmp/wt-phaseA/frontend --vcs=git --not-match-f='package-lock\.json$'
git worktree remove --force /tmp/wt-phaseA

# 5. ファイル数の直接カウント(git ls-files、cloc結果の検算)
git ls-files backend/app/services | grep '\.py$' | wc -l
git ls-files supabase/migrations | wc -l
```
