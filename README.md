# Saints and Sinners Website

The alliance website has five separate sections: Events, Alliance Events, Alliance RSS, Website Updates and HR Announcements.

The website now requires an approved SaS member account. New players register with a username, in-game player name, email and password, then enter the administrator review queue. The server serves a separate login-only document to guests. The full website HTML is delivered only to an approved member or administrator session; changing CSS or JavaScript in DevTools cannot obtain server-protected application data.

The Saints and Sinners crest appears on the welcome screen, in the header and in the navigation. The entrance uses a sharper transparent AVIF crest derived from the supplied artwork with a WebP fallback, subtle motion, and a smooth transition after **Bring me in!** is pressed. The rest of the website keeps its clean, light design. Motion is reduced when the visitor enables reduced-motion accessibility settings. The website is responsive and works on desktop, tablet and mobile.

## Website maintenance / Under Construction

Set the following value in your host's environment settings or `.env` file (the key name is case-sensitive):

```dotenv
Const-Web=true
```

**true:** The server responds at `/` with the standalone **Under Construction** page (HTTP 503). There is no navigation or account login. All API routes, registration, logins, administrator functions, private HTML/JS, and changes are disabled for everyone, **including administrators with an existing session**. Only the logo asset required by the maintenance page is served.

**false:** Normal website operation resumes, including registration, player login, admin login, and the usual server-side access controls.

```dotenv
Const-Web=false
```

**Restart the Python application after changing this value.** Changing the `.env` file alone does not update a running server. The switch changes access control, not the database: accounts, events and RSS information remain saved. Keep `SAS_DB_PATH` persistent. The maintenance document is `maintenance.html` and is intentionally separate from the login and application pages. It contains the approved purple SaS Under Construction artwork embedded as a self-contained WebP image (no separate image upload is required), with **no navigation or sign-in controls**. During maintenance **every other path**, including images, scripts, private pages and API routes, returns HTTP 503.

## Messenger bug fixes and account email privacy

- The signed-in member bootstrap now consistently starts Messenger with the actual CSRF token from `/api/member/login` or `/api/session` after a page refresh. An old undefined `session` reference in the login flow previously interrupted setup.
- Messenger can recover from a **confirmed Invalid CSRF token** rejection by refreshing the authenticated session and retrying once; it never retries unrelated authorization failures.
- The Players directory shows the logged-in approved account as **Your profile**. In **Create Group**, this creator is labelled as included automatically; searches look for *other* approved accounts. A group may be created with only the creator if no other players are available. Other players are still excluded until explicitly invited.
- Mobile conversation loads no longer wait for an unrelated stale chat request; initial history displays before asynchronous read-receipt writes, and loading failures show actionable errors rather than leaving a permanent spinner. Visible chats check for new messages approximately every 2.5 seconds and contacts/unread approximately every 10 seconds.
- When no conversation is open, the placeholder reads **No Conversation has been Made**.
- Admin account-detail emails are concealed by default and revealed only with an accessible eye toggle; hiding or closing the dialog conceals them again. Account-list rows no longer display unmasked emails. Passwords remain protected and cannot be viewed.

## SaS Messenger

The approved-member website includes a dedicated **SaS Messenger** page with the same purple glass-style UI used elsewhere:

