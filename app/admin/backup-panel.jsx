"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ArchiveRestore, CheckCircle2, Download, FileArchive, ShieldCheck, Upload } from "lucide-react";

const API = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");
const BACKUP_FILE = "binodmahato_backup_data.zip";
const MAX_UPLOAD_BYTES = 200 * 1024 * 1024;
const ZIP_SIGNATURE = [0x50, 0x4b, 0x03, 0x04];
const COLLECTION_LABELS = {
  books: "Books", users: "Users & team", orders: "Orders & deliveries", payments: "Payments",
  customers: "Customers", reviews: "Reviews", mediaassets: "Media & gallery",
  sitecontents: "Website content", adminsettings: "Store, bank & site settings",
  storecategories: "Categories", newslettersubscribers: "Newsletter subscribers",
  adminnotifications: "Notifications", adminaudits: "Activity log", app_metadata: "System records"
};

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// Checks the file locally so a wrong file is refused before anything is uploaded.
async function validateBackupFile(file) {
  if (!file.name.toLowerCase().endsWith(".zip")) return `Choose the ${BACKUP_FILE} file created by this Admin Panel.`;
  if (!file.size) return "That file is empty.";
  if (file.size > MAX_UPLOAD_BYTES) return "Backup files larger than 200 MB cannot be restored.";
  const header = new Uint8Array(await file.slice(0, 4).arrayBuffer());
  if (!ZIP_SIGNATURE.every((byte, index) => header[index] === byte)) return "That file is not a valid ZIP archive.";
  return "";
}

