type RouteLoadingSkeletonProps = {
  fitViewport?: boolean;
};

export function RouteLoadingSkeleton({ fitViewport = false }: RouteLoadingSkeletonProps) {
  return (
    <main className="min-h-screen bg-[#f7f7f8] text-stone-950 dark:bg-[#212121] dark:text-stone-100">
      <div
        className={[
          "mx-auto flex min-h-screen w-full max-w-[1500px] flex-col px-3 pb-4 pt-3 sm:px-4 lg:px-5",
          fitViewport ? "h-[100dvh] min-h-0 overflow-hidden" : "",
        ].join(" ")}
      >
        <header className="mb-3 rounded-2xl border border-stone-900/10 bg-white px-3 py-3 shadow-[0_14px_45px_-34px_rgba(28,25,23,0.45)] dark:border-white/10 dark:bg-[#2f2f2f] sm:px-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <div className="size-10 animate-pulse rounded-xl bg-stone-200 dark:bg-white/10" />
              <div className="min-w-0 space-y-2">
                <div className="h-4 w-36 animate-pulse rounded-full bg-stone-200 dark:bg-white/10" />
                <div className="hidden h-3 w-64 animate-pulse rounded-full bg-stone-100 dark:bg-white/8 md:block" />
              </div>
            </div>
            <div className="flex items-center gap-2">
              <div className="size-10 animate-pulse rounded-xl bg-stone-200 dark:bg-white/10" />
              <div className="size-10 animate-pulse rounded-xl bg-stone-200 dark:bg-white/10" />
              <div className="size-10 animate-pulse rounded-xl bg-stone-200 dark:bg-white/10" />
            </div>
          </div>
        </header>

        <section className={["min-h-0 flex-1", fitViewport ? "overflow-hidden" : ""].join(" ")}>
          <div className="h-full rounded-2xl border border-stone-900/10 bg-white p-4 shadow-sm dark:border-white/10 dark:bg-[#2f2f2f]">
            <div className="grid h-full gap-4 lg:grid-cols-[1fr_0.85fr]">
              <div className="space-y-3">
                <div className="h-10 w-48 animate-pulse rounded-xl bg-stone-100 dark:bg-white/8" />
                <div className="h-48 animate-pulse rounded-2xl bg-stone-100 dark:bg-white/8" />
                <div className="h-48 animate-pulse rounded-2xl bg-stone-100 dark:bg-white/8" />
              </div>
              <div className="hidden space-y-3 lg:block">
                <div className="h-24 animate-pulse rounded-2xl bg-stone-100 dark:bg-white/8" />
                <div className="h-24 animate-pulse rounded-2xl bg-stone-100 dark:bg-white/8" />
                <div className="h-24 animate-pulse rounded-2xl bg-stone-100 dark:bg-white/8" />
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
