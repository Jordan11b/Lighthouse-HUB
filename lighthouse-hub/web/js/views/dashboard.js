import { api } from "../api.js";
import { fmtDate, pacePill } from "../utils.js";
import { CURRENT_USER } from "../main.js";
import { viewProviderSchedule } from "./schedule.js";

export async function renderDashboard(content) {
  const d = await api.get("/api/dashboard");

  const liveLabel = {
    in_session: "In a session", available: "Available", between_sessions: "Between sessions",
    finished_for_day: "Finished for the day", absent: "Absent", missing_schedule: "No schedule today",
  };

  content.innerHTML = `
    <div class="grid grid-4">
      <div class="card"><h3>Today — Scheduled</h3><div class="stat">${d.today.scheduled}</div><div class="stat-sub">${d.today.date}</div></div>
      <div class="card"><h3>Today — Completed</h3><div class="stat">${d.today.completed}</div></div>
      <div class="card"><h3>Today — Missed</h3><div class="stat">${d.today.missed}</div></div>
      <div class="card"><h3>Today — Remaining</h3><div class="stat">${d.today.remaining}</div></div>
    </div>

    <div class="grid grid-4" style="margin-top:16px;">
      <div class="card"><h3>Students on target</h3><div class="stat" style="color:var(--ok)">${d.students_on_target}</div></div>
      <div class="card"><h3>Students at risk</h3><div class="stat" style="color:var(--warn)">${d.students_at_risk}</div></div>
      <div class="card"><h3>Students behind</h3><div class="stat" style="color:var(--danger)">${d.students_behind}</div></div>
      <div class="card"><h3>Outstanding makeups</h3><div class="stat">${d.outstanding_makeups}</div></div>
    </div>

    ${CURRENT_USER.role === "provider" ? `
    <div class="grid grid-2" style="margin-top:16px;">
      <div class="card"><h3>This week</h3><div class="stat">${d.weekly_session_count}</div><div class="stat-sub">sessions scheduled</div></div>
      <div class="card"><h3>Your live status</h3><div class="stat" style="font-size:20px;">${liveLabel[d.live_status] || d.live_status}</div></div>
    </div>` : ""}

    <div class="section-title"><h3>Pending approvals</h3></div>
    <div class="card"><div class="stat">${d.pending_approvals}</div><div class="stat-sub">waiting in the approvals queue</div></div>

    ${d.provider_workload ? `
    <div class="section-title"><h3>Provider workload &amp; live status</h3></div>
    <p class="small">Click a provider to see their schedule.</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Provider</th><th>Caseload</th><th>Schools</th><th>Status</th></tr></thead>
      <tbody>
        ${d.provider_workload.map(p => `
          <tr class="clickable" data-provider-id="${p.provider_id}"><td>${p.name}</td><td>${p.caseload}</td><td>${p.schools.join(", ") || "—"}</td>
          <td>${liveLabel[p.live_status] || p.live_status}</td></tr>
        `).join("") || `<tr><td colspan="4" class="empty">No providers yet.</td></tr>`}
      </tbody>
    </table></div>` : ""}

    <div class="section-title"><h3>Students behind target this month</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Student</th><th>Completed / target</th><th>Status</th></tr></thead>
      <tbody>
        ${d.students_behind_list.map(s => `
          <tr class="clickable" data-goto="#/students/${s.student_id}">
            <td>${s.name}</td><td>${s.completed} / ${s.target}</td><td>${pacePill(s.status)}</td>
          </tr>`).join("") || `<tr><td colspan="3" class="empty">Nobody is behind pace right now.</td></tr>`}
      </tbody>
    </table></div>

    <div class="section-title"><h3>Upcoming IEP / eligibility dates (next 90 days)</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Student</th><th>IEP date</th><th>Eligibility date</th></tr></thead>
      <tbody>
        ${d.upcoming_iep_eligibility.map(s => `
          <tr class="clickable" data-goto="#/students/${s.id}">
            <td>${s.name}</td><td>${fmtDate(s.iep_date)}</td><td>${fmtDate(s.eligibility_date)}</td>
          </tr>`).join("") || `<tr><td colspan="3" class="empty">Nothing coming up.</td></tr>`}
      </tbody>
    </table></div>
  `;

  content.querySelectorAll("[data-goto]").forEach((row) => {
    row.addEventListener("click", () => { location.hash = row.dataset.goto; });
  });
  content.querySelectorAll("[data-provider-id]").forEach((row) => {
    row.addEventListener("click", () => { viewProviderSchedule(row.dataset.providerId); });
  });
}
