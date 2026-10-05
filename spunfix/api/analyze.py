# api/analyze.py
# Vercel Serverless Function - AI 트러블슈팅 백엔드 (Claude 버전)

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
import anthropic

def _clean_env(val, default=""):
    return (val or default).strip()

def _get_config():
    api_key = _clean_env(os.environ.get("ANTHROPIC_API_KEY", ""))
    base_url = _clean_env(os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")).rstrip("/")
    model_name = _clean_env(os.environ.get("ANTHROPIC_MODEL", "claude-3-haiku-20240307"))
    return api_key, base_url, model_name

# --- 속도·비용 제한 설정 (개선 1·2·4) ---
MAX_TOKENS = 1500          # 답변 길이 상한 기본값 (1500 토큰)
API_TIMEOUT_SEC = 60       # Claude 응답 최대 대기 시간 (SDK 기본 600초 → 60초)
API_MAX_RETRIES = 1        # 실패 시 자동 재시도 횟수 (SDK 기본 2회 → 1회)
MAX_BODY_BYTES = 10_000    # 요청 본문 최대 크기
LIMITS = {                 # 입력 항목별 최대 글자 수
    "resin": 50, "gsm": 10, "defect_type": 50, "zone": 50, "symptom": 1000,
}

# --- '모름' 개수별 답변 길이 설정 ---
UNKNOWN_VALUE = "모름"
UNKNOWN_FIELDS = ("defect_type", "zone")   # '모름'을 선택할 수 있는 항목
TOKEN_BY_UNKNOWN = {                        # 모름 개수: (max_tokens, 프롬프트 분량 기준)
    0: (MAX_TOKENS, "약 1,500자"),          # 기본 (1500 토큰)
    1: (2000, "약 2,000자"),                # 대분류 또는 구간 중 1개 모름 (2000 토큰)
    2: (2500, "약 2,500자"),                # 둘 다 모름 (2500 토큰)
}


def count_unknowns(fields):
    """'모름'을 선택한 항목의 개수(0, 1, 2)를 계산합니다."""
    return sum(1 for k in UNKNOWN_FIELDS if fields.get(k) == UNKNOWN_VALUE)


def resolve_max_tokens(fields):
    """모름 개수(0, 1, 2개)에 따라 (max_tokens, 분량 가이드)를 반환하는 함수"""
    count = count_unknowns(fields)
    return TOKEN_BY_UNKNOWN.get(count, TOKEN_BY_UNKNOWN[0])


def _get_client():
    api_key, base_url, _ = _get_config()
    return anthropic.Anthropic(
        api_key=api_key,
        base_url=base_url,
        timeout=API_TIMEOUT_SEC,
        max_retries=API_MAX_RETRIES,
    )


def _log(message):
    """상세 오류는 화면이 아닌 서버 터미널 로그에만 남깁니다 (개선 4)"""
    print(f"[analyze] {message}", file=sys.stderr, flush=True)


class handler(BaseHTTPRequestHandler):
    """Vercel이 호출하는 서버리스 함수 핸들러"""

    def do_POST(self):
        # 1) 요청 본문(body) 읽기 + 형식 검사 → 잘못된 요청은 400
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            content_length = 0
        if content_length <= 0:
            self._send_json(400, {"error": "요청 내용이 비어 있습니다.", "code": "EMPTY_BODY"})
            return
        if content_length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "입력 내용이 너무 깁니다.", "code": "TOO_LARGE"})
            return

        try:
            body = json.loads(self.rfile.read(content_length))
            if not isinstance(body, dict):
                raise ValueError("JSON 객체가 아님")
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "요청 형식이 올바르지 않습니다.", "code": "BAD_JSON"})
            return

        # 2) 필수 입력값 확인 (숫자 등 글자가 아닌 값도 안전하게 처리)
        fields = {key: str(body.get(key) or "").strip() for key in LIMITS}

        if not fields["resin"] or not fields["gsm"] or not fields["defect_type"] or not fields["symptom"]:
            self._send_json(400, {"error": "필수 입력값이 누락되었습니다.", "code": "MISSING_FIELD"})
            return

        for key, limit in LIMITS.items():
            if len(fields[key]) > limit:
                self._send_json(400, {
                    "error": f"입력 글자 수를 초과했습니다. ({key}: 최대 {limit}자)",
                    "code": "TOO_LONG",
                })
                return

        api_key, base_url, model_name = _get_config()

        if not api_key:
            _log("ANTHROPIC_API_KEY 환경 변수가 없습니다.")
            self._send_json(500, {"error": "서버 설정(API 키)이 누락되었습니다. 관리자에게 문의하세요.", "code": "NO_API_KEY"})
            return

        _log(f"진단 요청 시작: URL={base_url}, MODEL={model_name}, KEY_LEN={len(api_key)}")

        # 3) AI 호출 + 모름 개수별 max_tokens 별도 적용 함수 적용
        tokens_limit, length_guide = resolve_max_tokens(fields)
        try:
            response = _get_client().messages.create(
                model=model_name,
                max_tokens=tokens_limit,
                messages=[{"role": "user", "content": self._build_prompt(fields, length_guide)}],
            )
        except anthropic.APITimeoutError:
            _log("Claude 응답 시간 초과")
            self._send_json(504, {"error": "AI 응답이 지연되어 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.", "code": "AI_TIMEOUT"})
            return
        except anthropic.APIConnectionError as e:
            _log(f"Claude 연결 실패 (URL={base_url}): {e!r}")
            self._send_json(502, {
                "error": f"AI 서버({base_url})에 연결하지 못했습니다. Vercel 환경 변수의 주소 철자 또는 방화벽을 확인해주세요.",
                "code": "AI_CONNECTION"
            })
            return
        except anthropic.AuthenticationError as e:
            _log(f"인증 실패: {e!r}")
            self._send_json(502, {"error": "AI 서버 인증에 실패했습니다. 관리자에게 API 키 확인을 요청하세요.", "code": "AI_AUTH"})
            return
        except anthropic.RateLimitError as e:
            _log(f"요청 한도 초과: {e!r}")
            self._send_json(429, {"error": "요청이 많아 잠시 처리할 수 없습니다. 1분 후 다시 시도해주세요.", "code": "AI_RATE_LIMIT"})
            return
        except anthropic.APIStatusError as e:
            _log(f"Claude API 오류 (status={e.status_code}): {e!r}")
            if e.status_code in (500, 502, 503, 529):
                msg = "AI 서버가 일시적으로 혼잡합니다. 잠시 후 다시 시도해주세요."
            else:
                msg = f"AI 서버가 요청을 처리하지 못했습니다. (AI 코드: {e.status_code})"
            self._send_json(502, {"error": msg, "code": "AI_API_ERROR"})
            return
        except Exception as e:
            _log(f"예상치 못한 오류: {e!r}")
            self._send_json(500, {"error": "서버 내부 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", "code": "INTERNAL"})
            return

        # 4) 결과 추출 (빈 답변·잘린 답변 확인)
        ai_result = "".join(
            block.text for block in (response.content or []) if getattr(block, "type", "") == "text"
        ).strip()

        if not ai_result:
            _log(f"빈 답변 수신 (stop_reason={response.stop_reason})")
            self._send_json(502, {"error": "AI가 빈 답변을 보냈습니다. 다시 시도해주세요.", "code": "AI_EMPTY"})
            return

        self._send_json(200, {
            "result": ai_result,
            "truncated": response.stop_reason == "max_tokens",
        })

    def do_GET(self):
        """정적 파일(HTML, CSS, JS 등) 서빙 및 GET 요청 처리"""
        # URL 경로 정리 (쿼리스트링 제거 및 앞 슬래시 제거)
        raw_path = getattr(self, "path", "/") or "/"
        path = raw_path.split("?")[0].lstrip("/")
        if not path or path == "index.html":
            path = "index.html"

        # 안전한 경로 조합 (디렉토리 탈출 방지)
        safe_rel_path = os.path.normpath(path)
        if safe_rel_path.startswith(".."):
            self._send_json(403, {"error": "접근이 금지된 경로입니다.", "code": "FORBIDDEN"})
            return

        # spunfix 폴더 내부 또는 프로젝트 루트에서 파일 탐색
        current_dir = os.path.dirname(os.path.abspath(__file__))  # api/
        parent_dir = os.path.dirname(current_dir)                 # spunfix/ 또는 루트

        target_file = None
        candidates = [
            os.path.join(parent_dir, safe_rel_path),
            os.path.join(parent_dir, "spunfix", safe_rel_path),
            os.path.join(os.path.dirname(parent_dir), "spunfix", safe_rel_path),
        ]
        for c in candidates:
            if os.path.isfile(c):
                target_file = c
                break

        if not target_file:
            self._send_json(404, {"error": "요청하신 페이지 또는 파일을 찾을 수 없습니다.", "code": "NOT_FOUND"})
            return

        # MIME 타입 결정
        content_type = "application/octet-stream"
        if target_file.endswith(".html"):
            content_type = "text/html; charset=utf-8"
        elif target_file.endswith(".css"):
            content_type = "text/css; charset=utf-8"
        elif target_file.endswith(".js"):
            content_type = "application/javascript; charset=utf-8"
        elif target_file.endswith(".json"):
            content_type = "application/json; charset=utf-8"
        elif target_file.endswith(".png"):
            content_type = "image/png"
        elif target_file.endswith((".jpg", ".jpeg")):
            content_type = "image/jpeg"
        elif target_file.endswith(".svg"):
            content_type = "image/svg+xml"
        elif target_file.endswith(".ico"):
            content_type = "image/x-icon"
        elif target_file.endswith(".md"):
            content_type = "text/markdown; charset=utf-8"

        try:
            with open(target_file, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            _log(f"정적 파일 읽기 실패: {e!r}")
            self._send_json(500, {"error": "파일을 읽는 중 오류가 발생했습니다.", "code": "FILE_READ_ERROR"})

    @staticmethod
    def _build_prompt(f, length_guide="약 1,500자"):
        """AI에게 보낼 프롬프트 구성 ('모름' 선택 시 추정 지시 및 분량 가이드 반영)"""
        zone_info = f"  - 발생 구간: {f['zone']}\n" if f["zone"] else ""
        unknown_guide = ""
        if f.get("defect_type") == UNKNOWN_VALUE or f.get("zone") == UNKNOWN_VALUE:
            unknown_guide = "- '모름'으로 입력된 항목(대분류/발생 구간)은 '구체적 증상'을 바탕으로 가장 가능성 높은 항목을 먼저 추정하여 서두에 밝혀주세요.\n"

        return f"""당신은 스펀본드(Spunbond) 부직포 제조 공정의 품질 트러블슈팅 전문가입니다.
아래 현장 정보를 바탕으로 분석해주세요.

[제품 사양]
  - 수지 소재: {f['resin']}
  - 목표 평량: {f['gsm']} GSM

[불량 정보]
  - 불량 대분류: {f['defect_type']}
{zone_info}  - 구체적 증상: {f['symptom']}

[작성 규칙]
- 현장 작업자가 바로 읽고 실행할 수 있도록 핵심만 간결하게 작성하세요.
- 전체 분량은 {length_guide} 이내로 작성하세요.
- 각 항목은 짧은 글머리표(-) 위주로 쓰고, 표와 HTML 태그는 사용하지 마세요.
{unknown_guide}
다음 형식으로 한국어로 답변해주세요:

**[전체 목차]**
전체 답변의 핵심 목차를 먼저 요약해서 보여주세요.

**1. 예상 원인 순위 (상위 3가지)**
각 원인에 대해 왜 이 문제가 발생하는지 간단히 설명해주세요.

**2. 현장 점검 포인트**
현장 작업자가 즉시 확인해야 할 구체적인 위치와 방법을 알려주세요.

**3. 단계별 조치 방향**
[즉각 조치] → [공정 조정] → [예방 조치] 순서로 알려주세요.

**4. 안전 수칙**
해당 점검·조치 시 주의할 점을 적어주세요.

⚠️ 마지막에 반드시 다음 문구를 포함하세요:
"본 안내는 참고용이며 실제 조치는 사내 표준(SOP)과 담당자 판단을 따르세요."
"""

    def _send_json(self, status_code, data):
        """JSON 응답을 보내는 유틸리티 메서드"""
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
