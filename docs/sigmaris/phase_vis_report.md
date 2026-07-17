# Phase Vis-1 実施報告: 表示する指標の選定(フロントエンド成長ログ、第一段階)

**作業ブランチ:** `phase-vis1-metric-selection`(mainから新規作成)
**範囲:** Phase R・G・S・D〜F・Safetyを通じて分散して蓄積されてきた、内部的な指標・状態の測定・記録の仕組みを棚卸しし、「シグマリスが、今、どういう状態にあるか」「どう成長・変化してきたか」を一目で把握できる、新しいフロントエンド画面(以下「成長ログ」)の表示内容を設計する。**コードの実装は一切行っていない。設計・提案のみ。**

---

## 0. 前提として確認したこと

- `docs/sigmaris/phase_r_report.md`(RC-1〜RC-5、`sigmaris_cycle_health_runs`)
- `docs/sigmaris/phase_g_report.md`(Citation Precision・Search Trigger Rate・Contradiction Rate、`sigmaris_grounding_health_runs`)
- `docs/sigmaris/phase_s_report.md`(Drive State、`drive_system.py`)
- `docs/sigmaris/phase_d_report.md`・`phase_e_report.md`・`phase_f_report.md`(D-1〜F-3、自己改善パイプライン全体)
- `docs/sigmaris/safety_governance_report.md`(Safety-1〜3、安全機構の棚卸し・統合・監視)
- `docs/sigmaris/frontend_inventory.md`(`/timeline`の設計・`/admin/memory`との役割分担、11〜17章)
- 実装コード: `drive_system.py`・`experience_layer.py`・`cycle_health_runs_store.py`・`grounding_health_runs_store.py`・各`sigmaris_*`テーブルのマイグレーション、`frontend/src/components/app-shell.tsx`(既存ナビゲーション構造)

**重要な追加発見(調査の過程で判明、以降の設計全体に影響する)**: `backend/app/services/proactive/scheduler.py`の全定期ジョブ一覧を確認した結果、**Phase R(`run_cycle_health.py`)・Phase G(`run_grounding_health.py`)・Phase D〜F(`run_hypothesis_generation.py`等)・Safety-3(`scan_safety_critical_files.py`)のいずれも、自動スケジューラには一切登録されていない**——全て、運用者が手動でCLIを実行した時だけデータが記録される。この事実は、3章(成長ログのコンセプト)・5章(役割分担)の設計に直接影響するため、最初に明記しておく。

---

## 1. 表示候補の、洗い出し結果

実際のテーブル・関数を確認し、値の意味・更新頻度・実データの有無まで含めて棚卸しした。

### 1.1 Phase R: 循環の健全性(`sigmaris_cycle_health_runs`、`run_cycle_health.py`手動実行)

| 指標 | 意味 | 値の性質 |
|---|---|---|
| RC-1 Cycle Completion Rate(`eligible_completion_rate`) | Experience→Memoryへの到達率 | 0〜1の比率。Noneはあり得ない(到達率0でも数値は出る) |
| RC-2 Temporal Consistency Score | 時系列的にありえない矛盾の検出 | 0〜1のスコア。**検査対象0件のときNone**(矛盾ゼロと区別) |
| RC-3 Belief Stability Index | 信念(B14)が根拠なく覆っていないか | 0〜1のスコア。**初回実行時は必ずNone**(前回スナップショット不在) |
| RC-4 Policy-Belief Alignment | 方策(B16)が信念と同じ材料に基づくか | 0〜1のスコア。**評価対象0件のときNone** |
| RC-5 Cycle Break Detection | RC-1/RC-2の急激な悪化の検知 | `insufficient_history`/`healthy`/`break_detected`の3値 |

### 1.2 Phase G: 応答の根拠品質(`sigmaris_grounding_health_runs`、`run_grounding_health.py`手動実行)

| 指標 | 意味 | 値の性質 |
|---|---|---|
| Citation Precision | 引用の忠実性(歪めずに使えているか) | 0〜1の比率。**引用されたclaimが0件のときNone** |
| Search Trigger Rate | 検索が発動した割合 | **下限近似値であることが、G-5報告書で明記済み**(G-1のneeds_search判定自体は永続化されていないため) |
| Contradiction Rate | 矛盾フラグが立った割合 | 0〜1の比率。分母は「検証が行われたターン」のみ |

### 1.3 Phase S: Drive State(`drive_system.py`、**永続化テーブルなし・都度ライブ計算**)

| 指標 | 意味 | 値の性質 |
|---|---|---|
| KnowledgeGap(`level`) | 「まだ知らない/確認が必要」の量 | 0〜1、常に値を持つ |
| Mastery(`level`) | RC-1/RC-2/RC-5から算出される、循環の健全性への内的な反応 | 0〜1、**RC計測が一度も実行されていない場合はNone**(`has_data=False`) |
| Coherence(`level`) | B16未解決フラグ数+RC-4から算出される、方策と信念の緊張度 | 0〜1、常に値を持つ |

**重要な制約**: `DriveState`は、`get_current_drive_state()`が呼ばれた瞬間にライブ計算されるだけで、**過去のDrive State自体を記録するテーブルは存在しない**。「先週のCoherenceは今週よりどうだったか」という比較は、現状のデータ構造では不可能。

さらに、以下も候補として洗い出した:

- **直近の自発的な行動の履歴**: `sigmaris_experience`(`experience_layer.get_recent_experiences()`)。`experience_type`(success/failure/unresolved)・`category`・`title`・`created_at`を持つ。S-2(Goal Proposal)が生成した自発的な行動の結果が、ここに記録される。

### 1.4 Phase D〜F: 自己改善パイプラインの進捗

| 段階 | テーブル | 表示候補となりうる値 |
|---|---|---|
| D-1(根拠収集) | `sigmaris_evidence_bundles` | 収集された根拠の件数・カテゴリ内訳 |
| D-2(仮説生成) | `sigmaris_hypotheses` | 生成された仮説の件数、`requires_special_review`件数 |
| D-3(優先順位付け) | `sigmaris_hypothesis_priorities` | `normal_track`/`special_review_track`の件数、上位仮説 |
| E-1(静的検証) | `sigmaris_static_verifications` | `verdict`別内訳(`baseline_healthy_with_coverage`等) |
| E-2(動的検証) | `sigmaris_sandbox_verifications` | 直近実行の`verdict`(基盤の健全性) |
| E-4(マイグレーションレビュー) | `sigmaris_migration_review_queue` | `pending`件数(人間の判断待ち) |
| F-1〜F-3(差分生成・承認・PR) | `sigmaris_code_diff_proposals` | `review_status`別件数(pending/approved/rejected)、`pr_creation_status`別件数(pr_created等) |

