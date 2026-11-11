# Saints and Sinners Website

The alliance website has five separate sections: Events, Alliance Events, Alliance RSS, Website Updates and HR Announcements.

The public website opens with an animated welcome screen. Anyone can use **Bring me in!** to view the site without an account.

The original Saints and Sinners crest appears on the welcome screen, in the header and in the navigation. The website is responsive and works on desktop, tablet and mobile.

## Sections

**Events** lists current and upcoming game events, their categories, exact UTC start/end times and statuses. Click an event to see its rewards and notes.

**Alliance Events** uses a completely separate event list with the same detail view.

**Alliance RSS** displays the resource income per hour and the next alliance technology plan. Until an editor supplies a value, the site states that the information has not been added.

**Website Updates** holds website news.

**HR Announcements** holds leadership announcements attributed to R4 or R5.

The Events page initially contains the eight names and dates from the supplied Event Center screenshot. Those are starting records, not a live sync with the Discord bot or the game. Ended events remain in the database and are available through the **Ended** filter.

## Public and editor access

Public visitors can read all five sections without signing in. The welcome button is not a password check.

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

The code uses plain HTML, CSS, browser JavaScript, Python's built-in HTTP server and SQLite.
