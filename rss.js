(function (root) {
  const resources = ['ammo', 'cash', 'electricity', 'gas'];
  const buffs = ['troop_attack', 'troop_defense', 'troop_hp', 'resource_gathering'];

  function normalize(value = {}) {
    const source = value && typeof value === 'object' ? value : {};
    const savedResources = source.resources && typeof source.resources === 'object' ? source.resources : {};
    const savedBuffs = source.buffs && typeof source.buffs === 'object' ? source.buffs : {};
    const result = {
      resources: {},
      buffs: {},
      tech_name: typeof source.tech_name === 'string' ? source.tech_name : '',
      tech_plan: typeof source.tech_plan === 'string' ? source.tech_plan : '',
      tech_progress: validNumber(source.tech_progress, 100),
      tech_stage: typeof source.tech_stage === 'string' ? source.tech_stage : '',
      tech_ends_at: typeof source.tech_ends_at === 'string' ? source.tech_ends_at : '',
      territory_plan: typeof source.territory_plan === 'string' ? source.territory_plan : '',
      updated_at: typeof source.updated_at === 'string' ? source.updated_at : '',
      legacy_hour: typeof source.legacy_hour === 'string' ? source.legacy_hour : ''
    };
    for (const key of resources) {
      const item = savedResources[key] || {};
      result.resources[key] = {
        stored: validNumber(item.stored),
        per_hour: validNumber(item.per_hour)
      };
    }
    for (const key of buffs) {
      result.buffs[key] = validNumber(savedBuffs[key], 1000);
    }
    return result;
  }

  function validNumber(value, maximum = 1000000000000000) {
    if (value === '' || value === undefined || value === null || typeof value === 'boolean') return null;
    if (typeof value !== 'number' && typeof value !== 'string') return null;
    const amount = Number(value);
    return Number.isFinite(amount) && amount >= 0 && amount <= maximum ? amount : null;
  }

  function formatAmount(value) {
    const amount = validNumber(value);
    if (amount === null) return '—';
    for (const [limit, symbol] of [[1000000000000, 'T'], [1000000000, 'B'], [1000000, 'M'], [1000, 'K']]) {
      if (amount >= limit) return (amount / limit).toFixed(1) + symbol;
    }
    return amount.toLocaleString('en-US', { maximumFractionDigits: 2 });
  }

  function formatRate(value) {
    const amount = validNumber(value);
    return amount === null ? 'Not recorded' : '+' + formatAmount(amount) + '/h';
  }

  function formatBuff(value) {
    const amount = validNumber(value, 1000);
    return amount === null ? 'Not set' : '+' + amount.toFixed(1) + '%';
  }

  function formatProgress(value) {
    const amount = validNumber(value, 100);
    return amount === null ? null : amount.toLocaleString('en-US', { maximumFractionDigits: 2 }) + '%';
  }

  function parseDuration(value) {
    if (value === '') return null;
    if (typeof value !== 'string' || !/^\d{1,3}:[0-5]\d:[0-5]\d$/.test(value)) {
      throw new Error('Use HH:MM:SS for time remaining, for example 01:45:00.');
    }
    const [hours, minutes, seconds] = value.split(':').map(Number);
    return hours * 3600 + minutes * 60 + seconds;
  }

  function remainingSeconds(deadline, now = Date.now()) {
    if (!deadline) return null;
    const timestamp = Date.parse(deadline);
    if (!Number.isFinite(timestamp)) return null;
    return Math.max(0, Math.ceil((timestamp - now) / 1000));
  }

  function formatDuration(seconds) {
    if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return '';
    const total = Math.ceil(seconds);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const remainder = total % 60;
    return [hours, minutes, remainder].map(value => String(value).padStart(2, '0')).join(':');
  }

  function formatUpdated(value) {
    if (!value) return 'No alliance RSS data posted yet.';
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return 'No alliance RSS data posted yet.';
    return 'Last updated: ' + date.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
  }

  function readNumber(input, name, maximum = 1000000000000000) {
    const text = input.trim();
    if (text === '') return null;
    if (!/^\d+(?:\.\d{1,2})?$/.test(text)) {
      throw new Error(name + ' must be a non-negative number with up to two decimals.');
    }
    const number = Number(text);
    if (!Number.isFinite(number) || number > maximum) {
      throw new Error(name + ' is outside the allowed range.');
    }
    return number;
  }

  const api = { resources, buffs, normalize, formatAmount, formatRate, formatBuff,
    formatProgress, formatUpdated, readNumber, parseDuration, remainingSeconds, formatDuration };
  root.SasRss = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