- **Direct messages:** click an approved member in the conversation list to write privately. Each private thread can only be read by its two participants. The administrator appears as a direct-message contact for every approved member.
- **SaS - Group Chat:** a pinned, highlighted alliance chat at the top of the Group Chats section. Its unread messages appear on the chat and Messenger sidebar badge. All currently approved members and the administrator can participate.
- **Private custom groups:** click **Create Group**, enter a name, search approved players and select up to 24 participants (the creator is always included, even if no other account is approved). Only the creator and invited members can see the group in their contact list or access its messages/read receipts. A non-member, including an administrator who was not invited, cannot open a private group by guessing its URL or ID. Group membership is stored in SQLite.
- **Player directory:** a visible Players section lists all approved accounts by username and in-game name, with search. The currently signed-in player's account is also shown as **Your profile** (not a self-chat). Pending, rejected or unregistered accounts are deliberately not listed.
- **Account contacts:** usernames and in-game names of approved players appear in the searchable sidebar. Member emails, passwords and reset requests are **not** exposed.
- **Unread notifications:** server-persisted unread counts appear beside each chat and on the website's Messenger tab. Opening a conversation marks that conversation as read without affecting other conversations.
- **Live refresh:** the visible conversation refreshes approximately every 5 seconds, while the unread/contact list refreshes approximately every 15 seconds. No third-party real-time chat provider is required.
- **Message history:** stored in existing SQLite under `chat_messages`; the most recent 80 messages per thread load in chronological order.
- **Mobile UI:** conversations list and individual chat open in separate phone-sized views with a back arrow.
- **Training points target:** Troop Training now takes the number of desired **Phase 3 Officer Training event points** as its input and computes the minimum required Tier IX/X troops (IX = 1,485 points; X = 1,960 points) and estimated resources/time. The +200% capacity toggle rounds up to a whole batch, shows any extra troops/points, and still feeds the speedup and event-points calculators.
- **Safety:** requests enforce approved-member or administrator sessions and valid CSRF tokens for writes. Message text is length-limited to 2,000 characters and **30 sends per minute per account**, escaped in the browser, and never used as raw HTML. Only sender identities from the validated server session are saved. Pending/rejected accounts and guests cannot access the messenger. Messages are not sent to Discord.
- **Account deletion:** erases direct-message threads involving the deleted member; their existing alliance-group messages are anonymized so the group conversation still makes sense.

The existing account approval flow, 30-minute administrator inactivity logout, maintenance mode and event tools are unchanged. Back up SQLite before deploying; the two new messenger tables are created automatically on startup. Chat requires a single persistent database across app restarts, and concurrent application instances should share one properly managed database (SQLite is best deployed as a single writer on this hosting setup).

## New Police Chief game guides

The **Calculators → GAME GUIDES** left sidebar has four additional separate pages. All data is bundled in `reference-data.js` and rendered by `reference-ui.js`, available only after approved member/admin authentication:

