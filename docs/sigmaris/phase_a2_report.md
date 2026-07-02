# Phase A2 実施報告: プロンプト構造の並べ替え(OpenAIキャッシュ有効化)

**目的:** `chat_prompts.py::build_system_prompt()`の結合順序を「不変・長大な指示文を先頭、可変・短い要素を末尾」に並べ替え、OpenAIのプレフィックスキャッシュを有効化する。
**作業ブランチ:** `phase-a2-prompt-cache-ordering`（`phase-a1b-chat-orchestrator-switch`から分岐）
**範囲:** Phase A3(decision_log本稼働)・A4(排他制御)・A5(RAGのLOCAL_LLM_ENABLED依存見直し)には着手していない。

---

## 1. 変更前後の`build_system_prompt()`の構造比較

### 変更前

```
[base_system, ai_tone_instruction, router_instruction, "\n".join(rules), attachment_facts]
```

`rules`配列の3番目の要素に`f"現在日時は... {now_jst}"`（分単位で変化）が埋め込まれていた。

### 変更後

```
["\n".join(rules), ai_tone_instruction, base_system, attachment_facts, router_instruction, time_instruction]
```

- `now_jst`の埋め込みは`rules`から完全に削除し、`time_instruction`として関数末尾で独立変数化、結合リストの最後尾に配置。
- `rules`自体はテキスト内容を一切変更していない（該当行を削除しただけ）。

**関数シグネチャは無変更**（`base_system, ai_tone_instruction, attachment_facts, router_instruction=None, agent_mode=False`）。`chat.py`側の2箇所の呼び出し(`run_chat_completion` 454行目、`stream_chat_completion_ui` 716行目)はいずれも無改修で動作する。

---

## 2. `rules`内で他に見つかった動的要素の有無

`now_jst`以外に動的要素は見つからなかった。全34行を確認し、文字列展開(f-string)が使われているのは元の`now_jst`埋め込み行のみ。`identity_rule`（`rules[0]`）は`agent_mode`という真偽値によって2種類の固定文字列を切り替えているが、これは「ターンごとに変化する値」ではなく「呼び出し経路によって決まる固定モード」（`agent_mode=not persist_messages`。同一スレッド内では通常一貫した値になる）のため、動的要素としては扱わず`rules`内に残した。

---

## 3. `base_system`/`ai_tone_instruction`/`attachment_facts`の順序をどう決めたか

指示書の例示スケルトンでは`base_system`(中頻度更新) → `ai_tone_instruction`(低頻度更新)の順だったが、実装では**`ai_tone_instruction`を`base_system`より前**に配置した。指示書が「相対順序は実際の更新頻度を確認した上で決めてよい」と明示的に判断を委ねていたため、以下の根拠で決定した。

- `ai_tone_instruction`はユーザーが明示的に設定を変更しない限り不変（`profile.aiTone`という低頻度の設定値）。実質的に会話全体を通じて固定。
- `base_system`（fact/self_model/trend文脈）は、`orchestrator/service.py`内のキャッシュ無効化ロジックにより**毎ターン変化しうる**:
  ```python
  # orchestrator/service.py:556-558, 774-775
  # Invalidate context cache after response so next turn picks up any new facts
  # (only invalidate facts — profile and self_model change less frequently)
  _cache.pop(f"facts:{user_id}", None)
  ```
  応答後に毎回`facts`キャッシュを明示的に破棄しているため、`base_system`に含まれる事実記憶部分は次ターンで再取得され、新しい事実が抽出されていれば内容が変わる。
- したがって`ai_tone_instruction`の方が`base_system`より実際の更新頻度が低く、より前方に置くことでキャッシュ対象のプレフィックスを長く保てる。

`attachment_facts`は指示書通りの位置（`base_system`の後、`router_instruction`の前）とした。添付の有無はターンごとに変わりうるが、`router_instruction`（毎ターン必ずLLM分類し直される）・`time_instruction`（毎ターン必ず変わる）ほど確実に変化するわけではないため、この位置が妥当と判断した。

---

## 4. トークン数の変更前後比較

`tiktoken`（`cl100k_base`、近似値）で、代表的な入力（ユーザーコンテキスト・fact要約・添付なし・ルーティング結果あり）を使い、変更前(Phase A1-bまでのコミット)と変更後の`build_system_prompt()`の出力を直接比較した。

