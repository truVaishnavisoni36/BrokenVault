const state = { versions: [], uploads: [], job: null, stats: {} };
const $ = (id) => document.getElementById(id);
const formatBytes = (n) => {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const value = Number(n);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
};
const formatDate = (seconds) => seconds ? new Date(Number(seconds) * 1000).toLocaleString() : "—";
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;","\"":"&quot;"}[c]));

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || payload.error || `Request failed (${response.status})`);
  return payload;
}

function setServer(online) {
  $("server-dot").className = `status-dot ${online ? "online" : "offline"}`;
  $("server-label").textContent = online ? "Server online" : "Server unavailable";
  $("system-server").textContent = online ? "Online" : "Offline";
}

function renderVersions() {
  const versions = [...state.versions].reverse();
  const latest = versions[0];
  $("stat-versions").textContent = state.stats.completed_versions ?? state.versions.length;
  $("stat-latest").textContent = latest ? `${latest.version_id} completed ${formatDate(latest.created_at)}` : "No versions yet";
  $("stat-chunks").textContent = state.stats.unique_chunks ?? "—";
  $("stat-storage").textContent = state.stats.stored_bytes != null ? `${formatBytes(state.stats.stored_bytes)} stored` : "— stored";
  $("stat-latest-size").textContent = latest ? formatBytes(latest.total_bytes) : "—";
  $("stat-reuse").textContent = latest ? `${formatBytes(latest.reused_bytes)} reused · ${formatBytes(latest.uploaded_bytes)} uploaded` : "—";

  const rows = versions.slice(0, 6).map(v => `
    <tr>
      <td class="mono">${escapeHtml(v.version_id)}</td>
      <td>${formatDate(v.created_at)}</td>
      <td>${Number(v.files || 0)}</td>
      <td>${formatBytes(v.total_bytes)}</td>
      <td>${formatBytes(v.reused_bytes)}</td>
      <td><span class="state ok"><span class="state-dot"></span>Completed</span></td>
    </tr>`).join("");
  $("recent-versions").innerHTML = rows ? `<table><thead><tr><th>Version</th><th>Created</th><th>Files</th><th>Total</th><th>Reused</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>` : `<div class="empty">No completed backups yet.</div>`;

  const allRows = versions.map(v => `
    <tr>
      <td class="mono">${escapeHtml(v.version_id)}</td>
      <td>${formatDate(v.created_at)}</td>
      <td>${Number(v.files || 0)}</td>
      <td>${Number(v.chunks || 0)}</td>
      <td>${formatBytes(v.total_bytes)}</td>
      <td>${formatBytes(v.uploaded_bytes)}</td>
      <td>${formatBytes(v.reused_bytes)}</td>
    </tr>`).join("");
  $("all-versions").innerHTML = allRows ? `<table><thead><tr><th>Version</th><th>Created</th><th>Files</th><th>Chunks</th><th>Total</th><th>Uploaded</th><th>Reused</th></tr></thead><tbody>${allRows}</tbody></table>` : `<div class="empty">No completed backups yet.</div>`;

  const select = $("restore-version");
  select.innerHTML = versions.length ? versions.map(v => `<option value="${escapeHtml(v.version_id)}">${escapeHtml(v.version_id)} · ${formatDate(v.created_at)} · ${formatBytes(v.total_bytes)}</option>`).join("") : `<option value="">No completed versions</option>`;
}

function renderUploads() {
  $("system-uploads").textContent = state.stats.unfinished_uploads ?? state.uploads.length;
  const rows = state.uploads.map(upload => `
    <tr>
      <td class="mono">${escapeHtml(upload.upload_id)}</td>
      <td>${formatDate(upload.created_at)}</td>
      <td>${formatBytes(upload.total_bytes)}</td>
      <td><span class="state warn"><span class="state-dot"></span>Uploading</span></td>
    </tr>`).join("");
  $("unfinished-uploads").innerHTML = rows ? `<table><thead><tr><th>Upload</th><th>Started</th><th>Total</th><th>State</th></tr></thead><tbody>${rows}</tbody></table>` : `<div class="empty">No unfinished uploads.</div>`;
}

function renderJob() {
  const job = state.job;
  if (!job) {
    $("system-job").textContent = "None";
    $("job-state").textContent = "Idle";
    $("job-detail").textContent = "No backup is running.";
    $("job-progress").style.width = "0%";
    $("job-progress-text").textContent = "—";
    $("job-chunk-text").textContent = "—";
    return;
  }
  $("system-job").textContent = job.status;
  $("job-state").textContent = job.status;
  $("job-detail").textContent = job.message || job.phase || job.status;
  const total = Number(job.total_bytes || 0);
  const uploaded = Number(job.uploaded_bytes || 0);
  const percent = total > 0 ? Math.min(100, Math.round((uploaded / total) * 100)) : (job.status === "completed" ? 100 : 0);
  $("job-progress").style.width = `${percent}%`;
  $("job-progress-text").textContent = total ? `${formatBytes(uploaded)} uploaded · ${percent}% of source bytes` : "Preparing source";
  $("job-chunk-text").textContent = `${Number(job.uploaded_chunks || 0)} uploaded chunks${job.missing_chunks ? ` · ${job.missing_chunks} remaining` : ""}`;
}

