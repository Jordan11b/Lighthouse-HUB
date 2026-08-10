import { api } from "../api.js";
import { fmtDate, toast } from "../utils.js";
import { CURRENT_USER } from "../main.js";

const TYPE_LABEL = {
  recurring_schedule: "Recurring schedule", cross_week_move: "Cross-week move",
  conflict_override: "Conflict override", target_adjustment: "Target adjustment",
  transfer: "Transfer", late_attendance_correction: "Late attendance correction",
  makeup_exception: "Makeup exception", emergency_change_review: "Emergency change review",
};

export async function renderApprovals(content) {
  const canDecide = CURRENT_USER.role !== "provider";
  const statusParam = canDecide ? "pending" : "all";
  const { approvals } = await api.get(`/api/approvals?status=${statusParam}`);

  content.innerHTML = `
    ${!canDecide ? `<p class="small" style="margin-bottom:14px;">Your submitted requests and their status.</p>` : ""}
    <div class="table-wrap"><table>
      <thead><tr><th>Type</th><th>Reason</th><th>Requested by</th><th>Requested</th><th>Status</th>${canDecide ? "<th></th>" : ""}</tr></thead>
      <tbody>
        ${approvals.map(a => `
          <tr>
            <td>${TYPE_LABEL[a.type] || a.type}</td>
            <td>${a.reason || "—"}</td>
            <td>${a.requested_by_name}</td>
            <td>${fmtDate(a.created_at.slice(0,10))}</td>
            <td>${a.status}</td>
            ${canDecide ? `<td>
              ${a.status === "pending" && a.requested_by !== CURRENT_USER.id ? `
                <button class="btn btn-outline btn-sm" data-approve="${a.id}">Approve</button>
                <button class="btn btn-outline btn-sm" data-reject="${a.id}">Reject</button>
              ` : a.status === "pending" ? `<span class="small">Awaiting another admin/SLP (can't approve your own)</span>` : ""}
            </td>` : ""}
          </tr>
        `).join("") || `<tr><td colspan="6" class="empty">Nothing here.</td></tr>`}
      </tbody>
    </table></div>
  `;

  content.querySelectorAll("[data-approve]").forEach(b => b.addEventListener("click", () => decide(b.dataset.approve, "approve", content)));
  content.querySelectorAll("[data-reject]").forEach(b => b.addEventListener("click", () => decide(b.dataset.reject, "reject", content)));
}

async function decide(id, decision, content) {
  const note = decision === "reject" ? prompt("Optional note for this rejection:") || "" : "";
  try {
    await api.post(`/api/approvals/${id}/decide`, { decision, note });
    toast(decision === "approve" ? "Approved." : "Rejected.");
    renderApprovals(content);
  } catch (err) { toast(err.message, true); }
}
