/* ---- จบ Session: สรุปผลบนจอตู้ + QR ให้ผู้ใช้เอาผลกลับไปเอง ----
   จอตู้เป็นจอรวม ผู้ใช้จึงเห็นผลคืนนี้ได้แค่ตรงนี้ที่เดียว. แท็บเล็ตอยู่บน hotspot
   ที่ออกอินเทอร์เน็ตไม่ได้ จึงวาดรูปเองด้วย Canvas (เบราว์เซอร์จัดรูปภาษาไทยได้ถูก
   โดยไม่ต้องฝังฟอนต์) แล้วให้ Pi เป็นคนอัปโหลดและสร้าง QR ให้ */
// หน้าจอนี้อยู่ได้นานเท่าที่ลิงก์ใน QR ยังสแกนได้จริง: ผู้ใช้ที่ลุกไปล้างหน้าแล้ว
// กลับมาสแกนต้องยังทัน. เริ่มที่ค่าสั้นก่อน แล้วขยายเมื่อ QR ขึ้นจริงเท่านั้น —
// ถ้าสร้าง QR ไม่สำเร็จก็ไม่มีอะไรให้รอ และไม่ควรทิ้งชื่อ + ผลการนอนไว้บนจอรวม
const SESSION_END_NO_QR_HOLD_MS=180000;
const SESSION_END_QR_FALLBACK_MINUTES=60;
const REPORT_PNG_FONT='"Noto Sans Thai","Inter",system-ui,sans-serif';
const REPORT_PNG_FINDING_COLOR={critical:'#ff5f6d',poor:'#f6785a',fair:'#f6b94a',good:'#4fd39b',excellent:'#19e3ff',unavailable:'#7fa6b8'};
let featureReportShare=false;
// ธง: WS จะปิด 4403 ระหว่างที่ finalize ยังทำงานอยู่ — เป็นเรื่องปกติของ flow นี้
// ไม่ใช่การถูก Admin ไล่ออก จึงต้องไม่พาออกจากหน้าจอก่อน QR มาถึง
let sessionEndInProgress=false;
// overlay มาถึงได้สองทาง (response ของ logout / WS session_ended) — อันแรกชนะ
let sessionEndShown=false;
let sessionEndTimer=null;
let sessionEndDeadline=0;

function sessionEndDateText(iso){
  const d=iso?new Date(iso):new Date();
  if(isNaN(d))return '';
  try{return d.toLocaleString('th-TH',{dateStyle:'long',timeStyle:'short'});}
  catch{return d.toISOString().slice(0,16).replace('T',' ');}
}

function closeSessionEndScreen(){
  if(sessionEndTimer){clearInterval(sessionEndTimer);sessionEndTimer=null;}
  location.replace('/login?logged_out=session_saved');
}

// เรียกได้จากทั้ง user path และ admin path · คืน true เมื่อรับช่วงหน้าจอไปแล้ว
function showSessionEndScreen(payload){
  if(sessionEndShown)return true;
  if(!featureReportShare||payload?.session_report?.available!==true)return false;
  sessionEndShown=true;sessionEndInProgress=true;
  currentPrincipal=null;authenticatedAppStarted=false;
  authPod={occupied:false,owns_active_session:false};
  sessionState={...sessionState,active:false,recording:false};
  stopRestFallback();clearTimeout(wsReconnectTimer);
  if(activeWS?.readyState===WebSocket.OPEN)activeWS.close();
  renderSessionEndScreen(payload);
  runSessionEndShare(payload);
  return true;
}

