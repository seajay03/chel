const TECHNICIANS = ["Jean David", "Mr. Cotton", "Eric", "Emmy"];
const TEMPLATES = {
  "Service #1": ["Oil change", "Brake inspection", "Tire rotation"],
  "Service #2": ["Transmission check", "Coolant flush", "Electrical scan"],
  "Hybrid": ["Battery health", "Inverter test", "Cooling loop inspection"],
  "Oil": ["Oil change", "Filter swap", "Top-up fluids"],
  "Brake Clean": ["Caliper clean", "Rotor resurface", "Pad measurement"],
};

const defaultJobs = [
  {
    id: crypto.randomUUID(),
    client: "Marie D.",
    vehicle: "CX-5 Touring",
    stock: "MX-204",
    technician: "Jean David",
    date: today(),
    time: "09:00",
    duration: 1.5,
    tasks: ["Oil change", "Brake inspection"],
    notes: "Customer waiting room",
    status: "Waiting",
    priority: "Urgent",
    template: "Service #1",
    noShow: false,
  },
  {
    id: crypto.randomUUID(),
    client: "Studio Boreal",
    vehicle: "Mazda3 GS",
    stock: "MX-198",
    technician: "Emmy",
    date: today(1),
    time: "13:00",
    duration: 2,
    tasks: ["Battery health", "Inverter test"],
    notes: "Hybrid diagnostics",
    status: "In Progress",
    priority: "Normal",
    template: "Hybrid",
    noShow: false,
  },
];

let jobs = loadJobs();
let editingId = null;
let deferredPrompt = null;

function today(add = 0) {
  const d = new Date();
  d.setDate(d.getDate() + add);
  return d.toISOString().slice(0, 10);
}

function loadJobs() {
  const saved = localStorage.getItem("mazda-jobs");
  if (saved) {
    try {
      return JSON.parse(saved);
    } catch (e) {
      console.warn("Could not parse jobs", e);
    }
  }
  return defaultJobs;
}

function saveJobs() {
  localStorage.setItem("mazda-jobs", JSON.stringify(jobs));
}

function byId(id) { return document.getElementById(id); }

function init() {
  populateTechnicians();
  populateTemplates();
  renderQR();
  renderTechCards();
  renderDashboard();
  attachEvents();
  renderTasks();
  setForm();
  resolveLandingView();
  registerServiceWorker();
}

document.addEventListener("DOMContentLoaded", init);

function populateTechnicians() {
  const techSelects = ["tech-filter", "technician", "manager-tech-filter", "qr-technician"]
    .map(byId);
  techSelects.forEach(sel => {
    if (!sel) return;
    sel.innerHTML = TECHNICIANS.map(t => `<option value="${t}">${t}</option>`).join("");
    const defaultTech = new URLSearchParams(location.search).get("tech");
    if (defaultTech && TECHNICIANS.includes(defaultTech)) {
      sel.value = defaultTech;
    }
  });
}

function populateTemplates() {
  const templateSelect = byId("template");
  templateSelect.innerHTML = Object.keys(TEMPLATES).map(t => `<option>${t}</option>`).join("");
  templateSelect.addEventListener("change", () => applyTemplate(templateSelect.value));
  applyTemplate(templateSelect.value);
}

function renderTasks(tasks = []) {
  const container = byId("task-selectors");
  container.innerHTML = "";
  for (let i = 0; i < 6; i++) {
    const selector = document.createElement("select");
    selector.innerHTML = `<option value="">Task #${i + 1}</option>` +
      Array.from(new Set(Object.values(TEMPLATES).flat())).map(t => `<option>${t}</option>`).join("");
    selector.value = tasks[i] || "";
    container.appendChild(selector);
  }
}

function applyTemplate(template) {
  const tasks = TEMPLATES[template] || [];
  renderTasks(tasks);
}

function attachEvents() {
  byId("go-garage").onclick = () => showSection("technician-view");
  byId("go-service").onclick = () => showSection("manager-login");
  byId("login-btn").onclick = login;
  byId("job-form").addEventListener("submit", saveJob);
  byId("reset-form").onclick = () => setForm();
  byId("tech-filter").onchange = renderTechCards;
  byId("tech-status-filter").onchange = renderTechCards;
  byId("date-filter").onchange = renderTechCards;
  ["manager-tech-filter", "manager-status-filter", "priority-filter", "manager-date-filter"].forEach(id => {
    byId(id).onchange = renderDashboard;
  });
  byId("export-csv").onclick = exportCSV;
  byId("export-pdf").onclick = exportPDF;
  byId("pwa-install").onclick = installPrompt;
  byId("qr-technician").onchange = renderQR;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
  });
}

function showSection(id) {
  ["welcome-screen", "technician-view", "manager-login", "manager-dashboard"].forEach(sec => {
    byId(sec).classList.toggle("hidden", sec !== id);
  });
}

