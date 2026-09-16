/* ---------- per-person session: login / logout / history ---------- */
function historyUserKey(user){
  return String(user?.account_key||user?.email||user?.username||'').trim().toLowerCase();
}
function identityLabel(user,fallback='ผู้ใช้งาน'){
  const email=String(user?.email||'').trim();
  const accountKey=String(user?.account_key||user?.username_key||'').trim();
  if(email)return email;
  if(accountKey.includes('@'))return accountKey;
  return String(user?.username||user?.display_name||fallback).trim()||fallback;
}
function historyUserActivityMs(user){
  const timestamp=user?.history_order_utc||user?.last_session_utc||user?.created_at_utc;
  const parsed=timestamp?Date.parse(timestamp):0;
  return Number.isFinite(parsed)?parsed:0;
}
function sortHistoryUsersNewestFirst(users){
  // Keep the account currently using the Pod first, then use the latest
  // Session timestamp. Name is only a stable tie-breaker for equal timestamps.
  const activeKey=String(
    sessionState.account_key||sessionState.email||sessionState.username||''
  ).trim().toLowerCase();
  return [...(users||[])].sort((a,b)=>{
    const aActive=Boolean(a?.has_active_session)||(activeKey&&historyUserKey(a)===activeKey);
    const bActive=Boolean(b?.has_active_session)||(activeKey&&historyUserKey(b)===activeKey);
    if(aActive!==bActive)return aActive?-1:1;
    const activityDiff=historyUserActivityMs(b)-historyUserActivityMs(a);
    if(activityDiff)return activityDiff;
    return identityLabel(a,'').localeCompare(
      identityLabel(b,''),'th'
    );
  });
}
function sortHistoryUsersByEmail(users){
  // Sessions uses email as the stable identity. Local/legacy accounts follow
  // email-backed accounts; Login keeps its separate active/newest ordering.
  const key=user=>{
    const account=historyUserKey(user);
    const email=String(user?.email||(account.includes('@')?account:'')).trim().toLowerCase();
    return {email,account,label:identityLabel(user,'').toLowerCase()};
  };
  return [...(users||[])].sort((a,b)=>{
    const left=key(a),right=key(b);
    if(Boolean(left.email)!==Boolean(right.email))return left.email?-1:1;
    return (left.email||left.account).localeCompare(
      right.email||right.account,'en',{sensitivity:'base'},
    )||left.label.localeCompare(right.label,'th',{sensitivity:'base'});
  });
}
async function loadUsers(){
  const chips=document.getElementById('userChips'),sel=document.getElementById('historyUser');
  if(currentPrincipal?.role==='user'){
    chips.innerHTML='';sel.innerHTML='';
    const ownerTitle=document.getElementById('historyOwnerTitle');
    if(ownerTitle)ownerTitle.textContent=`ประวัติการใช้งานของ ${identityLabel(currentPrincipal)}`;
    if(document.body.dataset.view==='sessions')refreshHistory();
    return;
  }
  if(currentPrincipal?.role!=='admin')return;
  try {
    const r = await fetch('/api/users'); const d = await r.json();
    const ownerTitle=document.getElementById('historyOwnerTitle');
    if(ownerTitle)ownerTitle.textContent='ภาพรวมผู้ใช้งานและประวัติการพัก';
    chips.innerHTML = '';
    const kept = sel.value; sel.innerHTML = '';
    const allUsers=document.createElement('option');
    allUsers.value='';allUsers.textContent='ผู้ใช้งานทุกคน';sel.appendChild(allUsers);
    const orderedUsers=sortHistoryUsersNewestFirst(d.users);
    orderedUsers.forEach(u=>{
      const c = document.createElement('button'); c.type = 'button'; c.className = 'chip';
      c.textContent = `${identityLabel(u)} · ${genderTh(u.gender)}`;
      c.onclick = ()=>{
        document.querySelectorAll('.chip').forEach(x=>x.classList.remove('sel'));
        c.classList.add('sel');
        document.getElementById('loginName').value = u.username;
        document.getElementById('loginAgeGroup').value = u.age_group || ageToGroup(u.age);
        renderLoginBaseline();
        selectGender(u.gender);
      };
      chips.appendChild(c);
    });
    sortHistoryUsersByEmail(d.users).forEach(u=>{
      const availableSessions=Number(u.available_sessions??u.sessions??0);
      const sessionsWithoutSensor=Number(u.current_sessions_without_data??0);
      const usageSessions=Number(
        u.available_usage_sessions??(availableSessions+sessionsWithoutSensor)
      );
      if(usageSessions<=0)return;
      const o = document.createElement('option');
      o.value = u.account_key||u.email||u.username;
      const sensorNote=sessionsWithoutSensor
        ?` · ไม่มี Sensor ${sessionsWithoutSensor}`:'';
      o.textContent = `${identityLabel(u)} (${usageSessions} ครั้ง${sensorNote})`;
      sel.appendChild(o);
    });
    if (!orderedUsers.length) chips.innerHTML = '<div class="mini" style="margin-top:2px">ยังไม่มีผู้ใช้ — พิมพ์ชื่อด้านล่างเพื่อสร้างใหม่</div>';
    if (sel.options.length===1){
      const empty=document.createElement('option');
      empty.value='';empty.textContent='ยังไม่มี Session ที่จบในช่วง Pilot';empty.disabled=true;
      sel.innerHTML='';empty.selected=true;sel.appendChild(empty);
    }
    // Sessions may receive its first WebSocket frame before the admin user
    // list finishes loading. Restore the active user after options exist, then
    // load the list automatically instead of leaving a false "no user" state.
    const preferredUser=kept;
    if(preferredUser&&[...sel.options].some(option=>option.value===preferredUser))sel.value=preferredUser;
    if(document.body.dataset.view==='sessions'){
      refreshUsageUserDirectory();
      refreshHistory();
    }
  } catch {}
}

