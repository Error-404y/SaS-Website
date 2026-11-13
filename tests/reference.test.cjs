const test = require('node:test');
const assert = require('node:assert/strict');
const ref = require('../reference-data.js');

test('PD Office reference covers all levels 1 to 30 in order', () => {
  assert.equal(ref.pd.length,30);
  assert.deepEqual(ref.pd.map(x=>x.level),Array.from({length:30},(_,i)=>i+1));
  assert.equal(ref.pd[9].cash,460000);
  assert.equal(ref.pd[9].time,'6h');
  assert.equal(ref.pd[19].ammo,21000000);
  assert.equal(ref.pd[29].cash,300000000);
  assert.equal(ref.pd[29].electricity,60000000);
  assert.equal(ref.pd[29].gas,15000000);
  assert.equal(ref.pd[29].time,'40d 4h');
  assert.equal(ref.pd[0].time,'—');
});
test('Hero shards require 1065 total excluding hero recruitment',()=>{
  assert.deepEqual(ref.shards.map(x=>x.perStar),[10,40,115,300,600]);
  assert.deepEqual(ref.shards.map(x=>x.cumulative),[10,50,165,465,1065]);
  assert.deepEqual(ref.shards[4].steps,[100,100,100,100,100,100]);
});
test('SvS has 5 prep days and a separate final battle, each with sourced chest target',()=>{
  assert.equal(ref.svs.days.length,6);
  assert.deepEqual(ref.svs.days[0].chests,[30000,100000,200000]);
  assert.deepEqual(ref.svs.days[4].chests,[40000,130000,250000]);
  const speedup=ref.svs.days[0].actions.find(x=>x.name==='Construction speedup');
  assert.equal(speedup.points,30);
  assert.equal(ref.requirements(200000,1,30),6667);
  assert.equal(ref.svs.days[5].actions.find(x=>x.name.includes('opposing Lv 10 Officer')).points,13);
});
test('Chief Almighty chest and item rates are day-specific',()=>{
  assert.equal(ref.chief.days.length,7);
  assert.deepEqual(ref.chief.days[0].chests,[1000,1190000,2240000,3010000]);
  assert.deepEqual(ref.chief.days[2].chests,[1000,670000,1200000,1670000]);
  assert.equal(ref.chief.days[1].actions.find(x=>x.name==='Legendary Hero Fragment').points,35000);
  assert.equal(ref.chief.days[6].actions.find(x=>x.name==='Research speedup').points,300);
  assert.equal(ref.requirements(800000,1,35000),23);
  assert.equal(ref.requirements(800000,1,300),2667);
  assert.equal(ref.requirements(0,1,300),0);
  assert.equal(ref.requirements(100,0,1),null);
});
test('Upcoming event urgency updates precisely at 4h and 1h',()=>{
 const now=Date.parse('2026-11-13T12:00:00Z');
 const iso=minutes=>new Date(now+minutes*60000).toISOString().slice(0,19).replace('T',' ');
 assert.equal(ref.upcomingUrgency(iso(241),now),'normal');
 assert.equal(ref.upcomingUrgency(iso(240),now),'yellow');
 assert.equal(ref.upcomingUrgency(iso(61),now),'yellow');
 assert.equal(ref.upcomingUrgency(iso(60),now),'red');
 assert.equal(ref.upcomingUrgency(iso(1),now),'red');
 assert.equal(ref.upcomingUrgency(iso(0),now),'normal');
 assert.equal(ref.upcomingUrgency(iso(-20),now),'normal');
});

