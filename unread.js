(function (root) {
  const sections = ['events', 'alliance', 'rss', 'updates', 'announcements'];

  function snapshot(entries = [], rss = {}) {
    const state = { events: {}, alliance: {}, rss: '', updates: {}, announcements: {} };
    for (const item of entries) {
      if (!item || item.kind === 'rss' || !sections.includes(item.kind)) continue;
      if (!item.id) continue;
      state[item.kind][String(item.id)] = item.modified_at || item.created_at || String(item.id);
    }
    state.rss = rss && typeof rss.updated_at === 'string' ? rss.updated_at : '';
    return state;
  }

  function count(current, seen) {
    const unread = {};
    for (const kind of sections) {
      if (kind === 'rss') {
        unread.rss = current.rss && current.rss !== seen.rss ? 1 : 0;
        continue;
      }
      const viewed = seen[kind] && typeof seen[kind] === 'object' ? seen[kind] : {};
      unread[kind] = Object.entries(current[kind] || {})
        .filter(([id, revision]) => revision !== viewed[id]).length;
    }
    return unread;
  }

  function acknowledge(seen, current, kind) {
    if (!sections.includes(kind)) return seen;
    return { ...seen, [kind]: kind === 'rss' ? current.rss : { ...current[kind] } };
  }

  const api = { sections, snapshot, count, acknowledge };
  root.SasUnread = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
