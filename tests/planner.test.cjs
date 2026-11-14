const test = require('node:test');
const assert = require('node:assert/strict');
const p = require('../planner.js');

test('compact K M B resource formatting and input parsing', () => {
  assert.equal(p.fmt(3220000000), '3.22B');
  assert.equal(p.fmt(3210000000), '3.21B');
  assert.equal(p.fmt(633100000), '633.1M');
  assert.equal(p.fmt(460000), '460K');
  assert.equal(p.parseAmount('3.22 B'), 3220000000);
  assert.equal(p.parseAmount('633.1M'), 633100000);
  assert.equal(p.parseAmount('1,200'), 1200);
  assert.equal(p.parseAmount('garbage'), 0);
});

test('five screenshot-backed troop snapshots for 722 troops', () => {
  const expected = {
    'guard-9': [1000000, 755200, 176100, 36800, 94582],
    'guard-10': [2000000, 1500000, 352300, 73600, 109744],
    'biker-9': [880800, 831000, 171100, 39700, 94582],
    'marksman-9': [629500, 931300, 156600, 50500, 94582],
    'marksman-10': [1200000, 1800000, 312600, 101000, 109744]
  };
  for (const [key, [ammo,cash,electricity,gas,seconds]] of Object.entries(expected)) {
    const calc = p.troops(key, 722);
    assert.equal(calc.costs.ammo, ammo);
    assert.equal(calc.costs.cash, cash);
    assert.equal(calc.costs.electricity, electricity);
    assert.equal(calc.costs.gas, gas);
    assert.equal(calc.seconds, seconds);
  }
  assert.equal(p.troops('marksman-9', 1444).costs.ammo, 1259000);
  assert.equal(p.troops('not-observed', 722), null);
});

test('new game screenshots: +200% capacity is 3x troops, resources and time', () => {
  const base = p.troops('marksman-10', 722);
  const boosted = p.troops('marksman-10', 722, true);
  assert.equal(base.quantity, 722);
  assert.equal(boosted.baseQuantity, 722);
  assert.equal(boosted.quantity, 2166);
  assert.equal(boosted.capacityMultiplier, 3);
  assert.equal(boosted.originalSeconds, 3 * 109744); // 3d 19h 27m 12s
  assert.equal(p.duration(boosted.originalSeconds), '3d 19h 27m 12s');
  for (const resource of p.RESOURCES) {
    assert.equal(boosted.costs[resource], base.costs[resource] * 3);
  }
  assert.equal(boosted.costs.electricity, 937800);
  const guard = p.troops('guard-10', 722, true);
  assert.equal(guard.quantity, 2166);
  assert.equal(guard.costs.ammo, 6000000);
  assert.equal(guard.costs.cash, 4500000);
  assert.equal(p.troops('biker-9', 722, false, 50).seconds, p.troops('biker-9', 722).seconds / 2);
  assert.equal(p.troops('biker-9', 722, true, 50).seconds, p.troops('biker-9', 722).seconds * 1.5);
});

test('recorded building upgrade costs are not falsely extrapolated', () => {
  assert.deepEqual(p.build(10), { cash: 460000, ammo: 460000, electricity: 92000, gas: 23000 });
  assert.equal(p.build(12), null);
});

test('screenshots: phase 1, 3, 4, 5 give distinct rates', () => {
  assert.equal(p.eventPoints(1, { construction: 10000, research: 10000 }).total, 900000);
  assert.equal(p.eventPoints(3, { officer4: 2, officer10: 100 }).total, 196530);
  assert.equal(p.eventPoints(4, { ammo: 200, cash: 200, electricity: 40, gas: 10, research: 1 }).total, 105);
  assert.equal(p.eventPoints(5, { steel: 2, exclusive: 1, construction: 10, research: 10, officerPower: 10 }).total, 200800);
  assert.equal(p.eventPoints(2, {}).total, 0);
  assert.equal(p.faceoffPoints({ ammo: 2000, cash: 2000, electricity: 400, gas: 100 }), 8);
  assert.equal(p.eventPoints(4, { ammo: 199 }).total, 0);
});

test('speedups: 24 hours is exactly 3x8h, 8x3h, 24x1h, 288x5m or 1440x1m', () => {
  assert.deepEqual(p.speedupSingles(1440).map(row => row.count), [3,8,24,288,1440]);
  const mix = p.speedupMix(1440, { '8h': 3 });
  assert.equal(mix.used, 1440);
  assert.equal(mix.remaining, 0);
  assert.equal(mix.counts['8h'], 3);
});