/* ---- login: บัญชี ZEEP เป็นค่าเริ่มต้น · Local เฉพาะตอนต่อ ZEEP API ไม่ได้ ---- */
let loginMode = 'zeep';
const USER_LOGIN_PATH='/login';
const ADMIN_LOGIN_PATH='/admin/login';
const QR_LOGIN_PATH='/login/qr';
const adminLoginPaths=new Set(['/admin','/admin/login','/monitor','/control-debug']);
let loginAudience = adminLoginPaths.has(location.pathname) ? 'admin' : 'user';
// bootstrapAuth() rewrites the URL to the canonical login path, so remember the
// QR request separately or the redirect would silently drop it.
let qrLoginRequested = location.pathname === QR_LOGIN_PATH;

function canonicalLoginPath(){
  if(loginAudience==='admin')return ADMIN_LOGIN_PATH;
  return qrLoginRequested?QR_LOGIN_PATH:USER_LOGIN_PATH;
}

function setLoginAudience(audience){
  loginAudience=audience==='admin'?'admin':'user';
  const admin=loginAudience==='admin',overlay=document.getElementById('login');
  overlay.dataset.audience=loginAudience;
  document.getElementById('loginTitle').textContent=admin
    ? 'เข้าสู่ระบบผู้ดูแลระบบ · ZEEP'
    : 'เข้าสู่ระบบผู้ใช้งาน · ZEEP';
  document.getElementById('loginRouteLabel').textContent=admin?'ผู้ดูแลระบบ':'ผู้ใช้งาน ZEEP';
  document.getElementById('loginRouteCaption').textContent=admin
    ? 'ตรวจสอบระบบ ควบคุม และดูข้อมูลเชิงเทคนิค'
    : 'เริ่ม Session การพักผ่อนในตู้นี้';
  document.getElementById('loginAudienceHelp').textContent=loginAudience==='admin'
    ? 'ใช้บัญชีผู้ดูแลระบบที่ได้รับอนุญาตเท่านั้น'
    : 'เข้าสู่ระบบด้วยบัญชี ZEEP';
  offlineTicket=null;offlineIdentifier='';
  setLoginMode('zeep');
  document.getElementById('loginSafety').style.display=loginAudience==='admin'?'none':'';
  document.getElementById('loginRestModeBlock').classList.toggle('login-off',loginAudience==='admin');
}

function applyRoleUI(principal){
  currentPrincipal=principal||null;
  const roleBadge=document.getElementById('roleBadge');
  if(!principal){
    delete document.body.dataset.role;
    if(roleBadge)roleBadge.style.display='none';
    const accountLogout=document.getElementById('accountLogoutBtn');
    if(accountLogout)accountLogout.style.display='none';
    return;
  }
  document.body.dataset.role=principal.role;
  // Avoid repeating USER in the header. Admin remains explicit because that
  // role exposes Monitor and Control Debug capabilities.
  if(roleBadge){
    roleBadge.textContent='ADMIN';
    roleBadge.style.display=principal.role==='admin'?'':'none';
  }
  document.getElementById('accountLogoutBtn').style.display='';
  if(principal.role!=='admin'&&['monitor','control_debug'].includes(document.body.dataset.view)){
    history.replaceState({},'', '/dashboard');applyPageView();
  }
}