### 1.5 Safety: 安全機構の状況

| 項目 | データソース | 値の性質 |
|---|---|---|
| 安全機構の棚卸し内容(14機構、CIK分類) | `docs/sigmaris/safety_governance_report.md`(静的文書) | **DBに存在しない、文書のみ**——頻繁に変化しないため、そもそも「測定」というより「参照文書」の性質が強い |
| 安全上重要なファイルの追加漏れ検知 | `sigmaris_cycle_health_runs.safety_governance_status`(Safety-3でRC計測基盤に統合済み) | `healthy`/`gap_detected`の2値 |

---

## 2. 「見せるべきもの」の、選定結果と、その根拠

### 2.1 選定方針

依頼書の要件(「一目で把握できる、必要な指標だけ」)に従い、以下の3つの基準で絞り込んだ。

1. **「壊れていないか」を一目で判断できる、状態を持つ指標を優先する**(RC-5・Safety Governance Statusのような、3値・2値の明確なステータスは特に優先度が高い)。
2. **人間の判断が必要な"滞留"を示す指標を優先する**(E-4の`pending`件数、F-1〜F-3の`pending`件数——これらは「今、海星さんが確認すべきものがあるか」を直接示す)。
3. **数値の解釈に、複雑な前提知識を要するものは、除外または補足付きで格下げする**(Search Trigger Rateの下限近似値、RC-3/RC-4の初回None等)。

### 2.2 「見せるべきもの」(ヘッドライン指標、5〜7個程度に絞る)

| # | 指標 | 選定根拠 |
|---|---|---|
| 1 | RC-5 Cycle Break Detection(status) | 「循環が壊れていないか」を一言で示す、最も統合的な健全性シグナル。3値ステータスがそのまま「一目で分かる」形式に合う |
| 2 | Citation Precision + Contradiction Rate | 「シグマリスの発言は、根拠に忠実か」という、利用者にとって最も直感的に気になる品質軸 |
| 3 | Drive State(3軸) | 「シグマリスが今、何を気にかけているか」という、擬人的で分かりやすい"今の気持ち"のスナップショット。成長ログの中で最も「シグマリスらしさ」を感じられる要素になると考えられる |
| 4 | 自己改善パイプラインの"今、人間の確認を待っているもの"の件数(E-4 pending + F-1〜F-3 pending の合算、または内訳) | 「今、海星さんが何かすべきことがあるか」という、行動を促す実用的な情報 |
| 5 | Safety Governance Status(healthy/gap_detected) | 安全機構全体の健全性を、1つのバッジで示せる、Safety-1〜3の集大成 |
| 6(補足枠) | RC-1 eligible_completion_rate・RC-2 score(数値そのもの) | ヘッドラインのRC-5が「異常あり」と示した場合に、詳細を確認する入り口として、数値自体も画面内には置く(ただし1のような主役ではなく、クリック展開等の二次情報として) |

### 2.3 「見せなくてよいもの」(除外、または`/admin/memory`相当の開発者領域に留める)

| 除外対象 | 除外理由 |
|---|---|
| RC-3 Belief Stability Index・RC-4 Policy-Belief Alignment(生の数値) | 初回None・評価対象0件Noneが頻発しやすく、解釈に前提知識(B14/B16の仕組み)を要する。**完全に隠すのではなく、RC-5のbroke_metrics内訳として言及される場合のみ、詳細ドリルダウンで触れる**という扱いにする |
| Search Trigger Rateの生の値 | 「下限近似値」という重要な限定条件を伴い、額面通り受け取ると誤解を招く。数値そのものより「引用の忠実性(Citation Precision)」の方が実感に直結するため、ヘッドラインからは外す(詳細画面には残す) |
| E-1(静的検証)の`matched_modules`・E-2(動的検証)のポート番号・サンドボックス起動ログ | 完全に技術的な実装詳細。`/admin/memory`同様の開発者向け情報であり、成長ログの目的(状態の把握)に寄与しない |
| F-1〜F-3の差分本文(`diff_text`)・PR URL | レビュー・承認は、既存の専用CLI(`review_diff_proposals.py`)が引き続き担う。成長ログは「pending件数」という要約のみを見せ、実際のレビュー作業への誘導はしない(役割分担、5章) |
| Safety-1〜3の14機構の個別詳細(役割・トリガー条件等) | 一度棚卸しされた後は頻繁に変化しない、リファレンス的な情報。成長ログの「今の状態・推移」という性質に合わない——`docs/sigmaris/safety_governance_report.md`という文書のまま参照する形を維持し、フロントエンドへの移植は不要と判断した |
| `sigmaris_experience`の個々のログ全文 | 件数・週次推移という集計値のみをヘッドラインに残し、個別の内容は(必要なら)展開時にのみ表示する二次情報とする |

---

## 3. 「成長ログ」という、コンセプトへの、具体的な、当てはめ方

### 3.1 `/timeline`との違いの明確化(依頼書が要求した意識合わせ)

| | `/timeline` | 成長ログ(本タスクで設計) |
|---|---|---|
| 対象 | **記憶の内容**(event/state/trait、Temporal Layer) | **測定指標・システムの状態**(RC/Grounding/Drive/自己改善パイプライン/Safety) |
| 「変化」の意味 | 「海星さんについて、何を覚えているか」がどう更新されたか | 「シグマリス自身が、どれだけ機能的に成長・安定してきたか」がどう推移したか |
| データソース | `user_fact_items`・`sigmaris_user_preference_patterns` | `sigmaris_cycle_health_runs`・`sigmaris_grounding_health_runs`・D〜Fの各テーブル |
| 更新頻度 | 会話のたびに(ほぼリアルタイム) | **測定スクリプトを手動実行した時のみ**(0章の発見、3.2節で詳述) |

両者は「時系列で何かを見せる」という点で似ているが、**`/timeline`は"記憶の内容そのもの"、成長ログは"記憶やシステムを扱う仕組み自体の性能・健全性"** という、対象が根本的に異なる。依頼書の言葉を借りれば、`/timeline`は「シグマリスが何を覚えているか」、成長ログは「シグマリスが、どれだけうまく機能しているか」を見せる。

### 3.2 【最重要】「成長ログ」を成立させる前提条件(0章の発見の影響)

RC・Grounding指標の測定、D〜Fパイプラインの各段階、Safetyのスキャンは、**いずれも自動スケジューラに登録されておらず、運用者が手動でCLIを実行した時にしか、新しい記録が増えない。** これは「成長ログ」というコンセプトの根幹(時間の経過とともに、データが積み上がっていく)に、直接影響する重要な制約である。

