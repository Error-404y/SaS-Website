const test = require('node:test');
const assert = require('node:assert/strict');
const unread = require('../unread.js');

test('new content and edits produce badges in the correct section', () => {
  const original = unread.snapshot([
    { id: 1, kind: 'events', created_at: '2026-11-11T01:00:00Z' },
    { id: 2, kind: 'updates', created_at: '2026-11-11T01:00:00Z' }
  ], { updated_at: '2026-11-11T01:00:00Z' });
  const current = unread.snapshot([
    { id: 1, kind: 'events', created_at: '2026-11-11T01:00:00Z', modified_at: '2026-11-11T01:30:00Z' },
    { id: 2, kind: 'updates', created_at: '2026-11-11T01:00:00Z' },
    { id: 3, kind: 'announcements', created_at: '2026-11-11T01:32:00Z' },
    { id: 4, kind: 'alliance', created_at: '2026-11-11T01:33:00Z' }
  ], { updated_at: '2026-11-11T01:40:00Z' });
  assert.deepEqual(unread.count(current, original), {
    events: 1, alliance: 1, rss: 1, updates: 0, announcements: 1
  });
});

test('opening a section clears its badge without clearing the others', () => {
  const current = unread.snapshot([
    { id: 1, kind: 'events', created_at: '2026-11-11T01:00:00Z' },
    { id: 2, kind: 'announcements', created_at: '2026-11-11T01:01:00Z' }
  ], { updated_at: '2026-11-11T01:02:00Z' });
  const blank = unread.snapshot();
  const seen = unread.acknowledge(blank, current, 'events');
  assert.equal(unread.count(current, seen).events, 0);
  assert.equal(unread.count(current, seen).announcements, 1);
  assert.equal(unread.count(current, seen).rss, 1);
  const afterRss = unread.acknowledge(seen, current, 'rss');
  assert.equal(unread.count(current, afterRss).rss, 0);
  assert.equal(unread.count(current, afterRss).announcements, 1);
});

test('resource accrual does not create unread badges without a saved change', () => {
  const reference = unread.snapshot([], { updated_at: '2026-11-11T01:00:00Z' });
  const later = unread.snapshot([], { updated_at: '2026-11-11T01:00:00Z' });
  assert.equal(unread.count(later, reference).rss, 0);
});
