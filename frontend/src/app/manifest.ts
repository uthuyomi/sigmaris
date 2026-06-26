import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "シグマリス",
    short_name: "シグマリス",
    description: "あなたの家庭支援AI",
    start_url: "/launch",
    scope: "/",
    display: "standalone",
    background_color: "#212121",
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