// fetch() cannot report upload progress, so ZIP uploads use XMLHttpRequest.
function uploadBackup(path, file, headers, onUploadProgress) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${API}/api/admin${path}`);
    request.withCredentials = true;
    request.setRequestHeader("Content-Type", "application/zip");
    for (const [name, value] of Object.entries(headers)) request.setRequestHeader(name, value);
    request.upload.onprogress = event => { if (event.lengthComputable) onUploadProgress(event.loaded / event.total); };
    request.upload.onload = () => onUploadProgress(1);
    request.onload = () => {
      let data = {};
      try { data = JSON.parse(request.responseText || "{}"); } catch { /* non-JSON error page */ }
      if (request.status >= 200 && request.status < 300) resolve(data);
      else reject(new Error(data.error || (request.status === 413 ? "The backup file is too large to upload." : `Request failed (${request.status}).`)));
    };
    request.onerror = () => reject(new Error("The upload was interrupted. Check your connection and try again."));
    request.onabort = () => reject(new Error("The upload was cancelled."));
    request.send(file);
  });
}

function Progress({ progress }) {
  if (!progress) return null;
  const known = typeof progress.percent === "number";
  const percent = known ? Math.round(progress.percent * 100) : null;
  return <div className={`admin-progress ${known ? "" : "is-indeterminate"}`} role="progressbar" aria-label={progress.label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent ?? undefined}>
    <div className="admin-progress-head"><span>{progress.label}</span><b>{known ? `${percent}%` : progress.detail || ""}</b></div>
    <div className="admin-progress-track"><span style={known ? { width: `${percent}%` } : undefined}/></div>
  </div>;
}

export default function BackupPanel({ api, onNotice, onError, onRestored }) {
  const [downloading, setDownloading] = useState(false);
  const [file, setFile] = useState(null);
  const [summary, setSummary] = useState(null);
  const [checking, setChecking] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [downloadProgress, setDownloadProgress] = useState(null);
  const [restoreProgress, setRestoreProgress] = useState(null);
  const [restored, setRestored] = useState(null);
  const inputRef = useRef(null);
  const busy = checking || restoring || downloading;

  useEffect(() => {
    if (!busy) return;
    // Leaving mid-transfer would abandon the download or upload, so the browser asks first.
    function warn(event) { event.preventDefault(); event.returnValue = ""; }
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [busy]);

  function clearSelection() {
    setFile(null);
    setSummary(null);
    setConfirmText("");
    setRestoreProgress(null);
  }

  async function downloadBackup() {
    setDownloading(true);
    setRestored(null);
    onError("");
    setDownloadProgress({ label: "Collecting database records and images…" });
    try {
      const response = await fetch(`${API}/api/admin/backup`, { credentials: "include" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Backup failed (${response.status}).`);
      }
      const total = Number(response.headers.get("content-length")) || 0;
      const chunks = [];
      let received = 0;
      if (response.body) {
        const reader = response.body.getReader();
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(value);
          received += value.length;
          setDownloadProgress(total
            ? { label: "Downloading backup…", percent: received / total }
            : { label: "Downloading backup…", detail: formatBytes(received) });
        }
      } else {
        chunks.push(new Uint8Array(await response.arrayBuffer()));
      }
      const url = URL.createObjectURL(new Blob(chunks, { type: "application/zip" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = BACKUP_FILE;
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setDownloadProgress({ label: "Backup downloaded", percent: 1 });
      onNotice(`Backup downloaded as ${BACKUP_FILE} (${formatBytes(received || chunks[0]?.length || 0)}).`);
    } catch (error) {
      setDownloadProgress(null);
      onError(error.message || "The backup could not be created.");
    } finally {
      setDownloading(false);
    }
  }

  async function chooseFile(event) {
    const selected = event.target.files?.[0];
    event.target.value = "";
    clearSelection();
    setRestored(null);
    onError("");
    if (!selected) return;
    const problem = await validateBackupFile(selected);
    if (problem) return onError(problem);
    setFile(selected);
    setChecking(true);
    setRestoreProgress({ label: "Uploading for verification…", percent: 0 });
    try {
      // An expired session would cut the upload off mid-way; check first for a clear message.
      await api("/auth/me");
      const result = await uploadBackup("/backup/verify", selected, {}, fraction => setRestoreProgress(fraction < 1
        ? { label: "Uploading for verification…", percent: fraction }
        : { label: "Checking signature, checksums, and records…" }));
      setSummary(result.backup);
      setRestoreProgress(null);
    } catch (error) {
      setFile(null);
      setRestoreProgress(null);
      onError(error.message);
    } finally {
      setChecking(false);
    }
  }

  async function restoreBackup() {
    if (!file || !summary || confirmText !== "RESTORE") return;
    if (!window.confirm("Replace ALL current website data with this backup? Changes made after the backup was created will be lost.")) return;
    setRestoring(true);
    onError("");
    setRestoreProgress({ label: "Uploading backup…", percent: 0 });
    try {
      await api("/auth/me");
      const result = await uploadBackup("/backup/restore", file, { "X-Confirm-Restore": "RESTORE" }, fraction => setRestoreProgress(fraction < 1
        ? { label: "Uploading backup…", percent: fraction }
        : { label: "Verifying and restoring data, then checking images…" }));
      clearSelection();
      setRestored(result.backup);
      onRestored();
      const images = result.backup.imageRestore || {};
      onNotice(`Backup restored: ${result.backup.documents.toLocaleString()} records are back in place${images.repaired ? ` and ${images.repaired} broken image link${images.repaired === 1 ? " was" : "s were"} restored from the backup` : ""}. Other signed-in sessions were signed out.`);
    } catch (error) {
      setRestoreProgress(null);
      onError(error.message);
    } finally {
      setRestoring(false);
    }
  }

  const collections = Object.entries(summary?.collections || {}).sort(([a], [b]) => (COLLECTION_LABELS[a] || a).localeCompare(COLLECTION_LABELS[b] || b));
  const imageResult = restored?.imageRestore;

  return <>
    <section className="admin-panel">
      <div className="admin-panel-heading"><div><h2>Download backup</h2><span>Everything in one ZIP file: books, website content, images, users, customers, orders and deliveries, payments, and store, bank and site settings.</span></div></div>
      <div className="admin-callout"><ShieldCheck size={16}/><span><strong>Signed and checksummed.</strong> Personal details stay encrypted inside the file, passwords are stored only as one-way hashes, and payment API keys are never included. Keep the file private.</span></div>
      <div className="admin-page-editor">
        <Progress progress={downloadProgress}/>
        <div className="admin-page-editor-footer"><span>Saved as <code>{BACKUP_FILE}</code>. Large image libraries can take a minute.</span><button className="button" type="button" onClick={downloadBackup} disabled={busy}>{downloading ? "Preparing backup…" : "Download backup"} <Download size={14}/></button></div>
      </div>
    </section>

    <section className="admin-panel">
      <div className="admin-panel-heading"><div><h2>Restore backup</h2><span>Replace the current website data with a backup created by this Admin Panel.</span></div></div>
      <div className="admin-callout"><AlertTriangle size={16}/><span><strong>Download a fresh backup first.</strong> Restoring replaces all current data. Your own admin account and this session are kept, and everyone else is signed out. Images whose original links no longer work are served from the backup.</span></div>
      <div className="admin-page-editor">
        <input ref={inputRef} type="file" accept=".zip,application/zip" hidden onChange={chooseFile}/>
        {summary && <dl className="admin-facts">
          <div><dt>File</dt><dd><FileArchive size={13}/> {file?.name} · {formatBytes(summary.bytes)}</dd></div>
          <div><dt>Created</dt><dd>{summary.createdAt ? new Date(summary.createdAt).toLocaleString() : "—"}</dd></div>
          <div><dt>Contents</dt><dd>{summary.documents.toLocaleString()} records · {summary.images} images</dd></div>
          {collections.map(([name, count]) => <div key={name}><dt>{COLLECTION_LABELS[name] || name}</dt><dd>{count.toLocaleString()}</dd></div>)}
        </dl>}
        {restored && <p className="admin-success"><CheckCircle2 size={14}/> Restored {restored.documents.toLocaleString()} records from the backup created {restored.createdAt ? new Date(restored.createdAt).toLocaleString() : "earlier"}.{imageResult && (imageResult.failed
          ? " Images could not be checked; their original links were kept."
          : ` Images: ${imageResult.kept} kept at their original links${imageResult.repaired ? `, ${imageResult.repaired} restored from the backup` : ""}.`)}</p>}
        {summary && <p className="admin-warning"><AlertTriangle size={14}/> The backup passed all security checks. Type RESTORE below to replace the current website data with it.</p>}
        {summary && <label className="field">Type RESTORE to confirm<input value={confirmText} autoComplete="off" spellCheck={false} disabled={restoring} onChange={event => setConfirmText(event.target.value.trim().toUpperCase())}/></label>}
        <Progress progress={restoreProgress}/>
        <div className="admin-page-editor-footer">
          <span>{checking ? "Checking the backup file…" : summary ? "Verified: signature, checksums, and data are valid." : "Choose a .zip backup file (up to 200 MB). It is verified before anything changes."}</span>
          <div className="admin-page-editor-actions">
            {summary && <button type="button" className="admin-cancel" onClick={clearSelection} disabled={restoring}>Cancel</button>}
            {summary
              ? <button type="button" className="button" onClick={restoreBackup} disabled={restoring || confirmText !== "RESTORE"}>{restoring ? "Restoring…" : "Restore backup"} <ArchiveRestore size={14}/></button>
              : <button type="button" className="button" onClick={() => inputRef.current?.click()} disabled={busy}>{checking ? "Verifying…" : "Choose backup file"} <Upload size={14}/></button>}
          </div>
        </div>
      </div>
    </section>
  </>;
}
