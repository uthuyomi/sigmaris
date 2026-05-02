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
    <div className="flex min-h-[42rem] flex-col overflow-hidden rounded-2xl border border-stone-900/10 bg-white shadow-sm dark:border-white/10 dark:bg-[#2f2f2f]">
      <div className="border-b border-stone-900/10 px-5 py-5 dark:border-white/10">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="inline-flex size-11 items-center justify-center rounded-xl bg-stone-900 text-stone-50 dark:bg-white dark:text-stone-950">
              <CalendarIcon className="size-5" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-stone-500 dark:text-stone-400">{dict.calendar.title}</p>
              <h2 className="mt-1 text-xl font-semibold text-stone-900 dark:text-stone-50">{monthLabel}</h2>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href={`/calendar?month=${formatMonthValue(previousMonth)}`}
              className="inline-flex size-11 items-center justify-center rounded-full border border-stone-900/10 bg-white text-stone-700 transition hover:bg-stone-900 hover:text-stone-50 dark:border-white/10 dark:bg-white/6 dark:text-stone-200 dark:hover:bg-white/12"
              aria-label={dict.calendar.previousMonth}
            >
              <ChevronLeftIcon className="size-4" />
            </Link>
            <div className="rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-stone-50 dark:bg-white dark:text-stone-950">
              {monthlyEventCount} {dict.calendar.eventsCount}
            </div>
            <Link
              href={`/calendar?month=${formatMonthValue(nextMonth)}`}
              className="inline-flex size-11 items-center justify-center rounded-full border border-stone-900/10 bg-white text-stone-700 transition hover:bg-stone-900 hover:text-stone-50 dark:border-white/10 dark:bg-white/6 dark:text-stone-200 dark:hover:bg-white/12"
              aria-label={dict.calendar.nextMonth}
            >
              <ChevronRightIcon className="size-4" />
            </Link>
          </div>
        </div>
      </div>

      <div className="hidden grid-cols-7 border-b border-stone-900/10 bg-stone-900/5 px-4 py-3 dark:border-white/10 dark:bg-white/6 md:grid">
        {dict.calendar.weekdays.map((label) => (
          <div key={label} className="px-2 text-sm font-medium text-stone-600 dark:text-stone-300">
            {label}
          </div>
        ))}
      </div>

      <div className="hidden flex-1 grid-cols-7 md:grid">
        {calendarDays.map((day) => {
          const dayEvents = events.filter((event) => event.date === day.iso);

          return (
            <Link
              key={day.key}
              href={`/timeline?date=${day.iso}`}
              aria-label={`${day.iso} ${dict.calendar.openDay}`}
              className={`block min-h-[9rem] border-b border-r border-stone-900/8 p-3 transition dark:border-white/8 ${
                day.inMonth ? "bg-white/70 dark:bg-[#2f2f2f]" : "bg-stone-900/3 dark:bg-white/3"
              } hover:bg-white dark:hover:bg-white/8`}
            >
              <div className="flex items-center justify-between">
                <span
                  className={`inline-flex size-8 items-center justify-center rounded-full text-sm font-semibold ${
                    day.inMonth ? "text-stone-700 dark:text-stone-200" : "text-stone-400 dark:text-stone-500"
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
                    className="rounded-2xl border border-stone-900/8 bg-stone-50 px-3 py-2 dark:border-white/10 dark:bg-white/8"
                  >
                    <p className="truncate text-xs font-semibold text-stone-900 dark:text-stone-100">{event.title}</p>
                    <p className="mt-1 text-[11px] text-stone-500 dark:text-stone-400">
                      {minutesToLabel(event.startMinutes)} - {minutesToLabel(event.endMinutes)}
                    </p>
                  </div>
                ))}
              </div>
            </Link>
          );
        })}
      </div>

      <div className="divide-y divide-stone-900/10 dark:divide-white/10 md:hidden">
        {calendarDays
          .filter((day) => day.inMonth)
          .map((day) => {
            const dayEvents = events.filter((event) => event.date === day.iso);

            return (
              <Link
                key={day.key}
                href={`/timeline?date=${day.iso}`}
                aria-label={`${day.iso} ${dict.calendar.openDay}`}
                className="grid min-h-20 grid-cols-[3.25rem_minmax(0,1fr)] gap-3 px-4 py-3 transition hover:bg-stone-50 dark:hover:bg-white/8"
              >
                <div className="flex flex-col items-center">
                  <span className="inline-flex size-10 items-center justify-center rounded-xl bg-stone-100 text-sm font-semibold text-stone-900 dark:bg-white/8 dark:text-stone-100">
                    {day.day}
                  </span>
                  {dayEvents.length ? (
                    <span className="mt-1 text-[11px] font-medium text-stone-400">{dayEvents.length}</span>
                  ) : null}
                </div>

                <div className="min-w-0 space-y-2">
                  {dayEvents.length ? (
                    dayEvents.slice(0, 2).map((event) => (
                      <div
                        key={event.id}
                        className="rounded-xl border border-stone-900/8 bg-stone-50 px-3 py-2 dark:border-white/10 dark:bg-white/8"
                      >
                        <p className="truncate text-sm font-semibold text-stone-900 dark:text-stone-100">{event.title}</p>
                        <p className="mt-1 text-xs text-stone-500 dark:text-stone-400">
                          {minutesToLabel(event.startMinutes)} - {minutesToLabel(event.endMinutes)}
                        </p>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-xl border border-dashed border-stone-900/10 px-3 py-3 text-xs text-stone-400 dark:border-white/10">
                      No events
                    </div>
                  )}
                  {dayEvents.length > 2 ? (
                    <p className="text-xs text-stone-500 dark:text-stone-400">+{dayEvents.length - 2}</p>
                  ) : null}
                </div>
              </Link>
            );
          })}
      </div>
    </div>
  );
}
