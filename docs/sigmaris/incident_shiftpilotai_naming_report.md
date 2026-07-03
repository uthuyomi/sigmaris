# インシデント調査・対応報告: 「以前ShiftPilotAIと名乗っていた」発言

**発端:** シグマリスとの会話で、「以前shiftpilotaiと名乗っていたことがあり、それを海星さんに指摘された」という趣旨の発言があった。直近の出来事であるかのように語られたが、要出典・裏取りが必要という報告依頼があった。
**このファイルについて:** 最初の調査(下記1〜3章)は当初チャット内でのみ回答し、ファイルとしてはコミットしていなかった。本タスク(鮮度情報の実装)の依頼書が本ファイルを「前タスクの調査結果」として参照していたため、今回まとめてファイル化した。

---

## 1. この発言は事実に基づいている(幻覚ではない)

コード・git履歴に直接の裏付けがある。

- `backend/app/services/chat_prompts.py`の`rules`に、毎ターン注入される固定ルールとして「あなたの名前はシグマリスです。ShiftPilotAI・shift-pilot-ai・ShiftPilotという名前は絶対に使わないでください。自己紹介を求められたら必ず『シグマリス』と名乗ってください。」が存在する。
- `backend/app/services/orchestrator/response_guard.py`には、LLMが誤ってこれらの名前を出力した場合に強制的に「シグマリス」へ置換する`FORBIDDEN_ASSISTANT_NAME_PATTERN`/`replace_forbidden_assistant_names()`という正規表現ガードが存在する。

git履歴:

| 日付 | コミット | 内容 |
|---|---|---|
| 2026-06-24 | `25ab48f` | `fix: rename ShiftPilotAI to sigmaris in system prompt, add agent_mode` |
| 2026-06-26 | `3df1690` | `Ensure Sigmaris identity in responses` — プロンプト文言強化・`persona_rewriter.py`に「legacy project namesを名乗らせるな」という指示追加・`response_guard.py`に正規表現ガード追加 |

プロジェクトの土台自体が"ShiftPilotAI"として作られ(リポジトリ名`shift-pilot-ai`・パッケージ名`shiftpilotai_backend`はその名残)、2026-06-24にシステムプロンプト側を改名、2日後の06-26にさらに念押しの修正が入っている。1度目の修正だけでは実際にShiftPilotAIと名乗る挙動が再発した(=海星さんが気づいて指摘した可能性が高い)ことを示唆している。

**結論: 「以前ShiftPilotAIと名乗っていた」という内容自体は史実として正しい。**

---

## 2. DBの3テーブル(fact/decision_log/experience)には記録されていない可能性が高い

テーブル作成時期を確認したところ:

- `user_fact_items`: 2026-06-24作成(改名修正と同日)
- `sigmaris_decision_log`・`sigmaris_experience`: 2026-06-28作成(**改名騒動の2日後 — この時点ではまだ存在すらしていない**)

したがって`sigmaris_decision_log`・`sigmaris_experience`にこの件が記録されている可能性は構造的にゼロ(テーブルが存在しなかった)。`user_fact_items`も、`category`列が`profile`/`health`/`lifestyle`/`environment`/`devices`/`preferences`/`relationships`/`finance`/`goals`に限定されており、「シグマリス自身の名乗り方の履歴」という海星さんについての事実ではなく**シグマリス自身についての事実**を保存する設計になっていない。

（この3テーブルへの実際の検索は、依頼当初から一貫してSUPABASE_SERVICE_ROLE_KEY等の認証情報がローカル環境に一切なく、サーバーへのSSHアクセスもないため実行できていない。今回の鮮度情報修正タスクの際にも改めて確認したが、状況は変わっていない。予測では0件だが、確認は運用者側にお願いしたい。）

---

## 3. 最有力の原因: `sigmaris_self_model.identity_statement`の鮮度情報欠落(今回修正)

`self_model.py`はシグマリス自身の自己記述(`identity_statement`、1〜3文の自由記述テキスト)を保持するテーブルで、`orchestrator/service.py::_build_self_model_context()`により**毎ターン無条件で**(類似度検索も鮮度チェックもなく)システムプロンプトに`[シグマリス自己認識]`として注入されていた。DBには`last_reflected_at`(最終更新日時)が実際に保存されていたが、この関数には一切渡されていなかった。

