import Link from "next/link";
import { minutesToLabel, scheduleEvents } from "@/lib/mock-schedule";

const calendarDays = Array.from({ length: 35 }, (_, index) => {
  const day = index - 1;
  const date = new Date(2026, 2, day);
  return {
    key: `${date.toISOString()}-${index}`,
    day: date.getDate(),
    inMonth: date.getMonth() === 2,
    iso: date.toISOString().slice(0, 10),
  };
});

const weekLabels = ["月", "火", "水", "木", "金", "土", "日"];

export function CalendarBoard() {
  return (
    <div className="flex min-h-[42rem] flex-col overflow-hidden rounded-[32px] border border-stone-900/10 bg-white/75 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
      <div className="border-b border-stone-900/10 px-5 py-5">
        <p className="text-xs font-medium uppercase tracking-[0.3em] text-stone-500">
          Calendar
        </p>
        <div className="mt-1 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-stone-900">2026年3月の予定一覧</h2>
            <p className="mt-2 text-sm leading-7 text-stone-600">
              月表示で予定の密度を俯瞰して、日付を押したらその日のタイムラインへ降りる。
            </p>
          </div>
          <div className="rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-stone-50">
            今月は {scheduleEvents.length} 件
          </div>
        </div>
      </div>

      <div className="grid grid-cols-7 border-b border-stone-900/10 bg-stone-900/5 px-4 py-3">
        {weekLabels.map((label) => (
          <div key={label} className="px-2 text-sm font-medium text-stone-600">
            {label}
          </div>
        ))}
      </div>

      <div className="grid flex-1 grid-cols-7">
        {calendarDays.map((day) => {
          const events = scheduleEvents.filter((event) => event.date === day.iso);
          const active = day.iso === "2026-03-27";

          return (
            <Link
              key={day.key}
              href={`/timeline?date=${day.iso}`}
              className={`block min-h-[9rem] border-b border-r border-stone-900/8 p-3 transition ${
                day.inMonth ? "bg-white/70" : "bg-stone-900/3"
              } ${active ? "ring-1 ring-[#e76f51]/45 ring-inset" : ""} hover:bg-white`}
            >
              <div className="flex items-center justify-between">
                <span
                  className={`inline-flex size-8 items-center justify-center rounded-full text-sm font-semibold ${
                    active ? "bg-stone-900 text-stone-50" : "text-stone-700"
                  }`}
                >
                  {day.day}
                </span>
                {events.length ? (
                  <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-stone-400">
                    {events.length}件
                  </span>
                ) : null}
              </div>

              <div className="mt-3 space-y-2">
                {events.slice(0, 3).map((event) => (
                  <div
                    key={event.id}
                    className="rounded-2xl border border-stone-900/8 bg-stone-50 px-3 py-2"
                  >
                    <p className="text-xs font-semibold text-stone-900">{event.title}</p>
                    <p className="mt-1 text-[11px] text-stone-500">
                      {minutesToLabel(event.startMinutes)} -{" "}
                      {minutesToLabel(event.endMinutes)}
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