function renderSessionEndScreen(payload){
  const overlay=document.getElementById('sessionEndScreen');
  const presentation=reportPresentationMode(payload.session_report||payload);
  const resultSummaryHtml=renderRestoreSummary(
    payload,presentation,payload.ended_at_utc||true,
  );
  document.getElementById('sessionEndMeta').textContent=[
    payload.display_name||payload.username||'ผู้ใช้งาน',
    sessionEndDateText(payload.ended_at_utc),
    `ระยะเวลา ${fmtDur(payload.duration_s)}`,
  ].filter(Boolean).join(' · ');
  document.getElementById('sessionEndSummary').innerHTML=
    resultSummaryHtml
    +renderSessionOverview(payload.session_report,Boolean(resultSummaryHtml));
  overlay.classList.remove('hide');overlay.setAttribute('aria-hidden','false');
  const label=document.getElementById('sessionEndCountdown');
  sessionEndDeadline=Date.now()+SESSION_END_NO_QR_HOLD_MS;
  const tick=()=>{
    const left=Math.max(0,Math.round((sessionEndDeadline-Date.now())/1000));
    // นาทีสุดท้าย ๆ เท่านั้นที่ควรนับถอยหลังเป็นวินาที ก่อนหน้านั้นบอกเป็นอายุ
    // ของ QR ซึ่งเป็นสิ่งที่ผู้ใช้สนใจจริง ไม่ใช่เวลาที่จอจะดับ
    label.textContent=left>300
      ? `QR ใช้ได้อีก ${Math.ceil(left/60)} นาที`
      : `หน้าจอนี้จะปิดเองใน ${Math.floor(left/60)}:${String(left%60).padStart(2,'0')}`;
    if(left<=0)closeSessionEndScreen();
  };
  tick();sessionEndTimer=setInterval(tick,1000);
}

function setSessionEndQr(state,html){
  const box=document.getElementById('sessionEndQr');
  box.className=`session-end-qr ${state}`;box.innerHTML=html;
}

async function runSessionEndShare(payload){
  const note=document.getElementById('sessionEndShareNote');
  const ticket=payload?.report_share?.ticket;
  const fallback='ดูผลย้อนหลังได้ในแอป ZEEP ด้วยบัญชีเดิม';
  if(!ticket){setSessionEndQr('failed','QR สำหรับผลครั้งนี้ยังไม่พร้อม<br>ทีมงานช่วยตรวจสอบผลให้ได้');return;}
  let image;
  try{image=await drawSessionReportPng(payload);}
  catch{setSessionEndQr('failed',`ยังเตรียมรูปสรุปไม่ได้<br>${fallback}`);return;}
  let result=null;
  try{
    // ไม่ใช้ post(): cookie ถูกเพิกถอนไปแล้ว ticket คือสิทธิ์ และความล้มเหลว
    // ตรงนี้ต้องไม่เด้ง toast ทับหน้าสรุปผล
    const r=await fetch('/api/session/report-share',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ticket,image_base64:image}),
    });
    if(r.ok)result=await r.json();
  }catch{result=null;}
  if(!result?.ok||!result.qr_data_url){
    setSessionEndQr('failed',`ยังเตรียม QR ไม่ได้ · กรุณาดูผลในแอป ZEEP<br>${fallback}`);
    return;
  }
  const minutes=Number(result.expires_in_minutes)||SESSION_END_QR_FALLBACK_MINUTES;
  setSessionEndQr('','<img alt="QR ผลการพัก" src="'+result.qr_data_url+'">');
  if(note)note.textContent=`สแกนด้วยมือถือของคุณ · ลิงก์หมดอายุใน ${minutes} นาที`;
  // ยืดหน้าจอให้เท่าอายุลิงก์จริงที่ backend ตอบมา ไม่ใช่ค่าที่เดาไว้ฝั่งนี้
  sessionEndDeadline=Date.now()+minutes*60000;
}

/* ---- Canvas 2D: รูปผลการพัก 1080×1920 ที่ผู้ใช้เอากลับไปได้ ----
   เป็น layout ชุดที่สองที่ต้องดูแลคู่กับ renderSessionOverview() — ราคาที่จ่าย
   เพื่อให้สระ/วรรณยุกต์ไทยถูกต้องโดยไม่ต้องเพิ่ม dependency ฝั่ง Pi */
function reportFont(weight,size){return `${weight} ${size}px ${REPORT_PNG_FONT}`;}

function reportRoundRect(ctx,x,y,w,h,r){
  ctx.beginPath();
  ctx.moveTo(x+r,y);ctx.lineTo(x+w-r,y);ctx.quadraticCurveTo(x+w,y,x+w,y+r);
  ctx.lineTo(x+w,y+h-r);ctx.quadraticCurveTo(x+w,y+h,x+w-r,y+h);
  ctx.lineTo(x+r,y+h);ctx.quadraticCurveTo(x,y+h,x,y+h-r);
  ctx.lineTo(x,y+r);ctx.quadraticCurveTo(x,y,x+r,y);ctx.closePath();
}

const THAI_MARK=/[\u0E31\u0E34-\u0E3A\u0E47-\u0E4E]/;
const THAI_LEAD_VOWEL=/[\u0E40-\u0E44]/;