もし`identity_statement`のどこかの更新タイミングで「私はかつてShiftPilotAIと呼ばれていたが、シグマリスに改名された」という趣旨の一文がLLMによって書き込まれていた場合、それ以降**いつの情報かという手がかりを完全に失ったまま**毎ターン注入され続けることになる。これは海星さんの仮説「プロンプト構築時に鮮度情報が失われている」に正確に一致するが、原因箇所はRAG検索(`search_relevant_memories`)ではなくこの`self_model`の自己記述だった。

### 追加で判明した事実: `identity_statement`はおよそ毎日更新されている

`heartbeat.py::_check_self_reflect_due()`を確認したところ、`last_reflected_at`から24時間以上経過すると`self_model.py::reflect()`が呼ばれ、`identity_statement`を**LLMが「現在の自己記述」を入力として再生成**する設計になっていた(`heartbeat`ジョブは毎分実行されるcronで、条件成立時にディスパッチされる)。つまりこのテキストは静的な一度きりの記述ではなく、およそ日次で「前回の自己記述を土台にLLMが書き直す」形で継続的に進化している。

これは今回の現象の説明力をむしろ強めている: 6月下旬の改名騒動そのものの文言が一言一句残っていなくても、「自分の過去についての語り」という要素が一度自己記述に混入すると、以後の毎日の再生成サイクルでその「自分史」的な内容が古い情報だと明示されないまま引き継がれ続ける、という構造的なリスクがあったと考えられる。

---

## 4. 実装内容: `_build_self_model_context()`への鮮度情報追加

### フォーマット

`backend/app/services/orchestrator/service.py`に`_format_self_model_freshness()`を新設し、`_build_self_model_context()`の先頭行に埋め込んだ。

```
[シグマリス自己認識] (最終更新: 本日)
{identity_statement}

[シグマリス自己認識] (最終更新: 10日前 — 古い情報である可能性が高いため、現在進行中の出来事であるかのように話さないこと)
{identity_statement}

[シグマリス自己認識] (最終更新: 不明 — 古い情報の可能性があるため断定的に話さないこと)
{identity_statement}
```

判断根拠:

- **相対表現(「N日前」)を採用し、絶対日付は使わなかった。** 絶対日付(例: 2026-07-06)だけを渡すと、LLMが別途「今日が何日か」(`chat_prompts.py`の`time_instruction`)と突き合わせて経過日数を自分で計算する必要があり、推論の手間がある分だけ見落とされるリスクが上がると判断した。相対表現なら「これは古いかもしれない」という判断がその場で完結する。
- **日単位(calendar-day差分、Asia/Tokyo基準)に丸め、時・分単位の情報は含めない。** Phase A2でシステムプロンプトのキャッシュ効率化(分単位で変化する現在時刻をプロンプト末尾に隔離)を行った経緯があるため、新たに分単位で変わる値を`base_system`(プロンプトの前方寄りの位置)に混ぜないよう配慮した。
- **経過7日以上の場合、明示的な警告文("古い情報である可能性が高いため、現在進行中の出来事であるかのように話さないこと")を追加した。** 単に日数を示すだけでは、LLMがその数字の意味(「これは古い」)を正しく解釈するとは限らないため、直接的な指示文を添えた。
- **`last_reflected_at`が欠落・NULL・パース不能な場合は「不明」として保守的に扱い、常に「断定的に話さないこと」という注意書きを付けた。** クラッシュさせず、かつ「鮮度不明だから安全側に倒す」という一貫した方針にした。

### キャッシュ効率への影響

`chat_prompts.py`のプレフィックスキャッシュ順序コメントに既に明記されている通り、`base_system`(`profile_context`+`self_model_context`が入る位置)は、fact-memoryのRAG検索結果が**毎ターンユーザーの直近発言に応じて変わる**ため、そもそもターンをまたいで安定していない(Phase A2時点で既知の制約)。したがって、日次でしか変化しない鮮度ラベルを追加しても、**既存のキャッシュ効率に対する追加的な悪影響はない**と判断した(要件2に対応)。

### `last_reflected_at`更新ロジックの確認結果

