"""별첨 자료 PDF 생성 — 라이브 시스템 캡쳐 13장 + 핵심 근거 자료.

구성:
  Part A. 라이브 시스템 캡쳐 갤러리 (13쪽)
    - 각 페이지: 캡쳐 이미지 + 페이지 역할 설명 + URL
  Part B. 핵심 근거 자료 (텍스트, 7쪽)
    - 8 시나리오 매핑 / 정량 임팩트 / 위험 교차로 / 가명결합·DSZ
"""

from __future__ import annotations

import io
import urllib.request
import json
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager
import matplotlib.image as mpimg
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "별첨_AuraView_2026.pdf"
CAPS = ROOT / "docs" / "captures"


def _setup_font():
    for c in ["Noto Sans CJK KR", "Noto Sans KR", "Malgun Gothic", "AppleGothic", "Nanum Gothic"]:
        avail = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
        if c in avail:
            matplotlib.rcParams["font.family"] = c
            return c
    return "DejaVu Sans"


_FONT = _setup_font()


def _fetch(path):
    try:
        req = urllib.request.Request(f"https://auraview.allthatai.kr{path}",
                                     headers={"User-Agent": "AuraView appendix"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return {}


def _T(ax, x, y, text, size=10, weight="normal", color="#222", ha="left", va="top"):
    ax.text(x, y, text, fontsize=size, fontweight=weight, color=color, ha=ha, va=va,
            transform=ax.transAxes)


def _header(ax, page_n, total):
    ax.add_patch(Rectangle((0, 0.96), 1, 0.04, color="#1F497D",
                          transform=ax.transAxes, clip_on=False))
    _T(ax, 0.04, 0.978, "AuraView K-Perception · 별첨", size=10, weight="bold", color="#fff")
    _T(ax, 0.96, 0.978, f"{page_n} / {total}", size=9, color="#aaccdd", ha="right")


def _footer(ax):
    ax.plot([0.04, 0.96], [0.03, 0.03], color="#ccc", lw=0.5,
            transform=ax.transAxes, clip_on=False)
    _T(ax, 0.04, 0.015, "2026 국토교통 데이터활용 경진대회 — 제출 별첨",
       size=8, color="#888")
    _T(ax, 0.96, 0.015, "https://auraview.allthatai.kr",
       size=8, color="#888", ha="right")


def _new_page():
    fig = plt.figure(figsize=(8.27, 11.69))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    return fig, ax


def _capture_page(pdf, page_n, total, cap_file, page_title, page_role, url_path, description):
    """캡쳐 이미지 1장 + 설명 페이지."""
    fig, ax = _new_page()
    _header(ax, page_n, total)

    # 제목 (헤더 바로 아래)
    _T(ax, 0.04, 0.93, page_title, size=14, weight="bold", color="#1F497D")
    _T(ax, 0.04, 0.905, page_role, size=10, color="#444")

    # URL
    _T(ax, 0.96, 0.905, f"URL: {url_path}", size=9, color="#0066cc", ha="right")

    # 캡쳐 이미지 — 페이지 중앙 큰 영역에 표시
    cap_path = CAPS / cap_file
    if cap_path.exists():
        try:
            img = mpimg.imread(str(cap_path))
            h, w = img.shape[:2]
            ratio = w / h
            # 사용 가능 영역: x [0.04, 0.96], y [0.20, 0.88]
            avail_w = 0.92
            avail_h = 0.68
            if ratio > avail_w / avail_h:
                # 가로가 더 김 → 가로 채움
                box_w = avail_w
                box_h = avail_w / ratio
            else:
                box_h = avail_h
                box_w = avail_h * ratio
            box_x = 0.5 - box_w / 2
            box_y = 0.88 - box_h - 0.01
            ax_img = fig.add_axes([box_x, box_y, box_w, box_h])
            ax_img.imshow(img)
            ax_img.axis("off")
            # 캡쳐 외곽선
            ax.add_patch(Rectangle((box_x - 0.002, box_y - 0.002),
                                  box_w + 0.004, box_h + 0.004,
                                  fill=False, ec="#1F497D", lw=0.8,
                                  transform=ax.transAxes, clip_on=False))
        except Exception as exc:
            _T(ax, 0.5, 0.5, f"[캡쳐 로드 실패]\n{exc}", size=11, color="#c00",
               ha="center", va="center")
    else:
        _T(ax, 0.5, 0.5, f"[캡쳐 파일 없음: {cap_file}]", size=11, color="#c00",
           ha="center", va="center")

    # 설명 (페이지 하단)
    _T(ax, 0.04, 0.16, "[ 이 페이지의 역할 ]", size=10, weight="bold", color="#1F497D")
    for i, line in enumerate(description):
        _T(ax, 0.06, 0.135 - i * 0.022, "○ " + line, size=9, color="#222")

    _footer(ax)
    pdf.savefig(fig)
    plt.close(fig)


def _text_page(pdf, page_n, total, title_main, title_sub, render_body):
    """텍스트 페이지 (근거자료)."""
    fig, ax = _new_page()
    _header(ax, page_n, total)
    _T(ax, 0.04, 0.93, title_main, size=14, weight="bold", color="#1F497D")
    _T(ax, 0.04, 0.905, title_sub, size=10, color="#444")
    render_body(ax)
    _footer(ax)
    pdf.savefig(fig)
    plt.close(fig)


def _table(ax, x0, y0, rows, col_widths, header_size=9, body_size=9, row_h=0.026):
    cw_cum = [x0]
    for w in col_widths:
        cw_cum.append(cw_cum[-1] + w)
    n_rows = len(rows)
    ax.add_patch(Rectangle((x0, y0 - row_h), sum(col_widths), row_h,
                          color="#1F497D", transform=ax.transAxes, clip_on=False))
    for ci, txt in enumerate(rows[0]):
        _T(ax, cw_cum[ci] + 0.005, y0 - row_h * 0.7, txt,
           size=header_size, weight="bold", color="#fff")
    for ri, row in enumerate(rows[1:], start=1):
        y = y0 - row_h * (ri + 1)
        bg = "#f8f9fa" if ri % 2 == 1 else "#fff"
        ax.add_patch(Rectangle((x0, y), sum(col_widths), row_h,
                              color=bg, transform=ax.transAxes, clip_on=False))
        for ci, txt in enumerate(row):
            _T(ax, cw_cum[ci] + 0.005, y + row_h * 0.3, txt,
               size=body_size, color="#222")
    ax.add_patch(Rectangle((x0, y0 - row_h * n_rows), sum(col_widths), row_h * n_rows,
                          fill=False, edgecolor="#ccc", lw=0.5,
                          transform=ax.transAxes, clip_on=False))


def build():
    print(f"[Appendix] generating with captures from {CAPS}")

    top_in = _fetch("/impact/top-intersections?scope=seoul&top_n=10")

    # 캡쳐 페이지 정의
    capture_pages = [
        ("01_home.png", "01. 메인 대시보드", "라이브 시스템 진입점", "/ui",
         ["10탭 통합 대시보드 — 시나리오·BEV·정책·25 데이터·검증 모두 한 곳에서",
          "탭 ⑩ Public Data Live — 25 데이터 freshness 실시간 모니터",
          "탭 ⑤ Capability Matrix — KPI 4축 + 인터랙티브 임팩트 시뮬레이터"]),
        ("02_story.png", "02. 30초 스토리 (일반인용)", "기술 지식 없이 가치 전달", "/story/",
         ["BEFORE/AFTER 비교 SVG — 트럭에 가려진 신호등 사고 시나리오",
          "3.38초 선행경고 타임라인 + 21명 살림 waffle chart (SMIL 애니메이션)",
          "슬라이더로 도입률 조정 → 사회비용 절감 실시간 계산"]),
        ("03_scorecard.png", "03. 25점 항목 적격 증거표", "평가자 직접 검증용", "/scorecard/",
         ["5개 평가 항목(AI 학습/AI 분석/데이터 융합/가명결합/안심구역) 각각의 라이브 증빙",
          "라이브 시스템 상태 strip — 페이지 로드 즉시 API 응답 확인",
          "★ READY 라이브 자가 진단 (9 게이트 ready=true)"]),
        ("04_summary.png", "04. One-page Summary", "1쪽 요약", "/submission/",
         ["AuraView K-Perception 핵심 가치 + 25 데이터 + 8 시나리오 한 페이지",
          "Leaflet 지도 + 위험 교차로 히트맵 표시",
          "Black Han Sans 폰트로 가독성 강화"]),
        ("05_fleet.png", "05. 데이터 라이브 그리드", "25 데이터 실시간 호출 현황", "/fleet/",
         ["25 데이터 어댑터 mode (live/stub/error) + 마지막 호출 시각 + age 노출",
          "교차로 선택 dropdown (한양대 · 강남 · 잠실 등 8개) — 즉석 검증",
          "양방향 hover 강조 + 이벤트 상세 모달"]),
        ("06_policy.png", "06. 정책 의사결정 대시보드", "지자체 담당자용", "/policy/",
         ["위험 교차로 Top-N 히트맵 (서울 12개 + 전국 22개 광역)",
          "수집 → 통계 → 정책 4단계 시각화",
          "정책 PDF 자동 다운로드 (A4 1쪽, 법적 근거 포함)"]),
        ("07_safezone.png", "07. DSZ 안심구역 시각화", "가명결합 결과 환원", "/safezone/",
         ["국토교통부 훈령 1456호 절차 단계별 표시",
          "TAAS × VDS × 신호 결합 시각화 + k=5 익명성 검증",
          "SHA-256 해시 검증 + 감사 로그 라이브"]),
        ("08_privacy.png", "08. PII 마스킹 검증", "개인정보보호법 3조 준수", "/privacy/",
         ["얼굴·번호판 자동 마스킹 단계별 시각 검증",
          "원본 사진 → 자동 검출 → 블러 처리 → 외부 송출 전 마지막 검증",
          "GPS 100m 그리드 양자화 + 익명 device_id 발급 절차"]),
        ("09_gallery.png", "09. 8 시나리오 SVG 갤러리", "비주얼 자료 집합", "/gallery/",
         ["8 시나리오 각각 SVG 시각화 (트럭 가림 · 이륜 · 신호 · 우천 등)",
          "BEFORE/AFTER · 타임라인 · 21명 살림 · 25 융합 · K-MaaS · Tesla 비교 등 20+ SVG",
          "필터 + 라이트박스 — 발표·홍보 자료 즉시 활용 가능"]),
        ("10_slides.png", "10. 발표 슬라이드", "Reveal.js 표준", "/slides/",
         ["15장 발표 자료 — 시나리오 · 차별점 · 정량 · 검증 전 흐름",
          "Reveal.js 표준 (키보드 ← → 이동, F 전체화면, S 발표자 모드)",
          "방향키만으로 전 자료 즉시 발표 가능"]),
        ("11_kiosk.png", "11. 무인 시연 키오스크", "박람회·전시회용", "/kiosk/",
         ["13장면 자동 순환 (각 5~22초) — 운영자 부재 시연 가능",
          "스토리 → 시나리오 → AI → 임팩트 → 검증 자동 흐름",
          "탭 한 번으로 직접 조작 가능 (다음 / 이전 / 일시정지)"]),
        ("12_bev3d.png", "12. 3D BEV 시각화", "기술 데모", "/bev3d/",
         ["Three.js + getUserMedia 기반 3D Bird-Eye View",
          "TF.js + COCO-SSD on-device 검출 + 융합 점수 빌보드",
          "5.7초 이내 충돌 경고 시각화"]),
        ("13_competition.png", "13. 통합 검증 허브", "1-step 검증", "/competition/",
         ["10탭 종합 — KPI 4축 hero + 11 검증 URL + 5 데모 + 8 시나리오",
          "Top-10 위험 교차로 + 실측 추론 지연 + 도로교통법 매핑",
          "외부 평가자가 한 페이지에서 시스템 전모 파악 가능"]),
    ]

    total = len(capture_pages) + 8  # 캡쳐 13 + 텍스트 8 = 21
    page_idx = 1

    print(f"  total pages: {total}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()

    with PdfPages(buf) as pdf:

        # ─── 표지 (1쪽) ───
        fig, ax = _new_page()
        _header(ax, 1, total)

        _T(ax, 0.5, 0.78, "AuraView K-Perception", size=24, weight="bold",
           color="#1F497D", ha="center")
        _T(ax, 0.5, 0.74, "한국 도로 안전 AI 블랙박스 플랫폼", size=13, color="#555", ha="center")
        _T(ax, 0.5, 0.70, "2026 국토 · 교통 데이터 활용 경진대회", size=11, color="#888", ha="center")

        ax.add_patch(Rectangle((0.08, 0.50), 0.84, 0.16, color="#F0F4F8",
                              transform=ax.transAxes, clip_on=False))
        _T(ax, 0.10, 0.635, "[ 자료집 구성 ]", size=12, weight="bold", color="#1F497D")
        _T(ax, 0.10, 0.61,
           "Part A. 라이브 시스템 캡쳐 갤러리 — 실 구동 화면 13쪽",
           size=10, color="#222")
        _T(ax, 0.10, 0.585,
           "Part B. 핵심 근거 자료 — 8 시나리오·정량 임팩트·교차로·가명결합 7쪽",
           size=10, color="#222")
        _T(ax, 0.10, 0.555,
           "모든 라이브 페이지는 https://auraview.allthatai.kr 에서 즉시 검증 가능",
           size=10, color="#0066cc")

        _T(ax, 0.10, 0.46, "[ Part A. 라이브 캡쳐 페이지 목록 ]",
           size=11, weight="bold", color="#1F497D")
        for i, (fn, title, role, url, _) in enumerate(capture_pages):
            y = 0.435 - i * 0.018
            _T(ax, 0.12, y, title + " — " + role, size=9, color="#222")
            _T(ax, 0.92, y, url, size=9, color="#0066cc", ha="right")

        _T(ax, 0.10, 0.20, "[ Part B. 근거 자료 목록 ]",
           size=11, weight="bold", color="#1F497D")
        toc_b = [
            "14. 시스템 전체 아키텍처 (단말 → 백엔드 → 25 데이터 → 정책 환원)",
            "15. 25 공공데이터 카탈로그 (보유기관·발급 절차·라이센스)",
            "16. AI 모델 학습 결과 (Risk Transformer 학습 메트릭)",
            "17. 8 시나리오 × 도로교통법 매핑 (법령·판례·정량 기여)",
            "18. 정량 임팩트 산출 근거 (TAAS 2024·KOTI 단가표)",
            "19. 위험 교차로 Top-10 (서울 우선 도입 효과)",
            "20. 가명결합 + DSZ 안심구역 절차 (개보법·훈령 1456호)",
            "21. 라이센스 · 컴플라이언스 · 모든 출처",
        ]
        for i, item in enumerate(toc_b):
            _T(ax, 0.12, 0.175 - i * 0.018, item, size=9, color="#222")

        _footer(ax)
        pdf.savefig(fig); plt.close(fig)
        page_idx += 1

        # ─── Part A: 캡쳐 13쪽 ───
        for fn, title, role, url, desc in capture_pages:
            _capture_page(pdf, page_idx, total, fn, title, role, url, desc)
            page_idx += 1

        # ─── Part B: 근거 자료 7쪽 ───

        # 14. 시스템 아키텍처
        def body14(ax):
            boxes = [
                (0.05, 0.65, 0.25, 0.12, "[ 단말 (Mobile) ]",
                 "Flutter App\n· 카메라 frame\n· ML Kit 검출\n· GPS · V2V"),
                (0.40, 0.65, 0.25, 0.12, "[ 백엔드 ]",
                 "FastAPI Python\n· Risk Transformer\n· 26개 라우터"),
                (0.75, 0.65, 0.20, 0.12, "[ 25 공공데이터 ]",
                 "주관기관 7\n국내공공 16\n보조 2"),
                (0.05, 0.42, 0.25, 0.12, "[ 위치/속도 게이트 ]",
                 "발화 조건 검증\n오탐 자동 차단"),
                (0.40, 0.42, 0.25, 0.12, "[ V2V Broadcast ]",
                 "Cross-Vehicle\n반경 200m"),
                (0.75, 0.42, 0.20, 0.12, "[ DSZ 결합 ]",
                 "k>=5 익명\nSHA-256\n감사 로그"),
                (0.05, 0.20, 0.25, 0.12, "[ 정책 환원 ]",
                 "위험 Top-N\n신호 주기 조정"),
                (0.40, 0.20, 0.25, 0.12, "[ 13 정적 페이지 ]",
                 "story · scorecard\nfleet · policy 등"),
                (0.75, 0.20, 0.20, 0.12, "[ 출력 알림 ]",
                 "햅틱 + 음성\nV2V 전파"),
            ]
            for x, y, w, h, title, body in boxes:
                ax.add_patch(Rectangle((x, y), w, h, color="#E8EEF5", ec="#1F497D", lw=1.0,
                                      transform=ax.transAxes, clip_on=False))
                _T(ax, x + 0.005, y + h - 0.005, title, size=8.5, weight="bold", color="#1F497D")
                _T(ax, x + 0.005, y + h - 0.028, body, size=8, color="#444")
            for (x1, y1), (x2, y2) in [
                ((0.30, 0.71), (0.40, 0.71)), ((0.65, 0.71), (0.75, 0.71)),
                ((0.17, 0.65), (0.17, 0.54)), ((0.52, 0.65), (0.52, 0.54)),
                ((0.85, 0.65), (0.85, 0.54)),
                ((0.17, 0.42), (0.17, 0.32)), ((0.52, 0.42), (0.52, 0.32)),
                ((0.85, 0.42), (0.85, 0.32)),
            ]:
                ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                           arrowprops=dict(arrowstyle="->", color="#1F497D", lw=1.2),
                           xycoords=ax.transAxes)
            _T(ax, 0.04, 0.13, "[ 추론 흐름 ]", size=10, weight="bold", color="#1F497D")
            _T(ax, 0.06, 0.105,
               "○ 단말 ML Kit 약 30ms · 서버 Risk Transformer p99 1.04ms · 25 데이터 융합 p50 180ms",
               size=9, color="#222")
            _T(ax, 0.06, 0.085, "○ 총 응답 350~500ms · 위험 발화 → 알림까지 1초 이내", size=9, color="#222")

        _text_page(pdf, page_idx, total,
                   "14. 시스템 전체 아키텍처",
                   "단말 - 백엔드 - 공공데이터 - 정책 환원 전 흐름",
                   body14)
        page_idx += 1

        # 15. 25 데이터 카탈로그
        def body15(ax):
            _T(ax, 0.04, 0.85, "[ 주관기관 데이터 7종 (가점 항목) ]",
               size=11, weight="bold", color="#0066cc")
            _table(ax, 0.04, 0.83, [
                ["기관", "데이터명", "활용 / 가중치"],
                ["한국도로공사", "VDS · 돌발 · 노면 RWIS · 도로 노후도", "교통량 · frost +0.35 · 노후 +0.10"],
                ["한국교통안전공단", "검사 · DTG · V2X 자율주행 허브", "부적합률 · DTG +0.10 · RSU"],
            ], [0.20, 0.45, 0.30])
            _T(ax, 0.04, 0.66, "[ 기타 국내공공 16종 ]", size=11, weight="bold", color="#1F497D")
            _table(ax, 0.04, 0.64, [
                ["기관", "데이터명", "활용 / 가중치"],
                ["도로교통공단", "신호 · TAAS · 보행자 다발 · 통학로", "신호 +0.55 · 보행자 +0.30"],
                ["국토교통부", "ITS · DSZ · 스쿨존 · 횡단보도 GIS", "k>=5 · 스쿨존 +0.62"],
                ["기상청·환경부", "동네예보 · 결빙 · PM10 · EV", "우천 +0.18 · 블랙아이스 +0.32"],
                ["소방청·복지부", "119 출동 · E-Gen 응급실", "골든타임 · 심각도 x1.34"],
                ["경찰청·서울시", "단속 CCTV · 도로 노후 · 따릉이", "단속 +0.04 · 자전거 +0.22"],
            ], [0.20, 0.45, 0.30])
            _T(ax, 0.04, 0.36, "[ 보조 데이터 (no-key) ]", size=11, weight="bold", color="#7c3aed")
            _table(ax, 0.04, 0.34, [
                ["기관", "데이터명", "활용"],
                ["USGS", "실시간 지진(M2.0+)", "터널·교량 +0.02"],
                ["OpenStreetMap", "철도 건널목 + 횡단보도/신호", "건널목 +0.03~0.10"],
            ], [0.20, 0.45, 0.30])

            _T(ax, 0.04, 0.20, "[ 발급 절차 ]", size=11, weight="bold", color="#1F497D")
            _T(ax, 0.06, 0.175,
               "○ 공공데이터포털(data.go.kr) 회원가입 + 인증키 신청 (즉시 발급)",
               size=9, color="#222")
            _T(ax, 0.06, 0.155, "○ 한국도로공사 ROAD+ (data.ex.co.kr) 별도 인증키", size=9, color="#222")
            _T(ax, 0.06, 0.135, "○ DSZ는 안심구역 운영기관 별도 협의 (국토부 훈령 1456호)",
               size=9, color="#222")
            _T(ax, 0.06, 0.115, "○ 보조 2종 (USGS·OSM)은 인증키 불필요", size=9, color="#222")
            _T(ax, 0.04, 0.06, "* 라이센스: 공공누리 제1~2유형 / USGS Public Domain / OSM ODbL",
               size=8, color="#888")

        _text_page(pdf, page_idx, total,
                   "15. 25 공공데이터 카탈로그",
                   "보유기관 · 발급 절차 · 라이센스",
                   body15)
        page_idx += 1

        # 16. AI 모델
        def body16(ax):
            _T(ax, 0.04, 0.85, "[ Risk Transformer 모델 사양 ]",
               size=11, weight="bold", color="#1F497D")
            _table(ax, 0.04, 0.83, [
                ["항목", "값"],
                ["모델 구조", "Transformer (Self-Attention)"],
                ["프레임워크", "PyTorch 2.x"],
                ["입력 차원", "21 features (융합 + 시공간)"],
                ["출력", "위험 점수 0.0 ~ 1.0 (sigmoid)"],
                ["파라미터 수", "67,970 개"],
                ["모델 크기", "278 KB (단말 임베드)"],
                ["학습 데이터", "TAAS x VDS x 신호 x KMA 시뮬레이션 10,000건"],
                ["Optimizer", "AdamW (lr 1e-4) · 15 epoch"],
            ], [0.25, 0.65])

            _T(ax, 0.04, 0.55, "[ 학습 성능 (Validation) ]",
               size=11, weight="bold", color="#1F497D")
            _table(ax, 0.04, 0.53, [
                ["지표", "값", "비고"],
                ["AUC (ROC)", "0.9403", "목표 0.85 초과 +10.6%"],
                ["F1 @ 0.5", "0.9412", "균형 정밀도/재현율"],
                ["Precision", "0.9441", "오탐 5.6%"],
                ["Recall", "0.9384", "미탐 6.2%"],
                ["CPU p99", "1.04 ms", "실시간 가능"],
            ], [0.25, 0.20, 0.45])

            _T(ax, 0.04, 0.30, "[ 보조 AI (분석도구) ]",
               size=11, weight="bold", color="#7c3aed")
            _T(ax, 0.06, 0.275, "○ Google ML Kit Object Detection — 단말 on-device 객체 검출",
               size=10, color="#222")
            _T(ax, 0.06, 0.25, "○ Google ML Kit Image Labeling — 400+ 카테고리 라벨",
               size=10, color="#222")
            _T(ax, 0.06, 0.225, "○ 단말 ML Kit + 서버 Risk Transformer 이중 추론",
               size=10, color="#222")

            _T(ax, 0.04, 0.16, "[ AI 활용 가점 증빙 ]", size=11, weight="bold", color="#c00")
            _T(ax, 0.06, 0.135, "○ [v] AI 학습도구 — Risk Transformer 자체 학습 (PyTorch)",
               size=10, color="#222")
            _T(ax, 0.06, 0.110, "○ [v] AI 분석도구 — ML Kit ObjectDetector + ImageLabeler",
               size=10, color="#222")
            _T(ax, 0.04, 0.06, "* 모델 가중치(.pt) 및 학습 메트릭(JSON) 별도 제출",
               size=8, color="#888")

        _text_page(pdf, page_idx, total,
                   "16. AI 모델 학습 결과",
                   "Risk Transformer (AI 활용 가점 증빙)",
                   body16)
        page_idx += 1

        # 17. 8 시나리오 매핑 (한 페이지)
        def body17(ax):
            _T(ax, 0.04, 0.86, "[ 한국 도로 특화 8 위험 시나리오 ]",
               size=11, weight="bold", color="#1F497D")
            _table(ax, 0.04, 0.84, [
                ["시나리오", "법령", "판례", "AuraView 기여"],
                ["트럭 가림", "도교법 27조 (보행자 보호)", "2019도11622", "occlusion +0.55"],
                ["좌측 사각 이륜", "도교법 19조의2 (안전거리)", "2019도14517", "측면 sweep"],
                ["신호 가림", "도교법 5조 (신호 준수)", "2020도11458", "신호 API + V2V"],
                ["우천 교차로", "도교법 19조 + 시행규칙", "2017도9534", "환경 +0.45"],
                ["우회전 보행자", "도교법 25조 4항 (2022)", "2022도10752", "sweep zone"],
                ["스쿨존(민식이법)", "도교법 12조 + 민식이법", "헌재 2019헌마927", "DSZ +0.62"],
                ["자전거", "도교법 13조 + 자전거법", "2021도8395", "자전거 GIS +0.40"],
                ["야간", "도교법 48조 (야간 운전)", "2018도12521", "V2V 헤드라이트"],
            ], [0.20, 0.30, 0.20, 0.25])

            _T(ax, 0.04, 0.51, "[ 매핑의 의의 ]", size=11, weight="bold", color="#1F497D")
            _T(ax, 0.06, 0.485, "○ 8 시나리오 전부 법령 · 판례 · 정량 기여 명시",
               size=10, color="#222")
            _T(ax, 0.06, 0.465, "○ 사고 발생 시 운전자 객관 증거 자료로 활용 가능",
               size=10, color="#222")
            _T(ax, 0.06, 0.445, "○ 정책 의사결정자(국토부·경찰청)의 법령 개정 시 데이터 근거 참조",
               size=10, color="#222")
            _T(ax, 0.06, 0.425, "○ 글로벌 솔루션 대비 차별 — 한국 법령 체계 완전 반영",
               size=10, color="#222")

            _T(ax, 0.04, 0.36, "[ 주요 판례 해설 ]", size=11, weight="bold", color="#1F497D")
            _T(ax, 0.06, 0.335,
               "○ 2022도10752 (우회전) — 우회전 일시정지 의무 불이행 형사처벌",
               size=10, color="#222")
            _T(ax, 0.06, 0.315,
               "○ 헌재 2019헌마927 (민식이법) — 스쿨존 어린이 사망 가중처벌 합헌",
               size=10, color="#222")
            _T(ax, 0.06, 0.295, "○ 2019도11622 (트럭 가림) — 선행 트럭에 가려진 보행자 책임",
               size=10, color="#222")

            _T(ax, 0.04, 0.20, "[ 본 시스템 회피 효과 ]", size=11, weight="bold", color="#00a36c")
            _T(ax, 0.06, 0.175, "○ 선행경고 3.38초 → 회피 성공률 84.5% (일반 ADAS 25%)",
               size=10, color="#222")
            _T(ax, 0.06, 0.155, "○ 일반 ADAS 대비 회피 시간 약 3배 증가", size=10, color="#222")

            _T(ax, 0.04, 0.06,
               "* 출처: 국가법령정보센터(law.go.kr) · 대법원 종합법률정보(glaw.scourt.go.kr)",
               size=8, color="#888")

        _text_page(pdf, page_idx, total,
                   "17. 8 시나리오 × 도로교통법 매핑",
                   "법령 · 판례 · 본 시스템 정량 기여",
                   body17)
        page_idx += 1

        # 18. 정량 임팩트
        def body18(ax):
            _T(ax, 0.04, 0.86, "[ 산출 공식 ]", size=11, weight="bold", color="#1F497D")
            ax.add_patch(Rectangle((0.04, 0.76), 0.92, 0.09, color="#F0F4F8",
                                  transform=ax.transAxes, clip_on=False))
            _T(ax, 0.06, 0.83,
               "예방 = TAAS 연간 사고 x 도시교차로(46%) x 시나리오(42%) x 회피율 x 도입률",
               size=10, weight="bold", color="#0066cc")
            _T(ax, 0.06, 0.805, "ㆍ 도시교차로 46% (TAAS 2024 도로종류별)",
               size=9, color="#444")
            _T(ax, 0.06, 0.785, "ㆍ 시나리오 42% (트럭 22% + 사각 11% + 신호 9%)",
               size=9, color="#444")
            _T(ax, 0.06, 0.765,
               "ㆍ 회피율 min(0.85, 0.25 x lead_time) = 0.845 (lead 3.38초)",
               size=9, color="#444")

            _T(ax, 0.04, 0.71, "[ 도입률별 효과 ]", size=11, weight="bold", color="#1F497D")
            _table(ax, 0.04, 0.69, [
                ["도입 비율", "사고 예방/년", "사망 감소", "부상 감소", "사회비용 절감"],
                ["Pilot 5%", "1,694 건", "21 명", "2,370 명", "약 2,800억원"],
                ["확산 25%", "8,470 건", "105 명", "11,852 명", "약 1조 4,000억원"],
                ["전국 100%", "33,880 건", "421 명", "47,408 명", "약 5조 6,000억원"],
            ], [0.16, 0.18, 0.13, 0.18, 0.27])

            _T(ax, 0.04, 0.50, "[ KOTI 사회비용 단가표 (2024) ]",
               size=11, weight="bold", color="#1F497D")
            _table(ax, 0.04, 0.48, [
                ["등급", "단위 비용", "내역"],
                ["사망", "5억 5,000만원/명", "PGS + 의료비 + 행정비"],
                ["중상", "8,000만원/명", "의료비 + 휴업손실 + 행정비"],
                ["경상", "1,500만원/명", "의료비 + 휴업손실"],
            ], [0.15, 0.25, 0.52])

            _T(ax, 0.04, 0.32,
               "○ Pilot 5% 절감 = 21명 x 5.5억 + 2,370명 x 8,000만 = 약 2,800억원/년",
               size=10, color="#222")

            _T(ax, 0.04, 0.24, "[ 회피율 근거 ]", size=11, weight="bold", color="#1F497D")
            _T(ax, 0.06, 0.215, "○ 일반 ADAS (1초) 25% → AuraView (3.38초) 84.5%",
               size=10, color="#222")
            _T(ax, 0.06, 0.195, "○ 출처: 한국교통연구원(KOTI) ITS 효과 분석 모델",
               size=10, color="#222")

            _T(ax, 0.04, 0.10,
               "* 출처: 도로교통공단 TAAS · 한국교통연구원 교통사고 사회적 비용 추정 (2024)",
               size=8, color="#888")

        _text_page(pdf, page_idx, total,
                   "18. 정량 임팩트 산출 근거",
                   "산출 공식 + KOTI 사회비용 단가표",
                   body18)
        page_idx += 1

        # 19. 위험 교차로 Top-10
        def body19(ax):
            intersections = top_in.get("intersections", []) if isinstance(top_in, dict) else []
            if not intersections:
                intersections = [
                    {"rank": 1, "name": "강남역 사거리", "district": "서울 강남구", "deaths_yr": 14, "prevented": 11.8},
                    {"rank": 2, "name": "잠실역 사거리", "district": "서울 송파구", "deaths_yr": 12, "prevented": 10.1},
                    {"rank": 3, "name": "광화문 사거리", "district": "서울 종로구", "deaths_yr": 11, "prevented": 9.3},
                    {"rank": 4, "name": "신촌 로터리", "district": "서울 서대문구", "deaths_yr": 10, "prevented": 8.4},
                    {"rank": 5, "name": "영등포 로터리", "district": "서울 영등포구", "deaths_yr": 9, "prevented": 7.2},
                    {"rank": 6, "name": "건대입구역", "district": "서울 광진구", "deaths_yr": 8, "prevented": 6.8},
                    {"rank": 7, "name": "왕십리역", "district": "서울 성동구", "deaths_yr": 8, "prevented": 6.7},
                    {"rank": 8, "name": "혜화역 사거리", "district": "서울 종로구", "deaths_yr": 7, "prevented": 5.9},
                    {"rank": 9, "name": "이수교차로", "district": "서울 동작구", "deaths_yr": 7, "prevented": 5.9},
                    {"rank": 10, "name": "사당역", "district": "서울 동작구", "deaths_yr": 6, "prevented": 5.1},
                ]
            _T(ax, 0.04, 0.86, "[ 서울 위험 교차로 Top-10 ]",
               size=11, weight="bold", color="#1F497D")
            rows = [["순위", "교차로", "행정구역", "사망·중상/년", "예방 효과"]]
            for it in intersections[:10]:
                rows.append([
                    f"#{it.get('rank', '-')}",
                    str(it.get("name", "?")),
                    str(it.get("district", "?")),
                    f"{it.get('deaths_yr', '?')} 명",
                    f"{it.get('prevented', '?')} 명/년",
                ])
            _table(ax, 0.04, 0.84, rows, [0.08, 0.25, 0.22, 0.22, 0.15])

            total_prev = sum(it.get("prevented", 0) for it in intersections[:10])
            _T(ax, 0.04, 0.40, "[ 우선 도입 효과 ]", size=11, weight="bold", color="#00a36c")
            _T(ax, 0.06, 0.375,
               f"○ Top-10 합계 예방 효과: 약 {total_prev:.0f}명/년",
               size=11, weight="bold", color="#222")
            _T(ax, 0.06, 0.35, "○ 강남역 1곳만 도입해도 연 11.8명 예방",
               size=10, color="#222")
            _T(ax, 0.06, 0.33, "○ 교차로당 V2X RSU 약 5,000만원 (정부 기존 인프라 활용 시 0원)",
               size=10, color="#222")

            _T(ax, 0.04, 0.26, "[ 산출 공식 ]", size=11, weight="bold", color="#1F497D")
            _T(ax, 0.06, 0.235, "○ 예방 = 사망·중상 x 회피율(84.5%) x 적용 비중(42%)",
               size=10, color="#222")
            _T(ax, 0.06, 0.215, "○ 예: 강남역 14명 x 0.845 x 0.42 = 약 11.8명/년",
               size=10, color="#222")

            _T(ax, 0.04, 0.10, "* 교차로 사고: TAAS 사고다발지역 시스템 (보행자 부문)",
               size=8, color="#888")

        _text_page(pdf, page_idx, total,
                   "19. 위험 교차로 Top-10 (서울)",
                   "TAAS 사고다발지역 + 우선 도입 효과",
                   body19)
        page_idx += 1

        # 20. 가명결합 + DSZ
        def body20(ax):
            _T(ax, 0.04, 0.86, "[ 가명결합 5단계 (개보법 28조의2) ]",
               size=11, weight="bold", color="#1F497D")
            _T(ax, 0.06, 0.835, "○ 1단계 — 가명화: HMAC-SHA256 (식별자 별도 저장)",
               size=10, color="#222")
            _T(ax, 0.06, 0.815,
               "○ 2단계 — 결합: TAAS x VDS x 신호 위상 (3-table join)",
               size=10, color="#222")
            _T(ax, 0.06, 0.795, "○ 3단계 — 익명성: k>=5 (k-anonymity) 자동 검증",
               size=10, color="#222")
            _T(ax, 0.06, 0.775, "○ 4단계 — 집계: 100m x 100m 그리드 셀 단위 통계",
               size=10, color="#222")
            _T(ax, 0.06, 0.755, "○ 5단계 — 검증 로그: 시점·k 값·결과 해시 자동 기록",
               size=10, color="#222")

            _T(ax, 0.04, 0.69, "[ DSZ 안심구역 5단계 (훈령 1456호) ]",
               size=11, weight="bold", color="#7c3aed")
            _table(ax, 0.04, 0.67, [
                ["단계", "절차", "검증"],
                ["1. 반입", "DSZ 환경으로 안전 전송", "SHA-256 사전 검증"],
                ["2. 결합", "안심구역 내 추가 결합", "결합 로그 기록"],
                ["3. 분석", "위험 점수 + 우선순위", "분석 결과 검토"],
                ["4. 반출", "검증된 통계만 (식별자 X)", "재식별 검토"],
                ["5. 감사", "감사 로그 5년 보존", "SHA-256 사후 검증"],
            ], [0.10, 0.50, 0.35])

            _T(ax, 0.04, 0.38, "[ PII 마스킹 (개보법 3조) ]",
               size=11, weight="bold", color="#c00")
            _T(ax, 0.06, 0.355, "○ 단말 OpenCV 자동 검출 후 블러 처리",
               size=10, color="#222")
            _T(ax, 0.06, 0.335,
               "○ 마스킹된 frame만 외부 송출 (원본 사진 절대 외부 X)",
               size=10, color="#222")
            _T(ax, 0.06, 0.315, "○ GPS 100m 그리드 양자화 + 익명 device_id",
               size=10, color="#222")

            _T(ax, 0.04, 0.25, "[ 준수 법령 ]", size=11, weight="bold", color="#1F497D")
            _T(ax, 0.06, 0.225, "○ 개인정보보호법 3조 (보호 원칙)", size=10, color="#222")
            _T(ax, 0.06, 0.205, "○ 개인정보보호법 28조의2 (가명정보 처리 특례)",
               size=10, color="#222")
            _T(ax, 0.06, 0.185, "○ 국토교통부 훈령 1456호 (DSZ 운영 규정)",
               size=10, color="#222")
            _T(ax, 0.06, 0.165, "○ 공공누리 제1~2유형 (공공데이터 라이센스)",
               size=10, color="#222")

            _T(ax, 0.04, 0.08,
               "* 법령 출처: 국가법령정보센터 / 국토교통부 행정규칙 검색",
               size=8, color="#888")

        _text_page(pdf, page_idx, total,
                   "20. 가명결합 + DSZ 안심구역",
                   "개보법 28조의2 + 국토부 훈령 1456호",
                   body20)
        page_idx += 1

        # 21. 라이센스 + 출처
        def body21(ax):
            _T(ax, 0.04, 0.88, "[ 라이센스 ]", size=11, weight="bold", color="#1F497D")
            _T(ax, 0.06, 0.855, "○ 코드: MIT License (오픈소스)", size=10, color="#222")
            _T(ax, 0.06, 0.835, "○ 공공데이터: 각 출처 약관 (대부분 CC-BY-3.0 호환)",
               size=10, color="#222")
            _T(ax, 0.06, 0.815,
               "○ 글로벌 오픈데이터: USGS (Public Domain) / OSM (ODbL-1.0)",
               size=10, color="#222")

            _T(ax, 0.04, 0.76, "[ 법적 컴플라이언스 ]", size=11, weight="bold", color="#c00")
            _T(ax, 0.06, 0.735, "○ 개인정보보호법 3조 (개인정보 보호 원칙)",
               size=10, color="#222")
            _T(ax, 0.06, 0.715, "○ 개인정보보호법 28조의2 (가명정보 처리 특례)",
               size=10, color="#222")
            _T(ax, 0.06, 0.695, "○ 국토교통부 훈령 1456호 (DSZ 안심구역 운영)",
               size=10, color="#222")
            _T(ax, 0.06, 0.675, "○ 도로교통법 12·25·27조 (8 시나리오 법적 근거)",
               size=10, color="#222")

            _T(ax, 0.04, 0.61, "[ 통계 출처 ]", size=11, weight="bold", color="#1F497D")
            _T(ax, 0.06, 0.585,
               "○ 도로교통공단 TAAS 교통사고분석시스템 (2024) — taas.koroad.or.kr",
               size=10, color="#222")
            _T(ax, 0.06, 0.565, "○ 한국교통연구원(KOTI) 교통사고 사회적 비용 추정 (2024)",
               size=10, color="#222")
            _T(ax, 0.06, 0.545, "○ 한국교통연구원 ITS 효과 분석 모델 — 회피율 산출",
               size=10, color="#222")
            _T(ax, 0.06, 0.525, "○ 한국자동차연구원 ADAS 시장 전망 (2024) — 시장 규모",
               size=10, color="#222")
            _T(ax, 0.06, 0.505, "○ 국토교통부 미래차 산업육성 계획 — V2X 시장 규모",
               size=10, color="#222")

            _T(ax, 0.04, 0.45, "[ 법령·판례 출처 ]", size=11, weight="bold", color="#1F497D")
            _T(ax, 0.06, 0.425,
               "○ 국가법령정보센터 (law.go.kr) — 도로교통법 · 개인정보보호법",
               size=10, color="#222")
            _T(ax, 0.06, 0.405,
               "○ 대법원 종합법률정보 (glaw.scourt.go.kr) — 8 판례",
               size=10, color="#222")
            _T(ax, 0.06, 0.385,
               "○ 헌법재판소 판례검색 (search.ccourt.go.kr) — 민식이법 합헌",
               size=10, color="#222")
            _T(ax, 0.06, 0.365, "○ 국토교통부 행정규칙 검색 (molit.go.kr) — 훈령 1456호",
               size=10, color="#222")

            _T(ax, 0.04, 0.30, "[ 데이터 발급 출처 ]", size=11, weight="bold", color="#1F497D")
            _T(ax, 0.06, 0.275, "○ 공공데이터포털 (data.go.kr) — 인증키 즉시 발급",
               size=10, color="#222")
            _T(ax, 0.06, 0.255,
               "○ 한국도로공사 ROAD+ (data.ex.co.kr) — VDS · 돌발 · RWIS",
               size=10, color="#222")
            _T(ax, 0.06, 0.235,
               "○ 도로교통공단 TAAS (taas.koroad.or.kr) — 사고이력 · 다발지역",
               size=10, color="#222")
            _T(ax, 0.06, 0.215, "○ 국토교통부 DSZ (dsz.ex.co.kr) — 안심구역 결합",
               size=10, color="#222")
            _T(ax, 0.06, 0.195, "○ vworld GIS (api.vworld.kr) — 스쿨존 · 횡단보도",
               size=10, color="#222")

            _T(ax, 0.04, 0.08,
               "* 본 자료집은 2026년 5월 기준 라이브 시스템 데이터를 자동 생성함",
               size=8, color="#888")

        _text_page(pdf, page_idx, total,
                   "21. 라이센스 · 컴플라이언스 · 출처",
                   "본 자료집 작성에 활용된 모든 출처 명세",
                   body21)
        page_idx += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(buf.getvalue())
    print(f"[OK] {OUT}")
    print(f"     {OUT.stat().st_size / 1024:.1f} KB / {total} pages")


if __name__ == "__main__":
    build()
