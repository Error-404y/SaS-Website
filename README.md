# Saints and Sinners Website

The alliance website has five separate sections: Events, Alliance Events, Alliance RSS, Website Updates and HR Announcements.

The website now requires an approved SaS member account. New players register with a username, in-game player name, email and password, then enter the administrator review queue. The server serves a separate login-only document to guests. The full website HTML is delivered only to an approved member or administrator session; changing CSS or JavaScript in DevTools cannot obtain server-protected application data.

The Saints and Sinners crest appears on the welcome screen, in the header and in the navigation. The entrance uses a sharper transparent AVIF crest derived from the supplied artwork with a WebP fallback, subtle motion, and a smooth transition after **Bring me in!** is pressed. The rest of the website keeps its clean, light design. Motion is reduced when the visitor enables reduced-motion accessibility settings. The website is responsive and works on desktop, tablet and mobile.

## Sections

**Events** lists current and upcoming game events, their categories, exact UTC start/end times and statuses. Click an event to see its rewards and notes. Each upcoming event has a live `Starts in` countdown, and each ongoing event has a live `Ends in` countdown.

**Alliance Events** uses a completely separate event list with the same detail view and live countdowns.

**Alliance RSS** shows separate **Ammo, Cash, Electricity and Gas** balances, hourly production, the individual resource capacities, territory notes, a live research countdown, and territory buff values. Unrecorded amounts remain blank instead of being presented as real game data.

An administrator can use **Edit RSS** to enter the current balances, hourly production rates, individual capacity limits (default **1,200,000** each), technology name and stage, territory notes and buffs. Enter `122400` for a rate of `122.4K/h`. Balances increase automatically according to their configured rates and stop at the capacity. Zero is a valid recorded value, different from an empty field.

For research, enter an actual time remaining such as `01:45:00` rather than a percentage. The server saves a UTC completion deadline; everyone sees the same countdown, even after refreshing or restarting the server. Changing unrelated RSS figures does not restart the timer unless the remaining-time field is changed.

**Spend resources** records which resource was used, how much was spent, a UTC timestamp (`YYYY-MM-DD HH:MM:SS`) and an optional reason. A spending record must be timestamped after the latest manually saved resource balance and cannot be in the future or exceed the available balance at that moment. The server recalculates spending chronologically, applies the maximum-capacity rule before each expense, and resumes hourly production when resources are spent. Staff can remove incorrect entries. Historical spending entries remain visible after a balance reset, but are not deducted twice. Saving new balances creates a fresh starting point.

The small navigation badges indicate newly created or edited items in each section, plus updates to Alliance RSS. They clear when the member opens the section and remember what that browser has already seen. They are not account-wide push notifications.

This page is manually updated, not connected to live game servers. Earlier single-total RSS entries remain stored in the database and can be viewed by administrators if no per-resource rates are entered; the website does not automatically distribute a historical aggregate across different resource types. Existing technology notes are retained.

**Website Updates** holds website news.

**HR Announcements** holds leadership announcements attributed to R4 or R5.

**Personal calendar reminders:** Open an event's details and choose **Add to Google Calendar** or **Download calendar file (.ics)**. Google Calendar opens a prefilled event for the member to save. The ICS file can be imported into Apple Calendar, Outlook or other compatible calendars, and includes a one-hour alert for calendar apps that support imported alerts. All event times remain UTC. Google Calendar notifications depend on each member's own calendar settings.

The Events page initially contains the eight names and dates from the supplied Event Center screenshot. Those are starting records, not a live sync with the Discord bot or the game. Ended events remain in the database and are available through the **Ended** filter.

## Member accounts and administrator approval

Visitors must register and be approved before they can read any alliance data. New registrations are stored in SQLite with per-user salted scrypt password hashes; approval status is initially pending. Pending and rejected users cannot sign in. Rejected registrations receive a mandatory administrator review reason, which is shown when they attempt to log in. Approved players can sign in subsequently without repeating approval. Member sessions persist for up to 30 days through an HttpOnly cookie; revoking access invalidates existing sessions. Only administrators can access the **SaS – Accounts** page to review, approve, reject or revoke accounts. This does not connect to an in-game identity provider or automatically verify alliance membership.

