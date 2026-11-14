/* SaS Messenger: approved-member private messages and alliance chat. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let csrf = '', identity = '', contacts = [], activePeer = '', shownIds = '',
    currentPage = false, running = false, busy = false, loadingPeer = '', listFlight = false,
    lastNotify = 0, selectedGroupPlayers = new Set(), sessionGeneration = 0,
    olderMessages = [], historyHasMore = false, oldestBefore = null, loadingOlder = false,
    lastPresencePing = 0, presenceFlight = false;
  const avatar = item => item.group ? (item.id==='alliance'?'SaS':'GR') :
    String(item.username || '??').slice(0, 2).toUpperCase();
  const showTime = time => {
    if (!time) return '';
    const date = new Date(String(time).replace(' ','T') + 'Z');
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',timeZone:'UTC'}) + ' UTC';
  };
  const presenceText = item => {
    if (!item || item.group || item.self) return '';
    if (item.online) return 'Online';
    if (!item.last_seen_at) return 'Last seen unavailable';
    const when = new Date(Number(item.last_seen_at) * 1000);
    if (Number.isNaN(when.getTime())) return 'Last seen unavailable';
    const utc = date => date.toISOString().slice(0,10);
    const now = new Date();
    const yesterday = new Date(now.getTime()-86400000);
    const clock = when.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',timeZone:'UTC'});
    if (utc(when)===utc(now)) return 'Last seen today at '+clock+' UTC';
    if (utc(when)===utc(yesterday)) return 'Last seen yesterday at '+clock+' UTC';
    return 'Last seen '+when.toLocaleDateString([], {day:'numeric',month:'short',year:'numeric',timeZone:'UTC'})+' at '+clock+' UTC';
  };
  function updateActivePresence() {
    const item=contacts.find(c=>c.id===activePeer);
    if (!item || item.group || item.self) return;
    $('messenger-active-detail').textContent=presenceText(item);
    $('messenger-active-avatar').classList.toggle('is-online',Boolean(item.online));
  }
  async function pingPresence() {
    if (!running || document.hidden || presenceFlight) return;
    presenceFlight=true;
    lastPresencePing=Date.now();
    try { await api('/api/messenger/presence',{method:'POST',body:'{}'}); }
    catch (e) { /* Presence is optional; Messenger must remain usable. */ }
    finally { presenceFlight=false; }
  }
  // Keep a mobile chat within the *visible* viewport when Chrome's URL bar or
  // the on-screen keyboard changes size. CSS uses dvh as a safe fallback.
  function syncChatViewport(){
    const shell=$('messenger-shell');
    if (!shell) return;
    if (window.innerWidth>620 || !shell.classList.contains('chat-open')) {
      shell.style.removeProperty('--sas-visual-height');
      shell.style.removeProperty('--sas-visual-top');
      return;
    }
    const viewport=window.visualViewport;
    const height=viewport ? viewport.height : window.innerHeight;
    shell.style.setProperty('--sas-visual-height',Math.max(240,Math.round(height))+'px');
    shell.style.setProperty('--sas-visual-top',Math.round(viewport?.offsetTop||0)+'px');
  }
  const totalUnread = () => contacts.reduce((sum, c) => sum + (Number(c.unread)||0),0);
  async function api(path, options={}) {
    const makeRequest = async () => {
      const response = await fetch(path, {
        credentials:'same-origin', ...options,
        headers:{'Content-Type':'application/json',
          ...(options.method && options.method!=='GET' ? {'X-CSRF-Token':csrf} : {}),
          ...(options.headers||{})}
      });
      const data = await response.json().catch(() => ({}));
      return {response, data};
    };
    let {response, data} = await makeRequest();
    // A renewed session or restored mobile tab can leave the old CSRF token cached.
    // Refresh from the server only after it explicitly reports a token mismatch.
    if (response.status === 403 && /invalid csrf token/i.test(data.error||'')) {
      const sessionResponse = await fetch('/api/session',{credentials:'same-origin',cache:'no-store'});
      if (sessionResponse.ok) {
        const session = await sessionResponse.json();
        if (session.csrf && (session.admin || session.approved)) {
          csrf=session.csrf;
          ({response,data}=await makeRequest());
        }
      }
    }
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
      ((item.id==='alliance' && !item.joined)||item.invitation?' is-new-group':'')+
      (item.self?' messenger-own-profile':'')+
      '" data-messenger-peer="'+escape(item.id)+'" role="listitem">'+
      '<span class="messenger-avatar'+(item.group?' is-group':'')+(item.online && !item.self?' is-online':'')+'">'+escape(avatar(item))+'</span>'+
      '<span class="messenger-contact-details"><strong>'+escape(item.self?'Your Profile':item.username)+
      (item.id==='alliance'?' <span class="messenger-group-pin'+(!item.joined?' is-new':'')+'">'+(!item.joined?'NEW · JOIN':'PINNED')+'</span>':
      (item.invitation?' <span class="messenger-group-pin is-new">INVITED</span>':''))+'</strong>'+
      '<small>'+escape(item.self ? (item.last_message || (item.username+' · Private notes to yourself')) :
        (item.invitation ? item.invited_by+' has invited you to join a Group' :
        (item.id==='alliance' && !item.joined ? 'Join to see all messages' :
          (item.last_message || (item.group ? 'Group chat' : (item.player_name||'Say hello'))))))+'</small>'+
      (!item.group && !item.self && (item.online || item.last_seen_at) ?
        '<small class="messenger-presence-line'+(item.online?' online':'')+'">'+escape(presenceText(item))+'</small>' : '')+'</span>'+
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
    if (!running || listFlight) return;
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
      updateActivePresence();
    } catch (e) {
      if (currentPage) {
        error('Unable to load players: '+e.message);
        if (!contacts.length)
          $('messenger-contact-list').innerHTML='<p class="messenger-loading">Could not load players. Please try again.</p>';
      }
    } finally {listFlight=false;}
  }
  async function openPeer(peer) {
    if (!running || !contacts.some(c=>c.id===peer)) return;
    activePeer=peer;
    shownIds='';
    olderMessages=[];historyHasMore=false;oldestBefore=null;
    // A slow request for another conversation must never block this one.
    loadingPeer='';
    error();
    const contact=contacts.find(c=>c.id===peer);
    $('messenger-active-name').textContent=contact.self?'Your Profile':contact.username;
    $('messenger-active-detail').textContent=contact.self ? 'Notes to self · Private' :
      (contact.group ? (contact.id==='alliance'?'All joined SaS members':'Private group · '+contact.player_name) :
      (contact.player_name || 'Private conversation'));
    const locked=(peer==='alliance' && !contact.joined) || !!contact.invitation;
    $('messenger-alliance-lock').hidden=!locked;
    $('messenger-shell').classList.toggle('is-locked',locked);
    if (locked) {
      $('messenger-join-title').textContent=contact.username;
      $('messenger-join-description').textContent=contact.invitation
        ? contact.invited_by+' has invited you to join a Group. Join to see the messages.'
        : 'Join the group to read its messages and take part in the conversation.';
      $('messenger-join-alliance').textContent=contact.invitation?'Join Group':'Join SaS Group';
    }
    $('messenger-active-avatar').textContent=avatar(contact);
    $('messenger-active-avatar').classList.toggle('is-online',Boolean(contact.online && !contact.group && !contact.self));
    updateActivePresence();
    $('messenger-history').innerHTML='<p class="messenger-loading">Loading conversation…</p>';
    $('messenger-message').disabled=locked;
    $('messenger-send').disabled=locked;
    $('messenger-shell').classList.add('chat-open');
    document.body.classList.add('messenger-mobile-chat-open');
    syncChatViewport();
    renderContacts();
    if (locked) {
      $('messenger-history').innerHTML='<div class="messenger-empty">Join to unlock the conversation.</div>';
    } else {
      await loadMessages(true);
    }
  }
  function renderHistory(messages) {
    const holder=$('messenger-history');
    const combined=new Map([...olderMessages,...messages].map(m=>[m.id,m]));
    const allMessages=[...combined.values()].sort((a,b)=>a.id-b.id);
    holder.innerHTML=(historyHasMore ? '<button type="button" class="messenger-load-older" data-load-older="1">Load older messages</button>' : '')+
      messagesMarkup(allMessages);
  }
  async function loadOlder() {
    if (loadingOlder || !historyHasMore || !oldestBefore || !activePeer || !running) return;
    loadingOlder=true;
    const current=activePeer, generation=sessionGeneration;
    const holder=$('messenger-history'), beforeHeight=holder.scrollHeight;
    try {
      const result=await api('/api/messenger/messages?peer='+encodeURIComponent(current)+
        '&before='+encodeURIComponent(oldestBefore));
      if (current!==activePeer || generation!==sessionGeneration) return;
      const page=result.messages||[];
      olderMessages=[...page,...olderMessages];
      historyHasMore=Boolean(result.has_more);
      if (page.length) oldestBefore=page[0].id;
      const fresh=await api('/api/messenger/messages?peer='+encodeURIComponent(current));
      if (current!==activePeer || generation!==sessionGeneration) return;
      renderHistory(fresh.messages||[]);
      holder.scrollTop += holder.scrollHeight-beforeHeight;
    }catch(e){error('Could not load older messages: '+e.message);}
    finally{loadingOlder=false;}
  }
  function messagesMarkup(messages) {
    if (!messages.length) return '<div class="messenger-empty">No messages yet. '+(activePeer===identity?'Save a note to yourself!':'Say hello!')+'</div>';
    return messages.map(msg => {
      const mine = msg.sender_key===identity;
      const sender = msg.sender_key==='system' ? 'SaS Group' :
        (msg.sender_key==='admin' ? 'SaS Admin' :
        (contacts.find(c=>c.id===msg.sender_key)?.username || (mine ? 'You' : 'Former member')));
      if (msg.sender_key==='system') return '<div class="messenger-system-message">'+escape(msg.body)+'</div>';
      return '<div class="messenger-line'+(mine?' mine':'')+'">'+
        '<div class="messenger-bubble">'+
        ((activePeer==='alliance'||activePeer.startsWith('group:')) ? '<strong>'+escape(mine?'You':sender)+'</strong>' : '')+
        '<span class="messenger-bubble-text">'+escape(msg.body)+'</span>'+
        '<span class="messenger-bubble-footer"><time>'+escape(showTime(msg.created_at))+'</time>'+
        (mine && typeof msg.read==='boolean' ?
          '<span class="messenger-read-receipt'+(msg.read?' is-read':'')+'" aria-label="'+(msg.read?'Read':'Sent, not yet read')+'" title="'+(msg.read?'Read':'Sent, not yet read')+'">'+
          (msg.read ? '<svg viewBox="0 0 26 18" width="13" height="10" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M2 9l5 5L17 3"/><path d="M10 9l5 5L25 3"/></svg>' :
          '<svg viewBox="0 0 18 18" width="12" height="10" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M2 9l5 5L16 3"/></svg>')+'</span>' : '')+
        '</span></div></div>';
    }).join('');
  }
  async function loadMessages(force=false) {
    if (!running || !activePeer || !currentPage ||
        contacts.some(c=>c.id===activePeer && (c.invitation || (c.id==='alliance' && !c.joined)))) return;
    const targetPeer=activePeer;
    if (loadingPeer===targetPeer) return;
    const generation=sessionGeneration;
    loadingPeer=targetPeer;
    try {
      const result=await api('/api/messenger/messages?peer='+encodeURIComponent(targetPeer));
      if (!running || generation!==sessionGeneration ||
          activePeer!==targetPeer || !currentPage) return;
      const messages=result.messages||[];
      // Include receipt state so a read acknowledgement updates existing bubbles
      // even if no new messages arrived.
      const key=messages.map(m=>m.id+':'+(m.read===true?'r':m.read===false?'s':'-')).join(',');
      if (force || key!==shownIds) {
        const holder=$('messenger-history');
        const previousScrollTop=holder.scrollTop;
        const stickToBottom=force || holder.scrollHeight-holder.scrollTop-holder.clientHeight<90;
        if (!shownIds) {
          historyHasMore=Boolean(result.has_more);
          oldestBefore=messages.length?messages[0].id:null;
        }
        renderHistory(messages);
        shownIds=key;
        if (stickToBottom) holder.scrollTop=holder.scrollHeight;
        else holder.scrollTop=previousScrollTop;
      }
      const contact=contacts.find(c=>c.id===targetPeer);
      if (contact?.unread>0 || force) {
        // Do not block rendering while the read receipt is being written.
        api('/api/messenger/read',{method:'POST',body:JSON.stringify({peer:targetPeer})})
          .then(()=>{if (activePeer===targetPeer && generation===sessionGeneration) {
            if (contact) contact.unread=0;
            renderContacts();
          }}).catch(e=>{if (activePeer===targetPeer) error('Read sync: '+e.message);});
      }
    } catch(e){
      if (activePeer===targetPeer && generation===sessionGeneration) {
        error('Could not load conversation: '+e.message);
        $('messenger-history').innerHTML='<div class="messenger-empty">Conversation unavailable. Try opening it again.</div>';
      }
    } finally {
      if (loadingPeer===targetPeer) loadingPeer='';
    }
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
  async function joinAlliance() {
    if (!running || !activePeer) return;
    const current=contacts.find(c=>c.id===activePeer);
    if (!current || (activePeer!=='alliance' && !current.invitation)) return;
    const peer=activePeer;
    const button=$('messenger-join-alliance');
    button.disabled=true;
    error();
    try {
      if (peer==='alliance') {
        await api('/api/messenger/alliance/join',{method:'POST',body:'{}'});
      } else {
        await api('/api/messenger/groups/join',{method:'POST',
          body:JSON.stringify({peer})});
      }
      const result=await api('/api/messenger');
      identity=result.me;
      contacts=Array.isArray(result.contacts)?result.contacts:[];
      renderContacts();
      if (activePeer===peer) await openPeer(peer);
    } catch(e){error(e.message);}
    finally{button.disabled=false;}
  }
  function approvedPlayers() {
    return contacts.filter(c=>!c.group && !c.self && c.id!=='admin' && c.id.startsWith('member:'));
  }
  function renderGroupPicker() {
    const search=$('messenger-group-player-search').value.trim().toLowerCase();
    const eligible=approvedPlayers().filter(p=>p.username.toLowerCase().includes(search) ||
      (p.player_name||'').toLowerCase().includes(search));
    const own=contacts.find(c=>c.self);
    const ownLine=own ? '<div class="messenger-player-option messenger-own-profile">'+
      '<span class="messenger-avatar">'+escape(avatar(own))+'</span>'+
      '<span><strong>'+escape(own.username)+' (You)</strong><small>Group creator · included automatically</small></span></div>' : '';
    $('messenger-group-players').innerHTML=ownLine + (eligible.length?eligible.map(p=>
      '<label class="messenger-player-option"><input type="checkbox" data-group-player="'+escape(p.id)+'"'+
      (selectedGroupPlayers.has(p.id)?' checked':'')+'><span class="messenger-avatar">'+escape(avatar(p))+'</span>'+
      '<span><strong>'+escape(p.username)+'</strong><small>'+escape(p.player_name||'')+'</small></span></label>'
    ).join(''):'<p class="messenger-loading">No other approved players found. Your account is already included.</p>');
    $('messenger-group-selected').textContent=selectedGroupPlayers.size+' other player(s) selected · You are included automatically';
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
    pingPresence();
    loadList();
  }
  function stop(){
    sessionGeneration++;
    running=false;csrf='';identity='';activePeer='';contacts=[];shownIds='';loadingPeer='';
    olderMessages=[];historyHasMore=false;oldestBefore=null;
    lastPresencePing=0;
    $('messenger-active-avatar').classList.remove('is-online');
    $('messenger-shell').classList.remove('chat-open','is-locked');
    document.body.classList.remove('messenger-mobile-chat-open');
    syncChatViewport();
    $('messenger-message').disabled=true;
    $('messenger-send').disabled=true;
    $('messenger-history').innerHTML='<div class="messenger-empty">No Conversation has been Made</div>';
    $('messenger-alliance-lock').hidden=true;
    renderContacts();
  }
  function onPage(name){
    currentPage=name==='messenger';
    if (!currentPage) {
      $('messenger-shell').classList.remove('chat-open');
      document.body.classList.remove('messenger-mobile-chat-open');
      syncChatViewport();
    }
    if (currentPage && running) {
      loadList();
      if (activePeer) {
        const contact=contacts.find(c=>c.id===activePeer);
        if (contact && !contact.invitation && (activePeer!=='alliance' || contact.joined)) loadMessages();
      }
    }
  }
  function init(){
    $('messenger-history').addEventListener('click',event=>{
      if (event.target.closest('[data-load-older]')) loadOlder();
    });
    $('messenger-contact-list').addEventListener('click',event=>{
      const button=event.target.closest('[data-messenger-peer]');
      if (button) openPeer(button.dataset.messengerPeer);
    });
    $('messenger-search').addEventListener('input',renderContacts);
    $('messenger-join-alliance').addEventListener('click',joinAlliance);
    $('messenger-create-group').addEventListener('click',openGroupDialog);
    $('messenger-group-player-search').addEventListener('input',renderGroupPicker);
    $('messenger-group-players').addEventListener('change', event=>{
      const checkbox=event.target.closest('[data-group-player]');
      if (!checkbox) return;
      if (checkbox.checked) selectedGroupPlayers.add(checkbox.dataset.groupPlayer);
      else selectedGroupPlayers.delete(checkbox.dataset.groupPlayer);
      $('messenger-group-selected').textContent=selectedGroupPlayers.size+' other player(s) selected · You are included automatically';
    });
    $('messenger-group-form').addEventListener('submit',createGroup);
    $('messenger-compose').addEventListener('submit',send);
    window.addEventListener('resize',syncChatViewport,{passive:true});
    if (window.visualViewport){
      window.visualViewport.addEventListener('resize',syncChatViewport,{passive:true});
      window.visualViewport.addEventListener('scroll',syncChatViewport,{passive:true});
    }
    $('messenger-back').addEventListener('click',()=>{
      $('messenger-shell').classList.remove('chat-open');
      document.body.classList.remove('messenger-mobile-chat-open');
      syncChatViewport();
    });
    document.addEventListener('visibilitychange',()=>{
      if (!document.hidden && running) {
        pingPresence();
        loadList();
        if (currentPage) loadMessages();
      }
    });
    setInterval(()=>{
      if (!running || document.hidden) return;
      if (Date.now()-lastPresencePing>=25000) pingPresence();
      if (currentPage) loadMessages();
      if (Date.now()-lastNotify>=10000) {
        lastNotify=Date.now();loadList();
      }
    },2500);
  }
  window.SasMessenger={init,start,stop,onPage};
})();
