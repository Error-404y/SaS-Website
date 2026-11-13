# SaS Website — authentication security review

## Threat model and scope

The previous implementation served the entire `index.html` application to all visitors. JavaScript hid `#website` behind `#auth-gate`; Chrome DevTools could reveal the interface without login. Backend API authorization already covered some routes, but the full HTML shell was disclosed. A frontend visibility check is never an authorization boundary.

**Corrected design:** `GET /` chooses the response **on the server**:
- With a valid administrator session or an approved member session: complete `index.html`, `Cache-Control: private, no-store`.
- Without one: `login.html` only. That document contains no `#website`, private navigation, or alliance data.
- `GET /index.html` and `GET /app` reject unauthenticated requests with HTTP 401.

The separate `auth.js` runs on the login-only page. `app.js` runs after server-side authorization. UI flags remain convenience controls only; no server decision trusts them.

## Route-by-route access policy

| Endpoint | Required authentication | CSRF / origin policy |
| --- | --- | --- |
| `GET /` | login-only page for guests; complete page for approved members/admin | N/A |
| `GET /index.html`, `GET /app` | Approved member or administrator | N/A |
| `GET /api/state` | Approved member or administrator | N/A |
| `GET /api/accounts` | Administrator only | N/A |
| `GET /api/session` | Public self-session status; no other member data | N/A |
| `POST /api/login`, `POST /api/member/login` | Public authentication entry points | Same-origin checks |
| `POST /api/register` | Public registration entry point | Same-origin checks |
| `POST /api/password/request`, `POST /api/password/complete` | Public password recovery entry points (reset code required for completion) | Same-origin checks |
| `POST /api/logout`, `POST /api/member/logout` | Appropriate active session | Session-specific CSRF + origin checks |
| `PATCH /api/accounts/{id}` | Administrator only | Administrator CSRF + origin checks |
| `PATCH /api/password/requests/{id}` | Administrator only | Administrator CSRF + origin checks |
| `POST /api/entries`, `PUT /api/entries/{id}`, `DELETE /api/entries/{id}` | Administrator only | Administrator CSRF + origin checks |
| `PUT /api/rss`, `POST /api/rss/spending`, `DELETE /api/rss/spending/{id}` | Administrator only | Administrator CSRF + origin checks |
| `GET /auth.js`, CSS, images, utility scripts | Public static files; **no private data** | N/A |

Public registration/login/recovery endpoints are intentional exceptions to the rule requiring an authenticated session; requiring a session there would make login and registration impossible.

## Session and cookie controls

- Administrator cookies: `sas_session`, random 256-bit token, SHA-256 digest stored in SQLite, 12-hour maximum.
- Approved player cookies: `sas_member`, random 256-bit token, SHA-256 digest stored in SQLite, 30-day maximum.
- Both cookies: `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` when `SAS_COOKIE_SECURE=1`.
- No user-controlled role flag is trusted; every privilege check joins against database session/state.
- Logout deletes the server session and redirects to the server-rendered login page, discarding private in-memory state.
- Rejection/revocation invalidates member sessions.
- Authenticated API data and application HTML must not be cached across users.
- Mutating requests require a matching Origin when sent by browsers and reject cross-site `Sec-Fetch-Site`; authenticated mutations additionally require the per-session `X-CSRF-Token`.

## Run the automated regression tests

```bash
python -m unittest discover -s tests -v
python -m py_compile server.py members.py main.py
node --check auth.js
node --check app.js
node --test tests/calendar.test.cjs tests/rss.test.cjs tests/unread.test.cjs
```

## Manual production security test checklist

**Use a private/incognito window without cookies. Do not use a live administrator password in screenshots.**

- [ ] GET `/` displays the sign-in form and the browser's response HTML has **no** `id="website"` or `id="page-accounts"`.
- [ ] DevTools `document.getElementById("website")` returns `null` as a guest; the former CSS bypass cannot reveal private content.
- [ ] Visiting `/index.html` or `/app` without a session returns 401, not the application HTML.
- [ ] `GET /api/state` as a guest returns 401; `GET /api/accounts` returns 403.
- [ ] Unauthenticated `POST /api/entries` and `PUT /api/rss` return 403.
- [ ] A new registered **pending** player cannot sign in or retrieve protected HTML/API data.
- [ ] A **rejected** player cannot sign in or retrieve protected data.
- [ ] An **approved** player can sign in, see Events/Alliance RSS, and load `GET /api/state`.
- [ ] An approved player receives 403 from `GET /api/accounts`, account approval, password request review, event write, and RSS write routes, even with their own CSRF token.
- [ ] An admin can sign in, see SaS – Accounts, list members, approve/reject players, post events, edit RSS, and review password resets.
- [ ] Admin writes fail with 403 if `X-CSRF-Token` is missing or invalid.
- [ ] Authenticated writes with an unrelated `Origin` header or `Sec-Fetch-Site: cross-site` fail with 403.
- [ ] Cookies show `Secure; HttpOnly; SameSite=Lax` in production (HTTPS).
- [ ] Logout invalidates the session: reusing the old cookie fails and browser navigation returns the login-only page.
- [ ] An expired or revoked session can no longer fetch private HTML or API data.
- [ ] Refreshing after successful login preserves approved access until session expiry; clearing browser cookies signs out.
- [ ] Check the reverse-proxy configuration: `SAS_COOKIE_SECURE=1` and no public caching of authenticated HTML.

**Important:** Previously delivered data cannot be erased from a person's memory, screenshots, or a DevTools view while their session was valid. The objective is to prevent *future server access* after logout/revocation and prevent any protected data delivery before login.

## Deployment and remaining operational risks

1. Back up the persistent SQLite DB configured in `SAS_DB_PATH`; never put it in a web-served directory.
2. Deploy over HTTPS with `SAS_COOKIE_SECURE=1`. Keep `SAS_ADMIN_PASSWORD` secret, strong, and outside Git.
3. Restart the Python app and confirm the new `login.html` and `auth.js` are deployed alongside `server.py`.
4. Verify GitHub Actions tests, then repeat the manual checklist against the live domain.
5. Rate limiting is currently local SQLite-backed and based on connection source; a reverse proxy can make multiple visitors share a source. For high traffic or multiple replicas, use a trusted-edge rate limiter and consider admin MFA.
6. Review backups, TLS termination, file access permissions, server logs, and dependency/hosting configuration. Passing these tests does not constitute a full external penetration test.
