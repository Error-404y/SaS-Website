(() => {
  const one = selector => document.querySelector(selector);
  const rssTools = window.SasRss;
  const unreadTools = window.SasUnread;
  const readKey = 'sas-read-state-v1-admin';
  const all = selector => [...document.querySelectorAll(selector)];
  const site = { entries: [], settings: {}, rss: null, admin: false, member: false, csrf: null, page: 'events', selected: null, loaded: false, clockOffset: 0, rssFormRevision: '', rssFormInitialBalances: {}, rssFormInitialRemaining: '' };
  const labels = { events: 'Events', alliance: 'Alliance Events', rss: 'Alliance RSS',
    updates: 'Website Updates', announcements: 'HR Announcements', accounts: 'SaS – Accounts',
    'tool-overview': 'Calculators', 'tool-events': 'Event Points', 'tool-training': 'Troop Training',
    'tool-buildings': 'Building Costs', 'tool-speedups': 'Speedups', 'tool-gathering': 'RSS Gathering',
    'tool-svs': 'State vs. State', 'tool-chief': 'Chief Almighty',
    'tool-shards': 'Hero Star-Up', 'tool-pd': 'PD Level 1–30' };
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
  const calendar = window.SasCalendar;
  const toTime = value => calendar.utcTime(value);
  const currentUtc = () => new Date().toISOString().slice(0, 19).replace('T', ' ');
  let toastTimer;
  let adminLastInteraction = Date.now();
  let adminActivityLastSent = 0;
  let adminActivitySending = false;
  const ADMIN_IDLE_MS = 30 * 60 * 1000;

  function adminExpired() {
    site.entries = [];
    site.accounts = [];
    site.rss = null;
    site.member = false;
    setAdmin(false);
    window.location.replace('/');
  }

  function trackAdminInteraction(event) {
    if (!site.admin || (event.type === 'keydown' && (
      event.key === 'Shift' || event.key === 'Control' || event.key === 'Alt'))) return;
    const now = Date.now();
    if (now - adminLastInteraction >= ADMIN_IDLE_MS) {
      adminExpired();
      return;
    }
    adminLastInteraction = now;
    if (adminActivitySending || now - adminActivityLastSent < 60000) return;
    adminActivityLastSent = now;
    adminActivitySending = true;
    request('/api/admin/activity', { method: 'POST', body: '{}' })
      .catch(() => adminExpired())
      .finally(() => { adminActivitySending = false; });
  }

  ['pointerdown', 'keydown', 'touchstart'].forEach(type =>
    document.addEventListener(type, trackAdminInteraction, { passive: true }));

  async function request(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (site.csrf && options.method && options.method !== 'GET') headers['X-CSRF-Token'] = site.csrf;
    const response = await fetch(path, { credentials: 'same-origin', ...options, headers });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Something went wrong.');
    return data;
  }

  function notify(message) {
    const node = one('#toast');
    node.textContent = message;
    node.classList.add('visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.remove('visible'), 3600);
  }

  function updateClock() {
    one('#clock').textContent = currentUtc() + ' UTC';
  }

  function status(item) {
    return calendar.eventStatus(item);
  }

  function statusTag(state) {
    const titles = { active: 'In Progress', upcoming: 'Upcoming', ended: 'Ended' };
    return '<span class="status-pill status-' + state + '">' + titles[state] + '</span>';
  }

  function setAdmin(isAdmin, csrf = null) {
    site.admin = isAdmin;
    site.csrf = csrf;
    one('[data-view="accounts"]').hidden = !isAdmin;
    all('.admin-only').forEach(node => { node.hidden = !isAdmin; });
    one('#admin-toggle').textContent = isAdmin || site.member ? 'Sign out' : 'Admin login';
  }

  let readState = null;

  try {
    const stored = JSON.parse(localStorage.getItem(readKey));
    if (stored && typeof stored === 'object' && !Array.isArray(stored)) readState = stored;
  } catch (_) {
    readState = null;
  }

  function storeReadState() {
    if (site.member) return; // Approved players sync read state to SQLite instead.
    try {
      localStorage.setItem(readKey, JSON.stringify(readState));
    } catch (_) {
      return;
    }
  }

  function unreadSnapshot() {
    return unreadTools.snapshot(site.entries, site.rss);
  }

  function showUnread() {
    if (!site.loaded) return;
    const current = unreadSnapshot();
    if (!readState) {
      readState = current;
      storeReadState();
    }
    const counts = unreadTools.count(current, readState);
    all('[data-unread]').forEach(node => {
      const count = counts[node.dataset.unread] || 0;
      node.hidden = count === 0;
      node.textContent = count > 99 ? '99+' : String(count);
      node.setAttribute('aria-label', count + ' unread items');
      node.parentElement.toggleAttribute('data-unread-priority', count > 0);
    });
    // Unread tabs move to the beginning; reading them restores the default order.
    const kinds = unreadTools.sections;
    const ranked = [...kinds].sort((a, b) =>
      (counts[b] || 0) - (counts[a] || 0) || kinds.indexOf(a) - kinds.indexOf(b));
    for (const kind of kinds) {
      const button = one('.sidebar-nav [data-view="' + kind + '"]');
      if (button) button.style.order = counts[kind] ? ranked.indexOf(kind) - 10 : kinds.indexOf(kind);
    }
  }

  function acknowledgePage(kind) {
    if (!site.loaded) return;
    if (!readState) readState = unreadSnapshot();
    const current = unreadSnapshot();
    const pending = unreadTools.count(current, readState)[kind] || 0;
    if (!pending) return;
    readState = unreadTools.acknowledge(readState, current, kind);
    if (site.member) {
      request('/api/reads', { method: 'POST', body: JSON.stringify({ kind }) })
        .then(data => {
          if (data && data.seen) {
            // Merge the acknowledged section without erasing other local updates.
            readState = { ...readState, [kind]: data.seen[kind] };
            showUnread();
          }
        })
        .catch(() => { /* Server read state is restored on next login. */ });
    } else {
      storeReadState();
    }
    showUnread();
  }

  function setClockOffset(timestamp) {
    const parsed = Date.parse(timestamp);
    if (Number.isFinite(parsed)) site.clockOffset = parsed - Date.now();
  }

  function refreshResearchCountdown() {
    if (!site.loaded) return;
    const data = rssTools.normalize(site.rss);
    const remaining = rssTools.remainingSeconds(data.tech_ends_at, Date.now() + site.clockOffset);
    const box = one('#rss-tech-countdown-box');
    const noTimer = one('#rss-tech-unreported');
    box.classList.toggle('hidden', remaining === null);
    noTimer.classList.toggle('hidden', remaining !== null);
    if (remaining !== null) {
      one('#rss-tech-time-remaining').textContent = rssTools.formatDuration(remaining);
      one('#rss-tech-time-label').textContent = remaining === 0 ? 'Research complete' : 'Research in progress';
      box.classList.toggle('is-complete', remaining === 0);
    }
  }

  function switchPage(name) {
    if (!labels[name] || (name === 'accounts' && !site.admin)) return;
    site.page = name;
    all('.page').forEach(node => {
      const selected = node.dataset.section === name;
      node.classList.toggle('hidden', !selected);
      if (selected) {
        node.classList.remove('page-animate');
        void node.offsetWidth;
        node.classList.add('page-animate');
      }
    });
    const toolPage = name.startsWith('tool-');
    one('#site-layout').classList.toggle('tools-open', toolPage);
    one('#tools-sidebar').classList.toggle('hidden', !toolPage);
    all('[data-view]').forEach(node => {
      const selected = node.dataset.view === name ||
        (toolPage && node.closest('.sidebar-nav') && node.dataset.view === 'tool-overview');
      node.classList.toggle('selected', selected);
      if (selected) node.setAttribute('aria-current', 'page');
      else node.removeAttribute('aria-current');
    });
    one('#header-section').textContent = labels[name];
    acknowledgePage(name);
    history.replaceState({}, '', '#' + name);
    render();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function eventRows(kind) {
    const entries = site.entries.filter(item => item.kind === kind);
    const active = entries.filter(item => status(item) === 'active').length;
    const upcoming = entries.filter(item => status(item) === 'upcoming').length;
    one('#' + kind + '-active').textContent = active;
    one('#' + kind + '-upcoming').textContent = upcoming;
    const search = one('#' + kind + '-search').value.toLowerCase().trim();
    const currentStatus = one('#' + kind + '-status').value;
    const category = kind === 'events' ? one('#events-category').value : '';
    const filtered = entries.filter(item => {
      const state = status(item);
      return (!search || (item.title + ' ' + item.category + ' ' + item.details).toLowerCase().includes(search))
        && (!category || item.category === category)
        && (currentStatus ? state === currentStatus : state !== 'ended');
    }).sort((a, b) => {
      const order = { active: 0, upcoming: 1, ended: 2 };
      return order[status(a)] - order[status(b)] || toTime(a.start_utc) - toTime(b.start_utc);
    });
    one('#' + kind + '-rows').innerHTML = filtered.map(item => {
      const urgency = status(item) === 'upcoming' ? window.SasReference.upcomingUrgency(item.start_utc, Date.now()) : 'normal';
      return '<tr class="event-row event-soon-' + urgency + '" tabindex="0" role="button" data-id="' + item.id + '" aria-label="View ' + escapeHtml(item.title) + ' details">' +
        '<td><strong>' + escapeHtml(item.title) + '</strong><span class="mobile-date">' + escapeHtml(item.start_utc) + ' UTC</span></td>' +
        '<td>' + escapeHtml(item.category) + '</td>' +
        '<td class="date-cell">' + escapeHtml(item.start_utc) + '</td>' +
        '<td class="date-cell">' + escapeHtml(item.end_utc) + '</td>' +
        '<td class="event-status-cell">' + statusTag(status(item)) +
        '<span class="event-countdown" data-countdown-id="' + item.id + '">' + calendar.countdown(item) + '</span></td></tr>';
    }).join('') || '<tr><td class="empty-row" colspan="5">No ' + (kind === 'alliance' ? 'alliance ' : '') + 'events match your filters.</td></tr>';
  }

  function posts(kind) {
    const entries = site.entries.filter(item => item.kind === kind)
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
    const target = one('#' + kind + '-list');
    target.innerHTML = entries.length ? entries.map(item => {
      const badge = kind === 'announcements' ? '<span class="post-author">' + escapeHtml(item.author) + '</span>' : '';
      const actions = site.admin ? '<button type="button" class="post-edit" data-edit="' + item.id + '">Edit</button>' : '';
      const date = item.created_at ? new Date(item.created_at).toLocaleDateString('en-GB', { timeZone: 'UTC', day: 'numeric', month: 'long', year: 'numeric' }) : '';
      return '<article class="post-card"><div class="post-meta"><time>' + escapeHtml(date) + '</time>' + badge + actions +
        '</div><h2>' + escapeHtml(item.title) + '</h2><p>' + escapeHtml(item.details).replace(/\n/g, '<br>') + '</p></article>';
    }).join('') : '<div class="empty-content"><h2>Nothing posted yet</h2><p>Check back here for ' + (kind === 'updates' ? 'website updates.' : 'announcements from the alliance leadership.') + '</p></div>';
  }

  function rss() {
    const data = rssTools.normalize(site.rss || {
      tech_plan: site.settings.tech_plan || '',
      legacy_hour: site.settings.rss_hour || ''
    });
    for (const key of rssTools.resources) {
      one('#rss-limit-' + key).textContent = 'Capacity ' + rssTools.formatAmount(data.resources[key].limit);
      const rate = one('#rss-rate-' + key);
      rate.textContent = rssTools.formatRate(data.resources[key].per_hour);
      rate.classList.toggle('rss-value-missing', data.resources[key].per_hour === null);
    }
    for (const key of rssTools.buffs) {
      const buff = one('#rss-buff-' + key);
      buff.textContent = rssTools.formatBuff(data.buffs[key]);
      buff.classList.toggle('rss-value-missing', data.buffs[key] === null);
    }
    one('#rss-buffs-heading').textContent = Object.values(data.buffs).some(value => value > 0)
      ? 'Active Territory Buffs' : 'Territory Buffs';
    one('#rss-territory-plan').textContent = data.territory_plan ||
      'Alliance HQ and flags expand controlled territory.';
    one('#rss-tech-name').textContent = data.tech_name || 'No technology selected';
    one('#rss-tech-plan').textContent = data.tech_plan ||
      'Our next technology plan has not been posted yet.';
    one('#rss-tech-stage').textContent = data.tech_stage;
    one('#rss-tech-stage').classList.toggle('hidden', !data.tech_stage);
    refreshResearchCountdown();
    one('#rss-last-updated').textContent = rssTools.formatUpdated(data.updated_at);
    refreshResourceBalances();
    renderSpending(data);
    const unassigned = data.legacy_hour.trim() &&
      rssTools.resources.every(key => data.resources[key].per_hour === null);
    const legacy = one('#rss-legacy-note');
    legacy.classList.toggle('hidden', !unassigned || !site.admin);
    if (unassigned) {
      legacy.textContent = 'Previously saved total rate: ' + data.legacy_hour +
        '/h. This value has been kept, but it cannot be assigned to individual resources automatically.';
    }
  }

  function refreshResourceBalances() {
    if (!site.loaded) return;
    const data = rssTools.normalize(site.rss);
    for (const key of rssTools.resources) {
      const item = data.resources[key];
      const amount = rssTools.estimateBalance(item, data.as_of, Date.now() + site.clockOffset);
      const node = one('#rss-amount-' + key);
      node.textContent = rssTools.formatAmount(amount);
      node.title = amount === null ? 'Balance not entered' : amount.toLocaleString('en-US', { maximumFractionDigits: 2 }) + ' / ' + item.limit.toLocaleString('en-US');
    }
  }

  function renderSpending(data) {
    const target = one('#rss-spending-list');
    if (!data.spending.length) {
      target.innerHTML = '<p class="rss-empty-spending">No resources spent yet.</p>';
      return;
    }
    const names = { ammo: 'Ammo', cash: 'Cash', electricity: 'Electricity', gas: 'Gas' };
    target.innerHTML = data.spending.map(item => {
      const deleteButton = site.admin ? '<button class="spend-delete" data-spend-delete="' + item.id + '" type="button" aria-label="Remove spending entry">Remove</button>' : '';
      const time = escapeHtml(item.spent_at) + ' UTC';
      const note = item.note ? '<span class="spend-note">' + escapeHtml(item.note) + '</span>' : '';
      const included = item.included ? '' : '<span class="spend-prior">Already included in the last saved balance</span>';
      return '<div class="spend-row"><div class="spend-row-main"><strong>' + escapeHtml(names[item.resource] || item.resource) +
        '</strong><span>' + time + '</span>' + note + included + '</div><div class="spend-row-end"><strong>-' +
        rssTools.formatAmount(item.amount) + '</strong>' + deleteButton + '</div></div>';
    }).join('');
  }

  async function recordSpending(event) {
    event.preventDefault();
    one('#spend-error').textContent = '';
    try {
      const payload = {
        resource: one('#spend-resource').value,
        amount: rssTools.readNumber(one('#spend-amount').value, 'Spending amount'),
        spent_at: one('#spend-at').value.trim(),
        note: one('#spend-note').value
      };
      if (payload.amount === null || payload.amount <= 0) throw new Error('Enter an amount greater than zero.');
      await request('/api/rss/spending', { method: 'POST', body: JSON.stringify(payload) });
      one('#spend-dialog').close();
      await reload();
      acknowledgePage('rss');
      notify('Spending recorded.');
    } catch (error) {
      one('#spend-error').textContent = error.message;
    }
  }

  async function deleteSpending(id) {
    if (!site.admin || !await confirmAction({
      title: 'Remove spending record?',
      message: 'The resource balance will be recalculated after this record is removed.',
      buttonLabel: 'Remove record'
    })) return;
    try {
      await request('/api/rss/spending/' + id, { method: 'DELETE' });
      await reload();
      acknowledgePage('rss');
      notify('Spending record removed.');
    } catch (error) {
      notify(error.message);
    }
  }

  function render() {
    eventRows('events');
    eventRows('alliance');
    posts('updates');
    posts('announcements');
    rss();
    if (site.admin && site.page === 'accounts') {
      loadAccounts();
      loadDiscordStatus();
    }
    refreshCountdowns();
    showUnread();
  }

  function refreshCountdowns() {
    const now = Date.now();
    const events = new Map(site.entries.filter(item => item.kind === 'events' || item.kind === 'alliance')
      .map(item => [item.id, item]));
    let changed = false;
    all('.event-row[data-id]').forEach(row => {
      const item = events.get(Number(row.dataset.id));
      const badge = row.querySelector('.status-pill');
      if (item && badge && !badge.classList.contains('status-' + calendar.eventStatus(item, now))) {
        changed = true;
      }
      if (item) {
        const urgency = calendar.eventStatus(item, now) === 'upcoming' ? window.SasReference.upcomingUrgency(item.start_utc, now) : 'normal';
        row.classList.toggle('event-soon-yellow', urgency === 'yellow');
        row.classList.toggle('event-soon-red', urgency === 'red');
        row.classList.toggle('event-soon-normal', urgency === 'normal');
      }
    });
    if (changed) {
      eventRows('events');
      eventRows('alliance');
    }
    all('[data-countdown-id]').forEach(node => {
      const item = events.get(Number(node.dataset.countdownId));
      if (item) node.textContent = calendar.countdown(item, now);
    });
    for (const kind of ['events', 'alliance']) {
      const items = site.entries.filter(item => item.kind === kind);
      one('#' + kind + '-active').textContent = items.filter(item => calendar.eventStatus(item, now) === 'active').length;
      one('#' + kind + '-upcoming').textContent = items.filter(item => calendar.eventStatus(item, now) === 'upcoming').length;
    }
    if (one('#detail-dialog').open) {
      const item = events.get(site.selected);
      if (item) {
        one('#detail-status').textContent = { active: 'In Progress', upcoming: 'Upcoming', ended: 'Ended' }[calendar.eventStatus(item, now)];
      }
    }
  }

  async function reload() {
    const data = await request('/api/state');
    site.entries = Array.isArray(data.entries) ? data.entries : [];
    site.settings = data.settings || {};
    site.rss = data.rss || null;
    setClockOffset(data.utc);
    site.loaded = true;
    if (!document.hidden) acknowledgePage(site.page);
    render();
  }

  function openDialog(id) {
    one('#' + id).showModal();
  }

  function confirmAction({ title, message, buttonLabel = 'Delete permanently' }) {
    const dialog = one('#confirm-action-dialog');
    // Avoid opening two destructive confirmations simultaneously.
    if (dialog.open) return Promise.resolve(false);
    one('#confirm-action-title').textContent = title;
    one('#confirm-action-message').textContent = message;
    one('#confirm-action-error').textContent = '';
    one('[data-confirm-choice="accept"]').textContent = buttonLabel;
    return new Promise(resolve => {
      let selected = false;
      const cleanup = () => {
        dialog.removeEventListener('click', choose);
        dialog.removeEventListener('close', finish);
      };
      const finish = () => {
        cleanup();
        resolve(selected);
      };
      const choose = event => {
        const button = event.target.closest('[data-confirm-choice]');
        if (!button || !dialog.contains(button)) return;
        selected = button.dataset.confirmChoice === 'accept';
        dialog.close();
      };
      dialog.addEventListener('click', choose);
      dialog.addEventListener('close', finish, { once: true });
      dialog.showModal();
    });
  }

  function inspect(id) {
    const item = site.entries.find(entry => entry.id === id);
    if (!item) return;
    site.selected = id;
    one('#detail-title').textContent = item.title;
    one('#detail-countdown').dataset.countdownId = String(item.id);
    one('#detail-countdown').textContent = calendar.countdown(item);
    one('#google-calendar-link').href = calendar.googleCalendarUrl(item);
    const fields = [
      ['Category', item.category],
      ['Status', { active: 'In Progress', upcoming: 'Upcoming', ended: 'Ended' }[status(item)]],
      ['Start (UTC)', item.start_utc],
      ['End (UTC)', item.end_utc],
      ['Rewards', item.rewards || 'Not specified'],
      ['Details', item.details || 'No additional details']
    ];
    one('#detail-body').innerHTML = fields.map(([label, value]) =>
      '<div class="detail-item"><span>' + label + '</span><p' + (label === 'Status' ? ' id="detail-status"' : '') + '>' + escapeHtml(value).replace(/\n/g, '<br>') + '</p></div>'
    ).join('');
    one('#detail-edit').hidden = !site.admin;
    openDialog('detail-dialog');
  }

  function downloadCalendar() {
    const item = site.entries.find(entry => entry.id === site.selected);
    if (!item) return;
    const data = calendar.calendarFile(item);
    const blob = new Blob([data], { type: 'text/calendar;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'sas-event-' + item.id + '.ics';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function edit(kind, id = null) {
    if (!site.admin) return;
    const item = site.entries.find(entry => entry.id === id);
    one('#entry-form').reset();
    one('#entry-id').value = id || '';
    one('#entry-kind').value = kind;
    one('#entry-heading').textContent = (item ? 'Edit ' : 'Add ') + (kind === 'alliance' ? 'alliance event' : kind === 'events' ? 'event' : kind === 'updates' ? 'website update' : 'announcement');
    one('#event-fields').classList.toggle('hidden', kind !== 'events' && kind !== 'alliance');
    one('#author-field').classList.toggle('hidden', kind !== 'announcements');
    one('#entry-category').disabled = kind === 'alliance';
    one('#details-label').textContent = kind === 'events' || kind === 'alliance' ? 'Notes' : 'Message';
    one('#entry-error').textContent = '';
    one('#entry-delete').classList.toggle('hidden', !item);
    if (item) {
      one('#entry-title').value = item.title;
      one('#entry-category').value = kind === 'alliance' ? 'Alliance' : item.category;
      one('#entry-start').value = item.start_utc;
      one('#entry-end').value = item.end_utc;
      one('#entry-rewards').value = item.rewards;
      one('#entry-details').value = item.details;
      one('#entry-author').value = item.author || 'R4';
    } else if (kind === 'events' || kind === 'alliance') {
      const start = new Date(Math.ceil(Date.now() / 3600000) * 3600000);
      one('#entry-start').value = start.toISOString().slice(0, 19).replace('T', ' ');
      one('#entry-end').value = new Date(start.getTime() + 3600000).toISOString().slice(0, 19).replace('T', ' ');
    }
    openDialog('entry-dialog');
  }

  async function saveEntry(event) {
    event.preventDefault();
    const kind = one('#entry-kind').value;
    const id = one('#entry-id').value;
    const body = {
      kind,
      title: one('#entry-title').value,
      category: kind === 'alliance' ? 'Alliance' : one('#entry-category').value,
      start_utc: one('#entry-start').value,
      end_utc: one('#entry-end').value,
      rewards: one('#entry-rewards').value,
      details: one('#entry-details').value,
      author: one('#entry-author').value
    };
    const error = one('#entry-error');
    error.textContent = '';
    try {
      if (kind === 'events' || kind === 'alliance') {
        const valid = text => /^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/.test(text);
        if (!valid(body.start_utc) || !valid(body.end_utc)) throw new Error('Use UTC format YYYY-MM-DD HH:MM:SS.');
      }
      await request(id ? '/api/entries/' + id : '/api/entries', {
        method: id ? 'PUT' : 'POST', body: JSON.stringify(body)
      });
      one('#entry-dialog').close();
      await reload();
      notify('Saved successfully.');
    } catch (reason) {
      error.textContent = reason.message;
    }
  }

  async function deleteEntry() {
    const id = one('#entry-id').value;
    if (!id || !await confirmAction({
      title: 'Delete this entry?',
      message: 'This entry will be permanently removed. This action cannot be undone.',
      buttonLabel: 'Delete entry'
    })) return;
    try {
      await request('/api/entries/' + id, { method: 'DELETE' });
      one('#entry-dialog').close();
      await reload();
      notify('Entry deleted.');
    } catch (error) {
      one('#entry-error').textContent = error.message;
    }
  }

  async function saveRss(event) {
    event.preventDefault();
    const error = one('#rss-error');
    error.textContent = '';
    try {
      const resources = {};
      for (const key of rssTools.resources) {
        resources[key] = {
          stored: rssTools.readNumber(one('#rss-stock-' + key).value, key + ' balance'),
          per_hour: rssTools.readNumber(one('#rss-income-' + key).value, key + ' income per hour'),
          limit: rssTools.readNumber(one('#rss-cap-' + key).value, key + ' capacity')
        };
      }
      const buffs = {};
      for (const key of rssTools.buffs) {
        buffs[key] = rssTools.readNumber(one('#rss-buff-input-' + key).value,
          key.replace(/_/g, ' ') + ' buff', 1000);
      }
      const payload = {
        resources,
        buffs,
        tech_name: one('#rss-tech-title-input').value,
        tech_stage: one('#rss-tech-stage-input').value,
        tech_plan: one('#rss-tech-notes-input').value,
        tech_remaining: one('#rss-tech-remaining-input').value.trim(),
        revision: site.rssFormRevision,
        territory_plan: one('#rss-territory-input').value
      };
      if (payload.tech_remaining === site.rssFormInitialRemaining) {
        delete payload.tech_remaining;
      } else {
        rssTools.parseDuration(payload.tech_remaining);
      }
      const snapshot = rssTools.normalize(site.rss);
      for (const key of rssTools.resources) {
        const item = payload.resources[key];
        if (item.limit === null || item.limit <= 0) throw new Error(key + ' capacity must be greater than zero.');
        if (one('#rss-stock-' + key).value === site.rssFormInitialBalances[key]) {
          const estimate = rssTools.estimateBalance(snapshot.resources[key], snapshot.as_of, Date.now() + site.clockOffset);
          item.stored = estimate === null ? null : Math.round(estimate * 100) / 100;
        }
        if (item.stored !== null && item.stored > item.limit) throw new Error(key + ' balance exceeds its capacity.');
      }
      await request('/api/rss', { method: 'PUT', body: JSON.stringify(payload) });
      one('#rss-dialog').close();
      await reload();
      notify('Alliance RSS updated.');
    } catch (problem) {
      error.textContent = problem.message;
    }
  }

  async function login(event) {
    event.preventDefault();
    one('#login-error').textContent = '';
    try {
      const data = await request('/api/login', { method: 'POST', body: JSON.stringify({
        username: one('#login-username').value, password: one('#login-password').value
      }) });
      site.member = false;
      setAdmin(true, data.csrf);
      adminLastInteraction = Date.now();
      adminActivityLastSent = adminLastInteraction;
      unlockSite();
      one('#login-form').reset();
      one('#login-dialog').close();
      render();
      notify('Signed in.');
    } catch (error) {
      one('#login-error').textContent = error.message;
    }
  }

  async function toggleAdmin() {
    if (!site.admin && !site.member) {
      openDialog('login-dialog');
      return;
    }
    try {
      await request(site.admin ? '/api/logout' : '/api/member/logout', { method: 'POST', body: '{}' });
      site.member = false;
      site.entries = [];
      site.settings = {};
      site.rss = null;
      site.accounts = [];
      site.passwordRequests = [];
      site.loaded = false;
      setAdmin(false);
      sessionStorage.removeItem('sas-entered');
      window.location.replace('/');
    } catch (error) {
      notify(error.message);
    }
  }


  function unlockSite() {
    one('#auth-gate').classList.add('hidden');
    one('#entrance').classList.add('hidden');
    one('#website').classList.remove('hidden');
    sessionStorage.setItem('sas-entered', '1');
    one('#admin-toggle').textContent = 'Sign out';
  }

  function authMessage(message, ok = false) {
    const node = one('#auth-feedback');
    node.textContent = message;
    node.classList.toggle('success', ok);
  }

  function authTab(tab) {
    all('[data-auth-tab]').forEach(node => node.classList.toggle('active', node.dataset.authTab === tab));
    one('#member-login-form').classList.toggle('hidden', tab !== 'signin');
    one('#member-register-form').classList.toggle('hidden', tab !== 'register');
    one('#password-request-form').classList.add('hidden');
    one('#password-complete-form').classList.add('hidden');
    one('.auth-tabs').classList.remove('hidden');
    one('#auth-heading').textContent = tab === 'signin' ? 'Welcome back' : 'Join Saints and Sinners';
    one('#auth-subheading').textContent = tab === 'signin' ?
      'Sign in to continue to Saints and Sinners.' : 'Submit your account for alliance review.';
    authMessage('');
  }

  async function playerLogin(event) {
    event.preventDefault();
    authMessage('');
    try {
      const response = await request('/api/member/login', { method: 'POST', body: JSON.stringify({
        username: one('#member-login-name').value, password: one('#member-login-password').value
      }) });
      site.member = true;
      setAdmin(false, response.csrf);
      unlockSite();
      await reload();
      one('#member-login-form').reset();
    } catch (error) { authMessage(error.message); }
  }

  async function registerPlayer(event) {
    event.preventDefault();
    authMessage('');
    try {
      await request('/api/register', { method: 'POST', body: JSON.stringify({
        username: one('#member-username').value,
        player_name: one('#member-player').value,
        email: one('#member-email').value,
        password: one('#member-password').value
      }) });
      one('#member-register-form').reset();
      authTab('signin');
      authMessage('Registration received. An administrator must approve your account before you can sign in.', true);
    } catch (error) { authMessage(error.message); }
  }

  async function loadDiscordStatus() {
    if (!site.admin) return;
    const target = one('#discord-status-grid');
    if (!target) return;
    try {
      const data = await request('/api/notifications/status');
      const names = { registration: 'New registrations', login: 'Member / admin login', reminder: 'Event reminders (1h)' };
      target.innerHTML = Object.entries(data.channels).map(([key, channel]) =>
        '<article class="discord-status-card"><strong>' + escapeHtml(names[key] || key) + '</strong>' +
        '<span class="discord-status-indicator ' + (channel.configured ? 'is-set' : 'is-unset') + '">' +
        (channel.configured ? 'Configured' : 'Not configured') + '</span>' +
        '<small>Last delivery: ' + escapeHtml(channel.last_result) + '</small>' +
        '<button type="button" class="small-button" data-test-discord="' + escapeHtml(key) + '"' +
        (channel.configured ? '' : ' disabled') + '>Send test</button></article>'
      ).join('');
    } catch (error) {
      target.textContent = 'Unable to read Discord status: ' + error.message;
    }
  }

  async function testDiscord(channel, button) {
    if (!site.admin) return;
    button.disabled = true;
    try {
      await request('/api/notifications/test', {
        method: 'POST', body: JSON.stringify({ channel })
      });
      notify('Test sent to Discord: ' + channel);
    } catch (error) {
      notify('Discord test failed: ' + error.message);
    } finally {
      await loadDiscordStatus();
      button.disabled = false;
    }
  }

  async function loadAccounts() {
    if (!site.admin) return;
    try {
      const data = await request('/api/accounts');
      site.accounts = data.accounts || [];
      site.passwordRequests = data.password_requests || [];
      renderAccounts();
    } catch (error) { notify(error.message); }
  }

  function renderAccounts() {
    const accounts = site.accounts || [];
    for (const status of ['pending', 'approved', 'rejected']) {
      one('#accounts-' + status).textContent = accounts.filter(item => item.status === status).length;
    }
    const pending = accounts.filter(item => item.status === 'pending').length;
    one('#accounts-badge').hidden = pending === 0;
    one('#accounts-badge').textContent = pending > 99 ? '99+' : String(pending);
    const query = one('#accounts-search').value.trim().toLowerCase();
    const filter = one('#accounts-filter').value;
    const visible = accounts.filter(item => (!filter || item.status === filter) &&
      [item.username, item.player_name, item.email].some(v => v.toLowerCase().includes(query)));
    one('#accounts-list').innerHTML = visible.map(item => {
      const actions =
        (item.status !== 'approved' ? '<button type="button" class="account-approve" data-account-approve="' + item.id + '">Accept</button>' : '') +
        (item.status !== 'rejected' ? '<button type="button" class="account-reject" data-account-reject="' + item.id + '">Reject</button>' : '') +
        '<button type="button" class="account-edit" data-account-edit="' + item.id + '">Edit</button>' +
        '<button type="button" class="account-delete" data-account-delete="' + item.id + '">Delete</button>';
      return '<article class="account-row status-' + item.status + '"><div class="account-row-info"><button class="account-detail-open" type="button" data-account-detail="' + item.id + '">' + escapeHtml(item.player_name) + '</button>' +
        '<span>@' + escapeHtml(item.username) + ' · ' + escapeHtml(item.email) +
        '</span><span>Registered ' + escapeHtml(item.created_at.slice(0, 10)) + '</span>' +
        (item.review_message ? '<p>Review note: ' + escapeHtml(item.review_message) + '</p>' : '') +
        '</div><div class="account-actions"><span class="account-pill ' + item.status + '">' + item.status +
        '</span>' + actions + '</div></article>';
    }).join('') || '<p class="rss-empty-spending">No matching accounts.</p>';
    renderPasswordRequests();
  }

  function accountDetails(id) {
    if (!site.admin) return;
    const member = (site.accounts || []).find(item => item.id === id);
    if (!member) return;
    one('#account-detail-player').textContent = member.player_name;
    one('#account-detail-username').textContent = member.username;
    one('#account-detail-email').textContent = member.email;
    one('#account-detail-status').textContent = member.status;
    one('#account-detail-created').textContent = member.created_at;
    one('#account-detail-review').textContent = member.review_message || '—';
    openDialog('account-detail-dialog');
  }

  function renderPasswordRequests() {
    const requests = site.passwordRequests || [];
    const pending = requests.filter(item => item.status === 'pending').length;
    const accountPending = (site.accounts || []).filter(item => item.status === 'pending').length;
    const totalPending = pending + accountPending;
    one('#accounts-badge').hidden = totalPending === 0;
    one('#accounts-badge').textContent = totalPending > 99 ? '99+' : String(totalPending);
    one('#password-requests-badge').hidden = pending === 0;
    one('#password-requests-badge').textContent = pending > 99 ? '99+' : String(pending);
    one('#password-requests-list').innerHTML = requests.map(item => {
      const actions = item.status === 'pending' ?
        '<button class="account-approve" type="button" data-reset-approve="' + item.id + '">Approve change</button>' +
        '<button class="account-reject" type="button" data-reset-reject="' + item.id + '">Reject</button>' : '';
      const date = new Date(item.created_at * 1000).toISOString().slice(0, 16).replace('T', ' ');
      return '<article class="account-row"><div class="account-row-info"><strong>' +
        escapeHtml(item.player_name) + '</strong><span>@' + escapeHtml(item.username) +
        ' · ' + escapeHtml(item.email) + '</span><span>Requested: ' + date + ' UTC</span>' +
        (item.review_message ? '<p>Reason: ' + escapeHtml(item.review_message) + '</p>' : '') +
        '</div><div class="account-actions"><span class="account-pill ' + item.status + '">' +
        escapeHtml(item.status) + '</span>' + actions + '</div></article>';
    }).join('') || '<p class="rss-empty-spending">No password change requests.</p>';
  }

  function approvePasswordChange(id) {
    if (!site.admin) return;
    const entry = (site.passwordRequests || []).find(item => item.id === id && item.status === 'pending');
    if (!entry) return;
    one('#reset-approve-id').value = String(id);
    one('#reset-approve-player').textContent = 'Player: ' + entry.player_name + ' (@' + entry.username + ')';
    one('#reset-approve-error').textContent = '';
    openDialog('reset-approve-dialog');
  }

  async function submitResetApproval(event) {
    event.preventDefault();
    if (!site.admin) return;
    const button = one('#reset-approve-form button[type="submit"]');
    button.disabled = true;
    try {
      const result = await request('/api/password/requests/' + one('#reset-approve-id').value, {
        method: 'PATCH', body: JSON.stringify({ decision: 'approved' })
      });
      one('#reset-approve-dialog').close();
      one('#admin-reset-code').value = result.reset_code;
      openDialog('reset-code-dialog');
      await loadAccounts();
    } catch (error) {
      one('#reset-approve-error').textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }

  function rejectPasswordChange(id) {
    if (!site.admin) return;
    one('#reset-review-id').value = String(id);
    one('#reset-review-message').value = '';
    one('#reset-review-error').textContent = '';
    openDialog('reset-review-dialog');
  }

  async function submitPasswordReview(event) {
    event.preventDefault();
    try {
      await request('/api/password/requests/' + one('#reset-review-id').value, {
        method: 'PATCH', body: JSON.stringify({
          decision: 'rejected', message: one('#reset-review-message').value.trim()
        })
      });
      one('#reset-review-dialog').close();
      await loadAccounts();
      notify('Password change request rejected.');
    } catch (error) { one('#reset-review-error').textContent = error.message; }
  }

  function recoveryView(view) {
    one('#member-login-form').classList.toggle('hidden', view !== 'login');
    one('#member-register-form').classList.add('hidden');
    one('#password-request-form').classList.toggle('hidden', view !== 'request');
    one('#password-complete-form').classList.toggle('hidden', view !== 'complete');
    one('.auth-tabs').classList.toggle('hidden', view !== 'login');
    one('#auth-heading').textContent = view === 'request' ? 'Forgot your password?' :
      view === 'complete' ? 'Set a new password' : 'Welcome back';
    one('#auth-subheading').textContent = view === 'request' ?
      'Submit a password change request to your alliance administrator.' :
      view === 'complete' ? 'Enter the one-time reset code provided by your administrator.' :
      'Sign in to continue to Saints and Sinners.';
    authMessage('');
  }

  async function requestPasswordChange(event) {
    event.preventDefault();
    try {
      const result = await request('/api/password/request', {
        method: 'POST', body: JSON.stringify({ identifier: one('#reset-identifier').value })
      });
      authMessage(result.message + ' Once approved, request your one-time code from an administrator.', true);
    } catch (error) { authMessage(error.message); }
  }

  async function completePasswordChange(event) {
    event.preventDefault();
    try {
      const result = await request('/api/password/complete', {
        method: 'POST', body: JSON.stringify({
          username: one('#reset-username').value,
          code: one('#reset-code').value.trim(),
          new_password: one('#reset-new-password').value
        })
      });
      one('#password-complete-form').reset();
      recoveryView('login');
      authMessage(result.message, true);
    } catch (error) { authMessage(error.message); }
  }

  function editAccount(id) {
    if (!site.admin) return;
    const member = (site.accounts || []).find(item => item.id === id);
    if (!member) return;
    one('#account-edit-id').value = String(member.id);
    one('#account-edit-username').value = member.username;
    one('#account-edit-player').value = member.player_name;
    one('#account-edit-email').value = member.email;
    one('#account-edit-error').textContent = '';
    openDialog('account-edit-dialog');
  }

  async function saveAccountEdits(event) {
    event.preventDefault();
    if (!site.admin) return;
    const id = Number(one('#account-edit-id').value);
    try {
      await request('/api/accounts/' + id, { method: 'PUT', body: JSON.stringify({
        username: one('#account-edit-username').value.trim(),
        player_name: one('#account-edit-player').value.trim(),
        email: one('#account-edit-email').value.trim()
      }) });
      one('#account-edit-dialog').close();
      await loadAccounts();
      notify('Player account updated.');
    } catch (error) { one('#account-edit-error').textContent = error.message; }
  }

  async function deleteAccount(id) {
    if (!site.admin) return;
    const member = (site.accounts || []).find(item => item.id === id);
    if (!member || !await confirmAction({
      title: 'Delete player account?',
      message: 'Permanently delete @' + member.username + '? Their active sessions and password reset requests will also be removed. This cannot be undone.',
      buttonLabel: 'Delete account'
    })) return;
    try {
      await request('/api/accounts/' + id, { method: 'DELETE' });
      await loadAccounts();
      notify('Account deleted permanently.');
    } catch (error) { notify(error.message); }
  }

  async function approveAccount(id) {
    try {
      await request('/api/accounts/' + id, { method: 'PATCH', body: JSON.stringify({ status: 'approved' }) });
      await loadAccounts();
      notify('Account approved.');
    } catch (error) { notify(error.message); }
  }

  function rejectAccount(id) {
    const item = (site.accounts || []).find(account => account.id === id);
    if (!item) return;
    one('#review-id').value = String(id);
    one('#review-player').textContent = 'Player: ' + item.player_name + ' (@' + item.username + ')';
    one('#review-message').value = '';
    one('#review-error').textContent = '';
    openDialog('review-dialog');
  }

  async function submitReview(event) {
    event.preventDefault();
    const id = Number(one('#review-id').value);
    const message = one('#review-message').value.trim();
    try {
      await request('/api/accounts/' + id, { method: 'PATCH', body: JSON.stringify({ status: 'rejected', message }) });
      one('#review-dialog').close();
      await loadAccounts();
      notify('Account rejected. Reason saved.');
    } catch (error) { one('#review-error').textContent = error.message; }
  }

  all('[data-auth-tab]').forEach(node => node.addEventListener('click', () => authTab(node.dataset.authTab)));
  one('#member-login-form').addEventListener('submit', playerLogin);
  one('#member-register-form').addEventListener('submit', registerPlayer);
  one('#auth-admin').addEventListener('click', () => openDialog('login-dialog'));
  one('#accounts-search').addEventListener('input', renderAccounts);
  one('#accounts-filter').addEventListener('change', renderAccounts);
  one('#account-edit-form').addEventListener('submit', saveAccountEdits);
  one('#password-requests-refresh').addEventListener('click', loadAccounts);
  one('#discord-status-refresh').addEventListener('click', loadDiscordStatus);
  one('#discord-status-grid').addEventListener('click', event => {
    const button = event.target.closest('[data-test-discord]');
    if (button) testDiscord(button.dataset.testDiscord, button);
  });
  one('#review-form').addEventListener('submit', submitReview);
  one('#forgot-password').addEventListener('click', () => recoveryView('request'));
  one('#have-reset-code').addEventListener('click', () => recoveryView('complete'));
  all('[data-auth-back]').forEach(node => node.addEventListener('click', () => recoveryView('login')));
  one('#password-request-form').addEventListener('submit', requestPasswordChange);
  one('#password-complete-form').addEventListener('submit', completePasswordChange);
  one('#reset-review-form').addEventListener('submit', submitPasswordReview);
  one('#reset-approve-form').addEventListener('submit', submitResetApproval);
  one('#copy-reset-code').addEventListener('click', () => {
    const value = one('#admin-reset-code').value;
    if (value) navigator.clipboard.writeText(value).then(() => notify('Reset code copied. Share privately.'))
      .catch(() => { one('#admin-reset-code').select(); notify('Select the code and copy it manually.'); });
  });
  one('#reset-code-dialog').addEventListener('close', () => { one('#admin-reset-code').value = ''; });

  document.addEventListener('click', event => {
    const accountDetail = event.target.closest('[data-account-detail]');
    if (accountDetail && site.admin) accountDetails(Number(accountDetail.dataset.accountDetail));
    const resetApprove = event.target.closest('[data-reset-approve]');
    if (resetApprove && site.admin) approvePasswordChange(Number(resetApprove.dataset.resetApprove));
    const resetReject = event.target.closest('[data-reset-reject]');
    if (resetReject && site.admin) rejectPasswordChange(Number(resetReject.dataset.resetReject));
    const editAccountButton = event.target.closest('[data-account-edit]');
    if (editAccountButton && site.admin) editAccount(Number(editAccountButton.dataset.accountEdit));
    const deleteAccountButton = event.target.closest('[data-account-delete]');
    if (deleteAccountButton && site.admin) deleteAccount(Number(deleteAccountButton.dataset.accountDelete));
    const approve = event.target.closest('[data-account-approve]');
    if (approve && site.admin) approveAccount(Number(approve.dataset.accountApprove));
    const reject = event.target.closest('[data-account-reject]');
    if (reject && site.admin) rejectAccount(Number(reject.dataset.accountReject));
    const nav = event.target.closest('[data-view]');
    if (nav) switchPage(nav.dataset.view);
    const create = event.target.closest('[data-create]');
    if (create) edit(create.dataset.create);
    const editButton = event.target.closest('[data-edit]');
    if (editButton) {
      const item = site.entries.find(row => row.id === Number(editButton.dataset.edit));
      if (item) edit(item.kind, item.id);
    }
    const row = event.target.closest('.event-row[data-id]');
    if (row) inspect(Number(row.dataset.id));
    const spendDelete = event.target.closest('[data-spend-delete]');
    if (spendDelete) deleteSpending(Number(spendDelete.dataset.spendDelete));
    const close = event.target.closest('[data-close]');
    if (close) one('#' + close.dataset.close).close();
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Enter' && event.target.matches('.event-row[data-id]')) {
      event.preventDefault();
      inspect(Number(event.target.dataset.id));
    }
  });

  all('#events-search, #events-category, #events-status, #alliance-search, #alliance-status').forEach(node => {
    node.addEventListener(node.tagName === 'INPUT' ? 'input' : 'change', render);
  });

  one('#enter-site').addEventListener('click', () => {
    const button = one('#enter-site');
    if (button.disabled) return;
    button.disabled = true;
    sessionStorage.setItem('sas-entered', '1');
    const entrance = one('#entrance');
    const website = one('#website');
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
    entrance.classList.add('leave');
    setTimeout(() => {
      entrance.classList.add('hidden');
      website.classList.remove('hidden');
      website.classList.add('welcome-arrived');
      website.addEventListener('animationend', () => website.classList.remove('welcome-arrived'), { once: true });
    }, reducedMotion ? 0 : 540);
  });
  one('#admin-toggle').addEventListener('click', toggleAdmin);
  one('#login-form').addEventListener('submit', login);
  one('#entry-form').addEventListener('submit', saveEntry);
  one('#entry-delete').addEventListener('click', deleteEntry);
  one('#download-calendar').addEventListener('click', downloadCalendar);
  one('#detail-edit').addEventListener('click', () => {
    const item = site.entries.find(entry => entry.id === site.selected);
    if (item) { one('#detail-dialog').close(); edit(item.kind, item.id); }
  });
  one('#rss-edit').addEventListener('click', () => {
    const data = rssTools.normalize(site.rss || {
      tech_plan: site.settings.tech_plan || '',
      legacy_hour: site.settings.rss_hour || ''
    });
    site.rssFormRevision = data.updated_at;
    site.rssFormInitialBalances = {};
    for (const key of rssTools.resources) {
      const item = data.resources[key];
      const current = rssTools.estimateBalance(item, data.as_of, Date.now() + site.clockOffset);
      one('#rss-stock-' + key).value = current === null ? '' : Math.round(current * 100) / 100;
      one('#rss-income-' + key).value = item.per_hour === null ? '' : item.per_hour;
      one('#rss-cap-' + key).value = item.limit;
      site.rssFormInitialBalances[key] = one('#rss-stock-' + key).value;
    }
    for (const key of rssTools.buffs) {
      one('#rss-buff-input-' + key).value = data.buffs[key] === null ? '' : data.buffs[key];
    }
    one('#rss-tech-title-input').value = data.tech_name;
    one('#rss-tech-stage-input').value = data.tech_stage;
    one('#rss-tech-notes-input').value = data.tech_plan;
    const remaining = rssTools.remainingSeconds(data.tech_ends_at, Date.now() + site.clockOffset);
    one('#rss-tech-remaining-input').value = remaining === null ? '' : rssTools.formatDuration(remaining);
    site.rssFormInitialRemaining = one('#rss-tech-remaining-input').value;
    one('#rss-territory-input').value = data.territory_plan;
    one('#rss-error').textContent = '';
    openDialog('rss-dialog');
  });
  one('#rss-form').addEventListener('submit', saveRss);
  one('#rss-spend-open').addEventListener('click', () => {
    one('#spend-form').reset();
    one('#spend-at').value = new Date(Date.now() + site.clockOffset).toISOString().slice(0, 19).replace('T', ' ');
    one('#spend-error').textContent = '';
    openDialog('spend-dialog');
  });
  one('#spend-form').addEventListener('submit', recordSpending);
  all('dialog').forEach(node => node.addEventListener('click', event => {
    if (event.target === node) node.close();
  }));
  updateClock();
  setInterval(() => {
    updateClock();
    if (!document.hidden) {
      refreshCountdowns();
      refreshResearchCountdown();
      if (site.page === 'rss') refreshResourceBalances();
    }
  }, 1000);
  one('#entrance').classList.add('hidden');
  window.SasPlannerUI?.init();
  window.SasReferenceUI?.init();
  const page = location.hash.slice(1);
  switchPage(labels[page] ? page : 'events');
  request('/api/session').then(async session => {
    site.member = !!session.approved && !session.admin;
    setAdmin(!!session.admin, session.csrf);
    adminLastInteraction = Date.now();
    adminActivityLastSent = adminLastInteraction;
    if (session.admin || session.approved) {
      window.SasPlannerUI?.setIdentity(session.username || 'admin');
      if (site.member) {
        const result = await request('/api/reads');
        readState = result.seen || { events: {}, alliance: {}, rss: '', updates: {}, announcements: {} };
      }
      unlockSite();
      await reload();
      if (site.admin) loadAccounts();
    } else {
      window.location.replace('/');
    }
  }).catch(() => window.location.replace('/'));
  // Keep account approvals and password requests visible without manually refreshing.
  setInterval(() => {
    if (site.admin && !document.hidden) loadAccounts();
  }, 15000);
  setInterval(async () => {
    if (site.admin && Date.now() - adminLastInteraction >= ADMIN_IDLE_MS) {
      adminExpired();
      return;
    }
    if (document.hidden || (!site.admin && !site.member)) return;
    try {
      const session = await request('/api/session');
      if (!session.admin && !session.approved) {
        site.entries = []; site.accounts = []; site.rss = null;
        site.member = false; setAdmin(false);
        window.location.replace('/');
        return;
      }
      await reload();
      if (site.admin) await loadAccounts();
    } catch (_) {}
  }, 60000);
})();
