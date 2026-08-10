import { api } from "../api.js";
import { fmtDate, toast, showModal, qs } from "../utils.js";
import { CURRENT_USER } from "../main.js";

export async function renderProviders(content) {
  const isAdmin = CURRENT_USER.role === "admin";
  const [{ users }, { students }, { coverage }] = await Promise.all([
    api.get("/api/users"), api.get("/api/students"), api.get("/api/coverage"),
  ]);
  const providers = users.filter(u => u.role === "provider");
  const slps = users.filter(u => u.role === "supervising_slp");
  const caseload = (id) => students.filter(s => s.provider_id === id && s.status === "active").length;
  const slpName = (id) => (slps.find(x => x.id === id) || {}).name || "—";

  content.innerHTML = `
    <div class="toolbar">
      <div class="spacer"></div>
      ${isAdmin ? `<button class="btn btn-primary" id="invite-btn">+ Invite user</button>` : ""}
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Name</th><th>Role</th><th>Credentials</th><th>License expires</th><th>Supervising SLP</th><th>Caseload</th><th>Status</th>${isAdmin ? "<th></th>" : ""}</tr></thead>
        <tbody>
          ${[...providers, ...slps].map(u => `
            <tr>
              <td>${u.name}<div class="small">${u.email}</div></td>
              <td>${u.role === "provider" ? "Provider" : "Supervising SLP"}</td>
              <td>${u.credentials || "—"}</td>
              <td>${fmtDate(u.license_expiration)}</td>
              <td>${u.role === "provider" ? slpName(u.supervising_slp_id) : "—"}</td>
              <td>${u.role === "provider" ? caseload(u.id) : "—"}</td>
              <td>${u.is_active ? "Active" : "Inactive"}</td>
              ${isAdmin ? `<td>
                <button class="btn btn-outline btn-sm" data-reset="${u.id}">Reset password</button>
                <button class="btn btn-outline btn-sm" data-toggle="${u.id}" data-active="${u.is_active}">${u.is_active ? "Deactivate" : "Reactivate"}</button>
                ${u.role === "provider" && caseload(u.id) > 0 ? `<button class="btn btn-outline btn-sm" data-bulk-transfer="${u.id}">Transfer caseload</button>` : ""}
                <button class="btn btn-outline btn-sm btn-danger" data-delete="${u.id}" data-name="${u.name}">Delete permanently</button>
              </td>` : ""}
            </tr>
          `).join("") || `<tr><td colspan="8" class="empty">No staff yet.</td></tr>`}
        </tbody>
      </table>
    </div>

    <div class="section-title"><h3>Temporary coverage</h3>
      ${CURRENT_USER.role !== "provider" ? `<button class="btn btn-outline btn-sm" id="grant-coverage">+ Grant coverage</button>` : ""}
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Covering provider</th><th>Original provider</th><th>Start</th><th>End</th><th>Reason</th></tr></thead>
      <tbody>
        ${coverage.map(c => `<tr>
          <td>${(providers.find(p => p.id === c.covering_provider_id) || {}).name || c.covering_provider_id}</td>
          <td>${(providers.find(p => p.id === c.original_provider_id) || {}).name || c.original_provider_id}</td>
          <td>${fmtDate(c.start_date)}</td><td>${fmtDate(c.end_date)}</td><td>${c.reason}</td>
        </tr>`).join("") || `<tr><td colspan="5" class="empty">No temporary coverage on file.</td></tr>`}
      </tbody>
    </table></div>
  `;

  if (isAdmin) {
    content.querySelector("#invite-btn").addEventListener("click", () => openInviteForm(slps, () => renderProviders(content)));
    content.querySelectorAll("[data-reset]").forEach(b => b.addEventListener("click", async () => {
      const resp = await api.post(`/api/users/${b.dataset.reset}/reset-password`);
      showModal(`<h3>Temporary password</h3><p>Share this with the user through a trusted channel. They'll set up MFA again on next login.</p>
        <div class="mfa-secret">${resp.temporary_password}</div>
        <div class="actions"><button class="btn btn-primary" id="ok-btn">Done</button></div>`,
        (modal, close) => modal.querySelector("#ok-btn").addEventListener("click", close));
    }));
    content.querySelectorAll("[data-toggle]").forEach(b => b.addEventListener("click", async () => {
      const active = b.dataset.active === "1" || b.dataset.active === "true";
      try {
        await api.post(`/api/users/${b.dataset.toggle}/${active ? "deactivate" : "reactivate"}`);
        toast("Updated.");
        renderProviders(content);
      } catch (err) { toast(err.message, true); }
    }));
    content.querySelectorAll("[data-bulk-transfer]").forEach(b => b.addEventListener("click", () => {
      const fromId = parseInt(b.dataset.bulkTransfer, 10);
      const fromProvider = providers.find(p => p.id === fromId);
      const others = providers.filter(p => p.id !== fromId);
      openBulkTransferForm(fromProvider, others, caseload(fromId), () => renderProviders(content));
    }));
    content.querySelectorAll("[data-delete]").forEach(b => b.addEventListener("click", async () => {
      if (!confirm(`Permanently delete ${b.dataset.name}? This can't be undone. Accounts with real service history (recorded attendance, scheduled sessions, an active caseload, etc.) will be blocked — deactivate those instead.`)) return;
      try {
        await api.del(`/api/users/${b.dataset.delete}`);
        toast(`${b.dataset.name} was permanently deleted.`);
        renderProviders(content);
      } catch (err) { toast(err.message, true); }
    }));
  }
  if (CURRENT_USER.role !== "provider") {
    content.querySelector("#grant-coverage").addEventListener("click", () => openCoverageForm(providers, () => renderProviders(content)));
  }
}

