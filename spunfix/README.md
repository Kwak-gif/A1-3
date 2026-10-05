# SpunFix – 부직포 공정·품질 트러블슈팅 도우미

스펀본드(Spunbond) 부직포 제조 현장의 불량 증상과 제품 사양을 입력하면,  
AI가 **예상 원인 순위**, **현장 점검 포인트**, **단계별 조치 방향**을 즉시 제공하는 웹 서비스입니다.

---

## 📂 프로젝트 구조

```
spunfix/
├── index.html          ← 메인 페이지 (5개 섹션 포함)
├── css/style.css       ← 디자인 (스타일시트)
├── js/main.js          ← 화면 동작 + API 호출
├── api/analyze.py      ← 백엔드 서버리스 함수 (Claude AI 호출)
├── images/             ← 이미지 폴더
├── requirements.txt    ← Python 패키지 목록
├── .gitignore          ← Git 제외 파일 목록 (보안 목적)
├── .env.example        ← 환경변수 설정 가이드(템플릿)
└── README.md           ← 이 파일
```

## 🚀 사용 기술

| 영역 | 기술 |
| --- | --- |
| 프론트엔드 | HTML5 / CSS3 / 바닐라 JavaScript |
| 백엔드 | Python (Vercel Serverless Functions) |
| AI | Anthropic Claude API (claude-3-haiku-20240307) |
| 배포 | Vercel |

## ⚙️ 로컬 실행 및 환경 변수 설정

**로컬 환경 (내 컴퓨터) 테스트 시:**
1. `.env.example` 파일을 복사하여 `.env` 라는 이름으로 파일을 생성합니다.
2. `.env` 파일 안에 본인의 API 키를 입력합니다. (`ANTHROPIC_API_KEY=나의_키`)
3. `.env` 파일은 `.gitignore` 규칙에 의해 안전하게 보호되며 외부에 유출되지 않습니다.

**Vercel 배포 시:**
Vercel 대시보드 → Settings → Environment Variables 메뉴로 이동하여 아래 환경 변수를 등록하세요.

| 변수명 | 설명 |
| --- | --- |
| `ANTHROPIC_API_KEY` | Anthropic(Claude) API 인증 키 |

## ⚠️ 면책 조항

본 서비스의 AI 진단 결과는 참고용 추정치이며,  
설비 조작 전 반드시 사내 표준 작업 지침서(SOP)를 준수하세요.