async function refresh() {
  try {
    const data = await api("/api/state");
    setServer(data.server_ok);
    state.versions = data.versions || [];
    state.uploads = data.uploads || [];
    state.stats = data.stats || {};
    state.job = data.job || null;
    $("server-url").textContent = data.server_url || "—";
    renderVersions();
    renderUploads();
    renderJob();
  } catch (error) {
    setServer(false);
    $("system-job").textContent = "Unavailable";
    $("job-detail").textContent = error.message;
  }
}

function setView(view) {
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  document.querySelectorAll(".view").forEach((section) => section.classList.toggle("active", section.id === `view-${view}`));
  const titles = { overview: ["Overview", "Backup dashboard"], backups: ["Backups", "Backup history"], restore: ["Restore", "Restore a version"], verify: ["Verify", "Integrity verification"] };
  $("view-eyebrow").textContent = titles[view][0];
  $("view-title").textContent = titles[view][1];
}

document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
document.querySelectorAll("[data-go]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.go)));
$("refresh-button").addEventListener("click", refresh);

async function watchJob(jobId, statusElement, button) {
  const timer = setInterval(async () => {
    try {
      const job = await api(`/api/jobs/${jobId}`);
      state.job = job;
      renderJob();
      statusElement.textContent = job.message || job.status;
      if (["completed", "interrupted", "failed"].includes(job.status)) {
        clearInterval(timer);
        button.disabled = false;
        if (job.status === "completed") statusElement.textContent = `Completed ${job.result.version_id}`;
        if (job.status === "interrupted") statusElement.textContent = "Interrupted. The upload remains on the server; run the same source again to resume.";
        if (job.status === "failed") statusElement.textContent = job.error || "Backup failed";
        await refresh();
      }
    } catch (error) {
      clearInterval(timer);
      button.disabled = false;
      statusElement.textContent = error.message;
    }
  }, 700);
}

$("backup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("backup-button");
  const status = $("backup-status");
  button.disabled = true;
  status.textContent = "Preparing backup…";
  try {
    const source = $("backup-source").value.trim();
    const stop = $("stop-after").value.trim();
    localStorage.setItem("brokenvault.source", source);
    const payload = { source, stop_after: stop ? Number(stop) : null };
    const job = await api("/api/backup", { method: "POST", body: JSON.stringify(payload) });
    status.textContent = "Backup running…";
    watchJob(job.job_id, status, button);
  } catch (error) {
    button.disabled = false;
    status.textContent = error.message;
  }
});

$("restore-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("restore-button");
  const status = $("restore-status");
  button.disabled = true;
  status.textContent = "Restoring…";
  try {
    const payload = { version: $("restore-version").value, destination: $("restore-destination").value.trim() };
    const result = await api("/api/restore", { method: "POST", body: JSON.stringify(payload) });
    status.textContent = `Restored ${result.files} files and ${result.folders} folders.`;
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

$("verify-button").addEventListener("click", async () => {
  const button = $("verify-button");
  const panel = $("verify-result");
  button.disabled = true;
  panel.innerHTML = `<div class="verify-empty">Verifying stored chunks…</div>`;
  try {
    const result = await api("/api/verify", { method: "POST" });
    if (result.ok) {
      panel.innerHTML = `<div class="verify-good"><h3>Verification passed</h3><p>${Number(result.checked_chunks || 0)} stored chunks referenced by completed versions were checked successfully.</p></div>`;
    } else {
      const damaged = result.damaged || [];
      const issues = damaged.flatMap(item => (item.affected || []).length ? item.affected.map(ref => ({ chunk_id: item.chunk_id, reason: item.reason, version_id: ref.version_id, path: ref.path })) : [{ chunk_id: item.chunk_id, reason: item.reason, version_id: "—", path: "—" }]);
      const html = issues.map(issue => `<div class="issue"><div class="issue-title mono">${escapeHtml(issue.chunk_id)}</div><div class="issue-meta">${escapeHtml(issue.reason)} · ${escapeHtml(issue.version_id)} · ${escapeHtml(issue.path)}</div></div>`).join("");
      panel.innerHTML = `<div class="verify-bad"><h3>Corruption detected</h3><p>${damaged.length} stored chunk(s) failed verification. No repair was attempted.</p><div class="issue-list">${html || `<div class="issue"><div class="issue-meta">No affected file details returned.</div></div>`}</div></div>`;
    }
  } catch (error) {
    panel.innerHTML = `<div class="verify-bad"><h3>Verification failed</h3><p>${escapeHtml(error.message)}</p></div>`;
  } finally {
    button.disabled = false;
  }
});

const savedSource = localStorage.getItem("brokenvault.source");
if (savedSource) $("backup-source").value = savedSource;
refresh();
setInterval(refresh, 5000);
