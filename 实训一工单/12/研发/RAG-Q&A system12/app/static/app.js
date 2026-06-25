const state = {
  selectedSources: [],
  retrievalMode: "hybrid",
  topK: 4,
  scoreThreshold: 0,
  rerankerEnabled: false,
  rerankerTypes: [],
  sessionId: "",
  activeUploadController: null,
  activeAskController: null,
  isUploading: false,
  isAsking: false,
  documentStatus: null,
  warmupStatus: null,
  warmupPollTimer: null,
  lastWarmupBannerKey: "",
  lastDocumentBannerKey: "",
  lastDocumentProcessingStatus: "idle",
};

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, { ...options });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

function appendMessage(role, content, options = {}) {
  const board = document.getElementById("streamOutput");
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const text = document.createElement("div");
  text.className = "message-content";
  const prefix = options.prefix || (
    role === "system" ? "系统: " : role === "user" ? "提问: " : "回答: "
  );
  text.textContent = `${prefix}${content}`;
  bubble.appendChild(text);

  if (options.citations?.length) {
    const citations = document.createElement("div");
    citations.className = "message-citations";
    options.citations.forEach((item) => {
      const pill = document.createElement("span");
      pill.className = "citation-pill";
      const page = item.page_number ? `P${item.page_number}` : "页码未知";
      pill.textContent = `${item.source_id} · ${page}`;
      citations.appendChild(pill);
    });
    bubble.appendChild(citations);
  }

  wrapper.appendChild(bubble);
  board.appendChild(wrapper);
  board.scrollTop = board.scrollHeight;
}

function saveSessionId(sessionId) {
  state.sessionId = sessionId || "";
  if (state.sessionId) {
    localStorage.setItem("pdf-qna-session-id", state.sessionId);
  } else {
    localStorage.removeItem("pdf-qna-session-id");
  }
}

function syncActionButtons() {
  const uploadButton = document.getElementById("uploadButton");
  const askButton = document.getElementById("askButton");
  const uploadInput = document.getElementById("uploadInput");
  const questionInput = document.getElementById("questionInput");
  const processing = state.documentStatus?.processing_status === "running";

  uploadButton.textContent = state.isUploading ? "停止上传" : "上传";
  askButton.textContent = state.isAsking ? "停止发送" : processing ? "解析中" : "发送";

  uploadButton.disabled = state.isAsking;
  uploadInput.disabled = state.isUploading || state.isAsking;
  askButton.disabled = state.isUploading || state.isAsking || processing;
  questionInput.disabled = state.isAsking;
}

function setUploadUI(isUploading) {
  state.isUploading = isUploading;
  syncActionButtons();
}

function setAskUI(isAsking) {
  state.isAsking = isAsking;
  syncActionButtons();
}

function renderDebug(result) {
  const debugOutput = document.getElementById("debugOutput");
  if (result?.debug) {
    debugOutput.classList.remove("hidden");
    debugOutput.textContent = JSON.stringify(result.debug, null, 2);
  } else {
    debugOutput.classList.add("hidden");
    debugOutput.textContent = "";
  }
}

function setRetrievalMode(mode) {
  state.retrievalMode = mode;
  const cards = document.querySelectorAll(".retrieval-card");
  cards.forEach((card) => {
    card.classList.toggle("is-active", card.dataset.mode === mode);
  });
  if (mode === "fulltext" || mode === "keyword") {
    state.rerankerEnabled = false;
    const toggle = document.getElementById("rerankerEnabledToggle");
    if (toggle) {
      toggle.checked = false;
    }
    updateRerankerStrategyUI();
  }
}

function renderControlValues() {
  document.getElementById("topKValue").textContent = String(state.topK);
  document.getElementById("scoreThresholdValue").textContent = state.scoreThreshold.toFixed(2);
}

function updateRerankerStrategyUI() {
  const chips = document.querySelectorAll(".strategy-chip");
  chips.forEach((chip) => {
    const input = chip.querySelector("input");
    const isActive = state.rerankerTypes.includes(input.value);
    chip.classList.toggle("is-active", isActive);
    input.checked = isActive;
  });
  document.getElementById("rerankerStrategyGroup").classList.toggle("is-disabled", !state.rerankerEnabled);
}

function renderWarmupStatus(warmupStatus) {
  if (!warmupStatus) {
    return;
  }

  const { status, message, error } = warmupStatus;
  const bannerKey = `${status}:${message}:${error || ""}`;
  if (bannerKey === state.lastWarmupBannerKey) {
    return;
  }

  if (status === "running") {
    appendMessage("system", "检索索引正在后台准备，首次提问可能稍慢。", { prefix: "" });
  } else if (status === "ready" && state.lastWarmupBannerKey) {
    appendMessage("system", "检索索引已就绪。", { prefix: "" });
  } else if (status === "failed") {
    appendMessage("system", "检索预热失败，系统将按当前可用能力继续工作。", { prefix: "" });
    if (error) {
      appendMessage("system", error, { prefix: "" });
    }
  }

  state.lastWarmupBannerKey = bannerKey;
}

