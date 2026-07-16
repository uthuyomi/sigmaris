// 役割: チャットメッセージの日時表示用フォーマッタ。
//
// 絶対日時の書式は lib/timeline/transform.ts の formatDate() と意図的に
// 揃えている(年/月/日/時/分、ja-JP)が、あちらは"/timelineページが表示
// するevent/state/traitデータの整形ロジック"と明記されたページ専用モジュー
// ルのため、直接importせずこのファイルへ同じ書式を複製した。

const ABSOLUTE_FORMATTER = new Intl.DateTimeFormat("ja-JP", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

const RELATIVE_FORMATTER = new Intl.RelativeTimeFormat("ja-JP", { numeric: "auto" });

const RELATIVE_UNITS: readonly [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 86_400_000],
  ["month", 30 * 86_400_000],
  ["day", 86_400_000],
  ["hour", 3_600_000],
  ["minute", 60_000],
];

export function formatAbsoluteDateTime(value?: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return ABSOLUTE_FORMATTER.format(date);
}

export function formatRelativeTime(value?: string | null, now: number = Date.now()): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;

  const diffMs = date.getTime() - now;
  const absDiffMs = Math.abs(diffMs);

  if (absDiffMs < 60_000) return "たった今";

  for (const [unit, unitMs] of RELATIVE_UNITS) {
    if (absDiffMs >= unitMs) {
      return RELATIVE_FORMATTER.format(Math.round(diffMs / unitMs), unit);
    }
  }
  return "たった今";
}
