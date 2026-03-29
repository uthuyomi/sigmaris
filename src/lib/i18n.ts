export const supportedLocales = [
  "ja",
  "en",
  "ko",
  "zh-CN",
  "zh-TW",
  "es",
  "fr",
  "de",
  "pt-BR",
  "it",
  "id",
  "th",
  "vi",
] as const;

export type AppLocale = (typeof supportedLocales)[number];

export const defaultLocale: AppLocale = "ja";

type Dictionary = {
  nav: {
    chat: string;
    calendar: string;
    settings: string;
  };
  common: {
    appName: string;
    statusOn: string;
    statusOff: string;
    unavailable: string;
    today: string;
    backToCalendar: string;
    syncNow: string;
    loading: string;
    save: string;
  };
  shell: {
    chatTitle: string;
    chatDescription: string;
    calendarTitle: string;
    calendarDescription: string;
    timelineTitle: string;
    timelineDescription: string;
    settingsTitle: string;
    settingsDescription: string;
    chatBadge: string;
    calendarBadge: string;
    timelineBadge: string;
    settingsBadge: string;
  };
  chat: {
    assistant: string;
    welcomeTitle: string;
    welcomeBody: string;
    inputPlaceholder: string;
    threadList: string;
    newThread: string;
    renameThread: string;
    deleteThread: string;
    renamePrompt: string;
    deleteConfirm: string;
    emptyThreadTitle: string;
  };
  calendar: {
    title: string;
    previousMonth: string;
    nextMonth: string;
    openDay: string;
    eventsCount: string;
    weekdays: string[];
  };
  timeline: {
    title: string;
    selectedDay: string;
    selectedGrain: string;
    quickEdit: string;
    start: string;
    end: string;
    sourceSync: string;
    sourceApp: string;
    place: string;
    refine: string;
    humanLogic: string;
    logicItems: string[];
  };
  settings: {
    account: string;
    sync: string;
    language: string;
    integrations: string;
    environment: string;
    statusReady: string;
    statusMissing: string;
    languageHint: string;
    syncTitle: string;
    syncBody: string;
    syncSuccess: string;
    syncError: string;
    syncDisabled: string;
  };
  auth: {
    signIn: string;
    signOut: string;
    signingIn: string;
    signedInAs: string;
    unavailable: string;
    signInError: string;
    signOutError: string;
  };
};

const baseJa: Dictionary = {
  nav: {
    chat: "会話",
    calendar: "予定",
    settings: "設定",
  },
  common: {
    appName: "ShiftPilotAI",
    statusOn: "オン",
    statusOff: "オフ",
    unavailable: "未接続",
    today: "今日",
    backToCalendar: "月表示へ",
    syncNow: "今すぐ同期",
    loading: "処理中",
    save: "保存",
  },
  shell: {
    chatTitle: "チャット",
    chatDescription: "会話、画像、URLをまとめて扱う",
    calendarTitle: "カレンダー",
    calendarDescription: "月から日を選んで予定を開く",
    timelineTitle: "デイビュー",
    timelineDescription: "1日の流れを細かく確認する",
    settingsTitle: "設定",
    settingsDescription: "連携、言語、既定値を調整する",
    chatBadge: "AI",
    calendarBadge: "月",
    timelineBadge: "日",
    settingsBadge: "環境",
  },
  chat: {
    assistant: "アシスタント",
    welcomeTitle: "今日は何を組む？",
    welcomeBody: "予定の相談、画像の取り込み、シートの読み込みをここで続けられる。",
    inputPlaceholder: "メッセージ、画像、シートURL",
    threadList: "スレッド",
    newThread: "新規スレッド",
    renameThread: "名前変更",
    deleteThread: "削除",
    renamePrompt: "スレッド名を入力",
    deleteConfirm: "このスレッドを削除しますか？",
    emptyThreadTitle: "新しい会話",
  },
  calendar: {
    title: "月表示",
    previousMonth: "前の月",
    nextMonth: "次の月",
    openDay: "その日の予定を開く",
    eventsCount: "件",
    weekdays: ["月", "火", "水", "木", "金", "土", "日"],
  },
  timeline: {
    title: "1日の流れ",
    selectedDay: "日付",
    selectedGrain: "粒度",
    quickEdit: "注目予定",
    start: "開始",
    end: "終了",
    sourceSync: "同期",
    sourceApp: "アプリ",
    place: "場所",
    refine: "この粒度で見る",
    humanLogic: "見方",
    logicItems: [
      "まず日付を選ぶ",
      "必要な時だけ粒度を細かくする",
      "移動がある日は出発時刻も見る",
    ],
  },
  settings: {
    account: "アカウント",
    sync: "同期",
    language: "言語",
    integrations: "連携状況",
    environment: "開発設定",
    statusReady: "接続済み",
    statusMissing: "未設定",
    languageHint: "表示言語を切り替える",
    syncTitle: "Google カレンダー同期",
    syncBody: "オンで双方向同期、オフでこのアプリのみ。",
    syncSuccess: "同期完了",
    syncError: "同期に失敗した",
    syncDisabled: "同期オフ",
  },
  auth: {
    signIn: "Google でログイン",
    signOut: "ログアウト",
    signingIn: "接続中",
    signedInAs: "接続中",
    unavailable: "Supabase 未設定",
    signInError: "ログインに失敗した",
    signOutError: "ログアウトに失敗した",
  },
};