function renderDocumentProcessingStatus(documentStatus) {
  if (!documentStatus) {
    return;
  }

  const status = documentStatus.processing_status || "idle";
  const message = documentStatus.processing_message || "not_started";
  const sources = documentStatus.processing_sources || [];
  const error = documentStatus.processing_error || "";
  const bannerKey = `${status}:${message}:${sources.join("|")}:${error}`;
  if (bannerKey === state.lastDocumentBannerKey) {
    return;
  }

  if (status === "running") {
    const scope = sources.length ? sources.join("、") : "所选文档";
    appendMessage("system", `文件已接收，后台解析中：${scope}。`, { prefix: "" });
  } else if (status === "ready" && state.lastDocumentProcessingStatus === "running") {
    const loadedAt = Date.parse(documentStatus.last_loaded_at || "");
    const startedAt = Date.parse(documentStatus.processing_started_at || "");
    const hasCurrentRefresh = Number.isNaN(startedAt) || (!Number.isNaN(loadedAt) && loadedAt >= startedAt);
    if (!hasCurrentRefresh || (sources.length && !documentStatus.document_count && !error)) {
      return;
    }
    const selected = documentStatus.selected_sources?.length
      ? documentStatus.selected_sources.join("、")
      : "全部文档";
    const retrievableChunks = documentStatus.selected_chunk_count ?? documentStatus.chunk_count ?? 0;
    if (retrievableChunks <= 0 && !error) {
      return;
    }
    appendMessage(
      "system",
      `解析完成：当前已载入 ${documentStatus.document_count} 份文档，可检索分块 ${retrievableChunks} 个，检索范围为 ${selected}。`,
      { prefix: "" },
    );
  } else if (status === "failed") {
    appendMessage("system", `文档解析失败：${error || "请查看后端日志。"}`, { prefix: "" });
  }

  state.lastDocumentProcessingStatus = status;
  state.lastDocumentBannerKey = bannerKey;
}

async function loadStatus() {
  const documentStatus = await fetchJSON("/api/document/status");
  state.documentStatus = documentStatus;
  state.selectedSources = documentStatus.selected_sources || documentStatus.source_files || [];
  renderDocumentProcessingStatus(documentStatus);
  syncActionButtons();
}

async function loadWarmupStatus() {
  const warmupStatus = await fetchJSON("/api/document/warmup");
  state.warmupStatus = warmupStatus;
  renderWarmupStatus(warmupStatus);
}

function startWarmupPolling() {
  stopWarmupPolling();
  state.warmupPollTimer = window.setInterval(() => {
    Promise.allSettled([loadStatus(), loadWarmupStatus()]).catch(() => {});
  }, 3000);
}

function stopWarmupPolling() {
  if (state.warmupPollTimer) {
    window.clearInterval(state.warmupPollTimer);
    state.warmupPollTimer = null;
  }
}

async function syncSelectedSources() {
  await fetchJSON("/api/document/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_files: state.selectedSources }),
  });
}

async function loadSessionHistory() {
  if (!state.sessionId) {
    return;
  }

  try {
    const payload = await fetchJSON(`/api/session/${state.sessionId}`);
    const board = document.getElementById("streamOutput");
    board.innerHTML = "";
    payload.messages.forEach((item) => {
      appendMessage(item.role, item.content, {
        prefix: item.role === "assistant" ? "回答: " : item.role === "user" ? "提问: " : "系统: ",
      });
    });
  } catch (error) {
    appendMessage("system", `读取会话失败：${error.message}`);
  }
}

function resetConversationSession() {
  saveSessionId("");
  const board = document.getElementById("streamOutput");
  if (board) {
    board.innerHTML = "";
  }
}

async function uploadDocument() {
  const input = document.getElementById("uploadInput");
  const files = Array.from(input.files || []);

  if (state.isUploading && state.activeUploadController) {
    state.activeUploadController.abort();
    return;
  }

  if (!files.length) {
    appendMessage("system", "请先选择一个或多个 PDF 文件。");
    return;
  }

  const controller = new AbortController();
  state.activeUploadController = controller;
  setUploadUI(true);
  appendMessage("system", `开始上传：${files.map((item) => item.name).join("、")}`);

  try {
    const formData = new FormData();
    files.forEach((file) => {
      formData.append("files", file);
    });

    const result = await fetchJSON("/api/document/upload", {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });

    state.documentStatus = result;
    state.selectedSources = result.selected_sources || files.map((item) => item.name);
    renderDocumentProcessingStatus(result);
    input.value = "";
    document.getElementById("uploadFileLabel").textContent = "上传";
    syncActionButtons();
  } catch (error) {
    if (error.name === "AbortError") {
      appendMessage("system", "上传已停止。");
    } else {
      appendMessage("system", `上传失败：${error.message}`);
    }
  } finally {
    state.activeUploadController = null;
    setUploadUI(false);
  }
}

