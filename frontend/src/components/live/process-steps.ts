// 役割: Sigmaris Live-3/他の処理への拡大(docs/sigmaris/
// sigmaris_live_report.md)。「処理の流れ」の視覚化(LiveProcessFlow)が
// 対象とする処理の一覧と、イベント配列からその時点の状態を導出する
// 純粋関数。
//
// 【拡張性についての設計判断(依頼書1章「将来複数の処理が追加された際に
// 自然に拡張できるレイアウトを意識すること」への対応)】
// PROCESS_STEPSにエントリを1つ追加するだけで、LiveProcessFlow/
// LiveEventLogのいずれにも自然に反映される。
//
// 【他の処理への拡大タスクでの改良点(要件5の検証結果)】
// Live-3時点では、「done状態の結果要約」を組み立てるロジック
// (旧resultSummary())が、live-process-flow.tsx側にintent_classification
// 専用のハードコードとして存在しており、Live-3報告書の懸念点2で
// 「2つ目の処理を追加する時点で決めるべき」と申し送っていた。本タスクで
// memory_search・response_generationを追加するにあたり、この要約整形
// ロジック自体を`summarizeResult`として各ステップのconfigへ移した——
// これにより、表示コンポーネント(live-process-flow.tsx・live-event-
// log.tsx)は`config.summarizeResult(event)`を呼ぶだけの、真に汎用的な
// コードのままになり、「設定の追加のみで新しい処理に対応できる」が、
// より厳密な意味で成り立つようになった(判断根拠、報告書に詳述)。

import type { LiveEvent } from "./types";

export type ProcessStepId = "intent_classification" | "memory_search" | "response_generation";

export type ProcessStepConfig = {
  id: ProcessStepId;
  label: string;
  description: string;
  startedEvent: string;
  finishedEvent: string;
  /** doneになった際の結果要約(1行)を、finishedイベントのペイロード
   * (要約データのみ、Live-1 4章のプライバシー方針の通り本文・引数等は
   * 一切含まれない)から組み立てる。live-process-flow.tsx・
   * live-event-log.tsxの両方が、この関数を通じてのみ結果を表示する。 */
  summarizeResult: (event: LiveEvent) => string;
  /** この処理が、ヒューリスティック/LLM判定の内訳(source フィールド)を
   * 持つ場合のみ設定する。持たない処理(記憶検索・応答生成)では省略し、
   * LiveMetricsはこのフィールドの有無で、即時判定/LLM判定カードの表示要否
   * を判断する(config側のデータのみで判断し、component側にconfig.idでの
   * 分岐は持たせない)。 */
  sourceBreakdownLabel?: { heuristic: string; llm: string };
};

function fieldAsString(value: unknown, fallback = "unknown"): string {
  return typeof value === "string" ? value : fallback;
}

