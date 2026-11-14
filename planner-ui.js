/* Presentation layer for SaS calculators. Inputs are local to the signed-in user. */
(function (root) {
  'use strict';
  const P = root.SasPlanner;
  if (!P) return;
  const el = id => document.getElementById(id);
  const all = sel => [...document.querySelectorAll(sel)];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, s => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[s]);
  const int = value => P.whole(value);
  const readable = n => Number(n).toLocaleString('en-US', { maximumFractionDigits: 1 });
  const field = (label, key, value = 0, note = '') =>
    '<label>' + esc(label) + '<input type="number" min="0" step="1" data-event-input="' +
    esc(key) + '" value="' + esc(value) + '"></label>' + (note ? '<small>' + esc(note) + '</small>' : '');
  const baseLabels = { construction: 'Construction power gained', research: 'Research power gained',
    officerPower: 'Officer training / promotion power gained', steel: 'Hardened Steel used',
    exclusive: "Hero's Exclusive Equipment materials used", ammo: 'Ammo confiscated / gathered',
    cash: 'Cash confiscated / gathered', electricity: 'Electricity confiscated / gathered',
    gas: 'Gas confiscated / gathered' };
  let identity = 'anonymous', overrides = {}, phaseInputs = {}, trainingTimes = {};

  function dataKey() { return 'sas-planner-v1:' + identity; }
  function loadCustom() {
    try { overrides = JSON.parse(localStorage.getItem(dataKey()) || '{}') || {}; }
    catch (_) { overrides = {}; }
    if (typeof overrides !== 'object' || Array.isArray(overrides)) overrides = {};
  }
  function saveCustom() {
    try { localStorage.setItem(dataKey(), JSON.stringify(overrides)); } catch (_) {}
  }
  function trainingStorageKey() { return 'sas-training-times-v1:' + identity; }
  function loadTrainingTimes() {
    try {
      const stored = JSON.parse(localStorage.getItem(trainingStorageKey()) || '{}');
      trainingTimes = stored && typeof stored === 'object' && !Array.isArray(stored) ? stored : {};
    } catch (_) { trainingTimes = {}; }
  }
  function saveTrainingTimes() {
    try { localStorage.setItem(trainingStorageKey(), JSON.stringify(trainingTimes)); } catch (_) {}
  }
  function syncTrainingSample() {
    const key = el('planner-troop').value;
    el('planner-actual-sample').value = trainingTimes[key] || '';
  }
  function readActualTrainingSample() {
    const text = el('planner-actual-sample').value.trim();
    const hint = el('planner-actual-help');
    if (!text) {
      hint.textContent = 'Enter the actual time displayed by your game for 722 of these troops to calculate Actual Time.';
      return null;
    }
    const seconds = P.parseGameDuration(text);
    const origin = P.TROOPS[el('planner-troop').value]?.seconds;
    if (seconds === null || seconds <= 0 || seconds > origin) {
      hint.textContent = 'Use HH:MM:SS or 1d HH:MM:SS. Actual Time must be shorter than or equal to Origin Time.';
      return null;
    }
    hint.textContent = 'Actual Time is based on your recorded 722-troop training time.';
    return seconds;
  }
  function setIdentity(username) {
    identity = String(username || 'admin');
    loadCustom();
    loadTrainingTimes();
    if (el('planner-actual-sample')) {
      syncTrainingSample();
      renderTraining();
    }
    renderEvents(true);
  }
  function stat(title, value) {
    return '<div class="tool-stat"><span>' + esc(title) + '</span><strong>' + esc(value) + '</strong></div>';
  }

  function targetTraining() {
    return P.troopsForTargetPoints(el('planner-troop').value,
      el('planner-target-points').value,
      el('planner-capacity').getAttribute('aria-pressed') === 'true',
      readActualTrainingSample());
  }
  function renderTraining() {
    const data = targetTraining();
    if (!data) return;
    el('planner-count').value = String(data.baseQuantity);
    const html = stat('Target points', readable(data.targetPoints)) +
      stat('Points per troop', readable(data.rate)) +
      stat('Minimum troops needed', readable(data.requiredTroops)) +
      stat('Troops in selected batch', readable(data.quantity)) +
      stat('Event points earned', readable(data.actualPoints)) +
      stat('Origin Time', P.duration(data.originSeconds)) +
      stat('Actual Time', data.actualSeconds === null ? 'Enter actual time above' : P.duration(data.actualSeconds)) +
      P.RESOURCES.map(r => stat(r[0].toUpperCase() + r.slice(1) + ' needed', P.fmt(data.costs[r]))).join('');
    el('planner-training-results').innerHTML = html;
    el('planner-send-speedups').disabled = data.actualSeconds === null;
    el('planner-send-speedups').title = data.actualSeconds === null
      ? 'Enter the actual training time first.' : 'Calculate speedups for Actual Time.';
    el('planner-training-notes').textContent = P.TROOPS[data.key].name + ' · ' +
      readable(data.requiredTroops) + ' troops required for ' + readable(data.targetPoints) +
      ' points' + (data.extraPoints ? ' · ' + readable(data.extraPoints) +
      ' extra points from full batch' : '');
  }
  function renderBuildings() {
    const level = el('planner-building-level').value;
    const costs = P.build(level);
    el('planner-building-results').innerHTML = P.RESOURCES.map(r => stat(r[0].toUpperCase() +
      r.slice(1), P.fmt(costs[r]))).join('');
    el('planner-building-table').innerHTML = Object.entries(P.BUILDINGS).map(([lvl, c]) =>
      '<tr><td>L' + esc(lvl) + '</td>' + P.RESOURCES.map(r =>
        '<td>' + esc(P.fmt(c[r])) + '</td>').join('') + '</tr>').join('');
  }
  function renderGathering() {
    const resource = el('planner-gather-type').value;
    const level = Number(el('planner-gather-level').value);
    const bonus = el('planner-gather-bonus').value;
    const amount = P.gathering(resource, level, bonus);
    el('planner-gather-results').innerHTML = '<span>' + esc(resource) + ' / hour</span><strong>' +
      (amount === null ? 'Not recorded' : esc(readable(amount))) + '</strong>';
    el('planner-gather-table').innerHTML = Array.from({ length: 8 }, (_, idx) => {
      const lvl = idx + 1;
      return '<tr><td>L' + lvl + '</td>' + P.RESOURCES.map(key =>
        '<td>' + (P.GATHERING[key][idx] == null ? '—' :
          esc(readable(P.GATHERING[key][idx]))) + '</td>').join('') + '</tr>';
    }).join('');
  }
  function eventRates(phase) {
    if (phase === 'faceoff') {
      const r = JSON.parse(JSON.stringify(P.FACE_OFF));
      for (const resource of P.RESOURCES) {
        const ov = overrides['faceoff:' + resource];
        if (Number.isFinite(ov) && ov >= 0) r[resource].points = ov;
      }
      return r;
    }
    const defaults = P.PHASE_RULES[phase];
    if (!defaults) return {};
    const r = JSON.parse(JSON.stringify(defaults));
    for (const [key, val] of Object.entries(r)) {
      if (typeof val === 'number') {
        const ov = overrides[phase + ':' + key];
        if (Number.isFinite(ov) && ov >= 0) r[key] = ov;
      } else if (key === 'officers') {
        for (const lvl of Object.keys(val)) {
          const ov = overrides[phase + ':officer' + lvl];
          if (Number.isFinite(ov) && ov >= 0) r.officers[lvl] = ov;
        }
      } else if (key === 'confiscation') {
        for (const resource of P.RESOURCES) {
          const ov = overrides[phase + ':' + resource];
          if (Number.isFinite(ov) && ov >= 0) r.confiscation[resource].points = ov;
        }
      }
    }
    return r;
  }
  function eventDefinitions(phase) {
    if (phase === 'faceoff') {
      return P.RESOURCES.map(resource => ({ key: resource,
        label: resource[0].toUpperCase() + resource.slice(1) + ' gathered',
        factor: P.FACE_OFF[resource].amount, unit: P.FACE_OFF[resource].points }));
    }
    const data = P.PHASE_RULES[phase] || {};
    const defs = Object.entries(data).filter(([, val]) => typeof val === 'number')
      .map(([key, val]) => ({ key, label: baseLabels[key] || key, factor: 1, unit: val }));
    if (data.officers) for (const [tier, points] of Object.entries(data.officers)) {
      defs.push({ key: 'officer' + tier, label: 'Level ' + tier + ' Officers trained', factor: 1, unit: points });
    }
    if (data.confiscation) for (const resource of P.RESOURCES) {
      defs.push({ key: resource, label: resource[0].toUpperCase() + resource.slice(1) + ' confiscated',
        factor: data.confiscation[resource].amount, unit: data.confiscation[resource].points });
    }
    return defs;
  }
  function renderEvents(regenerate = false) {
    const phaseEl = el('planner-phase');
    if (!phaseEl) return;
    const phase = phaseEl.value;
    const defs = eventDefinitions(phase);
    const savedInputs = phaseInputs[phase] || {};
    if (regenerate || !el('planner-event-fields').querySelector('input')) {
      el('planner-event-fields').innerHTML = defs.map(d =>
        field(d.label, d.key, savedInputs[d.key] || 0)).join('');
    }
    const rules = eventRates(phase);
    let total = 0;
    const fields = all('[data-event-input]');
    for (const input of fields) {
      const key = input.dataset.eventInput;
      if (!defs.some(d => d.key === key)) continue;
      const amount = int(input.value);
      savedInputs[key] = amount;
      const def = defs.find(d => d.key === key);
      let pointValue = def.unit;
      if (phase === 'faceoff') pointValue = rules[key].points;
      else if (rules.officers && key.startsWith('officer')) pointValue = rules.officers[key.slice(7)];
      else if (rules.confiscation && rules.confiscation[key]) pointValue = rules.confiscation[key].points;
      else if (typeof rules[key] === 'number') pointValue = rules[key];
      total += Math.floor(amount / def.factor) * pointValue;
    }
    phaseInputs[phase] = savedInputs;
    const target = int(el('planner-target').value);
    el('planner-event-total').textContent = readable(total) + ' pts';
    el('planner-event-remaining').textContent = target
      ? (total >= target ? 'Target achieved' : readable(target - total) + ' pts to target')
      : 'Set a target to see how many points remain';
    el('planner-event-source').textContent = phase === 'faceoff'
      ? 'Alliance Faceoff gathering: 2,000 Ammo/Cash, 400 Electricity or 100 Gas = 2 pts. Day 1/3.'
      : phase === '3' ? 'Phase 3 · Officer Training (Lv4–10).'
      : phase === '4' ? 'Phase 4 · Resource Confiscation.'
      : phase === '5' ? 'Phase 5 · Power Sprint.'
      : 'Phase 1 · PD Construction. Phase 2 is not available yet.';
    const custom = el('planner-custom-points');
    if (regenerate || custom.dataset.phase !== phase) {
      custom.dataset.phase = phase;
      custom.innerHTML = defs.map(d => '<label>' + esc(d.label) + ' (points per ' +
        esc(d.factor) + ')<input type="number" min="0" step="1" data-event-rate="' + esc(d.key) +
        '" value="' + esc(overrides[phase + ':' + d.key] ?? d.unit) + '"></label>').join('');
    }
  }
  function renderSpeedups() {
    const d = Math.min(365, int(el('planner-speed-days').value));
    const h = Math.min(23, int(el('planner-speed-hours').value));
    const m = Math.min(59, int(el('planner-speed-minutes').value));
    const total = d * 1440 + h * 60 + m;
    el('planner-speed-total').textContent = P.duration(total * 60);
    el('planner-speed-singles').innerHTML = P.speedupSingles(total).map(item =>
      stat(item.label + ' speedups', readable(item.count) + (item.extra ? ' (+' + P.duration(item.extra * 60) + ')' : ''))).join('');
    const inventory = Object.fromEntries(all('[data-speed-owned]').map(input =>
      [input.dataset.speedOwned, int(input.value)]));
    const mix = P.speedupMix(total, inventory);
    el('planner-speed-mix').innerHTML = '<span>Longest-first inventory suggestion</span><strong>' +
      (Object.entries(mix.counts).filter(([, count]) => count)
        .map(([type, count]) => readable(count) + ' × ' + esc(type)).join(' · ') || 'No speedups selected') +
      '</strong><small>' + (mix.remaining ? esc(P.duration(mix.remaining * 60)) +
        ' still remaining' : mix.waste ? esc(P.duration(mix.waste * 60)) + ' extra used' :
        'Exact time covered') + '</small>';
  }
  function init() {
    if (!el('planner-troop')) return;
    el('planner-troop').addEventListener('change', () => {
      syncTrainingSample();
      renderTraining();
    });
    el('planner-target-points').addEventListener('input', renderTraining);
    el('planner-actual-sample').addEventListener('input', () => {
      const key = el('planner-troop').value;
      const value = el('planner-actual-sample').value.trim();
      if (value) trainingTimes[key] = value;
      else delete trainingTimes[key];
      saveTrainingTimes();
      renderTraining();
    });
    document.querySelectorAll('[data-locked-troop]').forEach(button =>
      button.addEventListener('click', () => el('locked-troop-dialog').showModal()));
    el('planner-capacity').addEventListener('click', () => {
      const active = el('planner-capacity').getAttribute('aria-pressed') !== 'true';
      el('planner-capacity').setAttribute('aria-pressed', String(active));
      el('planner-capacity-state').textContent = active ? 'ON' : 'OFF';
      renderTraining();
    });
    el('planner-send-speedups').addEventListener('click', () => {
      const result = targetTraining();
      if (!result) return;
      if (result.actualSeconds === null) return;
      const minutes = Math.ceil(result.actualSeconds / 60);
      el('planner-speed-days').value = Math.floor(minutes / 1440);
      el('planner-speed-hours').value = Math.floor(minutes % 1440 / 60);
      el('planner-speed-minutes').value = minutes % 60;
      renderSpeedups();
      document.querySelector('[data-view="tool-speedups"]').click();
    });
    el('planner-send-event').addEventListener('click', () => {
      const troop = P.TROOPS[el('planner-troop').value];
      if (!troop) return;
      el('planner-phase').value = '3';
      const result = targetTraining();
      phaseInputs['3'] = { ...(phaseInputs['3'] || {}), ['officer' + troop.tier]: result.quantity };
      renderEvents(true);
      document.querySelector('[data-view="tool-events"]').click();
    });
    el('planner-building-level').addEventListener('change', renderBuildings);
    for (const id of ['planner-gather-type', 'planner-gather-level', 'planner-gather-bonus'])
      el(id).addEventListener('input', renderGathering);
    el('planner-phase').addEventListener('change', () => renderEvents(true));
    el('planner-target').addEventListener('input', () => renderEvents(false));
    el('planner-event-fields').addEventListener('input', () => renderEvents(false));
    el('planner-custom-points').addEventListener('input', event => {
      const key = event.target.dataset.eventRate;
      if (!key) return;
      const value = Number(event.target.value);
      if (!Number.isFinite(value) || value < 0) return;
      overrides[el('planner-phase').value + ':' + key] = Math.floor(value);
      saveCustom();
      renderEvents(false);
    });
    el('planner-reset-rates').addEventListener('click', () => {
      const prefix = el('planner-phase').value + ':';
      for (const key of Object.keys(overrides)) if (key.startsWith(prefix)) delete overrides[key];
      saveCustom();
      renderEvents(true);
    });
    for (const id of ['planner-speed-days', 'planner-speed-hours', 'planner-speed-minutes'])
      el(id).addEventListener('input', renderSpeedups);
    el('planner-speed-inventory').addEventListener('input', renderSpeedups);
    loadTrainingTimes();
    syncTrainingSample();
    renderTraining();
    renderBuildings();
    renderGathering();
    renderEvents(true);
    renderSpeedups();
  }
  root.SasPlannerUI = { init, setIdentity, renderTraining, renderBuildings, renderGathering,
    renderEvents, renderSpeedups };
})(typeof window !== 'undefined' ? window : globalThis);
