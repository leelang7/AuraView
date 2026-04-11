from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .routers import intersections, signals, events, risk, detect

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AuraView Prototype")

app.include_router(intersections.router, prefix="/intersections", tags=["intersections"])
app.include_router(signals.router, prefix="/signals", tags=["signals"])
app.include_router(events.router, prefix="/events", tags=["events"])
app.include_router(risk.router, prefix="/risk", tags=["risk"])
app.include_router(detect.router, prefix="/detect", tags=["detect"])

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/app", StaticFiles(directory="app"), name="app")


@app.get("/")
def root():
    return {"message": "AuraView Prototype Running"}


@app.get("/ui", response_class=HTMLResponse)
def prototype_ui():
    return """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
        <title>AuraView Dashboard</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Black+Han+Sans&family=JetBrains+Mono:wght@400;600;700&family=Noto+Sans+KR:wght@300;400;500;700&display=swap');

            :root {
              --bg: #f5f7fa;
              --surface: #ffffff;
              --surface2: #eef1f6;
              --border: #dde3ed;
              --text: #1a1f2e;
              --muted: #6b7a99;
              --dim: #c5cfe0;
              --accent: #0284c7;
              --danger: #dc2626;
              --warn: #d97706;
              --safe: #059669;
              --shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
            }

            * { margin:0; padding:0; box-sizing:border-box; }

            body {
              background: var(--bg);
              color: var(--text);
              font-family: 'Noto Sans KR', sans-serif;
              min-height: 100vh;
              overflow-x: hidden;
            }

            body::before {
              content:'';
              position:fixed; inset:0;
              background-image:
                radial-gradient(circle at 15% 50%, rgba(2,132,199,0.05) 0%, transparent 50%),
                radial-gradient(circle at 85% 20%, rgba(124,58,237,0.04) 0%, transparent 50%);
              pointer-events:none;
            }

            header {
              padding: 28px 40px 18px;
              border-bottom: 1px solid var(--border);
              display:flex;
              justify-content:space-between;
              align-items:flex-end;
              gap:16px;
              flex-wrap:wrap;
            }

            .eyebrow {
              font-family:'JetBrains Mono', monospace;
              font-size:11px;
              letter-spacing:4px;
              color:var(--accent);
              text-transform:uppercase;
              margin-bottom:10px;
            }

            h1 {
              font-family:'Black Han Sans', sans-serif;
              font-size:34px;
              line-height:1.02;
              margin-bottom:6px;
            }

            h1 em { color:var(--accent); font-style:normal; }

            .subtitle {
              font-size:13px;
              color:var(--muted);
            }

            .tabs {
              display:flex;
              gap:0;
              padding:0 40px;
              border-bottom:1px solid var(--border);
              background:var(--surface);
              overflow-x:auto;
            }

            .tab {
              padding:12px 18px;
              font-size:12px;
              font-weight:500;
              border-bottom:3px solid transparent;
              color:var(--muted);
              white-space:nowrap;
            }

            .tab.active {
              color:var(--accent);
              border-bottom-color:var(--accent);
            }

            .content {
              padding: 24px 40px 36px;
              max-width: 1440px;
              margin: 0 auto;
            }

            .dashboard-grid {
              display: grid;
              grid-template-columns: 400px 1fr;
              gap: 20px;
              align-items: start;
            }

            .left-col {
              display: grid;
              grid-template-rows: auto 320px;
              gap: 20px;
            }

            .right-col {
              display: grid;
              grid-template-rows: 560px 260px;
              gap: 20px;
            }

            .card {
              background: var(--surface);
              border: 1px solid var(--border);
              border-radius: 16px;
              padding: 22px;
              position: relative;
              box-shadow: var(--shadow);
            }

            .card-tag {
              position:absolute;
              top:-11px; left:20px;
              font-family:'JetBrains Mono', monospace;
              font-size:10px;
              letter-spacing:2px;
              padding:2px 12px;
              border-radius:4px;
              color:#fff;
              background:var(--accent);
            }

            .section-label {
              font-family:'JetBrains Mono', monospace;
              font-size:10px;
              letter-spacing:3px;
              color:var(--muted);
              text-transform:uppercase;
              margin-bottom:18px;
              padding-bottom:10px;
              border-bottom:1px solid var(--border);
            }

            .form-grid {
              display:grid;
              gap:10px;
            }

            label {
              font-size:12px;
              font-weight:700;
              color:var(--muted);
              margin-bottom:4px;
              display:block;
            }

            input, select, button {
              width:100%;
              border-radius:12px;
              border:1px solid var(--border);
              background:var(--surface2);
              color:var(--text);
              font-family:'Noto Sans KR', sans-serif;
              font-size:14px;
              padding:12px 14px;
            }

            input:focus, select:focus {
              outline: none;
              border-color: var(--accent);
              box-shadow: 0 0 0 3px rgba(2,132,199,0.12);
            }

            button {
              cursor:pointer;
              background:var(--text);
              color:white;
              border:none;
              font-weight:700;
              transition:all .18s ease;
            }

            button:hover {
              transform:translateY(-1px);
              box-shadow: 0 8px 18px rgba(15, 23, 42, 0.12);
            }

            .btn-secondary { background:#334155; }
            .btn-accent { background:var(--accent); }

            .btn-row {
              display:grid;
              grid-template-columns:1fr 1fr;
              gap:10px;
              margin-top:2px;
            }

            .status {
              border-radius:14px;
              padding:18px;
              margin-top:16px;
              border:1px solid var(--border);
              background:var(--surface2);
            }

            .status.warning {
              background:rgba(220,38,38,0.10);
              border-color:rgba(220,38,38,0.25);
            }

            .status.safe {
              background:rgba(5,150,105,0.10);
              border-color:rgba(5,150,105,0.25);
            }

            .status-title {
              font-family:'JetBrains Mono', monospace;
              font-size:11px;
              letter-spacing:2px;
              margin-bottom:8px;
            }

            .status-main {
              font-size:24px;
              font-weight:800;
              margin-bottom:8px;
              line-height: 1.25;
            }

            .status-meta {
              font-size:13px;
              color:var(--muted);
              line-height:1.8;
            }

            .preview-card,
            .control-card,
            .ranking-card {
              min-height: 0;
            }

            .preview-wrap {
              margin-top:8px;
              height:240px;
              border:1px solid var(--border);
              border-radius:14px;
              overflow:hidden;
              background:#fff;
              display:flex;
              align-items:center;
              justify-content:center;
            }

            .preview-wrap img {
              width:100%;
              height:100%;
              object-fit:cover;
              display:block;
            }

            .placeholder {
              padding:40px 20px;
              color:var(--muted);
              text-align:center;
              font-size:13px;
            }

            .map-card {
              background:var(--surface);
              border:1px solid var(--border);
              border-radius:16px;
              overflow:hidden;
              box-shadow: var(--shadow);
            }

            #map {
              width:100%;
              height:100%;
              min-height:560px;
            }

            .ranking {
              display:grid;
              grid-template-columns: repeat(2, minmax(0, 1fr));
              gap:12px;
              margin-top:8px;
            }

            .rank-item {
              background:var(--surface2);
              border:1px solid var(--border);
              border-radius:12px;
              padding:14px 16px;
              border-left:4px solid var(--safe);
              height:100%;
            }

            .rank-item.high { border-left-color: var(--danger); }
            .rank-item.mid { border-left-color: var(--warn); }

            .rank-head {
              display:flex;
              justify-content:space-between;
              align-items:center;
              gap:8px;
              margin-bottom:8px;
            }

            .rank-title {
              font-family:'JetBrains Mono', monospace;
              font-size:12px;
              font-weight:700;
              line-height:1.4;
            }

            .badge {
              display:inline-block;
              padding:2px 8px;
              border-radius:4px;
              font-size:11px;
              font-family:'JetBrains Mono', monospace;
              flex-shrink:0;
            }

            .b-g { background:rgba(5,150,105,0.12); color:#059669; }
            .b-y { background:rgba(217,119,6,0.12); color:#d97706; }
            .b-r { background:rgba(220,38,38,0.12); color:#dc2626; }

            .rank-body {
              font-size:12px;
              color:var(--muted);
              line-height:1.65;
            }

            @media (max-width: 1100px) {
              .dashboard-grid {
                grid-template-columns: 1fr;
              }

              .left-col,
              .right-col {
                grid-template-rows: auto;
              }

              .ranking {
                grid-template-columns: 1fr;
              }

              #map {
                min-height: 420px;
              }

              header,
              .tabs,
              .content {
                padding-left: 20px;
                padding-right: 20px;
              }

              h1 {
                font-size: 28px;
              }
            }
        </style>
    </head>
    <body>
        <header>
          <div>
            <div class="eyebrow">AuraView(Prototype)</div>
            <h1><em>AuraView</em> Dashboard</h1>
            <div class="subtitle">비가시 교통정보의 축적/분석을 통해 보이지 않는 위험까지 예측/제공하는 차세대 안전 주행 지원 시스템</div>
          </div>
        </header>

        <div class="tabs">
          <div class="tab active">① AuraView 데모</div>
          <div class="tab">② 실시간 위험 판단</div>
          <div class="tab">③ 위험 지도화</div>
        </div>

        <div class="content">
          <div class="dashboard-grid">
            <div class="left-col">
              <div class="card control-card">
                <div class="card-tag">FIELD INPUT</div>
                <div class="section-label">// 현장 입력</div>

                <div class="form-grid">
                  <div>
                    <label>교차로 선택</label>
                    <select id="intersection_id"></select>
                  </div>

                  <div class="btn-row">
                    <div>
                      <label>사용자 위도</label>
                      <input id="user_lat" type="number" step="0.000001"/>
                    </div>
                    <div>
                      <label>사용자 경도</label>
                      <input id="user_lon" type="number" step="0.000001"/>
                    </div>
                  </div>

                  <div class="btn-row">
                    <div>
                      <label>지속시간(초)</label>
                      <input id="duration" type="number" step="0.1" value="3.5"/>
                    </div>
                    <div>
                      <label>장애물 유형</label>
                      <select id="obstacle_type">
                        <option value="truck">truck</option>
                        <option value="bus">bus</option>
                        <option value="top_truck">top_truck</option>
                        <option value="van">van</option>
                        <option value="unknown_vehicle">unknown_vehicle</option>
                      </select>
                    </div>
                  </div>

                  <div>
                    <label>현장 이미지 업로드</label>
                    <input id="image_file" type="file" accept="image/*" capture="environment"/>
                  </div>

                  <div class="btn-row">
                    <button class="btn-secondary" onclick="getLocation()">현재 위치 가져오기</button>
                    <button class="btn-secondary" onclick="loadSignal()">신호 조회</button>
                  </div>

                  <div class="btn-row">
                    <button class="btn-accent" onclick="autoDetect()">자동 감지 실행</button>
                    <button onclick="refreshAll()">지도/랭킹 갱신</button>
                  </div>
                </div>

                <div id="statusBox" class="status">
                  <div class="status-title">SYSTEM STATUS</div>
                  <div class="status-main">대기 중</div>
                  <div class="status-meta">이미지를 업로드하고 자동 감지 실행을 누르세요.</div>
                </div>
              </div>

              <div class="card preview-card">
                <div class="section-label">// 오버레이 결과</div>
                <div class="preview-wrap" id="previewWrap">
                  <div class="placeholder">오버레이 결과 이미지가 여기 표시됩니다.</div>
                </div>
              </div>
            </div>

            <div class="right-col">
              <div class="map-card">
                <div id="map"></div>
              </div>

              <div class="card ranking-card">
                <div class="section-label">// 위험 랭킹 TOP 5</div>
                <div class="ranking" id="ranking"></div>
              </div>
            </div>
          </div>
        </div>

        <script>
          const map = L.map('map').setView([37.5665, 126.9780], 12);

          L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19
          }).addTo(map);

          let markers = [];

          function clearMarkers() {
            markers.forEach(m => map.removeLayer(m));
            markers = [];
          }

          function markerColor(score) {
            if (score >= 10) return 'red';
            if (score >= 6) return 'orange';
            return 'green';
          }

          function badgeClass(score) {
            if (score >= 10) return 'badge b-r';
            if (score >= 6) return 'badge b-y';
            return 'badge b-g';
          }

          function rankClass(score) {
            if (score >= 10) return 'rank-item high';
            if (score >= 6) return 'rank-item mid';
            return 'rank-item';
          }

          async function loadIntersections() {
            const res = await fetch(window.location.origin + '/intersections/');
            const data = await res.json();
            const select = document.getElementById('intersection_id');
            select.innerHTML = '';

            data.slice(0, 500).forEach(item => {
              const opt = document.createElement('option');
              opt.value = item.intersection_id;
              opt.textContent = item.intersection_id + ' — ' + item.name;
              select.appendChild(opt);
            });

            const target = Array.from(select.options).find(o => o.value === '1007');
            if (target) target.selected = true;
          }

          function getLocation() {
            if (!navigator.geolocation) {
              alert('Geolocation not supported');
              return;
            }

            navigator.geolocation.getCurrentPosition(
              (pos) => {
                document.getElementById('user_lat').value = pos.coords.latitude;
                document.getElementById('user_lon').value = pos.coords.longitude;
                map.setView([pos.coords.latitude, pos.coords.longitude], 16);
              },
              () => {
                alert('현재 위치 가져오기는 HTTPS 환경에서 동작합니다.');
              }
            );
          }

          async function loadSignal() {
            const intersectionId = document.getElementById('intersection_id').value;
            const res = await fetch(window.location.origin + '/signals/' + intersectionId);
            const data = await res.json();

            let signalState = '-';
            let remainTime = '-';

            if (data && data.body && data.body.items && data.body.items.item) {
              let item = data.body.items.item;
              if (Array.isArray(item)) item = item[0];
              signalState = item.stPdsgSttsNm || '-';
              remainTime = item.stPdsgRmndCs || '-';
            }

            const box = document.getElementById('statusBox');
            box.className = 'status safe';
            box.innerHTML = `
              <div class="status-title">SIGNAL STATUS</div>
              <div class="status-main">${signalState}</div>
              <div class="status-meta">잔여시간: ${remainTime}</div>
            `;
          }

          async function autoDetect() {
            const fileInput = document.getElementById('image_file');
            if (!fileInput.files || fileInput.files.length === 0) {
              alert('이미지를 선택해라');
              return;
            }

            const formData = new FormData();
            formData.append('intersection_id', document.getElementById('intersection_id').value);

            const latVal = document.getElementById('user_lat').value;
            const lonVal = document.getElementById('user_lon').value;
            if (latVal !== '') formData.append('user_lat', latVal);
            if (lonVal !== '') formData.append('user_lon', lonVal);

            formData.append('duration', document.getElementById('duration').value);
            formData.append('obstacle_type', document.getElementById('obstacle_type').value);
            formData.append('image', fileInput.files[0]);

            const res = await fetch(window.location.origin + '/detect/frame', {
              method: 'POST',
              body: formData
            });

            const data = await res.json();
            const box = document.getElementById('statusBox');

            if (data.status === 'warning') {
              box.className = 'status warning';
              box.innerHTML = `
                <div class="status-title">AURAVIEW ALERT</div>
                <div class="status-main">가려진 신호등 대체 안내 활성화</div>
                <div class="status-meta">
                  intersection_id: ${data.intersection_id || '-'}<br>
                  signal_state: ${data.signal_state || '-'}<br>
                  remain_time: ${data.signal_remain_time || '-'}초<br>
                  risk_score: ${data.risk_score || '-'}
                </div>
              `;
            } else {
              box.className = 'status safe';
              box.innerHTML = `
                <div class="status-title">AURAVIEW STATUS</div>
                <div class="status-main">신호 확인 가능</div>
                <div class="status-meta">
                  intersection_id: ${data.intersection_id || '-'}<br>
                  signal_state: ${data.signal_state || '-'}<br>
                  remain_time: ${data.signal_remain_time || '-'}초<br>
                  risk_score: ${data.risk_score || '-'}
                </div>
              `;
            }

            const previewWrap = document.getElementById('previewWrap');
            if (data.overlay_image) {
              previewWrap.innerHTML = `<img src="${data.overlay_image}?t=${Date.now()}" alt="overlay result"/>`;
            } else {
              previewWrap.innerHTML = `<div class="placeholder">오버레이 결과가 없습니다.</div>`;
            }

            await refreshAll();
          }

          async function refreshMap() {
            const res = await fetch(window.location.origin + '/events/map-data');
            const data = await res.json();

            clearMarkers();

            const valid = data.filter(x => x.last_lat !== null && x.last_lon !== null);

            valid.forEach(ev => {
              const color = markerColor(ev.risk_score);
              const radius = Math.min(10 + ev.event_count * 2, 28);

              const marker = L.circleMarker([ev.last_lat, ev.last_lon], {
                radius: radius,
                color: color,
                fillColor: color,
                fillOpacity: 0.75
              }).addTo(map);

              marker.bindPopup(
                '<b>' + ev.intersection_id + '</b><br>' +
                'event_count: ' + ev.event_count + '<br>' +
                'avg_duration: ' + ev.avg_duration + '<br>' +
                'signal_state: ' + (ev.signal_state || '') + '<br>' +
                'risk_score: ' + ev.risk_score
              );

              markers.push(marker);
            });

            if (valid.length > 0) {
              map.setView([valid[0].last_lat, valid[0].last_lon], 14);
            }
          }

          async function loadRiskRanking() {
            const res = await fetch(window.location.origin + '/risk/');
            const data = await res.json();

            const wrap = document.getElementById('ranking');
            wrap.innerHTML = '';

            data.slice(0, 5).forEach((item, idx) => {
              const div = document.createElement('div');
              div.className = rankClass(item.risk_score);
              div.innerHTML = `
                <div class="rank-head">
                  <div class="rank-title">#${idx + 1} ${item.intersection_id}</div>
                  <span class="${badgeClass(item.risk_score)}">RISK ${item.risk_score}</span>
                </div>
                <div class="rank-body">
                  event_count: ${item.event_count}<br>
                  avg_duration: ${item.avg_duration}<br>
                  signal_state: ${item.signal_state || '-'}
                </div>
              `;
              wrap.appendChild(div);
            });
          }

          async function refreshAll() {
            await refreshMap();
            await loadRiskRanking();
          }

          loadIntersections();
          refreshAll();
        </script>
    </body>
    </html>
    """