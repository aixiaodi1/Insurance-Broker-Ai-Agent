const uploadForm = document.querySelector("#upload-form");
const uploadResult = document.querySelector("#upload-result");
const jobList = document.querySelector("#job-list");
const documentList = document.querySelector("#document-list");
const refreshDocumentsButton = document.querySelector("#refresh-documents");

const terminalStatuses = new Set(["succeeded", "failed"]);
const activePolls = new Map();

function renderJson(target, value) {
  target.textContent = JSON.stringify(value, null, 2);
}

function item(title, meta, status) {
  const row = document.createElement("div");
  row.className = "item";

  const heading = document.createElement("p");
  heading.className = `item-title status-${status || "unknown"}`;
  heading.textContent = title;

  const details = document.createElement("p");
  details.className = "meta";
  details.textContent = meta;

  row.append(heading, details);
  return row;
}

function renderJob(job) {
  const jobId = job.job_id || job.id;
  const title = `${jobId} · ${job.status || "unknown"} · ${job.progress ?? 0}%`;
  const meta = `文档: ${job.document_id || "-"} · 阶段: ${job.stage || "-"}${job.error ? ` · 错误: ${job.error}` : ""}`;
  const existing = document.querySelector(`[data-job-id="${CSS.escape(jobId)}"]`);
  const row = item(title, meta, job.status);
  row.dataset.jobId = jobId;

  if (existing) {
    existing.replaceWith(row);
    return;
  }

  if (jobList.textContent.trim() === "暂无任务。") {
    jobList.textContent = "";
  }
  jobList.prepend(row);
}

async function refreshDocuments() {
  documentList.textContent = "正在加载文档...";
  try {
    const response = await fetch(documentList.dataset.documentsEndpoint);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "文档列表加载失败");
    }

    documentList.textContent = "";
    const documents = data.documents || [];
    if (documents.length === 0) {
      documentList.textContent = "暂无文档。";
      return;
    }

    for (const documentRecord of documents) {
      const documentId = documentRecord.document_id || documentRecord.id || "-";
      const title = `${documentRecord.filename} · ${documentRecord.status}`;
      const meta = `ID: ${documentId} · Collection: ${documentRecord.collection} · 分块: ${documentRecord.chunk_count ?? 0}`;
      documentList.append(item(title, meta, documentRecord.status));
    }
  } catch (error) {
    documentList.textContent = `加载失败: ${error.message}`;
  }
}

async function pollJob(jobId) {
  if (!jobId || activePolls.has(jobId)) {
    return;
  }

  const poll = window.setInterval(async () => {
    try {
      const response = await fetch(`${jobList.dataset.jobEndpoint}${encodeURIComponent(jobId)}`);
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "任务查询失败");
      }

      renderJob(data);
      if (terminalStatuses.has(data.status)) {
        window.clearInterval(poll);
        activePolls.delete(jobId);
        await refreshDocuments();
      }
    } catch (error) {
      renderJob({ job_id: jobId, status: "failed", progress: 0, error: error.message });
      window.clearInterval(poll);
      activePolls.delete(jobId);
    }
  }, 1800);

  activePolls.set(jobId, poll);
}

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitButton = uploadForm.querySelector("button[type='submit']");
  submitButton.disabled = true;
  uploadResult.textContent = "正在上传...";

  try {
    const response = await fetch(uploadForm.action, {
      method: "POST",
      body: new FormData(uploadForm),
    });
    const data = await response.json();
    renderJson(uploadResult, data);

    if (!response.ok) {
      throw new Error(data.detail || "上传失败");
    }

    for (const job of data.jobs || []) {
      const jobId = job.job_id || job.id;
      renderJob({ ...job, job_id: jobId });
      pollJob(jobId);
    }
    await refreshDocuments();
  } catch (error) {
    uploadResult.textContent = `上传失败: ${error.message}`;
  } finally {
    submitButton.disabled = false;
  }
});

refreshDocumentsButton.addEventListener("click", refreshDocuments);
refreshDocuments();

const collectionList = document.querySelector("#collection-list");
const refreshCollectionsButton = document.querySelector("#refresh-collections");
const deleteAllButton = document.querySelector("#delete-all-vectors");

function renderCollectionItem(name) {
  const row = document.createElement("div");
  row.className = "item item-row";

  const title = document.createElement("p");
  title.className = "item-title";
  title.textContent = name;

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "danger-small";
  deleteBtn.textContent = "删除";
  deleteBtn.addEventListener("click", async () => {
    if (!window.confirm(`确认删除向量库「${name}」？此操作不可恢复。`)) return;
    deleteBtn.disabled = true;
    deleteBtn.textContent = "删除中...";
    try {
      const resp = await fetch(`/collections/${encodeURIComponent(name)}`, { method: "DELETE" });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "删除失败");
      await refreshCollections();
    } catch (err) {
      alert(`删除失败: ${err.message}`);
      deleteBtn.disabled = false;
      deleteBtn.textContent = "删除";
    }
  });

  row.append(title, deleteBtn);
  return row;
}

