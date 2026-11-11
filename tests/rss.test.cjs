const test = require('node:test');
const assert = require('node:assert/strict');
const rss = require('../rss.js');

test('four resource types use the correct game names', () => {
  assert.deepEqual(rss.resources, ['ammo', 'cash', 'electricity', 'gas']);
});

test('resource values use compact numbers without losing zero', () => {
  assert.equal(rss.formatAmount(21200), '21.2K');
  assert.equal(rss.formatAmount(374000), '374.0K');
  assert.equal(rss.formatAmount(840400), '840.4K');
  assert.equal(rss.formatAmount(1000000), '1.0M');
  assert.equal(rss.formatAmount(0), '0');
  assert.equal(rss.formatAmount(null), '—');
});

test('production rates and buffs distinguish unset from zero', () => {
  assert.equal(rss.formatRate(122400), '+122.4K/h');
  assert.equal(rss.formatRate(0), '+0/h');
  assert.equal(rss.formatRate(null), 'Not recorded');
  assert.equal(rss.formatBuff(8), '+8.0%');
  assert.equal(rss.formatBuff(0), '+0.0%');
  assert.equal(rss.formatBuff(null), 'Not set');
});

test('technology progress displays only submitted values', () => {
  assert.equal(rss.formatProgress(null), null);
  assert.equal(rss.formatProgress(0), '0%');
  assert.equal(rss.formatProgress(72), '72%');
  assert.equal(rss.formatProgress(72.5), '72.5%');
  assert.equal(rss.formatProgress(120), null);
});

test('empty server state never invents resource metrics or buffs', () => {
  const data = rss.normalize();
  assert.equal(Object.keys(data.resources).length, 4);
  assert.ok(rss.resources.every(key => data.resources[key].stored === null));
  assert.ok(rss.buffs.every(key => data.buffs[key] === null));
  assert.equal(data.tech_progress, null);
  assert.equal(data.updated_at, '');
});

test('number input only accepts finite non-negative values within bounds', () => {
  assert.equal(rss.readNumber('', 'Ammo'), null);
  assert.equal(rss.readNumber('0', 'Ammo'), 0);
  assert.equal(rss.readNumber('12.50', 'Ammo'), 12.5);
  assert.equal(rss.readNumber('100', 'Progress', 100), 100);
  assert.throws(() => rss.readNumber('-4', 'Ammo'));
  assert.throws(() => rss.readNumber('12K', 'Ammo'));
  assert.throws(() => rss.readNumber('101', 'Progress', 100));
  assert.throws(() => rss.readNumber('1.999', 'Ammo'));
  assert.throws(() => rss.readNumber('1e309', 'Ammo'));
});

test('last update uses UTC and never claims a timestamp without one', () => {
  assert.equal(rss.formatUpdated(''), 'No alliance RSS data posted yet.');
  assert.equal(rss.formatUpdated('2026-11-11T02:45:09+00:00'),
    'Last updated: 2026-11-11 02:45 UTC');
});
