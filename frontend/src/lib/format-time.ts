// 役割: チャットメッセージの日時表示用フォーマッタ。
//
// 絶対日時は「2026年7月10日 21:00」のような漢字区切りで表示する
// (docs/sigmaris/phase_ba4_report.md 19章追補: 「証拠として残せる」という
// 当初の目的を踏まえ、常時表示・曖昧さのない書式を優先する要望に対応)。
// lib/timeline/transform.ts の formatDate()(年/月/日、スラッシュ区切り)
// とは書式を揃えていない — あちらは"/timelineページが表示するevent/
// state/traitデータの整形ロジック"と明記されたページ専用モジュールであり、
// 元々このファイルへ複製していたものを、今回の要望に合わせて変更した。

const ABSOLUTE_FORMATTER = new Intl.DateTimeFormat("ja-JP", {
  year: "numeric",
  month: "long",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

// style: "narrow" — "long"/"short"はja-JPで数値と単位の間に半角スペースを
// 挿入する("3 日前")。絶対日時に括弧書きで併記する用途では、日本語として
// 自然な詰めた表記("3日前")の方が適切と判断した。
const RELATIVE_FORMATTER = new Intl.RelativeTimeFormat("ja-JP", { numeric: "auto", style: "narrow" });

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
