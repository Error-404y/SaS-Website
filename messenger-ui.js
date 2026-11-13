/* SaS Messenger: approved-member private messages and alliance chat. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let csrf = '', identity = '', contacts = [], activePeer = '', shownIds = '',
    currentPage = false, running = false, busy = false, inFlight = false, listFlight = false,
    lastNotify = 0;
  const avatar = item => item.group ? 'SaS' :
    String(item.username || '??').slice(0, 2).toUpperCase();
  const showTime = time => {
    if (!time) return '';
    const date = new Date(String(time).replace(' ','T') + 'Z');
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',timeZone:'UTC'}) + ' UTC';
  };
  const totalUnread = () => contacts.reduce((sum, c) => sum + (Number(c.unread)||0),0);
  async function api(path, options={}) {
    const response = await fetch(path, {
      credentials:'same-origin', ...options,
      headers:{'Content-Type':'application/json',
        ...(options.method && options.method!=='GET' ? {'X-CSRF-Token':csrf} : {}),
        ...(options.headers||{})}
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Messaging is unavailable.');
    return data;
  }
  function error(message='') {
    const node = $('messenger-error');
    node.hidden = !message;
    node.textContent = message;
  }
  function badges() {
    const count = totalUnread();
    for(const id of ['messenger-nav-unread','messenger-list-unread']){
      const node=$(id);
      node.hidden = count === 0;
      node.textContent = count > 99 ? '99+' : String(count);
    }
    const page = $('messenger-page-unread');
    page.hidden = count===0;
    page.textContent = count+' unread';
    const nav = document.querySelector('.sidebar-nav [data-view="messenger"]');
    if (nav) nav.classList.toggle('messenger-nav-highlight',count>0);
  }
  function contactMarkup(item) {
    return '<button type="button" class="messenger-contact'+(item.id===activePeer?' is-active':'')+
      '" data-messenger-peer="'+escape(item.id)+'" role="listitem">'+
      '<span class="messenger-avatar'+(item.group?' is-group':'')+'">'+escape(avatar(item))+'</span>'+
      '<span class="messenger-contact-details"><strong>'+escape(item.username)+'</strong>'+
      '<small>'+escape(item.last_message || (item.group ? 'Alliance group chat' : (item.player_name||'Say hello')))+'</small></span>'+
      '<span class="messenger-contact-meta"><small>'+escape(showTime(item.last_at))+'</small>'+
      (item.unread ? '<span class="messenger-contact-badge">'+Math.min(item.unread,99)+(item.unread>99?'+':'')+'</span>':'')+
      '</span></button>';
  }
  function renderContacts() {
    const filter = $('messenger-search').value.trim().toLowerCase();
    const filtered = contacts.filter(c =>
      c.username.toLowerCase().includes(filter) ||
      (c.player_name||'').toLowerCase().includes(filter));
    $('messenger-contact-list').innerHTML = filtered.length ? filtered.map(contactMarkup).join('') :
      '<p class="messenger-loading">No players found.</p>';
    badges();
  }
  async function loadList() {
    if (!running || listFlight || document.hidden) return;
    listFlight=true;
    try {
      const data = await api('/api/messenger');
      if (!running) return;
      identity = data.me;
      contacts = Array.isArray(data.contacts) ? data.contacts : [];
      if (activePeer && !contacts.some(c=>c.id===activePeer)) {
        activePeer = '';
        $('messenger-shell').classList.remove('chat-open');
      }
      renderContacts();
    } catch (e) {
      if (currentPage) error(e.message);
    } finally {listFlight=false;}
  }
  async function openPeer(peer) {
    if (!running || !contacts.some(c=>c.id===peer)) return;
    activePeer=peer;
    shownIds='';
    error();
    const contact=contacts.find(c=>c.id===peer);
    $('messenger-active-name').textContent=contact.username;
    $('messenger-active-detail').textContent=contact.group ? 'Alliance group chat' :
      (contact.player_name || 'Private conversation');
    $('messenger-active-avatar').textContent=avatar(contact);
    $('messenger-history').innerHTML='<p class="messenger-loading">Loading messages…</p>';
    $('messenger-message').disabled=false;
    $('messenger-send').disabled=false;
    $('messenger-shell').classList.add('chat-open');
    renderContacts();
    await loadMessages(true);
  }
  function messagesMarkup(messages) {
    if (!messages.length) return '<div class="messenger-empty">No messages yet. Say hello!</div>';
    return messages.map(msg => {
      const mine = msg.sender_key===identity;
      const sender = msg.sender_key==='admin' ? 'SaS Admin' :
        (contacts.find(c=>c.id===msg.sender_key)?.username || (mine ? 'You' : 'Former member'));
      return '<div class="messenger-line'+(mine?' mine':'')+'">'+
        '<div class="messenger-bubble">'+
        (activePeer==='alliance' ? '<strong>'+escape(mine?'You':sender)+'</strong>' : '')+
        '<span class="messenger-bubble-text">'+escape(msg.body)+'</span>'+
        '<time>'+escape(showTime(msg.created_at))+'</time></div></div>';
    }).join('');
  }
  async function loadMessages(force=false) {
    if (!running || !activePeer || !currentPage || inFlight || document.hidden) return;
    const targetPeer=activePeer;
    inFlight=true;
    try {
      const result=await api('/api/messenger/messages?peer='+encodeURIComponent(targetPeer));
      if (!running || activePeer!==targetPeer || !currentPage) return;
      const messages=result.messages||[];
      const key=messages.map(m=>m.id).join(',');
      if (force || key!==shownIds) {
        const holder=$('messenger-history');
        const stickToBottom=force || holder.scrollHeight-holder.scrollTop-holder.clientHeight<90;
        holder.innerHTML=messagesMarkup(messages);
        shownIds=key;
        if (stickToBottom) holder.scrollTop=holder.scrollHeight;
      }
      const contact=contacts.find(c=>c.id===targetPeer);
      if (contact?.unread>0 || force) {
        await api('/api/messenger/read',{method:'POST',body:JSON.stringify({peer:targetPeer})});
        if (contact) contact.unread=0;
        renderContacts();
      }
    } catch(e){ if (activePeer===targetPeer) error(e.message); }
    finally{inFlight=false;}
  }
  async function send(event){
    event.preventDefault();
    if (!running || !activePeer || busy) return;
    const input=$('messenger-message'), body=input.value.trim();
    if (!body) return;
    busy=true;
    $('messenger-send').disabled=true;
    error();
    try {
      await api('/api/messenger/messages',{method:'POST',
        body:JSON.stringify({peer:activePeer,body})});
      input.value='';
      shownIds='';
      await loadMessages(true);
      await loadList();
      input.focus();
    } catch(e){error(e.message);}
    finally{busy=false;$('messenger-send').disabled=false;}
  }
  function start(token){
    if (!token) return;
    csrf=token;running=true;
    loadList();
  }
  function stop(){
    running=false;csrf='';identity='';activePeer='';contacts=[];shownIds='';
    $('messenger-shell').classList.remove('chat-open');
    $('messenger-message').disabled=true;
    $('messenger-send').disabled=true;
    $('messenger-history').innerHTML='<div class="messenger-empty">Choose a conversation to begin.</div>';
    renderContacts();
  }
  function onPage(name){
    currentPage=name==='messenger';
    if (currentPage && running) {
      loadList();
      if (activePeer) loadMessages();
    }
  }
  function init(){
    $('messenger-contact-list').addEventListener('click',event=>{
      const button=event.target.closest('[data-messenger-peer]');
      if (button) openPeer(button.dataset.messengerPeer);
    });
    $('messenger-search').addEventListener('input',renderContacts);
    $('messenger-compose').addEventListener('submit',send);
    $('messenger-back').addEventListener('click',()=>{
      $('messenger-shell').classList.remove('chat-open');
    });
    document.addEventListener('visibilitychange',()=>{
      if (!document.hidden && running) {
        loadList();
        if (currentPage) loadMessages();
      }
    });
    setInterval(()=>{
      if (!running || document.hidden) return;
      if (currentPage) loadMessages();
      if (Date.now()-lastNotify>=15000) {
        lastNotify=Date.now();loadList();
      }
    },5000);
  }
  window.SasMessenger={init,start,stop,onPage};
})();
