// 全局状态对象，存储应用运行时的各种状态
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

// 通用的 JSON 请求封装函数，自动处理 HTTP 错误
async function fetchJSON(url, options = {}) {
  const response = await fetch(url, { ...options });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

// 向聊天面板追加一条消息，支持角色标识、引用来源展示
function appendMessage(role, content, options = {}) {
  const board = document.getElementById("streamOutput");
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const text = document.createElement("div");
  text.className = "message-content";
  const prefix = options.prefix || (role === "system" ? "系统：" : role === "user" ? "提问：" : "回答：");
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

// 将会话 ID 保存到 localStorage，用于会话持久化
function saveSessionId(sessionId) {
  state.sessionId = sessionId || "";
  if (state.sessionId) {
    localStorage.setItem("pdf-qna-session-id", state.sessionId);
  } else {
    localStorage.removeItem("pdf-qna-session-id");
  }
}

// 从后端加载文档状态信息，更新全局状态
async function loadStatus() {
  const documentStatus = await fetchJSON("/api/document/status");
  state.documentStatus = documentStatus;
  state.selectedSources = documentStatus.selected_sources || documentStatus.source_files || [];
}

// 加载检索索引预热状态
async function loadWarmupStatus() {
  const warmupStatus = await fetchJSON("/api/document/warmup");
  state.warmupStatus = warmupStatus;
  renderWarmupStatus(warmupStatus);
}

// 根据预热状态渲染对应的系统提示消息，避免重复显示
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

// 启动定时轮询，每 3 秒检查一次预热状态
function startWarmupPolling() {
  stopWarmupPolling();
  state.warmupPollTimer = window.setInterval(() => {
    loadWarmupStatus().catch(() => {});
  }, 3000);
}

// 停止预热状态的定时轮询
function stopWarmupPolling() {
  if (state.warmupPollTimer) {
    window.clearInterval(state.warmupPollTimer);
    state.warmupPollTimer = null;
  }
}

// 将当前选中的数据源文件列表同步到后端
async function syncSelectedSources() {
  await fetchJSON("/api/document/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_files: state.selectedSources }),
  });
}

// 根据上传状态切换上传按钮和相关控件的启用/禁用
function setUploadUI(isUploading) {
  state.isUploading = isUploading;
  const uploadButton = document.getElementById("uploadButton");
  const askButton = document.getElementById("askButton");
  const uploadInput = document.getElementById("uploadInput");

  uploadButton.textContent = isUploading ? "停止上传" : "上传";
  askButton.disabled = isUploading;
  uploadInput.disabled = isUploading;
}

// 根据提问状态切换提问按钮和相关控件的启用/禁用
function setAskUI(isAsking) {
  state.isAsking = isAsking;
  const uploadButton = document.getElementById("uploadButton");
  const askButton = document.getElementById("askButton");
  const questionInput = document.getElementById("questionInput");

  askButton.textContent = isAsking ? "停止发送" : "发送";
  uploadButton.disabled = isAsking;
  questionInput.disabled = isAsking;
}

// 渲染调试信息面板，有 debug 数据时显示，否则隐藏
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

// 加载并恢复指定会话的历史消息记录
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
        prefix: item.role === "assistant" ? "回答：" : item.role === "user" ? "提问：" : "系统：",
      });
    });
  } catch (error) {
    appendMessage("system", `读取会话失败：${error.message}`);
  }
}

// 处理文档上传流程：发送文件到后端，支持中途取消
async function uploadDocument() {
  const input = document.getElementById("uploadInput");
  const file = input.files?.[0];

  if (state.isUploading && state.activeUploadController) {
    state.activeUploadController.abort();
    return;
  }

  if (!file) {
    appendMessage("system", "请先选择一个 PDF 文件。");
    return;
  }

  const controller = new AbortController();
  state.activeUploadController = controller;
  setUploadUI(true);
  appendMessage("system", `开始上传并解析 ${file.name}`);

  try {
    const formData = new FormData();
    formData.append("file", file);
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
      appendMessage("system", `上传完成，已建立 ${result.chunk_count} 个分块。`);
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

// 处理提问流程：发送问题并通过 SSE 流式接收回答
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
    appendMessage("system", `无法检索。${warning}`);
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
      // 使用 fetch 发送 POST 请求，开启流式响应
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

    // 通过 ReadableStream 逐块读取 SSE 数据
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      // 将二进制数据解码为文本并累积到缓冲区
      buffer += decoder.decode(value, { stream: true });
      // 以双换行符分割 SSE 事件
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";

      for (const event of events) {
        const line = event.split("\n").find((item) => item.startsWith("data: "));
        if (!line) continue;

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

// 绑定页面上的按钮和输入框事件监听器
function bindEvents() {
  document.getElementById("askButton").addEventListener("click", askQuestion);
  document.getElementById("uploadButton").addEventListener("click", uploadDocument);
  document.getElementById("uploadInput").addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    document.getElementById("uploadFileLabel").textContent = file ? file.name : "上传";
  });
}

// 应用初始化入口：绑定事件、加载状态、恢复历史、启动轮询
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
