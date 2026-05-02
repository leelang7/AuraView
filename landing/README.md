# allthatai-landing

`allthatai.kr` 루트 랜딩 페이지 — GitHub Pages 호스팅.

AllThatAI 포트폴리오의 얼굴. 프로젝트 카드 추가는 `index.html` 하단 `.grid` 안에
`<a class="card" ...>` 블록 하나만 붙여넣으면 자동으로 확장됩니다.

## Deploy

GitHub Pages (무료 · HTTPS 자동):

1. GitHub 에 이 리포 push
2. Settings → Pages → Source: `main` 브랜치, folder `/` (root)
3. Custom domain: `allthatai.kr` 입력, "Enforce HTTPS" 체크
4. 가비아 DNS 에 A 레코드 4개 + `www` CNAME 설정 (아래)

## DNS (가비아)

| 타입 | 호스트 | 값 | TTL |
|---|---|---|---|
| A | `@` | `185.199.108.153` | 300 |
| A | `@` | `185.199.109.153` | 300 |
| A | `@` | `185.199.110.153` | 300 |
| A | `@` | `185.199.111.153` | 300 |
| CNAME | `www` | `leelang7.github.io.` | 300 |

> 기존 `@` A 레코드(Vultr `158.247.200.59`) 는 **위 4개로 교체**.
> `lolbutler.allthatai.kr` → Vultr, `auraview.allthatai.kr` → EC2 는 **그대로 유지**.