function setLoginMode(mode){
  if(loginAudience==='admin')mode='zeep';
  loginMode = mode;
  const zeep = mode === 'zeep', local = mode === 'local', qr = mode === 'qr';
  document.getElementById('loginPaneZeep').classList.toggle('login-off', !zeep);
  document.getElementById('loginPaneLocal').classList.toggle('login-off', !local);
  document.getElementById('loginPaneQr').classList.toggle('login-off', !qr);
  // โหมด ZEEP/QR ดึงช่วงอายุจากโปรไฟล์ให้เอง — โชว์ตัวเลือกเฉพาะเมื่อ server ขอมา
  document.getElementById('loginAgeBlock').classList.toggle('login-off', !local);
  // QR ไม่มีปุ่มส่ง: มือถือเป็นฝ่ายยืนยัน แล้วหน้านี้ poll รอผลเอง
  document.getElementById('loginStartBtn').classList.toggle('login-off', qr);
  document.getElementById('loginStartBtn').textContent = loginAudience==='admin'
    ? 'เข้าสู่ระบบผู้ดูแล'
    : zeep ? 'เข้าสู่ระบบและเริ่มพัก' : 'เริ่มพักแบบออฟไลน์';
  document.getElementById('loginModeLink').textContent = zeep
    ? 'หากยังเชื่อมบัญชีไม่ได้ ใช้งานแบบออฟไลน์'
    : '← กลับไปเข้าสู่ระบบด้วยบัญชี ZEEP';
  document.getElementById('loginModeLink').classList.toggle(
    'login-off',loginAudience==='admin'||qr||(zeep&&!offlineTicket)
  );
  document.getElementById('loginQrLink').textContent = qr
    ? '← เข้าสู่ระบบด้วยรหัสผ่าน'
    : 'สแกน QR ด้วยแอป ZEEP แทนการพิมพ์รหัสผ่าน';
  document.getElementById('loginQrLink').classList.toggle(
    'login-off',loginAudience==='admin'||local
  );
  showLoginError('');
  const overlay = document.getElementById('login');
  if (overlay && !overlay.classList.contains('hide') && !qr){
    document.getElementById(zeep ? 'loginIdentifier' : 'loginName').focus();
  }
  renderRestModeHint();
  // ขอ QR เฉพาะตอนการ์ด login โผล่จริง ๆ — ZEEP จำกัดจำนวน session ต่อ IP และ
  // ทุกแท็บเล็ตในตู้ออกเน็ตด้วย IP เดียวกัน
  if (qr){
    if (overlay && !overlay.classList.contains('hide')) startQrSession();
  } else {
    resetQrView();
  }
}

function selectedRestIntent(){
  const mode=document.getElementById('loginRestMode')?.value||'nap_recovery';
  const requested=Number(document.getElementById('loginNapTarget')?.value);
  const napTarget=requested===90?90:30;
  return {
    rest_mode:mode,
    target_duration_minutes:mode==='nap_recovery'?napTarget:null,
  };
}

function renderRestModeHint(){
  const hint=document.getElementById('loginRestModeHint');
  const targetBlock=document.getElementById('loginNapTargetBlock');
  if(!hint||!targetBlock)return;
  const intent=selectedRestIntent(),isNap=intent.rest_mode==='nap_recovery';
  targetBlock.classList.toggle('login-off',!isNap);
  if(!isNap){
    hint.textContent='เหมาะกับการพักค้างคืนประมาณ 5 ชั่วโมงขึ้นไป · สรุปความต่อเนื่องและรูปแบบการนอน';
    return;
  }
  hint.textContent=intent.target_duration_minutes===90
    ?'พัก 90 นาที · จะหลับหรือพักอย่างเป็นธรรมชาติก็ได้'
    :'พัก 30 นาที · จะหลับ พักสายตา หรือทำสมาธิก็ได้';
}
function toggleLoginMode(){
  if(loginAudience==='user'&&offlineTicket)setLoginMode(loginMode === 'zeep' ? 'local' : 'zeep');
}

