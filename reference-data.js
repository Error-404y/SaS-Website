/* Police Chief reference guide data, with displayed (often rounded) game values.
 * Sources: betterpolicechief.com (v0.1.179), policechief-wiki.com.
 * Event editions and point chest thresholds can change by PD and server age.
 */
(function(root) {
'use strict';
const M = 1e6, K = 1e3;
const pd = [
[1,0,0,0,0,'—'],
[2,0,180,0,0,'6s'],
[3,0,805,0,0,'1m'],
[4,0,1800,360,0,'3m'],
[5,0,7600,1500,0,'10m'],
[6,0,19000,3800,960,'30m'],
[7,0,69000,13000,3400,'1h'],
[8,0,120000,25000,6300,'2h 30m'],
[9,0,260000,52000,13000,'4h 30m'],
[10,0,460000,92000,23000,'6h'],
[11,1.3*M,1.3*M,260*K,65*K,'7h 30m'],
[12,1.6*M,1.6*M,330*K,84*K,'9h'],
[13,2.3*M,2.3*M,470*K,110*K,'11h'],
[14,3.1*M,3.1*M,630*K,150*K,'14h'],
[15,4.6*M,4.6*M,930*K,230*K,'18h'],
[16,5.9*M,5.9*M,1.1*M,290*K,'1d 6h'],
[17,9.3*M,9.3*M,1.8*M,460*K,'1d 12h'],
[18,12*M,12*M,2.5*M,620*K,'1d 19h'],
[19,15*M,15*M,3.1*M,780*K,'2d 17h'],
[20,21*M,21*M,4.3*M,1*M,'3d 10h'],
[21,27*M,27*M,5.4*M,1.3*M,'4d 10h'],
[22,36*M,36*M,7.2*M,1.8*M,'6d 16h'],
[23,44*M,44*M,8.9*M,2.2*M,'9d 8h'],
[24,60*M,60*M,12*M,3*M,'13d 2h'],
[25,81*M,81*M,16*M,4*M,'18d 8h'],
[26,100*M,100*M,21*M,5.2*M,'21d 2h'],
[27,140*M,140*M,29*M,7.4*M,'25d 7h'],
[28,190*M,190*M,39*M,9.9*M,'29d 2h'],
[29,240*M,240*M,49*M,12*M,'33d 11h'],
[30,300*M,300*M,60*M,15*M,'40d 4h']
].map(([level,ammo,cash,electricity,gas,time])=>({level,ammo,cash,electricity,gas,time,
  reference: 'https://betterpolicechief.com/buildings/chiefs-office/'}));
const shards = [
  [1,[1,1,2,2,2,2]],
  [2,[5,5,5,5,5,15]],
  [3,[15,15,15,15,15,40]],
  [4,[40,40,40,40,40,100]],
  [5,[100,100,100,100,100,100]]
].map(([star,steps],index,array)=>({star,steps,perStar:steps.reduce((a,b)=>a+b,0),
  cumulative:array.slice(0,index+1).reduce((sum,[,values])=>sum+values.reduce((a,b)=>a+b,0),0)}));
const action=(name,unit,points,note='')=>({name,unit,points,note});
const speedups = rate => ['Construction','Research','Officer training/promotion']
 .map(name=>action(name+' speedup',1,rate,'Points per 1 minute; using Diamonds does not count.'));
const gathering = (ammo,cash,electricity,gas,points)=>[
  action('Confiscate Ammo',ammo,points),action('Confiscate Cash',cash,points),
  action('Confiscate Electricity',electricity,points),action('Confiscate Gas',gas,points)
];
const hero = (a,b,c)=>[action('Rare Hero Fragment',1,a),action('Epic Hero Fragment',1,b),
 action('Legendary Hero Fragment',1,c)];
const svs = {
  name: 'State vs. State (State Showdown)',
  source:'https://betterpolicechief.com/events/state-showdown/',
  edition:'v0.1.179 · State age Day 50–110 · source displayed thresholds',
  days: [
    {name:'PD Construction',chests:[30000,100000,200000],actions:[
      action('Electro Core',1,2000),...speedups(30),action('Badge rating increase',1,70)]},
    {name:'Base Power Boost',chests:[40000,120000,270000],actions:[
      action('Electro Core',1,2000),...speedups(30),action('Lucky Wheel spin',1,8000),
      ...hero(350,1220,3040),...gathering(1000,1000,200,50,2)]},
    {name:'Arresting Criminals',chests:[80000,150000,300000],actions:[
      action('Badge rating increase',1,70),action('Lucky Wheel spin',1,8000),
      ...hero(350,1220,3040),action('Defeat Crime Boss rally',1,30000),
      action('Defeat Lv 1–10 Criminal',1,9000),action('Defeat Lv 11–15 Criminal',1,9750),
      action('Defeat Lv 16–20 Criminal',1,10500),action('Defeat Lv 21–25 Criminal',1,11250),
      action('Defeat Lv 26–30 Criminal',1,12000)]},
    {name:'Hero Growth',chests:[80000,150000,300000],actions:[
      action('Badge rating increase',1,70),action('Hardened Steel',1,4000),
      action('Hero Exclusive Equipment material',1,8000),
      ...[3,4,5,8,12,18,25,35,45,60].map((points,i)=>action('Train Lv '+(i+1)+' Officer',1,points)),
      action('Valor Crystal',1,144000)]},
    {name:'Power Sprint',chests:[40000,130000,250000],actions:[
      action('K9 breakthrough rating increase',1,50),action('Premium Whistle',1,15000),
      action('Normal Whistle',1,1150),action("Chief equipment rating increase",1,36),
      action('Hardened Steel',1,4000),action('Hero Exclusive Equipment material',1,8000),
      action('Electro Core',1,2000),...speedups(30),action('Valor Crystal',1,144000)]},
    {name:'Final Showdown',chests:[48000,120000,250000],actions:[
      action('Defeat Lv 1–10 Criminal',1,9000),
      action('Defeat Lv 11–15 Criminal',1,9750),
      action('Defeat Lv 16–20 Criminal',1,10500),
      action('Defeat Lv 21–25 Criminal',1,11250),
      action('Defeat Lv 26–30 Criminal',1,12000),
      action('Defeat Crime Boss rally',1,30000)]}
  ]
};
const chief = {
  name:'Chief Almighty',
  source:'https://betterpolicechief.com/events/chief-almighty/',
  edition:'v0.1.179 · Edition 5 · PD under 19 · State age Day 1–112',
  days:[
    {name:'Power Sprint',chests:[1000,1190000,2240000,3010000],actions:[
      action('Construction power gained',1,30),action('Research power gained',1,30),
      action('Officer power gained',1,20)]},
    {name:'Hero Growth',chests:[1000,260000,570000,800000],actions:[
      action('Lucky Wheel spin',1,90000),...hero(4000,14000,35000),
      ...gathering(50,50,10,2,3)]},
    {name:'Officer Training',chests:[1000,670000,1200000,1670000],actions:
      [90,120,180,265,385,595,830,1130,1485,1960].map((v,i)=>action('Train Lv '+(i+1)+' Officer',1,v))},
    {name:'Badge Upgrade',chests:[1000,337000,674000,1120000],actions:[
      action('Badge rating increase',1,1000),
      ...gathering(50,50,10,2,3),action('Research power gained',1,45)]},
    {name:'Power Sprint',chests:[1000,686000,1260000,1750000],actions:[
      action('Hardened Steel',1,50000),action('Hero Exclusive Equipment material',1,100000),
      action('Construction power gained',1,30),action('Research power gained',1,30),
      action('Officer power gained',1,20)]},
    {name:"Chief's Upgrade",chests:[1000,528000,1320000,2650000],actions:[
      action("Chief equipment rating increase",1,500)]},
    {name:'Hero Growth',chests:[1000,150000,430000,800000],actions:[
      ...hero(4000,14000,35000),...speedups(300)]}
  ]
};
function requirements(points, unit, rate){
  if (!Number.isFinite(Number(points)) || !Number.isFinite(Number(unit)) || !Number.isFinite(Number(rate)) ||
      Number(points)<0 || Number(unit)<=0 || Number(rate)<=0) return null;
  return Math.ceil(Number(points)/Number(rate))*Number(unit);
}
function upcomingUrgency(startUtc, now = Date.now()){
  const ms = Date.parse(String(startUtc||'').replace(' ','T')+'Z')-now;
  if(!Number.isFinite(ms)||ms<=0)return 'normal';
  if(ms<=3600000)return 'red';
  if(ms<=4*3600000)return 'yellow';
  return 'normal';
}
const api={pd,shards,svs,chief,requirements,upcomingUrgency};
root.SasReference=api;
if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
