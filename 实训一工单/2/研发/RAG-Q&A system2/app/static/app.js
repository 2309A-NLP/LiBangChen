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
  uploadTaskPollTimer: null,
  activeUploadTaskId: "",
  lastUploadTaskBannerKey: "",
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
  const prefix =
    options.prefix !== undefined
      ? options.prefix
      : role === "system"
        ? "System: "
        : role === "user"
          ? "Question: "
          : "Answer: ";
  text.textContent = `${prefix}${content}`;
  bubble.appendChild(text);

  if (options.citations?.length) {
    const citations = document.createElement("div");
    citations.className = "message-citations";
    options.citations.forEach((item) => {
      const pill = document.createElement("span");
      pill.className = "citation-pill";
      const page = item.page_number ? `P${item.page_number}` : "Page unknown";
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
    appendMessage("system", "Retriever warmup is running in the background.", { prefix: "" });
  } else if (status === "ready" && state.lastWarmupBannerKey) {
    appendMessage("system", "Retriever warmup completed.", { prefix: "" });
  } else if (status === "failed") {
    appendMessage("system", "Retriever warmup failed, the system will keep using the current setup.", { prefix: "" });
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

function stopUploadTaskPolling() {
  if (state.uploadTaskPollTimer) {
    window.clearInterval(state.uploadTaskPollTimer);
    state.uploadTaskPollTimer = null;
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

  uploadButton.textContent = isUploading ? "Stop Upload" : "Upload";
  askButton.disabled = isUploading;
  uploadInput.disabled = isUploading;
}

function setAskUI(isAsking) {
  state.isAsking = isAsking;
  const uploadButton = document.getElementById("uploadButton");
  const askButton = document.getElementById("askButton");
  const questionInput = document.getElementById("questionInput");

  askButton.textContent = isAsking ? "Stop Asking" : "Send";
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
        prefix: item.role === "assistant" ? "Answer: " : item.role === "user" ? "Question: " : "System: ",
      });
    });
  } catch (error) {
    appendMessage("system", `Failed to load session history: ${error.message}`);
  }
}

function renderUploadTaskStatus(taskStatus) {
  if (!taskStatus) {
    return;
  }

  const progress = `${taskStatus.processed_files || 0}/${taskStatus.total_files || 0}`;
  const bannerKey = [
    taskStatus.task_id,
    taskStatus.status,
    taskStatus.current_step,
    taskStatus.current_file,
    taskStatus.message,
    progress,
    taskStatus.error || "",
  ].join(":");

  if (bannerKey === state.lastUploadTaskBannerKey) {
    return;
  }

  if (taskStatus.status === "processing") {
    appendMessage(
      "system",
      `${taskStatus.message} Progress: ${progress}${taskStatus.current_file ? `, file: ${taskStatus.current_file}` : ""}`,
    );
  } else if (taskStatus.status === "success") {
    if (taskStatus.chunk_count > 0) {
      appendMessage("system", `${taskStatus.message} Parsed ${taskStatus.chunk_count} chunks.`);
    } else {
      const warning = taskStatus.warnings?.[0] || "No searchable content was extracted.";
      appendMessage("system", `${taskStatus.message} ${warning}`);
    }
  } else if (taskStatus.status === "failed") {
    appendMessage(
      "system",
      `${taskStatus.message}${taskStatus.error ? ` Error: ${taskStatus.error}` : ""}`,
    );
  }

  state.lastUploadTaskBannerKey = bannerKey;
}

async function loadUploadTaskStatus(taskId) {
  const taskStatus = await fetchJSON(`/api/document/tasks/${taskId}`);
  renderUploadTaskStatus(taskStatus);

  if (taskStatus.status === "success" || taskStatus.status === "failed") {
    stopUploadTaskPolling();
    state.activeUploadTaskId = "";
    if (taskStatus.status === "success") {
      await loadStatus();
      await loadWarmupStatus();
    }
    setUploadUI(false);
  }

  return taskStatus;
}

function startUploadTaskPolling(taskId) {
  stopUploadTaskPolling();
  state.activeUploadTaskId = taskId;
  state.lastUploadTaskBannerKey = "";
  state.uploadTaskPollTimer = window.setInterval(() => {
    loadUploadTaskStatus(taskId).catch((error) => {
      appendMessage("system", `Task polling failed: ${error.message}`);
      stopUploadTaskPolling();
      state.activeUploadTaskId = "";
      setUploadUI(false);
    });
  }, 1500);
}

async function uploadDocument() {
  const input = document.getElementById("uploadInput");
  const files = Array.from(input.files || []);

  if (state.isUploading && state.activeUploadController) {
    state.activeUploadController.abort();
    return;
  }

  if (!files.length) {
    appendMessage("system", "Please select at least one PDF file.");
    return;
  }

  const controller = new AbortController();
  state.activeUploadController = controller;
  setUploadUI(true);
  appendMessage("system", `Starting upload for ${files.length} PDF file(s).`);

  try {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));

    const result = await fetchJSON("/api/document/upload", {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });

    input.value = "";
    document.getElementById("uploadFileLabel").textContent = "Upload";
    appendMessage("system", `${result.message} Task ID: ${result.task_id}`);

    const taskStatus = await loadUploadTaskStatus(result.task_id);
    if (taskStatus.status === "processing") {
      startUploadTaskPolling(result.task_id);
    }
  } catch (error) {
    if (error.name === "AbortError") {
      appendMessage("system", "Upload stopped.");
    } else {
      appendMessage("system", `Upload failed: ${error.message}`);
    }
    setUploadUI(false);
  } finally {
    state.activeUploadController = null;
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
    const warning = state.documentStatus?.warnings?.[0] || "There are no searchable document chunks right now.";
    appendMessage("system", `Cannot search yet. ${warning}`);
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
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";

      for (const event of events) {
        const line = event.split("\n").find((item) => item.startsWith("data: "));
        if (!line) continue;

        const payload = JSON.parse(line.slice(6));
        if (payload.type === "status") {
          appendMessage("system", "Processing your question...");
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
          appendMessage("system", payload.message || "Request failed.");
        }
      }
    }
  } catch (error) {
    if (error.name === "AbortError") {
      appendMessage("system", "Request stopped.");
    } else {
      appendMessage("system", `Request failed: ${error.message}`);
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
    const label =
      files.length === 0
        ? "Upload"
        : files.length === 1
          ? files[0].name
          : `${files.length} files selected`;
    document.getElementById("uploadFileLabel").textContent = label;
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
  appendMessage("system", `Initialization failed: ${error.message}`);
});