/* ---- login ด้วย QR ----------------------------------------------------------
   Pi เป็นฝ่ายคุยกับ ZEEP ให้ เพราะแท็บเล็ตอยู่บน hotspot ที่ออกเน็ตไม่ได้ ผลพลอยได้คือ
   pollSecret ไม่เคยลงมาถึงหน้านี้ คนที่ถ่ายรูป QR ไปจึงเอาไป poll เอา token ไม่ได้ */
const QR_POLL_MS = 2000;
let qrLogin = {loginId:null, timer:null, expiresAt:0};

function setQrStatus(message, tone){
  const el = document.getElementById('loginQrStatus');
  if (!el) return;
  el.textContent = message || '';
  el.className = `login-qr-status${tone ? ' ' + tone : ''}`;
}

function showQrRetry(label){
  const btn = document.getElementById('loginQrRetry');
  if (!btn) return;
  btn.textContent = label || 'ขอ QR ใหม่';
  btn.classList.remove('login-off');
}

function stopQrPolling(){
  if (qrLogin.timer){ clearTimeout(qrLogin.timer); qrLogin.timer = null; }
}

function resetQrView(){
  stopQrPolling();
  qrLogin = {loginId:null, timer:null, expiresAt:0};
  const img = document.getElementById('loginQrImage');
  if (img){ img.removeAttribute('src'); img.classList.add('login-off'); }
  const btn = document.getElementById('loginQrRetry');
  if (btn) btn.classList.add('login-off');
  setQrStatus('');
}

function qrSecondsLeft(){
  return Math.max(0, Math.ceil((qrLogin.expiresAt - Date.now()) / 1000));
}

function qrErrorFrom(response, body){
  const detail = body && body.detail, obj = detail && typeof detail === 'object';
  const code = obj ? detail.code : null;
  const userMessages={
    pod_already_occupied:'ZEEP กำลังมีผู้ใช้งาน กรุณารอให้การพักครั้งนี้จบก่อน',
    offline:'ตอนนี้ยังเชื่อมต่อบัญชี ZEEP ไม่ได้ ระบบจะลองใหม่ให้',
    age_group_required:'กรุณาเลือกช่วงอายุเพื่อเตรียมผลให้เหมาะกับคุณ',
    profile_incomplete:'กรอกข้อมูลสุขภาพพื้นฐานก่อนเริ่มการพัก',
    expired:'QR หมดอายุแล้ว กรุณาขอ QR ใหม่',
  };
  return {
    code,
    detail: obj ? detail : null,
    message:userMessages[code]||'ยังเชื่อมต่อด้วย QR ไม่ได้ กรุณาลองอีกครั้ง',
  };
}

async function startQrSession(){
  resetQrView();
  setQrStatus('กำลังขอ QR จาก ZEEP…');
  let r, d = null;
  try { r = await fetch('/api/auth/qr/session', {method:'POST'}); }
  catch { setQrStatus('ยังเชื่อมต่อระบบไม่ได้ กรุณาลองอีกครั้ง','danger'); showQrRetry(); return; }
  try { d = await r.json(); } catch {}
  if (!r.ok){
    const err = qrErrorFrom(r, d);
    setQrStatus(err.message, err.code === 'pod_already_occupied' ? 'warning' : 'danger');
    showQrRetry();
    return;
  }
  qrLogin.loginId = d.login_id;
  qrLogin.expiresAt = Date.now() + (Number(d.expires_in) || 180) * 1000;
  const img = document.getElementById('loginQrImage');
  img.src = d.qr_code;
  img.classList.remove('login-off');
  setQrStatus('เปิดแอป ZEEP บนมือถือแล้วสแกน QR นี้');
  qrLogin.timer = setTimeout(pollQrLogin, QR_POLL_MS);
}