function fieldAsNumber(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

export const PROCESS_STEPS: readonly ProcessStepConfig[] = [
  {
    id: "intent_classification",
    label: "意図分類",
    description: "会話の意図(カレンダー登録・予定確認等)を判定します",
    startedEvent: "intent_classification_started",
    finishedEvent: "intent_classification_finished",
    sourceBreakdownLabel: { heuristic: "即時判定", llm: "LLM判定" },
    summarizeResult: (evt) => {
      const intent = fieldAsString(evt.intent);
      const source = evt.source === "llm" ? "LLM判定" : "即時判定";
      const needsSearch = evt.needs_search ? "・検索要" : "";
      const elapsed = fieldAsNumber(evt.elapsed_ms);
      return `${intent}(${source}${needsSearch})${elapsed !== null ? ` ・ ${elapsed}ms` : ""}`;
    },
  },
  {
    id: "memory_search",
    label: "記憶検索",
    description: "過去の会話・事実から、関連する記憶を検索します",
    startedEvent: "memory_search_started",
    finishedEvent: "memory_search_finished",
    summarizeResult: (evt) => {
      const count = fieldAsNumber(evt.result_count) ?? 0;
      const tierLabel: Record<string, string> = {
        confident: "確信あり",
        hedged: "確信度低め",
        abstain: "該当なし扱い",
      };
      const tier = evt.confidence_tier ? (tierLabel[String(evt.confidence_tier)] ?? String(evt.confidence_tier)) : null;
      const decomposed = evt.was_decomposed ? "・複数の観点に分解" : "";
      const diary = evt.diary_search_triggered ? "・日付指定の検索あり" : "";
      const elapsed = fieldAsNumber(evt.elapsed_ms);
      return `記憶${count}件${tier ? `(${tier})` : ""}${decomposed}${diary}${elapsed !== null ? ` ・ ${elapsed}ms` : ""}`;
    },
  },
  {
    id: "response_generation",
    label: "応答生成",
    description: "実際にユーザーへ届く応答本文を生成します(本物のstreaming、本文自体は含みません)",
    startedEvent: "response_generation_started",
    finishedEvent: "response_generation_finished",
    summarizeResult: (evt) => {
      const length = fieldAsNumber(evt.response_length);
      const elapsed = fieldAsNumber(evt.elapsed_ms);
      return `${length !== null ? `${length}文字を生成` : "生成完了"}${elapsed !== null ? ` ・ ${elapsed}ms` : ""}`;
    },
  },
  // 将来の処理(Evidence検索等)は、ここに1エントリ追加するだけで、
  // LiveProcessFlow/LiveEventLogのいずれにも自然に反映される。
  // tool_call_started/finishedは、意図的にここへ含めていない——1ターン
  // 中に0〜複数回発生しうる(他のステップは1ターンにつき高々1回)という、
  // 性質が異なるイベントであるため、フローの「1本の線に並ぶステップ」
  // というモデルには馴染まないと判断した。ログ・メトリクスへの表示は
  // live-event-log.tsx・metrics.tsが個別に対応する(判断根拠、報告書に
  // 詳述)。
] as const;

export type ProcessStepStatus = "idle" | "active" | "done";

export type ProcessStepState = {
  config: ProcessStepConfig;
  status: ProcessStepStatus;
  // 直近のfinishedイベント全体(結果の要約表示に使う、生データはそもそも
  // イベントに含まれていない——Live-1、4章のプライバシー方針を参照)。
  lastFinishedEvent: LiveEvent | null;
  // 現在activeな場合の開始時刻(epoch ms)。「実行中」の表示にのみ使い、
  // 経過時間を演出的にカウントアップさせる用途には使わない(依頼書
  // 「実際には存在しない遅延を演出しないこと」への配慮——本コンポーネント
  // は経過時間の実況カウントダウン/アップは行わない、finishedイベントが
  // 届いた時点のelapsed_msのみを正直に表示する)。
  activeSinceMs: number | null;
};

/** イベント配列を時系列順(古い→新しい)に走査し、各処理の「今の状態」を
 * 導出する。同じ処理が1ターンに複数回実行されることは無い前提だが、
 * 複数ターンにまたがる場合でも、最新のイベントが状態を決定する
 * (=最後に見たstarted/finishedのどちらが後だったかで決まる)。
 *
 * 他の処理への拡大タスクでの確認結果(要件5): この関数自体は、
 * PROCESS_STEPSにmemory_search・response_generationを追加した後も、
 * 1行も変更していない——ステップの数・対象イベント名に一切依存しない、
 * 汎用的な状態機械のままであることを、実装を通じて確認した。 */
export function computeStepStates(
  events: readonly LiveEvent[],
  steps: readonly ProcessStepConfig[] = PROCESS_STEPS,
): ProcessStepState[] {
  return steps.map((config) => {
    let status: ProcessStepStatus = "idle";
    let lastFinishedEvent: LiveEvent | null = null;
    let activeSinceMs: number | null = null;

    for (const evt of events) {
      if (evt.event === config.startedEvent) {
        status = "active";
        activeSinceMs = evt.timestamp * 1000;
      } else if (evt.event === config.finishedEvent) {
        status = "done";
        lastFinishedEvent = evt;
        activeSinceMs = null;
      }
    }

    return { config, status, lastFinishedEvent, activeSinceMs };
  });
}
