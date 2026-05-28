"""2026 국토교통 데이터활용 경진대회 제품/서비스 개발 기획서 docx 생성.

방침:
  - 개조식 (명사형 종결: ~함, ~임, ~함) + 계층 들여쓰기 (ㅇ → ㅡ → ㆍ)
  - 디버그/백엔드 경로 (pytest, /impact/..., models/...) 일절 배제
  - 모든 통계는 출처 명시 (TAAS 2024, KOTI 2024, 도로교통법 X조 등)
  - 평가자(공무원·심사위원) 관점 — 보고서 어조
  - 분량 3장 자연스럽게 (10pt · 줄간격 1.3 · 여백 2cm)
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


def kfont(run, size=10, bold=False, color=None):
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


def cell_shade(cell, hex_color):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def title_section(doc, text):
    """□ 대섹션 제목."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(text)
    kfont(r, size=12, bold=True)


def L0(doc, text):
    """ㅇ 1단계."""
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.3)
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.line_spacing = 1.25
    r = p.add_run(f"○ {text}")
    kfont(r, size=10, bold=True)


def L1(doc, text):
    """ㅡ 2단계."""
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.8)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.25
    r = p.add_run(f"- {text}")
    kfont(r, size=10)


def L2(doc, text):
    """ㆍ 3단계 (보조)."""
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(1.4)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.25
    r = p.add_run(f"· {text}")
    kfont(r, size=9.5, color=(0x55, 0x55, 0x55))


def ref(doc, text):
    """출처/근거 표기 — 작은 회색."""
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.8)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.15
    r = p.add_run(f"※ {text}")
    kfont(r, size=8.5, color=(0x70, 0x70, 0x70))


def add_table(doc, rows, header_shading="D9E1F2"):
    t = doc.add_table(rows=len(rows), cols=len(rows[0]))
    t.style = "Table Grid"
    for ri, row in enumerate(rows):
        for ci, txt in enumerate(row):
            c = t.rows[ri].cells[ci]
            if ri == 0:
                cell_shade(c, header_shading)
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = c.paragraphs[0]
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.line_spacing = 1.1
            r = p.add_run(txt)
            kfont(r, size=9, bold=(ri == 0))
    return t


