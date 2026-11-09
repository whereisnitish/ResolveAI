import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "resolveai_session";

/**
 * Optimistic routing only: send visitors without a session cookie to /login.
 *
 * This is NOT an authorization check. Django authenticates and authorizes
 * every API call; a stale/invalid cookie is handled by the app shell, which
 * clears it and redirects to /login. (We deliberately don't redirect /login
 * -> /app on cookie presence, which would loop on stale cookies.)
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (!request.cookies.has(SESSION_COOKIE)) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/app/:path*"],
};
