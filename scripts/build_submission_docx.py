"""2026 국토교통 데이터활용 경진대회 제품/서비스 개발 기획서 docx 생성.

사용:
    python scripts/build_submission_docx.py
    → docs/제출용_제품서비스_개발기획서.docx

★ 양식 분량 엄수: 최대 3장 (별첨 제외)
   본문 압축, 표 2개 핵심만, 줄간격 1.15, 9pt 폰트로 3장 안에 맞춤.
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


def set_korean_font(run, size=9, bold=False, color=None):
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
    if color:
        run.font.color.rgb = RGBColor(*color)


def set_cell_shading(cell, color_hex):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color_hex)
    tc_pr.append(shd)


def add_paragraph(doc, text, size=9, bold=False, indent_cm=0, before=0, after=1, align=None, color=None, line_spacing=1.15):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(indent_cm)
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = line_spacing
    if align:
        p.alignment = align
    r = p.add_run(text)
    set_korean_font(r, size=size, bold=bold, color=color)
    return p


def add_body(doc, text):
    """본문 단락 — 9pt, 줄간격 1.15, 양쪽 정렬, 첫 줄 들여쓰기 0.4cm, 단락 후 간격 2pt."""
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.4)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.15
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    r = p.add_run(text)
    set_korean_font(r, size=9)
    return p


def add_section_title(doc, text, top_space=6):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(top_space)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(text)
    set_korean_font(r, size=11, bold=True)
    return p


def add_sub_title(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.left_indent = Cm(0.2)
    r = p.add_run(text)
    set_korean_font(r, size=9.5, bold=True, color=(0x1F, 0x49, 0x7D))
    return p


def add_table(doc, rows, header_shading="DBE5F1"):
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    table.autofit = True
    for ri, row in enumerate(rows):
        for ci, cell_text in enumerate(row):
            cell = table.rows[ri].cells[ci]
            if ri == 0:
                set_cell_shading(cell, header_shading)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.0
            r = p.add_run(cell_text)
            set_korean_font(r, size=8, bold=(ri == 0))
    return table


def add_bullet(doc, text, level=0):
    p = doc.add_paragraph()
    if level == 0:
        p.paragraph_format.left_indent = Cm(0.4)
        marker = "○ "
    else:
        p.paragraph_format.left_indent = Cm(1.0)
        marker = "- "
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.15
    r = p.add_run(f"{marker}{text}")
    set_korean_font(r, size=9)


def build():
    doc = Document()
    # 페이지 여백 축소 (3장 분량 확보)
    for section in doc.sections:
        section.top_margin = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin = Cm(1.8)
        section.right_margin = Cm(1.8)

    # ── 표지 (한 줄로 축소) ──
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run("「2026년 국토·교통 데이터 활용 경진대회」  제품/서비스 개발 기획서")
    set_korean_font(r, size=13, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run("* 작성분량: 최대 3장 (별첨 제외, 분량 엄수)")
    set_korean_font(r, size=8, color=(0x80, 0x80, 0x80))

    # ── 가점 자가체크 ──
    tbl = doc.add_table(rows=2, cols=2)
    tbl.style = "Table Grid"
    c00 = tbl.rows[0].cells[0]; c10 = tbl.rows[1].cells[0]; c00.merge(c10)
    set_cell_shading(c00, "E7E6E6")
    pp = c00.paragraphs[0]; pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pp.paragraph_format.space_before = Pt(0); pp.paragraph_format.space_after = Pt(0)
    rr = pp.add_run("가점 자가체크\n(심사 후 반영)")
    set_korean_font(rr, size=9, bold=True)
    pp = tbl.rows[0].cells[1].paragraphs[0]
    pp.paragraph_format.space_before = Pt(0); pp.paragraph_format.space_after = Pt(0)
    rr = pp.add_run("☑ 가명정보 결합   ☑ 주관기관 융합데이터   ☑ 안심구역 활용   ☑ AI 활용 (☑ 학습도구, ☑ 분석도구)")
    set_korean_font(rr, size=9, bold=True)
    pp = tbl.rows[1].cells[1].paragraphs[0]
    pp.paragraph_format.space_before = Pt(0); pp.paragraph_format.space_after = Pt(0)
    rr = pp.add_run("AI 학습: PyTorch Risk Transformer (AUC 0.9403) · AI 분석: Google ML Kit ObjectDetector + ImageLabeler")
    set_korean_font(rr, size=8); rr.italic = True

    # ── □ 아이템명 ──
    add_section_title(doc, "□ 아이템명", top_space=6)
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.2)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run("AuraView K-Perception")
    set_korean_font(r, size=11, bold=True, color=(0x00, 0x66, 0xCC))
    r = p.add_run("  ─  25종 공공데이터 융합 + V2V 협업 인지 기반 한국 도로 안전 AI 블랙박스 플랫폼")
    set_korean_font(r, size=10, bold=True)

    # ── □ 제안배경 ──
    add_section_title(doc, "□ 제안배경")
    add_body(doc,
        "한국 도로에서는 연간 2,581명이 사망(TAAS 2024)하며 도시 교차로 사고가 전체의 46%를 차지한다. "
        "트럭·버스에 가려진 신호등·보행자 사고가 22%에 달하나, 일반 ADAS는 카메라 단일 시점만 활용하여 사각지대 객체를 사전 감지하지 못한다. "
        "선행경고 0.5~1초로 시속 60km 회피거리 8~16m, 회피 성공률 25% 미만에 그친다.")
    add_body(doc,
        "Tesla FSD 등 글로벌 솔루션은 자기 차량 시점만 사용하며 한국 8 시나리오(트럭 가림·이륜 사각·우회전 보행자·스쿨존·자전거·야간·신호 가림·우천)에 대한 prior를 가지지 않는다. "
        "민식이법(12조)·우회전 보행자법(25조 4항) 강화로 운전자 형사 책임이 커진 상황에서 객관적 회피 데이터가 필요하다.")
    add_body(doc,
        "한국도로공사 VDS·돌발, 도로교통공단 TAAS·신호, 한국교통안전공단 DTG·V2X, DSZ 안심구역 등 25종 공공데이터가 구축되어 있으나 정책 보고서 형태로만 머문다. "
        "본 아이템은 이를 단일 응답으로 융합하고 V2V 협업 인지를 결합해 평균 3.38초 선행경고(회피 성공률 84.5%)를 제공한다.")

    # ── □ 세부내용 ──
    add_section_title(doc, "□ 세부내용")

    add_sub_title(doc, "1. 시스템 개요")
    add_body(doc,
        "일반 스마트폰·블랙박스 후면 카메라 한 대만으로 동작(특수 H/W 불필요, Galaxy Z Fold 3 검증). "
        "단말은 카메라 frame을 Google ML Kit(AI 분석도구)과 자체 학습 Risk Transformer(AI 학습도구, PyTorch · AUC 0.9403 · 278KB · p99 1.04ms)에 입력해 객체 검출과 위험점수를 산출한다. "
        "서버는 25종 공공데이터를 실시간 호출해 단일 JSON(fusion.v11-2026.05.25-25src)으로 융합 응답한다(p50 180ms). "
        "위험 발화 시 햅틱 3-burst + 음성 안내 + 반경 200m V2V broadcast가 동시 트리거된다.")

    add_sub_title(doc, "2. 공공데이터 보유기관 및 확보방안 (주관기관 융합 가점)")
    add_table(doc, [
        ["구분", "보유기관 — 데이터", "AuraView 활용 / 가중치"],
        ["주관기관", "한국도로공사 — VDS · 돌발 · 노면 RWIS · 도로 노후도", "교통량 비대칭 · 노면 frost +0.35 · 노후 +0.10"],
        ["주관기관", "한국교통안전공단 — KOTSA 검사 · DTG · V2X 자율주행 허브", "구별 부적합 prior · 사업용 위험운전 +0.10"],
        ["국내공공", "도로교통공단 — 신호 위상 · TAAS 사고이력 · 보행자 다발 · 통학로", "신호 occlusion +0.55 · 보행자 prior +0.30"],
        ["국내공공", "국토교통부 — ITS 표준링크 · DSZ 안심구역 · 스쿨존/횡단보도 GIS", "k≥5 가명결합 · 스쿨존 +0.62 (등하교)"],
        ["국내공공", "기상청·환경부 — KMA 동네예보 · 결빙 · PM10·PM2.5 · EV 충전소", "우천 +0.18 · 블랙아이스 +0.32 · 시정 +0.06"],
        ["국내공공", "소방청·보건복지부 — 119 출동 · E-Gen 응급실 가용병상", "골든타임 라우팅 · 심각도 ×1.34"],
        ["국내공공", "경찰청·행안부·서울시 — 단속 CCTV · 도로 노후도 · 따릉이", "단속 prior +0.04 · 자전거 prior +0.22"],
        ["보조(no-key)", "USGS 지진 · OSM 철도건널목", "터널/교량 +0.02 · 건널목 +0.03~0.10"],
    ])
    add_body(doc,
        "공공데이터포털 인증키 즉시 발급 + no-key fallback 12종으로 cold-start 즉시 동작. "
        "가명결합은 HMAC-SHA256 + k≥5(개인정보보호법 28조의2), DSZ는 반입→결합→반출 SHA-256 검증(국토부 훈령 1456호).")

    add_sub_title(doc, "3. 기존 솔루션 대비 한국 특화 차별점 5종")
    add_body(doc,
        "① V2V 협업 인지(heading 130°+ Cross-Vehicle 가중 0.95) — Tesla는 자기 시점만. "
        "② Bus-Aware(정류장 dwelling 보행자 +0.55). "
        "③ Bidirectional Lane(마주오는 차로 + VDS 비대칭). "
        "④ 공공 신호 API 결합(vision-only 아닌 도로교통공단 신호 API + ITS 직접). "
        "⑤ 정책 환원(위험 교차로 Top-N 자동 리포트 + DSZ 가명결합).")

    add_sub_title(doc, "4. 경쟁력 및 UI/UX")
    add_body(doc,
        "데이터 깊이: 한국 공공 인프라 25종 + 사용자 fleet 결합 cold-start 우위. "
        "법적 적합성: 8 시나리오를 도로교통법 + 대법원 판례(예: 우회전 2022도10752)에 매핑. "
        "검증 투명성: MIT GitHub 공개 + 119/119 pytest PASS + 단일 URL /impact/submission-ready 호출 시 9 게이트 자가 진단(현재 ready=true). "
        "UI/UX: 상단 카메라 + ML Kit 검출 cyan bbox 오버레이, 하단 위험점수 게이지 + 4축 라이브 인디케이터, 발화 시 햅틱·음성·V2V 동시 트리거, 운영자 대시보드는 위험 교차로 히트맵 + 3-page A4 정책 PDF 자동 생성.")

    # ── □ 아이템의 실효성 ──
    add_section_title(doc, "□ 아이템의 실효성")
    add_body(doc,
        "핵심 고객은 B2C 일반 운전자(국내 블랙박스 1,500만 대), B2B 영업용 운수업체(사업용 50만 대, DTG 의무), B2G 지자체·국토부(17 시도 + 226 시군구)이다. "
        "국내 ADAS·블랙박스 시장은 연 1.2조원으로 7.2% 성장 중(한국자동차연구원 2024), V2X 시장은 2030년 3,800억원 예상이다. "
        "운전자는 회피 성공률 25%→84.5%, 운수업체는 DTG 패턴 식별로 사고율 30% 감소, 지자체는 신호 주기 조정 의사결정 데이터를 확보한다.")
    add_body(doc,
        "수익 모델: B2C Free + Premium 월 4,900원, B2B SaaS 차량당 월 9,900원(50만대×10%=연 59억), B2G 정책 리포트 연 2,000만원(226시군구×30%=연 13.5억). "
        "3년 매출 추정 1년차 5억 / 2년차 20억 / 3년차 70억, BEP 2년차 후반. "
        "확장 계획: ①마이데이터 결합(보험사·정비소) ②자율주행 V2X 데이터셋(국토부 av-hub 기여) ③해외 진출(일본·태국·베트남, 한국형 도로 환경).")

    # ── □ 기대효과 ──
    add_section_title(doc, "□ 기대효과")
    add_body(doc,
        "산출 공식: TAAS_annual × 도시교차로 비중(46%) × 시나리오 비중(42%) × min(0.85, 0.25 × lead) × coverage. "
        "lead = 3.38s 기준 도입 단계별 정량 임팩트는 다음과 같다(사회비용은 KOTI 2024 단가표 환산).")
    add_table(doc, [
        ["도입 비율", "사고 예방/년", "사망 감소", "부상 감소", "사회비용 절감"],
        ["Pilot 5%", "1,694 건", "21 명", "2,370 명", "약 2,800억원"],
        ["확산 25%", "8,470 건", "105 명", "11,852 명", "약 1조 4,000억원"],
        ["전국 100%", "33,880 건", "421 명", "47,408 명", "약 5조 6,000억원"],
    ])
    add_body(doc,
        "서울 위험 교차로 Top-10(강남역 11.8 / 잠실역 10.1 / 광화문 9.3 / 신촌 8.4 / 영등포 7.2…)만 우선 도입해도 연 사망·중상 85명 예방 가능하다. "
        "일반 운전자는 민식이법·우회전 강화 부담 하에서 객관적 회피 데이터로 형사 위험을 줄이고, 보행 약자(어린이·고령자)는 스쿨존 V2V 알림으로 보호된다(보행자 사망 전체 38%). "
        "운수 종사자는 졸음·과속 사전 차단으로 보험료·배상금 절감 효과를 얻는다.")

    # ── □ 기 타 ──
    add_section_title(doc, "□ 기 타")
    add_body(doc,
        "라이브 검증 URL(호출 시 즉시 응답): /impact/submission-ready(9 게이트 자가 진단, 현재 ready=true), /metrics/audit(시스템 헬스 + tests 119/119), /impact/proposal-pdf(호출 시점 git_sha 반영 3-page PDF), /fusion/sources(25 소스 freshness), /impact/top-intersections(위험 교차로 Top-N), GitHub(MIT) https://github.com/leelang7/AuraView.")
    add_body(doc,
        "법적 컴플라이언스: MIT License · 공공데이터 각 출처 약관(CC-BY-3.0 호환) · PII 자동 블러(개인정보보호법 3조) · 가명결합 k≥5(28조의2) · DSZ SHA-256 감사 로그(국토부 훈령 1456호). "
        "사업 역량: 119/119 자동 테스트, GitHub Actions CI/CD, 149+ API 엔드포인트, 라이브 서비스 24/7(Render 배포 + Docker 한 줄 가동), 모델 가중치·학습 메트릭 published. "
        "개인 개발 → MIT 오픈소스 사회 환원 + B2B/B2G 수익 모델로 사업화. DSZ 결합 결과를 정책 보고서가 아닌 실시간 차량 알림으로 전달하는 첫 사례 구축이 본 아이템의 의의이다.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"[OK] {OUT}")
    print(f"     {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    build()
