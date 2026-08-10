import { api } from "../api.js";

export async function renderAudit(content) {
  const { audit_log } = await api.get("/api/audit");
  content.innerHTML = `
    <div class="table-wrap"><table>
      <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Entity</th></tr></thead>
      <tbody>${audit_log.map(a => `
        <tr><td>${a.created_at.replace("T"," ").replace("Z","")}</td><td>${a.actor_name || "System"}</td>
        <td>${a.action.replace(/_/g," ")}</td><td>${a.entity_type ? `${a.entity_type} #${a.entity_id}` : "—"}</td></tr>
      `).join("") || `<tr><td colspan="4" class="empty">No activity recorded yet.</td></tr>`}</tbody>
    </table></div>
  `;
}