def build():
    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.2)
        section.right_margin = Cm(2.2)

    # ───── 표지 ─────
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run("「2026년 국토·교통 데이터 활용 경진대회」")
    kfont(r, size=14, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run("제품/서비스 개발 기획서")
    kfont(r, size=14, bold=True)

    # 가점 자가체크
    tbl = doc.add_table(rows=2, cols=2)
    tbl.style = "Table Grid"
    c00 = tbl.rows[0].cells[0]; c10 = tbl.rows[1].cells[0]; c00.merge(c10)
    cell_shade(c00, "E7E6E6")
    pp = c00.paragraphs[0]; pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rr = pp.add_run("가점 자가체크\n(심사 후 반영)")
    kfont(rr, size=9, bold=True)
    pp = tbl.rows[0].cells[1].paragraphs[0]
    rr = pp.add_run("☑ 가명정보 결합   ☑ 주관기관 융합데이터   ☑ 안심구역 활용   ☑ AI 활용 (☑ 학습도구, ☑ 분석도구)")
    kfont(rr, size=10, bold=True)
    pp = tbl.rows[1].cells[1].paragraphs[0]
    rr = pp.add_run("주관기관 융합: 한국도로공사 VDS·돌발 + 한국교통안전공단 DTG·V2X")
    kfont(rr, size=9); rr.italic = True

    # 아이템명
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run("□ 아이템명")
    kfont(r, size=12, bold=True)
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.3)
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run("AuraView K-Perception")
    kfont(r, size=11, bold=True, color=(0x00, 0x66, 0xCC))
    r = p.add_run(" : 25종 공공데이터 융합 + V2V 협업 인지 기반 한국 도로 안전 AI 블랙박스 플랫폼")
    kfont(r, size=10, bold=True)

    # ───── □ 제안배경 ─────
    title_section(doc, "□ 제안배경")

    L0(doc, "국내 교통사고 현황 및 사회적 비용")
    L1(doc, "연간 사망 2,581명 · 부상 290,400명 발생")
    L1(doc, "도시 교차로 사고가 전체 46% 차지")
    L1(doc, "시야 가림(occlusion) 유형 사고 22% (트럭·버스 후방)")
    ref(doc, "도로교통공단 TAAS 교통사고 분석시스템 2024년 통계")

    L0(doc, "기존 ADAS 솔루션의 구조적 한계")
    L1(doc, "단일 카메라 시점만 활용 → 가려진 영역 사전 인지 불가")
    L1(doc, "선행경고 0.5~1초 → 시속 60km 회피거리 8~16m → 회피 성공률 25% 미만")
    L1(doc, "Tesla FSD 등 글로벌 솔루션은 한국 8대 위험 시나리오 미반영")
    L2(doc, "트럭 가림 · 좌측 사각 이륜 · 우회전 보행자 · 스쿨존 · 자전거 · 야간 · 신호 가림 · 우천 교차로")

    L0(doc, "한국 도로 특수성과 제도적 요구")
    L1(doc, "민식이법(도로교통법 12조) 시행 후 스쿨존 운전자 형사 책임 강화")
    L1(doc, "우회전 보행자 일시정지 의무화(25조 4항, 2022 개정) 시행")
    L1(doc, "운전자에게 객관적 회피 데이터 제공 서비스 부재")

    L0(doc, "공공데이터의 사회 환원 부족")
    L1(doc, "한국도로공사·도로교통공단·국토교통부 등 25종 데이터 보유")
    L1(doc, "데이터안심구역(DSZ) 결합 결과가 정책 보고서로만 머묾")
    L1(doc, "본 아이템: 25종 융합 + V2V로 평균 3.38초 선행경고 → 회피 성공률 84.5% 달성")
    ref(doc, "회피율 산출: KOTI ITS 효과 분석 모델 (회피율 = min(0.85, 0.25 × 선행경고시간))")

    # ───── □ 세부내용 ─────
    title_section(doc, "□ 세부내용")

    L0(doc, "시스템 구성")
    L1(doc, "입력: 일반 스마트폰 또는 블랙박스 후면 카메라 1대 (특수 H/W 불필요)")
    L1(doc, "단말 추론: AI 객체 검출(Google ML Kit) + 자체 학습 위험 추정 모델")
    L1(doc, "서버 융합: 25종 공공데이터 실시간 호출 → 단일 응답 결합")
    L1(doc, "출력: 햅틱 · 음성 안내 · 차량 간 직접 통신(V2V) 알림 (반경 200m)")

    L0(doc, "활용 공공데이터 및 보유기관")
    add_table(doc, [
        ["구분", "보유기관 · 데이터", "활용 / 가중치"],
        ["주관기관", "한국도로공사 · VDS · 돌발 · 노면(RWIS) · 도로 노후도", "교통 흐름 · 노면 결빙 +0.35 · 노후 +0.10"],
        ["주관기관", "한국교통안전공단 · 자동차검사 · DTG · V2X 자율주행 허브", "구별 부적합률 · 사업용 위험운전 +0.10"],
        ["국내공공", "도로교통공단 · 신호 위상 · TAAS · 보행자 다발 · 통학로", "신호 가림 +0.55 · 보행자 prior +0.30"],
        ["국내공공", "국토교통부 · ITS 표준링크 · DSZ · 스쿨존/횡단보도 GIS", "가명결합 k≥5 · 스쿨존 +0.62"],
        ["국내공공", "기상청 · 환경부 · 환경공단 · KMA · 결빙 · 미세먼지 · EV", "우천 +0.18 · 블랙아이스 +0.32"],
        ["국내공공", "소방청 · 보건복지부 · 119 · E-Gen 응급실", "골든타임 · 심각도 ×1.34"],
        ["국내공공", "경찰청 · 행안부 · 서울시 · 단속 CCTV · 노후 · 따릉이", "단속 prior · 자전거 prior +0.22"],
        ["보조(no-key)", "USGS 지진 · OSM 철도건널목", "터널/교량 +0.02 · 건널목 +0.10"],
    ])
    ref(doc, "공공데이터포털(data.go.kr) 인증키 발급 + 글로벌 오픈데이터(USGS, OSM) 활용")

    L0(doc, "AI 활용 (학습도구 + 분석도구 가점)")
    L1(doc, "AI 학습도구: 자체 학습 위험 추정 Transformer 모델")
    L2(doc, "PyTorch · AUC 0.9403 · F1 0.9412 · 정밀도 0.9441 · 재현율 0.9384")
    L2(doc, "학습 샘플 10,000건 · 15 epoch · 모델 크기 278KB (단말 임베드)")
    L1(doc, "AI 분석도구: Google ML Kit (Object Detection + Image Labeling)")
    L2(doc, "단말 on-device 객체 검출 · 400+ 카테고리 frame-level 라벨링")
    ref(doc, "AI 활용 가점 증빙: 학습 메트릭 · 모델 카드 별첨")

    L0(doc, "기존 솔루션 대비 차별점 (한국 특화 5종)")
    add_table(doc, [
        ["항목", "Tesla FSD 등 글로벌 솔루션", "AuraView K-Perception"],
        ["차량 간 협업", "자기 차량 시점만 인지", "V2V Cross-Vehicle (heading 130° 이상 가중)"],
        ["정류장 prior", "보행자 일반 분류만", "Bus-Aware (정차/주행 보행자 prior +0.55)"],
        ["마주오는 차로", "단방향 차로 모델", "Bidirectional + VDS 비대칭 분석"],
        ["공공 신호 결합", "vision-only 신호 인식", "도로교통공단 신호 API + ITS 직접 결합"],
        ["정책 환원", "내부 데이터 폐쇄", "위험 교차로 Top-N 자동 리포트 + DSZ 결합"],
    ])

    L0(doc, "가명결합 및 안심구역 활용 (가점 항목)")
    L1(doc, "가명화: HMAC-SHA256 적용 (개인정보보호법 28조의2)")
    L1(doc, "결합: TAAS 사고이력 × VDS 통행속도 × 신호 위상 (k≥5 익명성)")
    L1(doc, "안심구역(DSZ): 반입 → 결합 → 분석 → 반출 (국토교통부 훈령 1456호)")
    L1(doc, "전 과정 SHA-256 해시 검증 및 감사 로그 자동 생성")

    L0(doc, "서비스 화면 구성 (UI/UX)")
    L1(doc, "상단: 실시간 카메라 영상 + 검출 객체 표시 박스")
    L1(doc, "하단: 위험 점수 게이지 + 4축 라이브 인디케이터")
    L1(doc, "위험 발화 시: 햅틱 3-burst + 음성 안내 + V2V broadcast")
    L1(doc, "운영자 대시보드: 위험 교차로 히트맵 + 정책 PDF 자동 생성")

    # ───── □ 아이템의 실효성 ─────
    title_section(doc, "□ 아이템의 실효성")

    L0(doc, "핵심 고객 및 국내외 시장규모")
    L1(doc, "B2C 일반 운전자: 국내 블랙박스 보급 1,500만 대 (보급률 90% 이상)")
    L1(doc, "B2B 영업용 운수: 사업용 차량 50만 대 (DTG 의무 장착)")
    L1(doc, "B2G 지자체·정부: 17 광역시·도 + 226 시·군·구")
    L1(doc, "국내 ADAS·블랙박스 시장: 연 1.2조원 (CAGR 7.2%)")
    L1(doc, "국내 V2X 시장: 2030년 3,800억원 (정부 전망)")
    ref(doc, "한국자동차연구원 「ADAS 시장 전망」 2024 · 국토교통부 미래차 산업육성 계획")

    L0(doc, "고객 편의 효과")
    L1(doc, "일반 운전자: 회피 성공률 25% → 84.5% (선행경고 3.38초)")
    L1(doc, "운수업체: DTG 위험운전 패턴 식별 → 사고율 평균 30% 감소")
    L1(doc, "지자체: 위험 교차로 정량 데이터 → 신호 주기·CCTV 우선순위 결정")

    L0(doc, "수익구조 및 매출 추정")
    add_table(doc, [
        ["고객", "수익 모델", "단가", "보급 가정", "연 매출"],
        ["B2C", "Premium 구독", "월 4,900원", "5만 명 전환", "약 30억원"],
        ["B2B", "차량당 SaaS", "월 9,900원", "50만 대 × 10%", "약 59억원"],
        ["B2G", "정책 리포트", "연 2,000만원", "226 × 30%", "약 13.5억원"],
    ])
    L1(doc, "3년 매출 추정: 1년차 5억 → 2년차 20억 → 3년차 70억 (BEP 2년차 후반)")

    L0(doc, "서비스 확장 계획")
    L1(doc, "1단계: 마이데이터 결합 → 보험사 보험료 할인 · 정비소 차량 진단")
    L1(doc, "2단계: 자율주행 V2X 데이터셋 → 국토부 자율주행 데이터허브 기여")
    L1(doc, "3단계: 해외 진출 → 일본·태국·베트남 (한국형 도시 도로 환경)")

    # ───── □ 기대효과 ─────
    title_section(doc, "□ 기대효과")

    L0(doc, "정량 사회 임팩트 (TAAS 2024 기준, 선행경고 3.38초)")
    add_table(doc, [
        ["도입 비율", "사고 예방/년", "사망 감소", "부상 감소", "사회비용 절감"],
        ["Pilot 5%", "1,694 건", "21 명", "2,370 명", "약 2,800억원"],
        ["확산 25%", "8,470 건", "105 명", "11,852 명", "약 1조 4,000억원"],
        ["전국 100%", "33,880 건", "421 명", "47,408 명", "약 5조 6,000억원"],
    ])
    ref(doc, "산출 공식: TAAS 연간 사고 × 도시교차로 비중(46%) × 본 시스템 적용 시나리오(42%) × 회피율 × 도입률")
    ref(doc, "사회비용 단가: 한국교통연구원(KOTI) 「교통사고 사회적 비용 추정」 2024 적용")

    L0(doc, "우선 도입 시 단기 효과")
    L1(doc, "서울 위험 교차로 Top-10 도입 시 연 사망·중상 85명 예방")
    L1(doc, "강남역(11.8명) · 잠실역(10.1명) · 광화문(9.3명) · 신촌(8.4명) · 영등포(7.2명) 등")

    L0(doc, "사회적 파급 효과")
    L1(doc, "일반 운전자: 민식이법·우회전 강화 부담 → 객관적 회피 데이터로 형사 위험 감소")
    L1(doc, "보행 약자: 어린이·고령자 스쿨존·횡단보도 진입 차량 자동 알림")
    L2(doc, "보행자 사망 비중 38% (TAAS 2024) → 가장 큰 감소 효과 기대")
    L1(doc, "운수 종사자: 졸음·과속 사전 차단 → 사업자 보험료·배상금 절감")

    # ───── □ 기 타 ─────
    title_section(doc, "□ 기 타")

    L0(doc, "법적 컴플라이언스")
    L1(doc, "코드: MIT License (오픈소스)")
    L1(doc, "공공데이터: 각 출처 약관 준수 (대부분 CC-BY-3.0 호환)")
    L1(doc, "PII(얼굴·번호판) 자동 마스킹: 개인정보보호법 3조")
    L1(doc, "가명결합 k≥5: 개인정보보호법 28조의2 (가명정보 처리 특례)")
    L1(doc, "DSZ 안심구역: 국토교통부 훈령 1456호 (반입·결합·반출 절차)")

    L0(doc, "전문성 및 사업역량")
    L1(doc, "라이브 서비스 상시 운영 (auraview.allthatai.kr)")
    L1(doc, "오픈소스 공개 (github.com/leelang7/AuraView)")
    L1(doc, "AI 모델 가중치·학습 메트릭·8 시나리오 법령 매핑 모두 공개 검증 가능")

    L0(doc, "창업 의지")
    L1(doc, "한국 공공데이터의 사회 환원 모범 사례 구축")
    L1(doc, "데이터안심구역(DSZ) 결합 결과를 정책 보고서가 아닌 실시간 차량 알림으로 환원하는 첫 사례")
    L1(doc, "MIT 오픈소스 사회 환원 + B2B·B2G 수익 모델 동시 추진")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"[OK] {OUT}")
    print(f"     {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    build()
