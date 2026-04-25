# 2026-04-01 Arrival Lead Minutes Setting

## 目的

公共交通や移動 route を探す時に、予定開始ぴったりではなく `何分前には着いていたいか` をプロフィール設定として持てるようにするための実装ログだよ。

## 追加したこと

### 設定 UI

- `frontend/src/components/arrival-lead-minutes-panel.tsx`
  - 到着余裕時間を 1 分単位で入力して保存できるようにした
- `frontend/src/app/settings/page.tsx`
  - 設定画面に新しいパネルを追加

### 保存 API

- `frontend/src/app/api/settings/arrival-lead-minutes/route.ts`
  - `profiles.arrival_lead_minutes` を更新する route を追加
- `frontend/src/lib/profile-settings.ts`
  - 読み書き関数と fallback を追加

### 実際の route 探索への反映

- `frontend/src/app/api/mobility/schedule/route.ts`
  - route 探索の到着基準を `event.starts_at - arrivalLeadMinutes` に変更
- `frontend/src/components/mobility-panel.tsx`
  - preview に到着余裕時間の基準を表示
- `backend/app/services/app_data.py`
  - profile context に `arrivalLeadMinutes` を追加
- `backend/app/services/chat.py`
  - `read_home_context` で arrival lead minutes を返すようにした

## 現在の仕様

- 0〜180 分で設定できる
- UI 上は 1 分単位で変更できる
- 既定値は 10 分
- mobility と AI の両方が同じ値を参照する

## 補足

- migration `202604010008_profile_arrival_lead_minutes.sql` の適用が必要
- これで `ギリギリすぎる到着候補` を避けやすくなる
