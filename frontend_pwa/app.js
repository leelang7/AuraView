/**
 * AuraView Fleet PWA — Shadow Mode
 *
 * 흐름:
 *  1) 카메라 스트림 획득 (후방 카메라 우선)
 *  2) 일정 주기마다 프레임을 JPEG로 캡처
 *  3) 간이 불확실성(entropy) 추정 — 장면 변화량·채도 변화로 근사
 *  4) entropy >= 임계값 이면 /fleet/contribute 에 업로드
 *  5) 서버가 얼굴·번호판 블러 후 저장, 원본 폐기
 *
 * 제출 payload:
 *   image (JPEG), device_id, entropy, reason, intersection_id?, lat?, lon?
 */

const API_BASE = ''; // same-origin via FastAPI
const SHADOW_INTERVAL_MS = 4000;
const ENTROPY_THRESHOLD = 0.55;

const $ = (id) => document.getElementById(id);
const video = $('cam');
const canvas = $('snap');

let stream = null;
let shadowTimer = null;
let lastFrameData = null;
let fpsCount = 0;
let fpsStart = performance.now();
let coords = null;

const chip = {
  entropy: $('chip-entropy'),
  reason: $('chip-reason'),
  fps: $('chip-fps'),
  geo: $('chip-geo'),
};

/* ── 카메라 기동 ── */
async function startCamera() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
    video.srcObject = stream;
    await video.play();
  } catch (e) {
    chip.reason.textContent = '카메라 접근 실패';
    chip.reason.classList.add('alert');
    console.error(e);
  }
}

/* ── 위치 ── */
function startGeo() {
  if (!navigator.geolocation) return;
  navigator.geolocation.watchPosition(
    (pos) => {
      coords = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      chip.geo.textContent = `geo ${coords.lat.toFixed(3)},${coords.lon.toFixed(3)}`;
    },
    () => { chip.geo.textContent = 'geo off'; },
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 10000 }
  );
}

/* ── 프레임 캡처 + 간이 entropy ── */
function captureFrame() {
  if (!video.videoWidth) return null;
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  fpsCount++;
  const now = performance.now();
  if (now - fpsStart > 1000) {
    chip.fps.textContent = `fps ${fpsCount}`;
    fpsCount = 0;
    fpsStart = now;
  }

  // 간이 entropy: 현재 프레임의 gray histogram 엔트로피
  const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const hist = new Array(32).fill(0);
  const step = 16;
  let count = 0;
  for (let i = 0; i < img.data.length; i += 4 * step) {
    const gray = (img.data[i] + img.data[i+1] + img.data[i+2]) / 3;
    hist[Math.min(31, (gray / 256 * 32) | 0)]++;
    count++;
  }
  let H = 0;
  for (const c of hist) {
    if (c > 0) {
      const p = c / count;
      H -= p * Math.log2(p);
    }
  }
  const normalized = Math.min(1, H / 5.0); // 5 bit ≒ 평평한 분포

  // 움직임 proxy: 전 프레임과의 평균 차이
  let motion = 0;
  if (lastFrameData) {
    let diff = 0, n = 0;
    for (let i = 0; i < img.data.length; i += 4 * step) {
      diff += Math.abs(img.data[i] - lastFrameData[i]);
      n++;
    }
    motion = Math.min(1, (diff / n) / 40);
  }
  lastFrameData = img.data;

  const entropy = Math.min(1, normalized * 0.6 + motion * 0.4);
  chip.entropy.textContent = `entropy ${entropy.toFixed(2)}`;

  return { entropy, motion };
}

function reasonFor(entropy, motion) {
  if (entropy >= 0.75) return 'high_entropy';
  if (motion >= 0.7)   return 'motion_spike';
  if (entropy >= ENTROPY_THRESHOLD) return 'low_confidence';
  return null;
}

async function uploadFrame(entropy, reason) {
  const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.82));
  if (!blob) return;
  const fd = new FormData();
  fd.append('image', blob, 'edge.jpg');
  fd.append('device_id', $('deviceId').value || 'anon-device');
  fd.append('entropy', entropy.toFixed(3));
  fd.append('reason', reason);
  const iid = $('intersectionId').value;
  if (iid) fd.append('intersection_id', iid);
  if (coords) {
    fd.append('lat', coords.lat);
    fd.append('lon', coords.lon);
  }
  try {
    const res = await fetch(API_BASE + '/fleet/contribute', { method: 'POST', body: fd });
    const data = await res.json();
    chip.reason.textContent = `sent · ${data.stored?.slice(0, 12) || 'ok'}`;
    chip.reason.classList.remove('alert');
    chip.reason.classList.add('ok');
  } catch (e) {
    chip.reason.textContent = 'upload fail';
    chip.reason.classList.add('alert');
  }
}

