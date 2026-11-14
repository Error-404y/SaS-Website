/* SaS calculators. Reference values are sourced from user-submitted game screenshots.
   No unobserved troop or building costs are inferred as exact data. */
(function (root) {
  'use strict';
  const RESOURCES = ['ammo', 'cash', 'electricity', 'gas'];
  const SPEEDUPS = [{ minutes: 480, label: '8h' }, { minutes: 180, label: '3h' },
    { minutes: 60, label: '1h' }, { minutes: 5, label: '5m' }, { minutes: 1, label: '1m' }];
  const GATHERING = {
    ammo: [316584, 332496, 348372, 364320, 380160, 396000, 411840, 427680],
    cash: [316584, 332496, 348372, 364320, 380160, 396000, 411840, 427680],
    electricity: [null, null, null, null, 76032, 79200, 82368, 85536],
    gas: [null, null, null, null, 19008, 19800, 20592, 21384]
  };
  // Per-722 screenshot snapshots, shown as rounded game UI values. Original time BEFORE acceleration.
  // Both variants of Honored Guard/Marksman have tier IX costs; Royal Guard/Marksman tier X.
  // These prices cannot be assumed exact across all technology/discount configurations.
  const TROOPS = {
    'guard-9':     { name: 'Honored Guard', tier: 9, type: 'Guard', ammo: 1000000, cash: 755200, electricity: 176100, gas: 36800, seconds: 94582 },
    'guard-10':    { name: 'Royal Guard', tier: 10, type: 'Guard', ammo: 2000000, cash: 1500000, electricity: 352300, gas: 73600, seconds: 109744 },
    'biker-9':     { name: 'Honored Biker', tier: 9, type: 'Biker', ammo: 880800, cash: 831000, electricity: 171100, gas: 39700, seconds: 94582 },
    'marksman-9':  { name: 'Honored Marksman', tier: 9, type: 'Marksman', ammo: 629500, cash: 931300, electricity: 156600, gas: 50500, seconds: 94582 },
    'marksman-10': { name: 'Royal Marksman', tier: 10, type: 'Marksman', ammo: 1200000, cash: 1800000, electricity: 312600, gas: 101000, seconds: 109744 }
  };
  const SAMPLE_SIZE = 722;
  // Each building row is the single upgrade to the specified level, not a 1-to-level total.
  const BUILDINGS = {
    '10': { cash: 460000, ammo: 460000, electricity: 92000, gas: 23000 },
    '11': { cash: 1300000, ammo: 1300000, electricity: 260000, gas: 65000 },
    '15': { cash: 4600000, ammo: 4600000, electricity: 930000, gas: 230000 },
    '20': { cash: 21000000, ammo: 21000000, electricity: 4300000, gas: 1000000 }
  };
  const OFFICERS = { 4: 265, 5: 385, 6: 595, 7: 830, 8: 1130, 9: 1485, 10: 1960 };
  const FACE_OFF = { ammo: { amount: 2000, points: 2 }, cash: { amount: 2000, points: 2 },
    electricity: { amount: 400, points: 2 }, gas: { amount: 100, points: 2 } };
  const PHASE4 = { ammo: { amount: 200, points: 15 }, cash: { amount: 200, points: 15 },
    electricity: { amount: 40, points: 15 }, gas: { amount: 10, points: 15 } };
  const PHASE_RULES = {
    '1': { construction: 45, research: 45 },
    '3': { officers: OFFICERS },
    '4': { research: 45, confiscation: PHASE4 },
    '5': { construction: 30, research: 30, officerPower: 20, steel: 50000, exclusive: 100000 }
  };
  function numeric(value) {
    const num = Number(value);
    return Number.isFinite(num) && num > 0 ? num : 0;
  }
  function whole(value) { return Math.floor(numeric(value)); }
  function fmt(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return '—';
    const magnitude = Math.abs(num);
    const compact = (unit, suffix) => {
      const v = num / unit;
      return v.toFixed(Math.abs(v) >= 10 ? 1 : 2).replace(/\.0+$|(?<=\.[0-9]*[1-9])0+$/g, '') + suffix;
    };
    if (magnitude >= 1e9) return compact(1e9, 'B');
    if (magnitude >= 1e6) return compact(1e6, 'M');
    if (magnitude >= 1e3) return compact(1e3, 'K');
    return new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(num);
  }
  function parseAmount(value) {
    if (typeof value === 'number') return numeric(value);
    const clean = String(value || '').trim().replace(/,/g, '').replace(/\s+/g, '');
    const match = clean.match(/^(\d+(?:\.\d+)?)([KMB])?$/i);
    if (!match) return 0;
    return numeric(Number(match[1]) * ({ K: 1e3, M: 1e6, B: 1e9 }[match[2]?.toUpperCase()] || 1));
  }
  function duration(seconds) {
    const s = Math.ceil(numeric(seconds));
    const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600),
      m = Math.floor(s % 3600 / 60), sec = s % 60;
    return [d ? d + 'd' : '', h ? h + 'h' : '', m ? m + 'm' : '', sec ? sec + 's' : ''].filter(Boolean).join(' ') || '0m';
  }
  function gathering(type, level, bonus = 0) {
    if (!GATHERING[type] || !Number.isInteger(Number(level)) || level < 1 || level > 8) return null;
    const base = GATHERING[type][level - 1];
    return base === null ? null : base * (1 + numeric(bonus) / 100);
  }
  function troops(key, quantity, capacityBoost = false, timeReduction = 0) {
    const t = TROOPS[key];
    if (!t) return null;
    const qty = whole(quantity);
    const factor = qty / SAMPLE_SIZE;
    const boost = capacityBoost ? 3 : 1; // +200% capacity means 300% of base troops: screenshots 722 -> 2166
    const reduction = Math.min(99.99, numeric(timeReduction));
    const costs = Object.fromEntries(RESOURCES.map(r => [r, t[r] * factor * boost]));
    return { key, baseQuantity: qty, quantity: qty * boost, costs, seconds: t.seconds * factor * boost * (1 - reduction / 100),
      originalSeconds: t.seconds * factor * boost, capacityMultiplier: boost, snapshot: SAMPLE_SIZE };
  }
  // Game screenshot reference times are ORIGINAL times. Actual time is player-specific
  // and must only be computed from a separately recorded actual 722-troop sample.
  function parseGameDuration(value) {
    const text = String(value ?? '').trim().toLowerCase();
    if (!text) return null;
    // Common in-game display: 1d 06:29:04 or 06:29:04.
    const match = text.match(/^(?:(\d+)\s*d(?:ays?)?\s*)?(\d{1,2}):(\d{2}):(\d{2})$/);
    if (match) {
      const days = Number(match[1] || 0);
      const [hours, minutes, seconds] = match.slice(2).map(Number);
      if (hours > 23 || minutes > 59 || seconds > 59 || days > 36500) return null;
      return days * 86400 + hours * 3600 + minutes * 60 + seconds;
    }
    // Also accept the calculator's readable "1d 6h 29m 4s" format.
    const readable = text.match(/^(?:(\d+)d\s*)?(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s\s*)?$/);
    if (readable && text && /\d+[dhms]/.test(text)) {
      const [days, hours, minutes, seconds] = readable.slice(1).map(x => Number(x || 0));
      if (days > 36500 || hours > 23 || minutes > 59 || seconds > 59) return null;
      return days * 86400 + hours * 3600 + minutes * 60 + seconds;
    }
    return null;
  }
  function troopsForTargetPoints(key, targetPoints, capacityBoost = false, actualSampleSeconds = null) {
    const troop = TROOPS[key];
    if (!troop) return null;
    const rate = OFFICERS[troop.tier];
    if (!rate) return null;
    const goal = Math.max(0, Math.floor(Number(targetPoints) || 0));
    const needed = Math.ceil(goal / rate);
    const multiplier = capacityBoost ? 3 : 1;
    const baseQuantity = Math.ceil(needed / multiplier);
    // The baseline per-722 screenshot time is already Origin Time. Do not treat
    // it as the actual sped-up training time or apply a made-up reduction.
    const result = troops(key, baseQuantity, capacityBoost);
    const validSample = typeof actualSampleSeconds === 'number' &&
      Number.isFinite(actualSampleSeconds) && actualSampleSeconds > 0 &&
      actualSampleSeconds <= troop.seconds;
    const actualSeconds = validSample
      ? actualSampleSeconds * result.quantity / SAMPLE_SIZE : null;
    return {...result, rate, targetPoints:goal, requiredTroops:needed,
      actualPoints:result.quantity * rate, extraPoints:result.quantity * rate - goal,
      originSeconds: result.originalSeconds, actualSeconds};
  }
  function build(level) { return BUILDINGS[String(level)] || null; }
  function eventPoints(phase, inputs = {}, rules = PHASE_RULES) {
    const rule = rules[String(phase)] || {};
    const points = {};
    for (const key of ['construction', 'research', 'officerPower', 'steel', 'exclusive']) {
      if (Number.isFinite(rule[key])) points[key] = whole(inputs[key]) * rule[key];
    }
    if (rule.officers) {
      points.officers = Object.entries(rule.officers).reduce((sum, [level, rate]) =>
        sum + whole(inputs['officer' + level]) * rate, 0);
    }
    if (rule.confiscation) {
      points.confiscation = RESOURCES.reduce((sum, resource) => {
        const r = rule.confiscation[resource];
        return sum + Math.floor(numeric(inputs[resource]) / r.amount) * r.points;
      }, 0);
    }
    return { parts: points, total: Object.values(points).reduce((a, b) => a + b, 0) };
  }
  function faceoffPoints(inputs) {
    return RESOURCES.reduce((sum, resource) => {
      const rule = FACE_OFF[resource];
      return sum + Math.floor(numeric(inputs[resource]) / rule.amount) * rule.points;
    }, 0);
  }
  function speedupSingles(minutes) {
    const need = numeric(minutes);
    return SPEEDUPS.map(item => ({ ...item, count: Math.ceil(need / item.minutes),
      extra: Math.ceil(need / item.minutes) * item.minutes - need }));
  }
  function speedupMix(minutes, inventory = {}) {
    const target = Math.ceil(numeric(minutes));
    if (!target) return { counts: {}, used: 0, remaining: 0, waste: 0 };
    // Limited inventory, longest first; never claim this greedy combination is globally optimal.
    let remaining = target, used = 0;
    const counts = {};
    for (const item of SPEEDUPS) {
      const available = whole(inventory[item.label]);
      const count = Math.min(available, Math.floor(remaining / item.minutes));
      counts[item.label] = count;
      used += count * item.minutes;
      remaining -= count * item.minutes;
    }
    if (remaining > 0) {
      for (const item of [...SPEEDUPS].reverse()) {
        if (counts[item.label] < whole(inventory[item.label])) {
          counts[item.label]++;
          used += item.minutes;
          remaining = Math.max(0, target - used);
          break;
        }
      }
    }
    return { counts, used, remaining, waste: Math.max(0, used - target) };
  }
  const api = { RESOURCES, SPEEDUPS, GATHERING, TROOPS, SAMPLE_SIZE, BUILDINGS, OFFICERS, troopsForTargetPoints,
    FACE_OFF, PHASE4, PHASE_RULES, numeric, whole, fmt, parseAmount, duration,
    gathering, troops, parseGameDuration, build, eventPoints, faceoffPoints, speedupSingles, speedupMix };
  root.SasPlanner = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