- **現状のまま実装した場合**: グラフのX軸(時間)上に、実際にCLIを実行した日だけ、飛び飛びに点が打たれる形になる。「週を追うごとにどう変化しているか」を滑らかな推移として見せる、という依頼書3章の要望を、額面通りには満たせない可能性が高い。
- **選択肢A(本タスクでは採用、Vis-2への申し送り)**: 現状のまま、**「記録がある時点だけを、正直にプロットする」**設計にする。データが疎であること自体を隠さず、「最終計測日: {日付}」を明示し、間隔が空いている場合は、グラフ上で明確に分かるようにする(例: 点と点を直線で結ばない、または結ぶ場合は破線にする等)。**判断根拠**: 依頼書1章「コードの実装を行わない」という制約上、本タスクではスケジューラへの統合を提案するに留め、実装はしない。無理に滑らかな推移に見せかけることは、Safety-1〜3が一貫して守ってきた「できていないことを、できているかのように装わない」という原則に反する。
- **選択肢B(将来の別タスクとして提案)**: `proactive/scheduler.py`に、これらの測定スクリプトを定期実行するジョブを追加する。これ自体は独立したタスクの規模になる(判断根拠: RC-5・Grounding指標のいずれも、報告書自身が「定期実行の仕組みは未整備」と明記済みであり、通知の要否・実行時刻の設計等、本タスクの範囲を超える検討が必要)。**成長ログが実用的な"推移"を見せられるようになるための、事実上の前提条件として、Vis-2以降、または独立タスクでの対応を強く推奨する。**

### 3.3 「成長」を、具体的にどう可視化するか(選択肢Aの範囲内での提案)

1. **RC-1 eligible_completion_rate・RC-2 score・Citation Precision・Contradiction Rateの折れ線(実行日ごとの点)**: `/timeline`のevent週次棒グラフと同じRechartsを再利用する想定。ただし週次バケットではなく、**実際の実行日をそのままX軸に使う**(3.2節、データが疎であることを隠さないため)。
2. **自己改善パイプラインの"活動量"の推移**: `sigmaris_hypotheses`・`sigmaris_code_diff_proposals`等の`created_at`を使い、「週ごとに、何件の仮説が生成され、何件が承認・PR化されたか」を積み上げ棒グラフで見せる。これは`/timeline`のevent週次グラフと最も似た性質を持つが、**対象がユーザーの記憶ではなく、シグマリス自身の自己改善活動である**という点で、明確に区別できる。
3. **Drive Stateは、"推移"を持てない(3.2節の制約と別の、1.3節で述べた構造的な制約)**。現状のまま実装するなら、**「現在のスナップショットのみ」**を表示し、時系列グラフの対象からは外す。将来的にDrive Stateの履歴を残したい場合、`get_current_drive_state()`の呼び出し結果を都度どこかへ記録する、新しい永続化の仕組みが必要になる(これも独立した検討課題として申し送る)。
4. **Safety Governance Statusの推移**: Safety-3がRC計測基盤に統合したことで、`sigmaris_cycle_health_runs`の各行が`safety_governance_status`を持つ。RC-1/RC-2と同じ実行日ベースの点として、「過去に`gap_detected`になったことがあるか」を示すマーカー(通常は稀にしか発生しないはずなので、折れ線よりは「発生履歴のバッジ一覧」のような見せ方が適切と考える)。

---

## 4. 画面構成の、大まかな、設計案

依頼書の指示通り、詳細なUIデザインではなく、情報設計(何を・どこに・どう並べるか)に留める。

### 4.1 全体構成(上から下への優先順位)

```
┌─────────────────────────────────────────────┐
│ セクション1: 総合ステータス(3〜4枚のバッジ/カード)     │
│  [RC-5: healthy]  [Safety: healthy]            │
│  [承認待ち: 2件]   [直近の測定日: 3日前]         │
├─────────────────────────────────────────────┤
│ セクション2: Drive State(現在のスナップショット)      │
│  Knowledge Gap ▓▓▓▓▓░░░░░ 0.52                 │
│  Mastery       ▓▓▓░░░░░░░ 0.31 (RC計測ベース)   │
│  Coherence     ▓▓▓▓▓▓░░░░ 0.64                 │
├─────────────────────────────────────────────┤
│ セクション3: 応答品質の推移(折れ線、実行日ベース)      │
│  Citation Precision / Contradiction Rate         │
│  (直近の値 + 過去の実行日ぶんの推移)             │
├─────────────────────────────────────────────┤
│ セクション4: 循環の健全性の推移(折れ線、実行日ベース)   │
│  RC-1 / RC-2(RC-5のstatusはセクション1に既出)   │
├─────────────────────────────────────────────┤
│ セクション5: 自己改善パイプラインの活動量            │
│  週次の積み上げ棒グラフ(生成→検証→承認→PR)       │
│  + 「今、確認が必要なもの」への導線(件数バッジ)    │
├─────────────────────────────────────────────┤
│ セクション6: 直近の自発的な行動(履歴リスト、5〜10件)  │
│  [success] 知識ギャップの言語化 ── 3日前         │
│  [unresolved] ... ── 5日前                       │
└─────────────────────────────────────────────┘
```

### 4.2 各セクションの判断根拠

- **セクション1を最上部に置く判断根拠**: 依頼書の最優先事項(「一目で把握」)に最も忠実に応えるのが、このセクションである。バッジ形式(色付きの短いラベル)にとどめ、詳細はスクロールした先で見る、という優先順位づけにした。
- **セクション2(Drive State)を、推移グラフより上に置く判断根拠**: 3.3節で述べた通り、Drive Stateは推移を持てないため、他の推移グラフ群とは性質が異なる。「現在の状態」という性質を明確にするため、時系列セクション群(3〜5)より前に、独立したセクションとして配置した。
- **セクション5に「確認が必要なもの」への導線を含める判断根拠**: 依頼書2章の「一目で把握するために本当に必要な指標」という基準に照らすと、"承認待ちが何件あるか"は、単なる状態の表示以上に、**行動を促す情報**である。既存の`review_diff_proposals.py`・`run_migration_review_queue.py`への導線(実際のレビューは、引き続きCLIで行う想定、5章参照)として、件数バッジからリンクさせる設計を提案する。
- **セクション6(自発的な行動履歴)を最下部に置く判断根拠**: 個別の行動ログは、他のセクションに比べて情報の粒度が細かく、「一目で把握する」というより「気になったら詳細を見る」性質のものであるため、最も下に配置した。

---

## 5. `/admin/memory`・`/timeline`との、役割分担の、整理

