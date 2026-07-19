// 役割: Sigmaris Live-7(デモモード)。X発信・動画撮影用の、模擬イベント
// シーケンスの定義。
//
// 【個人情報を一切含まないことについて】
// ここに定義する数値(elapsed_ms・result_count・confidence_tier等)は、
// 全て架空の値であり、実データからの抽出・加工は一切行っていない
// (依頼書の必須制約)。値の「桁数・相場感」自体は、Live-1〜6の報告書に
// 記載された実測値(例: 意図分類のLLM経路が2350ms、記憶検索が95〜187ms、
// 応答生成が410〜932ms、ツール呼び出しが15〜88ms)を参考にしている——
// これは、演出が誇張されて見えないための判断根拠であり(依頼書「実際の
// 処理時間の感覚を大きく裏切らない自然な間隔」への対応)、個人情報とは
// 無関係の、処理速度の一般的な相場感のみを踏襲したものである。
//
// シナリオの本文("今日の天気"等)自体も、実際のユーザーの発言を書き起こした
// ものではなく、依頼書が例示した「当たり障りのない内容」に沿って、最初から
// 架空のシナリオとして作成した。実イベントのペイロード設計(Live-1、4章)
// 自体が、そもそも発言内容・記憶の中身を含まない、要約データのみの構造で
// あるため、この模擬データも同じ構造(件数・カテゴリラベル・真偽値・
// 所要時間)のみで構成されており、個人情報が入り込む余地が構造的に無い。

export type DemoStepEvent =
  | "intent_classification_started"
  | "intent_classification_finished"
  | "memory_search_started"
  | "memory_search_finished"
  | "response_generation_started"
  | "tool_call_started"
  | "tool_call_finished"
  | "response_generation_finished";

export type DemoStep = {
  event: DemoStepEvent;
  /** 直前のステップから、このステップが発火するまでの遅延(ms)。 */
  delayMs: number;
  fields?: Record<string, unknown>;
  /** trueの場合、ツール呼び出し用の共有tool_call_idを発行してfieldsへ
   * 混ぜ込む(tool_call_started/finishedの対で同じIDを使うため)。 */
  isToolCall?: boolean;
};

export type DemoScenario = {
  id: string;
  steps: DemoStep[];
};

// シナリオ1: 今日の天気を聞かれる。記憶のヒットは無く、意図分類は
// ヒューリスティックで即座に完了する、最も軽いパターン。
const WEATHER_SCENARIO: DemoScenario = {
  id: "weather",
  steps: [
    { event: "intent_classification_started", delayMs: 400 },
    {
      event: "intent_classification_finished",
      delayMs: 38,
      fields: { intent: "chat", source: "heuristic", needs_search: true, elapsed_ms: 38 },
    },
    { event: "memory_search_started", delayMs: 250 },
    {
      event: "memory_search_finished",
      delayMs: 110,
      fields: {
        result_count: 0,
        was_decomposed: false,
        confidence_tier: "abstain",
        diary_search_triggered: false,
        elapsed_ms: 110,
      },
    },
    { event: "response_generation_started", delayMs: 250 },
    {
      event: "response_generation_finished",
      delayMs: 480,
      fields: { response_length: 58, elapsed_ms: 480 },
    },
  ],
};

// シナリオ2: 開発の進捗を聞かれる。意図分類がLLM経路にフォールバックし、
// やや時間がかかる(数十ms〜数秒の幅がある、という実際の挙動を再現)。
const DEV_PROGRESS_SCENARIO: DemoScenario = {
  id: "dev_progress",
  steps: [
    { event: "intent_classification_started", delayMs: 400 },
    {
      event: "intent_classification_finished",
      delayMs: 1450,
      fields: { intent: "chat", source: "llm", needs_search: false, elapsed_ms: 1450 },
    },
    { event: "memory_search_started", delayMs: 250 },
    {
      event: "memory_search_finished",
      delayMs: 165,
      fields: {
        result_count: 2,
        was_decomposed: false,
        confidence_tier: "confident",
        diary_search_triggered: false,
        elapsed_ms: 165,
      },
    },
    { event: "response_generation_started", delayMs: 250 },
    {
      event: "response_generation_finished",
      delayMs: 810,
      fields: { response_length: 142, elapsed_ms: 810 },
    },
  ],
};

// シナリオ3: 予定を登録してほしいと頼まれる。ツール呼び出し
// (create_app_events)を伴う、唯一のシナリオ。
const SCHEDULE_REGISTRATION_SCENARIO: DemoScenario = {
  id: "schedule_registration",
  steps: [
    { event: "intent_classification_started", delayMs: 400 },
    {
      event: "intent_classification_finished",
      delayMs: 6,
      fields: { intent: "calendar_create", source: "heuristic", needs_search: false, elapsed_ms: 6 },
    },
    { event: "memory_search_started", delayMs: 250 },
    {
      event: "memory_search_finished",
      delayMs: 98,
      fields: {
        result_count: 1,
        was_decomposed: false,
        confidence_tier: "confident",
        diary_search_triggered: false,
        elapsed_ms: 98,
      },
    },
    { event: "response_generation_started", delayMs: 250 },
    { event: "tool_call_started", delayMs: 200, fields: { tool_name: "create_app_events" }, isToolCall: true },
    {
      event: "tool_call_finished",
      delayMs: 52,
      fields: { tool_name: "create_app_events", ok: true, elapsed_ms: 52 },
      isToolCall: true,
    },
    {
      event: "response_generation_finished",
      delayMs: 690,
      fields: { response_length: 76, elapsed_ms: 690 },
    },
  ],
};

// シナリオ4: 旅行の計画について相談される。記憶検索がクエリ分解(B7)を
// 行い、確信度が「確信度低め」になる、より複雑なパターン。
const TRAVEL_PLANNING_SCENARIO: DemoScenario = {
  id: "travel_planning",
  steps: [
    { event: "intent_classification_started", delayMs: 400 },
    {
      event: "intent_classification_finished",
      delayMs: 980,
      fields: { intent: "chat", source: "llm", needs_search: true, elapsed_ms: 980 },
    },
    { event: "memory_search_started", delayMs: 250 },
    {
      event: "memory_search_finished",
      delayMs: 205,
      fields: {
        result_count: 3,
        was_decomposed: true,
        confidence_tier: "hedged",
        diary_search_triggered: false,
        elapsed_ms: 205,
      },
    },
    { event: "response_generation_started", delayMs: 250 },
    {
      event: "response_generation_finished",
      delayMs: 890,
      fields: { response_length: 168, elapsed_ms: 890 },
    },
  ],
};

/** 複数シナリオを、順番にループ再生する(use-mock-live-events.ts参照)。
 * 将来シナリオを追加する場合は、この配列に1エントリ追加するだけでよい。 */
export const DEMO_SCENARIOS: readonly DemoScenario[] = [
  WEATHER_SCENARIO,
  DEV_PROGRESS_SCENARIO,
  SCHEDULE_REGISTRATION_SCENARIO,
  TRAVEL_PLANNING_SCENARIO,
];

/** 1つのシナリオの再生が終わってから、次のシナリオが始まるまでの間隔。 */
export const DEMO_SCENARIO_GAP_MS = 2200;
