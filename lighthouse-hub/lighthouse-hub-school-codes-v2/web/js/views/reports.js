import { api } from "../api.js";
import { pacePill, toast } from "../utils.js";

export async function renderReports(content) {
  const now = new Date();
  const { schools } = await api.get("/api/schools");

  content.innerHTML = `
    <div class="toolbar">
      <select id="month">${Array.from({length:12}).map((_,i) => {
        const m = i + 1;
        return `<option value="${m}" ${m === now.getMonth()+1 ? "selected" : ""}>${new Date(2020, i, 1).toLocaleString(undefined,{month:"long"})}</option>`;
      }).join("")}</select>
      <input id="year" type="number" value="${now.getFullYear()}" style="width:90px;padding:9px 12px;border:1.5px solid var(--border);border-radius:8px;">
      <select id="school"><option value="">All schools</option>${schools.map(s => `<option value="${s.id}">${s.code ? `${s.code} — ` : ""}${s.name}</option>`).join("")}</select>
      <div class="spacer"></div>
      <button class="btn btn-outline" id="export-csv">Export CSV</button>
      <button class="btn btn-outline" id="export-pdf">Export PDF</button>
    </div>
    <div id="report-table"></div>
  `;

  let currentRows = [];
  async function load() {
    const month = content.querySelector("#month").value;
    const year = content.querySelector("#year").value;
    const school = content.querySelector("#school").value;
    const url = `/api/reports/compliance?year=${year}&month=${month}${school ? `&school_id=${school}` : ""}`;
    const { rows } = await api.get(url);
    currentRows = rows;
    content.querySelector("#report-table").innerHTML = `
      <div class="table-wrap"><table>
        <thead><tr><th>Student</th><th>School</th><th>Provider</th><th>Target</th><th>Completed</th><th>% of target</th><th>Status</th></tr></thead>
        <tbody>${rows.map(r => `<tr><td>${r.student_name}</td><td>${r.school_name || "—"}</td><td>${r.provider_name || "—"}</td><td>${r.target}</td><td>${r.completed}</td><td>${r.compliance_pct}%</td><td>${pacePill(r.status)}</td></tr>`).join("") || `<tr><td colspan="7" class="empty">No students for this filter.</td></tr>`}</tbody>
      </table></div>
    `;
  }
  content.querySelector("#month").addEventListener("change", load);
  content.querySelector("#year").addEventListener("change", load);
  content.querySelector("#school").addEventListener("change", load);
  content.querySelector("#export-csv").addEventListener("click", () => {
    if (!currentRows.length) { toast("Nothing to export.", true); return; }
    const header = ["Student", "School", "Provider", "Target", "Completed", "% of target", "Status"];
    const lines = [header.join(",")].concat(currentRows.map(r => [r.student_name, r.school_name, r.provider_name, r.target, r.completed, r.compliance_pct, r.status].map(v => `"${String(v ?? "").replace(/"/g,'""')}"`).join(",")));
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "compliance-report.csv";
    a.click();
  });
  content.querySelector("#export-pdf").addEventListener("click", async () => {
    const month = content.querySelector("#month").value;
    const year = content.querySelector("#year").value;
    const school = content.querySelector("#school").value;
    const url = `/api/reports/compliance.pdf?year=${year}&month=${month}${school ? `&school_id=${school}` : ""}`;
    try {
      const { blob, filename } = await api.getBinary(url);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
    } catch (err) { toast(err.message, true); }
  });
  load();
}
