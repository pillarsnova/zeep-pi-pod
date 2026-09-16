/* ---------- Admin person-level usage directory ---------- */
let usageUserDirectory=null;
let usageUserDirectorySavedAt=0;
const USAGE_USER_DIRECTORY_CACHE_MS=30000;

function usageUserModeLine(mode,label,scoreTitle){
  const count=Number(mode?.session_count||0);
  const latest=mode?.latest_score;
  const score=latest===null||latest===undefined
    ?'ยังไม่มีคะแนน':`${scoreTitle} ล่าสุด ${historyEscape(latest)}`;
  return `<span><b>${historyEscape(label)} ${count} ครั้ง</b><small>${score}</small></span>`;
}

function renderUsageUserDirectory(payload){
  const summaryRoot=document.getElementById('historyPeopleSummary');
  const grid=document.getElementById('historyPeopleGrid');
  if(!summaryRoot||!grid)return;
  usageUserDirectory=payload||{};
  const summary=usageUserDirectory.summary||{};
  summaryRoot.innerHTML=`<div><span>ผู้ใช้งาน</span><b>${summary.user_count||0}</b><small>บัญชีทั้งหมด</small></div>
    <div><span>เข้าใช้งานแล้ว</span><b>${summary.users_with_sessions||0}</b><small>คน</small></div>
    <div><span>การพักทั้งหมด</span><b>${summary.usage_count||0}</b><small>ครั้ง</small></div>
    <div><span>Overnight</span><b>${summary.overnight_count||0}</b><small>ครั้ง</small></div>
    <div><span>Nap & Refresh</span><b>${summary.nap_recovery_count||0}</b><small>ครั้ง</small></div>`;
  const users=Array.isArray(usageUserDirectory.users)?usageUserDirectory.users:[];
  if(!users.length){
    grid.innerHTML='<div class="history-people-empty"><b>ยังไม่มีผู้ใช้งาน</b><span>บัญชีจะแสดงที่นี่หลังเชื่อมต่อ Profile</span></div>';
    return;
  }
  grid.innerHTML=users.map((entry,index)=>{
    const user=entry.user||{};
    const account=user.canonical_identifier||'';
    const email=user.email||account||'บัญชี Local';
    const displayName=user.display_name&&user.display_name!==email
      ?user.display_name:'';
    const count=Number(entry.usage_count||0);
    const missing=Number(entry.without_sensor_data_count||0);
    const last=count?fmtDateTh(entry.last_used_at_utc):'ยังไม่เคยใช้งาน';
    const modes=entry.modes||{};
    return `<article class="history-person-card" data-user-search="${historyEscape(`${email} ${displayName}`.toLowerCase())}" style="--person-order:${index}">
      <div class="history-person-identity"><span class="history-person-avatar" aria-hidden="true">${historyEscape((displayName||email).trim().slice(0,1).toUpperCase()||'Z')}</span><div><b title="${historyEscape(email)}">${historyEscape(email)}</b>${displayName?`<small>${historyEscape(displayName)}</small>`:''}</div></div>
      <div class="history-person-usage"><strong>${count}</strong><span>ครั้งที่ใช้งาน<small>ล่าสุด ${historyEscape(last)}</small></span></div>
      <div class="history-person-modes">${usageUserModeLine(modes.sleep,'Overnight','Sleep Score')}${usageUserModeLine(modes.nap_recovery,'Nap & Refresh','Recovery Score')}</div>
      ${missing?`<div class="history-person-note">ไม่มีข้อมูล Sensor ${missing} ครั้ง</div>`:''}
      <button type="button" class="history-person-action" data-account="${historyEscape(account)}" ${count?'':'disabled'} onclick="openUsageUserHistory(this.dataset.account)">${count?'ดูประวัติของคนนี้':'ยังไม่มีประวัติ'}</button>
    </article>`;
  }).join('');
  filterUsageUserDirectory();
}

function filterUsageUserDirectory(){
  const query=String(document.getElementById('historyPeopleSearch')?.value||'')
    .trim().toLowerCase();
  document.querySelectorAll('#historyPeopleGrid .history-person-card').forEach(card=>{
    card.hidden=Boolean(query&&!String(card.dataset.userSearch||'').includes(query));
  });
}

async function refreshUsageUserDirectory(force=false){
  if(currentPrincipal?.role!=='admin'||document.body.dataset.view!=='sessions')return;
  const summaryRoot=document.getElementById('historyPeopleSummary');
  const grid=document.getElementById('historyPeopleGrid');
  if(!summaryRoot||!grid)return;
  if(!force&&usageUserDirectory&&Date.now()-usageUserDirectorySavedAt<USAGE_USER_DIRECTORY_CACHE_MS){
    renderUsageUserDirectory(usageUserDirectory);return;
  }
  summaryRoot.innerHTML='<div class="mini">กำลังรวมข้อมูลผู้ใช้งาน…</div>';
  grid.innerHTML='';
  try{
    const response=await fetch('/api/v1/usage-sessions/users',{cache:'no-store'});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    const payload=(await response.json()).data||{};
    usageUserDirectorySavedAt=Date.now();
    renderUsageUserDirectory(payload);
  }catch{
    summaryRoot.innerHTML='<div class="history-people-empty"><b>ยังรวมข้อมูลผู้ใช้งานไม่ได้</b><span>รายการ Session ด้านล่างยังใช้งานได้ตามปกติ</span></div>';
  }
}

function openUsageUserHistory(account){
  if(!account)return;
  const select=document.getElementById('historyUser');
  if(!select)return;
  if(![...select.options].some(option=>option.value===account)){
    const option=document.createElement('option');option.value=account;option.textContent=account;
    select.appendChild(option);
  }
  select.value=account;
  const query=document.getElementById('historyNameFilter');if(query)query.value='';
  const historyStart=usageUserDirectory?.history_start_utc;
  const start=historyStart?historyLocalDate(historyStart):'';
  if(start)document.getElementById('historyDateFrom').value=start;
  document.getElementById('historyDateTo').value=historyLocalToday();
  document.getElementById('historyTimeFrom').value='00:00';
  document.getElementById('historyTimeTo').value='23:59';
  refreshHistory().then(()=>document.querySelector('.history-list-section')?.scrollIntoView({behavior:'smooth',block:'start'}));
}
