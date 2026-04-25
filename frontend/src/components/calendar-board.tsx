// 役割: 予定をカレンダー形式で表示するReactコンポーネント。

import Link from "next/link";
import { CalendarIcon, ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { getDictionary, type AppLocale } from "@/lib/i18n";
import { minutesToLabel, type EventItem } from "@/lib/mock-schedule";

const toLocalIsoDate = (date: Date) => {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
};

const parseMonth = (value?: string) => {
  if (!value || !/^\d{4}-\d{2}$/.test(value)) {
    return new Date();
  }

  const [year, month] = value.split("-").map(Number);
  return new Date(year, month - 1, 1);
};

const formatMonthValue = (date: Date) => {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  return `${year}-${month}`;
};

const formatMonthLabel = (date: Date, locale: AppLocale) =>
  new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "long",
  }).format(date);

const buildCalendarDays = (monthDate: Date) => {
  const firstDay = new Date(monthDate.getFullYear(), monthDate.getMonth(), 1);
  const offset = (firstDay.getDay() + 6) % 7;
  const startDate = new Date(firstDay);
  startDate.setDate(firstDay.getDate() - offset);

  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(startDate);
    date.setDate(startDate.getDate() + index);

    return {
      key: `${toLocalIsoDate(date)}-${index}`,
      day: date.getDate(),
      inMonth: date.getMonth() === monthDate.getMonth(),
      iso: toLocalIsoDate(date),
    };
  });
};

type CalendarBoardProps = {
  locale: AppLocale;
  month?: string;
  events: EventItem[];
};

export function CalendarBoard({ locale, month, events }: CalendarBoardProps) {
  const dict = getDictionary(locale);
  const currentMonth = parseMonth(month);
  const calendarDays = buildCalendarDays(currentMonth);
  const previousMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1);
  const nextMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1);
  const monthLabel = formatMonthLabel(currentMonth, locale);
  const monthValue = formatMonthValue(currentMonth);
  const monthlyEventCount = events.filter((event) => event.date.startsWith(monthValue)).length;

  return (
    <div className="flex min-h-[42rem] flex-col overflow-hidden rounded-[32px] border border-stone-900/10 bg-white/80 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
      <div className="border-b border-stone-900/10 px-5 py-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="inline-flex size-11 items-center justify-center rounded-2xl bg-stone-900 text-stone-50">
              <CalendarIcon className="size-5" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-stone-500">{dict.calendar.title}</p>
              <h2 className="mt-1 text-xl font-semibold text-stone-900">{monthLabel}</h2>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href={`/calendar?month=${formatMonthValue(previousMonth)}`}
              className="inline-flex size-11 items-center justify-center rounded-full border border-stone-900/10 bg-white text-stone-700 transition hover:bg-stone-900 hover:text-stone-50"
              aria-label={dict.calendar.previousMonth}
            >
              <ChevronLeftIcon className="size-4" />
            </Link>
            <div className="rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-stone-50">
              {monthlyEventCount} {dict.calendar.eventsCount}
            </div>
            <Link
              href={`/calendar?month=${formatMonthValue(nextMonth)}`}
              className="inline-flex size-11 items-center justify-center rounded-full border border-stone-900/10 bg-white text-stone-700 transition hover:bg-stone-900 hover:text-stone-50"
              aria-label={dict.calendar.nextMonth}
            >
              <ChevronRightIcon className="size-4" />
            </Link>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-7 border-b border-stone-900/10 bg-stone-900/5 px-4 py-3">
        {dict.calendar.weekdays.map((label) => (
          <div key={label} className="px-2 text-sm font-medium text-stone-600">
            {label}
          </div>
        ))}
      </div>

      <div className="grid flex-1 grid-cols-7">
        {calendarDays.map((day) => {
          const dayEvents = events.filter((event) => event.date === day.iso);

          return (
            <Link
              key={day.key}
              href={`/timeline?date=${day.iso}`}
              aria-label={`${day.iso} ${dict.calendar.openDay}`}
              className={`block min-h-[9rem] border-b border-r border-stone-900/8 p-3 transition ${
                day.inMonth ? "bg-white/70" : "bg-stone-900/3"
              } hover:bg-white`}
            >
              <div className="flex items-center justify-between">
                <span
                  className={`inline-flex size-8 items-center justify-center rounded-full text-sm font-semibold ${
                    day.inMonth ? "text-stone-700" : "text-stone-400"
                  }`}
                >
                  {day.day}
                </span>
                {dayEvents.length ? (
                  <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-stone-400">
                    {dayEvents.length}
                  </span>
                ) : null}
              </div>

              <div className="mt-3 space-y-2">
                {dayEvents.slice(0, 3).map((event) => (
                  <div
                    key={event.id}
                    className="rounded-2xl border border-stone-900/8 bg-stone-50 px-3 py-2"
                  >
                    <p className="truncate text-xs font-semibold text-stone-900">{event.title}</p>
                    <p className="mt-1 text-[11px] text-stone-500">
                      {minutesToLabel(event.startMinutes)} - {minutesToLabel(event.endMinutes)}
                    </p>
                  </div>
                ))}
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
