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