| 観点 | `/admin/memory` | `/timeline` | 成長ログ(本タスク) |
|---|---|---|---|
| 対象読者 | 開発者(海星さん自身がデバッグする用途) | 海星さんが利用者として眺める用途 | 海星さんが「シグマリスの調子」を確認する用途 |
| 見せる対象 | `user_fact_items`の生データ | 記憶の内容(event/state/trait) | システムの測定指標・健全性状態 |
| 「変化」の主役 | なし(スナップショットのテーブル) | 記憶の内容の変遷 | シグマリス自身の機能的な成長・安定度の推移 |
| データの更新頻度 | 会話のたびに | 会話のたびに | **測定スクリプトの手動実行時のみ**(3.2節の制約) |
| ナビゲーション | 意図的に`navItems`から除外(既存の判断を維持) | `navItems`に追加済み | **`navItems`への追加を推奨**(依頼書の目的「一目で把握できる場所」に、日常的にアクセスできる必要があるため) |
| 実際のレビュー・承認作業 | — | — | **行わない**。E-4・F-1〜F-3の承認は、引き続き既存のCLI(`review_diff_proposals.py`等)が担う。成長ログは「件数の把握と、CLIへの導線」に徹する(判断根拠: 既存のF-3が確立した、承認は必ず人間の明示的なCLI操作を経る、という絶対原則を、フロントエンド側から弱めないため——ボタン一つでの承認operationをフロントエンドに実装することは、本タスクは提案しない) |

**判断根拠(成長ログを`navItems`に追加すべきと考えた理由)**: 依頼書の背景が「一目で把握できる場所が存在しない」ことを課題として明示している以上、既存の`/timeline`同様、日常的にアクセスできるナビゲーション上の位置づけが必要だと判断した。ただし、これは実装(Vis-2)側の判断でもあるため、本タスクでは提案にとどめる。**副次的な実装上の注意点として記録する**: 現在のモバイル下部ナビは`grid-cols-4`(`/chat`・`/memory`・`/timeline`・`/settings`)であり、5つ目の項目を追加する場合、`grid-cols-5`への変更、またはドロワー化等のレイアウト再検討が、Vis-2で必要になる。

---

## 6. 今後(Vis-2)に向けた申し送り事項

1. **【最重要、3.2節】測定スクリプトの定期実行が未整備であることが、成長ログの実用性そのものを左右する。** Vis-2の実装着手前、または並行して、`proactive/scheduler.py`への統合を検討することを強く推奨する。これを行わないまま実装すると、「グラフを開いても、点が数個しかない」という、依頼書の意図(成長の推移を見せる)から外れた画面になるリスクが高い。
2. **Drive Stateには、履歴を残す仕組みが存在しない(1.3節・3.3節)。** 「現在のスナップショットのみ」として実装するか、別途、Drive State自体の記録テーブルを新設するか(スコープ拡大になるため独立した判断が必要)、Vis-2着手前に方針を決める必要がある。
3. **セクション5(自己改善パイプラインの活動量)の実データでの見え方は、この環境からは確認できていない。** D〜Fの各段階が、実際にどの程度の頻度で仮説を生成・処理しているかは、運用開始後の実データを見てから、表示の粒度(週次か、月次か等)を調整する余地がある。
4. **本タスクは、依頼書の指示通り、コード実装を一切行っていない。** レイアウト案(4章)は、既存の`/timeline`が確立した`AppShell`・カード・Rechartsという技術スタックを前提にしたものであり、Vis-2での詳細なコンポーネント設計・実データでの動作確認が、次の自然なステップになる。

---

# 測定スクリプトの定期実行化 実施報告(Phase Vis-2の前提条件)

**作業ブランチ:** `schedule-measurement-jobs-vis2-prereq`(mainから新規作成)
**範囲:** Vis-1(申し送り事項1)が発見した、RC-1〜RC-5・Phase G指標・Safety Governanceの測定スクリプトが、いずれも定期実行に登録されていないという前提条件の欠落を解消する。既存の`proactive/scheduler.py`に3件の新規ジョブを追加した。**新しい測定ロジックは一切追加していない**——既存の`run_cycle_health.py`・`run_grounding_health.py`・`scan_safety_critical_files.py`が確立済みの計測・スキャン関数を、そのまま呼び出すだけの、薄いラッパーである。

---

## 7. 各ジョブの、登録内容(頻度、時間帯、判断根拠)

`backend/app/services/proactive/scheduler.py`に、以下3件を追加した(既存の20ジョブには一切手を加えていない)。

| ジョブID | 頻度 | 時刻(JST) | 呼び出す既存ロジック |
|---|---|---|---|
| `cycle_health_measure` | 毎日 | 3:20 | `cycle_health_runner.run_cycle_health()` → `cycle_health_runs_store.record_cycle_health_run()`(RC-1〜RC-5、および6章で統合済みのSafety Governance判定を含む) |
| `grounding_health_measure` | 毎週日曜 | 5:40 | `grounding_health_runner.run_grounding_health()` → `grounding_health_runs_store.record_grounding_health_run()`(Citation Precision・Search Trigger Rate・Contradiction Rate) |
| `safety_governance_scan` | 毎週日曜 | 5:45 | `safety_critical_files_scan.find_unregistered_gate_files()`(DB記録なし、ログのみ。判断根拠は8.2節) |

### 7.1 時刻選定の判断根拠

**`cycle_health_measure`(毎日3:20)**: 依頼書が例示した「3時台」をそのまま採用した。既存の深夜帯ジョブは`memory_embed`(3:00)のみであり、その20分後という配置にした。**判断根拠**: `memory_embed`(fact embeddingの再計算)と`cycle_health_measure`(experience/fact/chat_messagesの読み取りを伴う、複数回のDB往復を要する処理、`phase_r_report.md`が既に「重い処理」と明記)は、いずれもDB負荷を伴うため、完全に同時刻(3:00ちょうど)に重ねることは避け、20分の間隔を空けた。次の日次ジョブ(`curiosity_search`、6:15)までは約3時間の余裕があり、深夜帯の中でも特に他ジョブが存在しない時間帯である。

**`grounding_health_measure`・`safety_governance_scan`(毎週日曜、5:40・5:45)**: 依頼書は「B2週次統合バッチ(日曜早朝)と近い時間帯に配置することを検討する。ただしB2自体と時間が重ならないよう注意する」と指示していた。既存のB2週次チェーンを実際に確認した結果、`experience_analyze`(4:00)から`self_interest_queries`(5:30)まで、10件のジョブが5分〜30分間隔で密集して連続実行される設計になっていることを確認した(8.2節で全件挙げる)。**判断根拠(チェーンの直後に配置した理由)**: このチェーンの最中に割り込ませると、既存のB2ジョブ群のいずれかと時間的に重なるリスクが高い(依頼書の禁止事項に直接抵触する)。そのため、チェーンが完全に終了した後(`self_interest_queries`の5:30)に、10分の間隔を空けて配置した。「近い時間帯」という依頼書の要望(判断根拠: 週次の測定は、他の週次バッチ処理と同じ"週の節目の作業"として、運用上まとめて把握しやすい)と、「重ならない」という制約の、両方を満たす配置だと判断した。

