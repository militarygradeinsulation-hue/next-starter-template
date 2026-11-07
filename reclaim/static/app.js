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
  if(!filtered.length){$('walletRows').innerHTML='<tr><td colspan="10" class="empty-state">No addresses match. Import addresses or discover a historical block.</td></tr>';return;}
  $('walletRows').innerHTML=filtered.map(w=>{
    const link=explorer[w.chain]+w.address;
    const s=w.scanned_at?'<span class="state-pill good">Observed</span>':'<span class="state-pill">Not scanned</span>';
    const when=w.scanned_at?new Date(w.scanned_at).toLocaleDateString():'—';
    const lastSeen=w.last_activity?new Date(w.last_activity).toLocaleDateString()+(w.coverage_complete?'':' †'):'—';
    const aaveHf=w.aave_health_factor??'—';
    const native=w.native_balance===null?'—':qty(w.native_balance)+' '+(w.chain==='polygon'?'POL':'ETH');
    return `<tr><td><input class="pick" type="checkbox" data-id="${w.id}" aria-label="Select ${escapeHTML(w.address)}" ${state.selected.has(w.id)?'checked':''}></td><td><a href="${link}" target="_blank" rel="noopener noreferrer" title="Open verified block explorer">${shorten(w.address)}</a></td><td><span class="chain-pill">${chainNames[w.chain]||'UNKNOWN'}</span></td><td>${native}</td><td>${qty(w.usdc_balance)}</td><td>${w.estimated_usd===null?'—':money(w.estimated_usd)}</td><td>${lastSeen}</td><td>${aaveHf}</td><td>${when}</td><td>${s}</td></tr>`;
  }).join('');
  document.querySelectorAll('.pick').forEach(el=>el.addEventListener('change',()=>{const id=Number(el.dataset.id);el.checked?state.selected.add(id):state.selected.delete(id);$('selectAll').checked=filtered.every(w=>state.selected.has(w.id));}));
}
async function loadWallets(){
  try{const d=await api('/api/wallets');state.wallets=d.wallets;state.selected=new Set([...state.selected].filter(id=>state.wallets.some(w=>w.id===id)));renderTable();refreshStats();$('networkState').textContent='LOCAL ENGINE';$('serverStatus').textContent='CONNECTED';await Promise.all([loadMonitor(),loadCandidates(),loadJobs(),loadBorrowerJobs(),loadReserveAnalyses()]);}
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
$('verifyNetworksBtn').addEventListener('click',e=>withLoading(e.currentTarget,async()=>{
  const response=await api('/api/network/status');const networks=response.networks||[];
  $('liveNetworkResults').innerHTML=networks.map(n=>`<div class="setting-line"><span>${escapeHTML(chainNames[n.chain]||n.chain)}</span><strong>${n.status==='connected'?'CONNECTED · block '+Number(n.block_number):'UNAVAILABLE'}</strong></div>`).join('');
  const failed=networks.filter(n=>n.status!=='connected').length;
  toast(`${networks.length-failed}/${networks.length} networks live.`,failed>0);
}));
async function loadMonitor(){
  const result=await api('/api/monitor');
  const scanner=result.scanner||{};
  $('autoStatus').textContent=scanner.enabled?`ENABLED · ${scanner.interval_minutes} MIN`:'DISABLED';
  $('autoNext').textContent=scanner.next_run?new Date(scanner.next_run).toLocaleString():'—';
  $('autoLast').textContent=scanner.last_result?`${scanner.last_result.scanned||0} OK / ${scanner.last_result.failed||0} ERR`:'—';
  $('indexStatus').textContent=result.indexed_activity_configured?'KEY CONFIGURED':'API KEY REQUIRED';
  $('queueAutoStatus').textContent=scanner.discovery_enabled?'ENABLED':'DISABLED';
  $('borrowerAutoStatus').textContent=scanner.aave_borrower_enabled?'ENABLED':'DISABLED';
}
async function loadCandidates(){
  const result=await api('/api/opportunities');const found=result.candidates||[];
  $('candidateCount').textContent=`${found.length} health factor signals flagged`;
  $('statCandidate').innerHTML=found.length+'<span class="suffix"> candidates</span>';
  $('candidateRows').innerHTML=found.length?found.map(p=>{
    const addr=escapeHTML(p.address);
    const url=explorer[p.chain]+addr;
    const date=p.scanned_at?new Date(p.scanned_at).toLocaleString():'—';
    return `<tr><td><a href="${url}" target="_blank" rel="noopener noreferrer">${shorten(addr)}</a></td><td>${escapeHTML(chainNames[p.chain]||p.chain)}</td><td>${escapeHTML(p.health_factor??'—')}</td><td><span class="state-pill">${p.snapshot_fresh?'RISK SIGNAL · UNVERIFIED':'STALE SIGNAL · RECHECK'}</span></td><td>${escapeHTML(date)}</td></tr>`;
  }).join(''):'<tr><td colspan="5" class="empty-state">No sub-1 Aave V3 risk signals have been recorded.</td></tr>';
}
async function loadReserveAnalyses(){
  const response=await api('/api/aave/reserves/analyses'), analyses=response.analyses||[];
  $('reserveAnalysisCount').textContent=`${analyses.length} REAL CONTRACT SNAPSHOTS`;
  const rows=[];
  for(const item of analyses){
    for(const reserve of item.reserves||[])rows.push({item,reserve});
    if(!(item.reserves||[]).length)rows.push({item,reserve:null});
  }
  $('reserveRows').innerHTML=rows.length?rows.slice(0,60).map(({item,reserve:r})=>{
    const address=escapeHTML(item.address), url=explorer[item.chain]+address;
    return `<tr><td><a href="${url}" target="_blank" rel="noopener noreferrer">${shorten(address)}</a><div class="muted">${escapeHTML(chainNames[item.chain]||item.chain)} · block ${Number(item.block_number)}</div></td>
      <td>${escapeHTML(item.health_factor??'—')}</td><td>${r?escapeHTML(r.symbol):'No active reserves'}</td>
      <td>${r?escapeHTML(r.collateral_value_base):'—'}</td><td>${r?escapeHTML(r.debt_value_base):'—'}</td>
      <td>${r?(Number(r.liquidation_bonus_bps)/100).toFixed(2)+'%':'—'}</td>
      <td><span class="state-pill">READ ONLY</span></td></tr>`;
  }).join(''):'<tr><td colspan="7" class="empty-state">No live Aave reserves read yet. Select a wallet in Intelligence Hub.</td></tr>';
}
$('reserveForm').addEventListener('submit',e=>{e.preventDefault();withLoading(e.submitter,async()=>{
  const ids=[...state.selected];
  if(ids.length<1||ids.length>2)throw Error('Select one or two addresses in Intelligence Hub.');
  const response=await post('/api/aave/reserves/analyze',{ids});
  const complete=response.analyses.filter(x=>x.status==='ok').length;
  toast(`${complete}/${ids.length} positions read from live Aave contracts.`,complete!==ids.length);
  await loadReserveAnalyses();
});});

async function loadJobs(){
  const result=await api('/api/discovery/jobs');const jobs=result.jobs||[];
  $('queueCount').textContent=`${jobs.length} queues`;
  $('jobRows').innerHTML=jobs.length?jobs.map(j=>{
    const active=j.status==='active';const id=Number(j.id);
    return `<tr><td><span class="chain-pill">${escapeHTML(chainNames[j.chain]||j.chain)}</span></td><td>${j.next_block}</td><td>${j.end_block}</td><td>${j.processed_blocks}</td><td>${j.sampled_addresses}</td><td><span class="state-pill ${j.status==='complete'?'good':''}">${escapeHTML(j.status)}</span></td><td>${active?`<button class="tiny-action" data-job-action="run" data-job-id="${id}">Run batch</button> <button class="tiny-action muted-action" data-job-action="pause" data-job-id="${id}">Pause</button>`:j.status==='paused'?`<button class="tiny-action" data-job-action="resume" data-job-id="${id}">Resume</button>`:'—'}</td></tr>`;
  }).join(''):'<tr><td colspan="7" class="empty-state">No discovery queues created.</td></tr>';
}
$('jobForm').addEventListener('submit',e=>{e.preventDefault();withLoading(e.submitter,async()=>{
  const start=Number($('jobStart').value),end=Number($('jobEnd').value);
  if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start<0||end<start||end-start>10000)throw Error('Enter an ascending block range of at most 10001 blocks.');
  await post('/api/discovery/jobs',{chain:$('jobChain').value,start_block:start,end_block:end,blocks_per_run:Number($('jobBatch').value)});
  toast('Discovery queue created. Run a batch or enable the automatic scanner.');await loadJobs();
});});
$('jobRows').addEventListener('click',e=>{
  const button=e.target.closest('[data-job-action]');if(!button)return;
  withLoading(button,async()=>{
    const id=Number(button.dataset.jobId), action=button.dataset.jobAction;
    const result=await post('/api/discovery/jobs/'+action,{job_id:id});
    toast(action==='run'?`Processed ${result.blocks_processed} block(s); sampled ${result.addresses_sampled} addresses.`:action==='resume'?'Discovery queue resumed.':'Discovery queue paused.');
    await loadWallets();
  });
});
$('activityBtn').addEventListener('click',e=>withLoading(e.currentTarget,async()=>{
  const ids=[...state.selected];if(!ids.length)throw Error('Select addresses in the watchlist first.');
  if(ids.length>5)throw Error('Activity indexing is limited to 5 wallets per request to conserve API quota.');
  const result=await post('/api/activity/scan',{ids});
  const good=result.results.filter(x=>x.status==='ok').length;
  toast(`${good} of ${ids.length} activity histories indexed; coverage may be incomplete.`,good!==ids.length);await loadWallets();
}));
$('aaveScanBtn').addEventListener('click',e=>withLoading(e.currentTarget,async()=>{
  const ids=[...state.selected];if(!ids.length)throw Error('Select addresses from the Intelligence Hub first.');
  if(ids.length>20)throw Error('Check a maximum of 20 Aave positions per request.');
  const result=await post('/api/aave/scan',{ids});
  const good=result.results.filter(x=>x.status==='ok').length;
  const candidates=result.results.filter(x=>x.candidate).length;
  toast(`${good} Aave positions read, ${candidates} preliminary risk signal(s).`,good!==ids.length);
  await loadWallets();
}));