function login() {
  const pass = byId("manager-password").value.trim();
  if (pass === "mazda123") {
    byId("login-error").textContent = "";
    showSection("manager-dashboard");
  } else {
    byId("login-error").textContent = "Incorrect password";
  }
}

function gatherForm() {
  const taskSelectors = Array.from(byId("task-selectors").querySelectorAll("select"));
  const tasks = taskSelectors.map(s => s.value).filter(Boolean);
  return {
    id: editingId || crypto.randomUUID(),
    client: byId("client").value,
    vehicle: byId("vehicle").value,
    stock: byId("stock").value,
    technician: byId("technician").value,
    date: byId("date").value,
    time: byId("time").value,
    duration: parseFloat(byId("duration").value || 0),
    tasks,
    notes: byId("notes").value,
    status: byId("status").value,
    priority: byId("priority").value,
    template: byId("template").value,
    noShow: byId("status").value === "No-Show",
  };
}

function setForm(job = null) {
  editingId = job?.id || null;
  byId("save-job").textContent = job ? "Update job" : "Save job";
  byId("client").value = job?.client || "";
  byId("vehicle").value = job?.vehicle || "";
  byId("stock").value = job?.stock || "";
  byId("technician").value = job?.technician || TECHNICIANS[0];
  byId("date").value = job?.date || today();
  byId("time").value = job?.time || "08:00";
  byId("duration").value = job?.duration || 1;
  byId("status").value = job?.status || "Waiting";
  byId("priority").value = job?.priority || "Normal";
  byId("template").value = job?.template || Object.keys(TEMPLATES)[0];
  renderTasks(job?.tasks || []);
  byId("notes").value = job?.notes || "";
  byId("overlap-warning").textContent = "";
}

function saveJob(e) {
  e.preventDefault();
  const job = gatherForm();
  if (!job.client || !job.date || !job.time) return;

  const overlap = detectOverlap(job, editingId);
  byId("overlap-warning").textContent = overlap ? `⚠️ Overlap with ${overlap.client} at ${overlap.time}` : "";

  if (editingId) {
    jobs = jobs.map(j => j.id === editingId ? job : j);
  } else {
    jobs.push(job);
  }
  saveJobs();
  renderTechCards();
  renderDashboard();
  setForm();
}

function detectOverlap(job, ignoreId = null) {
  const start = new Date(`${job.date}T${job.time}`);
  const end = new Date(start.getTime() + job.duration * 60 * 60 * 1000);
  return jobs.find(j => {
    if (j.id === ignoreId) return false;
    if (j.technician !== job.technician || j.date !== job.date) return false;
    const jStart = new Date(`${j.date}T${j.time}`);
    const jEnd = new Date(jStart.getTime() + j.duration * 60 * 60 * 1000);
    return jStart < end && start < jEnd;
  });
}

function renderTechCards() {
  const tech = byId("tech-filter").value || TECHNICIANS[0];
  const date = byId("date-filter").value || today();
  const status = byId("tech-status-filter").value;
  const container = byId("tech-cards");
  container.innerHTML = "";
  const filtered = jobs
    .filter(j => j.technician === tech && j.date === date)
    .filter(j => !status || j.status === status)
    .sort((a,b) => a.time.localeCompare(b.time));

  filtered.forEach(job => container.appendChild(jobCard(job, false)));
}

function jobCard(job, editable) {
  const card = document.createElement("div");
  card.className = "job-card";
  card.draggable = editable;
  card.dataset.id = job.id;

  const statusClass = job.status.replace(/\s+/g, "-");
  card.innerHTML = `
    <div class="job-header">
      <div>
        <strong>${job.client}</strong>
        <div class="badge">${job.vehicle}${job.stock ? ` • ${job.stock}` : ""}</div>
      </div>
      <div class="status ${statusClass}">${job.status}</div>
    </div>
    <div class="badge">${job.date} • ${job.time} • ${job.duration}h</div>
    <div class="badge">Tasks: ${job.tasks.join(", ") || "—"}</div>
    <div class="badge">Notes: ${job.notes || "—"}</div>
    <div class="badge priority ${job.priority}">${job.priority}</div>
  `;

  if (editable) {
    card.addEventListener("dragstart", dragStart);
    card.addEventListener("dragend", dragEnd);
    const actions = document.createElement("div");
    actions.className = "form-actions";
    const editBtn = document.createElement("button");
    editBtn.textContent = "Edit";
    editBtn.onclick = () => setForm(job);
    const delBtn = document.createElement("button");
    delBtn.textContent = "Delete";
    delBtn.className = "accent";
    delBtn.onclick = () => deleteJob(job.id);
    actions.append(editBtn, delBtn);
    card.appendChild(actions);
  }

  return card;
}

function deleteJob(id) {
  if (!confirm("Delete this job?")) return;
  jobs = jobs.filter(j => j.id !== id);
  saveJobs();
  renderTechCards();
  renderDashboard();
}

