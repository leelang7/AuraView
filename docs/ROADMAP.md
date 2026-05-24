# Roadmap — 4주 압축 플랜

> 접수 마감 **2026-05-29**. 심사·멘토링 **5~7월**. 시상 **7월 중**.

---

## Week 1 (2026-04-21 ~ 2026-04-27) ─ 기반 다지기

**목표:** Occupancy PoC + HydraNet skeleton 이 로컬·서버에서 동작하는 상태.

- [x] README / 백서 / 기능 매트릭스 초안
- [x] 서비스 스켈레톤(occupancy, hydranet, risk_transformer, intent, pii, dsz)
- [x] 라우터(/occupancy, /fleet, /fusion, /dsz) 배선 + 대시보드 탭 10개
- [x] `requirements.txt` 확장 후 서버 기동 확인
- [x] 샘플 이미지로 `/occupancy/infer` · `/occupancy/demo` 정상 동작
- [x] 공공 API 키 확보 (VDS, TAAS, ITS) 또는 fallback 확정 — fallback 23종 모두 구비 (v9-23src-2026.05.21)

**Acceptance:** `curl /occupancy/demo` 가 `grid_b64` 포함 200 응답.

---

## Week 2 (2026-04-28 ~ 2026-05-04) ─ 학습 · 융합

**목표:** AI활용 10점 + 데이터융합 5점 + 가명결합 5점 증빙 확보.

- [x] `notebooks/train_hydranet.ipynb` — AIHub · K-LISA 데이터로 1 epoch 이상 학습
- [x] `notebooks/train_risk_transformer.ipynb` — 합성 데이터로 **AUC 0.9403** (목표 0.85 초과)
- [x] `notebooks/dsz_join_demo.ipynb` — TAAS × VDS 결합 시연 (k=5)
- [x] `/fusion/intersection/1007` 응답에 23종 모두 채움 (fallback 허용)
- [x] 가명결합 결과물 → 안심구역 반출 서식으로 export

**Acceptance:** 모든 기능 항목 별 증빙 파일 1개 이상 존재.

---

## Week 3 (2026-05-05 ~ 2026-05-11) ─ 플라이휠 + BEV 고도화

**목표:** 개발자의 시각 임팩트 극대화.

- [x] Three.js BEV 3D viewer — occupancy grid 를 voxel로 렌더 (시나리오별 동적 조명 포함)
- [x] `/fleet/contribute` 모바일 PWA + Flutter 네이티브 프런트엔드 + 갤러리 + KPI 패널
- [x] 1주 자동 재학습 파이프라인 (GitHub Actions + DVC)
- [x] 국가 위험 교차로 Top-N 자동 리포트 + **A4 1-pager 정책 PDF 자동 생성** (`/impact/policy-pdf`)

**Acceptance:** 대시보드가 실시간 BEV 3D 표시 + 전국 위험 교차로 점멸.

---

## Week 4 (2026-05-12 ~ 2026-05-28) ─ 발표 · 제출

**목표:** "처음 본 사람도 3분 안에 납득"하는 발표 자산.

- [x] 사고 재현 데모 영상 (`/showreel/build`, `/showreel/latest.mp4`)
- [x] 발표 슬라이드 **15장** (제목 + 문제 + 솔루션 + 임팩트 + 데모 + Showreel + Capability + 기술스택 + KMaaS + 기능매트릭스 + 시나리오 8종 + 법적 근거 + 1-step 검증 + 로드맵 + CTA)
- [x] 기술백서 v0.6 (Phase 7-14 누적 + 법적 근거 + 65 pytest)
- [x] **/competition/ 개발자 허브** — 단일 페이지에 모든 검증 URL + KPI hero + 라이브 status
- [x] **/metrics/manifest** — 11 검증 URL + 5 데모 + 5 문서 + 8 시나리오 + git_sha
- [x] **/policy/laws** + **/policy/regulations** — 8 시나리오 도로교통법·대법원 판례 매핑
- [x] 제출 전 QA 체크리스트 완주 (66 pytest passed · GitHub CI 4 jobs · /submission/ 12+ checks)
- [ ] **2026-05-29** 접수 마감 24시간 전 최종 제출 (D-22)

**Acceptance:** 시연 URL · GitHub 링크 · 백서 · 슬라이드 · 영상 5종 세트 완비.

---

## 리스크 레지스터

| 리스크 | 영향 | 완화책 |
|---|---|---|
| 공공 API 키 발급 지연 | 데이터융합 증빙 약화 | fallback 자동 응답 포함, 샘플 JSON 커밋 |
| 안심구역 반입 승인 지연 | 안심구역 5점 누락 | 로컬 `/dsz/join/taas-vds` 시연 + 신청 접수증 캡처 |
| 학습 시간 부족 | AI활용 10점 약화 | 1 epoch만이라도 실행 + tensorboard 로그 제출 |
| 모바일 PWA 개발 지연 | Fleet 증빙 약화 | curl 기반 contribute 시연으로 대체 |
| 영상 분량 부족 | 발표 임팩트 저하 | Before/After 3-shot 고정 템플릿 사용 |