async function askQuestion() {
  const questionInput = document.getElementById("questionInput");
  const question = questionInput.value.trim();

  if (state.isAsking && state.activeAskController) {
    state.activeAskController.abort();
    return;
  }

  if (!question) {
    return;
  }

  await loadStatus();
  if (state.documentStatus?.processing_status === "running") {
    appendMessage("system", "文档仍在解析，请等待解析完成后再提问。");
    return;
  }

  const retrievableChunks = state.documentStatus?.selected_chunk_count ?? state.documentStatus?.chunk_count ?? 0;
  if (retrievableChunks <= 0) {
    const warning = state.documentStatus?.warnings?.[0] || "当前没有可检索的文档分块。";
    appendMessage("system", `无法检索：${warning}`);
    return;
  }

  await syncSelectedSources();

  const controller = new AbortController();
  state.activeAskController = controller;
  setAskUI(true);
  appendMessage("user", question);
  questionInput.value = "";
  renderDebug(null);

  try {
    const response = await fetch("/api/query/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        top_k: state.topK,
        include_debug: false,
        source_files: state.selectedSources,
        session_id: state.sessionId || null,
        retrieval_mode: state.retrievalMode,
        score_threshold: state.scoreThreshold,
        reranker_enabled: state.rerankerEnabled,
        reranker_types: state.rerankerEnabled ? state.rerankerTypes : [],
      }),
      signal: controller.signal,
    });

    if (!response.ok || !response.body) {
      const text = await response.text();
      throw new Error(text || `Request failed: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";

      for (const event of events) {
        const line = event.split("\n").find((item) => item.startsWith("data: "));
        if (!line) {
          continue;
        }

        const payload = JSON.parse(line.slice(6));
        if (payload.type === "status") {
          appendMessage("system", "正在处理你的问题...");
        }

        if (payload.type === "result") {
          const result = payload.payload;
          saveSessionId(result.session_id);
          appendMessage("assistant", result.answer || "", {
            citations: result.citations || [],
          });
          renderDebug(null);
        }

        if (payload.type === "error") {
          appendMessage("system", payload.message || "请求失败。");
        }
      }
    }
  } catch (error) {
    if (error.name === "AbortError") {
      appendMessage("system", "发送已停止。");
    } else {
      appendMessage("system", `请求失败：${error.message}`);
    }
  } finally {
    state.activeAskController = null;
    setAskUI(false);
  }
}

function bindEvents() {
  document.getElementById("askButton").addEventListener("click", askQuestion);
  document.getElementById("uploadButton").addEventListener("click", uploadDocument);
  document.getElementById("retrievalModeGroup").addEventListener("click", (event) => {
    const card = event.target.closest(".retrieval-card");
    if (!card) {
      return;
    }
    setRetrievalMode(card.dataset.mode);
  });
  document.getElementById("topKRange").addEventListener("input", (event) => {
    state.topK = Number(event.target.value);
    renderControlValues();
  });
  document.getElementById("scoreThresholdRange").addEventListener("input", (event) => {
    state.scoreThreshold = Number(event.target.value);
    renderControlValues();
  });
  document.getElementById("rerankerEnabledToggle").addEventListener("change", (event) => {
    state.rerankerEnabled = Boolean(event.target.checked);
    // 打开开关时默认勾选 cross_encoder，避免 reranker_types 为空导致重排不生效
    if (state.rerankerEnabled && state.rerankerTypes.length === 0) {
      state.rerankerTypes.push("cross_encoder");
    }
    updateRerankerStrategyUI();
  });
  document.getElementById("rerankerStrategyGroup").addEventListener("change", (event) => {
    const input = event.target.closest("input[type='checkbox']");
    if (!input) {
      return;
    }
    const strategy = input.value;
    if (input.checked) {
      if (!state.rerankerTypes.includes(strategy)) {
        state.rerankerTypes.push(strategy);
      }
    } else {
      state.rerankerTypes = state.rerankerTypes.filter((item) => item !== strategy);
    }
    if (!state.rerankerTypes.length) {
      state.rerankerEnabled = false;
      document.getElementById("rerankerEnabledToggle").checked = false;
    }
    updateRerankerStrategyUI();
  });
  document.getElementById("uploadInput").addEventListener("change", (event) => {
    const files = Array.from(event.target.files || []);
    document.getElementById("uploadFileLabel").textContent = files.length ? `已选 ${files.length} 个` : "上传";
  });
}

async function bootstrap() {
  bindEvents();
  resetConversationSession();
  const defaultRetrievalCard = document.querySelector(".retrieval-card.is-active");
  if (defaultRetrievalCard?.dataset.mode) {
    state.retrievalMode = defaultRetrievalCard.dataset.mode;
  }
  setRetrievalMode(state.retrievalMode);
  renderControlValues();
  updateRerankerStrategyUI();
  await loadStatus();
  await loadWarmupStatus();
  syncActionButtons();
  startWarmupPolling();
}

bootstrap().catch((error) => {
  appendMessage("system", `初始化失败：${error.message}`);
});
