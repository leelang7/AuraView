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

/// AuraView 컨셉 시나리오 — voxel grid 기반 occlusion 감지 (네이티브 동일).
function reasonFor(entropy, motion) {
  // bevData 가 있으면 voxel 분석으로 occlusion 시나리오 우선
  if (bevData && Array.isArray(bevData.grid_flat) && bevData.grid_flat.length === 1600) {
    const flat = bevData.grid_flat;
    const COLS = 40;
    let upperCenter = 0, leftEdge = 0, rightEdge = 0, bigBlobCenter = 0;
    for (let r = 25; r < 38; r++) {
      for (let c = 14; c < 26; c++) upperCenter += flat[r * COLS + c];
    }
    for (let r = 5; r < 25; r++) {
      for (let c = 0; c < 8; c++) leftEdge += flat[r * COLS + c];
      for (let c = 32; c < 40; c++) rightEdge += flat[r * COLS + c];
    }
    for (let r = 8; r < 22; r++) {
      for (let c = 12; c < 28; c++) bigBlobCenter += flat[r * COLS + c];
    }
    if (upperCenter >= 30)   return 'signal_occluded';
    if (bigBlobCenter >= 60) return 'crosswalk_blocked';
    if (leftEdge >= 25)      return 'blind_spot_left';
    if (rightEdge >= 25)     return 'blind_spot_right';
  }
  if (entropy >= 0.75 || motion >= 0.7) return 'high_uncertainty';
  if (entropy >= ENTROPY_THRESHOLD) return 'low_confidence';
  return null;
}

function reasonKo(r) {
  return ({
    'signal_occluded':    '🚦 신호등 가림',
    'crosswalk_blocked':  '🚛 횡단보도 가림',
    'blind_spot_left':    '◀ 좌측 사각지대',
    'blind_spot_right':   '▶ 우측 사각지대',
    'high_uncertainty':   '⚠ 시야 불확실',
    'low_confidence':     '· 시야 흐림',
  })[r] || ('· ' + r);
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

/* ── Auto Capture (Shadow Mode) ── */
async function shadowTick() {
  const feat = captureFrame();
  if (!feat) return;
  const reason = reasonFor(feat.entropy, feat.motion);
  if (reason) {
    chip.reason.textContent = reasonKo(reason) + ' 기록';
    chip.reason.classList.remove('ok');
    chip.reason.classList.add('alert');
    await uploadFrame(feat.entropy, reason);
  } else {
    chip.reason.textContent = '· 주행 중';
    chip.reason.classList.remove('alert');
    chip.reason.classList.add('ok');
  }
}

function startShadow() {
  if (shadowTimer) return;
  shadowTimer = setInterval(shadowTick, SHADOW_INTERVAL_MS);
  shadowTick();
  $('startBtn').innerHTML = '⏹ 주행 중지';
  $('startBtn').style.background = 'linear-gradient(135deg,#005580,#003344)';
  $('startBtn').onclick = stopShadow;
  $('capBtn').disabled = false;
  $('serverStatus').innerHTML = '<span style="color:var(--safe);">● 주행 중</span> — 위험 순간만 자동 기록 (PII 마스킹)';
}
function stopShadow() {
  clearInterval(shadowTimer);
  shadowTimer = null;
  $('startBtn').innerHTML = '🚗 주행 시작';
  $('startBtn').style.background = 'linear-gradient(135deg,#00C8FF,#0078A8)';
  $('startBtn').onclick = startShadow;
  $('serverStatus').innerHTML = '주행 시작 누르면 — 카메라가 자동으로 위험 순간만 기록 (PII 자동 마스킹).';
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

/* ── BEV 3D VOXEL — 카메라 프레임 → /occupancy/infer 실시간 ────────── */
let bevOpen = true;          // 기본 ON
let bevTimer = null;
let bevData = null;
let fusionData = null;
let bevThree = null;         // {renderer, scene, camera, voxelGroup, t}

function ensureBevThree() {
  if (bevThree) return bevThree;
  const canvas = $('bevThree');
  if (!canvas || typeof THREE === 'undefined') return null;
  const renderer = new THREE.WebGLRenderer({canvas, antialias:true, alpha:true});
  renderer.setPixelRatio(window.devicePixelRatio || 1);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x04080e);
  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 200);
  camera.position.set(-15, 16, -8);
  camera.lookAt(0, 1, 18);
  scene.add(new THREE.AmbientLight(0x88aacc, 0.65));
  const dir = new THREE.DirectionalLight(0xffffff, 0.85);
  dir.position.set(20, 30, 10); scene.add(dir);

  // ground + grid
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(40, 40),
    new THREE.MeshBasicMaterial({color:0x0a1624})
  );
  ground.rotation.x = -Math.PI/2; ground.position.z = 20; scene.add(ground);
  const grid = new THREE.GridHelper(40, 40, 0x0f2a44, 0x0a1a2e);
  grid.position.z = 20; scene.add(grid);

  // EGO 차량 (시안)
  const ego = new THREE.Mesh(
    new THREE.BoxGeometry(1.8, 1.4, 4),
    new THREE.MeshStandardMaterial({color:0x00c8ff, emissive:0x003b55, metalness:0.6, roughness:0.3})
  );
  ego.position.set(0, 0.7, 0); scene.add(ego);

  const voxelGroup = new THREE.Group();
  scene.add(voxelGroup);

  bevThree = {renderer, scene, camera, voxelGroup, t: 0};

  function animate() {
    bevThree.t += 0.005;
    camera.position.x = Math.cos(bevThree.t * 0.25) * 22;
    camera.position.z = Math.sin(bevThree.t * 0.25) * 22 + 14;
    camera.lookAt(0, 2, 18);
    renderer.render(scene, camera);
    requestAnimationFrame(animate);
  }
  function resize() {
    const r = canvas.getBoundingClientRect();
    const sz = Math.min(r.width, r.height) || 220;
    renderer.setSize(sz, sz, false);
    camera.aspect = 1; camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', resize);
  resize();
  animate();
  return bevThree;
}

