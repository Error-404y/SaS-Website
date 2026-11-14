/* SaS Messenger: mobile-first rich chat controls. No external chat service. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const timeText = value => {
    if (!value) return '';
    const dt = new Date(String(value).replace(' ','T')+'Z');
    return Number.isNaN(dt.getTime()) ? '' :
      dt.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',timeZone:'UTC'})+' UTC';
  };
  let adapter = null, peer = '', me = '', contacts = [], latest = new Map();
  let reply = null, imagePayload = '', mentionables = [], lastTyping = 0, typingActive = false;
  let swiped = null, editingId = null, imageBusy = false;
  const context = () => adapter ? adapter.context() : {};
  const contextPeer = () => context().peer || '';
  const api = (path,data) => adapter.api(path,{method:'POST',body:JSON.stringify(data)});
  const say = error => adapter && adapter.error(error instanceof Error ? error.message : String(error));
  const isGroup = () => peer === 'alliance' || peer.startsWith('group:');
  const idNumber = value => Number.isSafeInteger(Number(value)) && Number(value)>0 ? Number(value) : null;
  const authorName = (sender, context) => {
    if (sender === context.me) return 'You';
    if (sender === 'admin') return 'SaS Admin';
    return context.contacts.find(c => c.id === sender)?.username || 'Former member';
  };
  const statusMarkup = msg => {
    if (typeof msg.read !== 'boolean') return '';
    return '<span class="messenger-read-receipt'+(msg.read?' is-read':'')+
      '" title="'+(msg.read?'Read':'Sent, not yet read')+'" aria-label="'+
      (msg.read?'Read':'Sent, not yet read')+'">'+
      (msg.read ?
        '<svg viewBox="0 0 26 18" width="13" height="10" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 9l5 5L17 3"/><path d="M10 9l5 5L25 3"/></svg>' :
        '<svg viewBox="0 0 18 18" width="12" height="10" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 9l5 5L16 3"/></svg>')+
      '</span>';
  };
  function messageMarkup(messages, state) {
    latest = new Map(messages.map(m => [Number(m.id),m]));
    if (!messages.length) return '<div class="messenger-empty">No messages yet. Say hello!</div>';
    return messages.map(msg => {
      const mine = msg.sender_key === state.me;
      if (msg.sender_key === 'system') {
        return '<div class="messenger-system-message">'+escape(msg.body)+'</div>';
      }
      const name = authorName(msg.sender_key,state);
      const id = Number(msg.id);
      const gone = msg.kind === 'deleted';
      const replyMarkup = msg.reply ?
        '<button type="button" class="rich-quoted" data-rich-jump="'+Number(msg.reply.id)+'">'+
        '<strong>'+escape(authorName(msg.reply.sender_key,state))+'</strong>'+
        '<span>'+escape(msg.reply.body)+'</span></button>' : '';
      let body;
      if (gone) {
        body='<em class="rich-deleted">This message was deleted</em>';
      } else if (msg.kind === 'image') {
        const link='/api/messenger/images/'+id+'?peer='+encodeURIComponent(state.peer);
        body='<a class="rich-image-link" href="'+escape(link)+'" target="_blank" rel="noopener noreferrer" title="Open photo">'+
          '<img loading="lazy" src="'+escape(link)+'" alt="Image shared in conversation" /></a>'+
          (msg.body && msg.body!=='Photo' ?
            '<span class="messenger-bubble-text">'+escape(msg.body)+'</span>' : '');
      } else if (msg.kind === 'poll' && msg.poll) {
        const poll=msg.poll;
        const total=Number(poll.total_votes)||0;
        body='<div class="rich-poll"><strong class="rich-poll-question">'+escape(poll.question)+'</strong>'+
          poll.options.map(option => {
            const n=Number(option.votes)||0;
            const pct=total?Math.round(n*100/total):0;
            const selected=poll.my_vote===Number(option.position);
            return '<button type="button" class="rich-poll-option'+(selected?' is-voted':'')+
              '" data-rich-vote="'+id+'" data-rich-position="'+Number(option.position)+'"'+
              (poll.closed?' disabled':'')+'><span class="rich-poll-option-name">'+
              (selected?'✓ ':'')+escape(option.label)+'</span><span>'+n+' · '+pct+'%</span>'+
              '<span class="rich-poll-bar" style="width:'+pct+'%"></span></button>';
          }).join('')+
          '<span class="rich-poll-total">'+total+' vote'+(total===1?'':'s')+
          (poll.closed?' · Closed':' · Tap an option to vote')+'</span>'+
          (mine && !poll.closed ?
            '<button type="button" class="rich-close-poll" data-rich-close-poll="'+id+'">Close poll</button>' : '')+
          '</div>';
      } else {
        // HTML-escape all text before adding harmless visual mention highlighting.
        const text=escape(msg.body).replace(/(^|[\s(])(@[A-Za-z0-9_.-]{2,32})/g,
          '$1<mark class="rich-mention">$2</mark>');
        body='<span class="messenger-bubble-text">'+text+'</span>';
      }
      const actions = !gone ?
        '<span class="rich-message-actions"><button type="button" class="rich-menu-trigger" data-rich-menu="'+id+
        '" aria-label="Message options" aria-expanded="false">⋯</button>'+
        '<span class="rich-message-menu" hidden>'+
        '<button type="button" data-rich-reply="'+id+'">Reply</button>'+
        (mine && msg.kind==='text'?'<button type="button" data-rich-edit="'+id+'">Edit</button>':'')+
        (mine?'<button type="button" data-rich-delete="'+id+'">Delete</button>':'')+
        '</span></span>' : '';
      return '<div class="messenger-line'+(mine?' mine':'')+(msg.mentioned_me?' rich-mentioned':'')+
        '" data-rich-message="'+id+'"><div class="messenger-bubble">'+
        ((state.peer==='alliance'||state.peer.startsWith('group:')) ?
          '<strong>'+escape(name)+'</strong>' : '')+
        replyMarkup+body+
        '<span class="messenger-bubble-footer"><time>'+escape(timeText(msg.created_at))+'</time>'+
        (msg.edited_at && !gone?'<small class="rich-edited">edited</small>':'')+
        (mine?statusMarkup(msg):'')+actions+'</span></div></div>';
    }).join('');
  }
  const disableMenu = () => {
    document.querySelectorAll('.rich-message-menu').forEach(node=>{ node.hidden=true; });
    document.querySelectorAll('.rich-menu-trigger').forEach(node=>node.setAttribute('aria-expanded','false'));
  };
  function replyTo(id) {
    const msg=latest.get(Number(id));
    if (!msg || msg.kind==='deleted' || msg.sender_key==='system') return;
    reply={id:Number(msg.id),sender_key:msg.sender_key,body:
      msg.kind==='image'?'Photo':msg.kind==='poll'?'Poll: '+(msg.poll?.question||''):msg.body.slice(0,100)};
    const title=reply.sender_key===me?'You':authorName(reply.sender_key,{me,contacts});
    $('rich-reply-author').textContent='Replying to '+title;
    $('rich-reply-body').textContent=reply.body;
    $('rich-reply-preview').hidden=false;
    $('messenger-message').focus();
    disableMenu();
  }
  const replyId = () => reply?.id ?? null;
  function clearReply() {
    reply=null;
    $('rich-reply-preview').hidden=true;
  }
  function clearPhoto() {
    imagePayload='';
    $('rich-photo-preview').hidden=true;
    $('rich-photo-thumb').removeAttribute('src');
    const input=$('rich-image-file');
    if (input) input.value='';
    $('messenger-message').placeholder='Write a message...';
  }
  function onPeer(nextPeer, contact) {
    if (peer && typingActive) typing(false,peer);
    peer=nextPeer;
    me=context().me||me;
    contacts=context().contacts||[];
    mentionables=[];
    lastTyping=0;
    clearReply();
    clearPhoto();
    $('rich-mention-picker').hidden=true;
    $('rich-typing').textContent='';
    $('rich-poll-trigger').hidden=!(contact.group && contact.joined!==false && !contact.invitation);
    if (isGroup() && contact.joined!==false && !contact.invitation) {
      const requested=peer;
      adapter.api('/api/messenger/mentionables?peer='+encodeURIComponent(requested))
        .then(result=>{if(peer===requested)mentionables=result.members||[];})
        .catch(()=>{});
    }
  }
  function onClose(){
    if (typingActive) typing(false,peer);
    clearReply();
    clearPhoto();
    $('rich-mention-picker').hidden=true;
    $('rich-typing').textContent='';
    peer='';
    mentionables=[];
  }
  function onMessageData(result) {
    const who=Array.isArray(result.typing)?result.typing:[];
    $('rich-typing').textContent=who.length?
      (who.length===1?who[0]+' is typing…':who.join(', ')+' are typing…'):'';
  }
  async function typing(active,forPeer=peer) {
    if (!forPeer || forPeer===me) return;
    if (active && (document.hidden || !context().visible)) return;
    if (active && Date.now()-lastTyping<3000) return;
    lastTyping=Date.now();
    typingActive=active;
    try {await api('/api/messenger/typing',{peer:forPeer,active});}
    catch(_) { /* Typing is best effort and must not block Messenger. */ }
  }
  async function prepareImage(file) {
    if (!file || !/^image\/(jpeg|png|webp|heic|heif)$/.test(file.type)) throw new Error('Choose a JPEG, PNG, WebP or supported iPhone HEIC photo.');
    if (file.size>12*1024*1024) throw new Error('Choose an image smaller than 12 MB.');
    const source=URL.createObjectURL(file);
    try {
      const image=new Image();
      image.src=source;
      await image.decode();
      if (image.width*image.height > 32000000) throw new Error('This photo is too large. Choose a smaller version.');
      const ratio=Math.min(1,1600/Math.max(image.width,image.height));
      const canvas=document.createElement('canvas');
      canvas.width=Math.max(1,Math.round(image.width*ratio));
      canvas.height=Math.max(1,Math.round(image.height*ratio));
      const ctx=canvas.getContext('2d');
      if(!ctx)throw new Error('Cannot prepare image on this device.');
      ctx.fillStyle='#ffffff';
      ctx.fillRect(0,0,canvas.width,canvas.height);
      ctx.drawImage(image,0,0,canvas.width,canvas.height);
      const url=canvas.toDataURL('image/jpeg',0.76);
      const encoded=url.slice(url.indexOf(',')+1);
      if(encoded.length>5_500_000) throw new Error('Image too large; choose a smaller picture.');
      return {url,encoded};
    }finally{URL.revokeObjectURL(source);}
  }
  async function selectPhoto(file) {
    if(imageBusy)return;
    imageBusy=true;
    try {
      const prepared=await prepareImage(file);
      imagePayload=prepared.encoded;
      $('rich-photo-thumb').src=prepared.url;
      $('rich-photo-preview').hidden=false;
      $('messenger-message').placeholder='Add a caption (optional)...';
      $('messenger-message').focus();
    }catch(e){say(e);}
    finally{imageBusy=false;}
  }
  const hasImage = () => Boolean(imagePayload);
  const sendImage = (target,caption) => api('/api/messenger/images',{
    peer:target,image:imagePayload,caption:caption||'',reply_to:replyId()
  });
  function afterSend() {
    clearPhoto();clearReply();
    if (typingActive)typing(false,peer);
  }
  function mentionPicker() {
    const input=$('messenger-message');
    const value=input.value.slice(0,input.selectionStart);
    const match=value.match(/(?:^|\s)@([A-Za-z0-9_.-]*)$/);
    if(!isGroup()||!match||!mentionables.length){
      $('rich-mention-picker').hidden=true;return;
    }
    const query=match[1].toLowerCase();
    const filtered=mentionables.filter(x=>x.username.toLowerCase().includes(query)).slice(0,8);
    const current=contacts.find(c=>c.id===peer);
    if ((me==='admin'||current?.can_mention_everyone) && 'everyone'.includes(query))
      filtered.unshift({id:'everyone',username:'everyone',player_name:'Notify all group members'});
    const picker=$('rich-mention-picker');
    picker.innerHTML=filtered.map(x=>'<button type="button" data-rich-mention="'+escape(x.username)+'">'+
      '<strong>@'+escape(x.username)+'</strong><small>'+escape(x.player_name)+'</small></button>').join('');
    picker.hidden=!filtered.length;
  }
  function pickMention(username) {
    const input=$('messenger-message');
    const prefix=input.value.slice(0,input.selectionStart);
    const suffix=input.value.slice(input.selectionStart);
    const match=prefix.match(/(?:^|\s)@([A-Za-z0-9_.-]*)$/);
    if(!match)return;
    input.value=prefix.slice(0,prefix.length-match[1].length)+username+' '+suffix;
    // We retained the leading @ from the typed token.
    const pos=prefix.length-match[1].length+username.length+1;
    input.focus();input.setSelectionRange(pos,pos);
    $('rich-mention-picker').hidden=true;
    typing(true);
  }
  function jumpTo(id) {
    const row=$('messenger-history').querySelector('[data-rich-message="'+Number(id)+'"]');
    if(!row){say('This message is older than the currently loaded history. Use Load older messages.');return;}
    row.scrollIntoView({block:'center',behavior:'smooth'});
    row.classList.add('rich-jump-highlight');
    setTimeout(()=>row.classList.remove('rich-jump-highlight'),1600);
  }
  async function handleAction(event) {
    const target=event.target;
    const menu=target.closest('[data-rich-menu]');
    if(menu){
      const panel=menu.nextElementSibling;
      const open=panel.hidden;
      disableMenu();panel.hidden=!open;menu.setAttribute('aria-expanded',String(open));
      return;
    }
    const mention=target.closest('[data-rich-mention]');
    if(mention){pickMention(mention.dataset.richMention);return;}
    const quote=target.closest('[data-rich-jump]');
    if(quote){jumpTo(quote.dataset.richJump);return;}
    const action=target.closest('[data-rich-reply],[data-rich-edit],[data-rich-delete],[data-rich-vote],[data-rich-close-poll]');
    if(!action)return;
    if(action.dataset.richReply){replyTo(action.dataset.richReply);return;}
    if(action.dataset.richEdit){
      const msg=latest.get(Number(action.dataset.richEdit));
      if(!msg||msg.sender_key!==me||msg.kind!=='text')return;
      editingId=Number(msg.id);
      $('rich-edit-body').value=msg.body;
      $('rich-edit-error').textContent='';
      $('rich-edit-dialog').showModal();
      disableMenu();return;
    }
    if(action.dataset.richDelete){
      const id=idNumber(action.dataset.richDelete);
      if (!id || !window.confirm('Delete this message for everyone?'))return;
      try{await api('/api/messenger/messages/delete',{peer:contextPeer(),id});disableMenu();await adapter.reload();}
      catch(e){say(e);}
      return;
    }
    if(action.dataset.richVote){
      try{await api('/api/messenger/polls/vote',{peer:contextPeer(),
        id:Number(action.dataset.richVote),position:Number(action.dataset.richPosition)});
        await adapter.reload();}
      catch(e){say(e);}
      return;
    }
    if(action.dataset.richClosePoll){
      if(!window.confirm('Close this poll? Players will no longer be able to vote.'))return;
      try{await api('/api/messenger/polls/close',{peer:contextPeer(),
        id:Number(action.dataset.richClosePoll)});await adapter.reload();}
      catch(e){say(e);}
    }
  }
  async function saveEdit(event) {
    event.preventDefault();
    const button=$('rich-edit-submit');
    button.disabled=true;
    try{
      await api('/api/messenger/messages/edit',{peer:contextPeer(),
        id:editingId,body:$('rich-edit-body').value.trim()});
      $('rich-edit-dialog').close();
      editingId=null;
      await adapter.reload();
    }catch(e){$('rich-edit-error').textContent=e.message;}
    finally{button.disabled=false;}
  }
  async function savePoll(event) {
    event.preventDefault();
    const button=$('rich-poll-submit');
    button.disabled=true;
    try{
      const question=$('rich-poll-question').value.trim();
      const options=[...$('rich-poll-options').querySelectorAll('input')].map(x=>x.value.trim()).filter(Boolean);
      await api('/api/messenger/polls',{peer:contextPeer(),question,options,reply_to:replyId()});
      $('rich-poll-dialog').close();
      clearReply();
      await adapter.reload();
      await adapter.refreshContacts();
    }catch(e){$('rich-poll-error').textContent=e.message;}
    finally{button.disabled=false;}
  }
  function openPoll() {
    if(!isGroup())return;
    $('rich-poll-form').reset();
    $('rich-poll-error').textContent='';
    const options=$('rich-poll-options');
    options.innerHTML='';
    for(let i=0;i<2;i++)addPollOption();
    $('rich-poll-dialog').showModal();
  }
  function addPollOption() {
    const options=$('rich-poll-options');
    if(options.children.length>=6)return;
    const input=document.createElement('input');
    input.type='text';input.maxLength=80;input.required=true;
    input.placeholder='Option '+(options.children.length+1);
    input.setAttribute('aria-label',input.placeholder);
    options.appendChild(input);
  }
  function init(config) {
    adapter=config;
    $('messenger-history').addEventListener('click',handleAction);
    $('rich-mention-picker').addEventListener('click',handleAction);
    $('messenger-history').addEventListener('touchstart',event=>{
      const line=event.target.closest('[data-rich-message]');
      if(!line||event.touches.length!==1)return;
      const t=event.touches[0];
      swiped={x:t.clientX,y:t.clientY,id:Number(line.dataset.richMessage)};
    },{passive:true});
    $('messenger-history').addEventListener('touchend',event=>{
      if(!swiped||!event.changedTouches.length)return;
      const t=event.changedTouches[0],dx=t.clientX-swiped.x,dy=t.clientY-swiped.y;
      if(dx>65 && Math.abs(dy)<45)replyTo(swiped.id);
      swiped=null;
    },{passive:true});
    $('messenger-message').addEventListener('input',()=>{
      mentionPicker();
      if($('messenger-message').value.trim())typing(true);
      else if(typingActive)typing(false);
    });
    $('messenger-message').addEventListener('blur',()=>{
      // Tapping the suggestion list must not dismiss it until the click fires.
      if(typingActive)typing(false);
    });
    $('rich-reply-cancel').addEventListener('click',clearReply);
    $('rich-photo-cancel').addEventListener('click',clearPhoto);
    $('rich-image-trigger').addEventListener('click',()=>$('rich-image-file').click());
    $('rich-image-file').addEventListener('change',event=>{
      if(event.target.files?.[0])selectPhoto(event.target.files[0]);
    });
    $('rich-poll-trigger').addEventListener('click',openPoll);
    $('rich-poll-add-option').addEventListener('click',addPollOption);
    $('rich-poll-form').addEventListener('submit',savePoll);
    $('rich-edit-form').addEventListener('submit',saveEdit);
    document.querySelectorAll('[data-rich-close]').forEach(button=>button.addEventListener(
      'click',()=>$('rich-'+button.dataset.richClose+'-dialog').close()));
  }
  window.SasRich={init,onPeer,onClose,onMessageData,messageMarkup,replyId,hasImage,sendImage,afterSend};
})();