const localeOverrides: Partial<Record<AppLocale, Partial<Dictionary>>> = {
  en: {
    nav: { chat: "Chat", calendar: "Calendar", settings: "Settings" },
    common: {
      appName: "ShiftPilotAI",
      statusOn: "On",
      statusOff: "Off",
      unavailable: "Unavailable",
      today: "Today",
      backToCalendar: "Month view",
      syncNow: "Sync now",
      loading: "Loading",
      save: "Save",
    },
    shell: {
      chatTitle: "Chat",
      chatDescription: "Messages, images, and links in one thread",
      calendarTitle: "Calendar",
      calendarDescription: "Pick a day from the month view",
      timelineTitle: "Day View",
      timelineDescription: "Inspect one day in fine detail",
      settingsTitle: "Settings",
      settingsDescription: "Tune integrations, language, and defaults",
      chatBadge: "AI",
      calendarBadge: "Month",
      timelineBadge: "Day",
      settingsBadge: "Setup",
    },
    chat: {
      assistant: "Assistant",
      welcomeTitle: "What should we schedule?",
      welcomeBody: "Keep planning, imports, and edits in one thread.",
      inputPlaceholder: "Message, image, or sheet URL",
      threadList: "Threads",
      newThread: "New thread",
      renameThread: "Rename",
      deleteThread: "Delete",
      renamePrompt: "Rename thread",
      deleteConfirm: "Delete this thread?",
      emptyThreadTitle: "New chat",
    },
    calendar: {
      title: "Month",
      previousMonth: "Previous month",
      nextMonth: "Next month",
      openDay: "Open day",
      eventsCount: "items",
      weekdays: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    },
    timeline: {
      title: "Day flow",
      selectedDay: "Day",
      selectedGrain: "Zoom",
      quickEdit: "Focus event",
      start: "Start",
      end: "End",
      sourceSync: "Sync",
      sourceApp: "App",
      place: "Place",
      refine: "View at this grain",
      humanLogic: "Hints",
      logicItems: [
        "Pick the day first",
        "Zoom in only when needed",
        "Check departure time when travel is involved",
      ],
    },
    settings: {
      account: "Account",
      sync: "Sync",
      language: "Language",
      integrations: "Integrations",
      environment: "Environment",
      statusReady: "Ready",
      statusMissing: "Missing",
      languageHint: "Choose the display language",
      syncTitle: "Google Calendar Sync",
      syncBody: "On for two-way sync, off for app-only changes.",
      syncSuccess: "Sync completed",
      syncError: "Sync failed",
      syncDisabled: "Sync off",
    },
    auth: {
      signIn: "Sign in with Google",
      signOut: "Sign out",
      signingIn: "Signing in",
      signedInAs: "Signed in",
      unavailable: "Supabase not configured",
      signInError: "Sign-in failed",
      signOutError: "Sign-out failed",
    },
  },
};

const mergeDictionary = (locale: AppLocale): Dictionary => {
  const override = localeOverrides[locale] ?? (locale === "ja" ? undefined : localeOverrides.en);
  if (!override) return baseJa;

  return {
    ...baseJa,
    ...override,
    nav: { ...baseJa.nav, ...override.nav },
    common: { ...baseJa.common, ...override.common },
    shell: { ...baseJa.shell, ...override.shell },
    chat: { ...baseJa.chat, ...override.chat },
    calendar: { ...baseJa.calendar, ...override.calendar },
    timeline: { ...baseJa.timeline, ...override.timeline },
    settings: { ...baseJa.settings, ...override.settings },
    auth: { ...baseJa.auth, ...override.auth },
  };
};

export const normalizeLocale = (value?: string | null): AppLocale => {
  if (!value) return defaultLocale;
  const matched = supportedLocales.find(
    (locale) => locale.toLowerCase() === value.toLowerCase(),
  );
  return matched ?? defaultLocale;
};

export const getDictionary = (locale?: string | null) => mergeDictionary(normalizeLocale(locale));

export const formatLocaleName = (locale: AppLocale, displayLocale: AppLocale) => {
  try {
    const names = new Intl.DisplayNames([displayLocale], { type: "language" });
    return names.of(locale.split("-")[0]) ?? locale;
  } catch {
    return locale;
  }
};
