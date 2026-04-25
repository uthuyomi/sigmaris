// 役割: 予定データで使う日時の変換や整形処理をまとめる。

const APP_TIME_ZONE = "Asia/Tokyo";

export const getPartsInTimeZone = (value: string) => {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: APP_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });

  const parts = formatter.formatToParts(new Date(value));
  const read = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "00";

  return {
    year: read("year"),
    month: read("month"),
    day: read("day"),
    hour: Number(read("hour")),
    minute: Number(read("minute")),
  };
};

export const toMinutesInTimeZone = (value: string) => {
  const parts = getPartsInTimeZone(value);
  return parts.hour * 60 + parts.minute;
};

export const toIsoDateInTimeZone = (value: string) => {
  const parts = getPartsInTimeZone(value);
  return `${parts.year}-${parts.month}-${parts.day}`;
};

export const startOfMonthInJst = (month: string) => `${month}-01T00:00:00+09:00`;

export const nextMonthStartInJst = (month: string) => {
  const [year, monthValue] = month.split("-").map(Number);
  const nextYear = monthValue === 12 ? year + 1 : year;
  const nextMonth = monthValue === 12 ? 1 : monthValue + 1;
  return `${nextYear}-${`${nextMonth}`.padStart(2, "0")}-01T00:00:00+09:00`;
};

export const nextDayStartInJst = (date: string) => {
  const [year, month, day] = date.split("-").map(Number);
  const nextDay = new Date(Date.UTC(year, month - 1, day + 1, 0, 0, 0));
  return `${nextDay.getUTCFullYear()}-${`${nextDay.getUTCMonth() + 1}`.padStart(2, "0")}-${`${nextDay.getUTCDate()}`.padStart(2, "0")}T00:00:00+09:00`;
};