async function refreshCollections() {
  collectionList.textContent = "正在加载...";
  try {
    const resp = await fetch(collectionList.dataset.collectionsEndpoint);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "加载失败");
    collectionList.textContent = "";
    const collections = data.collections || [];
    if (collections.length === 0) {
      collectionList.textContent = "暂无向量库。";
      return;
    }
    for (const name of collections) {
      collectionList.append(renderCollectionItem(name));
    }
  } catch (err) {
    collectionList.textContent = `加载失败: ${err.message}`;
  }
}

refreshCollectionsButton.addEventListener("click", refreshCollections);
refreshCollections();

deleteAllButton.addEventListener("click", async () => {
  let collections = [];
  try {
    const resp = await fetch(collectionList.dataset.collectionsEndpoint);
    const data = await resp.json();
    collections = data.collections || [];
  } catch {
    alert("无法获取向量库列表");
    return;
  }
  if (collections.length === 0) {
    alert("没有可删除的向量库。");
    return;
  }
  if (!window.confirm(`确认删除全部 ${collections.length} 个向量库？\n${collections.join(", ")}\n\n此操作不可恢复！`)) return;

  deleteAllButton.disabled = true;
  deleteAllButton.textContent = "删除中...";
  let deleted = 0;
  for (const name of collections) {
    try {
      const resp = await fetch(`/collections/${encodeURIComponent(name)}`, { method: "DELETE" });
      if (resp.ok) deleted++;
    } catch {}
  }
  deleteAllButton.disabled = false;
  deleteAllButton.textContent = "删除全部向量内容";
  alert(`已删除 ${deleted}/${collections.length} 个向量库。`);
  await refreshCollections();
});

/* ── RAG 调试台 ── */
const debugForm = document.querySelector("#debug-query-form");
const debugInput = document.querySelector("#debug-query");
const debugResponse = document.querySelector("#debug-response");
const debugEvidence = document.querySelector("#debug-evidence");
const debugEvidenceContent = document.querySelector("#debug-evidence-content");
const debugEndpointToggle = document.querySelector("#debug-endpoint-toggle");
const debugNodes = document.querySelector("#debug-nodes");
const debugEvents = document.querySelector("#debug-events");
const debugTools = document.querySelector("#debug-tools");
const debugVectors = document.querySelector("#debug-vectors");
const debugRequestJson = document.querySelector("#debug-request-json");
const debugResponseJson = document.querySelector("#debug-response-json");
const debugNodeCount = document.querySelector("#debug-node-count");
const debugEventCount = document.querySelector("#debug-event-count");
const debugToolCount = document.querySelector("#debug-tool-count");
const debugVectorCount = document.querySelector("#debug-vector-count");

let debugEndpoint = debugForm.dataset.debugEndpoint || "/agent/run_v2";

debugEndpointToggle.addEventListener("click", () => {
  debugEndpoint = debugEndpoint === "/agent/run" ? "/agent/run_v2" : "/agent/run";
  debugEndpointToggle.textContent = debugEndpoint === "/agent/run_v2" ? "端点：新版 Agent" : "端点：经典 RAG";
});

function setText(target, value) {
  target.textContent = value;
}

function clearElement(target, fallbackText) {
  target.textContent = fallbackText;
}

function debugCard(title, detail, meta) {
  const row = document.createElement("article");
  row.className = "debug-item";

  const heading = document.createElement("strong");
  heading.textContent = title || "-";
  row.append(heading);

  if (detail) {
    const body = document.createElement("p");
    body.textContent = detail;
    row.append(body);
  }

  if (meta) {
    const foot = document.createElement("small");
    foot.textContent = meta;
    row.append(foot);
  }

  return row;
}

function statusText(status) {
  const labels = {
    idle: "空闲",
    pending: "等待",
    running: "运行",
    succeeded: "成功",
    failed: "失败",
  };
  return labels[status] || status || "-";
}

function renderDebugNodes(nodes) {
  debugNodes.textContent = "";
  debugNodeCount.textContent = String(nodes.length);
  if (!nodes.length) {
    clearElement(debugNodes, "暂无节点。");
    return;
  }

  nodes.forEach((node, index) => {
    const title = `${index + 1}. ${node.label || node.id || "未命名节点"} · ${statusText(node.status)}`;
    const detail = node.stateSummary || node.detail || "";
    const meta = `节点：${node.id || "-"} · 耗时：${node.durationMs ?? 0} 毫秒`;
    debugNodes.append(debugCard(title, detail, meta));
  });
}

