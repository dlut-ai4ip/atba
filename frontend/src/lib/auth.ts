// Storing/retrieving the login token — pairs with the backend's atba/auth.py: a single account
// (username/password configured in backend environment variables, not here); once login succeeds the
// backend issues an opaque token, and this file is only responsible for storing/retrieving/clearing
// it, never parsing its content (validation always happens on the backend — what's stored here is
// only the basis for "should this be attached to the request header," not a source of trust).
//
// "Remember me" gives this token a real semantic distinction, not just for show: checked stores it in
// localStorage (survives closing the browser/restarting the computer), unchecked stores it in
// sessionStorage (gone once this tab closes) — getToken() checks both, so callers don't need to care
// which one it's actually stored in.
const TOKEN_KEY = "atba-token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY) ?? sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string, remember: boolean): void {
  if (remember) {
    localStorage.setItem(TOKEN_KEY, token);
    sessionStorage.removeItem(TOKEN_KEY);
  } else {
    sessionStorage.setItem(TOKEN_KEY, token);
    localStorage.removeItem(TOKEN_KEY);
  }
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
}

// Just a check for "is a token stored locally" — doesn't mean the token definitely hasn't expired/
// definitely will be accepted by the backend; that's only known once a real request is made and
// whether the backend returns a 401, see request()/streamPost() in api.ts. This is used as a route
// guard (App.tsx's RequireAuth): without a token, there's no need to wait for an API call that's bound
// to fail — jump straight to the login page.
export function isAuthenticated(): boolean {
  return !!getToken();
}
