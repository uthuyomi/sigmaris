// 役割: Google Calendar APIとの予定同期・登録処理をまとめる。

import { google } from "googleapis";
import { createGoogleOAuthClient, hasGoogleOAuthConfig } from "@/lib/google/oauth";
import { readGoogleProviderTokens } from "@/lib/google/provider-tokens";

export type CalendarWriteEvent = {
  title: string;
  start: string;
  end: string;
  description?: string;
  location?: string;
};

export type CalendarListedEvent = {
  id: string | null | undefined;
  summary: string | null | undefined;
  description: string | null | undefined;
  location: string | null | undefined;
  htmlLink: string | null | undefined;
  status: string | null | undefined;
  start: string | null | undefined;
  end: string | null | undefined;
};

export const hasGoogleCalendarWriteConfig = () => hasGoogleOAuthConfig();

const createCalendarClient = async () => {
  const tokens = await readGoogleProviderTokens();
  const auth = createGoogleOAuthClient(tokens);
  return google.calendar({ version: "v3", auth });
};

export const listGoogleCalendarEvents = async (input: {
  calendarId?: string;
  timeMin?: string;
  timeMax?: string;
  maxResults?: number;
  query?: string;
  showDeleted?: boolean;
}) => {
  const calendar = await createCalendarClient();
  const calendarId = input.calendarId ?? process.env.GOOGLE_CALENDAR_ID ?? "primary";

  const result = await calendar.events.list({
    calendarId,
    timeMin: input.timeMin,
    timeMax: input.timeMax,
    maxResults: input.maxResults ?? 10,
    q: input.query,
    singleEvents: true,
    orderBy: "startTime",
    showDeleted: input.showDeleted,
  });

  return (result.data.items ?? []).map<CalendarListedEvent>((event) => ({
    id: event.id,
    summary: event.summary,
    description: event.description,
    location: event.location,
    htmlLink: event.htmlLink,
    status: event.status,
    start: event.start?.dateTime ?? event.start?.date,
    end: event.end?.dateTime ?? event.end?.date,
  }));
};

export const createGoogleCalendarEvents = async (
  events: CalendarWriteEvent[],
  calendarId = process.env.GOOGLE_CALENDAR_ID ?? "primary",
) => {
  if (!events.length) {
    return [];
  }

  const calendar = await createCalendarClient();
  const created = [];

  for (const event of events) {
    const result = await calendar.events.insert({
      calendarId,
      requestBody: {
        summary: event.title,
        description: event.description,
        location: event.location,
        start: {
          dateTime: event.start,
          timeZone: "Asia/Tokyo",
        },
        end: {
          dateTime: event.end,
          timeZone: "Asia/Tokyo",
        },
      },
    });

    created.push({
      id: result.data.id,
      htmlLink: result.data.htmlLink,
      summary: result.data.summary,
      start: result.data.start?.dateTime,
      end: result.data.end?.dateTime,
    });
  }

  return created;
};

export const deleteGoogleCalendarEvents = async (
  eventIds: string[],
  calendarId = process.env.GOOGLE_CALENDAR_ID ?? "primary",
) => {
  if (!eventIds.length) {
    return [];
  }

  const calendar = await createCalendarClient();
  const deleted = [];

  for (const eventId of eventIds) {
    await calendar.events.delete({
      calendarId,
      eventId,
    });

    deleted.push({ id: eventId });
  }

  return deleted;
};

export const deleteGoogleCalendarEventsInRange = async (input: {
  calendarId?: string;
  timeMin: string;
  timeMax: string;
  query?: string;
  maxResults?: number;
}) => {
  const calendarId = input.calendarId ?? process.env.GOOGLE_CALENDAR_ID ?? "primary";
  const events = await listGoogleCalendarEvents({
    calendarId,
    timeMin: input.timeMin,
    timeMax: input.timeMax,
    query: input.query,
    maxResults: input.maxResults ?? 250,
  });

  const deletable = events.filter((event) => event.id && event.status !== "cancelled");
  const deleted = await deleteGoogleCalendarEvents(
    deletable.map((event) => event.id as string),
    calendarId,
  );

  return {
    matchedCount: events.length,
    deletedCount: deleted.length,
    deletedIds: deleted.map((event) => event.id),
    deletedEvents: deletable,
  };
};
