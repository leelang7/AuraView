# Operations Cheatsheet

> ⚠️ 민감 정보(SERVICE_KEY, 서버 IP 등)는 이 파일에 기록하지 않습니다.
> 로컬에서는 `.env`, 운영에서는 시스템 환경변수 / Secrets Manager를 사용하세요.
> `.env.example` 파일에 필요한 키 목록만 문서화합니다.

## 실행 (로컬 개발)

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 실행 (운영)

```bash
cd /home/ubuntu/AuraView/backend
nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > uvicorn.log 2>&1 &
```

## 상태 확인

```bash
ps -ef | grep uvicorn
tail -f uvicorn.log
```

## 종료

```bash
pkill -f "uvicorn app.main:app"
```

## 재배포 한 줄 (CI/CD)

```bash
cd /home/ubuntu/AuraView/backend && git pull && pkill -f "uvicorn app.main:app" ; nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > uvicorn.log 2>&1 &
```

## 공공데이터 API 키 관리

1. 공공데이터포털에서 발급받은 인증키를 **절대 Git에 커밋하지 마세요.**
2. 서버에 `.env` 파일 생성 후 아래와 같이 기록합니다.

```
SERVICE_KEY=<your-decoded-service-key>
BASE_URL=https://apis.data.go.kr/B551982/rti
```

3. 과거 커밋에 키가 노출된 경우, 포털에서 키 폐기 후 재발급 받으세요.

## 데이터안심구역 분석

국토교통 데이터안심구역(https://dsz.ex.co.kr) 반입·분석·반출 규정은 `docs/DATASETS.md` 참조.
