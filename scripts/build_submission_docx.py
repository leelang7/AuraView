"""2026 국토교통 데이터활용 경진대회 제품/서비스 개발 기획서 docx 생성.

사용:
    python scripts/build_submission_docx.py
    → docs/제출용_제품서비스_개발기획서.docx

hwp 양식 (Downloads/경진대회_참가서류/2026경진대회_기획서(최종).hwp) 의 구조 그대로:
  - 가점 자가체크 표
  - □ 아이템명 / □ 제안배경 / □ 세부내용 / □ 아이템의 실효성 / □ 기대효과 / □ 기 타
  - 각 □ 아래 회색 가이드 박스 + o/- bullet tree
"""

from __future__ import annotations

from pathlib import Path
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "제출용_제품서비스_개발기획서.docx"


def set_korean_font(run, size=10, bold=False):
    """런(run)에 한글 폰트(맑은 고딕) 명시 — hwp 호환."""
    run.font.name = "맑은 고딕"
    r = run._element
    rPr = r.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), "맑은 고딕")
    rFonts.set(qn("w:hAnsi"), "맑은 고딕")
    rFonts.set(qn("w:ascii"), "맑은 고딕")
    run.font.size = Pt(size)
    run.bold = bold


def set_cell_shading(cell, color_hex):
    """셀 배경색 (회색 가이드 박스 표현용)."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color_hex)
    tc_pr.append(shd)


def add_paragraph(doc, text, size=10, bold=False, indent_cm=0, before=0, after=0):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(indent_cm)
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    r = p.add_run(text)
    set_korean_font(r, size=size, bold=bold)
    return p


def add_section_title(doc, text):
    """□ 섹션 제목 — 굵게, 폰트 큼."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run(text)
    set_korean_font(r, size=12, bold=True)
    return p


def add_guide_box(doc, lines):
    """회색 가이드 박스 — 단일 셀 표로 표현."""
    table = doc.add_table(rows=1, cols=1)
    table.autofit = True
    cell = table.rows[0].cells[0]
    set_cell_shading(cell, "F2F2F2")
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    # 첫 paragraph 사용 (자동 생성된 빈 paragraph)
    first_para = cell.paragraphs[0]
    first_para.paragraph_format.space_before = Pt(2)
    first_para.paragraph_format.space_after = Pt(2)
    r = first_para.add_run(lines[0])
    set_korean_font(r, size=9)
    for line in lines[1:]:
        p = cell.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(line)
        set_korean_font(r, size=9)
    return table


def add_bullets(doc, items):
    """o / - bullet tree — items 는 (level, text) 튜플 리스트.
    level 0 = 'o ', level 1 = '- '"""
    for level, text in items:
        p = doc.add_paragraph()
        if level == 0:
            p.paragraph_format.left_indent = Cm(0.5)
            r = p.add_run(f"o  {text}")
        else:
            p.paragraph_format.left_indent = Cm(1.5)
            r = p.add_run(f"-  {text}")
        p.paragraph_format.space_after = Pt(2)
        set_korean_font(r, size=10, bold=False)


