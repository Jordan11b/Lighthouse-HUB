import { api } from "../api.js";
import { toast } from "../utils.js";
import { CURRENT_USER } from "../main.js";

const SECTION_META = {
  urgent: { label: "Urgent", color: "red" },
  attention: { label: "Attention", color: "yellow" },
  informational: { label: "Informational", color: "blue" },
};

export async function renderAlerts(content) {
  const canManage = CURRENT_USER.role === "admin";
  const data = await api.get("/api/alerts");

  content.innerHTML = `
    ${canManage ? `
    <div class="toolbar">
      <div class="spacer"></div>
      <button class="btn btn-outline" id="run-check">Run alert check now</button>
    </div>` : ""}
    ${["urgent", "attention", "informational"].map(cat => `
      <div class="section-title"><h3><span class="badge badge-${SECTION_META[cat].color}"><span class="dot"></span>${SECTION_META[cat].label}</span></h3></div>
      <div class="table-wrap"><table>
        <tbody>
          ${data[cat].map(a => `<tr><td>${a.message}</td></tr>`).join("") || `<tr><td class="empty">Nothing here.</td></tr>`}
        </tbody>
      </table></div>
    `).join("")}
    ${canManage ? `<div id="log-section"></div>` : ""}
  `;

  if (canManage) {
    content.querySelector("#run-check").addEventListener("click", async () => {
      try {
        const resp = await api.post("/api/alerts/run-check");
        toast(`${resp.notifications_sent} notification(s) sent.`);
        loadLog();
      } catch (err) { toast(err.message, true); }
    });
    loadLog();
  }

  async function loadLog() {
    const { log } = await api.get("/api/alerts/log");
    content.querySelector("#log-section").innerHTML = `
      <div class="section-title"><h3>Simulated email outbox</h3></div>
      <p class="small">This environment can't send real email, so notifications are logged here instead — the
      content (student initials only, no diagnoses or dates) is exactly what would go out once a real mail
      provider is wired into the one delivery function in <code>lighthouse/routes_alerts.py</code>.</p>
      <div class="table-wrap"><table>
        <thead><tr><th>Sent</th><th>Category</th><th>Subject</th><th>Body</th></tr></thead>
        <tbody>${log.map(l => `<tr><td>${l.sent_at.replace("T"," ").replace("Z","")}</td><td>${l.category}</td><td>${l.subject}</td><td>${l.body}</td></tr>`).join("") || `<tr><td colspan="4" class="empty">Nothing sent yet.</td></tr>`}</tbody>
      </table></div>
    `;
  }
}