test('Guard X and Marksman X available; only Biker X is locked',()=>{
  const html=require('node:fs').readFileSync(require('node:path').join(__dirname,'../index.html'),'utf8');
  assert.match(html,/<option value="guard-10">/);
  assert.match(html,/<option value="marksman-10">/);
  assert.doesNotMatch(html,/<option value="biker-10">/);
  assert.match(html,/data-locked-troop="Royal Biker — T10"/);
  assert.doesNotMatch(html,/data-locked-troop="Royal Guard/);
  assert.doesNotMatch(html,/data-locked-troop="Royal Marksman/);
});

test('all destructive actions use the SaS confirmation dialog, not browser-native alerts',()=>{
  const fs=require('node:fs');
  const path=require('node:path');
  const app=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
  const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
  assert.doesNotMatch(app,/\b(?:window\.)?confirm\s*\(/);
  assert.doesNotMatch(app,/\b(?:window\.)?alert\s*\(/);
  assert.doesNotMatch(app,/\b(?:window\.)?prompt\s*\(/);
  assert.match(html,/<dialog id="confirm-action-dialog"/);
  assert.match(html,/data-confirm-choice="cancel"/);
  assert.match(html,/data-confirm-choice="accept"/);
  assert.match(app,/confirmAction\(\{/);
  assert.match(app,/title: 'Delete player account\?'/);
  assert.match(app,/title: 'Delete this entry\?'/);
  assert.match(app,/title: 'Remove spending record\?'/);
});

test('Event UI shows Reset Values, click hints, detailed scoring and ban modal',()=>{
  const fs=require('node:fs'),path=require('node:path');
  const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
  const app=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
  assert.match(html,/id="planner-reset-rates">Reset Values/);
  assert.doesNotMatch(html,/Reset to screenshot values/i);
  assert.match(app,/Click me · View details/);
  assert.match(html,/id="entry-points"/);
  assert.match(html,/id="entry-scoring"/);
  assert.match(app,/How to Earn Points/);
  assert.match(html,/id="ban-dialog"/);
  assert.match(html,/id="ban-queue-cancel-all"/);
  assert.match(app,/Cancel scheduled ban/);
});

test('Messenger exposes player list, pinned alliance and private group creation',()=>{
  const fs=require('node:fs'),path=require('node:path');
  const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
  const ui=fs.readFileSync(path.join(__dirname,'../messenger-ui.js'),'utf8');
  assert.match(html,/id="messenger-create-group"/);
  assert.match(html,/id="messenger-group-dialog"/);
  assert.match(html,/id="messenger-group-players"/);
  assert.match(ui,/GROUP CHATS/);
  assert.match(ui,/PLAYERS/);
  assert.match(ui,/messenger-alliance-pinned/);
  assert.match(ui,/Your Profile/);
  assert.match(ui,/api\/messenger\/groups/);
});
test('Troop Training now takes desired Phase 3 points, not an editable troop count',()=>{
  const fs=require('node:fs'),path=require('node:path');
  const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
  const ui=fs.readFileSync(path.join(__dirname,'../planner-ui.js'),'utf8');
  assert.match(html,/How many Event Points do you want\?/);
  assert.match(html,/id="planner-target-points"/);
  assert.match(html,/id="planner-count" type="hidden"/);
  assert.match(ui,/troopsForTargetPoints/);
  assert.match(ui,/Minimum troops needed/);
});

test('member login and reload initialize Messenger without undefined session scope',()=>{
  const fs=require('node:fs'),path=require('node:path');
  const app=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
  const login=app.split('async function playerLogin(event) {')[1].split('async function registerPlayer')[0];
  assert.match(login,/SasMessenger\?\.start\(response\.csrf\)/);
  assert.doesNotMatch(login,/SasMessenger\?\.start\(session\.csrf\)/);
  assert.match(login,/SasMessenger\?\.onPage\(site\.page\)/);
  const restore=app.split("request('/api/session').then(async session => {")[1].split("}).catch(")[0];
  assert.match(restore,/SasMessenger\?\.start\(session\.csrf\)/);
  assert.match(restore,/SasMessenger\?\.onPage\(site\.page\)/);
});
test('emails hidden by default with explicit eye toggle and mobile chat recovery',()=>{
  const fs=require('node:fs'),path=require('node:path');
  const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
  const app=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
  const chat=fs.readFileSync(path.join(__dirname,'../messenger-ui.js'),'utf8');
  assert.match(html,/id="account-detail-email-toggle"/);
  assert.match(html,/private-email-masked/);
  assert.match(app,/email\.textContent = '••••••••••••'/);
  assert.match(app,/toggleAccountEmail/);
  assert.match(chat,/invalid csrf token/i);
  assert.match(chat,/\/api\/session/);
  assert.match(chat,/No Conversation has been Made/);
  assert.match(chat,/No other approved players found/);
  assert.match(chat,/loadingPeer/);
});

test('Messenger self-notes and pinned group opt-in have visible controls',()=>{
  const fs=require('node:fs'),path=require('node:path');
  const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
  const ui=fs.readFileSync(path.join(__dirname,'../messenger-ui.js'),'utf8');
  assert.match(html,/id="messenger-join-alliance"/);
  assert.match(html,/id="messenger-alliance-lock"/);
  assert.match(ui,/Your Profile/);
  assert.match(ui,/Join SaS Group/);
  assert.match(ui,/api\/messenger\/alliance\/join/);
  assert.match(ui,/messenger-system-message/);
  assert.match(ui,/data-load-older/);
  assert.doesNotMatch(ui,/disabled aria-label="Your profile"/);
});