// ภาษาไทยไม่มีช่องว่างระหว่างคำ จึงต้องตัดบรรทัดเองทีละกลุ่มอักขระ. หนึ่งกลุ่ม
// คือพยัญชนะ + สระบน/ล่าง + วรรณยุกต์ที่เกาะอยู่ และสระหน้า (เ แ โ ใ ไ) ต้องอยู่
// ติดกับพยัญชนะที่ตามมาเสมอ — ตัดคั่นตรงนั้นจะได้ "ไ" ค้างท้ายบรรทัด
function textClusters(text){
  const chars=Array.from(String(text??''));
  const clusters=[];
  for(let i=0;i<chars.length;i++){
    let cluster=chars[i];
    if(THAI_LEAD_VOWEL.test(chars[i])&&i+1<chars.length)cluster+=chars[++i];
    while(i+1<chars.length&&THAI_MARK.test(chars[i+1]))cluster+=chars[++i];
    clusters.push(cluster);
  }
  return clusters;
}

function wrapCanvasText(ctx,text,maxWidth){
  const lines=[];let line='';
  for(const cluster of textClusters(text)){
    if(cluster==='\n'){lines.push(line);line='';continue;}
    const next=line+cluster;
    if(line&&ctx.measureText(next).width>maxWidth){
      // ข้อความปนสองภาษา: ถ้ามีช่องว่างให้ตัดที่คำ ("Recovery Score" ต้องไม่กลายเป็น
      // "Recovery Sc"/"ore") แต่ประโยคไทยยาว ๆ ที่เว้นวรรคห่างมากต้องไม่ถอยไปไกล
      // จนบรรทัดโหว่ — ถอยได้เมื่อยังเหลือความยาวอย่างน้อย 60% ของบรรทัด
      const cut=line.lastIndexOf(' ');
      const head=cut>0?line.slice(0,cut):'';
      if(head&&ctx.measureText(head).width>=maxWidth*0.6){
        lines.push(head);line=line.slice(cut+1)+cluster;
      }else{lines.push(line);line=cluster;}
    }
    else line=next;
  }
  if(line)lines.push(line);
  return lines;
}

function drawWrapped(ctx,text,x,y,maxWidth,lineHeight,maxLines=99){
  const lines=wrapCanvasText(ctx,text,maxWidth).slice(0,maxLines);
  lines.forEach((line,i)=>ctx.fillText(line,x,y+i*lineHeight));
  return y+lines.length*lineHeight;
}

function drawReportHeader(ctx,payload,W,M,presentation){
  let y=M;
  const reportTitle=presentation==='recovery'
    ?'ZEEP · RECOVERY REPORT'
    :presentation==='sleep'?'ZEEP · SLEEP REPORT':'ZEEP · SESSION REPORT';
  ctx.fillStyle='#19e3ff';ctx.font=reportFont(800,32);
  ctx.fillText(reportTitle,M,y);y+=54;
  ctx.fillStyle='#eaf7fc';ctx.font=reportFont(800,54);
  y=drawWrapped(ctx,payload.display_name||payload.username||'ผู้ใช้งาน',M,y,W-2*M,66,2)+10;
  ctx.fillStyle='#7fa6b8';ctx.font=reportFont(600,26);
  ctx.fillText(sessionEndDateText(payload.ended_at_utc),M,y);y+=38;
  ctx.fillText(`ระยะเวลาการใช้งาน ${fmtDur(payload.duration_s)}`,M,y);
  return y+62;
}

