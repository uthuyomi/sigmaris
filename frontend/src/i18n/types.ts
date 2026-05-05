// 役割: 対応言語、ロケール名、画面文言などの国際化設定をまとめる。

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

export type Dictionary = {
  nav: { chat: string; calendar: string; settings: string };
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
