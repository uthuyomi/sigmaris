export type Grain = 5 | 10 | 15 | 30 | 60;

export type EventItem = {
  id: string;
  title: string;
  startMinutes: number;
  endMinutes: number;
  tone: "mint" | "amber" | "sky";
  detail: string;
  date: string;
  location?: string;
};

export const grainOptions: Grain[] = [5, 10, 15, 30, 60];

export const scheduleEvents: EventItem[] = [
  {
    id: "e1",
    title: "朝の確認と連絡整理",
    startMinutes: 8 * 60 + 30,
    endMinutes: 9 * 60 + 10,
    tone: "mint",
    detail: "Slack / メール / 本日の優先順位",
    date: "2026-03-27",
  },
  {
    id: "e2",
    title: "集中作業ブロック",
    startMinutes: 10 * 60,
    endMinutes: 12 * 60 + 10,
    tone: "sky",
    detail: "UI 実装とタイムライン調整",
    date: "2026-03-27",
  },
  {
    id: "e3",
    title: "相談枠",
    startMinutes: 16 * 60 + 20,
    endMinutes: 16 * 60 + 50,
    tone: "amber",
    detail: "進捗確認 / 次の調整",
    date: "2026-03-27",
    location: "渋谷スクランブルスクエア",
  },
  {
    id: "e4",
    title: "夜の整理",
    startMinutes: 21 * 60,
    endMinutes: 21 * 60 + 45,
    tone: "mint",
    detail: "明日の仮配置を作る",
    date: "2026-03-27",
  },
  {
    id: "e5",
    title: "移動込みの訪問",
    startMinutes: 13 * 60,
    endMinutes: 14 * 60 + 20,
    tone: "amber",
    detail: "現地確認と戻り時間込み",
    date: "2026-03-29",
    location: "東京ビッグサイト",
  },
  {
    id: "e6",
    title: "月初レビュー",
    startMinutes: 11 * 60,
    endMinutes: 12 * 60,
    tone: "sky",
    detail: "来月分の予定整理",
    date: "2026-03-31",
    location: "品川駅",
  },
];

export const toneClassMap: Record<EventItem["tone"], string> = {
  mint: "border-lime-400/80 bg-lime-200/85 text-lime-950 shadow-[0_18px_40px_-24px_rgba(132,204,22,0.75)]",
  amber:
    "border-amber-400/80 bg-amber-200/90 text-amber-950 shadow-[0_18px_40px_-24px_rgba(245,158,11,0.75)]",
  sky: "border-sky-400/80 bg-sky-200/90 text-sky-950 shadow-[0_18px_40px_-24px_rgba(56,189,248,0.75)]",
};

export const minutesToLabel = (value: number) => {
  const hours = Math.floor(value / 60);
  const minutes = value % 60;

  return `${hours.toString().padStart(2, "0")}:${minutes
    .toString()
    .padStart(2, "0")}`;
};

export const getEventsByDate = (date: string) =>
  scheduleEvents.filter((event) => event.date === date);

export const formatJapaneseDate = (date: string) => {
  const parsed = new Date(`${date}T00:00:00`);

  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(parsed);
};

export const toIsoDateTime = (date: string, minutes: number) => {
  const hours = Math.floor(minutes / 60)
    .toString()
    .padStart(2, "0");
  const mins = (minutes % 60).toString().padStart(2, "0");
  return `${date}T${hours}:${mins}:00+09:00`;
};
