import type { Metadata, Viewport } from "next";
// Bootstrap Italia, the kit of the Italian public administration: served from here, no CDN.
import "bootstrap-italia/dist/css/bootstrap-italia.min.css";
import "leaflet/dist/leaflet.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Il suolo si muove? · egms-client",
  description:
    "Il movimento del suolo misurato dai satelliti (EGMS, Copernicus), per un Comune: quanto, dove e quanto fidarsi.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function Layout({ children }: { children: React.ReactNode }) {
  const lang = process.env.EGMS_UI_LANG === "en" ? "en" : "it";
  return (
    <html lang={lang}>
      <body>{children}</body>
    </html>
  );
}
