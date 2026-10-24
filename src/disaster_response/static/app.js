const $ = (selector) => document.querySelector(selector);
const state = { incidents: [], selected: null, map: null, markers: [] };
const icons = { flood: "≋", fire: "♨", building_collapse: "▤", landslide: "⌁", road_blockage: "⊘", other: "•" };
const pretty = (value) => (value || "unknown").replaceAll("_", " ");
const timeAgo = (stamp) => { const minutes = Math.max(0, Math.floor((Date.now() - new Date(stamp).getTime()) / 60000)); return minutes < 1 ? "just now" : minutes < 60 ? `${minutes}m ago` : minutes < 1440 ? `${Math.floor(minutes / 60)}h ago` : `${Math.floor(minutes / 1440)}d ago`; };
const placeOf = (incident) => incident.location.raw_text || incident.location.precision || "Location unresolved";

function initMap() {
  if (!window.L || state.map) return;
  document.querySelector("#map .map-placeholder")?.remove();
  state.map = L.map("map", { zoomControl: false }).setView([18.6298, 73.7997], 11);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(state.map);
  L.control.zoom({ position: "bottomright" }).addTo(state.map);
}

function renderMap() {
  initMap();
  if (!state.map) return;
  state.markers.forEach((marker) => marker.remove()); state.markers = [];
  const located = state.incidents.filter((item) => item.location.lat != null && item.location.lon != null);
  located.forEach((item) => {
    const status = item.verification.status;
    const icon = L.divIcon({ className: "", html: `<div class="map-pin ${status}"></div>`, iconSize: [16, 16], iconAnchor: [8, 8] });
    const marker = L.marker([item.location.lat, item.location.lon], { icon }).addTo(state.map);
    marker.bindPopup(`<b>${escapeHtml(pretty(item.hazard_type))}</b><br>${escapeHtml(item.description)}<br><small>${escapeHtml(placeOf(item))} · ${Math.round(item.urgency.score * 100)} urgency</small>`);
    marker.on("click", () => { state.selected = item.incident_id; renderList(); }); state.markers.push(marker);
  });
  if (located.length === 1) state.map.setView([located[0].location.lat, located[0].location.lon], 13);
  else if (located.length > 1) state.map.fitBounds(L.latLngBounds(located.map((x) => [x.location.lat, x.location.lon])).pad(0.2), { maxZoom: 13 });
}

function escapeHtml(value) { return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]); }

function renderList() {
  const query = $("#searchInput").value.trim().toLowerCase(); const filter = $("#statusFilter").value;
  const shown = state.incidents.filter((item) => (filter === "all" || item.verification.status === filter) && `${item.description} ${placeOf(item)} ${item.hazard_type}`.toLowerCase().includes(query));
  $("#queueCount").textContent = shown.length; $("#navCount").textContent = state.incidents.filter((x) => x.verification.status === "needs_review").length;
  $("#showingCount").textContent = `${shown.length} report${shown.length === 1 ? "" : "s"}`;
  const container = $("#incidentList");
  if (!shown.length) { container.innerHTML = `<div class="empty-state"><b>${state.incidents.length ? "No matching reports" : "No reports yet"}</b>${state.incidents.length ? "Adjust your filters and try again." : "Log a report to begin the review queue."}</div>`; return; }
  container.innerHTML = shown.map((item) => `<article class="incident-row ${state.selected === item.incident_id ? "selected" : ""}" data-id="${item.incident_id}"><div class="incident-top"><span class="incident-type"><i class="type-icon">${icons[item.hazard_type] || "•"}</i>${escapeHtml(pretty(item.hazard_type))}</span><span class="status-badge status-${item.verification.status}">${escapeHtml(pretty(item.verification.status))}</span></div><h3>${escapeHtml(item.description)}</h3><div class="incident-meta"><span>⌖ ${escapeHtml(placeOf(item))}</span><span>${timeAgo(item.reported_at)}</span><span class="priority">${Math.round(item.urgency.score * 100)} / 100</span></div></article>`).join("");
  container.querySelectorAll(".incident-row").forEach((row) => row.addEventListener("click", () => openDetails(row.dataset.id)));
}

function renderStats() {
  const items = state.incidents;
  $("#statOpen").textContent = items.filter((x) => x.verification.status === "needs_review").length;
  $("#statHigh").textContent = items.filter((x) => x.urgency.score >= .7 && x.verification.status !== "rejected").length;
  $("#statVerified").textContent = items.filter((x) => x.verification.status === "accepted").length;
  $("#statRejected").textContent = items.filter((x) => x.verification.status === "rejected").length;
}