function renderDashboard() {
  const filters = {
    tech: byId("manager-tech-filter").value,
    status: byId("manager-status-filter").value,
    priority: byId("priority-filter").value,
    date: byId("manager-date-filter").value,
  };

  const filtered = jobs.filter(j => (
    (!filters.tech || j.technician === filters.tech) &&
    (!filters.status || j.status === filters.status) &&
    (!filters.priority || j.priority === filters.priority) &&
    (!filters.date || j.date === filters.date)
  ));

  const grid = byId("calendar-grid");
  grid.innerHTML = "";

  const grouped = groupByDate(filtered);
  Object.entries(grouped).forEach(([date, list]) => {
    const col = document.createElement("div");
    col.className = "calendar-column";
    col.dataset.date = date;
    col.addEventListener("dragover", dragOver);
    col.addEventListener("drop", (e) => dropOnDate(e, date));

    const hours = list.reduce((sum, j) => sum + j.duration, 0);
    col.innerHTML = `<h4>${date} <span class="badge">${hours.toFixed(1)}h</span></h4>`;
    list.sort((a,b) => a.time.localeCompare(b.time)).forEach(job => {
      const card = jobCard(job, true);
      col.appendChild(card);
    });
    grid.appendChild(col);
  });

  renderHoursSummary();
}

function groupByDate(list) {
  return list.reduce((acc, job) => {
    acc[job.date] = acc[job.date] || [];
    acc[job.date].push(job);
    return acc;
  }, {});
}

function dragStart(e) {
  e.dataTransfer.setData("text/plain", e.target.dataset.id);
  e.currentTarget.classList.add("dragging");
}

function dragEnd(e) {
  e.currentTarget.classList.remove("dragging");
}

function dragOver(e) {
  e.preventDefault();
}

function dropOnDate(e, date) {
  e.preventDefault();
  const id = e.dataTransfer.getData("text/plain");
  const job = jobs.find(j => j.id === id);
  if (!job) return;
  const newTime = prompt("New start time (HH:MM)?", job.time) || job.time;
  const updated = { ...job, date, time: newTime };
  const overlap = detectOverlap(updated, id);
  if (overlap) {
    alert(`Overlap detected with ${overlap.client}`);
    return;
  }
  jobs = jobs.map(j => j.id === id ? updated : j);
  saveJobs();
  renderTechCards();
  renderDashboard();
}

function renderHoursSummary() {
  const summary = {};
  jobs.forEach(job => {
    const key = `${job.date}|${job.technician}`;
    summary[key] = (summary[key] || 0) + job.duration;
  });
  const container = byId("hours-summary");
  container.innerHTML = Object.entries(summary)
    .map(([key, hours]) => {
      const [date, tech] = key.split("|");
      return `<span class="badge">${date} • ${tech}: ${hours.toFixed(1)}h</span>`;
    }).join(" ");
}

function exportCSV() {
  const header = ["Client","Vehicle","Stock","Technician","Date","Time","Duration","Tasks","Notes","Status","Priority"];
  const rows = jobs.map(j => [j.client,j.vehicle,j.stock,j.technician,j.date,j.time,j.duration,j.tasks.join(" | "),j.notes,j.status,j.priority]);
  const csv = [header, ...rows].map(r => r.map(v => `"${(v ?? "").toString().replace(/"/g,'""')}"`).join(",")).join("\n");
  downloadFile(csv, "jobs.csv", "text/csv");
}

function exportPDF() {
  const html = jobs.map(j => `<tr><td>${j.client}</td><td>${j.vehicle}</td><td>${j.technician}</td><td>${j.date}</td><td>${j.time}</td><td>${j.status}</td></tr>`).join("");
  const doc = window.open("", "print");
  doc.document.write(`<style>table{width:100%;border-collapse:collapse;font-family:sans-serif}td,th{border:1px solid #999;padding:6px;text-align:left}</style><table><tr><th>Client</th><th>Vehicle</th><th>Tech</th><th>Date</th><th>Time</th><th>Status</th></tr>${html}</table>`);
  doc.document.close();
  doc.print();
}

function downloadFile(content, filename, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

function renderQR() {
  const tech = byId("qr-technician").value || TECHNICIANS[0];
  const url = `${location.origin}${location.pathname}?tech=${encodeURIComponent(tech)}`;
  const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=120x120&data=${encodeURIComponent(url)}`;
  byId("qr-preview").src = qrUrl;
}

function resolveLandingView() {
  const params = new URLSearchParams(location.search);
  const tech = params.get("tech");
  const view = params.get("view");
  if (tech && TECHNICIANS.includes(tech)) {
    byId("tech-filter").value = tech;
    showSection("technician-view");
  } else if (view === "manager") {
    showSection("manager-login");
  } else {
    showSection("welcome-screen");
  }
}

function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  navigator.serviceWorker.register('service-worker.js').catch(console.error);
}

function installPrompt() {
  if (deferredPrompt) {
    deferredPrompt.prompt();
  }
}

