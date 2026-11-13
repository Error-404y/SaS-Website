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