function renderDebugEvents(events) {
  debugEvents.textContent = "";
  debugEventCount.textContent = String(events.length);
  if (!events.length) {
    clearElement(debugEvents, "暂无事件。");
    return;
  }

  events.forEach((event, index) => {
    const title = `${index + 1}. ${event.title || event.type || "事件"}`;
    const detail = event.detail || "";
    const meta = `节点：${event.nodeId || "-"} · 类型：${event.type || "-"} · 时间：${event.timestamp || "-"}`;
    debugEvents.append(debugCard(title, detail, meta));
  });
}

function renderDebugToolCalls(toolCalls) {
  debugTools.textContent = "";
  debugToolCount.textContent = String(toolCalls.length);
  if (!toolCalls.length) {
    clearElement(debugTools, "暂无工具调用。");
    return;
  }

  toolCalls.forEach((toolCall, index) => {
    const title = `${index + 1}. ${toolCall.name || "工具"} · ${statusText(toolCall.status)}`;
    const detail = toolCall.resultPreview || "";
    const meta = `节点：${toolCall.nodeId || "-"} · 耗时：${toolCall.durationMs ?? 0} 毫秒`;
    debugTools.append(debugCard(title, detail, meta));
  });
}

function renderDebugVectorMatches(vectorMatches) {
  debugVectors.textContent = "";
  debugVectorCount.textContent = String(vectorMatches.length);
  if (!vectorMatches.length) {
    clearElement(debugVectors, "暂无向量命中。");
    return;
  }

  vectorMatches.forEach((match, index) => {
    const score = typeof match.score === "number" ? match.score.toFixed(4) : "无分数";
    const title = `${index + 1}. ${match.title || "知识片段"}`;
    const detail = match.contentPreview || "";
    const meta = `集合：${match.collection || "-"} · 来源：${match.provider || "-"} · 分数：${score}`;
    debugVectors.append(debugCard(title, detail, meta));
  });
}

function renderDebugRunDetails(data) {
  const nodes = Array.isArray(data.nodes) ? data.nodes : [];
  const events = Array.isArray(data.events) ? data.events : [];
  const toolCalls = Array.isArray(data.toolCalls) ? data.toolCalls : [];
  const vectorMatches = Array.isArray(data.vectorMatches) ? data.vectorMatches : [];

  renderDebugNodes(nodes);
  renderDebugEvents(events);
  renderDebugToolCalls(toolCalls);
  renderDebugVectorMatches(vectorMatches);
  setText(debugRequestJson, JSON.stringify(data.requestJson || {}, null, 2));
  setText(debugResponseJson, JSON.stringify(data.responseJson || data, null, 2));
}

function resetDebugRunDetails(message) {
  debugNodeCount.textContent = "0";
  debugEventCount.textContent = "0";
  debugToolCount.textContent = "0";
  debugVectorCount.textContent = "0";
  clearElement(debugNodes, message);
  clearElement(debugEvents, message);
  clearElement(debugTools, message);
  clearElement(debugVectors, message);
  clearElement(debugRequestJson, message);
  clearElement(debugResponseJson, message);
}

function renderEvidenceTag(status) {
  if (status === "valid") return '<span class="evidence-tag tag-valid">有效</span>';
  if (status === "warning") return '<span class="evidence-tag tag-warning">警告</span>';
  return '<span class="evidence-tag tag-danger">异常</span>';
}