**`grounding_health_measure`を`safety_governance_scan`より先に置いた判断根拠**: 両者に処理順序の依存関係はないが、DB書き込みを伴う`grounding_health_measure`(相対的に重い)を先に、ファイルシステムの読み取りのみで完結する`safety_governance_scan`(相対的に軽い、Safety-3報告書が実測済み)を後に置くことで、万一前者が長引いた場合でも、後者との重なりを最小限にできると判断した。

---

## 8. 既存ジョブとの、時間帯の、重複確認結果(要件2・3)

### 8.1 機械的な確認方法

実際に`startup_scheduler()`を呼び出し、`AsyncIOScheduler.get_jobs()`で全23件のジョブの`CronTrigger`を取得し、`(day_of_week, hour, minute)`の組が1件も重複していないことを、テストで直接検証した(`heartbeat`は毎分実行のため、性質上この比較の対象外とした——13章参照)。

### 8.2 既存ジョブの全体像(実測、新規3件を含む)

```
毎日:
  03:00  memory_embed
  03:20  cycle_health_measure          [新規]
  06:15  curiosity_search
  06:30  memory_validate
  06:45  health_sync
  07:00  research
  08:00  morning_briefing
  22:00  evening_checkin

毎週月曜:
  06:00  trend_analyze

毎週日曜(B2週次統合バッチ、既存の連続チェーン):
  04:00  experience_analyze
  04:30  decision_analyze
  04:35  goal_alignment_extract
  04:45  preference_pattern_extract
  04:50  adoption_count_recompute
  04:55  episode_consolidate
  05:00  narrative_generate
  05:15  knowledge_graph_extract
  05:25  memory_snapshot_generate
  05:30  self_interest_queries
  05:40  grounding_health_measure      [新規]
  05:45  safety_governance_scan        [新規]
  20:00  weekly_review

(毎分: heartbeat)
```

**確認できたこと**: 新規3件は、いずれも既存ジョブの時刻と1分も重ならない。`grounding_health_measure`・`safety_governance_scan`は、B2週次チェーンの末尾(5:30)から10分・15分後に位置し、チェーン本体には一切割り込んでいない。次の日次ジョブ(`curiosity_search`、6:15)までは、35分・30分の余裕を残している。

---

## 9. エラーハンドリングの、実装内容(要件4)

既存の`_memory_validate()`・`_episode_consolidate()`等と、**全く同じ形の、try/except一段構えのfire-and-forgetパターン**をそのまま踏襲した。新しいエラーハンドリングの仕組みは、一切追加していない。

```python
async def _cycle_health_measure() -> None:
    from app.services.cycle_health_runner import run_cycle_health
    from app.services.cycle_health_runs_store import record_cycle_health_run
    try:
        jwt = await get_sigmaris_jwt()
        result = await run_cycle_health(jwt=jwt)
        ...
        run_id = await record_cycle_health_run(...)
        logger.info(...)
        if rc5["status"] == "break_detected":
            logger.warning(...)
        if safety_gov["status"] == "gap_detected":
            logger.warning(...)
    except Exception:
        logger.exception("Cycle health job raised unexpectedly")
```

**判断根拠(3ジョブとも、例外は`logger.exception()`で記録するのみで、再送出・通知は行わない)**: これはRC-5・Grounding指標が、報告書自身で明記した既存の判断(誤報リスクを避けるため通知は見送り、`get_notifier()`はいつでも統合できる状態にしておく)と、完全に一致する。今回のスケジューラ統合でも、この判断を変更する理由はないと考えた——依頼書自体も「通知」を要件に含めていない。

**要件4「各ジョブの失敗が、他の機能・ジョブに波及しないこと」の直接証明**: `AsyncIOScheduler`は、各ジョブを独立したコルーチンとして実行するため、構造的にも1つのジョブの例外が他のジョブの実行を妨げることはない(APScheduler自体の性質)。加えて、各関数内部でも`try/except`により例外を握りつぶしているため、**二重に**波及を防いでいる。この二重の保証を、実際に各ジョブ関数へ例外を注入するテストで直接検証した(11章)。

**`safety_governance_scan`にDB書き込みを含めなかった判断根拠**: 毎日の`cycle_health_measure`が、既にSafety-3で統合済みの`safety_governance_status`を`sigmaris_cycle_health_runs`へ記録している(Safety-3、`docs/sigmaris/safety_governance_report.md` 13章)。週次の`safety_governance_scan`まで同じテーブルへ書き込むと、1週間のうち特定の1日(日曜)だけ、同じテーブルに1日2回分の`safety_governance_status`が記録される状態になり、後からデータを読む際に紛らわしいと判断した。**本ジョブの独自の意義は、`cycle_health_measure`が(RC-1〜5計測の途中の、無関係な理由による例外で)失敗した日でも、このスキャンだけは独立して実行され続けることにある**——依頼書の言葉「状況確認」に忠実に、ログへの記録のみで完結させた(判断根拠、独断で決めた箇所として明記する)。

---

## 10. テスト結果

`test_schedule_measurement_jobs.py`として13件の新規テストを作成した(scratchディレクトリ)。

```
SchedulerRegistrationTests (6件、要件1・2・3への直接対応)
  PASS: cycle_health_measureが、毎日3:20に登録されること
  PASS: grounding_health_measureが、毎週日曜5:40に登録されること
  PASS: safety_governance_scanが、毎週日曜5:45に登録されること
  PASS: 新規3件を含む、全23ジョブが登録されていること
  PASS: 【重要】heartbeatを除く、いずれの2ジョブも、トリガー時刻
        (曜日・時・分)が重複していないこと(実際にstartup_scheduler()
        を呼び出し、実測で確認)
  PASS: 【重要】新規3件が、B2週次チェーン(4:00〜5:30)・毎日6:15の
        curiosity_searchのいずれとも、時間帯が重ならないこと

JobFailureIsolationTests (4件、要件4への直接対応)
  PASS: cycle_health_measure内でrun_cycle_health()が例外を送出しても、
        _cycle_health_measure()自体は例外を伝播させないこと
  PASS: 同上、jwt取得自体が失敗した場合も同様
  PASS: grounding_health_measure内でrun_grounding_health()が例外を
        送出しても、例外を伝播させないこと
  PASS: safety_governance_scan内でスキャン自体が例外を送出しても、
        例外を伝播させないこと

JobSuccessPathTests (3件、要件「可能な範囲で正常実行を確認する」)
  PASS: cycle_health_measureが、run_cycle_health()の結果を正しい形で
        record_cycle_health_run()へ渡すこと
  PASS: grounding_health_measureが、同様に正しい形で
        record_grounding_health_run()へ渡すこと
  PASS: 【実データに近い検証】safety_governance_scanを、モックなしで
        実際のbackend/ツリーに対して実行し、例外なく完了すること

13 passed
```