function drawReportScore(ctx,quality,y,W,M,presentation){
  const h=250;
  reportRoundRect(ctx,M,y,W-2*M,h,24);
  ctx.fillStyle='#0b1e2e';ctx.fill();ctx.strokeStyle='#17394f';ctx.lineWidth=2;ctx.stroke();
  const score=quality?.available&&presentation!=='unknown'
    ?Number(quality.score)||0:null;
  const cx=M+150,cy=y+h/2;
  ctx.lineWidth=18;ctx.strokeStyle='#123043';
  ctx.beginPath();ctx.arc(cx,cy,88,0,Math.PI*2);ctx.stroke();
  if(score!=null){
    ctx.strokeStyle='#19e3ff';ctx.beginPath();
    ctx.arc(cx,cy,88,-Math.PI/2,-Math.PI/2+Math.PI*2*Math.max(0,Math.min(1,score/100)));ctx.stroke();
  }
  ctx.textAlign='center';
  ctx.fillStyle='#f2fbfd';ctx.font=reportFont(800,62);ctx.fillText(score==null?'—':String(score),cx,cy-46);
  ctx.fillStyle='#7fa6b8';ctx.font=reportFont(600,24);ctx.fillText('/ 100',cx,cy+28);
  ctx.textAlign='left';
  const tx=M+290,tw=W-M-tx-30;
  const scoreTitle=presentation==='recovery'
    ?'Recovery Score'
    :presentation==='sleep'?'Sleep Score':'ผลการพักครั้งนี้';
  ctx.fillStyle='#9fd7e6';ctx.font=reportFont(700,24);
  ctx.fillText(scoreTitle,tx,y+50);
  ctx.fillStyle='#eaf7fc';ctx.font=reportFont(800,42);
  const scoreAvailable=score!==null;
  drawWrapped(ctx,scoreAvailable?userScoreLevelLabel(quality):'ครั้งนี้ยังไม่มีคะแนน',tx,y+88,tw,50,1);
  ctx.fillStyle='#7fa6b8';ctx.font=reportFont(500,24);
  const meaning=scoreAvailable
    ?userScoreMeaning(quality):userUnavailableScoreReason(quality,presentation);
  drawWrapped(ctx,meaning,tx,y+150,tw,34,3);
  return y+h+40;
}

function drawReportMetrics(ctx,report,quality,y,W,M,presentation){
  const sleep=report.sleep||{};
  const target=quality.duration_target||{};
  const regularity=quality.physiology?.regularity_factor;
  const movement=quality.body_response?.movement_pct;
  let boxes;
  if(presentation==='recovery')boxes=[
    ['เวลาพักที่นับได้',fmtDur(target.eligible_rest_seconds==null?sleep.recording_s:target.eligible_rest_seconds)],
    ['เทียบเป้าหมาย',target.completion_pct==null?'--':`${Math.round(Number(target.completion_pct))}%`],
    ['ความสม่ำเสมอระหว่างพัก',regularity==null?'--':`${Math.round(100*Number(regularity))}%`],
    ['ความนิ่งร่างกาย',movement==null?'--':`${Math.max(0,Math.round(100-Number(movement)))}%`],
  ];
  else if(presentation==='sleep')boxes=[
    ['เวลานอนโดยประมาณ',fmtDur(sleep.estimated_sleep_s)],
    ['ระยะเวลาการใช้งาน',fmtDur(sleep.recording_s)],
    ['ประสิทธิภาพ',sleep.sleep_efficiency_pct==null?'--':`${sleep.sleep_efficiency_pct}%`],
    ['W · ตื่น',fmtDur(sleep.wake_s)],
  ];
  else boxes=[['ระยะเวลาที่บันทึก',fmtDur(sleep.recording_s)]];
  const bw=(W-2*M-20)/2,bh=140;
  boxes.forEach(([label,value],i)=>{
    const bx=M+(i%2)*(bw+20),by=y+Math.floor(i/2)*(bh+20);
    reportRoundRect(ctx,bx,by,bw,bh,18);
    ctx.fillStyle='#0b1e2e';ctx.fill();ctx.strokeStyle='#17394f';ctx.lineWidth=2;ctx.stroke();
    ctx.fillStyle='#7fa6b8';ctx.font=reportFont(600,24);
    drawWrapped(ctx,label,bx+26,by+28,bw-52,30,1);
    ctx.fillStyle='#eaf7fc';ctx.font=reportFont(800,40);
    drawWrapped(ctx,value,bx+26,by+72,bw-52,46,1);
  });
  const rows=Math.ceil(boxes.length/2);
  return y+rows*bh+Math.max(0,rows-1)*20+44;
}