function renderDebugEvidence(data) {
  if (!data) return "";
  let html = "";

  if (data.retrievalDebug) {
    const rd = data.retrievalDebug;
    html += `<div class="evidence-section">
      <h4>检索计划</h4>
      <pre>Intent: ${rd.intent || "-"}
扩展查询: ${JSON.stringify(rd.expandedQueries || [])}
最终上下文数: ${rd.finalContextCount || 0}</pre>
    </div>`;

    if (rd.finalContextSections && rd.finalContextSections.length > 0) {
      html += `<div class="evidence-section">
        <h4>最终上下文条款</h4>`;
      for (const ctx of rd.finalContextSections) {
        html += `<pre>ID: ${ctx.id || "-"} | ${ctx.sectionTitle || "无标题"} (${ctx.contentType || "未知类型"}) RRF: ${ctx.rrfScore != null ? ctx.rrfScore.toFixed(4) : "-"}</pre>`;
      }
      html += `</div>`;
    }
  }

  if (data.intent) {
    html += `<div class="evidence-section">
      <h4>意图分类</h4>
      <pre>意图: ${data.intent} ${renderEvidenceTag("valid")}
扩展查询: ${JSON.stringify(data.expandedQueries || [])}</pre>
    </div>`;
  }

  if (data.events) {
    const citationEvent = data.events.find(e => e.nodeId === "verify_citations");
    if (citationEvent && citationEvent.payload) {
      const p = citationEvent.payload;
      html += `<div class="evidence-section">
        <h4>引用验证</h4>
        <pre>有效引用: [${(p.validCitationIds || []).join(", ")}] ${p.missingCitations ? renderEvidenceTag("danger") : renderEvidenceTag("valid")}
无效引用: [${(p.invalidCitationIds || []).join(", ")}] ${p.invalidCitationIds.length > 0 ? renderEvidenceTag("danger") : renderEvidenceTag("valid")}</pre>
      </div>`;

      if (p.numberDetails && p.numberDetails.length > 0) {
        html += `<div class="evidence-section">
          <h4>数字校验</h4>`;
        for (const nd of p.numberDetails) {
          const tag = nd.found_in_evidence ? renderEvidenceTag("valid") : renderEvidenceTag("danger");
          html += `<pre>数字 "${nd.number}": ${nd.found_in_evidence ? "证据中存在" : "证据中不存在"} ${tag}</pre>`;
        }
        html += `</div>`;
      }

      if (p.evidenceWarnings && p.evidenceWarnings.length > 0) {
        html += `<div class="evidence-section">
          <h4>证据完整性警告</h4>`;
        for (const w of p.evidenceWarnings) {
          html += `<pre>${w} ${renderEvidenceTag("warning")}</pre>`;
        }
        html += `</div>`;
      }

      if (p.contextTypesPresent && p.contextTypesPresent.length > 0) {
        html += `<div class="evidence-section">
          <h4>上下文类型</h4>
          <pre>${p.contextTypesPresent.join(", ")}</pre>
        </div>`;
      }
    }

    const rrfEvent = data.events.find(e => e.nodeId === "fuse_retrieval");
    if (rrfEvent && rrfEvent.payload && rrfEvent.payload.rrfTopK) {
      html += `<div class="evidence-section">
        <h4>RRF 融合排序 (Top ${rrfEvent.payload.rrfTopK.length})</h4>`;
      for (const item of rrfEvent.payload.rrfTopK) {
        const debug = item.rrf_debug || {};
        html += `<pre>ID: ${item.id || "-"} | RRF: ${item.rrf_score != null ? item.rrf_score.toFixed(4) : "-"}
  向量排名: ${debug.vector_rank != null ? debug.vector_rank : "-"} | BM25排名: ${debug.bm25_rank != null ? debug.bm25_rank : "-"} | 专题BM25排名: ${debug.section_bm25_rank != null ? debug.section_bm25_rank : "-"}</pre>`;
      }
      html += `</div>`;
    }
  }

  html += `<div class="evidence-section">
    <h4>完整响应 JSON</h4>
    <pre>${JSON.stringify(data, null, 2)}</pre>
  </div>`;

  return html;
}

debugForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = debugInput.value.trim();
  if (!query) return;

  const submitButton = debugForm.querySelector("button[type='submit']");
  submitButton.disabled = true;
  debugResponse.textContent = "正在查询...";
  debugEvidence.style.display = "none";
  resetDebugRunDetails("正在查询...");

  try {
    const requestBody = {
      prompt: query,
      collection: document.querySelector("#collection")?.value || "default",
      agentId: "debug-agent",
      threadId: `admin_${Date.now()}`,
      vectorProvider: "chroma",
      debug: true,
    };
    if (debugEndpoint === "/agent/run_v2") {
      requestBody.userId = "admin";
      requestBody.collectedVars = {};
    }

    debugRequestJson.textContent = JSON.stringify(requestBody, null, 2);

    const response = await fetch(debugEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });
    const data = await response.json();
    debugResponse.textContent = data.finalAnswer || JSON.stringify(data, null, 2);
    renderDebugRunDetails({
      ...data,
      requestJson: data.requestJson || requestBody,
      responseJson: data.responseJson || data,
    });

    if (!response.ok) {
      debugResponse.textContent = `查询失败: ${data.detail || JSON.stringify(data)}`;
      return;
    }

    const evidenceHtml = renderDebugEvidence(data);
    if (evidenceHtml) {
      debugEvidenceContent.innerHTML = evidenceHtml;
      debugEvidence.style.display = "block";
    }
  } catch (error) {
    debugResponse.textContent = `查询失败: ${error.message}`;
  } finally {
    submitButton.disabled = false;
  }
});