function renderBev3D() {
  const ctx = ensureBevThree();
  if (!ctx || !bevData) return;
  // clear voxels
  while (ctx.voxelGroup.children.length) {
    const m = ctx.voxelGroup.children.pop();
    m.geometry && m.geometry.dispose();
    m.material && m.material.dispose();
  }
  const flat = bevData.grid_flat;
  const shape = bevData.grid_shape_flat || [40, 40];
  const cell = bevData.grid_cell_m_flat || 1.0;
  const forward = bevData.forward_m || 40;
  const lateral = bevData.lateral_m || 20;
  if (!Array.isArray(flat)) return;
  const rows = shape[0], cols = shape[1];
  const geom = new THREE.BoxGeometry(cell * 0.9, 1, cell * 0.9);

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const p = flat[r * cols + c] || 0;
      if (p < 0.10) continue;
      const t = Math.min(1, Math.max(0, p));
      const height = Math.max(0.2, Math.min(6, t * 6));
      const x = -lateral + c * cell + cell / 2;
      const z = r * cell + cell / 2;
      const color = new THREE.Color(t, 0.8 - 0.6 * t, 1.0 - 0.9 * t);
      const mat = new THREE.MeshStandardMaterial({
        color, emissive: color.clone().multiplyScalar(0.3),
        transparent: true, opacity: 0.9,
      });
      const box = new THREE.Mesh(geom, mat);
      box.position.set(x, height / 2, z);
      box.scale.y = height;
      ctx.voxelGroup.add(box);
    }
  }

  // hotspot 마커 — 발광 sphere + Sprite 라벨
  const colorByKind = (k) => ({
    object:           new THREE.Color(1.00, 0.23, 0.23),
    occluded_shadow:  new THREE.Color(1.00, 0.69, 0.13),
    intent_prior:     new THREE.Color(0.00, 0.88, 0.60),
    signal_shadow:    new THREE.Color(0.49, 0.23, 0.93),
  }[k] || new THREE.Color(0, 0.78, 1));
  const fine = bevData.shape || [80, 80];
  for (const h of (bevData.hotspots || [])) {
    const x = -lateral + (h.col / (fine[1] - 1)) * lateral * 2;
    const z = (h.row / (fine[0] - 1)) * forward;
    const col = colorByKind(h.kind);
    const sph = new THREE.Mesh(
      new THREE.SphereGeometry(0.7, 12, 12),
      new THREE.MeshBasicMaterial({color: col, transparent: true, opacity: 0.9})
    );
    sph.position.set(x, 4.5, z);
    ctx.voxelGroup.add(sph);
    // beam
    const beam = new THREE.Mesh(
      new THREE.CylinderGeometry(0.06, 0.06, 4.5, 8),
      new THREE.MeshBasicMaterial({color: col, transparent:true, opacity:0.45})
    );
    beam.position.set(x, 2.25, z);
    ctx.voxelGroup.add(beam);
  }
}

