// Who may put this page in an iframe: EGMS_UI_FRAME_ANCESTORS, read at every request,
// such as "https://www.comune.pozzuoli.na.it". Without it, only this site itself.
import { NextResponse } from "next/server";

export function proxy() {
  const ancestors = process.env.EGMS_UI_FRAME_ANCESTORS?.trim() || "'self'";
  const response = NextResponse.next();
  response.headers.set("Content-Security-Policy", `frame-ancestors ${ancestors}`);
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set("X-Content-Type-Options", "nosniff");
  return response;
}

export const config = { matcher: "/((?!_next/static|_next/image|favicon.ico).*)" };