async function pollQrLogin(){
  qrLogin.timer = null;
  if (!qrLogin.loginId) return;
  const body = {login_id:qrLogin.loginId, ...selectedRestIntent()};
  const ageBlock = document.getElementById('loginAgeBlock');
  if (!ageBlock.classList.contains('login-off')){
    const ageGroup = document.getElementById('loginAgeGroup').value;
    if (ageGroup) body.age_group = ageGroup;
  }
  let r, d = null;
  try {
    r = await fetch('/api/auth/qr/poll', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body),
    });
  } catch {
    setQrStatus('การเชื่อมต่อสะดุด ระบบกำลังลองใหม่ให้','warning');
    qrLogin.timer = setTimeout(pollQrLogin, QR_POLL_MS);
    return;
  }
  try { d = await r.json(); } catch {}
  if (!r.ok){
    const err = qrErrorFrom(r, d);
    if (err.code === 'offline'){
      // Pi ยังรับคำขอได้ แต่ ZEEP ตอบไม่ได้ชั่วคราว — QR ยังไม่หมดอายุ จึง poll ต่อ
      setQrStatus(err.message,'warning');
      qrLogin.timer = setTimeout(pollQrLogin, QR_POLL_MS);
      return;
    }
    if (err.code === 'profile_incomplete'){
      // QR ใบนี้ถูกใช้ไปแล้ว แต่ ticket ถือ token ของรอบนี้ไว้ให้ → กรอกฟอร์ม
      // แล้วเข้าได้เลย ไม่ต้องสแกนใหม่
      qrLogin.loginId = null;
      resetQrView();
      openProfileGate(err.detail);
      return;
    }
    if (err.code === 'age_group_required'){
      // ZEEP ใช้ QR ใบนี้ไปแล้ว → เลือกช่วงอายุแล้วต้องสแกนใบใหม่
      qrLogin.loginId = null;
      ageBlock.classList.remove('login-off');
      renderLoginBaseline();
      setQrStatus(`${err.message} · เลือกช่วงอายุแล้วขอ QR ใหม่`,'warning');
      showQrRetry();
      document.getElementById('loginAgeGroup').focus();
      return;
    }
    qrLogin.loginId = null;
    setQrStatus(err.message, err.code === 'pod_already_occupied' ? 'warning' : 'danger');
    showQrRetry();
    return;
  }
  if (d.state === 'approved'){
    qrLogin.loginId = null;
    resetQrView();
    afterLoginStarted(d, `เข้าสู่ระบบด้วย QR: ${identityLabel(d.user||d.session)}`);
    return;
  }
  if (d.state === 'rejected'){
    qrLogin.loginId = null;
    setQrStatus('ยังไม่ได้ยืนยันการเข้าสู่ระบบจากโทรศัพท์','warning');
    showQrRetry();
    return;
  }
  if (d.state === 'expired' || qrSecondsLeft() <= 0){
    qrLogin.loginId = null;
    setQrStatus('QR หมดอายุแล้ว','warning');
    showQrRetry();
    return;
  }
  if (d.state === 'scanned'){
    // ต้องโชว์ชื่อบัญชีที่สแกน เพื่อให้คนหน้าตู้จับได้ถ้ามีคนอื่นเอา QR ไปสแกน
    const who = (d.scanned_by && d.scanned_by.display_name) || 'บัญชี ZEEP';
    setQrStatus(`${who} สแกนแล้ว · กดยืนยันในแอปเพื่อเริ่ม`,'warning');
    showQrRetry('ไม่ใช่ฉัน · ขอ QR ใหม่');
  } else {
    setQrStatus(`เปิดแอป ZEEP บนมือถือแล้วสแกน QR นี้ · เหลือ ${qrSecondsLeft()} วิ`);
  }
  qrLogin.timer = setTimeout(pollQrLogin, QR_POLL_MS);
}

/* ---------- ข้อมูลสุขภาพพื้นฐาน: บัญชี ZEEP ที่ยังกรอกไม่ครบต้องกรอกก่อนเริ่มพัก
   ตู้ยังไม่ถูกจอง และยังไม่มี cookie จนกว่าฟอร์มนี้จะผ่าน — ticket คือสิ่งเดียวที่
   ผูกฟอร์มกับ Login ที่ยืนยันตัวตนไปแล้ว (QR สแกนซ้ำไม่ได้) ---------- */
let profileGate = {ticket:null, gender:'', blood:''};

function fillDobOptions(){
  // ช่วงปีตรงกับที่ Session ยอมรับ (อายุ 18–100 ปี) — เลือกปี พ.ศ. ไม่ได้อยู่แล้ว
  const year = document.getElementById('profileDobYear');
  const thisYear = new Date().getFullYear();
  year.innerHTML = '<option value="">ปี ค.ศ.</option>';
  for (let y = thisYear - 18; y >= thisYear - 100; y--) year.add(new Option(String(y), String(y)));
  refreshDobDays();
}