/* ── Shadow Mode ── */
async function shadowTick() {
  const feat = captureFrame();
  if (!feat) return;
  const reason = reasonFor(feat.entropy, feat.motion);
  if (reason) {
    chip.reason.textContent = 'contributing';
    chip.reason.classList.remove('ok', 'alert');
    await uploadFrame(feat.entropy, reason);
  } else {
    chip.reason.textContent = 'ok';
    chip.reason.classList.remove('alert');
    chip.reason.classList.add('ok');
  }
}

function startShadow() {
  if (shadowTimer) return;
  shadowTimer = setInterval(shadowTick, SHADOW_INTERVAL_MS);
  shadowTick();
  $('startBtn').textContent = 'Shadow Mode 중지';
  $('startBtn').onclick = stopShadow;
  $('capBtn').disabled = false;
}
function stopShadow() {
  clearInterval(shadowTimer);
  shadowTimer = null;
  $('startBtn').textContent = 'Shadow Mode 시작';
  $('startBtn').onclick = startShadow;
}

/* ── 수동 기여 ── */
async function manualContribute() {
  const feat = captureFrame() || { entropy: 0.5 };
  await uploadFrame(feat.entropy, 'manual');
}

/* ── 서버 통계 ── */
async function refreshStats() {
  try {
    const res = await fetch(API_BASE + '/fleet/stats');
    const data = await res.json();
    $('serverStatus').textContent =
      `total ${data.total} · hard ${data.hard_count} (${Math.round(data.hard_ratio*100)}%)\n` +
      `unique devices ${data.unique_devices}\n` +
      `recent:\n` + (data.recent || []).slice(-5).map(r => ` • ${r.ts.slice(11,19)} entropy ${r.entropy} ${r.reason}`).join('\n');
  } catch (e) {
    $('serverStatus').textContent = '서버 연결 실패';
  }
}

/* ── BEV 오버레이 (단안 카메라 + 도시정보 결합) ───────────────────── */
let bevOpen = false;
let bevTimer = null;
let bevData = null;
let fusionData = null;

async function fetchBev() {
  try {
    const r = await fetch(API_BASE + '/occupancy/demo');
    if (r.ok) bevData = await r.json();
  } catch(e) {}
  const iid = ($('intersectionId').value || '').trim();
  if (iid) {
    try {
      const r = await fetch(API_BASE + '/fusion/intersection/' + iid);
      if (r.ok) fusionData = await r.json();
    } catch(e) {}
  } else {
    fusionData = null;
  }
  renderBev();
}