test('gathering rates include only sourced values for low-tier nodes', () => {
  assert.equal(p.gathering('ammo', 8), 427680);
  assert.equal(p.gathering('electricity', 8, 125), 85536 * 2.25);
  assert.equal(p.gathering('gas', 5), 19008);
  assert.equal(p.gathering('electricity', 2), null);
});

test('Phase 3 training calculates required troops from points instead of input troop count', () => {
  const ix = p.troopsForTargetPoints('guard-9', 1072170);
  assert.equal(ix.rate, 1485);
  assert.equal(ix.requiredTroops, 722);
  assert.equal(ix.baseQuantity, 722);
  assert.equal(ix.quantity, 722);
  assert.equal(ix.actualPoints, 1072170);
  const x = p.troopsForTargetPoints('guard-10', 196001);
  assert.equal(x.rate, 1960);
  assert.equal(x.requiredTroops, 101);
  const boost = p.troopsForTargetPoints('marksman-10', 196001, true);
  assert.equal(boost.requiredTroops, 101);
  assert.equal(boost.baseQuantity, 101);
  assert.equal(boost.quantity, 303);
  assert.equal(boost.actualPoints, 303 * 1960);
  assert.equal(boost.capacityMultiplier, 3);
  assert.equal(boost.originSeconds, p.troopsForTargetPoints('marksman-10',196001).originSeconds * 3);
  assert.equal(boost.costs.ammo, p.troopsForTargetPoints('marksman-10',196001).costs.ammo * 3);
  assert.equal(p.troopsForTargetPoints('guard-9', 0).quantity, 0);
  assert.equal(p.troopsForTargetPoints('biker-10', 1000), null);
});

test('Origin Time is never mistaken for reduced actual training time', () => {
  const origin = 109744; // Royal Marksman X, 722 troops: 1d 06:29:04
  const unknown = p.troopsForTargetPoints('marksman-10', 722 * 1960);
  assert.equal(unknown.requiredTroops, 722);
  assert.equal(unknown.originSeconds, origin);
  assert.equal(unknown.actualSeconds, null); // No invented research/speed time

  const observed722 = 40000; // Example actual time supplied by a player, not screenshot data
  const known = p.troopsForTargetPoints('marksman-10', 722 * 1960, false, observed722);
  assert.equal(known.originSeconds, origin);
  assert.equal(known.actualSeconds, observed722);
  assert.equal(known.seconds, origin); // legacy origin record remains unchanged

  const boosted = p.troopsForTargetPoints('marksman-10', 722 * 1960, true, observed722);
  assert.equal(boosted.quantity, 2166);
  assert.equal(boosted.originSeconds, 3 * origin);
  assert.equal(boosted.actualSeconds, 3 * observed722);
  assert.equal(boosted.extraPoints, 2 * 722 * 1960);
  assert.equal(p.troopsForTargetPoints('guard-9', 1000, false, 0).actualSeconds, null);
  assert.equal(p.troopsForTargetPoints('guard-9', 1000, false, 999999).actualSeconds, null);
  assert.equal(p.troopsForTargetPoints('guard-9', 0, false, 40000).actualSeconds, 0);
});

test('Actual time input accepts the game duration notation and rejects invalid values', () => {
  assert.equal(p.parseGameDuration('1d 06:29:04'), 109744);
  assert.equal(p.parseGameDuration('06:29:04'), 23344);
  assert.equal(p.parseGameDuration('1d 6h 29m 4s'), 109744);
  assert.equal(p.parseGameDuration('30m'), 1800);
  assert.equal(p.parseGameDuration('00:00:00'), 0);
  for (const entry of ['', 'not available', '24:00:00', '1d 19:60:00', '2d -1:00:00']) {
    assert.equal(p.parseGameDuration(entry), null, entry);
  }
});

test('capacity triples the entire goal-based training batch, points, cost, origin and actual time', () => {
  const target = 722 * 1960;
  const base = p.troopsForTargetPoints('marksman-10', target, false, 40000);
  const boosted = p.troopsForTargetPoints('marksman-10', target, true, 40000);
  assert.equal(base.requiredTroops, 722);
  assert.equal(base.quantity, 722);
  assert.equal(boosted.requiredTroops, 722);
  assert.equal(boosted.baseQuantity, 722);
  assert.equal(boosted.quantity, 2166);
  assert.equal(boosted.actualPoints, base.actualPoints * 3);
  assert.equal(boosted.originSeconds, base.originSeconds * 3);
  assert.equal(boosted.actualSeconds, base.actualSeconds * 3);
  for (const key of p.RESOURCES) assert.equal(boosted.costs[key], base.costs[key] * 3);
});