// จำนวนวันของเดือนที่เลือก · ยังไม่เลือกปี → เผื่อ 29 ไว้ก่อนด้วยปีอธิกสุรทิน
// แล้วค่อยตัดทิ้งตอนผู้ใช้เลือกปีจริง
function dobDaysInMonth(){
  const m = Number(document.getElementById('profileDobMonth').value);
  if (!m) return 31;
  return new Date(Number(document.getElementById('profileDobYear').value) || 2000, m, 0).getDate();
}

// เรียกทุกครั้งที่เดือนหรือปีเปลี่ยน เพื่อไม่ให้เลือกวันที่ไม่มีอยู่จริงได้เลย
// (31 กุมภาพันธ์, 31 เมษายน, 29 กุมภาพันธ์ ในปีที่ไม่ใช่อธิกสุรทิน)
function refreshDobDays(){
  const day = document.getElementById('profileDobDay');
  const chosen = day.value, days = dobDaysInMonth();
  day.innerHTML = '<option value="">วัน</option>';
  for (let d = 1; d <= days; d++) day.add(new Option(String(d), String(d)));
  // วันที่เคยเลือกไว้หลุดช่วง → ล้างทิ้ง ไม่เดาวันเกิดให้ผู้ใช้เอง
  day.value = (chosen && Number(chosen) <= days) ? chosen : '';
}

// วัน/เดือน/ปี → ISO ที่ server รับ · คืน '' เมื่อยังเลือกไม่ครบ
function profileDobValue(){
  const d = document.getElementById('profileDobDay').value;
  const m = document.getElementById('profileDobMonth').value;
  const y = document.getElementById('profileDobYear').value;
  if (!d || !m || !y) return '';
  const pad = n => String(n).padStart(2, '0');
  return `${y}-${pad(m)}-${pad(d)}`;
}

function openProfileGate(detail){
  profileGate.ticket = (detail && detail.profile_ticket) || null;
  fillDobOptions();
  ['profileDobMonth','profileHeight','profileWeight'].forEach(id=>{
    document.getElementById(id).value = '';
  });
  selectProfileGender('');
  selectProfileBlood('');
  showProfileError('');
  document.getElementById('profileModal').classList.remove('hide');
}

function closeProfileGate(){
  profileGate.ticket = null;
  document.getElementById('profileModal').classList.add('hide');
}

function selectProfileGender(value){
  profileGate.gender = value;
  document.querySelectorAll('#profileGenderSeg button').forEach(b=>{
    b.classList.toggle('sel', b.dataset.g === value);
  });
}

function selectProfileBlood(value){
  profileGate.blood = value;
  document.querySelectorAll('#profileBloodSeg button').forEach(b=>{
    b.classList.toggle('sel', b.dataset.b === value);
  });
}

function showProfileError(message, tone = 'danger'){
  const el = document.getElementById('profileError');
  if (!el) return;
  el.textContent = message || '';
  el.className = `login-safety ${tone}${message ? '' : ' login-off'}`;
  // แถบ error ดันปุ่มบันทึกลงไปได้ — เลื่อนให้เห็นทั้งคู่ ไม่ให้ดูเหมือนกดแล้วเงียบ
  if (message) el.scrollIntoView({block:'end', behavior:'smooth'});
}

async function submitProfileForm(btn){
  if (!profileGate.ticket){ showProfileError('แบบฟอร์มหมดอายุแล้ว — เข้าสู่ระบบอีกครั้ง'); return; }
  const dob = profileDobValue();
  const height = Number(document.getElementById('profileHeight').value);
  const weight = Number(document.getElementById('profileWeight').value);
  if (!profileGate.gender){ showProfileError('เลือกเพศก่อน'); return; }
  if (!dob){ showProfileError('เลือกวันเกิดให้ครบ'); return; }
  if (!(height > 0) || !(weight > 0)){ showProfileError('กรอกส่วนสูงและน้ำหนักให้ครบ'); return; }
  const body = {
    profile_ticket:profileGate.ticket, gender:profileGate.gender, date_of_birth:dob,
    height_cm:height, weight_kg:weight, blood_group:profileGate.blood || null,
    ...selectedRestIntent(),
  };
  await withBusy(btn, async ()=>{
    let r, d = null;
    try {
      r = await fetch('/api/auth/profile/complete', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body),
      });
    } catch { showProfileError('ยังเชื่อมต่อระบบไม่ได้ กรุณาลองอีกครั้ง'); return; }
    try { d = await r.json(); } catch {}
    if (!r.ok){
      const detail = d && d.detail, obj = detail && typeof detail === 'object';
      // ข้อผิดพลาดที่ลองใหม่ได้จะแนบ ticket ใบใหม่มาด้วย → แก้เฉพาะช่องที่ผิด
      // แล้วกดซ้ำได้ ไม่ต้องเข้าสู่ระบบหรือสแกน QR ใหม่
      profileGate.ticket = (obj && detail.profile_ticket) || null;
      showProfileError(
        (obj ? detail.message : detail) || 'บันทึกข้อมูลไม่สำเร็จ กรุณาลองอีกครั้ง',
        obj && detail.code === 'profile_update_offline' ? 'warning' : 'danger',
      );
      return;
    }
    closeProfileGate();
    afterLoginStarted(d, `เข้าสู่ระบบ: ${identityLabel(d.user||d.session)}`);
  });
}