function renderBev() {
  const c = $('bevCanvas');
  if (!c || !bevData) return;
  const ctx = c.getContext('2d');
  const W = c.width, H = c.height;
  ctx.fillStyle = '#050A10'; ctx.fillRect(0, 0, W, H);

  // 차로 가이드 점선
  ctx.strokeStyle = 'rgba(255,255,255,0.10)';
  ctx.lineWidth = 1; ctx.setLineDash([4, 6]);
  for (const cx of [W*0.30, W*0.50, W*0.70]) {
    ctx.beginPath(); ctx.moveTo(cx, 4); ctx.lineTo(cx, H-4); ctx.stroke();
  }
  ctx.setLineDash([]);

  // 그리드 (40x40 다운샘플)
  const flat = bevData.grid_flat;
  const shape = bevData.grid_shape_flat;
  if (Array.isArray(flat) && Array.isArray(shape) && shape.length === 2) {
    const rows = shape[0], cols = shape[1];
    const cw = W / cols, ch = H / rows;
    for (let r = 0; r < rows; r++) {
      for (let cc = 0; cc < cols; cc++) {
        const p = flat[r * cols + cc] || 0;
        if (p < 0.08) continue;
        const t = Math.min(1, Math.max(0, p));
        const yTop = H - (r + 1) * ch;
        const xLeft = cc * cw;
        ctx.fillStyle = `rgba(${Math.round(255*t)},${Math.round(180-140*t)},${Math.round(255*(1-t))},${0.5+0.4*t})`;
        ctx.fillRect(xLeft, yTop, cw + 0.5, ch + 0.5);
      }
    }
  }

  // EGO (하단 중앙)
  ctx.fillStyle = '#00C8FF';
  ctx.beginPath(); ctx.arc(W*0.5, H-12, 6, 0, Math.PI*2); ctx.fill();
  ctx.strokeStyle = '#FFF'; ctx.lineWidth = 1.5; ctx.stroke();

  // Hotspot 박스 + 거리
  const colorOf = k => ({object:'#FF3B3B', occluded_shadow:'#FFB020', intent_prior:'#00E09A', signal_shadow:'#7C3AED'})[k] || '#00C8FF';
  ctx.font = 'bold 10px ui-monospace, monospace';
  const fineRows = (bevData.shape || [80,80])[0];
  const fineCols = (bevData.shape || [80,80])[1];
  for (const h of (bevData.hotspots || [])) {
    const px = (h.col / (fineCols - 1)) * W;
    const py = H - (h.row / (fineRows - 1)) * H;
    const col = colorOf(h.kind);
    ctx.strokeStyle = col; ctx.lineWidth = 2;
    ctx.strokeRect(px - 14, py - 11, 28, 22);
    ctx.fillStyle = col;
    ctx.beginPath(); ctx.arc(px, py, 2.5, 0, Math.PI*2); ctx.fill();
    ctx.fillStyle = col;
    ctx.fillText(`${(h.distance_m).toFixed(0)}m`, px + 16, py - 2);
  }

  // "도시정보 결합" 배지
  if (fusionData) {
    ctx.fillStyle = 'rgba(0,224,154,0.18)';
    ctx.fillRect(6, 6, 90, 18);
    ctx.fillStyle = '#00E09A'; ctx.font = 'bold 10px ui-monospace, monospace';
    ctx.fillText('+CITY DATA', 11, 19);
  }

  // 우상단 risk_summary
  const rs = bevData.risk_summary;
  if (rs) {
    ctx.font = 'bold 10px ui-monospace, monospace';
    ctx.fillStyle = '#FF6B6B';
    ctx.fillText(`${(rs.p_collision*100).toFixed(0)}% COL`, W-78, 18);
    ctx.fillStyle = '#00E09A';
    ctx.fillText(`${rs.lead_time_s}s LEAD`, W-78, 32);
  }

  // 텍스트 라인
  if (rs) {
    $('bevStat').innerHTML = `<span style="color:#FF6B6B;">${(rs.p_collision*100).toFixed(0)}% 충돌</span> · <span style="color:#00E09A;">${rs.lead_time_s}s 선행</span>`;
  }
  if (fusionData) {
    let sigState = '?', vdsKmh = '?', taas = '?';
    try {
      const sig = fusionData.sources?.signal?.body?.items?.item?.stPdsgSttsNm;
      if (sig) sigState = sig.includes('Stop') ? '정지' : '진행';
      const vds = fusionData.sources?.vds?.list;
      if (Array.isArray(vds) && vds.length) vdsKmh = `${vds[0].speed}km/h`;
      const acc = fusionData.sources?.accidents_history;
      if (Array.isArray(acc)) taas = acc.length;
    } catch(e) {}
    $('bevCity').textContent = `🚦 ${sigState} · ⚡ ${vdsKmh} · ⚠ TAAS ${taas}`;
  } else {
    $('bevCity').textContent = '교차로 ID 입력 시 도시정보 결합';
  }
}

function toggleBev() {
  bevOpen = !bevOpen;
  $('bevPanel').style.display = bevOpen ? 'block' : 'none';
  const tog = $('bevToggle');
  if (bevOpen) {
    tog.style.borderColor = 'var(--accent)';
    tog.style.color = 'var(--accent)';
    fetchBev();
    bevTimer = setInterval(fetchBev, 5000);
  } else {
    tog.style.borderColor = '';
    tog.style.color = '';
    if (bevTimer) clearInterval(bevTimer);
    bevTimer = null;
  }
}

/* ── init ── */
window.addEventListener('load', () => {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('./service-worker.js').catch(console.warn);
  }
  $('startBtn').onclick = startShadow;
  $('capBtn').onclick = manualContribute;
  $('statsBtn').onclick = refreshStats;
  $('bevToggle').onclick = toggleBev;
  startCamera();
  startGeo();
  refreshStats();
});
