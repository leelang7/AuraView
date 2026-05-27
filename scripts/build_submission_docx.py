"""2026 국토교통 데이터활용 경진대회 제품/서비스 개발 기획서 docx 생성.

사용:
    python scripts/build_submission_docx.py
    → docs/제출용_제품서비스_개발기획서.docx

hwp 양식 (Downloads/경진대회_참가서류/2026경진대회_기획서(최종).hwp) 의 구조를
서술형 본문 + 표 + 보조 bullet 로 작성. 3장 분량 엄수.
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


def set_korean_font(run, size=10, bold=False, color=None):
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


def add_paragraph(doc, text, size=10, bold=False, indent_cm=0, before=0, after=2, align=None, color=None):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(indent_cm)
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = 1.4
    if align:
        p.alignment = align
    r = p.add_run(text)
    set_korean_font(r, size=size, bold=bold, color=color)
    return p


def add_body(doc, text):
    """본문 서술형 단락 — 줄간격 1.4, 양쪽 정렬, 들여쓰기 1칸."""
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.5)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.4
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    r = p.add_run(text)
    set_korean_font(r, size=10)
    return p


def add_section_title(doc, text, top_space=14):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(top_space)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    set_korean_font(r, size=13, bold=True)
    return p


def add_sub_title(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.left_indent = Cm(0.3)
    r = p.add_run(text)
    set_korean_font(r, size=11, bold=True, color=(0x1F, 0x49, 0x7D))
    return p


def add_table(doc, rows, header_shading="DBE5F1", body_shading=None, col_widths=None):
    """rows[0] = 헤더, 이후 = body."""
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    table.autofit = True
    for ri, row in enumerate(rows):
        for ci, cell_text in enumerate(row):
            cell = table.rows[ri].cells[ci]
            if ri == 0:
                set_cell_shading(cell, header_shading)
            elif body_shading and ri % 2 == 0:
                set_cell_shading(cell, body_shading)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(cell_text)
            set_korean_font(r, size=9, bold=(ri == 0))
    if col_widths:
        for ci, w in enumerate(col_widths):
            for row in table.rows:
                row.cells[ci].width = Cm(w)
    return table


def add_bullet(doc, text, level=0):
    p = doc.add_paragraph()
    if level == 0:
        p.paragraph_format.left_indent = Cm(0.5)
        marker = "o  "
    else:
        p.paragraph_format.left_indent = Cm(1.3)
        marker = "-  "
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.line_spacing = 1.3
    r = p.add_run(f"{marker}{text}")
    set_korean_font(r, size=10)


def build():
    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2)
        section.right_margin = Cm(2)

    # ── 표지 ────────────────────────────────────────────────
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run("「2026년 국토·교통 데이터 활용 경진대회」")
    set_korean_font(r, size=15, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run("제품/서비스 개발 기획서")
    set_korean_font(r, size=15, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = p.add_run("* 작성분량 : 최대 3장(별첨 제외, 분량 엄수)")
    set_korean_font(r, size=9, color=(0x80, 0x80, 0x80))

    # ── 가점 자가체크 표 ────────────────────────────────────
    tbl = doc.add_table(rows=2, cols=2)
    tbl.style = "Table Grid"
    c00 = tbl.rows[0].cells[0]; c10 = tbl.rows[1].cells[0]; c00.merge(c10)
    set_cell_shading(c00, "E7E6E6")
    pp = c00.paragraphs[0]; pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rr = pp.add_run("가점 자가체크\n(심사 후 반영)")
    set_korean_font(rr, size=10, bold=True)
    pp = tbl.rows[0].cells[1].paragraphs[0]
    rr = pp.add_run("☑ 가명정보 결합   ☑ 주관기관 융합데이터   ☑ 안심구역 활용   ☑ AI 활용  (☑ AI 학습도구, ☑ AI 분석도구)")
    set_korean_font(rr, size=10, bold=True)
    pp = tbl.rows[1].cells[1].paragraphs[0]
    rr = pp.add_run("ex) 한국도로공사 VDS·돌발 + 한국교통안전공단 DTG·V2X 융합")
    set_korean_font(rr, size=9); rr.italic = True

    add_paragraph(doc, "※ AI 학습도구: PyTorch Transformer (Risk Transformer · AUC 0.9403 · 10,000 train · 15 epoch · 가중치 published)", size=8, indent_cm=0.3, before=4, color=(0x60, 0x60, 0x60))
    add_paragraph(doc, "※ AI 분석도구: Google ML Kit ObjectDetector · ImageLabeler (단말 on-device 객체 검출 + 400+ 카테고리 라벨)", size=8, indent_cm=0.3, color=(0x60, 0x60, 0x60))
    add_paragraph(doc, "※ 증빙: models/risk_transformer_trained_metric.json · https://auraview.allthatai.kr/ai/model-card", size=8, indent_cm=0.3, after=6, color=(0x60, 0x60, 0x60))

    # ── □ 아이템명 ────────────────────────────────────────
    add_section_title(doc, "□ 아이템명", top_space=10)
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.3)
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run("AuraView K-Perception")
    set_korean_font(r, size=13, bold=True, color=(0x00, 0x66, 0xCC))
    r = p.add_run("  ─  ")
    set_korean_font(r, size=11)
    r = p.add_run("25종 공공데이터 융합 + V2V 협업 인지 기반 한국 도로 안전 AI 블랙박스 플랫폼")
    set_korean_font(r, size=11, bold=True)

    # ── □ 제안배경 ────────────────────────────────────────
    add_section_title(doc, "□ 제안배경")

    add_sub_title(doc, "1. 한국 도로의 인명 피해 현황과 일반 ADAS 의 구조적 한계")
    add_body(doc,
        "도로교통공단 TAAS 2024 통계에 따르면 우리나라 도로에서 발생한 교통사고로 연간 2,581명이 사망하고 290,400명이 부상을 입었다. "
        "이 가운데 도시 교차로에서 발생한 사고가 전체의 46%를 차지하며, 트럭·버스·대형 SUV에 시야가 가려진 상태에서 신호등이나 보행자를 인지하지 못해 발생한 occlusion 유형 사고가 약 22%에 달한다. "
        "기존 차량용 ADAS 시스템은 카메라 한 대의 직접 시야에만 의존하기 때문에, 가려진 영역의 객체를 사전에 감지할 수 없으며, 평균 선행경고 시간이 0.5~1초에 불과하여 시속 60km 주행 시 회피 가능 거리가 8~16m 수준에 그친다. "
        "결과적으로 회피 성공률은 25% 미만으로 추정되고, 사각지대 사고는 매년 반복되고 있다.")

    add_sub_title(doc, "2. 해외 솔루션의 한국 특수 환경 미반영")
    add_body(doc,
        "Tesla FSD, Mobileye 등 글로벌 ADAS 솔루션은 자기 차량의 단일 시점에서만 객체 인식과 위험 추정을 수행하며, 한국 도로 특유의 8대 위험 시나리오 — "
        "트럭에 가려진 신호등, 좌측 사각지대 이륜차, 우회전 시 횡단보도 보행자, 어린이보호구역, 자전거도로 진입, 야간 무인등화, 신호등 가림, 우천 시 교차로 — 에 대한 prior 데이터를 가지고 있지 않다. "
        "특히 2022년 시행된 우회전 일시정지 의무화(도로교통법 25조 4항)와 민식이법(12조) 강화 이후 한국 운전자의 형사 책임 부담이 크게 증가하였으나, 이를 사전에 회피할 수 있도록 지원하는 객관적 데이터 기반 솔루션은 부재한 실정이다.")

    add_sub_title(doc, "3. 국토교통부·공공기관 보유 데이터의 사회 환원 부족")
    add_body(doc,
        "한국도로공사의 VDS 실시간 소통·돌발상황·노면 정보, 도로교통공단의 신호 위상·TAAS 사고이력, 한국교통안전공단의 DTG 운행기록·V2X 자율주행 허브, 국토교통부의 데이터안심구역(DSZ) 가명결합 결과 등 "
        "약 25종의 공공 인프라 데이터가 이미 구축되어 있음에도, 이들이 정책 보고서나 통계 자료의 형태로만 머물고 일반 운전자가 실시간으로 활용할 수 있는 형태로 환원되지 않고 있다. "
        "본 아이템은 이 25종 공공데이터를 단일 응답으로 융합한 후 V2V 협업 인지를 결합하여, 평균 3.38초의 선행경고를 제공함으로써 회피 성공률을 84.5%까지 끌어올리는 것을 목표로 한다.")

    # ── □ 세부내용 ────────────────────────────────────────
    add_section_title(doc, "□ 세부내용")

    add_sub_title(doc, "1. 시스템 개요 및 구현 아키텍처")
    add_body(doc,
        "AuraView K-Perception 은 일반 스마트폰 또는 블랙박스의 후면 카메라 한 대만으로 동작하는 경량 솔루션이며, 특수 하드웨어를 요구하지 않는다(Galaxy Z Fold 3 기준 검증 완료). "
        "단말은 카메라 frame 을 Google ML Kit ObjectDetector 와 자체 학습 Risk Transformer 모델에 동시 입력하여 객체 검출과 위험 점수를 산출하고, "
        "동시에 서버는 25종 공공데이터를 실시간으로 호출해 단일 JSON 응답(`fusion.v11-2026.05.25-25src`)으로 융합한 후 단말로 전송한다. "
        "위험 발화 시에는 햅틱 3-burst 진동, 음성 안내, 그리고 반경 200m 내 다른 AuraView 차량으로의 V2V broadcast 가 동시에 트리거된다. "
        "추론 지연은 단말 ML Kit 약 30ms, 서버 Risk Transformer p99 1.04ms, 융합 응답 p50 180ms 수준으로 실시간성을 확보한다.")

    add_sub_title(doc, "2. 필요한 공공데이터 및 보유기관 (주관기관 융합 가점)")
    add_body(doc,
        "본 아이템은 한국도로공사와 한국교통안전공단 등 본 경진대회 주관기관의 핵심 데이터를 다음과 같이 융합한다. 모든 데이터는 공공데이터포털을 통한 인증키 발급 또는 no-key 라이브 fallback 으로 즉시 활용 가능하다.")
    add_table(doc, [
        ["구분", "데이터 / 보유기관", "AuraView 활용"],
        ["주관기관", "한국도로공사 — VDS · 돌발 · 노면 RWIS · 도로 노후도", "교통량 비대칭, 노면 frost +0.35, 노후 포트홀 +0.10"],
        ["주관기관", "한국교통안전공단 — KOTSA 검사 · DTG · V2X 자율주행 허브", "구별 부적합률 prior, 사업용 위험운전 +0.10, V2X RSU"],
        ["국내공공", "도로교통공단 — 신호 위상 · TAAS 사고이력 · 보행자 다발", "신호 occlusion +0.55, 사고이력 prior, 보행자 prior +0.30"],
        ["국내공공", "국토교통부 — ITS 표준링크 · DSZ 안심구역 · vworld GIS", "표준링크 속도, 가명결합 k≥5, 스쿨존/횡단보도 +0.62"],
        ["국내공공", "기상청·환경부 — KMA 동네예보 · 결빙 · PM10/PM2.5", "우천 +0.18, 블랙아이스 +0.32, 시정 +0.06"],
        ["국내공공", "소방청·보건복지부 — 119 출동 · E-Gen 응급실", "골든타임 라우팅, 사고 심각도 ×1.34"],
        ["국내공공", "환경공단 · 행안부 · 경찰청 — EV 충전소 · 도로 노후도 · 단속 CCTV", "EV 정차 패턴, 노후 +0.10, 단속 밀집 +0.04"],
        ["국내공공", "서울시 — 따릉이 실시간", "자전거도로 prior +0.22"],
        ["보조(no-key)", "USGS 지진 · OSM 철도건널목", "터널/교량 prior +0.02, 건널목 +0.03~0.10"],
    ])

    add_sub_title(doc, "3. AI 학습 및 분석 도구 활용 (AI 활용 가점)")
    add_body(doc,
        "AI 학습도구로는 PyTorch 기반 Transformer 모델인 Risk Transformer 를 자체 학습하였다. 21개 융합 피처를 입력으로 받아 0~1 범위의 위험 점수를 출력하며, "
        "10,000개 학습 샘플과 15 epoch 학습 후 AUC 0.9403, F1 0.9412, Precision 0.9441, Recall 0.9384 의 성능을 달성했다. "
        "모델 크기는 67,970 파라미터 / 278KB로 단말 임베드 가능 수준이며, CPU 단일 코어 추론 지연 p99 는 1.04ms 다. "
        "AI 분석도구로는 Google ML Kit ObjectDetector (단말 on-device YOLO 계열 객체 검출)와 ImageLabeler (400+ 카테고리 라벨링)를 활용하여 "
        "카메라 frame 에서 보행자·차량·이륜차·자전거 등의 후보 객체를 추출하고, Risk Transformer 의 위험 추정 입력으로 결합한다.")

    add_sub_title(doc, "4. 기존 유사 제품과의 차별점 — 한국 특화 5종")
    add_table(doc, [
        ["카테고리", "Tesla FSD / 글로벌 솔루션", "AuraView K-Perception"],
        ["차량 간 협업", "자기 차량 시점만 활용", "V2V Cross-Vehicle (heading 130°+ 가중 0.95)"],
        ["정류장 prior", "보행자 일반 분류만", "Bus-Aware 정류장 dwelling/passing → +0.55 boost"],
        ["마주오는 차로", "단방향 차로 모델", "Bidirectional Lane + VDS 비대칭 분석"],
        ["공공 신호 결합", "vision-only 신호 인식", "도로교통공단 신호 API + ITS 직접 호출 결합"],
        ["정책 환원", "Tesla 내부 데이터 폐쇄", "위험 교차로 Top-N 자동 리포트 + DSZ 가명결합"],
    ])

    add_sub_title(doc, "5. 개발 제품만의 경쟁력 확보 방안")
    add_body(doc,
        "첫째, 데이터 깊이 측면에서 글로벌 솔루션이 자체 fleet 학습에만 의존하는 반면 AuraView 는 한국 공공 인프라 25종에 사용자 fleet 를 결합하여 cold-start 시점부터 우위를 확보한다. "
        "둘째, 법적 적합성 측면에서 8 시나리오 각각을 도로교통법 조항과 대법원 판례(예: 2022도10752 우회전 보행자 사건)에 매핑하여(`/policy/laws`), 정책 의사결정자와 보험사가 즉시 신뢰할 수 있는 형태로 제공한다. "
        "셋째, 검증 투명성 측면에서 코드 전체를 MIT 라이센스로 GitHub 공개하고 119개 자동화 테스트를 매 커밋마다 실행하며, 단일 URL `/impact/submission-ready` 호출로 9개 게이트(소스 카운트·스키마·PDF 생성·모델 가중치·git_sha·LICENSE·외부 노출 금지어 등)를 자가 진단한다. "
        "넷째, DSZ 안심구역 활용을 완전 자동화하여 반입→결합→반출 전 과정에 SHA-256 해시 검증과 감사 로그를 자동 생성한다(`/dsz/pipeline-report`).")

    add_sub_title(doc, "6. UI/UX 서비스 예상 이미지")
    add_body(doc,
        "화면 상단 절반에는 실시간 카메라 frame 위에 검출된 객체를 cyan 색 bounding box 오버레이로 표시한다. 박스 좌상단에는 ML Kit 가 반환한 원본 라벨과 confidence 가 함께 노출된다. "
        "화면 하단 절반에는 4축 라이브 인디케이터(entropy · motion · voxel 점유율 · 검출 카운트)와 위험 점수 게이지가 배치된다. "
        "위험 발화 시 햅틱 3-burst 진동과 함께 음성 안내(예: \"전방 신호 가림, 즉시 정지\")가 출력되고, V2V 토글이 활성화되어 있으면 반경 200m 내 다른 AuraView 차량으로 위험 알림이 broadcast 된다. "
        "지자체용 운영자 대시보드에는 위험 교차로 Top-N 히트맵과 함께 정책 의사결정용 3-page A4 PDF 가 자동 생성되어 다운로드 가능하다.")

    # ── □ 아이템의 실효성 ────────────────────────────────────
    add_section_title(doc, "□ 아이템의 실효성")

    add_sub_title(doc, "1. 핵심 고객과 국내외 시장 규모")
    add_body(doc,
        "본 아이템은 B2C(일반 운전자), B2B(영업용 운수업체), B2G(지자체·국토부) 3개 segment 를 핵심 고객으로 한다. "
        "국내 블랙박스 보급 대수는 약 1,500만 대로 보급률 90% 이상이며, DTG 의무 장착 대상인 사업용 차량은 약 50만 대(택시·버스·화물)에 달한다. "
        "행정 단위로는 17개 광역 시·도와 226개 시·군·구가 정책 의사결정 단위로 존재한다. "
        "시장 규모는 한국자동차연구원 2024 보고서 기준 국내 ADAS·블랙박스 시장이 연 약 1.2조원이며 연평균 7.2% 성장 중이고, "
        "정부 미래차 산업육성 계획에 따른 국내 V2X 시장은 2030년 3,800억원 규모로 예상된다. "
        "해외 잠재 시장은 동남아시아·인도 등 한국형 도로 인프라(좁은 골목, 이륜차 비중, 보행자 밀집)와 유사한 신흥 시장이다.")

    add_sub_title(doc, "2. 고객 편의 효과 및 사고 회피 정량 효과")
    add_body(doc,
        "운전자는 평균 3.38초의 선행경고를 받음으로써 회피 가능 거리가 일반 ADAS 대비 약 4배 확장되어, 회피 성공률이 25%에서 84.5%로 향상된다. "
        "영업용 운수업체는 DTG 위험운전 패턴 자동 식별을 통해 사고율을 평균 30% 감소시킬 수 있으며(KOTSA DTG 통계 가정), "
        "지자체는 위험 교차로 정량 데이터를 확보하여 신호 주기 조정·CCTV 우선 설치 등의 정책 결정에 즉시 활용 가능하다.")

    add_sub_title(doc, "3. 매출 가능성 및 수익구조")
    add_table(doc, [
        ["고객", "수익 모델", "단가", "보급 시나리오", "연 매출"],
        ["B2C 일반 운전자", "Free + Premium", "월 4,900원", "프리미엄 5만 명 전환", "약 30억원"],
        ["B2B 영업용 운수", "차량당 SaaS", "월 9,900원", "50만대 × 10% 보급", "약 59억원"],
        ["B2G 지자체", "정책 리포트 라이센스", "연 2,000만원", "226 시군구 × 30%", "약 13.5억원"],
    ])
    add_body(doc,
        "B2C 무료 사용자는 익명 위험 이벤트 데이터를 기여하여 fleet learning 의 cold-start 를 가속하며(Tesla shadow mode 모델), 프리미엄 사용자에게는 V2V 광역 알림과 HUD 미러링 기능을 제공한다. "
        "3년 매출 추정은 1년차 5억원, 2년차 20억원, 3년차 70억원 수준이며, 손익분기점은 2년차 후반으로 예상한다.")

    add_sub_title(doc, "4. 서비스의 확장 계획")
    add_body(doc,
        "1단계로 마이데이터 결합을 통해 사용자 동의 기반 운전 행태 데이터를 보험사(보험료 할인)와 정비소(차량 진단)로 연동한다. "
        "2단계로 자율주행 V2X 데이터셋 확장을 위해 익명 충돌 직전 frame 을 국토부 자율주행 데이터허브(av-hub)에 기여하여 자율주행 학습 데이터 부족 문제 해결에 기여한다. "
        "3단계로는 일본·태국·베트남 등 한국과 유사한 도시 도로 환경을 가진 국가로 진출하며, 현지 공공데이터 어댑터만 교체하면 핵심 융합 엔진은 그대로 재사용 가능하다.")

    # ── □ 기대효과 ────────────────────────────────────────
    add_section_title(doc, "□ 기대효과")

    add_sub_title(doc, "1. 정량 사회 임팩트 (TAAS 2024 baseline · lead = 3.38s)")
    add_body(doc,
        "본 아이템이 실현될 경우 사회적·경제적 이득은 도입 비율에 따라 다음과 같이 산출된다. "
        "산출 공식은 TAAS 연간 사고 통계에 도시 교차로 비중(46%), 본 시스템 적용 시나리오 비중(42%), "
        "lead time 기반 회피율(min(0.85, 0.25 × lead))을 곱한 것이며, KOTI 사회비용 단가표 기준 환산이다.")
    add_table(doc, [
        ["도입 비율", "사고 예방/년", "사망 감소", "부상 감소", "사회비용 절감"],
        ["Pilot 5%", "1,694 건", "21 명", "2,370 명", "약 2,800억원"],
        ["확산 25%", "8,470 건", "105 명", "11,852 명", "약 1조 4,000억원"],
        ["전국 100%", "33,880 건", "421 명", "47,408 명", "약 5조 6,000억원"],
    ])

    add_sub_title(doc, "2. 우선순위 도입 시 단기 효과")
    add_body(doc,
        "전국 도입을 기다리지 않더라도, TAAS 사고 다발 분석에 기반한 서울 위험 교차로 Top-10 (강남역 11.8 / 잠실역 10.1 / 광화문 9.3 / 신촌 8.4 / 영등포 7.2 / ...) 에 우선 도입할 경우, "
        "해당 10개 교차로만으로도 연 사망·중상 약 85명을 예방할 수 있다. 라이브 데이터는 `https://auraview.allthatai.kr/impact/top-intersections` 에서 즉시 검증 가능하다.")

    add_sub_title(doc, "3. 일반 국민에게 미치는 영향")
    add_body(doc,
        "일반 운전자는 민식이법과 우회전 보행자 의무 일시정지 강화로 인한 형사 책임 부담이 증가한 상황에서, AuraView 의 객관적 회피 데이터를 통해 사전 회피 의사결정과 사후 입증 자료를 동시에 확보할 수 있다. "
        "보행 약자(어린이·고령자)는 스쿨존·실버존·횡단보도 진입 차량에 대한 자동 V2V 알림으로 보호받으며, 보행자 사망률(전체 교통사고 사망의 38%) 감소에 기여한다. "
        "영업용 운수 종사자는 DTG 위험운전 패턴 자동 알림으로 졸음·과속을 사전에 차단하며, 사업자 입장에서는 사고율 감소를 통한 보험료·배상금 절감 효과를 얻는다.")

    # ── □ 기 타 ────────────────────────────────────────
    add_section_title(doc, "□ 기 타")

    add_sub_title(doc, "1. 검증 자산 — 외부 평가자가 즉시 확인 가능한 라이브 URL")
    add_body(doc,
        "본 아이템의 모든 헤드라인 숫자(25 sources, 119 tests, AUC 0.9403, 사고예방 1,694건 등)는 라이브 시스템에서 호출 시점 기준으로 자동 검증 가능하다. 외부 평가자는 다음 URL 들을 즉시 클릭하여 사실을 확인할 수 있다.")
    add_bullet(doc, "자가 진단 단일 URL (9 게이트, ready=true/9/9 PASS): https://auraview.allthatai.kr/impact/submission-ready", 0)
    add_bullet(doc, "라이브 시스템 헬스 (데이터 소스·이벤트·25점 게이트): https://auraview.allthatai.kr/metrics/audit", 0)
    add_bullet(doc, "즉석 기획서 PDF 자동 생성 (호출 시점 git_sha 반영, 3-page A4): https://auraview.allthatai.kr/impact/proposal-pdf", 0)
    add_bullet(doc, "25 소스 카탈로그 (mode: live/stub, age_s 노출): https://auraview.allthatai.kr/fusion/sources", 0)
    add_bullet(doc, "위험 교차로 Top-N 정량 분석: https://auraview.allthatai.kr/impact/top-intersections", 0)
    add_bullet(doc, "GitHub 저장소 (MIT 오픈소스, 119 자동화 테스트): https://github.com/leelang7/AuraView", 0)

    add_sub_title(doc, "2. 법적 컴플라이언스")
    add_body(doc,
        "본 아이템은 다음과 같은 법령과 절차를 준수한다. "
        "코드는 MIT License 로 공개되며, 활용하는 공공데이터는 각 출처의 약관(대부분 CC-BY-3.0 호환)을 준수한다. "
        "개인정보 측면에서는 얼굴과 차량 번호판을 단말 외부 송출 전에 자동 블러 처리하며(개인정보보호법 3조), "
        "가명결합 시 k≥5 익명성 기준을 적용한다(개인정보보호법 28조의2 가명정보 처리 특례). "
        "데이터안심구역(DSZ) 활용은 국토교통부 훈령 1456호 절차를 준수하여 반입→결합→반출 전 과정에 SHA-256 해시 검증과 감사 로그를 자동 생성한다.")

    add_sub_title(doc, "3. 전문성 및 사업역량, 창업의지")
    add_body(doc,
        "본 프로젝트는 개인 개발자가 GitHub 오픈소스로 출발하여 백엔드 149+ 엔드포인트와 119개 자동화 테스트를 갖춘 라이브 서비스(https://auraview.allthatai.kr)를 24/7 운영하고 있다. "
        "CI/CD 는 GitHub Actions 로 자동화되어 매 커밋마다 Python 백엔드와 Flutter 모바일 앱을 모두 검증한다. "
        "AI 학습 증빙은 `models/risk_transformer_trained_metric.json` 으로 가중치와 학습 로그가 공개되어 있다. "
        "사업화 측면에서는 MIT 오픈소스로 사회 환원하는 동시에 B2B SaaS와 B2G 정책 리포트 라이센스로 수익 모델을 추진한다. "
        "본 아이템은 한국 공공데이터의 사회 환원 모범 사례 — 데이터안심구역 결합 결과를 정책 보고서가 아닌 실시간 차량 알림으로 전달하는 첫 사례 — 를 구축하는 데 그 의의가 있다.")

    # ── 별첨 안내 (분량 외) ────────────────────────────────
    add_paragraph(doc, "── 별첨 (분량 외) ──", size=9, bold=True, before=14, after=2)
    for line in [
        "• GitHub README · LICENSE · CHANGELOG",
        "• 25 sources 카탈로그 JSON (`/fusion/sources` 응답)",
        "• Risk Transformer 학습 메트릭 (`models/risk_transformer_trained_metric.json`)",
        "• 도로교통법 8 시나리오 매핑 (`/policy/laws`)",
        "• Native APK v12.170 (`auraview_fleet/build/app/outputs/flutter-apk/app-release.apk` · 56MB)",
    ]:
        add_paragraph(doc, line, size=9, indent_cm=0.5, after=0)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"[OK] {OUT}")
    print(f"     {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    build()