async function loadIncidents() {
  try {
    const response = await fetch("/api/v1/incidents"); if (!response.ok) throw new Error("Could not load incidents");
    state.incidents = await response.json(); renderStats(); renderList(); renderMap();
    $("#lastUpdated").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch (error) { toast(error.message); }
}

function openDetails(id) {
  const item = state.incidents.find((x) => x.incident_id === id); if (!item) return;
  state.selected = id; renderList();
  const evidence = item.verification.evidence.length ? item.verification.evidence.map((e) => `<p><b>${escapeHtml(e.result)}</b> · ${escapeHtml(e.claim_checked)}<br>${escapeHtml(e.detail || e.chunk_id)}</p>`).join("") : "<p>No independent evidence attached yet.</p>";
  const sources = item.sources.map((s) => `<p>${escapeHtml(pretty(s.type))} · ${escapeHtml(s.name || s.id)} · source prior ${Math.round(s.credibility_prior * 100)}%</p>`).join("");
  $("#detailContent").innerHTML = `<div class="detail-wrap"><div class="dialog-head"><div class="eyebrow">INCIDENT · ${escapeHtml(item.incident_id.slice(0, 8).toUpperCase())}</div><button class="close-btn" id="closeDetail">×</button></div><span class="status-badge status-${item.verification.status}">${escapeHtml(pretty(item.verification.status))}</span><h2 class="detail-title">${escapeHtml(item.description)}</h2><div class="detail-place">⌖ ${escapeHtml(placeOf(item))} · ${escapeHtml(pretty(item.location.precision))} precision · geocode confidence ${Math.round(item.location.geocode_confidence * 100)}%</div><div class="detail-section"><h4>TRIAGE</h4><p>Urgency <b>${Math.round(item.urgency.score * 100)} / 100</b> · ${item.corroboration_count} independent source${item.corroboration_count === 1 ? "" : "s"}</p><p>Reported ${new Date(item.reported_at).toLocaleString()} · ${escapeHtml(item.severity_cues.join(", ") || "No severity cues extracted")}</p></div><div class="detail-section"><h4>VERIFICATION NOTES</h4><p>${escapeHtml(item.verification.reasoning)}</p>${evidence}</div><div class="detail-section"><h4>SOURCES</h4>${sources || "<p>No source details.</p>"}</div>${item.verification.status === "rejected" ? "" : `<div class="detail-actions"><button class="reject-btn" data-decision="rejected">Reject report</button><button class="accept-btn" data-decision="accepted">Accept as verified</button></div>`}</div>`;
  const dialog = $("#detailDialog"); dialog.showModal(); $("#closeDetail").onclick = () => dialog.close();
  dialog.querySelectorAll("[data-decision]").forEach((button) => button.addEventListener("click", () => submitDecision(id, button.dataset.decision)));
}

async function submitDecision(id, status) {
  const note = window.prompt(status === "accepted" ? "Add a short verification note:" : "Why is this report being rejected?");
  if (!note || note.trim().length < 3) return;
  try {
    const response = await fetch(`/api/v1/incidents/${id}/decision`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status, note }) });
    if (!response.ok) throw new Error((await response.json()).detail || "Could not save decision");
    $("#detailDialog").close(); toast(`Report marked ${pretty(status)}.`); await loadIncidents();
  } catch (error) { toast(error.message); }
}

function toast(message) { const el = $("#toast"); el.textContent = message; el.classList.add("visible"); clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.remove("visible"), 2800); }

$("#newReportBtn").onclick = () => $("#reportDialog").showModal();
$("#closeDialog").onclick = $("#cancelDialog").onclick = () => $("#reportDialog").close();
$("#refreshBtn").onclick = loadIncidents;
$("#searchInput").addEventListener("input", renderList); $("#statusFilter").addEventListener("change", renderList);
$("#clearFilters").onclick = () => { $("#searchInput").value = ""; $("#statusFilter").value = "all"; renderList(); };
$("#reportForm").addEventListener("submit", async (event) => {
  event.preventDefault(); const button = $("#submitReport"); button.disabled = true; button.textContent = "Processing…";
  const id = $("#sourceId").value.trim() || `operator-${crypto.randomUUID().slice(0, 8)}`;
  const payload = { items: [{ text: $("#reportText").value.trim(), source: { type: $("#sourceType").value, id, name: id, credibility_prior: .5 } }] };
  try {
    const response = await fetch("/api/v1/ingest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (!response.ok) { const data = await response.json(); throw new Error(data.detail || "Report processing failed"); }
    $("#reportDialog").close(); event.target.reset(); toast("Report processed and added to review queue."); await loadIncidents();
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.innerHTML = 'Process report <span>→</span>'; }
});

async function startApp() {
  try {
    const configResponse = await fetch("/api/v1/config");
    if (!configResponse.ok) throw new Error("Could not read application configuration");
    const config = await configResponse.json();
    const existingSession = config.auth_required ? await fetch("/api/v1/incidents") : null;
    if (config.auth_required && existingSession.status === 401) {
      const token = window.prompt("Enter the operator access token:");
      if (!token) { toast("Operator sign-in is required."); return; }
      const login = await fetch("/api/v1/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) });
      if (!login.ok) { toast("Invalid operator token. Reload to retry."); return; }
    }
    await loadIncidents();
    const stream = new EventSource("/api/v1/events");
    stream.addEventListener("connected", () => { $("#connectionStatus").innerHTML = "<i></i> LIVE UPDATES"; });
    stream.addEventListener("incidents_changed", loadIncidents);
    stream.onerror = () => { $("#connectionStatus").innerHTML = "<i></i> RECONNECTING"; };
    setInterval(loadIncidents, 60000);
    if (!config.feed_enabled) $("#connectionStatus").title = "Live operator updates are active. Automatic feed ingestion is not configured.";
  } catch (error) { toast(error.message); }
}

document.addEventListener("DOMContentLoaded", startApp);