/** 카메라 프레임 → JPEG → POST /occupancy/infer */
async function inferFromCamera() {
  if (!video || !video.videoWidth) return null;
  // 작은 해상도로 캡처 (네트워크 절약)
  const w = 480, h = Math.round(video.videoHeight * w / video.videoWidth);
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0, w, h);
  const blob = await new Promise(res => canvas.toBlob(res, 'image/jpeg', 0.7));
  if (!blob) return null;
  const fd = new FormData();
  fd.append('image', blob, 'frame.jpg');
  fd.append('duration', '0');
  fd.append('obstacle_type', 'unknown_vehicle');
  fd.append('signal_state', '');
  fd.append('taas_nearby', '0');
  try {
    const r = await fetch(API_BASE + '/occupancy/infer', {method:'POST', body: fd});
    if (!r.ok) return null;
    return await r.json();
  } catch(e) { return null; }
}

async function fetchBev() {
  // 1. 실제 카메라 프레임이 있으면 /occupancy/infer 우선 시도
  let live = null;
  if (video && video.videoWidth) {
    live = await inferFromCamera();
  }
  if (live && live.occupancy) {
    // /infer 응답 형식 → BEV 컴포넌트가 기대하는 형식으로 어댑트
    const occ = live.occupancy;
    bevData = {
      shape: occ.shape || [80, 80],
      grid_flat: occ.grid_flat || occ.grid?.flat?.() || [],
      grid_shape_flat: occ.grid_shape_flat || occ.shape || [40, 40],
      grid_cell_m_flat: occ.grid_cell_m_flat || 1.0,
      forward_m: occ.forward_m || 40,
      lateral_m: occ.lateral_m || 20,
      hotspots: occ.hotspots || [],
      occluded_mass: occ.occluded_mass || 0,
      risk_summary: {
        p_collision: live.risk?.p_collision || 0,
        lead_time_s: 0,
        recommended_action: live.risk?.p_collision > 0.4 ? '감속' : '정상',
      },
    };
    $('bevSrc').textContent = 'CAMERA ●';
    $('bevSrc').style.color = 'var(--safe)';
  } else {
    // fallback — demo
    try {
      const r = await fetch(API_BASE + '/occupancy/demo');
      if (r.ok) bevData = await r.json();
    } catch(e) {}
    $('bevSrc').textContent = 'DEMO ●';
    $('bevSrc').style.color = 'var(--warn)';
  }

  // 도시정보 결합
  const iid = ($('intersectionId').value || '').trim();
  if (iid) {
    try {
      const r = await fetch(API_BASE + '/fusion/intersection/' + iid);
      if (r.ok) fusionData = await r.json();
    } catch(e) {}
  } else {
    fusionData = null;
  }

  renderBev3D();

  // 텍스트 갱신
  const rs = bevData?.risk_summary;
  if (rs) {
    $('bevRisk').textContent = `${(rs.p_collision*100).toFixed(0)}% COL`;
    $('bevStat').innerHTML = `<span style="color:#FF6B6B;">${(rs.p_collision*100).toFixed(0)}% 충돌</span> · <span style="color:#00E09A;">${rs.lead_time_s||0}s 선행</span>`;
  }
  // hotspot 라인
  const hs = (bevData?.hotspots || []).slice(0, 3);
  $('bevHotspots').innerHTML = hs.map(h => {
    const c = ({object:'#FF3B3B', occluded_shadow:'#FFB020', intent_prior:'#00E09A', signal_shadow:'#7C3AED'})[h.kind] || '#00C8FF';
    return `<div style="color:${c};">● ${h.label || h.class} ${h.distance_m||'?'}m</div>`;
  }).join('');
  // 도시정보 라인
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
    bevTimer = setInterval(fetchBev, 4000);
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
  // 카메라 준비 약간 기다렸다가 BEV 자동 시작 (live)
  setTimeout(() => {
    bevOpen = true;
    $('bevPanel').style.display = 'block';
    $('bevToggle').style.borderColor = 'var(--accent)';
    $('bevToggle').style.color = 'var(--accent)';
    fetchBev();
    bevTimer = setInterval(fetchBev, 4000);
  }, 1500);
});
