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

export const hasGoogleCalendarWriteConfig = () => hasGoogleOAuthConfig();

export const createGoogleCalendarEvents = async (
  events: CalendarWriteEvent[],
  calendarId = process.env.GOOGLE_CALENDAR_ID ?? "primary",
) => {
  if (!events.length) {
    return [];
  }

  const tokens = await readGoogleProviderTokens();
  const auth = createGoogleOAuthClient(tokens);
  const calendar = google.calendar({ version: "v3", auth });

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
