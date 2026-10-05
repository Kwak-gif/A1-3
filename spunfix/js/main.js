// ===== main.js =====
// 화면 동작(이벤트 처리) + 백엔드 API 호출(fetch)을 담당하는 파일

document.addEventListener("DOMContentLoaded", function () {

  // --- 설정값 ---
  const REQUEST_TIMEOUT_MS = 90000;   // 화면 최대 대기 시간 90초 (서버 60초 + 재시도 여유)
  const SYMPTOM_MAX_LENGTH = 1000;    // 증상 입력 최대 글자 수 (서버와 동일)

  // --- 주요 HTML 요소 가져오기 ---
  const form       = document.getElementById("troubleshoot-form");
  const submitBtn  = document.getElementById("submit-btn");
  const loading    = document.getElementById("loading");
  const errorMsg   = document.getElementById("error-msg");
  const resultDiv  = document.getElementById("result");
  const resultContent = document.getElementById("result-content");
  const downloadBtn   = document.getElementById("download-btn");

  // 현재 받아온 마크다운 원본 텍스트와 입력 조건을 저장할 변수
  let currentMarkdownResult = "";
  let currentRequest = null;

  // 로딩 중 경과 시간 표시용
  const loadingText = loading ? loading.querySelector("p") : null;
  let elapsedTimer = null;

  // --- 트러블슈팅 폼 전송 처리 ---
  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault(); // 페이지 새로고침 방지
      runDiagnosis();
    });
  }

  /** 진단 요청 전체 흐름 (폼 제출·[다시 시도] 버튼에서 공통 사용) */
  async function runDiagnosis() {
    // 1) 이전 상태 초기화
    hideElement(errorMsg);
    hideElement(resultDiv);
    clearInputErrors();

    // 2) 입력값 수집
    const input = {
      resin:       document.getElementById("resin").value.trim(),
      gsm:         document.getElementById("gsm").value.trim(),
      defect_type: document.getElementById("defect-type").value.trim(),
      zone:        document.getElementById("zone").value.trim(),
      symptom:     document.getElementById("symptom").value.trim()
    };

    // 3) 빈 입력·글자 수 검증 (필수 항목)
    let hasError = false;
    if (!input.resin)       { markInputError("resin"); hasError = true; }
    if (!input.gsm)         { markInputError("gsm"); hasError = true; }
    if (!input.defect_type) { markInputError("defect-type"); hasError = true; }
    if (!input.symptom)     { markInputError("symptom"); hasError = true; }

    if (hasError) {
      showError("제품 소재, 평량(GSM), 불량 대분류, 증상 내용을 모두 입력해주세요.");
      focusFirstError();
      return;
    }

    if (input.symptom.length > SYMPTOM_MAX_LENGTH) {
      markInputError("symptom");
      showError("증상 내용은 최대 " + SYMPTOM_MAX_LENGTH + "자까지 입력할 수 있습니다. (현재 " + input.symptom.length + "자)");
      focusFirstError();
      return;
    }

    // 4) 로딩 표시 + 버튼 비활성화 + 경과 시간 표시
    startLoading();

    // 5) 백엔드 API 호출 (fetch)
    const controller = new AbortController();
    const timeoutId = setTimeout(function () {
      controller.abort();
    }, REQUEST_TIMEOUT_MS);

    try {
      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
        signal: controller.signal
      });

      // 6) 응답 읽기 (JSON이 아닌 응답도 안전하게 처리)
      const data = await readJsonSafely(response);

      if (!response.ok) {
        throw new Error(buildErrorMessage(response.status, data));
      }

      if (!data || !data.result) {
        throw new Error("AI 답변을 읽을 수 없습니다. 다시 시도해주세요.");
      }

      // 7) 결과 표시
      currentMarkdownResult = data.result;
      currentRequest = input;
      resultContent.innerHTML = formatResult(data.result);

      if (data.truncated) {
        const notice = document.createElement("p");
        notice.className = "truncated-notice";
        notice.textContent = "⚠️ 답변이 길어 일부가 생략되었습니다. 증상을 더 구체적으로 좁혀 다시 요청해보세요.";
        resultContent.appendChild(notice);
      }

      showElement(resultDiv);
      resultDiv.scrollIntoView({ behavior: "smooth", block: "start" });

    } catch (err) {
      // 타임아웃(AbortError) 처리
      if (err.name === "AbortError") {
        showError("응답 대기 시간(" + (REQUEST_TIMEOUT_MS / 1000) + "초)이 초과되었습니다. 잠시 후 다시 시도해주세요.", true);
      } else if (err instanceof TypeError) {
        // fetch 자체 실패 (서버 꺼짐, 네트워크 끊김)
        showError("서버에 연결할 수 없습니다. 서버(vercel dev)가 켜져 있는지, 네트워크 상태를 확인해주세요.", true);
      } else {
        showError(err.message || "오류가 발생했습니다. 다시 시도해주세요.", true);
      }
    } finally {
      // 8) 타이머 해제 + 로딩 해제 + 버튼 복원
      clearTimeout(timeoutId);
      stopLoading();
    }
  }

  // --- 문의 폼 전송 처리 ---
  const contactForm = document.getElementById("contact-form");
  if (contactForm) {
    contactForm.addEventListener("submit", function (e) {
      e.preventDefault();
      alert("문의가 접수되었습니다. 감사합니다!");
      contactForm.reset();
    });
  }

  // --- 마크다운 다운로드 처리 ---
  if (downloadBtn) {
    downloadBtn.addEventListener("click", function () {
      if (!currentMarkdownResult) return;

      const now = new Date();
      const content = buildDownloadContent(now);
      const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "spunfix_진단결과_" + formatTimestamp(now, true) + ".md";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    });
  }

  // ===== 유틸리티 함수들 =====

  /** 응답 본문을 JSON으로 안전하게 읽기 (HTML 오류 페이지 등은 null 반환) */
  async function readJsonSafely(response) {
    try {
      return await response.json();
    } catch (e) {
      return null;
    }
  }

  /** 상태 코드 + 서버가 보낸 오류 내용으로 사용자 안내 문구 만들기 */
  function buildErrorMessage(status, data) {
    const serverMsg = data && data.error ? data.error : "";
    if (serverMsg) {
      return serverMsg + " (코드: " + status + ")";
    }
    if (status === 504) return "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요. (코드: 504)";
    if (status >= 400 && status < 500) {
      return "요청 정보에 문제가 발생했습니다. 입력 내용을 확인 후 다시 시도해주세요. (코드: " + status + ")";
    }
    if (status >= 500) {
      return "AI 진단 서버 점검 중입니다. 잠시 후 다시 시도해주시거나 관리자에게 문의해주세요. (코드: " + status + ")";
    }
    return "알 수 없는 오류가 발생했습니다. (코드: " + status + ")";
  }

  /** HTML 특수문자 무력화 (XSS 방지) */
  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /** 줄 안의 **굵게** 표시 변환 (이미 escape된 텍스트에만 사용) */
  function formatInline(escapedText) {
    return escapedText.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  }

  /** AI 마크다운 결과를 안전하고 보기 좋은 HTML로 변환 */
  function formatResult(markdown) {
    const lines = String(markdown || "결과를 불러올 수 없습니다.").split(/\r?\n/);
    const html = [];

    lines.forEach(function (rawLine) {
      const line = rawLine.trim();
      let m;

      if (line === "") {
        html.push('<div class="md-gap"></div>');
      } else if (/^(-{3,}|\*{3,}|_{3,})$/.test(line)) {
        html.push('<hr class="md-hr">');
      } else if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {
        const level = Math.min(m[1].length + 2, 6); // # → h3, ## → h4 ...
        html.push("<h" + level + ' class="md-heading">' + formatInline(escapeHtml(m[2])) + "</h" + level + ">");
      } else if ((m = line.match(/^>\s?(.*)$/))) {
        html.push('<blockquote class="md-quote">' + formatInline(escapeHtml(m[1])) + "</blockquote>");
      } else if ((m = line.match(/^[-*•]\s+(.*)$/))) {
        html.push('<div class="md-bullet">• ' + formatInline(escapeHtml(m[1])) + "</div>");
      } else {
        html.push('<p class="md-p">' + formatInline(escapeHtml(line)) + "</p>");
      }
    });

    return html.join("");
  }

  /** 다운로드 파일 내용 (입력 조건 + AI 결과) */
  function buildDownloadContent(now) {
    const r = currentRequest || {};
    const header = [
      "# SpunFix 진단 결과",
      "",
      "- 진단 일시: " + formatTimestamp(now, false),
      "- 수지 소재: " + (r.resin || "-"),
      "- 목표 평량: " + (r.gsm ? r.gsm + " GSM" : "-"),
      "- 불량 대분류: " + (r.defect_type || "-"),
      "- 발생 구간: " + (r.zone || "미선택"),
      "- 구체적 증상: " + (r.symptom || "-"),
      "",
      "---",
      ""
    ].join("\n");
    return header + currentMarkdownResult + "\n";
  }

  /** 날짜·시간 문자열 (파일명용: 20261005_1430 / 표시용: 2026-10-05 14:30) */
  function formatTimestamp(d, forFileName) {
    const pad = function (n) { return String(n).padStart(2, "0"); };
    const date = d.getFullYear() + (forFileName ? "" : "-") + pad(d.getMonth() + 1) + (forFileName ? "" : "-") + pad(d.getDate());
    const time = pad(d.getHours()) + (forFileName ? "" : ":") + pad(d.getMinutes());
    return date + (forFileName ? "_" : " ") + time;
  }

  /** 로딩 시작 (경과 시간 표시) */
  function startLoading() {
    showElement(loading);
    submitBtn.disabled = true;
    submitBtn.textContent = "⏳ 분석 중...";

    const startedAt = Date.now();
    const updateText = function () {
      const sec = Math.floor((Date.now() - startedAt) / 1000);
      if (loadingText) {
        loadingText.textContent = "⏳ AI가 분석 중입니다... (" + sec + "초 경과 · 보통 10~40초 소요)";
      }
    };
    updateText();
    elapsedTimer = setInterval(updateText, 1000);
  }

  /** 로딩 종료 */
  function stopLoading() {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
    hideElement(loading);
    submitBtn.disabled = false;
    submitBtn.textContent = "🔍 진단 요청";
  }

  /** 오류 메시지 표시 (withRetry=true면 [다시 시도] 버튼 함께 표시) */
  function showError(message, withRetry) {
    errorMsg.textContent = message;

    if (withRetry) {
      const retryBtn = document.createElement("button");
      retryBtn.type = "button";
      retryBtn.className = "btn-retry";
      retryBtn.textContent = "🔄 다시 시도";
      retryBtn.addEventListener("click", runDiagnosis);
      errorMsg.appendChild(document.createElement("br"));
      errorMsg.appendChild(retryBtn);
    }

    showElement(errorMsg);
    errorMsg.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  /** 첫 번째 오류 입력창으로 스크롤 */
  function focusFirstError() {
    const firstError = document.querySelector(".input-error");
    if (firstError) firstError.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  /** 입력 필드에 오류 표시 (붉은 테두리) */
  function markInputError(elementId) {
    document.getElementById(elementId).classList.add("input-error");
  }

  /** 모든 입력 필드의 오류 표시 제거 */
  function clearInputErrors() {
    const errorFields = document.querySelectorAll(".input-error");
    errorFields.forEach(function (field) {
      field.classList.remove("input-error");
    });
  }

  /** 요소 보이기 */
  function showElement(el) {
    el.classList.remove("hidden");
  }

  /** 요소 숨기기 */
  function hideElement(el) {
    el.classList.add("hidden");
  }

});