- **SvS Prep Week:** Day 1–5 personal chest thresholds and scoring actions, plus a separate Day 6 Final Showdown. Based on *State Showdown*, game reference 0.1.179, **state age Day 50–110**. Select a day and chest, enter already earned points, view how many of each action are needed, and enter a combination of planned actions. Speedup quantities are measured in **minutes** (not speedup items); Diamond-completed speedups do not score.
- **Chief Almighty:** Seven daily tabs with chest milestones and scoring actions from **edition 5**, **starting PD under 19**, **state age Day 1–112**. Other server ages / PD bands / event editions can differ, so this edition is visibly labeled and must be verified in-game before use.
- **Hero Star-Up:** Six shard steps for each of five stars, star totals **10 / 40 / 115 / 300 / 600**, and cumulative totals **10 / 50 / 165 / 465 / 1,065**, excluding initial recruitment. Source: [Police Chief Wiki](https://policechief-wiki.com/en/topics/fragments/).
- **PD Office L1–30:** Full list of each level's published Ammo/Cash/Electricity/Gas and base construction time, with a current-level-to-target calculator. Some source numbers are rounded K/M values; summed costs are therefore approximate and the list does not claim exact underlying game integers. Source: [BetterPoliceChief Chief's Office](https://betterpolicechief.com/buildings/chiefs-office/).

Source events: [State Showdown](https://betterpolicechief.com/events/state-showdown/) and [Chief Almighty](https://betterpolicechief.com/events/chief-almighty/). Reference-version labels on each page are part of the UI because the guide itself supports multiple editions and different reward thresholds.

**Troops:** Royal Guard X and Royal Marksman X are selectable again using screenshot-backed estimates; **only Royal Biker X remains locked** because its costs were not provided. A lock uses an SVG, not an emoji.

**Event colours:** Existing Events and Alliance Events automatically highlight upcoming starts in yellow when starting within 4 hours (but more than 1 hour away), and red when starting within 1 hour. Both row shading and countdown emphasis update as the time progresses. Current/ended events do not receive these warnings.

## Calculators and game reference data

The **Calculators** item opens a separate tool workspace with its own **left navigation** on desktop and horizontally scrollable tabs on mobile. Existing Events, Alliance Events, Alliance RSS, Website Updates, HR Announcements and SaS – Accounts remain separate pages.

- **Event Points**: rules from the provided in-game event screenshots for Phase 1 (PD Construction), Phase 3 (Officer Training Levels 4–10), Phase 4 (Resource Confiscation), and Phase 5 (Power Sprint). Alliance Faceoff gathering uses its **separate** point table. Specify an event target and entered quantities to calculate the score. Custom point values are stored *in the current browser for the signed-in username*, not published globally. Phase 2 is not inferred.
- **Troop Training**: screenshot-backed rounded RSS costs and original training time for **722 troops**, for Honored Guard IX, Royal Guard X, Honored Biker IX, Honored Marksman IX and Royal Marksman X. Other quantities use proportional estimates, which may differ from actual in-game calculations and player-specific bonuses. The **Training Capacity UP (2h)** button follows the new in-game screenshots: **+200% capacity means 3× the base troop count, 3× RSS costs, and 3× original training time** (722 → 2,166). Other quantities use proportional estimates and rounded game screenshot references. T10 troop choices remain visibly locked with a non-emoji lock icon and dialog, pending future availability.
- **Building Costs**: verified **Chief's Office** single-upgrade costs to Levels 10, 11, 15 and 20. The table does not incorrectly treat these as a cumulative range or estimate unknown levels.
- **Speedups**: exactly the game's 1-minute, 5-minute, 1-hour, 3-hour and 8-hour items; time input produces the amount required of each individual speedup. An optional available-inventory calculation gives a **longest-first suggestion**, not a guaranteed optimal combination.
- **RSS Gathering**: node gathering rate and bonus calculator. Ammo/Cash values are recorded for Levels 1–8, Electricity/Gas for Levels 5–8. Unconfirmed levels display **not recorded** instead of invented values.
- All resource quantities use **K / M / B** abbreviations (e.g. 3.22B = 3,220,000,000). The event examples do not represent alliance treasury balances or live game synchronisation.

### Unread tabs per approved account

Each approved player's viewed-section revisions are stored in a new SQLite `member_reads` table, created automatically on application restart. `GET /api/reads` returns only the logged-in player's read state; `POST /api/reads` with their session CSRF token records a **server-derived** snapshot for the opened section. Unauthenticated, pending and revoked users cannot use either endpoint. Existing admin sessions retain browser-local read state.

Unread counts show **1**, **2**, etc. by number of changed/new posts, and relevant navigation tabs temporarily move to the front. Opening a section acknowledges its messages and restores its default navigation order. The mobile navbar has swipe guidance and horizontal scrolling so players can discover other sections.

**Data limitation:** Screenshot prices and the public game guide are references, not a universal/official formula. Different servers, buffs, updates or troop types may have different costs. Please provide screenshots to expand missing price levels rather than assuming a complete catalog.

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
    SAS_DISCORD_REGISTRATION_WEBHOOK_URL=
    SAS_DISCORD_LOGIN_WEBHOOK_URL=

The application uses SERVER_PORT provided by Bot-Hosting, then PORT, and finally 8080.

Keep SAS_COOKIE_SECURE=1 when accessing the website over HTTPS. For local HTTP development only, use SAS_COOKIE_SECURE=0.

The .env file and local SQLite databases are ignored by Git. Never commit administrator credentials or webhook tokens.

**Persistence matters:** The SQLite database path must remain on persistent storage when your service restarts or redeploys. Back up the database before changing your hosting runtime.

### In-app confirmation dialogs

All destructive administrator actions—permanent account deletion, deleting an event/announcement entry, and removing an RSS spending record—now use a consistent **SaS-styled confirmation popup** rather than a browser's built-in confirm/alert. Each popup has an explicit **Cancel** and action-specific delete button, supports keyboard Escape and focus management, and keeps text safely in `textContent`.

### Delayed admin bans and detailed event cards

**SaS – Accounts** now includes a **Ban** action next to each player plus a Moderation & Ban Queue. Admins can select **IP**, **Email**, **Name** (both account username and in-game name), or **Everything** (all of these) from an in-site popup, optionally add a reason, and submit a ban for review. Every ban has a **two-hour delay** stored on the server. Until its deadline, the queue shows it as *Pending* with an **Undo [type] Ban** button; after the deadline the restriction activates automatically and the same row offers **Unban**. No background scheduler is required; the SQLite record is evaluated against current UTC time for every affected account request. A cancelled or revoked ban stops restricting access immediately. The admin queue also includes **Cancel All Pending Bans** to reverse multiple queued restrictions during the two-hour review period; it does not revoke already-active bans.

This protection is **not a device ban**: the site cannot reliably identify a particular phone. It tracks the last actual HTTP peer IP for a registered member and checks that source on future requests. It intentionally **does not trust client-supplied X-Forwarded-For** values. Behind a reverse proxy, the peer address can represent the proxy instead of the visitor; IP bans can also affect unrelated people sharing the same network. Only use IP/Everything when the administrator sees a verified last IP, and verify hosting proxy configuration before relying on it. An approved admin session is exempt from moderation bans so admins can lift a bad ban even from a shared network. Bans on names/emails apply to those values; someone who changes both their details and their IP may evade them.

Ban queue and removal endpoints require authenticated admin sessions **and CSRF tokens**. Members, guests, pending and rejected accounts cannot view the queue or schedule/cancel bans. Existing account deletion is separate and remains immediate.

**Events and Alliance Events** show a clear *Click me · View details* hint on every row. Their detail popups include event title, UTC start/end, category/status, rewards, **Points / Milestones**, **How to Earn Points**, and optional notes. Admins can edit the two new event fields. Older events show *Not specified* until an admin fills them in; no event-point rules are invented. The **Reset Values** button in Event Points replaces the older screenshot-specific label.

### Account moderation and password recovery

In **SaS – Accounts**, administrators can **Accept**, **Reject** (with a reason), **Edit** player name/username/email, and **Delete** accounts permanently after confirmation. Approved accounts appear in green and rejected ones in red. Deleting an account revokes its sessions and removes its pending password reset requests and unread state; make a database backup before bulk moderation.

The login screen offers **Forgot your password? → Request password change**. The server always gives the same neutral confirmation for existing and unknown usernames/emails, so it cannot be used to discover accounts. Requests from registered accounts appear under **SaS – Accounts → Password change requests**. The admin navigation badge includes pending reset requests and the queue refreshes automatically every 15 seconds while an admin is active, with a manual refresh button as well.

Admins can approve a pending request to generate a one-use code and share it **privately** with the correct player; the code expires after **one hour**. Players then use **I have a reset code** to set a new password. Reviewed requests remain visible in the admin list for **48 hours** and then disappear automatically from that list (database audit history is preserved). Pending requests remain visible until reviewed. A repeat request made within 15 minutes does not create another pending entry.

### Discord notifications: setup and troubleshooting

The three different notification types have **three different environment variables**. Set each to a newly generated private Discord webhook URL in **Bot-Hosting's actual Python application's environment or its deployed `.env`**, without quotes or spaces around the value. Restart/redeploy the Python application after changing environment values:

```dotenv
SAS_DISCORD_WEBHOOK_URL=YOUR_EVENT_REMINDER_WEBHOOK
SAS_DISCORD_REGISTRATION_WEBHOOK_URL=YOUR_REGISTRATION_REVIEW_WEBHOOK
SAS_DISCORD_LOGIN_WEBHOOK_URL=YOUR_SUCCESSFUL_LOGIN_WEBHOOK
```

If using `.env`, it must be in the **same directory as `server.py`** in the running Bot-Hosting filesystem. The host's already-set environment variables take precedence over `.env` (the loader uses `os.environ.setdefault`). Setting a variable to an empty value in the hosting dashboard also overrides a non-empty `.env` value. Public GitHub does **not** contain real webhook secrets.

The admin account page **SaS – Accounts → Discord notifications** reports **Configured/Not configured**, last delivery result, and a **Send test** button for each of the three channels. Successful test sends create a simple message in Discord. Delivery failures show only HTTP status or exception category (never the secret webhook URL). Examples: `HTTP 404` can indicate a deleted/rotated URL; `HTTP 401` a rejected credential; `HTTP 429` rate limiting; `network error` an outbound hosting/network problem. Account alerts fire for *new successful registrations* and *successful logins only*; neither a page refresh nor failed sign-in sends a new login message.

Event reminders apply to **every Events and Alliance Events entry with a valid upcoming UTC start**, using dynamic PNG cards in the approved dark Discord style. The server posts a **yellow card at T−2h**, deletes it **50 minutes after the send**, posts a **red card at T−1h** (with `@everyone`, subject to Discord mention permissions), and deletes the red card **24 hours after posting**. Only the event name, remaining time and UTC start are printed in the image. The generated image is attached to an embed, and the server requests Discord's message ID with `wait=true` so it can delete the same message later.

The server checks every 25 seconds, using **10-minute send windows** to avoid posting misleading old reminders after downtime. Message IDs, timestamps and deletion state are saved in the persistent SQLite table `reminder_messages`. Cleanup resumes after restarts and also deletes an older card if the event is removed or its start time is edited. Already-posted messages from the legacy reminder system **cannot be deleted automatically**, because that earlier version never stored their message IDs. Discord may block deletion if the webhook was replaced or deleted; in that case an admin must remove any orphaned message manually.

**Setup:** `reminder_cards.py` requires `Pillow` for generating actual PNG attachments. The Dockerfile installs `requirements.txt`; when running as a standard Bot-Hosting Python app instead, install `pip install -r requirements.txt` in its deployment environment. The app must be running for scheduled sends/deletes. Webhook secrets remain in the hosting environment, not in the source.

**Do not paste active webhook URLs into GitHub, screenshots or chat.** Previously shared URLs should be revoked/regenerated in Discord. Never include webhook URLs in a bug report; share only the sanitized delivery status instead.

### Administrator inactivity timeout

All administrator sessions now expire after **30 minutes with no actual browser activity**. API polling and the live event countdown do not refresh the server-side timer. The app records active user interaction through an authenticated, CSRF-protected `POST /api/admin/activity` endpoint (sent at most once per minute). The server checks last human activity for all administrative routes including `GET /api/accounts`, and destroys expired sessions. After expiry the admin must sign in again; normal approved-member sessions are unaffected. Previously issued admin sessions must reauthenticate after the SQLite migration. Login still has an absolute session expiry as a separate safety limit.

### Discord registration and login notifications

Create two Discord webhooks in your chosen channels and store them privately in `.env` or the host's environment settings:

- `SAS_DISCORD_REGISTRATION_WEBHOOK_URL`: posts **New member registration** when registration succeeds (username, in-game name, email, role MEMBER). Useful as an admin approval reminder; no public link or account approval is included.
- `SAS_DISCORD_LOGIN_WEBHOOK_URL`: posts **Website login** when a verified approved member or administrator successfully signs in, labeled MEMBER or ADMIN. Member email is included; the administrator login has no associated email stored, so only the admin username is shown. Both MEMBER and ADMIN login notifications include the exact **UTC login timestamp**.

**Failed sign-in attempts, pending/rejected sign-ins, passwords, session tokens, and CSRF tokens are never sent to Discord.** Messages use `allowed_mentions: {parse: []}` so untrusted usernames cannot ping anyone. Webhook delivery is best-effort in a background thread; a Discord outage does not block login. Both URLs are optional; set only the notifications you want. Restart the Python service after updating `.env`.

**Security:** Treat Discord webhook URLs like passwords. If a webhook URL has been pasted into a chat, log or public channel, revoke/regenerate it through Discord's webhook settings before use. Never commit a live webhook token to GitHub.

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

## Temporary Alliance RSS page and recovery UX

The **Alliance RSS** tab currently displays a simple **UNDER CONSTRUCTION** overlay over a blurred, inert version of its former interface. In this release, the page UI is intentionally unavailable; its existing backend resource records are not deleted or migrated. This is a *UI maintenance overlay*, not a new confidentiality boundary for authenticated API data.

Admins reviewing a password change now see a SaS-styled confirmation dialog before generating a one-time code. The reset request and code completion forms accept **username, email, or in-game name**. In-game names are not required to be unique: ambiguous name-only requests are answered generically but do not select a random player's account; use a unique username/email instead. The user-facing response intentionally does not disclose whether an account exists.
