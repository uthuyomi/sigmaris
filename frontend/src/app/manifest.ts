import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "ShiftPilotAI",
    short_name: "ShiftPilotAI",
    description:
      "AI scheduler that turns shift table screenshots and Google Sheets into calendar events with travel-time planning.",
    start_url: "/launch",
    scope: "/",
    display: "standalone",
    background_color: "#f7f2e8",
    theme_color: "#212121",
    orientation: "portrait",
    icons: [
      {
        src: "/images/icon/icon.png",
        sizes: "1254x1254",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/images/icon/icon.png",
        sizes: "1254x1254",
        type: "image/png",
        purpose: "maskable",
      },
      {
        src: "/images/icon/icon.ico",
        sizes: "48x48",
        type: "image/x-icon",
      },
    ],
  };
}
