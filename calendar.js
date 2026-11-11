(function (root) {
  function utcTime(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value)) {
      throw new Error('Invalid UTC date.');
    }
    const date = new Date(value.replace(' ', 'T') + 'Z');
    if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 19).replace('T', ' ') !== value) {
      throw new Error('Invalid UTC date.');
    }
    return date.getTime();
  }

  function eventStatus(event, now = Date.now()) {
    if (utcTime(event.end_utc) <= now) return 'ended';
    return utcTime(event.start_utc) <= now ? 'active' : 'upcoming';
  }

  function countdown(event, now = Date.now()) {
    const state = eventStatus(event, now);
    if (state === 'ended') return 'Ended';
    const seconds = Math.max(0, Math.ceil((utcTime(state === 'active' ? event.end_utc : event.start_utc) - now) / 1000));
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor(seconds % 86400 / 3600);
    const minutes = Math.floor(seconds % 3600 / 60);
    const remainder = seconds % 60;
    const pad = value => String(value).padStart(2, '0');
    const time = days > 0
      ? days + 'd ' + pad(hours) + 'h ' + pad(minutes) + 'm'
      : pad(hours) + 'h ' + pad(minutes) + 'm ' + pad(remainder) + 's';
    return (state === 'active' ? 'Ends in ' : 'Starts in ') + time;
  }

  function calendarTimestamp(value) {
    return new Date(utcTime(value)).toISOString().slice(0, 19).replace(/[-:]/g, '') + 'Z';
  }

  function description(event) {
    const parts = [];
    if (event.category) parts.push('Category: ' + event.category);
    if (event.rewards) parts.push('Rewards: ' + event.rewards);
    if (event.details) parts.push(event.details);
    return parts.join('\n\n');
  }

  function googleCalendarUrl(event) {
    const url = new URL('https://calendar.google.com/calendar/render');
    url.searchParams.set('action', 'TEMPLATE');
    url.searchParams.set('text', event.title);
    url.searchParams.set('dates', calendarTimestamp(event.start_utc) + '/' + calendarTimestamp(event.end_utc));
    url.searchParams.set('details', description(event));
    url.searchParams.set('ctz', 'UTC');
    return url.toString();
  }

  function escapeCalendarText(value) {
    return String(value ?? '').replace(/\\/g, '\\\\')
      .replace(/\r\n|\r|\n/g, '\\n')
      .replace(/;/g, '\\;')
      .replace(/,/g, '\\,');
  }

  function foldLine(line) {
    const encoder = new TextEncoder();
    const lines = [];
    let current = '';
    let length = 0;
    for (const character of line) {
      const size = encoder.encode(character).length;
      if (length + size > 75 && current) {
        lines.push(current);
        current = ' ' + character;
        length = 1 + size;
      } else {
        current += character;
        length += size;
      }
    }
    lines.push(current);
    return lines.join('\r\n');
  }

  function calendarFile(event, now = new Date()) {
    if (utcTime(event.end_utc) <= utcTime(event.start_utc)) throw new Error('End must be after start.');
    const stamp = now.toISOString().slice(0, 19).replace(/[-:]/g, '') + 'Z';
    const lines = [
      'BEGIN:VCALENDAR',
      'VERSION:2.0',
      'PRODID:-//Saints and Sinners//SaS Website//EN',
      'CALSCALE:GREGORIAN',
      'METHOD:PUBLISH',
      'BEGIN:VEVENT',
      'UID:sas-' + String(event.id) + '@sas-website.invalid',
      'DTSTAMP:' + stamp,
      'DTSTART:' + calendarTimestamp(event.start_utc),
      'DTEND:' + calendarTimestamp(event.end_utc),
      'SUMMARY:' + escapeCalendarText(event.title),
      'DESCRIPTION:' + escapeCalendarText(description(event)),
      'END:VEVENT',
      'END:VCALENDAR'
    ];
    return lines.map(foldLine).join('\r\n') + '\r\n';
  }

  const api = { utcTime, eventStatus, countdown, googleCalendarUrl, calendarFile };
  root.SasCalendar = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
