(() => {
  const one = selector => document.querySelector(selector);
  const rssTools = window.SasRss;
  const unreadTools = window.SasUnread;
  const readKey = 'sas-read-state-v1';
  const all = selector => [...document.querySelectorAll(selector)];
  const site = { entries: [], settings: {}, rss: null, admin: false, csrf: null, page: 'events', selected: null, loaded: false, clockOffset: 0 };
  const labels = { events: 'Events', alliance: 'Alliance Events', rss: 'Alliance RSS', updates: 'Website Updates', announcements: 'HR Announcements' };
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
  const calendar = window.SasCalendar;
  const toTime = value => calendar.utcTime(value);
  const currentUtc = () => new Date().toISOString().slice(0, 19).replace('T', ' ');
  let toastTimer;

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
    all('.admin-only').forEach(node => { node.hidden = !isAdmin; });
    one('#admin-toggle').textContent = isAdmin ? 'Sign out' : 'Admin login';
  }

  let readState = null;

  try {
    const stored = JSON.parse(localStorage.getItem(readKey));
    if (stored && typeof stored === 'object' && !Array.isArray(stored)) readState = stored;
  } catch (_) {
    readState = null;
  }

  function storeReadState() {
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
      node.setAttribute('aria-label', count + ' new updates');
    });
  }

  function acknowledgePage(kind) {
    if (!site.loaded) return;
    if (!readState) readState = unreadSnapshot();
    readState = unreadTools.acknowledge(readState, unreadSnapshot(), kind);
    storeReadState();
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
    if (!labels[name]) return;
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
    all('[data-view]').forEach(node => {
      const selected = node.dataset.view === name;
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
      return '<tr class="event-row" tabindex="0" role="button" data-id="' + item.id + '" aria-label="View ' + escapeHtml(item.title) + ' details">' +
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
      one('#rss-amount-' + key).textContent = rssTools.formatAmount(data.resources[key].stored);
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
    const unassigned = data.legacy_hour.trim() &&
      rssTools.resources.every(key => data.resources[key].per_hour === null);
    const legacy = one('#rss-legacy-note');
    legacy.classList.toggle('hidden', !unassigned || !site.admin);
    if (unassigned) {
      legacy.textContent = 'Previously saved total rate: ' + data.legacy_hour +
        '/h. This value has been kept, but it cannot be assigned to individual resources automatically.';
    }
  }

  function render() {
    eventRows('events');
    eventRows('alliance');
    posts('updates');
    posts('announcements');
    rss();
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
    render();
  }

  function openDialog(id) {
    one('#' + id).showModal();
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
    if (!id || !confirm('Delete this entry permanently?')) return;
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
          per_hour: rssTools.readNumber(one('#rss-income-' + key).value, key + ' income per hour')
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
        territory_plan: one('#rss-territory-input').value
      };
      rssTools.parseDuration(payload.tech_remaining);
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
      setAdmin(true, data.csrf);
      one('#login-form').reset();
      one('#login-dialog').close();
      render();
      notify('Signed in.');
    } catch (error) {
      one('#login-error').textContent = error.message;
    }
  }

  async function toggleAdmin() {
    if (!site.admin) {
      openDialog('login-dialog');
      return;
    }
    try {
      await request('/api/logout', { method: 'POST', body: '{}' });
      setAdmin(false);
      render();
      notify('Signed out.');
    } catch (error) {
      notify(error.message);
    }
  }

  document.addEventListener('click', event => {
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
    for (const key of rssTools.resources) {
      const item = data.resources[key];
      one('#rss-stock-' + key).value = item.stored === null ? '' : item.stored;
      one('#rss-income-' + key).value = item.per_hour === null ? '' : item.per_hour;
    }
    for (const key of rssTools.buffs) {
      one('#rss-buff-input-' + key).value = data.buffs[key] === null ? '' : data.buffs[key];
    }
    one('#rss-tech-title-input').value = data.tech_name;
    one('#rss-tech-stage-input').value = data.tech_stage;
    one('#rss-tech-notes-input').value = data.tech_plan;
    const remaining = rssTools.remainingSeconds(data.tech_ends_at, Date.now() + site.clockOffset);
    one('#rss-tech-remaining-input').value = remaining === null ? '' : rssTools.formatDuration(remaining);
    one('#rss-territory-input').value = data.territory_plan;
    one('#rss-error').textContent = '';
    openDialog('rss-dialog');
  });
  one('#rss-form').addEventListener('submit', saveRss);
  all('dialog').forEach(node => node.addEventListener('click', event => {
    if (event.target === node) node.close();
  }));
  updateClock();
  setInterval(() => {
    updateClock();
    if (!document.hidden) {
      refreshCountdowns();
      refreshResearchCountdown();
    }
  }, 1000);
  if (sessionStorage.getItem('sas-entered') === '1') {
    one('#entrance').classList.add('hidden');
    one('#website').classList.remove('hidden');
  }
  const page = location.hash.slice(1);
  switchPage(labels[page] ? page : 'events');
  Promise.all([request('/api/session'), request('/api/state')]).then(([session, data]) => {
    setAdmin(!!session.admin, session.csrf);
    site.entries = Array.isArray(data.entries) ? data.entries : [];
    site.settings = data.settings || {};
    site.rss = data.rss || null;
    setClockOffset(data.utc);
    site.loaded = true;
    acknowledgePage(site.page);
    render();
  }).catch(() => notify('Unable to load website data. Please refresh.'));
  setInterval(() => { if (!document.hidden) reload().catch(() => {}); }, 60000);
})();
