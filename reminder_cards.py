"""Render game-event reminder cards and send/delete Discord webhook messages.

The actual Discord screenshot includes Discord-owned author/time chrome. This module
renders only the content card, matching the preview's dark theme and amber/red accent.
"""
import io
import json
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

YELLOW = (245, 186, 46)
RED = (241, 65, 81)

def _font(size, bold=False):
    from PIL import ImageFont
    choices = ([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ] if bold else [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ])
    for filename in choices:
        try:
            return ImageFont.truetype(filename, size)
        except OSError:
            continue
    return ImageFont.load_default()

def make_card(event_title, start_utc, stage, remaining_seconds=None):
    """Generate a fresh PNG with a legible dynamic title and UTC event start."""
    from PIL import Image, ImageDraw
    if stage not in ("yellow", "red"):
        raise ValueError("Invalid reminder stage")
    color = YELLOW if stage == "yellow" else RED
    image = Image.new("RGB", (1080, 360), (24, 25, 32))
    draw = ImageDraw.Draw(image)
    # Subtle dark vignette and slim left accent, like the approved reference.
    for y in range(360):
        val = int(24 + 9 * (1 - y / 360))
        draw.line((0, y, 1079, y), fill=(val, val, val + 6))
    draw.rounded_rectangle((6, 6, 1074, 353), 16, outline=color, width=2)
    draw.rounded_rectangle((7, 7, 21, 351), 6, fill=color)
    white, muted = (246, 245, 251), (175, 180, 195)
    draw.text((48, 31), "Event Reminder", font=_font(25), fill=muted)
    title = re.sub(r"[\r\n\t]+", " ", str(event_title)).strip() or "Event"
    # Width-based truncation avoids overpainting the right side.
    headline = _font(43, bold=True)
    while len(title) > 1 and draw.textbbox((0, 0), title, font=headline)[2] > 980:
        title = title[:-2].rstrip() + "…"
    draw.text((48, 76), title, font=headline, fill=white)
    draw.line((48, 155, 1032, 155), fill=(100, 101, 112), width=2)
    draw.text((48, 183), "Starts in", font=_font(24), fill=muted)
    draw.text((548, 183), "Start (UTC)", font=_font(24), fill=muted)
    if remaining_seconds is None:
        remaining_seconds = 7200 if stage == "yellow" else 3600
    total_minutes = max(0, int((remaining_seconds + 59) // 60))
    hours, minutes = divmod(total_minutes, 60)
    draw.text((48, 232), f"{hours}h {minutes:02d}m",
              font=_font(49, bold=True), fill=color)
    draw.text((548, 239), start_utc[:16], font=_font(31, bold=True), fill=white)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()

def message_url(webhook, message_id):
    if not re.fullmatch(r"\d{1,30}", str(message_id)):
        raise ValueError("Invalid Discord message ID")
    parts = urlsplit(webhook)
    return urlunsplit((parts.scheme, parts.netloc,
                       parts.path.rstrip("/") + "/messages/" + str(message_id), "", ""))

def send_card(webhook, title, start_utc, stage):
    """Send a fresh PNG as an attachment; return Discord message ID or raise."""
    start = datetime.strptime(start_utc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    remaining = max(0, int((start - datetime.now(timezone.utc)).total_seconds()))
    png = make_card(title, start_utc, stage, remaining_seconds=remaining)
    # wait=true is essential: Discord otherwise responds 204 without the message ID.
    boundary = "sas-" + __import__("secrets").token_hex(12)
    payload = {
        "username": "SaS Website",
        "content": "@everyone" if stage == "red" else "",
        "allowed_mentions": {"parse": ["everyone"] if stage == "red" else []},
        "embeds": [{"color": 15810350 if stage == "yellow" else 15810897,
                    "image": {"url": "attachment://reminder.png"}}],
        "attachments": [{"id": 0, "filename": "reminder.png",
                         "description": "Event reminder showing name, time remaining and UTC start"}]
    }
    prefix = ("--" + boundary + "\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
              "Content-Type: application/json\r\n\r\n").encode() + json.dumps(payload).encode() + b"\r\n"
    filehead = ("--" + boundary + "\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"reminder.png\"\r\n"
                "Content-Type: image/png\r\n\r\n").encode()
    data = prefix + filehead + png + b"\r\n--" + boundary.encode() + b"--\r\n"
    request = urllib.request.Request(
        webhook + "?wait=true", data=data, method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                 "User-Agent": "SaS-Website/1.0"})
    with urllib.request.urlopen(request, timeout=18) as response:
        result = json.load(response)
    message_id = str(result.get("id", ""))
    if not re.fullmatch(r"\d{1,30}", message_id):
        raise ValueError("Discord did not return a message ID")
    return message_id

def delete_card(webhook, message_id):
    """Delete previously sent webhook message. A prior 404 counts as removed."""
    request = urllib.request.Request(message_url(webhook, message_id), method="DELETE",
                                     headers={"User-Agent": "SaS-Website/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return True
        raise