既存の`backend/tests/`・これまでの全scratchテスト一式(Safety-1〜3・Phase Vis-1を含む)を再実行し、リグレッションが無いことを確認した。**既存20ジョブの登録・トリガー設定には一切変更を加えていない**——テスト内で全23ジョブのトリガーを実測した際、既存20ジョブの値が、変更前のソースコード(9章のコードブロック追加前)と完全に一致することも確認した。

```
13(本タスク) + 526(既存、Phase Vis-1まで) = 539 passed, 7 subtests passed(合算実行)
```

**実際のスケジューラを、本番相当の長時間で稼働させての検証(実際に3:20・日曜5:40等を迎えて実行されることの確認)は、この環境では不可能である**(セッション時間・実時計に依存するため)。代わりに、`AsyncIOScheduler`を実際に起動し、`get_jobs()`で登録されたトリガーの実測値を直接検証する(10.1節)ことで、**「登録が正しいこと」は実測レベルで確認し、「実際にその時刻が来たら発火すること」はAPScheduler自体の既存の信頼性に委ねた**——これは、他の20件の既存ジョブについても、これまで一度も個別の発火タイミング自体をテストしてこなかった、このコードベース一貫の検証範囲と同じである。マイグレーションは不要(新しいテーブル・列を追加していない、既存の`sigmaris_cycle_health_runs`・`sigmaris_grounding_health_runs`をそのまま使う)。

---

## 11. 気づいた懸念点・次のステップ(Vis-2: フロントエンド実装)に向けた申し送り事項

1. **【最重要】Vis-1が指摘した「成長ログの前提条件」は、本タスクで解消された。** これにより、Vis-2が実装するグラフは、今後は日次・週次でデータが積み上がっていく状態になる。**ただし、本タスクの適用直後は、まだ実行回数が0〜数回しかない状態から始まる**——Vis-2の実装・実データでの見た目確認は、本タスクの適用から、ある程度の日数(理想的には数週間)が経過した後に行うことを推奨する。
2. **`safety_governance_scan`と`cycle_health_measure`の両方が、Safety Governanceの状態を把握できる状態になったが、記録場所は`cycle_health_measure`(日次)のみに絞った(9章)。** Vis-2でSafety Governance Statusを表示する際は、`sigmaris_cycle_health_runs.safety_governance_status`(日次の記録)を参照すればよく、週次の`safety_governance_scan`はログ(サーバーの標準出力・ログファイル)以外に確認手段がないことに注意が必要——フロントエンドから見える形にするには、この週次スキャン結果も何らかの形で永続化する設計変更が、将来必要になる可能性がある(本タスクでは、依頼書の「状況確認」という位置づけ通り、ログのみに留めた)。
3. **`window_days`はいずれも、既存スクリプトのデフォルト値(30日)をそのまま使った。** 毎日実行されるようになった`cycle_health_measure`が、30日分のデータを毎回読み直す設計のままでよいか(パフォーマンス・DB負荷の観点)は、実際の運用データ量が増えてきた段階で見直す余地がある——本タスクでは、依頼書が明示的に要求していない範囲であるため、変更しなかった。
4. **通知(Pushover等)への統合は、依頼書の要件に含まれておらず、本タスクでも実装していない(9章)。** RC-5・Safety Governanceのいずれかが異常を検知した場合、現状は次の項目(2)同様、ログ・DBの記録でしか気づけない。Vis-2でフロントエンド画面ができれば、海星さんが能動的に確認できるようになるが、それまでの間は、サーバーログを直接見る以外の検知手段がない状態が続く。
5. **Phase D〜Fのpending件数は、依頼書の指示通り、本タスクの定期実行には含めていない。** Vis-2が、表示のたびに直接集計する設計のままで問題ないことを、実装時に改めて確認してほしい。

---

# Phase Vis-2 実施報告: フロントエンド実装(フロントエンド成長ログ、最終ステップ)

**作業ブランチ:** `phase-vis2-frontend-implementation`(mainから新規作成)
**範囲:** Vis-1が選定した5指標(RC-5状態、Citation Precision + Contradiction Rate、Drive Stateスナップショット、自己改善パイプラインの承認待ち件数、Safety Governance状況)を、実際のフロントエンド画面として実装した。これをもって、安全性・ガバナンスの柱に続く、Phase Vis(フロントエンド成長ログ、Vis-1〜Vis-2)全体が完了する。

---

## 12. ページ構成(新規ページか、既存への統合か、その根拠)

**新規ページ`/growth`として実装した。** Vis-1(5章)が既に「`navItems`への追加を推奨」と結論づけていたが、これは実装(Vis-2)側の判断として申し送られていたため、本タスクで正式に決定し、その根拠をここに記す。

**判断根拠**:
1. **対象が根本的に異なる**。`/timeline`は「記憶の内容(event/state/trait)がどう変遷したか」を見せるページであり、本タスクが実装する内容は「シグマリス自身の機能的な健全性・状態」を見せるものである。Vis-1(3.1節)が既にこの区別を明確にしており、既存ページへ無理に統合すると、この対象の違いが画面上で曖昧になると判断した。
2. **データソースが完全に分離している**。`/timeline`は`user_fact_items`・`sigmaris_user_preference_patterns`を参照するが、本タスクは`sigmaris_cycle_health_runs`・`sigmaris_grounding_health_runs`・Drive State(ライブ計算)・`sigmaris_migration_review_queue`・`sigmaris_code_diff_proposals`という、全く異なる5系統のデータソースを参照する。1つのページに混在させると、既存の`/timeline`の`fetchAgentJson`呼び出し(2件)に、性質の異なる4件を追加することになり、ページの読み込み時間・責務が肥大化すると判断した。
3. **`/admin/memory`が意図的に`navItems`から除外されている一方、`/timeline`は追加されている、という既存の判断パターンとの整合性**。本タスクの対象読者は「海星さんが、利用者としてシグマリスの調子を確認する」ことであり(Vis-1 5章の表)、`/admin/memory`(開発者向け)ではなく`/timeline`と同じ「日常的にアクセスする一般ページ」の性格に近いと判断した。

