# 2026-04-01 Route Ranking And Travel Block

## 目的

公共交通の案内を `1本だけ返す` 状態から、`複数候補を比較して選び、そのまま予定へ組み込む` 状態へ引き上げるための実装ログだよ。

## 追加したこと

### backend mobility の強化

- `backend/app/schemas/mobility.py`
  - route plan に運賃、徒歩量、乗換回数、route summary を追加
  - transit candidate 用の schema を追加
- `backend/app/services/google_maps.py`
  - Google Geocoding と Places Nearby Search を使った地点解決
  - 公共交通候補の前倒し探索
  - `fare -> walking -> transfers -> latest departure` の順で候補整列

### frontend mobility 保存フローの強化

- `frontend/src/app/api/mobility/schedule/route.ts`
  - 公共交通では backend の `transit-candidates` を使うように変更
  - 候補を選んで preview / save できるようにした
- `frontend/src/components/mobility-panel.tsx`
  - 候補一覧を表示
  - 選択中候補の route detail を preview
  - 選んだ候補をそのまま保存

### travel plan 保存データの拡張

- `frontend/src/lib/events.ts`
  - `replaceTravelPlanForEvent` に運賃、徒歩量、乗換回数、selected candidate を追加
- `supabase/migrations/202604010007_travel_plan_route_metrics.sql`
  - `event_travel_plans` に route metrics 保存用カラムを追加

### AI からの route 保存

- `backend/app/services/app_data.py`
  - event 取得、競合確認、travel plan 保存、travel block event 作成を追加
- `backend/app/services/chat.py`
  - `plan_transit_candidates` を model dump で返すよう修正
  - `save_travel_plan_for_event` tool を追加
- `backend/app/services/chat_routing.py`
  - mobility intent / calendar write intent で `save_travel_plan_for_event` を使えるようにした

## 現在できること

- 予定の場所と開始時刻に対して公共交通候補を複数探索する
- 候補を価格順ベースで比較する
- 徒歩距離、徒歩時間、乗換回数を route detail として見る
- 候補を選んで travel block を保存する
- AI からも確認後に travel block を予定へ組み込める

## 補足

- Google 側が運賃を返さない候補では、価格比較は完全ではない
- リアルタイム遅延はまだ扱っていない
- migration `202604010007_travel_plan_route_metrics.sql` の適用が必要