function toggleQrLogin(){
  if (loginAudience === 'admin') return;
  qrLoginRequested = loginMode !== 'qr';
  history.replaceState({},'', canonicalLoginPath());
  setLoginMode(qrLoginRequested ? 'qr' : 'zeep');
}

function showLoginError(message, tone = 'danger'){
  const el = document.getElementById('loginError');
  if (!el) return;
  el.textContent = message || '';
  el.className = `login-safety ${tone}${message ? '' : ' login-off'}`;
}

function toggleLoginPassword(){
  const input = document.getElementById('loginPassword'), btn = document.getElementById('loginPwToggle');
  const reveal = input.type === 'password';
  input.type = reveal ? 'text' : 'password';
  btn.textContent = reveal ? 'ซ่อน' : 'แสดง';
}

async function submitLogin(btn){
  showLoginError('');
  if(loginAudience==='admin')return doAdminLogin(btn);
  // Login/session creation is always available; Safety separately guards
  // automatic response and physical device commands.
  return loginMode === 'zeep' ? doZeepLogin(btn) : doLocalLogin(btn);
}

async function doAdminLogin(btn){
  const identifier=document.getElementById('loginIdentifier').value.trim();
  const password=document.getElementById('loginPassword').value;
  if(!identifier||!password){showLoginError('กรอกอีเมลหรือชื่อผู้ใช้และรหัสผ่านให้ครบ');return;}
  await withBusy(btn,async()=>{
    let r;
    try{
      r=await fetch('/api/admin/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({identifier,password})});
    }catch{showLoginError('ต่อ server ของตู้ไม่ได้');return;}
    let d={};try{d=await r.json();}catch{}
    if(!r.ok){
      const detail=d.detail;
      showLoginError(typeof detail==='object'?detail.message:detail||`HTTP ${r.status}`);
      return;
    }
    document.getElementById('loginPassword').value='';
    authPod={occupied:false,owns_active_session:false};
    applyRoleUI(d.principal);
    document.getElementById('login').classList.add('hide');
    history.replaceState({},'', '/admin');applyPageView();
    startAuthenticatedApp();
    toast(`เข้าสู่ระบบผู้ดูแล: ${d.principal.display_name}`,'ok');
  });
}

function userLoginFailure(code,status){
  const messages={
    offline:'ตอนนี้ยังเชื่อมต่อบัญชี ZEEP ไม่ได้ คุณสามารถเลือกใช้งานแบบออฟไลน์ได้',
    age_group_required:'กรุณาเลือกช่วงอายุเพื่อเตรียมผลให้เหมาะกับคุณ',
    profile_incomplete:'กรอกข้อมูลสุขภาพพื้นฐานก่อนเริ่มการพัก',
    pod_already_occupied:'ZEEP กำลังมีผู้ใช้งาน กรุณารอให้การพักครั้งนี้จบก่อน',
    invalid_credentials:'อีเมลหรือรหัสผ่านไม่ถูกต้อง กรุณาลองอีกครั้ง',
  };
  if(messages[code])return messages[code];
  if(status===401)return 'อีเมลหรือรหัสผ่านไม่ถูกต้อง กรุณาลองอีกครั้ง';
  if(status>=500)return 'ระบบกำลังกลับมาทำงาน กรุณาลองอีกครั้ง';
  return 'เข้าสู่ระบบไม่สำเร็จ กรุณาตรวจข้อมูลแล้วลองอีกครั้ง';
}

async function doZeepLogin(btn){
  const identifier = document.getElementById('loginIdentifier').value.trim();
  const password = document.getElementById('loginPassword').value;
  if (!identifier || !password){ showLoginError('กรอกอีเมลหรือชื่อผู้ใช้และรหัสผ่านให้ครบ'); return; }
  const ageBlock = document.getElementById('loginAgeBlock');
  const body = {identifier, password, ...selectedRestIntent()};
  // ช่องช่วงอายุจะโผล่เฉพาะรอบที่ server ตอบ age_group_required มา → ส่งกลับไปด้วย
  if (!ageBlock.classList.contains('login-off')){
    const ageGroup = document.getElementById('loginAgeGroup').value;
    if (!ageGroup){ showLoginError('เลือกช่วงอายุก่อนเข้าสู่ระบบ'); return; }
    body.age_group = ageGroup;
  }
  // ไม่ใช้ post() เพราะต้องอ่าน error code จริง (post() กลืน 401 เป็นเรื่อง X-Api-Token)
  await withBusy(btn, async ()=>{
    const opt = {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)};
    let r;
    try { r = await fetch('/api/auth/login', opt); }
    catch { showLoginError('ยังเชื่อมต่อระบบไม่ได้ กรุณาลองอีกครั้ง'); return; }
    let d = null;
    try { d = await r.json(); } catch {}
    if (!r.ok){
      const detail = d && d.detail, obj = detail && typeof detail === 'object';
      const code = obj ? detail.code : null;
      const msg = userLoginFailure(code,r.status);
      if (code === 'offline'){
        offlineTicket=detail.offline_ticket||null;offlineIdentifier=detail.identifier||identifier;
        document.getElementById('loginName').value=(offlineIdentifier.split('@')[0]||offlineIdentifier).slice(0,40);
        document.getElementById('loginModeLink').classList.remove('login-off');
        showLoginError(`${msg}`, 'warning');
      } else if (code === 'profile_incomplete'){
        openProfileGate(detail);
      } else if (code === 'age_group_required'){
        ageBlock.classList.remove('login-off');
        renderLoginBaseline();
        showLoginError(msg, 'warning');
        document.getElementById('loginAgeGroup').focus();
      } else {
        showLoginError(msg);
      }
      return;
    }
    document.getElementById('loginPassword').value = '';
    afterLoginStarted(d, `เข้าสู่ระบบ: ${identityLabel(d.user||d.session)}`);
  });
}