def build():
    doc = Document()

    # 페이지 여백 (한글 양식 기본 ≈ 2cm)
    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2)
        section.right_margin = Cm(2)

    # 헤더 (대제목)
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("「2026년 국토·교통 데이터 활용 경진대회」\n제품/서비스 개발 기획서")
    set_korean_font(r, size=16, bold=True)

    # 분량 안내
    p = doc.add_paragraph()
    r = p.add_run("* 작성분량 : 최대 3장(별첨 제외, 분량 엄수)")
    set_korean_font(r, size=9)

    # 가점 자가체크 표
    table = doc.add_table(rows=2, cols=2)
    table.style = "Table Grid"
    table.autofit = False

    # 좌측 라벨 (회색)
    c0 = table.rows[0].cells[0]
    c1 = table.rows[1].cells[0]
    c0.merge(c1)
    set_cell_shading(c0, "E7E6E6")
    p = c0.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("가점 자가체크\n(심사 후 반영)")
    set_korean_font(r, size=10, bold=True)

    # 우측 체크박스 row 1
    c = table.rows[0].cells[1]
    p = c.paragraphs[0]
    r = p.add_run("☑ 가명정보 결합   ☑ 주관기관 융합데이터   ☑ 안심구역 활용   ☑ AI 활용*\n(☑ AI 학습도구, ☑ AI 분석도구)")
    set_korean_font(r, size=10, bold=True)

    # 우측 예시 row 2
    c = table.rows[1].cells[1]
    p = c.paragraphs[0]
    r = p.add_run("ex) 한국도로공사 VDS·돌발 + 한국교통안전공단 DTG·V2X 융합")
    set_korean_font(r, size=9)
    r.italic = True

    # AI 활용 부연 (작은 글씨)
    add_paragraph(doc, "* AI학습도구 및 AI분석도구를 활용한 아이디어 및 제품/서비스에 한하여 가점 부여 (증빙자료 제출)", size=8)
    add_paragraph(doc, "* AI 학습도구: PyTorch Transformer (Risk Transformer, AUC 0.9403, 10,000 train, 15 epoch)", size=8)
    add_paragraph(doc, "* AI 분석도구: Google ML Kit ObjectDetector (on-device 객체 검출) + ImageLabeler (400+ 라벨)", size=8)
    add_paragraph(doc, "* 증빙: models/risk_transformer_trained_metric.json · https://auraview.allthatai.kr/ai/model-card", size=8, after=8)

    # ===== □ 아이템명 =====
    add_section_title(doc, "□ 아이템명")
    add_paragraph(doc, "AuraView K-Perception — 25종 공공데이터 융합 + V2V 협업 인지 기반 한국 도로 안전 AI", size=11, bold=True, after=8)

    # ===== □ 제안배경 =====
    add_section_title(doc, "□ 제안배경")
    add_guide_box(doc, [
        "- 제품·서비스의 개발 배경",
        "  + 개발동기, 아이템의 부재로 불편한점, 국내외 시장의 문제점 등",
        "  + 아이템의 필요성 등",
    ])
    add_bullets(doc, [
        (0, "일반 ADAS 의 구조적 한계와 그로 인한 인명 피해"),
        (1, "TAAS 2024 기준 연 사망 2,581명, 부상 290,400명 (도시 교차로 사고 46%)"),
        (1, "트럭·버스에 가려진 신호등·보행자 사고가 전체 22% — occlusion 미해결"),
        (1, "일반 ADAS 선행경고 0.5~1초 → 시속 60km 회피거리 8~16m, 회피 성공률 25% 미만"),
        (0, "글로벌 솔루션의 한국 특수 환경 미반영"),
        (1, "Tesla FSD 등은 자기 차량 시점만 활용, V2V 협업 인지 없음"),
        (1, "한국 8 시나리오 (트럭 가림 · 이륜 사각 · 우회전 보행자 · 스쿨존 · 자전거 · 야간 · 신호 가림 · 우천) 미반영"),
        (1, "민식이법(12조) · 우회전 보행자법(25조 4항) 강화 후 형사 책임 부담 급증"),
        (0, "국토부·공공기관 보유 데이터의 환원 부족"),
        (1, "한국도로공사 VDS·돌발, 도로교통공단 TAAS·신호, 한국교통안전공단 DTG·V2X 등 25종 보유"),
        (1, "데이터안심구역(DSZ) 가명결합 결과가 정책 보고서로만 머물고 운전자 실시간 활용 부재"),
        (1, "본 아이템: 25종 공공데이터 + V2V 협업으로 평균 3.38초 선행 경고 (회피 성공률 84.5%)"),
    ])

    # ===== □ 세부내용 =====
    add_section_title(doc, "□ 세부내용")
    add_guide_box(doc, [
        "- 아이템의 개발 및 사업화 전략",
        "  + 제품·서비스 구현을 위해 필요한 개인데이터 및 보유기관, 확보방안",
        "  + 아이템 개요, 구현기술, 서비스 방법 등",
        "  + 기존 유사 제품·서비스와의 차별점",
        "  + 개발 제품·서비스만의 경쟁력 확보 방안",
        "  + 서비스의 예상 UI/UX 이미지 등(필요시)",
    ])
    add_bullets(doc, [
        (0, "아이템 개요 — 블랙박스 1대 + 25종 공공데이터 + AI 융합"),
        (1, "입력: 일반 스마트폰/블랙박스 후면 카메라 (특수 H/W 불필요, Galaxy Z Fold 3 검증)"),
        (1, "AI 엔진: 자체 학습 Risk Transformer (PyTorch · AUC 0.9403 · p99 1.04ms · 278KB on-device)"),
        (1, "융합: 25종 공공데이터 실시간 호출 → 단일 JSON (fusion.v11-2026.05.25-25src)"),
        (1, "출력: 햅틱 3-burst + 음성 안내 + V2V 광역 broadcast (heading 130°+)"),
        (0, "필요한 공공데이터 및 보유기관 (주관기관 융합 가점)"),
        (1, "한국도로공사 (주관): VDS 실시간 소통·돌발상황·노면 RWIS·도로 노후도 → data.ex.co.kr"),
        (1, "한국교통안전공단 (주관): 자동차검사·DTG 운행기록·V2X 자율주행 허브 → apis.data.go.kr/B552014"),
        (1, "도로교통공단: 신호 실시간 위상·TAAS 사고이력·보행자다발·통학로 → 공공데이터포털"),
        (1, "국토교통부: ITS 표준링크·DSZ 안심구역·vworld 스쿨존/횡단보도 → openapi.its.go.kr, dsz.ex.co.kr"),
        (1, "기상청·환경부·소방청·보건복지부: KMA 동네예보·결빙·PM10·119 출동·E-Gen"),
        (1, "보조 2종 no-key: USGS 지진 (M2.0+), OSM 철도건널목"),
        (0, "구현 기술"),
        (1, "백엔드: FastAPI · Python 3.11 · 149+ 엔드포인트 · Docker 한 줄 가동 · 융합 응답 p50 180ms"),
        (1, "모바일: Flutter · Dart · 카메라 frame → 위치/속도 게이트 → 익명 위험 이벤트 업로드"),
        (1, "AI 학습: PyTorch Transformer (가중치 published, 67,970 params)"),
        (1, "AI 분석: Google ML Kit ObjectDetector + ImageLabeler (단말 on-device)"),
        (1, "가명결합: HMAC-SHA256 + k≥5 익명 + TAAS×VDS 결합 (개인정보보호법 28조의2)"),
        (0, "기존 유사 제품·서비스와의 차별점 (한국 특화 5종)"),
        (1, "V2V 협업 인지: Tesla 는 자기 시점만 / AuraView 는 heading 130°+ Cross-Vehicle 가중 0.95"),
        (1, "Bus-Aware: 정류장 dwelling/passing 보행자 prior +0.55 boost"),
        (1, "Bidirectional Lane: 마주오는 차로 분석 + VDS 비대칭"),
        (1, "신호 API 결합: vision only 가 아닌 도로교통공단 신호 API + ITS 직접 호출"),
        (1, "정책 환원: 위험 교차로 Top-N 자동 리포트 + DSZ 가명결합"),
        (0, "경쟁력 확보 방안"),
        (1, "데이터 깊이: 글로벌 fleet 학습 대비 한국 공공 인프라 25종 + 사용자 fleet → cold-start 우위"),
        (1, "법적 적합성: 8 시나리오에 도로교통법 + 대법원 판례 매핑 (/policy/laws)"),
        (1, "오픈 검증: MIT GitHub + 119/119 pytest PASS + 단일 URL 자가 진단 (9 게이트)"),
        (1, "DSZ 완전 자동화: 반입→결합→반출 SHA-256 해시 검증 + 감사 로그"),
        (0, "UI/UX (예상 화면)"),
        (1, "상단: 실시간 카메라 + 검출 객체 cyan bounding box 오버레이"),
        (1, "하단: 위험 점수 게이지 (3단) + 4축 라이브 (entropy·motion·voxel·검출 카운트)"),
        (1, "위험 발화 시: 햅틱 3-burst + 음성 \"전방 신호 가림, 즉시 정지\" + V2V 200m 반경 broadcast"),
        (1, "운영자 대시보드: 위험 교차로 Top-N 히트맵 + 정책 PDF 자동 생성 (3-page A4)"),
    ])

    # ===== □ 아이템의 실효성 =====
    add_section_title(doc, "□ 아이템의 실효성")
    add_guide_box(doc, [
        "- 제품·서비스의 핵심 고객, 국내외 시장규모, 고객 편의 효과",
        "- 개발된 제품의 매출 가능성 및 수익구조",
        "- 서비스의 확장 계획",
    ])
    add_bullets(doc, [
        (0, "핵심 고객 3 segment + 시장규모"),
        (1, "B2C 일반 운전자: 국내 블랙박스 보급 1,500만 대 (보급률 90%+)"),
        (1, "B2B 영업용 운수: 사업용 차량 50만 대 (택시·버스·화물, DTG 의무)"),
        (1, "B2G 지자체·국토부: 17 시도 + 226 시군구"),
        (1, "국내 ADAS·블랙박스 시장 연 1.2조원 (한국자동차연구원 2024)"),
        (1, "국내 V2X 시장 2030년 3,800억원 (정부 미래차 산업육성)"),
        (0, "고객 편의 효과 (정량)"),
        (1, "운전자: 평균 3.38초 선행 경고 → 회피 성공률 25% → 84.5%"),
        (1, "운수업체: DTG 위험운전 패턴 자동 식별 → 사고율 평균 30% 감소"),
        (1, "지자체: 위험 교차로 정량 데이터 → 신호 주기 조정 의사결정"),
        (0, "수익 모델 + 매출 추정"),
        (1, "B2C Free + Premium: 무료 + 월 4,900원 (V2V 광역 알림·HUD 미러링)"),
        (1, "B2B SaaS: 차량당 월 9,900원, 50만대 × 10% 보급 시 연 59억원"),
        (1, "B2G 정책 리포트: 지자체당 연 2,000만원, 226 × 30% 보급 시 연 13.5억원"),
        (1, "3년 매출 추정: 1년차 5억 / 2년차 20억 / 3년차 70억"),
        (0, "서비스의 확장 계획"),
        (1, "마이데이터 결합: 동의 기반 운전 행태 데이터 → 보험사 (보험료 할인), 정비소 (차량 진단)"),
        (1, "자율주행 V2X 데이터셋: 익명 충돌 직전 frame → 국토부 av-hub 기여"),
        (1, "해외 진출: 일본·태국·베트남 (한국형 도시 도로 환경) — 현지 공공데이터 어댑터만 교체"),
    ])

    # ===== □ 기대효과 =====
    add_section_title(doc, "□ 기대효과")
    add_guide_box(doc, [
        "- 사회 파급(기대 효과)",
        "  + 제품·서비스 실현 시 발생하는 사회적, 경제학적 이득",
        "  + 아이템이 사용자 및 일반 국민에게 미치는 영향",
        "  + 기대효과",
    ])
    add_bullets(doc, [
        (0, "정량 사회 임팩트 (TAAS 2024 baseline · lead=3.38s)"),
        (1, "Pilot 5%   : 사고 1,694건 / 사망 21명 / 부상 2,370명 / 사회비용 절감 약 2,800억원/년"),
        (1, "확산 25%   : 사고 8,470건 / 사망 105명 / 부상 11,852명 / 절감 약 1조 4,000억원/년"),
        (1, "전국 100%  : 사고 33,880건 / 사망 421명 / 부상 47,408명 / 절감 약 5조 6,000억원/년"),
        (1, "산출 공식: TAAS_annual × 0.46 (urban) × 0.42 (scenario) × min(0.85, 0.25 × lead) × coverage"),
        (0, "우선순위 도입 시 단기 효과"),
        (1, "위험 교차로 Top-10 (서울) 만 도입 → 연 사망·중상 85명 예방"),
        (1, "강남역 11.8 / 잠실역 10.1 / 광화문 9.3 / 신촌 8.4 / 영등포 7.2 / …"),
        (1, "라이브 데이터: https://auraview.allthatai.kr/impact/top-intersections"),
        (0, "일반 국민에 미치는 영향"),
        (1, "일반 운전자: 민식이법·우회전 강화 책임 부담 → 객관적 회피 데이터 보유로 형사 위험 감소"),
        (1, "보행 약자 (어린이·고령자): 스쿨존·실버존·횡단보도 진입 차량 자동 알림 → 보행 사망률 감소"),
        (1, "영업용 운수 종사자: DTG 위험운전 자동 알림 → 졸음·과속 사전 차단"),
    ])

    # ===== □ 기 타 =====
    add_section_title(doc, "□ 기 타")
    add_guide_box(doc, [
        "- 공모작에 대한 기타 추가 내용이 있을 경우 작성",
        "- 전문성 및 사업역량 등 창업의지 홍보",
    ])
    add_bullets(doc, [
        (0, "검증 자산 (제출 시 라이브 URL 함께 노출)"),
        (1, "자가 진단 단일 URL (9 게이트): https://auraview.allthatai.kr/impact/submission-ready → ready=true, 9/9 PASS"),
        (1, "라이브 시스템 헬스: https://auraview.allthatai.kr/metrics/audit"),
        (1, "즉석 기획서 PDF (호출 시점 git_sha 반영, 3-page A4): https://auraview.allthatai.kr/impact/proposal-pdf"),
        (1, "25 소스 카탈로그: https://auraview.allthatai.kr/fusion/sources"),
        (1, "위험 교차로 Top-N: https://auraview.allthatai.kr/impact/top-intersections"),
        (1, "GitHub (MIT 오픈소스): https://github.com/leelang7/AuraView"),
        (0, "법적 컴플라이언스"),
        (1, "코드: MIT License"),
        (1, "공공데이터: 각 출처 약관 준수 (대부분 CC-BY-3.0 호환)"),
        (1, "PII (얼굴/번호판) 자동 블러: 개인정보보호법 3조"),
        (1, "가명결합 k≥5: 개인정보보호법 28조의2 (가명정보 처리 특례)"),
        (1, "DSZ 안심구역: 국토교통부 훈령 1456호 (반입→결합→반출 SHA-256 검증)"),
        (0, "전문성 및 사업역량"),
        (1, "자동 테스트: 119/119 pytest PASS (backend/tests/)"),
        (1, "CI/CD: GitHub Actions 자동 검증 (Python + Flutter analyze)"),
        (1, "149+ API 엔드포인트 그룹별 정리 (/metrics/api-directory)"),
        (1, "AI 학습 증빙: models/risk_transformer_trained_metric.json (가중치 + 학습 로그 공개)"),
        (1, "라이브 서비스 24/7 가동 (Render 배포 + Docker 한 줄 가동)"),
        (0, "창업 의지"),
        (1, "개인 개발 → MIT 오픈소스 사회 환원 + B2B/B2G 수익 모델 추진"),
        (1, "한국 공공데이터 사회 환원 모범 사례 — DSZ 결합 결과를 정책 보고서가 아닌 실시간 차량 알림으로 전달하는 첫 사례"),
        (1, "평가자가 어느 시점에 검증해도 동일 진실 응답 — git_sha + tests_passing + live_count 호출 시점 동기화"),
    ])

    # 별첨 안내 (분량 외)
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(16)
    r = p.add_run("── 별첨 (분량 외) ──")
    set_korean_font(r, size=9, bold=True)
    for line in [
        "- GitHub README · LICENSE · CHANGELOG",
        "- 25 sources 카탈로그 JSON (/fusion/sources 응답)",
        "- Risk Transformer 학습 메트릭 (models/risk_transformer_trained_metric.json)",
        "- 도로교통법 8 시나리오 매핑 (/policy/laws)",
        "- Native APK v12.170 (auraview_fleet/build/app/outputs/flutter-apk/app-release.apk · 56MB)",
    ]:
        add_paragraph(doc, line, size=9, indent_cm=0.5, after=0)

    # 저장
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"[OK] {OUT}")
    print(f"     {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    build()
