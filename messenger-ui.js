/* SaS Messenger: approved-member private messages and alliance chat. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let csrf = '', identity = '', contacts = [], activePeer = '', shownIds = '',
    currentPage = false, running = false, busy = false, inFlight = false, listFlight = false,
    lastNotify = 0, selectedGroupPlayers = new Set();
  const avatar = item => item.group ? (item.id==='alliance'?'SaS':'GR') :
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
      (item.id==='alliance'?' messenger-alliance-pinned':'')+
      (item.self?' messenger-own-profile':'')+
      '" '+(item.self?'disabled aria-label="Your profile"':'data-messenger-peer="'+escape(item.id)+'"')+' role="listitem">'+
      '<span class="messenger-avatar'+(item.group?' is-group':'')+'">'+escape(avatar(item))+'</span>'+
      '<span class="messenger-contact-details"><strong>'+escape(item.username)+
      (item.id==='alliance'?' <span class="messenger-group-pin">PINNED</span>':'')+'</strong>'+
      '<small>'+escape(item.self ? 'Your profile · '+(item.player_name||'') :
        (item.last_message || (item.group ? 'Group chat' : (item.player_name||'Say hello'))))+'</small></span>'+
      '<span class="messenger-contact-meta"><small>'+escape(showTime(item.last_at))+'</small>'+
      (item.unread ? '<span class="messenger-contact-badge">'+Math.min(item.unread,99)+(item.unread>99?'+':'')+'</span>':'')+
      '</span></button>';
  }
  function renderContacts() {
    const filter = $('messenger-search').value.trim().toLowerCase();
    const filtered = contacts.filter(c =>
      c.username.toLowerCase().includes(filter) ||
      (c.player_name||'').toLowerCase().includes(filter));
    const groups=filtered.filter(c=>c.group);
    const players=filtered.filter(c=>!c.group);
    const section=(label,items)=>items.length?
      '<div class="messenger-section-heading">'+label+' <span>'+items.length+'</span></div>'+
        items.map(contactMarkup).join(''):'';
    const content=section('GROUP CHATS',groups)+section('PLAYERS',players);
    $('messenger-contact-list').innerHTML = content || '<p class="messenger-loading">No approved players found. Players must be approved in SaS – Accounts before they appear here.</p>';

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
    $('messenger-active-detail').textContent=contact.group ? (contact.id==='alliance'?'All approved SaS members':'Private group · '+contact.player_name) :
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
        ((activePeer==='alliance'||activePeer.startsWith('group:')) ? '<strong>'+escape(mine?'You':sender)+'</strong>' : '')+
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
  function approvedPlayers() {
    return contacts.filter(c=>!c.group && !c.self && c.id!=='admin' && c.id.startsWith('member:'));
  }
  function renderGroupPicker() {
    const search=$('messenger-group-player-search').value.trim().toLowerCase();
    const eligible=approvedPlayers().filter(p=>p.username.toLowerCase().includes(search) ||
      (p.player_name||'').toLowerCase().includes(search));
    $('messenger-group-players').innerHTML=eligible.length?eligible.map(p=>
      '<label class="messenger-player-option"><input type="checkbox" data-group-player="'+escape(p.id)+'"'+
      (selectedGroupPlayers.has(p.id)?' checked':'')+'><span class="messenger-avatar">'+escape(avatar(p))+'</span>'+
      '<span><strong>'+escape(p.username)+'</strong><small>'+escape(p.player_name||'')+'</small></span></label>'
    ).join(''):'<p class="messenger-loading">No matching approved players.</p>';
    $('messenger-group-selected').textContent=selectedGroupPlayers.size+' player(s) selected';
  }
  function openGroupDialog(){
    selectedGroupPlayers=new Set();
    $('messenger-group-form').reset();
    $('messenger-group-error').textContent='';
    renderGroupPicker();
    $('messenger-group-dialog').showModal();
  }
  async function createGroup(event){
    event.preventDefault();
    const button=$('messenger-group-form').querySelector('button[type="submit"]');
    button.disabled=true;
    try{
      const result=await api('/api/messenger/groups',{method:'POST',body:JSON.stringify({
        name:$('messenger-group-name').value,
        members:[...selectedGroupPlayers]
      })});
      $('messenger-group-dialog').close();
      // Fetch this player's new membership immediately even if a background list poll is running.
      const fresh = await api('/api/messenger');
      identity = fresh.me;
      contacts = Array.isArray(fresh.contacts) ? fresh.contacts : [];
      renderContacts();
      await openPeer(result.id);
    }catch(e){$('messenger-group-error').textContent=e.message;}
    finally{button.disabled=false;}
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
    $('messenger-create-group').addEventListener('click',openGroupDialog);
    $('messenger-group-player-search').addEventListener('input',renderGroupPicker);
    $('messenger-group-players').addEventListener('change', event=>{
      const checkbox=event.target.closest('[data-group-player]');
      if (!checkbox) return;
      if (checkbox.checked) selectedGroupPlayers.add(checkbox.dataset.groupPlayer);
      else selectedGroupPlayers.delete(checkbox.dataset.groupPlayer);
      $('messenger-group-selected').textContent=selectedGroupPlayers.size+' player(s) selected';
    });
    $('messenger-group-form').addEventListener('submit',createGroup);
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
