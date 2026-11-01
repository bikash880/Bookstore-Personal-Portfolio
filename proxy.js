import { NextResponse } from "next/server";

const apiServerUrl = (process.env.API_SERVER_URL || process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");
const CACHE_MS = 10_000;
let cached = { maintenance: false, expires: 0 };

async function maintenanceEnabled() {
  if (Date.now() < cached.expires) return cached.maintenance;
  if (!apiServerUrl) return false;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2000);
  try {
    const response = await fetch(`${apiServerUrl}/api/site/status`, { signal: controller.signal, cache: "no-store" });
    const result = response.ok ? await response.json() : null;
    // Fail open: if the status can't be read, keep serving the site rather than locking visitors out.
    cached = { maintenance: Boolean(result?.maintenance), expires: Date.now() + CACHE_MS };
  } catch {
    cached = { maintenance: false, expires: Date.now() + 2000 };
  } finally {
    clearTimeout(timeout);
  }
  return cached.maintenance;
}

export async function proxy(request) {
  const { pathname } = request.nextUrl;
  // The Admin Panel always stays reachable so maintenance can be switched off again.
  if (pathname.startsWith("/admin")) return NextResponse.next();
  if (!(await maintenanceEnabled())) return NextResponse.next();
  const response = NextResponse.rewrite(new URL("/maintenance", request.url), { status: 503 });
  response.headers.set("Retry-After", "300");
  response.headers.set("Cache-Control", "no-store");
  return response;
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|maintenance|icon\\.svg|favicon\\.ico|robots\\.txt|sitemap\\.xml).*)"]
};
