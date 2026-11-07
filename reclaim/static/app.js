'use strict';
const $ = id => document.getElementById(id);
const state = {wallets:[], selected:new Set(), filter:''};
let toastHandle;
const toast = (message, error=false) => { const box=$('toast');box.textContent=message;box.className='toast show'+(error?' error':'');clearTimeout(toastHandle);toastHandle=setTimeout(()=>box.className='toast',4600);};
const token=()=>sessionStorage.getItem('reclaim_api_token')||'';
async function api(path, options={}){
  const headers={'Content-Type':'application/json',...(options.headers||{})};
  if(token()) headers.Authorization='Bearer '+token();
  const response=await fetch(path,{...options,headers,cache:'no-store'});
  const contentType=response.headers.get('content-type')||'';
  if(!contentType.includes('application/json')) throw Error('Unexpected server response');
  const data=await response.json();
  if(!response.ok) throw Error(data.error||`HTTP ${response.status}`);
  return data;
}
const post=(path,body)=>api(path,{method:'POST',body:JSON.stringify(body)});
const money=v=>Number.isFinite(Number(v))?'$'+Number(v).toLocaleString('en-US',{maximumFractionDigits:2,minimumFractionDigits:2}):'—';
const qty=v=>v===null||v===undefined?'—':Number(v).toLocaleString('en-US',{maximumFractionDigits:7});
const shorten=a=>a.slice(0,8)+'…'+a.slice(-6);
const escapeHTML=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const explorer={ethereum:'https://etherscan.io/address/',base:'https://basescan.org/address/',arbitrum:'https://arbiscan.io/address/',polygon:'https://polygonscan.com/address/'};
const chainNames={ethereum:'ETHEREUM',base:'BASE',arbitrum:'ARBITRUM',polygon:'POLYGON'};
function refreshStats(){
  const wallets=state.wallets, scanned=wallets.filter(w=>w.scanned_at);
  $('statTracked').textContent=wallets.length.toLocaleString();
  $('statScanned').textContent=scanned.length.toLocaleString();
  const values=scanned.filter(w=>w.estimated_usd!==null).map(w=>Number(w.estimated_usd));
  $('statValue').textContent=(scanned.length&&values.length===scanned.length)?money(values.reduce((a,b)=>a+b,0)):'—';
  $('scanStamp').textContent=scanned.length?`LAST SCAN · ${new Date(scanned.reduce((a,b)=>a.scanned_at>b.scanned_at?a:b).scanned_at).toLocaleString()}`:'NO SCANS YET';
}
function renderTable(){
  const filtered=state.wallets.filter(w=>`${w.address} ${w.chain} ${w.label||''}`.includes(state.filter));
  $('tableCount').textContent=`${filtered.length} ADDRESSES`;
  $('selectAll').checked=filtered.length>0&&filtered.every(w=>state.selected.has(w.id));
  if(!filtered.length){$('walletRows').innerHTML='<tr><td colspan="8" class="empty-state">No addresses match. Import addresses or discover a historical block.</td></tr>';return;}
  $('walletRows').innerHTML=filtered.map(w=>{
    const link=explorer[w.chain]+w.address;
    const s=w.scanned_at?'<span class="state-pill good">Observed</span>':'<span class="state-pill">Not scanned</span>';
    const when=w.scanned_at?new Date(w.scanned_at).toLocaleDateString():'—';
    const native=w.native_balance===null?'—':qty(w.native_balance)+' '+(w.chain==='polygon'?'POL':'ETH');
    return `<tr><td><input class="pick" type="checkbox" data-id="${w.id}" aria-label="Select ${escapeHTML(w.address)}" ${state.selected.has(w.id)?'checked':''}></td><td><a href="${link}" target="_blank" rel="noopener noreferrer" title="Open verified block explorer">${shorten(w.address)}</a></td><td><span class="chain-pill">${chainNames[w.chain]||'UNKNOWN'}</span></td><td>${native}</td><td>${qty(w.usdc_balance)}</td><td>${w.estimated_usd===null?'—':money(w.estimated_usd)}</td><td>${when}</td><td>${s}</td></tr>`;
  }).join('');
  document.querySelectorAll('.pick').forEach(el=>el.addEventListener('change',()=>{const id=Number(el.dataset.id);el.checked?state.selected.add(id):state.selected.delete(id);$('selectAll').checked=filtered.every(w=>state.selected.has(w.id));}));
}
async function loadWallets(){
  try{const d=await api('/api/wallets');state.wallets=d.wallets;state.selected=new Set([...state.selected].filter(id=>state.wallets.some(w=>w.id===id)));renderTable();refreshStats();$('networkState').textContent='LOCAL ENGINE';$('serverStatus').textContent='CONNECTED';}
  catch(err){$('serverStatus').textContent='DISCONNECTED';$('networkState').textContent='ACCESS REQUIRED';toast(err.message,true);}
}
function switchView(name){
  for(const key of ['explorer','lab','settings']){$('view-'+key).classList.toggle('hidden',key!==name);document.querySelector(`[data-nav="${key}"]`).classList.toggle('active',key===name);}
  $('breadcrumb').textContent={explorer:'INTELLIGENCE HUB',lab:'OPPORTUNITY LAB',settings:'NETWORK SETTINGS'}[name];
}
async function withLoading(button,work){const label=button.innerHTML;button.disabled=true;button.textContent='WORKING…';try{await work();}catch(err){toast(err.message,true);}finally{button.disabled=false;button.innerHTML=label;}}
document.querySelectorAll('[data-nav]').forEach(b=>b.addEventListener('click',()=>switchView(b.dataset.nav)));
$('refreshBtn').addEventListener('click',()=>loadWallets());
$('importForm').addEventListener('submit',async e=>{e.preventDefault();const button=e.submitter;await withLoading(button,async()=>{
  const addresses=$('addresses').value.split(/[\s,;]+/).map(s=>s.trim()).filter(Boolean);
  if(!addresses.length||addresses.length>100)throw Error('Enter 1 to 100 wallet addresses.');
  await post('/api/wallets',{chain:$('chainSelect').value,addresses});$('addresses').value='';toast(`${addresses.length} address(es) added or already tracked.`);await loadWallets();
});});
$('discoverForm').addEventListener('submit',async e=>{e.preventDefault();const button=e.submitter;await withLoading(button,async()=>{
  const d=await post('/api/discover',{chain:$('discoverChain').value,block_number:Number($('blockNumber').value)});
  toast(`${d.discovered} public addresses sampled from block ${d.block_number}.`);await loadWallets();
});});
$('searchBox').addEventListener('input',e=>{state.filter=e.target.value.toLowerCase();renderTable();});
$('selectAll').addEventListener('change',e=>{const filtered=state.wallets.filter(w=>`${w.address} ${w.chain} ${w.label||''}`.includes(state.filter));for(const w of filtered){e.target.checked?state.selected.add(w.id):state.selected.delete(w.id);}renderTable();});
$('scanBtn').addEventListener('click',e=>withLoading(e.currentTarget,async()=>{
  const ids=[...state.selected];if(!ids.length)throw Error('Select one or more wallet rows first.');if(ids.length>25)throw Error('Scan a maximum of 25 wallets at a time.');
  const d=await post('/api/scan',{ids});const good=d.results.filter(r=>r.status==='ok');const bad=d.results.filter(r=>r.status==='error');
  toast(`${good.length} scanned successfully; ${bad.length} failed.${bad.length?' '+bad[0].message:''}`,bad.length>0);await loadWallets();
}));
$('exportBtn').addEventListener('click',async()=>{
  try{const headers={};if(token())headers.Authorization='Bearer '+token();const resp=await fetch('/api/export.csv',{headers});if(!resp.ok)throw Error('CSV export failed');
    const blob=await resp.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='reclaim-wallet-observations.csv';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Observations exported.');}
  catch(err){toast(err.message,true);}
});
$('simForm').addEventListener('submit',async e=>{e.preventDefault();const button=e.submitter;await withLoading(button,async()=>{
  const obj=Object.fromEntries(new FormData(e.target));const result=await post('/api/simulate',obj);
  $('resultNet').textContent=money(result.estimated_net_usd);$('resultHf').textContent=result.health_factor??'—';$('resultGross').textContent=money(result.gross_profit_usd);$('resultCosts').textContent=money(result.estimated_costs_usd);
  const badge=$('resultBadge');badge.textContent=result.scenario_profitable?'POSITIVE HYPOTHETICAL SCENARIO':'NOT PROFITABLE / NOT ELIGIBLE';badge.classList.toggle('negative',!result.scenario_profitable);
  toast('Scenario calculated. No transaction was executed.');
});});
$('saveToken').addEventListener('click',()=>{const t=$('apiToken').value.trim();t?sessionStorage.setItem('reclaim_api_token',t):sessionStorage.removeItem('reclaim_api_token');$('apiToken').value='';toast(t?'Token set for this browser tab.':'Session token cleared.');loadWallets();});
loadWallets();