function drawReportStages(ctx,report,quality,y,W,M,presentation){
  const profile=reportProfileItems(report,presentation);
  const items=profile.items;
  if(presentation==='unknown'||!items.length)return y;
  ctx.fillStyle='#9fd7e6';ctx.font=reportFont(700,28);
  ctx.fillText(presentation==='recovery'?'รูปแบบการพักโดยประมาณ':'สัดส่วนการนอนโดยประมาณ',M,y);y+=48;
  const barW=W-2*M,barH=44;
  ctx.save();reportRoundRect(ctx,M,y,barW,barH,10);ctx.fillStyle='#122b3a';ctx.fill();ctx.clip();
  let cursor=0;
  items.forEach(item=>{
    const w=barW*Math.max(0,Number(item.pct)||0)/100;
    ctx.fillStyle=item.color;ctx.fillRect(M+cursor,y,w,barH);cursor+=w;
  });
  ctx.restore();
  y+=barH+26;
  items.forEach((item,i)=>{
    const lx=M+(i%2)*(barW/2),ly=y+Math.floor(i/2)*42;
    ctx.fillStyle=item.color;ctx.fillRect(lx,ly+6,16,16);
    ctx.fillStyle='#cfe8f2';ctx.font=reportFont(600,25);
    drawWrapped(ctx,`${item.label} · ${item.pct.toFixed(0)}% · ${fmtDur(item.duration_s)}`,
      lx+26,ly,barW/2-40,30,1);
  });
  return y+Math.ceil(items.length/2)*42+34;
}

function drawReportFindings(ctx,report,y,W,M,limit,presentation){
  const findingPriority=item=>item?.decision==='safety_review'?0:({critical:1,poor:2,fair:3}[item?.severity]??4);
  const findings=(Array.isArray(report.findings)?report.findings:[])
    .slice().sort((a,b)=>findingPriority(a)-findingPriority(b)).slice(0,5);
  if(!findings.length)return y;
  ctx.fillStyle='#9fd7e6';ctx.font=reportFont(700,28);
  const title=presentation==='sleep'
    ?'สิ่งที่ควรรู้จากคืนนี้':'สิ่งที่ควรรู้จากการพักครั้งนี้';
  ctx.fillText(title,M,y);y+=48;
  for(const item of findings){
    if(y>limit)break;
    const finding=userReportFinding(item);
    ctx.fillStyle=REPORT_PNG_FINDING_COLOR[finding.severity]||'#7fa6b8';
    ctx.fillRect(M,y+8,8,40);
    ctx.fillStyle='#eaf7fc';ctx.font=reportFont(700,27);
    y=drawWrapped(ctx,`${finding.metric} · ${finding.label}`,M+28,y,W-2*M-28,36,2);
    ctx.fillStyle='#7fa6b8';ctx.font=reportFont(500,24);
    const detail=finding.action?`${finding.detail} · ${finding.action}`:finding.detail;
    y=drawWrapped(ctx,detail,M+28,y+6,W-2*M-28,34,2)+24;
  }
  return y;
}

async function drawSessionReportPng(payload){
  const canvas=document.getElementById('sessionEndCanvas');
  const ctx=canvas.getContext('2d');
  const W=canvas.width,H=canvas.height,M=80;
  const report=payload.session_report||{},quality=payload.sleep_quality||{};
  const presentation=reportPresentationMode(report||quality);
  // รอฟอนต์ไทยของแท็บเล็ตให้พร้อมก่อน ไม่งั้น measureText คำนวณจาก fallback
  try{await document.fonts.ready;}catch{}
  const bg=ctx.createLinearGradient(0,0,0,H);
  bg.addColorStop(0,'#061422');bg.addColorStop(1,'#020a13');
  ctx.fillStyle=bg;ctx.fillRect(0,0,W,H);
  ctx.textBaseline='top';ctx.textAlign='left';
  let y=drawReportHeader(ctx,payload,W,M,presentation);
  y=drawReportScore(ctx,quality,y,W,M,presentation);
  y=drawReportMetrics(ctx,report,quality,y,W,M,presentation);
  if(presentation!=='unknown'){
    y=drawReportStages(ctx,report,quality,y,W,M,presentation);
  }
  drawReportFindings(ctx,report,y,W,M,H-M-190,presentation);
  ctx.fillStyle='#5c8296';ctx.font=reportFont(500,22);
  const resultScope=presentation==='recovery'
    ?'Recovery Score สรุปช่วงพักตามเป้าหมายที่เลือก'
    :presentation==='sleep'
      ?'Sleep Score สรุปภาพรวมการนอนครั้งนี้'
      :'แสดงเฉพาะข้อมูลที่บันทึก โดยยังไม่สรุปเป็นคะแนน';
  drawWrapped(ctx,`${resultScope} · เป็นข้อมูลเพื่อดูแลการพัก ไม่ใช่การวินิจฉัยทางการแพทย์`,
    M,H-M-120,W-2*M,32,3);
  return canvas.toDataURL('image/png');
}

