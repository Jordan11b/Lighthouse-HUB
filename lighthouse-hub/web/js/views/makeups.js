import { api } from "../api.js";
import { fmtDate, toast, showModal, qs } from "../utils.js";
import { CURRENT_USER } from "../main.js";

export async function renderMakeups(content) {
  const canManage = CURRENT_USER.role !== "provider";
  const [{ makeups }, refProviders] = await Promise.all([
    api.get("/api/makeups?status=open"), canManage ? api.get("/api/users?role=provider") : Promise.resolve({ users: [] }),
  ]);

  content.innerHTML = `
    <p class="small" style="margin-bottom:14px;">Provider-caused cancellations and absences that owe the student a makeup session. Student absences and school-controlled interruptions never appear here.</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Student</th><th>School</th><th>Original date</th><th>Age</th><th>Reason</th><th>Responsible provider</th><th>Proposed makeup</th><th></th></tr></thead>
      <tbody>
        ${makeups.map(m => `
          <tr>
            <td>${m.student_name}</td><td>${m.school_name}</td><td>${fmtDate(m.missed_date)}</td>
            <td>${m.age_days} day${m.age_days === 1 ? "" : "s"}</td>
            <td>${m.reason}</td><td>${m.responsible_provider_name}</td>
            <td>${m.proposed_makeup_date ? fmtDate(m.proposed_makeup_date) : "—"}</td>
            <td>
              <button class="btn btn-outline btn-sm" data-schedule="${m.id}">Schedule makeup</button>
              ${canManage ? `<button class="btn btn-outline btn-sm" data-exception="${m.id}">Request exception</button>` : ""}
            </td>
          </tr>
        `).join("") || `<tr><td colspan="8" class="empty">Nothing outstanding — nice work.</td></tr>`}
      </tbody>
    </table></div>
  `;

  content.querySelectorAll("[data-schedule]").forEach(b => b.addEventListener("click", () => {
    const m = makeups.find(x => x.id == b.dataset.schedule);
    showModal(`
      <h3>Schedule makeup for ${m.student_name}</h3>
      <form id="sched-form">
        <div class="field"><label>Date</label><input type="date" name="date" required></div>
        <div class="field"><label>Start time</label><input type="time" name="start_time" required value="09:00"></div>
        <div class="field"><label>Duration (minutes)</label><input type="number" name="duration_minutes" value="30" required></div>
        <div class="actions"><button type="button" class="btn btn-outline" id="cancel-btn">Cancel</button><button class="btn btn-primary" type="submit">Schedule</button></div>
      </form>
    `, (modal, close) => {
      modal.querySelector("#cancel-btn").addEventListener("click", close);
      modal.querySelector("#sched-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = qs(e.target);
        data.duration_minutes = parseInt(data.duration_minutes, 10);
        try {
          await api.post(`/api/makeups/${m.id}/schedule`, data);
          toast("Makeup scheduled.");
          close(); renderMakeups(content);
        } catch (err) { toast(err.message, true); }
      });
    });
  }));

  content.querySelectorAll("[data-exception]").forEach(b => b.addEventListener("click", () => {
    const m = makeups.find(x => x.id == b.dataset.exception);
    const reason = prompt(`Reason to excuse this makeup for ${m.student_name}?`);
    if (!reason) return;
    api.post(`/api/makeups/${m.id}/exception`, { reason }).then(() => {
      toast("Submitted for approval.");
      renderMakeups(content);
    }).catch(err => toast(err.message, true));
  }));
}
