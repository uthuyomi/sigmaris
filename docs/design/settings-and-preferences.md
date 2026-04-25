# Settings And Preferences

## 目的

このページは、設定画面で扱うプロフィール項目と、その保存先、実際にどこで使われるかをまとめるためのものだよ。  
会話の中で設定項目が少しずつ増えたので、今の実装に対して「何が UI で変えられて、どの処理に効くのか」を見えるようにしておく。

## 現在の設定項目

### 言語

- 保存先: `profiles.locale`
- 用途:
  - UI 文言の切り替え
  - 日付や表示ラベルのロケール補助
- 関連実装:
  - `frontend/src/lib/i18n.ts`
  - `frontend/src/lib/profile-settings.ts`
  - `frontend/src/app/api/settings/language/route.ts`

### AI 口調

- 保存先: `profiles.ai_tone`
- 用途:
  - backend chat の system instruction に反映
  - `standard / friendly / concise / direct` のトーン制御
- 関連実装:
  - `frontend/src/components/ai-tone-preference-panel.tsx`
  - `frontend/src/app/api/settings/ai-tone/route.ts`
  - `backend/app/services/chat.py`

### Google カレンダー同期

- 保存先: `profiles.google_calendar_sync_enabled`
- 用途:
  - 自前 DB と Google Calendar の双方向同期 ON/OFF
- 関連実装:
  - `frontend/src/components/google-calendar-sync-panel.tsx`
  - `frontend/src/app/api/settings/google-calendar-sync/route.ts`
  - `frontend/src/app/api/sync/google-calendar/route.ts`

### 自宅住所

- 保存先:
  - `profiles.home_address`
  - 表示用に `NEXT_PUBLIC_HOME_ADDRESS` も利用するケースあり
- 用途:
  - mobility の起点
  - chat の `自宅から` 補完
- 関連実装:
  - `frontend/src/components/saved-locations-panel.tsx`
  - `frontend/src/app/api/settings/locations/route.ts`
  - `backend/app/services/app_data.py`

### 保存地点

- 保存先: `saved_locations`
- 用途:
  - mobility の起点候補
  - chat の home context 補助
- 関連実装:
  - `frontend/src/components/saved-locations-panel.tsx`
  - `frontend/src/app/api/settings/locations/[locationId]/route.ts`

### 既定の移動手段

- 保存先: `profiles.preferred_travel_mode`
- 用途:
  - mobility panel の初期値
  - chat で交通手段未指定時の補完候補
- 選択肢:
  - `train`
  - `bus`
  - `bicycle`
  - `car`
  - `walk`
- 関連実装:
  - `frontend/src/components/preferred-travel-mode-panel.tsx`
  - `frontend/src/app/api/settings/travel-mode/route.ts`
- `backend/app/services/app_data.py`

### 到着余裕時間

- 保存先: `profiles.arrival_lead_minutes`
- 用途:
  - mobility の検索基準時刻を `予定開始 - 余裕時間` にずらす
  - AI が `何分前には着きたいか` を自動補完する
- 単位:
  - 1分単位
  - 0〜180分
- 関連実装:
  - `frontend/src/components/arrival-lead-minutes-panel.tsx`
  - `frontend/src/app/api/settings/arrival-lead-minutes/route.ts`
  - `frontend/src/app/api/mobility/schedule/route.ts`
  - `backend/app/services/app_data.py`

## UI 上の方針

- 文字を増やしすぎず、アイコンや短いラベル中心にする
- 言語設定は一覧展開型にして、常時全件を並べない
- AI 口調はプリセット選択で変える
- 連携状況は正式名称を省略せず表示する

## backend との関係

設定値は frontend の見た目だけでなく、backend chat や mobility にも効く。  
ここがミソで、プロフィールは単なる表示設定ではなく、AI の補助文脈としても使われる。

具体的には次の流れになる。

1. frontend が設定値を Supabase に保存する
2. frontend は session / JWT を backend に渡す
3. backend は app data route または service からプロフィールを読む
4. chat / mobility / sync に反映する

## Notion へ移す時のおすすめ構成

Notion 側では、`設定` という親ページを1つ作って、その中に次を子ページとして置くと追いやすい。

- 言語
- AI 口調
- Google カレンダー同期
- 自宅 / 保存地点
- 既定の移動手段

このページ自体は、その親ページの冒頭で全体像を説明するための総覧として使う想定だよ。
