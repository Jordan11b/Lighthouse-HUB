import { api } from "../api.js";
import { fmtDate, toast, showModal, qs } from "../utils.js";
import { CURRENT_USER } from "../main.js";

export async function renderSchools(content) {
  const isAdmin = CURRENT_USER.role === "admin";
  const { schools } = await api.get("/api/schools");
  const { students } = await api.get("/api/students");

  content.innerHTML = `
    <div class="toolbar"><div class="spacer"></div>
      ${isAdmin ? `<button class="btn btn-primary" id="new-school">+ Add school</button>` : ""}
    </div>
    <div class="grid grid-3">
      ${schools.map(s => `
        <div class="card clickable" data-id="${s.id}">
          <h3>${s.is_active ? "" : "(Inactive) "}${s.name}</h3>
          <div class="small">${s.address || "No address on file"}</div>
          <div class="small">${s.contact_name || ""} ${s.contact_phone || ""}</div>
          <div class="stat" style="font-size:22px;">${students.filter(st => st.school_id === s.id && st.status === "active").length}</div>
          <div class="stat-sub">active students</div>
        </div>
      `).join("") || `<div class="empty">No schools yet.</div>`}
    </div>
  `;
  content.querySelectorAll(".card[data-id]").forEach(c => c.addEventListener("click", () => { location.hash = `#/schools/${c.dataset.id}`; }));
  if (isAdmin) content.querySelector("#new-school").addEventListener("click", () => openSchoolForm(null, () => renderSchools(content)));
}

function openSchoolForm(existing, onSaved) {
  const s = existing || {};
  showModal(`
    <h3>${existing ? "Edit school" : "Add school"}</h3>
    <form id="school-form">
      <div class="field"><label>Name</label><input name="name" required value="${s.name || ""}"></div>
      <div class="field"><label>Address</label><input name="address" value="${s.address || ""}"></div>
      <div class="field"><label>Contact name</label><input name="contact_name" value="${s.contact_name || ""}"></div>
      <div class="field"><label>Contact phone</label><input name="contact_phone" value="${s.contact_phone || ""}"></div>
      <div class="field"><label>Hours</label><input name="hours" value="${s.hours || ""}"></div>
      <div class="actions">
        <button type="button" class="btn btn-outline" id="cancel-btn">Cancel</button>
        <button type="submit" class="btn btn-primary">${existing ? "Save" : "Add school"}</button>
      </div>
    </form>
  `, (modal, close) => {
    modal.querySelector("#cancel-btn").addEventListener("click", close);
    modal.querySelector("#school-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        if (existing) await api.patch(`/api/schools/${existing.id}`, qs(e.target));
        else await api.post("/api/schools", qs(e.target));
        toast("Saved.");
        close(); onSaved();
      } catch (err) { toast(err.message, true); }
    });
  });
}

export async function renderSchoolDetail(content, id) {
  const isAdmin = CURRENT_USER.role === "admin";
  const [{ schools }, { students }, { closures }] = await Promise.all([
    api.get("/api/schools"), api.get("/api/students"), api.get(`/api/schools/${id}/closures`),
  ]);
  const school = schools.find(s => String(s.id) === String(id));
  const roster = students.filter(s => String(s.school_id) === String(id) && s.status === "active");

  content.innerHTML = `
    <div class="toolbar"><a href="#/schools">&larr; Back to schools</a><div class="spacer"></div>
      ${isAdmin ? `<button class="btn btn-outline" id="edit-btn">Edit</button>` : ""}
    </div>
    <div class="grid grid-3">
      <div class="card"><h3>School</h3><div style="font-size:20px;font-weight:700;">${school.name}</div><div class="small">${school.address || "—"}</div></div>
      <div class="card"><h3>Contact</h3><div>${school.contact_name || "—"}</div><div class="small">${school.contact_phone || ""} ${school.contact_email || ""}</div></div>
      <div class="card"><h3>Hours</h3><div>${school.hours || "—"}</div></div>
    </div>

    <div class="section-title"><h3>Active roster (${roster.length})</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Student</th><th>Grade</th><th>Frequency</th></tr></thead>
      <tbody>${roster.map(s => `<tr class="clickable" data-id="${s.id}"><td>${s.name}</td><td>${s.grade || "—"}</td><td>${s.sessions_per_week}x/wk · ${s.duration_minutes}min</td></tr>`).join("") || `<tr><td colspan="3" class="empty">No active students.</td></tr>`}</tbody>
    </table></div>

    <div class="section-title"><h3>Closures &amp; calendar exceptions</h3>
      ${CURRENT_USER.role !== "provider" ? `<button class="btn btn-outline btn-sm" id="add-closure">+ Add closure</button>` : ""}
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Date</th><th>Reason</th></tr></thead>
      <tbody>${closures.map(c => `<tr><td>${fmtDate(c.closure_date)}</td><td>${c.reason || "—"}</td></tr>`).join("") || `<tr><td colspan="2" class="empty">No closures on file.</td></tr>`}</tbody>
    </table></div>
  `;
  content.querySelectorAll("[data-id]").forEach(r => r.addEventListener("click", () => { location.hash = `#/students/${r.dataset.id}`; }));
  if (isAdmin) content.querySelector("#edit-btn").addEventListener("click", () => openSchoolForm(school, () => renderSchoolDetail(content, id)));
  const closureBtn = content.querySelector("#add-closure");
  if (closureBtn) closureBtn.addEventListener("click", () => {
    showModal(`
      <h3>Add closure</h3>
      <form id="closure-form">
        <div class="field"><label>Date</label><input type="date" name="date" required></div>
        <div class="field"><label>Reason</label><input name="reason" placeholder="e.g. Winter break"></div>
        <div class="actions"><button type="button" class="btn btn-outline" id="cancel-btn">Cancel</button><button class="btn btn-primary" type="submit">Add</button></div>
      </form>
    `, (modal, close) => {
      modal.querySelector("#cancel-btn").addEventListener("click", close);
      modal.querySelector("#closure-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        await api.post(`/api/schools/${id}/closures`, qs(e.target));
        close();
        renderSchoolDetail(content, id);
      });
    });
  });
}