async function doLogout(btn){
  if (!await confirmAction({title:'จบและบันทึกการพัก',message:`เมื่อยืนยันว่าตื่นแล้ว ZEEP จะบันทึกสถานะตื่นก่อนสิ้นสุดการพักของ “${identityLabel(sessionState)}”`,confirmText:'ตื่นแล้ว · จบการพัก',tone:'warning',icon:'◷'})) return;
  // User logout is one complete flow: persist the sleep record first, then
  // revoke the browser account. Never leave the former user inside the app
  // after a completed Session on a shared ZEEP tablet.
  // finalize เคลียร์ ownership ตั้งแต่บรรทัดแรก แล้วค่อยทำงานยาว (flush + ingest)
  // ระหว่างนั้น WS จะปิด 4403 — ตั้งธงไว้ก่อนยิง เพื่อไม่ให้ handler พาออกจากหน้าจอ
  sessionEndInProgress = featureReportShare;
  const result = await withBusy(btn, async()=>{
    const ended = await post('/api/session/logout');
    if (!ended) return null;
    const signedOut = await post('/api/auth/logout');
    return {ended, signedOut};
  });
  if (result?.ended){
    authPod={occupied:false,owns_active_session:false};
    sessionState={...sessionState,active:false,recording:false};
    document.getElementById('logoutBtn').style.display='none';
    if (!result.signedOut){
      sessionEndInProgress=false;
      setPageMessage('warning','บันทึกผลการพักแล้ว','กรุณากดออกจากบัญชีที่มุมขวาบนอีกครั้ง');
      document.getElementById('accountLogoutBtn').style.display='';
      return;
    }
    currentPrincipal=null;
    if (showSessionEndScreen(result.ended)) return;
    location.replace('/login?logged_out=session_saved');
  } else {
    sessionEndInProgress=false;
  }
}

async function doAuthLogout(btn){
  const logoutPath=currentPrincipal?.role==='admin'?ADMIN_LOGIN_PATH:USER_LOGIN_PATH;
  const r=await withBusy(btn,()=>post('/api/auth/logout'));
  if(!r)return;
  currentPrincipal=null;authPod={occupied:false,owns_active_session:false};
  location.replace(`${logoutPath}?logged_out=account`);
}

async function loadPublicStatus(){
  try{
    const r=await fetch('/api/public/status',{cache:'no-store'});
    if(!r.ok)throw new Error(`HTTP ${r.status}`);
    const d=await r.json();serverReachable=true;
    current.safety=d.safety||{};renderLoginSafety(current.safety,!!d.occupied);
    if(d.occupied&&loginAudience==='user'){
      showLoginError('ZEEP กำลังมีผู้ใช้งาน กรุณารอให้การพักครั้งนี้จบก่อน','warning');
    }
  }catch{showLoginError('ติดต่อระบบของตู้ไม่ได้');}
}

function startAuthenticatedApp(){
  if(authenticatedAppStarted)return;
  authenticatedAppStarted=true;serverReachable=true;
  loadTracks();loadBrainwaveLab();loadUsers();fetchBcgTrend();connectWS();
}

async function bootstrapAuth(){
  try{
    const r=await fetch('/api/auth/me',{cache:'no-store'});
    if(!r.ok)throw new Error('not-authenticated');
    const d=await r.json();authPod=d.pod||authPod;applyRoleUI(d.principal);
    document.getElementById('login').classList.add('hide');
    startAuthenticatedApp();
  }catch{
    applyRoleUI(null);setLoginAudience(loginAudience);
    const target=canonicalLoginPath();
    if(location.pathname!==target)history.replaceState({},'',`${target}${location.search}`);
    const overlay=document.getElementById('login');overlay.classList.remove('hide');overlay.setAttribute('aria-hidden','false');
    if(loginAudience==='user'&&qrLoginRequested)setLoginMode('qr');
    await loadPublicStatus();
    const loggedOut=new URLSearchParams(location.search).get('logged_out');
    if(loggedOut){
      showLoginError(loggedOut==='session_saved'?'บันทึกผลการพักและออกจากระบบเรียบร้อยแล้ว':'ออกจากระบบเรียบร้อยแล้ว','success');
      history.replaceState({},'',location.pathname);
    }
  }finally{dismissBoot();}
}