**実装した副次的な変更(Vis-1 5章が予告していた通り)**: `app-shell.tsx`の`navItems`に5件目(`/growth`)を追加し、モバイル下部ナビの`grid-cols-4`を`grid-cols-5`へ変更した。アイコンは`lucide-react`の`ActivityIcon`(既存の`MessageSquareMoreIcon`・`BrainCircuitIcon`・`HistoryIcon`・`Settings2Icon`と同じライブラリ)を採用した——判断根拠: 心拍・健全性を直感的に想起させるアイコンであり、本ページの「調子を確認する」という性格に合致すると判断した。

---

## 13. 各指標の、表示方法の実装詳細

### 13.1 新規ページの構成(3セクション、5指標)

依頼書が明示した5指標を、Vis-1の設計(4章)を踏まえつつ、以下の3セクションに集約した。

| セクション | 含む指標 |
|---|---|
| 総合ステータス(4枚のカード) | ① RC-5状態(RC-1/RC-2の直近値を補足として併記) ・ ⑤ Safety Governance状況 ・ ④ 承認待ち件数 ・ 直近の測定日 |
| Drive State | ③ Knowledge Gap・Mastery・Coherenceのスナップショット(進捗バー) |
| 応答品質の推移 | ② Citation Precision + Contradiction Rateの、直近値+折れ線グラフ |

**判断根拠(RC-1/RC-2を独立セクションにしなかった理由)**: 依頼書が明示した5指標には、RC-1/RC-2の推移グラフは含まれていない(Vis-1の元の6セクション案から、本タスクの依頼書が意図的に絞り込んだものと解釈した)。Vis-1自身も「RC-5のstatusはセクション1に既出」と述べていたため、RC-1/RC-2は、RC-5バッジに添える一行の補足数値(`RC-1: 82% ・ RC-2: 91%`)にとどめ、独立したグラフは実装しなかった——要件4「詳細すぎる情報は含めない」への忠実な対応。

### 13.2 RC-5(循環破損検知)

`rc5StatusDisplay()`(`lib/growth/transform.ts`)が、`healthy`→「健全」(緑)・`break_detected`→「注意」(オレンジ)・`insufficient_history`→「測定中(履歴不足)」(グレー)・値なし→「未測定」(グレー)、の4状態に対応するラベル・トーンを返す。**`insufficient_history`を「健全」と混同しない**、というPhase R-3以来一貫した設計判断を、表示側でも踏襲した。

### 13.3 Citation Precision + Contradiction Rate

直近1件の値を、パーセント表示で強調(`直近のCitation Precision: 90%`)した上で、`sigmaris_grounding_health_runs`の直近30件を使い、`TrendLineChart`(Rechartsの`LineChart`をラップした新規コンポーネント、`/timeline`の`EventVolumeChart`と同じ配色・実装パターン)で2本の折れ線として表示する。**値がnullの点(検証対象0件だった実行)は、`connectNulls={false}`により、グラフ上で明示的に途切れさせる**——0%と「未測定」を混同しないという、Phase R/G全体の設計判断を、可視化でも一貫させた。

### 13.4 Drive Stateスナップショット

Vis-1の設計(3.3節「Drive Stateは推移を持てない」)通り、**時系列グラフの対象からは外し**、`/timeline`の`ConfidenceBar`と同じ見た目の進捗バー(`DriveLevelBar`)3本で、現在値のみを表示する。Masteryは`has_data=false`(RC計測が一度も実行されていない場合)のとき、バーを0%表示にする代わりに「(RC計測が未実行)」という注記を添え、値なしと0%を区別した。

### 13.5 承認待ち件数

E-4(`sigmaris_migration_review_queue`)・F-1〜F-3(`sigmaris_code_diff_proposals`)、それぞれの`review_status="pending"`件数を合算し、内訳とともに表示する。**判断根拠(件数のみで、個別の提案内容は表示しない)**: Vis-1(4.2節)が既に「実際のレビュー・承認作業は行わない」と方針を定めており、本タスクもこれをそのまま踏襲した——このカードは、リンクやボタンを持たない、純粋な件数表示にとどめた(13.6節で、リンクを設けなかった判断根拠を詳述する)。

### 13.6 Safety Governance状況

14章で詳述する。

---

## 14. Safety Governanceの、データ取得方法(要件2)

依頼書1章が明示した通り、「週次スキャン(`safety_governance_scan`)自体はログのみで、日次の`cycle_health_measure`のDBレコードから参照する必要がある」という、前回タスク(測定スクリプトの定期実行化、11章2項)の申し送りに、正確に従って実装した。

- 新設バックエンドエンドポイント`GET /api/agent/growth/cycle-health`が、`cycle_health_runs_store.get_recent_cycle_health_runs()`をそのまま呼び出し、`sigmaris_cycle_health_runs`の直近30件を返す。
- フロントエンドは、この配列の**先頭(最新)1件**の`safety_governance_status`列を参照し、`safetyGovernanceStatusDisplay()`で「健全」/「要確認」/「未測定」のいずれかに変換して表示する。
- `safety_governance_unregistered_count`が1件以上の場合、「未登録候補: N件」という補足を、バッジの下に追加表示する——具体的なファイル名までは表示しない(Vis-1が定めた「詳細すぎる情報は含めない」方針、これらのファイル名を確認したい場合は、引き続き`scripts/scan_safety_critical_files.py`を運用者が直接実行する想定)。

**週次の`safety_governance_scan`(ログのみ)自体は、本タスクでも一切参照していない。** 参照する手段がそもそも存在しない(DBに書き込まれていないため)ことを、実装前に再確認した上で、依頼書の指示通り、日次の`cycle_health_measure`の記録のみをデータソースとした。

---

## 15. テスト結果

### 15.1 バックエンド: `test_phase_vis2_growth_endpoints.py`(9件、scratchディレクトリ)

```
AuthGatingTests (3件)
  PASS: エージェント認証ヘッダー欠如で401になること
  PASS: JWT欠如で401になること
  PASS: 誤ったagent secretで403になること
        (既存の/preference-patterns/list等と同じ認証ゲートが機能して
        いることの直接確認)

CycleHealthEndpointTests (2件)
  PASS: get_recent_cycle_health_runs()の結果をそのまま返すこと
  PASS: store層の例外がHTTPException(500)として処理されること

GroundingHealthEndpointTests (1件)
  PASS: get_recent_grounding_health_runs()の結果をそのまま返すこと

DriveStateEndpointTests (1件)
  PASS: 【重要】dataclass(DriveState)をasdict()した結果が、実際に
        json.dumps()可能な、ネストした辞書・リストのみで構成されて
        いること(FastAPIのJSONシリアライズを通る前に、この変換自体が
        正しく機能していることの直接検証)

PendingReviewEndpointTests (2件)
  PASS: E-4・F-1〜F-3、両方の件数が正しく合算されること
  PASS: 両方とも0件の場合、エラーではなく0件として返ること

9 passed
```