```
old total chars=5305 tokens(cl100k_base est.)=1682
new total chars=5306 tokens(cl100k_base est.)=1682
delta tokens: 0
content-line-set equal: True
lines only in old: set()
lines only in new: set()
```

**トークン数は変化なし（1682→1682）。行単位の内容集合も完全一致**（`set()`同士の差分が両方とも空集合）。これは要件3「既存の応答品質に影響を与えないこと」の直接的な裏付けであり、今回の変更が純粋に「順序の並べ替え」であって内容の追加・削除・改変を一切含んでいないことを機械的に証明している。

---

## 5. キャッシュヒットの実測結果

**未検証。** ローカル環境に`OPENAI_API_KEY`がなく、実際のAPIレスポンスの`usage.prompt_tokens_details.cached_tokens`（またはそれに相当するフィールド）を確認することはできなかった。指示書の注意事項に従い、サーバーアクセスやAPIキーの追加取得は試みていない。

代わりに、**静的な構造確認でプレフィックス安定性を直接検証**した。同一の`base_system`/`ai_tone_instruction`/`attachment_facts`で`router_instruction`だけを変えた2回の呼び出しを比較し、共通接頭辞の長さを実測した:

```
common prefix length: 5205 of 5328 chars (prompt2 len=5326)
prefix covers rules+tone+base_system (up to attachment_facts start): True
PASS: rules+tone+base_system form a stable shared prefix across differing router_instruction values
```

全体5,328文字のうち**5,205文字（約98%）が、意図分類結果が完全に異なる2リクエスト間でバイト単位で一致する共通接頭辞**になっていることを確認した。これは要件1・2（`rules`が先頭に来ること、時刻が末尾に分離されること）が構造的に満たされていることの直接証拠であり、OpenAIのプレフィックスキャッシュが実際に機能する条件（長い共通接頭辞の存在）を満たしていると判断できる。

指示書の通り、実測不能自体はマージの妨げにしていない。

---

## 6. 気づいた懸念点・Phase A3以降に影響しそうな発見

1. **`agent_mode`の値がリクエスト経路によって決まる点**: `identity_rule`（`rules`の一部）は`agent_mode`の真偽値で2種類の固定文言に分岐する。同一ユーザーが`/chat`（orchestrator経由、`agent_mode=True`固定）と将来的に他の経路（`agent_mode=False`）を行き来した場合、`rules`のプレフィックス自体が経路によって2パターン存在することになり、キャッシュも経路ごとに別々に効くことになる。現状は`/chat`・WearOS・`/sigmaris`が全て`orchestrator/service.py`経由（`agent_mode=True`固定）のため実害はないが、Phase A1-bで温存した`routes/chat.py`の`/api/chat/stream`（`agent_mode=False`）を将来復活させる場合はこの分岐を意識する必要がある。
2. **`base_system`の粒度がキャッシュ効率に直結する**: 3章で述べた通り、`facts`キャッシュは毎ターン無効化される設計になっている。Phase A1のセッション継続ウィンドウ導入で会話が長時間続くケースが増えることを踏まえると、「本当に新しい事実が抽出された時だけ`base_system`を変える」（無関係な理由でのキャッシュ破棄を避ける）設計にできれば、さらにキャッシュ効率を上げられる可能性がある。ただしこれはPhase A2のスコープ外（`orchestrator/service.py`のキャッシュ無効化ロジック自体の変更）のため、次フェーズ以降の検討事項として記載するに留める。
3. **`router_instruction`はintent分類が変わるたびに毎回発生するため、キャッシュ非対象の「末尾」に置いても、その手前の共通接頭辞（rules+tone+base_system+attachment_facts）が変わらない限りキャッシュヒット自体は起きる**（OpenAIのプレフィックスキャッシュは「どこまで一致するか」で判定されるため、末尾が変わってもそこまでの一致部分はキャッシュされる）。この理解が正しいかは実際のAPI利用実績（`usage`フィールド）で確認する必要があり、5章で述べた通り未検証。

---

## Related Documents

- [global_state_migration_audit.md](global_state_migration_audit.md) — 発端となった監査レポート(7章)
- [phase_a1b_report.md](phase_a1b_report.md) — `/chat`のorchestrator経由化（全経路で`build_system_prompt()`が共通化されている前提）
