(() => {
  const one = selector => document.querySelector(selector);
  const all = selector => [...document.querySelectorAll(selector)];
  const site = { entries: [], settings: {}, admin: false, csrf: null, page: 'events', selected: null };
  const labels = { events: 'Events', alliance: 'Alliance Events', rss: 'Alliance RSS', updates: 'Website Updates', announcements: 'HR Announcements' };
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
  const toTime = value => new Date(value.replace(' ', 'T') + 'Z').getTime();
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
    const now = Date.now();
    if (toTime(item.end_utc) <= now) return 'ended';
    return toTime(item.start_utc) <= now ? 'active' : 'upcoming';
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
        '<td>' + statusTag(status(item)) + '</td></tr>';
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
    const value = site.settings.rss_hour || '';
    const parsed = Number(value.replace(/[,\s]/g, ''));
    one('#rss-hour').textContent = value ? (Number.isFinite(parsed) ? parsed.toLocaleString('en-US') : value) : 'Not added yet';
    one('#rss-unit').textContent = 'Resources per hour';
    one('#tech-plan').textContent = site.settings.tech_plan || 'Our next technology plan has not been posted yet.';
  }

  function render() {
    eventRows('events');
    eventRows('alliance');
    posts('updates');
    posts('announcements');
    rss();
  }

  async function reload() {
    const data = await request('/api/state');
    site.entries = Array.isArray(data.entries) ? data.entries : [];
    site.settings = data.settings || {};
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
    const fields = [
      ['Category', item.category],
      ['Status', { active: 'In Progress', upcoming: 'Upcoming', ended: 'Ended' }[status(item)]],
      ['Start (UTC)', item.start_utc],
      ['End (UTC)', item.end_utc],
      ['Rewards', item.rewards || 'Not specified'],
      ['Details', item.details || 'No additional details']
    ];
    one('#detail-body').innerHTML = fields.map(([label, value]) =>
      '<div class="detail-item"><span>' + label + '</span><p>' + escapeHtml(value).replace(/\n/g, '<br>') + '</p></div>'
    ).join('');
    one('#detail-edit').hidden = !site.admin;
    openDialog('detail-dialog');
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
    try {
      await request('/api/rss', { method: 'PUT', body: JSON.stringify({
        rss_hour: one('#rss-value').value, tech_plan: one('#rss-tech').value
      }) });
      one('#rss-dialog').close();
      await reload();
      notify('Alliance RSS updated.');
    } catch (error) {
      one('#rss-error').textContent = error.message;
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
    sessionStorage.setItem('sas-entered', '1');
    one('#entrance').classList.add('leave');
    setTimeout(() => { one('#entrance').classList.add('hidden'); one('#website').classList.remove('hidden'); }, 400);
  });
  one('#admin-toggle').addEventListener('click', toggleAdmin);
  one('#login-form').addEventListener('submit', login);
  one('#entry-form').addEventListener('submit', saveEntry);
  one('#entry-delete').addEventListener('click', deleteEntry);
  one('#detail-edit').addEventListener('click', () => {
    const item = site.entries.find(entry => entry.id === site.selected);
    if (item) { one('#detail-dialog').close(); edit(item.kind, item.id); }
  });
  one('#rss-edit').addEventListener('click', () => {
    one('#rss-value').value = site.settings.rss_hour || '';
    one('#rss-tech').value = site.settings.tech_plan || '';
    one('#rss-error').textContent = '';
    openDialog('rss-dialog');
  });
  one('#rss-form').addEventListener('submit', saveRss);
  all('dialog').forEach(node => node.addEventListener('click', event => {
    if (event.target === node) node.close();
  }));
  updateClock();
  setInterval(updateClock, 1000);
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
    render();
  }).catch(() => notify('Unable to load website data. Please refresh.'));
  setInterval(() => { if (!document.hidden) reload().catch(() => {}); }, 60000);
})();