async function doLocalLogin(btn){
  const name = document.getElementById('loginName').value.trim();
  const ageGroup = document.getElementById('loginAgeGroup').value;
  if (name.length < 2){ showLoginError('พิมพ์ชื่ออย่างน้อย 2 ตัวอักษร'); return; }
  if (!ageGroup){ showLoginError('กรุณาเลือกช่วงอายุก่อนเริ่มการพัก'); return; }
  await withBusy(btn, async ()=>{
    let response;
    try{
      response=await fetch('/api/session/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
        username:name,gender:selectedGender,age_group:ageGroup,offline_ticket:offlineTicket,
        offline_identifier:offlineIdentifier,...selectedRestIntent()
      })});
    }catch{showLoginError('ยังเชื่อมต่อระบบไม่ได้ กรุณาลองอีกครั้ง');return;}
    let result={};try{result=await response.json();}catch{}
    if(!response.ok){
      showLoginError(userLoginFailure(null,response.status));return;
    }
    afterLoginStarted(result, 'เริ่มการพักแบบออฟไลน์เรียบร้อยแล้ว');
  });
}

function afterLoginStarted(r, message){
  offlineTicket=null;offlineIdentifier='';
  authPod={occupied:true,owns_active_session:true,session_id:r.session?.session_id};
  applyRoleUI(r.principal||{
    role:'user',username:r.session?.username,email:r.session?.email,
    account_key:r.session?.account_key,display_name:r.session?.display_name||r.session?.username
  });
  document.getElementById('login').classList.add('hide');
  history.replaceState({},'', '/dashboard');applyPageView();
  startAuthenticatedApp();
  toast(message,'ok',2600);
  loadUsers();
  const sel = document.getElementById('historyUser');
  if (sel){ sel.value = r.session.account_key||r.session.email||r.session.username; refreshHistory(); }
}
