// 役割: Sigmaris Live-3(docs/sigmaris/sigmaris_live_report.md)。「処理の
// 流れ」の視覚化(LiveProcessFlow)が対象とする処理の一覧と、イベント
// 配列からその時点の状態を導出する純粋関数。
//
// 【拡張性についての設計判断(依頼書1章「将来複数の処理が追加された際に
// 自然に拡張できるレイアウトを意識すること」への対応)】
// 現時点ではclassify_chat_intent()(意図分類)のみが対象だが、次タスク
// (Live-4)以降で記憶検索・Evidence検索・応答生成等を追加する場合、
// PROCESS_STEPSにエントリを1つ追加するだけでよい設計にした。表示側
// (live-process-flow.tsx)は、この配列を動的にmapして描画するため、
// 要素数が変わってもコンポーネント自体の再設計は不要。

import type { LiveEvent } from "./types";

export type ProcessStepId = "intent_classification";

export type ProcessStepConfig = {
  id: ProcessStepId;
  label: string;
  description: string;
  startedEvent: string;
  finishedEvent: string;
};

export const PROCESS_STEPS: readonly ProcessStepConfig[] = [
  {
    id: "intent_classification",
    label: "意図分類",
    description: "会話の意図(カレンダー登録・予定確認等)を判定します",
    startedEvent: "intent_classification_started",
    finishedEvent: "intent_classification_finished",
  },
  // 将来の処理(記憶検索・Evidence検索・応答生成等)は、ここに1エントリ
  // 追加するだけで、LiveProcessFlow/LiveMetrics/LiveEventLogのいずれにも
  // 自然に反映される(各コンポーネントはPROCESS_STEPSを走査するのみで、
  // 個別の処理名をハードコードしていないため)。
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
 * (=最後に見たstarted/finishedのどちらが後だったかで決まる)。 */
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
