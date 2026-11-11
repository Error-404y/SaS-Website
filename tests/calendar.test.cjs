const test = require('node:test');
const assert = require('node:assert/strict');
const calendar = require('../calendar.js');

const event = {
  id: 12,
  kind: 'alliance',
  title: 'Alliance, Council; Session',
  category: 'Alliance',
  start_utc: '2026-11-11 12:00:00',
  end_utc: '2026-11-11 14:30:00',
  rewards: 'Gold, tokens',
  details: 'Meet at the hall;\nbring supplies.'
};

function time(value) {
  return Date.parse(value);
}

test('UTC timestamps remain exact and invalid dates are rejected', () => {
  assert.equal(calendar.utcTime(event.start_utc), time('2026-11-11T12:00:00Z'));
  assert.throws(() => calendar.utcTime('2026-11-31 12:00:00'));
  assert.throws(() => calendar.utcTime('2026-11-11T12:00:00+02:00'));
});

test('countdown changes from upcoming to active to ended at the exact boundaries', () => {
  const before = time('2026-11-11T11:59:00Z');
  const during = time('2026-11-11T12:30:00Z');
  const after = time('2026-11-11T14:30:00Z');
  assert.equal(calendar.eventStatus(event, before), 'upcoming');
  assert.equal(calendar.countdown(event, before), 'Starts in 00h 01m 00s');
  assert.equal(calendar.eventStatus(event, during), 'active');
  assert.equal(calendar.countdown(event, during), 'Ends in 02h 00m 00s');
  assert.equal(calendar.eventStatus(event, after), 'ended');
  assert.equal(calendar.countdown(event, after), 'Ended');
});

test('countdowns show days for events further away', () => {
  const before = time('2026-11-09T11:30:00Z');
  assert.equal(calendar.countdown(event, before), 'Starts in 2d 00h 30m');
});

test('Google Calendar link contains event title, description and exact UTC times', () => {
  const link = new URL(calendar.googleCalendarUrl(event));
  assert.equal(link.origin, 'https://calendar.google.com');
  assert.equal(link.searchParams.get('action'), 'TEMPLATE');
  assert.equal(link.searchParams.get('text'), event.title);
  assert.equal(link.searchParams.get('dates'), '20261111T120000Z/20261111T143000Z');
  assert.equal(link.searchParams.get('ctz'), 'UTC');
  assert.ok(link.searchParams.get('details').includes('Gold, tokens'));
});

test('downloadable calendar file contains valid UTC fields and escaped event content', () => {
  const file = calendar.calendarFile(event, new Date('2026-11-10T10:00:00Z'));
  assert.ok(file.startsWith('BEGIN:VCALENDAR\r\n'));
  assert.ok(file.endsWith('END:VCALENDAR\r\n'));
  assert.ok(file.includes('DTSTART:20261111T120000Z\r\n'));
  assert.ok(file.includes('DTEND:20261111T143000Z\r\n'));
  assert.ok(file.includes('DTSTAMP:20261110T100000Z\r\n'));
  assert.ok(file.includes('SUMMARY:Alliance\\, Council\\; Session\r\n'));
  assert.ok(file.includes('Meet at the hall\\;\\nbring supplies.'));
  assert.ok(file.includes('UID:sas-12@sas-website.invalid\r\n'));
  for (const line of file.split('\r\n')) {
    assert.ok(Buffer.byteLength(line, 'utf8') <= 75);
  }
});

test('downloadable calendar file rejects inverted dates', () => {
  assert.throws(() => calendar.calendarFile({
    ...event,
    end_utc: '2026-11-11 11:00:00'
  }));
});
