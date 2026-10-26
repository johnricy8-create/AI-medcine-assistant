(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = {
    taskId: null,
    eventSource: null,
    result: null,
    evidenceById: new Map(),
    busy: false,
  };

  const STATUS_TEXT = {
    planned: "已创建",
    running: "运行中",
    completed: "已完成",
    no_evidence: "无足够证据",
    blocked: "已拦截",
    budget_exhausted: "预算耗尽",
    failed: "失败",
    pending_review: "待评审",
  };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function setText(id, value) {
    const node = $(id);
    if (node) node.textContent = value ?? "";
  }

  function showError(message) {
    const node = $("form-error");
    if (!node) return;
    node.textContent = message || "";
    node.hidden = !message;
  }

  function setTaskStatus(status) {
    const node = $("task-status");
    const text = STATUS_TEXT[status] || status || "未知";
    node.textContent = text;
    node.className = "task-status" +
      (status === "running" ? " running" : "") +
      (["completed", "no_evidence"].includes(status) ? " done" : "") +
      (["blocked", "failed", "budget_exhausted", "rejected"].includes(status) ? " bad" : "");
  }

  function setBusy(busy) {
    state.busy = busy;
    const button = $("run-btn");
    if (button) {
      button.disabled = busy;
      button.textContent = busy ? "研究进行中…" : "开始研究";
    }
  }

  async function api(path, options = {}) {
    const headers = Object.assign(
      { "Content-Type": "application/json" },
      options.headers || {}
    );
    headers["X-User-Id"] = $("user-select").value;
    const response = await fetch(path, Object.assign({}, options, { headers }));
    let data = null;
    try { data = await response.json(); } catch (err) { data = null; }
    if (!response.ok) {
      const detail = data && (data.detail || data.error || data.message);
      const error = new Error(detail || `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async function refreshHealth() {
    const pill = $("health-pill");
    const modelPill = $("model-pill");
    const indexPill = $("index-pill");
    try {
      const data = await api("/api/health");
      const ready = data.services_ready !== false;
      pill.textContent = ready ? "服务就绪" : "服务未就绪";
      pill.className = "pill" + (ready ? "" : " warn");
      modelPill.textContent = data.llm_model || "LLM 未配置";
      modelPill.className = "pill subtle" + (data.llm_configured ? "" : " warn");
      indexPill.textContent = data.index_available
        ? `索引 ${data.index_chunk_count || 0} chunks`
        : "索引未建立";
      indexPill.className = "pill subtle" + (data.index_available ? "" : " warn");
    } catch (error) {
      pill.textContent = "服务异常";
      pill.className = "pill bad";
    }
  }

  async function refreshStats() {
    try {
      const data = await api("/api/knowledge/stats");
      setText("index-pill", `索引 ${data.chunk_count || 0} chunks`);
      const pill = $("index-pill");
      pill.className = "pill subtle" + (data.chunk_count ? "" : " warn");
    } catch (error) {
      /* health already reports the main state */
    }
  }

  async function loadProjects() {
    try {
      const projects = await api("/api/projects");
      const select = $("project-select");
      if (!select || !Array.isArray(projects) || !projects.length) return;
      const current = select.value;
      select.replaceChildren();
      projects.forEach((project) => {
        const option = el("option", "", `${project.project_id}${project.name ? " · " + project.name : ""}`);
        option.value = project.project_id;
        select.appendChild(option);
      });
      if (projects.some((project) => project.project_id === current)) {
        select.value = current;
      }
    } catch (error) {
      /* keep static options */
    }
  }

  function formatTime(value) {
    if (!value) return "--:--:--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "--:--:--";
    return date.toLocaleTimeString("zh-CN", { hour12: false });
  }

  function addTimeline(event) {
    const list = $("timeline");
    if (!list) return;
    if (list.children.length === 1 && list.firstElementChild.classList.contains("muted")) {
      list.replaceChildren();
    }
    const item = el("li", event.event_type === "error" || event.event_type === "failed" ? "error"
      : event.event_type === "warning" ? "warning" : "");
    item.appendChild(el("span", "t", formatTime(event.created_at)));
    const body = el("div");
    const node = el("span", "node", event.node || "node");
    body.appendChild(node);
    body.appendChild(document.createTextNode(" "));
    body.appendChild(el("span", "msg", event.message || event.event_type || ""));
    item.appendChild(body);
    list.appendChild(item);
    while (list.children.length > 40) list.removeChild(list.firstElementChild);
    list.scrollTop = list.scrollHeight;
  }

  function clearTimeline() {
    const list = $("timeline");
    if (list) list.replaceChildren(el("li", "muted", "等待任务…"));
  }

  async function runTask() {
    if (state.busy) return;
    const question = $("question").value.trim();
    if (!question) {
      showError("请先输入研究问题。");
      return;
    }
    showError("");
    setBusy(true);
    setTaskStatus("running");
    $("empty-state").hidden = false;
    $("result-content").hidden = true;
    setText("result-meta", "");
    clearTimeline();
    closeEvents();

    try {
      const data = await api("/api/research/tasks", {
        method: "POST",
        body: JSON.stringify({
          project_id: $("project-select").value,
          question,
          sources: ["literature", "patent", "eln", "report", "omics", "trial"],
          require_human_review: true,
        }),
      });
      state.taskId = data.task_id;
      setText("result-meta", `任务 ${data.task_id} · ${formatTime(new Date().toISOString())}`);
      subscribe(data.task_id);
    } catch (error) {
      setBusy(false);
      setTaskStatus("failed");
      showError(error.message);
    }
  }

  function closeEvents() {
    if (state.eventSource) {
      state.eventSource.close();
      state.eventSource = null;
    }
  }

  function subscribe(taskId) {
    closeEvents();
    const source = new EventSource(`/api/research/tasks/${taskId}/events?after=0`);
    state.eventSource = source;

    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        addTimeline(data);
      } catch (error) {
        /* ignore malformed event */
      }
    };

    source.addEventListener("done", () => {
      closeEvents();
      fetchResult(taskId, 0);
    });

    source.onerror = () => {
      closeEvents();
      // SSE 断线时用状态轮询兜底
      pollStatus(taskId, 0);
    };
  }

  async function pollStatus(taskId, attempts) {
    if (attempts > 240) {
      setBusy(false);
      setTaskStatus("failed");
      showError("任务状态轮询超时，请查看服务日志。");
      return;
    }
    try {
      const data = await api(`/api/research/tasks/${taskId}`);
      setTaskStatus(data.status);
      addTimeline({
        node: "poll",
        event_type: "info",
        message: `状态：${STATUS_TEXT[data.status] || data.status}`,
        created_at: new Date().toISOString(),
      });
      if (["completed", "no_evidence", "blocked", "failed", "budget_exhausted", "rejected"].includes(data.status)) {
        fetchResult(taskId, 0);
        return;
      }
    } catch (error) {
      /* keep polling */
    }
    setTimeout(() => pollStatus(taskId, attempts + 1), 1200);
  }

  async function fetchResult(taskId, attempts) {
    if (attempts > 30) {
      setBusy(false);
      showError("结果获取超时，请刷新页面或查看任务日志。");
      return;
    }
    try {
      const response = await fetch(`/api/research/tasks/${taskId}/result`, {
        headers: { "X-User-Id": $("user-select").value },
      });
      if (response.status === 202) {
        setTimeout(() => fetchResult(taskId, attempts + 1), 1000);
        return;
      }
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${response.status}`);
      }
      const data = await response.json();
      state.result = data;
      setTaskStatus(data.status);
      renderResult(data);
      setBusy(false);
      refreshStats();
    } catch (error) {
      if (attempts < 5) {
        setTimeout(() => fetchResult(taskId, attempts + 1), 1200);
      } else {
        setBusy(false);
        showError(error.message);
      }
    }
  }

  function levelBadge(level) {
    const normalized = (level || "unknown").toString().toUpperCase();
    const badge = el("span", `badge level-${normalized === "A" || normalized === "B" || normalized === "C" || normalized === "D" ? normalized : "unknown"}`, `等级 ${normalized}`);
    return badge;
  }

  function stanceBadge(stance) {
    const value = (stance || "neutral").toString();
    const label = value === "support" ? "支持" : value === "contradict" ? "反例" : "中性";
    return el("span", `badge ${value}`, label);
  }

  function citationChip(id, type) {
    const chip = el("button", "citation", `${type === "contradict" ? "反例" : type === "support" ? "支持" : ""} ${id}`);
    chip.type = "button";
    chip.title = id;
    chip.addEventListener("click", () => focusEvidence(id));
    return chip;
  }

  function focusEvidence(id) {
    const card = document.querySelector(`[data-evidence-id="${CSS.escape(id)}"]`);
    if (!card) return;
    card.classList.add("expanded");
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.animate(
      [{ boxShadow: "0 0 0 0 rgba(15,107,92,.35)" }, { boxShadow: "0 0 0 8px rgba(15,107,92,0)" }],
      { duration: 900 }
    );
  }

  function renderResult(data) {
    $("empty-state").hidden = true;
    $("result-content").hidden = false;
    setText("assessment", data.assessment || "证据不足，未形成明确判断。");
    setText(
      "result-meta",
      `${STATUS_TEXT[data.status] || data.status} · ${(data.evidence || []).length} 条证据 · ${data.llm_used ? "LLM 综合" : "规则兜底"}`
    );

    const claims = Array.isArray(data.claims) ? data.claims : [];
    const claimBox = $("claims");
    claimBox.replaceChildren();
    if (!claims.length) {
      claimBox.appendChild(el("p", "muted", "未形成通过引用/ACL 校验的 claim。"));
    } else {
      claims.forEach((claim) => claimBox.appendChild(renderClaim(claim)));
    }
    setText("claims-count", `${claims.length} 条`);

    const conflicts = Array.isArray(data.conflicts) ? data.conflicts : [];
    const conflictBox = $("conflicts");
    conflictBox.replaceChildren();
    if (!conflicts.length) {
      conflictBox.appendChild(el("p", "muted", "未自动识别到冲突；不等于没有反例，需继续检索。"));
    } else {
      conflicts.forEach((conflict) => conflictBox.appendChild(renderConflict(conflict)));
    }
    setText("conflicts-count", `${conflicts.length} 条`);

    const internal = Array.isArray(data.internal_evidence) ? data.internal_evidence : [];
    const internalBox = $("internal-evidence");
    internalBox.replaceChildren();
    if (!internal.length) {
      internalBox.appendChild(el("p", "muted", "当前可见范围内没有内部 ELN 证据。"));
    } else {
      internal.slice(0, 10).forEach((item) => internalBox.appendChild(renderInternal(item)));
    }
    setText("internal-count", `${internal.length} 条`);

    const gaps = $("gaps");
    gaps.replaceChildren();
    (data.gaps || []).forEach((gap) => gaps.appendChild(el("li", "", gap)));
    if (!(data.gaps || []).length) gaps.appendChild(el("li", "muted", "未自动识别到缺口。"));

    const steps = $("next-steps");
    steps.replaceChildren();
    (data.suggested_next_steps || []).forEach((step) => steps.appendChild(el("li", "", step)));
    if (!(data.suggested_next_steps || []).length) steps.appendChild(el("li", "muted", "由科学家决定验证顺序。"));

    setText("report-md", data.report_md || "");
    renderEvidence(data.evidence || []);
  }

  function renderClaim(claim) {
    const stance = (claim.stance || "neutral").toString();
    const card = el("article", `claim ${stance}`);
    const head = el("div", "claim-head");
    head.appendChild(stanceBadge(stance));
    head.appendChild(levelBadge(claim.level));
    if (claim.verified === false) {
      head.appendChild(el("span", "badge level-D", "未通过校验"));
    }
    card.appendChild(head);
    card.appendChild(el("p", "claim-text", claim.text || ""));
    const citations = el("div", "citations");
    (claim.support_ids || []).forEach((id) => citations.appendChild(citationChip(id, "support")));
    (claim.contradict_ids || []).forEach((id) => citations.appendChild(citationChip(id, "contradict")));
    if (citations.children.length) card.appendChild(citations);
    if ((claim.caveats || []).length) {
      card.appendChild(el("p", "caveat", `限制：${claim.caveats.join("；")}`));
    }
    if (state.taskId) {
      const actions = el("div", "claim-actions");
      [
        ["accept", "接受"],
        ["accept_with_revision", "修订后接受"],
        ["reject", "驳回"],
      ].forEach(([action, label]) => {
        const button = el("button", "mini", label);
        button.type = "button";
        button.addEventListener("click", () => reviewClaim(claim.claim_id, action));
        actions.appendChild(button);
      });
      card.appendChild(actions);
    }
    return card;
  }

  async function reviewClaim(claimId, action) {
    if (!state.taskId || state.busy) return;
    let comment = "";
    if (action !== "accept") {
      comment = window.prompt(
        action === "reject" ? "请填写驳回理由：" : "请填写修订说明：",
        ""
      ) || "";
      if (action === "reject" && !comment) return;
    }
    setBusy(true);
    try {
      await api(`/api/research/tasks/${state.taskId}/review`, {
        method: "POST",
        body: JSON.stringify({
          reviewer_id: $("user-select").value,
          claim_id: claimId,
          action,
          comment,
        }),
      });
      await fetchResult(state.taskId, 0);
      addTimeline({
        node: "review",
        event_type: "info",
        message: `claim ${claimId} · ${action}`,
        created_at: new Date().toISOString(),
      });
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(false);
    }
  }

  function renderConflict(conflict) {
    const card = el("div", "conflict");
    card.appendChild(el("strong", "", conflict.topic || "证据冲突"));
    const line = el("div", "citations");
    (conflict.support_ids || []).forEach((id) => line.appendChild(citationChip(id, "support")));
    (conflict.contradict_ids || []).forEach((id) => line.appendChild(citationChip(id, "contradict")));
    card.appendChild(line);
    card.appendChild(el("p", "", conflict.explanation || "需核对物种、方法和实验条件。"));
    return card;
  }

  function renderInternal(item) {
    const card = el("div", "internal");
    const id = item.locator && item.locator.experiment_id
      ? item.locator.experiment_id
      : item.source_id;
    const head = el("div", "claim-head");
    head.appendChild(el("span", "id", id || "ELN"));
    head.appendChild(levelBadge(item.level));
    head.appendChild(el("span", "badge source", item.species || "unknown"));
    card.appendChild(head);
    card.appendChild(el("p", "evidence-quote", item.quote || ""));
    return card;
  }

  function renderEvidence(evidence) {
    state.evidenceById.clear();
    const list = $("evidence-list");
    list.replaceChildren();
    if (!evidence.length) {
      list.appendChild(el("p", "muted", "没有合格证据。"));
      setText("evidence-count", "0");
      return;
    }
    evidence.forEach((item) => {
      state.evidenceById.set(item.evidence_id, item);
      const card = el("article", "evidence-card");
      card.dataset.evidenceId = item.evidence_id;
      const head = el("div", "evidence-head");
      head.appendChild(el("span", "badge source", item.source_type || "source"));
      head.appendChild(levelBadge(item.level));
      if (item.acl_scope && item.acl_scope !== "public") {
        head.appendChild(el("span", "badge acl", "项目"));
      }
      card.appendChild(head);
      card.appendChild(el("div", "evidence-title", item.title || item.source_id || "证据"));
      const section = item.locator && item.locator.section ? item.locator.section : "";
      card.appendChild(el("div", "evidence-meta", `${item.source_id || ""}${section ? " · " + section : ""}`));
      card.appendChild(el("p", "evidence-quote", item.quote || ""));
      card.addEventListener("click", () => card.classList.toggle("expanded"));
      list.appendChild(card);
    });
    setText("evidence-count", String(evidence.length));
  }

  async function rebuildIndex() {
    if (state.busy) return;
    if (!window.confirm("这会重建 Chroma + BM25 索引，可能需要数分钟。继续？")) return;
    setBusy(true);
    showError("");
    setTaskStatus("running");
    try {
      const data = await api("/api/knowledge/rebuild", { method: "POST" });
      setTaskStatus("completed");
      setText("result-meta", `索引重建完成：${data.chunk_count || 0} chunks`);
      await refreshHealth();
      await refreshStats();
    } catch (error) {
      setTaskStatus("failed");
      showError(error.message);
    } finally {
      setBusy(false);
    }
  }

  function bind() {
    $("run-btn").addEventListener("click", runTask);
    $("rebuild-btn").addEventListener("click", rebuildIndex);
    $("question").addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") runTask();
    });
    document.querySelectorAll(".example").forEach((button) => {
      button.addEventListener("click", () => {
        $("question").value = button.dataset.question || "";
        $("question").focus();
      });
    });
    $("user-select").addEventListener("change", () => {
      refreshHealth();
    });
    $("project-select").addEventListener("change", () => {
      /* project is sent with the next task */
    });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    bind();
    await Promise.allSettled([refreshHealth(), refreshStats(), loadProjects()]);
    const taskId = new URLSearchParams(window.location.search).get("task");
    if (taskId) {
      state.taskId = taskId;
      setBusy(true);
      addTimeline({
        node: "page",
        event_type: "info",
        message: `加载历史任务 ${taskId}`,
        created_at: new Date().toISOString(),
      });
      fetchResult(taskId, 0);
    }
  });
})();