async function loadBorrowerJobs(){
  const [jobsData,eventData]=await Promise.all([api('/api/aave/borrowers/jobs'),api('/api/aave/borrowers/events')]);
  const jobs=jobsData.jobs||[];
  $('borrowerJobCount').textContent=`${jobs.length} BORROWER QUEUES`;
  $('borrowerEventsCount').textContent=`${Number(eventData.total_events||0).toLocaleString()} historical borrowing events indexed`;
  $('borrowerJobRows').innerHTML=jobs.length?jobs.map(j=>{
    const id=Number(j.id),active=j.status==='active';
    const actions=active?`<button class="tiny-action" data-borrower-action="run" data-borrower-id="${id}">Index batch + check positions</button> <button class="tiny-action muted-action" data-borrower-action="pause" data-borrower-id="${id}">Pause</button>`:j.status==='paused'?`<button class="tiny-action" data-borrower-action="resume" data-borrower-id="${id}">Resume</button>`:'—';
    return `<tr><td><span class="chain-pill">${escapeHTML(chainNames[j.chain]||j.chain)}</span></td><td>${Number(j.next_block)}</td><td>${Number(j.end_block)}</td><td>${Number(j.scanned_blocks)}</td><td>${Number(j.borrow_events)}</td><td><span class="state-pill ${j.status==='complete'?'good':''}">${escapeHTML(j.status)}</span></td><td>${actions}</td></tr>`;
  }).join(''):'<tr><td colspan="7" class="empty-state">No borrower queues yet. Select a chain and block lookback above.</td></tr>';
}
$('borrowerJobForm').addEventListener('submit',e=>{e.preventDefault();withLoading(e.submitter,async()=>{
  const chain=$('borrowerChain').value,lookback_blocks=Number($('borrowerLookback').value),blocks_per_run=Number($('borrowerBatch').value);
  if(!Number.isSafeInteger(lookback_blocks)||lookback_blocks<1||lookback_blocks>250000)throw Error('Use 1–250000 blocks.');
  const result=await post('/api/aave/borrowers/jobs',{chain,lookback_blocks,blocks_per_run,confirmations:20});
  toast(`Aave borrower discovery created: ${result.start_block}–${result.end_block}.`);await loadBorrowerJobs();
});});
$('borrowerJobRows').addEventListener('click',e=>{
  const button=e.target.closest('[data-borrower-action]');if(!button)return;
  withLoading(button,async()=>{
    const job_id=Number(button.dataset.borrowerId),action=button.dataset.borrowerAction;
    const result=await post('/api/aave/borrowers/jobs/'+action,{job_id});
    if(action==='run'){
      const ids=result.wallet_ids||[];
      let detail='';
      if(ids.length){
        try{const check=await post('/api/aave/scan',{ids});const good=check.results.filter(x=>x.status==='ok').length;const risky=check.results.filter(x=>x.candidate).length;detail=` ${good}/${ids.length} current position checks; ${risky} preliminary risk signal(s).`;}
        catch(err){detail=' Position check unavailable; borrower events remain saved.';}
      }
      toast(`${result.blocks_processed} blocks, ${result.events_indexed} new borrow events, ${result.unique_borrowers_in_batch} borrowers.${detail}`);
    }else toast(action==='pause'?'Borrower queue paused.':'Borrower queue resumed.');
    await Promise.all([loadBorrowerJobs(),loadWallets()]);
  });
});
$('saveToken').addEventListener('click',()=>{const t=$('apiToken').value.trim();t?sessionStorage.setItem('reclaim_api_token',t):sessionStorage.removeItem('reclaim_api_token');$('apiToken').value='';toast(t?'Token set for this browser tab.':'Session token cleared.');loadWallets();});
loadWallets();
