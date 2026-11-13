/* SaS reference calculators, no server writes; all data belongs to documented public game editions. */
(function(root){
'use strict';
const R=root.SasReference, P=root.SasPlanner;
if(!R||!P)return;
const el=id=>document.getElementById(id);
const fmt=n=>Number(n).toLocaleString('en-US',{maximumFractionDigits:1});
const text=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const short=n=>n===null?'—':P.fmt(n);
let selected={svs:0,chief:0};
let totals={svs:0,chief:0};
function pill(n,i){return '<div class="ref-milestone"><span>Chest '+(i+1)+'</span><strong>'+text(short(n))+'</strong></div>';}
function actionRow(a,index,remaining){
  const count=R.requirements(remaining,a.unit,a.points);
  return '<tr><td><strong>'+text(a.name)+'</strong><small>'+text(a.note||'')+'</small></td>'+
    '<td>'+fmt(a.unit)+' → <b>'+fmt(a.points)+' pts</b></td>'+
    '<td><strong>'+fmt(count)+'</strong> '+(a.name.toLowerCase().includes('speedup')?'min':'')+
    (a.name.toLowerCase().includes('speedup')?'<small>'+P.duration(count*60)+'</small>':'')+'</td>'+
    '<td><input type="number" min="0" step="1" value="0" data-ref-action="'+index+'" aria-label="'+text(a.name)+' quantity" /></td></tr>';
}
function renderEvent(kind){
  const data=R[kind],day=selected[kind],current=data.days[day];
  const nav=el('ref-'+kind+'-days'),target=el('ref-'+kind+'-content');
  if(!nav||!target)return;
  nav.innerHTML=data.days.map((d,i)=>'<button type="button" data-reference-day="'+i+'" aria-pressed="'+(i===day)+'" class="'+(i===day?'active':'')+'">Day '+(i+1)+'<small>'+text(d.name)+'</small></button>').join('');
  const goal=current.chests.at(-1);
  const speedRates=[...new Set(current.actions.filter(a=>a.name.toLowerCase().includes('speedup')).map(a=>a.points))];
  const speedupChart=speedRates.length?
    '<details class="ref-speed-chart" open><summary>Speedup point values (per item)</summary>'+
    '<div class="ref-speed-grid">'+[{label:'1m',minutes:1},{label:'5m',minutes:5},{label:'1h',minutes:60},{label:'3h',minutes:180},{label:'8h',minutes:480}]
      .map(item=>'<div class="ref-speed-tile"><span>'+item.label+'</span><strong>'+
      fmt(item.minutes*speedRates[0])+' pts</strong><small id="ref-'+kind+'-speed-'+item.minutes+
      '">'+fmt(Math.ceil(goal/(item.minutes*speedRates[0])))+' needed</small></div>').join('')+
    '</div><p class="tool-footnote">Speedups for construction, research and training share this point rate on the selected day. This counts real speedup items used, not Diamond completions.</p></details>' : '';
  target.innerHTML=
    '<div class="ref-day-header"><div><p class="section-kicker">DAY '+(day+1)+'</p><h2>'+text(current.name)+'</h2></div><div class="ref-goal-label"><span>All chest rewards</span><strong>'+short(goal)+' pts</strong></div></div>'+
    '<div class="ref-chests">'+current.chests.map(pill).join('')+'</div>'+
    '<div class="ref-controls"><label>Points already earned<input id="ref-'+kind+'-earned" type="number" min="0" step="1" value="0"></label>'+
    '<label>Calculate for chest<select id="ref-'+kind+'-chest">'+current.chests.map((n,i)=>'<option value="'+n+'" '+(i===current.chests.length-1?'selected':'')+'>Chest '+(i+1)+' · '+short(n)+'</option>').join('')+'</select></label></div>'+
    '<div class="ref-result"><span>Points still needed</span><strong id="ref-'+kind+'-remaining">'+fmt(goal)+'</strong></div>'+
    speedupChart+
    '<h3 class="tool-subtitle">How many items or speedups do I need?</h3>'+
    '<p class="tool-footnote">Each row shows how much of ONE action would reach the selected chest. Enter what you have to calculate combined points. Speedup rows count actual minutes used, not number of speedup items.</p>'+
    '<div class="table-container"><table class="tool-table ref-table"><thead><tr><th>Action</th><th>Points per unit</th><th>Needed alone</th><th>Planned amount</th></tr></thead><tbody id="ref-'+kind+'-actions">'+current.actions.map((a,i)=>actionRow(a,i,goal)).join('')+'</tbody></table></div>'+
    '<div class="ref-totals"><span>Planned points <strong id="ref-'+kind+'-planned">0</strong></span><span>Remaining after plan <strong id="ref-'+kind+'-after">'+fmt(goal)+'</strong></span></div>';
  nav.querySelectorAll('[data-reference-day]').forEach(b=>b.addEventListener('click',()=>{
    selected[kind]=Number(b.dataset.referenceDay);resetEvent(kind);
  }));
  target.addEventListener('input',()=>updateEvent(kind),{signal:daySignals[kind].signal});
  target.addEventListener('change',()=>updateEvent(kind),{signal:daySignals[kind].signal});
}
let daySignals={};
function resetEvent(kind){
  if(daySignals[kind])daySignals[kind].abort();
  daySignals[kind]=new AbortController();
  renderEvent(kind);
}
function updateEvent(kind){
  const data=R[kind],current=data.days[selected[kind]],container=el('ref-'+kind+'-content');
  if(!container)return;
  const earned=Number(el('ref-'+kind+'-earned').value)||0;
  const target=Number(el('ref-'+kind+'-chest').value);
  const total=Array.from(container.querySelectorAll('[data-ref-action]')).reduce((sum,input)=>{
    const i=Number(input.dataset.refAction),a=current.actions[i];
    const amount=Math.max(0,Math.floor(Number(input.value)||0));
    return sum+Math.floor(amount/a.unit)*a.points;
  },0);
  const needed=Math.max(0,target-earned);
  el('ref-'+kind+'-remaining').textContent=fmt(needed);
  el('ref-'+kind+'-planned').textContent=fmt(total);
  el('ref-'+kind+'-after').textContent=fmt(Math.max(0,needed-total));
  const speedRate=current.actions.find(a=>a.name.toLowerCase().includes('speedup'))?.points;
  if(speedRate){
    for(const minutes of [1,5,60,180,480]){
      const node=el('ref-'+kind+'-speed-'+minutes);
      if(node)node.textContent=fmt(Math.ceil(needed/(minutes*speedRate)))+' needed';
    }
  }
  const tbody=el('ref-'+kind+'-actions');
  tbody.querySelectorAll('tr').forEach((row,i)=>{
    const a=current.actions[i],quantity=R.requirements(needed,a.unit,a.points);
    const cell=row.children[2];cell.innerHTML='<strong>'+fmt(quantity)+'</strong> '+(a.name.toLowerCase().includes('speedup')?'min':'')+
    (a.name.toLowerCase().includes('speedup')?'<small>'+P.duration(quantity*60)+'</small>':'');
  });
}
function renderShards(){
  const table=el('ref-shards-table');if(!table)return;
  table.innerHTML=R.shards.map(row=>'<tr><th>'+row.star+' ★</th>'+
    row.steps.map(n=>'<td>'+fmt(n)+'</td>').join('')+'<td><strong>'+fmt(row.perStar)+'</strong></td>'+
    '<td><strong>'+fmt(row.cumulative)+'</strong></td></tr>').join('');
  el('ref-shards-cards').innerHTML=R.shards.map(row=>'<div class="ref-shard-card"><span>'+row.star+' ★</span>'+
    '<strong>'+fmt(row.perStar)+' shards</strong><small>'+fmt(row.cumulative)+' cumulative</small></div>').join('');
}
function pdSeconds(s){
  const pattern=/(\d+)\s*(d|h|m|s)/g;let match,total=0;
  while((match=pattern.exec(s||''))!==null){
    total+=Number(match[1])*({d:86400,h:3600,m:60,s:1}[match[2]]);
  }
  return total;
}
function renderPD(){
  const current=Number(el('ref-pd-current').value),target=Number(el('ref-pd-target').value);
  const chosen=R.pd.filter(r=>r.level>current&&r.level<=target);
  const sums=Object.fromEntries(['ammo','cash','electricity','gas'].map(key=>[key,chosen.reduce((a,r)=>a+r[key],0)]));
  const secs=chosen.reduce((sum,r)=>sum+pdSeconds(r.time),0);
  el('ref-pd-summary').innerHTML=[
    ['Upgrades',chosen.length],['Time',P.duration(secs)],
    ...Object.entries(sums).map(([k,v])=>[k[0].toUpperCase()+k.slice(1),short(v)])
  ].map(([k,v])=>'<div class="tool-stat"><span>'+k+'</span><strong>'+v+'</strong></div>').join('');
  el('ref-pd-table').innerHTML=R.pd.map(r=>'<tr class="'+(chosen.includes(r)?'ref-selected-row':'')+'">'+
    '<td><strong>Level '+r.level+'</strong></td>'+
    ['ammo','cash','electricity','gas'].map(key=>'<td>'+short(r[key])+'</td>').join('')+
    '<td>'+text(r.time)+'</td></tr>').join('');
}
function init(){
  if(!el('ref-svs-days'))return;
  ['svs','chief'].forEach(resetEvent);
  renderShards();
  for(const [id,value] of [['ref-pd-current',1],['ref-pd-target',30]]){
    el(id).innerHTML=R.pd.map(r=>'<option value="'+r.level+'" '+(r.level===value?'selected':'')+'>Level '+r.level+'</option>').join('');
    el(id).addEventListener('change',renderPD);
  }
  renderPD();
}
root.SasReferenceUI={init};
})(typeof window!=='undefined'?window:globalThis);