function openInviteForm(slps, onSaved) {
  showModal(`
    <h3>Invite a new user</h3>
    <form id="invite-form">
      <div class="field"><label>Full name</label><input name="name" required></div>
      <div class="field"><label>Email</label><input type="email" name="email" required></div>
      <div class="field"><label>Role</label><select name="role" id="role-select">
        <option value="provider">Provider</option>
        <option value="supervising_slp">Supervising SLP</option>
        <option value="admin">Clinic administrator</option>
      </select></div>
      <div class="field" id="slp-field"><label>Supervising SLP</label><select name="supervising_slp_id">
        <option value="">—</option>
        ${slps.map(s => `<option value="${s.id}">${s.name}</option>`).join("")}
      </select></div>
      <div class="field"><label>Credentials</label><input name="credentials" placeholder="e.g. SLP-CCC"></div>
      <div class="field"><label>License number</label><input name="license_number"></div>
      <div class="field"><label>License expiration</label><input type="date" name="license_expiration"></div>
      <div class="actions">
        <button type="button" class="btn btn-outline" id="cancel-btn">Cancel</button>
        <button type="submit" class="btn btn-primary">Send invite</button>
      </div>
    </form>
  `, (modal, close) => {
    modal.querySelector("#cancel-btn").addEventListener("click", close);
    modal.querySelector("#invite-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = qs(e.target);
      if (!data.supervising_slp_id) delete data.supervising_slp_id;
      try {
        const resp = await api.post("/api/users", data);
        modal.querySelector(".modal").innerHTML = `
          <h3>Account created</h3>
          <p>Share this temporary password with ${resp.user.name} through a trusted channel. They'll set up MFA on first login.</p>
          <div class="mfa-secret">${resp.user.temporary_password}</div>
          <div class="actions"><button class="btn btn-primary" id="ok-btn">Done</button></div>
        `;
        modal.querySelector("#ok-btn").addEventListener("click", () => { close(); onSaved(); });
      } catch (err) { toast(err.message, true); }
    });
  });
}

function openBulkTransferForm(fromProvider, others, caseloadCount, onSaved) {
  showModal(`
    <h3>Transfer ${fromProvider.name}'s caseload</h3>
    <p class="small">Moves all ${caseloadCount} active student(s) currently assigned to ${fromProvider.name} to another provider in one step — for example, when a provider leaves. Each student's future scheduled sessions are sent to the approvals queue for review; nothing is deleted.</p>
    <form id="bulk-transfer-form">
      <div class="field"><label>Receiving provider</label><select name="to_provider_id" required>
        <option value="">Select a provider…</option>
        ${others.map(p => `<option value="${p.id}">${p.name}</option>`).join("")}
      </select></div>
      <div class="field"><label>Effective date</label><input type="date" name="effective_date" value="${new Date().toISOString().slice(0,10)}" required></div>
      <div class="field"><label>Reason</label><input name="reason" placeholder="e.g. Provider left the clinic" required></div>
      <div class="actions">
        <button type="button" class="btn btn-outline" id="cancel-btn">Cancel</button>
        <button type="submit" class="btn btn-primary">Transfer caseload</button>
      </div>
    </form>
  `, (modal, close) => {
    modal.querySelector("#cancel-btn").addEventListener("click", close);
    modal.querySelector("#bulk-transfer-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = qs(e.target);
      try {
        const resp = await api.post(`/api/users/${fromProvider.id}/bulk-transfer-caseload`, data);
        toast(`Moved ${resp.students_moved} student(s). ${resp.future_sessions_needing_review} future session(s) sent for approval.`);
        close(); onSaved();
      } catch (err) { toast(err.message, true); }
    });
  });
}

function openCoverageForm(providers, onSaved) {
  showModal(`
    <h3>Grant temporary coverage</h3>
    <form id="cov-form">
      <div class="field"><label>Covering provider</label><select name="covering_provider_id" required>
        ${providers.map(p => `<option value="${p.id}">${p.name}</option>`).join("")}
      </select></div>
      <div class="field"><label>Original provider (whose caseload is covered)</label><select name="original_provider_id" required>
        ${providers.map(p => `<option value="${p.id}">${p.name}</option>`).join("")}
      </select></div>
      <div class="field"><label>Start date</label><input type="date" name="start_date" required></div>
      <div class="field"><label>End date</label><input type="date" name="end_date" required></div>
      <div class="field"><label>Reason</label><input name="reason" required></div>
      <div class="actions">
        <button type="button" class="btn btn-outline" id="cancel-btn">Cancel</button>
        <button type="submit" class="btn btn-primary">Grant coverage</button>
      </div>
    </form>
  `, (modal, close) => {
    modal.querySelector("#cancel-btn").addEventListener("click", close);
    modal.querySelector("#cov-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await api.post("/api/coverage", qs(e.target));
        toast("Coverage granted.");
        close();
        onSaved();
      } catch (err) { toast(err.message, true); }
    });
  });
}