`self_model.py::update_self_model()`を確認したところ、初回INSERT・以後のPATCH更新のどちらのパスでも`last_reflected_at = datetime.now(timezone.utc).isoformat()`を無条件に設定しており、**更新ロジック自体に不備は見つからなかった**。このテーブルへの書き込みはこの関数からのみ行われている(`sigmaris_self_model`は「single-row table managed exclusively by the backend service role」とマイグレーションのコメントにも明記)。

---

## 5. 「システムプロンプトの禁止ルールからの作話」経路についての評価

**この経路も引き続き排除できず、今回の修正では対応していない。**

`chat_prompts.py`の「ShiftPilotAI・shift-pilot-ai・ShiftPilotという名前は絶対に使わないでください」というルールは、`self_model`の鮮度とは無関係に、**agent_mode以外の全ターンで常に**注入される。LLMがユーザーから「なぜその名前を使わないの?」のように問われた場合、この規則を見て「過去に指摘されたことがあるのだろう」という尤もらしい作話を、実際の記憶検索を一切経由せずに生成する可能性は十分にある。

この経路は今回の鮮度情報修正では解決しない。理由:

- ルール自体は「絶対に使わないでください」という**未来志向の禁止事項**であり、過去の出来事を明示的に語る文言ではない。LLM側の推論・作話によって「過去形の物語」に変換されている可能性がある。
- 対処するとすれば、ルールの文言を「これは運用上の制約であり、特定の過去の会話を指すものではない」のように補強する方向が考えられるが、これはかえって「特定の過去の会話」という発想をLLMに与えかねず(いわゆるストライサンド効果的な逆効果)、明確に効果があるとは言い切れない。

**所見**: 今回のself_model鮮度修正をデプロイした後も同様の発言が(鮮度情報付きの自己記述を見ているにもかかわらず)再発するようであれば、この「ルール文からの作話」経路が支配的である可能性が高まる。その場合は別タスクとして、ルール文言の見直しを検討する価値がある。現時点では対応必須とは判断していない(指示書の通り、今回は評価のみ)。

---

## 6. `identity_statement`の現在の中身について

**未確認。** 前述の通りDB・サーバーへのアクセス手段が今回もなく、`sigmaris_self_model`テーブルの現在のレコードを読み取ることができなかった。データの削除・書き換えは行っていない(そもそも読み取りすら実行できていない)。

**運用者にお願いしたいこと**(読み取りのみで確認可能):

```sql
select identity_statement, last_reflected_at, version
from sigmaris_self_model
order by version desc
limit 1;
```

これで`identity_statement`に「ShiftPilotAI」への直接的な言及が含まれているかどうかを確認できる。含まれていれば2章の仮説がほぼ確定し、含まれていなければ5章の「ルール文からの作話」経路の可能性が相対的に高まる。

---

## 7. テスト結果

モックのみ(実DB・実LLM不要、`_build_self_model_context()`は純粋にdictを受け取ってstrを返す関数のため)。9ケース全てPASS:

```
PASS: reflected today -> shows '本日'
PASS: 10-day-old reflection -> '10日前' + explicit staleness warning
PASS: ~1 day ago -> '1日前'
PASS: last_reflected_at=None -> graceful '不明' fallback, no crash
PASS: last_reflected_at key entirely absent -> same graceful fallback, no KeyError
PASS: malformed timestamp string -> graceful fallback, no crash
PASS: goals line format/truncation-to-3 unchanged by this fix
PASS: no model / empty identity_statement -> None, unchanged from before this fix
PASS: 'Z'-suffixed UTC timestamp (as Supabase sometimes returns) parses correctly
```

要件1(鮮度情報が含まれること)・要件2(NULLでもクラッシュしないこと)・要件3(goals等の既存要素に影響しないこと)を直接検証している。`backend/tests/`(既存8件)全てPASS、`import app.main`成功。

`run_orchestrator_chat`・`run_orchestrator_chat_stream`の両方が同じ`_build_self_model_context()`を呼んでいるため、この修正は両経路に自動的に反映される。

---

## Related Documents

- [phase_a5_report.md](phase_a5_report.md)
- [phase_c_mini_report.md](phase_c_mini_report.md) — この調査の発端になったbaseline取得作業