The `/api/state` endpoint requires an approved member or administrator session. `/api/accounts` and every administrative write require a server-validated administrator session. The full application HTML (`/index.html` or `/app`) also requires an approved member or administrator session; guests receive only `login.html` at `/`. CSS and utility scripts are public but contain no private data. For the route access matrix and production verification checklist, see [SECURITY_TESTING.md](SECURITY_TESTING.md).

### Persistence and deployment

The existing SQLite database configured by `SAS_DB_PATH` also contains `members` and `member_sessions` tables, created automatically on the next start. Keep this database file on persistent storage and back it up before deployment. Never commit the SQLite database, passwords or session tokens. HTTPS with `SAS_COOKIE_SECURE=1` is required in production.

### Account details and password recovery

In **SaS – Accounts**, click any player's in-game name to open the account details popup. It displays the in-game name, username, email, account status, registration date and review note. **Passwords cannot be viewed**: only password hashes are stored.

If a player forgets their password, they select **Forgot your password?** on the login page and submit their username or email. The request is saved in the existing SQLite database, subject to a per-account 15-minute request interval. The response is intentionally identical for known and unknown accounts.

Administrators can approve or reject the request under **SaS – Accounts → Password change requests**. A rejection requires an explanation. Approval generates a cryptographically random, single-use reset code displayed once to the administrator; it expires after one hour. The administrator must verify the player's identity and share the code via a trusted private channel. The player selects **I have a reset code**, enters the code, username and a new password (minimum 12 characters). Existing player sessions are revoked when the password changes. The website does not automatically email reset codes, and administrators cannot retrieve a code after dismissing it; the player may request another after the request interval.

## Editor access

Only authorized site editors can change information. Choose **Admin login** and sign in using the credentials configured privately on the host. Editors can add, edit and delete events, announcements and updates, and change the RSS figures. Each edit is saved to a SQLite file shared by all website visitors.

The initial administrator username defaults to admin. Set a strong private password through SAS_ADMIN_PASSWORD; with no password set, administrator login is disabled.

R4/R5 attribution on announcements is selected by the website editor. There is not yet Discord-role authentication or an automatic Discord bot data sync.

## Deploy on Bot-Hosting.net

Use a **Python Application**, not a static-only website deployment. The startup file is main.py, or start with python3 main.py. Python 3.11 or newer works, and no third-party packages are needed.

Configure these environment variables privately through the hosting panel or a .env file in the same directory as main.py:

    SAS_HOST=0.0.0.0
    SAS_ADMIN_USERNAME=admin
    SAS_ADMIN_PASSWORD=YOUR_LONG_PRIVATE_PASSWORD
    SAS_DB_PATH=/home/container/data/website.sqlite3
    SAS_COOKIE_SECURE=1
    SAS_DISCORD_WEBHOOK_URL=

The application uses SERVER_PORT provided by Bot-Hosting, then PORT, and finally 8080.

Keep SAS_COOKIE_SECURE=1 when accessing the website over HTTPS. For local HTTP development only, use SAS_COOKIE_SECURE=0.

The .env file and local SQLite databases are ignored by Git. Never commit administrator credentials or webhook tokens.

**Persistence matters:** The SQLite database path must remain on persistent storage when your service restarts or redeploys. Back up the database before changing your hosting runtime.

### Optional one-hour Discord reminder

You can set SAS_DISCORD_WEBHOOK_URL to a private Discord channel webhook URL. The server then checks upcoming events and sends a message in the channel when they are within an hour of starting, including an @everyone mention. Events already in progress will not receive pre-start reminders.

The reminder is based on the website's event records and does not automatically import events from the existing Discord bot. The hosting process must remain running to deliver notifications.

### Run locally

    SAS_COOKIE_SECURE=0 SAS_ADMIN_PASSWORD=choose-a-password python3 main.py

Open http://localhost:8080. Use a private password, especially when the service is reachable by other devices.

## Development

Run checks with:

    python3 -m unittest discover -s tests -v
    python3 -m py_compile server.py main.py
    node --check app.js
    node --check rss.js
    node --test tests/rss.test.cjs
    node --check unread.js
    node --test tests/unread.test.cjs

The code uses plain HTML, CSS, browser JavaScript, Python's built-in HTTP server and SQLite.