既存の`backend/tests/`・これまでの全scratchテスト一式(Safety-1〜3・Phase Vis-1・定期実行化を含む)を再実行し、リグレッションが無いことを確認した。

```
9(本タスク) + 539(既存、定期実行化まで) = 548 passed, 7 subtests passed(合算実行)
```

### 15.2 フロントエンド

```
npx eslint src/app/growth/page.tsx src/lib/growth/transform.ts \
  src/components/growth/trend-line-chart.tsx src/components/app-shell.tsx
→ エラー・警告なし(exit code 0)

npx next build
→ ✓ Compiled successfully
→ ✓ TypeScript型チェック通過
→ ルート一覧に /growth が正しく追加されていることを確認(既存の
  /chat・/timeline・/memory・/settings等、他の全ルートも変更なく
  ビルドされていることを確認)
```

**ビルド中に発見・修正した実装上の問題(2件、判断根拠として記録)**:
1. `TrendLineChart`の型定義`{ label: string } & Record<string, number | null>`が、TypeScriptの構造的型付け上、`label`(string)と`Record<string, number | null>`のインデックスシグネチャが矛盾するというエラーを起こした。`Record<string, string | number | null>`という、より緩い単一のインデックスシグネチャに変更して解消した。
2. Rechartsの`Tooltip`の`formatter`プロップに、独自の型注釈(`(value: number | null) => string`)を明示したところ、Recharts自身の型定義(`ValueType | undefined`を受け取る)と衝突した。型注釈を外し、Recharts側の型推論に委ねる形に変更して解消した。

**実データでの表示確認は行っていない。** この環境には、実際のSupabase・OpenAI API等への接続がないため、依頼書の注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない。`next build`によるビルド成功・型チェック通過・ESLint通過、および9件のバックエンドテストによる、API層のレスポンス形状の検証までが、この環境で確認できる範囲である。

---

## 16. Phase Vis全体(Vis-1〜Vis-2、および前提条件の定期実行化)を通じての、振り返り

### 16.1 何が完成したか

Vis-1(表示指標の選定)→ 測定スクリプトの定期実行化(前提条件の解消)→ Vis-2(フロントエンド実装)という3段階を経て、Phase R・G・S・D〜F・Safetyという、これまで別々のCLI・テーブルに分散していた測定結果が、初めて**日常的にアクセス可能な、1つのフロントエンド画面**(`/growth`)に集約された。

- Vis-1: 5指標への絞り込みと、`/timeline`・`/admin/memory`との役割分担の整理。**「測定スクリプトが定期実行に登録されていない」という、成長ログというコンセプト自体を成立させる前提条件の欠落**を発見したことが、最大の成果だった。
- 定期実行化: Vis-1の発見に正確に対応し、既存の`proactive/scheduler.py`のパターンをそのまま踏襲して、新しい計測ロジックを一切追加せずに、RC-1〜5・Grounding指標・Safety Governanceを定期実行に組み込んだ。
- Vis-2(本タスク): 5指標を、既存の`/timeline`のデザインシステム(`AppShell`・ダーク配色・Recharts)を忠実に踏襲した、新規ページとして実装した。

### 16.2 一貫して守られた設計原則

1. **各段階が、前段階の発見・申し送りに、正確に対応した。** Vis-1が発見した前提条件の欠落 → 定期実行化タスクが正確に解消 → Vis-2がその申し送り(Safety Governanceのデータ取得方法)を正確に実装、という、3タスクを通じた一貫性が保たれた。
2. **新しい判定・集計ロジックを、フロントエンド側に一切実装しなかった。** RC-5のstatus判定・Safety Governanceの状態・Citation Precision等の算出は、全てPhase R/G/Safety-3が既に確立したバックエンドのロジックをそのまま返すだけであり、Vis-2が独自に何かを再計算することはない。
3. **「測定できなかった」ことを、「悪い結果だった」から一貫して区別した。** `insufficient_history`≠healthy、null値≠0%、Mastery`has_data=false`≠0.00、という、Phase R/G全体で守られてきた設計判断を、表示レイヤーでも一切崩さなかった。
4. **既存のデザインシステムからの逸脱を、最小限にとどめた。** 新しい色として導入したのはemerald(健全状態用)のみであり、それ以外は全て`/timeline`が確立した既存のトークン(`#212121`・`#2a2a2a`・`#2f2f2f`・`#9b59b6`・`#8e8ea0`・`#ececec`・`#e07856`)をそのまま再利用した。

### 16.3 残っている懸念事項(総まとめ)

1. **実データでの見た目確認が、一度も行われていない(15.2節)。** 運用開始後、実際に日次・週次のジョブが数回〜数十回実行された段階で、グラフの見え方・カードの情報密度を、改めて確認することを推奨する。
2. **週次の`safety_governance_scan`の結果は、依然としてログにしか残らない(14章)。** `/growth`ページから確認できるのは、日次の`cycle_health_measure`が記録した`safety_governance_status`のみであり、週次スキャン独自の実行結果(9章、定期実行化タスクの判断根拠)は、フロントエンドから見えない状態が続く。
3. **承認待ちカードに、実際のレビューCLIへの導線(リンク)を実装しなかった。** Vis-1(4.2節)は「CLIへの導線」を提案していたが、Webブラウザからターミナルコマンドへ誘導する具体的な手段(コマンド文字列の表示程度にとどめるか、等)が定まっていなかったため、本タスクでは、件数表示のみにとどめた——Vis-3(あれば)で、コマンド例の提示等、軽量な形での導線を検討する余地がある。
4. **通知機能は、Phase R-3・定期実行化タスクから一貫して未実装のままである。** `/growth`ページの実装により、能動的に画面を開けば状態を確認できるようになったが、異常が発生したことを能動的に知らせる仕組みは、引き続き存在しない。
5. **多言語対応は、`/timeline`と同じ水準(日本語/英語の簡易切り替えのみ、他11言語の翻訳辞書ファイルは更新していない)にとどめた。** `/timeline`が確立した「新規ページ固有のラベルは、辞書ファイルを編集せず、ページ内でインラインの`locale === "ja" ? ... : ...`による最小限の分岐にとどめる」という前例をそのまま踏襲した判断であり、既存の13言語対応の一貫性という観点では、将来的に辞書ファイルへの正式な追加を検討する余地がある。
