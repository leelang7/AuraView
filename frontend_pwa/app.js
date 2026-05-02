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

/* ── init ── */
window.addEventListener('load', () => {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('./service-worker.js').catch(console.warn);
  }
  $('startBtn').onclick = startShadow;
  $('capBtn').onclick = manualContribute;
  $('statsBtn').onclick = refreshStats;
  startCamera();
  startGeo();
  refreshStats();
});
