const state = {
  selectedSources: [],
  sessionId: localStorage.getItem("pdf-qna-session-id") || "",
  activeUploadController: null,
  activeAskController: null,
  isUploading: false,
  isAsking: false,
  documentStatus: null,
  warmupStatus: null,
  warmupPollTimer: null,
  lastWarmupBannerKey: "",
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

async function loadStatus() {
  const documentStatus = await fetchJSON("/api/document/status");
  state.documentStatus = documentStatus;
  state.selectedSources = documentStatus.selected_sources || documentStatus.source_files || [];
}

async function loadWarmupStatus() {
  const warmupStatus = await fetchJSON("/api/document/warmup");
  state.warmupStatus = warmupStatus;
  renderWarmupStatus(warmupStatus);
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
    appendMessage("system", "系统正在后台预热检索索引，首次提问可能稍慢。", { prefix: "" });
  } else if (status === "ready" && state.lastWarmupBannerKey) {
    appendMessage("system", "检索索引预热完成。", { prefix: "" });
  } else if (status === "failed") {
    appendMessage("system", "检索索引预热失败，系统将继续尝试按当前配置工作。", { prefix: "" });
  }

  state.lastWarmupBannerKey = bannerKey;
}

function startWarmupPolling() {
  stopWarmupPolling();
  state.warmupPollTimer = window.setInterval(() => {
    loadWarmupStatus().catch(() => {});
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

function setUploadUI(isUploading) {
  state.isUploading = isUploading;
  const uploadButton = document.getElementById("uploadButton");
  const askButton = document.getElementById("askButton");
  const uploadInput = document.getElementById("uploadInput");

  uploadButton.textContent = isUploading ? "停止上传" : "上传";
  askButton.disabled = isUploading;
  uploadInput.disabled = isUploading;
}

function setAskUI(isAsking) {
  state.isAsking = isAsking;
  const uploadButton = document.getElementById("uploadButton");
  const askButton = document.getElementById("askButton");
  const questionInput = document.getElementById("questionInput");

  askButton.textContent = isAsking ? "停止发送" : "发送";
  uploadButton.disabled = isAsking;
  questionInput.disabled = isAsking;
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
  appendMessage("system", `开始上传并解析：${files.map((item) => item.name).join("、")}`);

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
    state.selectedSources = result.selected_sources || result.source_files || [];
    input.value = "";
    document.getElementById("uploadFileLabel").textContent = "上传";

    if (result.chunk_count > 0) {
      appendMessage(
        "system",
        `解析完成：当前已载入 ${result.document_count} 份文档，本次检索范围为 ${state.selectedSources.join("、")}。`,
      );
    } else {
      const warning = result.warnings?.[0] || "上传成功，但没有解析出可检索内容。";
      appendMessage("system", `上传完成，但当前不可检索。原因：${warning}`);
    }
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
  if (!state.documentStatus?.chunk_count) {
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
        include_debug: true,
        source_files: state.selectedSources,
        session_id: state.sessionId || null,
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
          renderDebug(result);
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
  document.getElementById("uploadInput").addEventListener("change", (event) => {
    const files = Array.from(event.target.files || []);
    document.getElementById("uploadFileLabel").textContent = files.length ? `已选 ${files.length} 个` : "上传";
  });
}

async function bootstrap() {
  bindEvents();
  await loadStatus();
  await loadWarmupStatus();
  await loadSessionHistory();
  startWarmupPolling();
}

bootstrap().catch((error) => {
  appendMessage("system", `初始化失败：${error.message}`);
});
