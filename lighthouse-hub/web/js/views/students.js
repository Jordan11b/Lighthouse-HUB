import { api } from "../api.js";
import { el, fmtDate, pacePill, toast, showModal, qs } from "../utils.js";
import { CURRENT_USER } from "../main.js";

async function loadRefData() {
  const [schools, providers] = await Promise.all([
    api.get("/api/schools"), api.get("/api/users?role=provider"),
  ]);
  return { schools: schools.schools, providers: providers.users };
}

export async function renderStudents(content) {
  const canEdit = CURRENT_USER.role !== "provider";
  // Archived students are excluded by the API by default (e.g. after a merge); "All statuses"
  // fetches everything so archived/merged records can still be found and reviewed.
  const [{ students: activeStudents }, { students: allStudents }, ref] = await Promise.all([
    api.get("/api/students"), api.get("/api/students?status=all"), loadRefData(),
  ]);

  content.innerHTML = `
    <div class="toolbar">
      <input class="search" id="q" placeholder="Search students…">
      <select id="filter-school"><option value="">All schools</option>
        ${ref.schools.map(s => `<option value="${s.id}">${s.code ? `${s.code} — ` : ""}${s.name}</option>`).join("")}</select>
      <select id="filter-status">
        <option value="">Active + inactive</option>
        <option value="all">All statuses (incl. archived)</option>
        <option value="archived">Archived only</option>
      </select>
      <div class="spacer"></div>
      <button class="btn btn-primary" id="new-student">+ Add student</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Name</th><th>School</th><th>Grade</th><th>Provider</th><th>Frequency</th><th>Type</th><th>Status</th></tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
  `;

  const providerName = (id) => (ref.providers.find(p => p.id === id) || {}).name || "Unassigned";
  const schoolName = (id) => (ref.schools.find(s => s.id === id) || {}).name || "—";

  function draw() {
    const q = content.querySelector("#q").value.toLowerCase();
    const schoolFilter = content.querySelector("#filter-school").value;
    const statusFilter = content.querySelector("#filter-status").value;
    let pool = statusFilter === "" ? activeStudents : allStudents;
    if (statusFilter === "archived") pool = pool.filter(s => s.status === "archived");
    const rows = pool.filter(s =>
      (!q || s.name.toLowerCase().includes(q)) &&
      (!schoolFilter || String(s.school_id) === schoolFilter)
    );
    content.querySelector("#rows").innerHTML = rows.map(s => `
      <tr class="clickable" data-id="${s.id}">
        <td>${s.name}</td><td>${schoolName(s.school_id)}</td><td>${s.grade || "—"}</td>
        <td>${providerName(s.provider_id)}</td>
        <td>${s.sessions_per_week}x/wk · ${s.duration_minutes}min</td>
        <td>${s.is_group ? "Group" : "Individual"}</td>
        <td>${s.status}</td>
      </tr>
    `).join("") || `<tr><td colspan="7" class="empty">No students match.</td></tr>`;
    content.querySelectorAll("#rows tr[data-id]").forEach(r => {
      r.addEventListener("click", () => { location.hash = `#/students/${r.dataset.id}`; });
    });
  }
  draw();
  content.querySelector("#q").addEventListener("input", draw);
  content.querySelector("#filter-school").addEventListener("change", draw);
  content.querySelector("#filter-status").addEventListener("change", draw);

  content.querySelector("#new-student").addEventListener("click", () => openStudentForm(ref, null, () => renderStudents(content)));
}

function openStudentForm(ref, existing, onSaved) {
  const s = existing || {};
  const isProvider = CURRENT_USER.role === "provider";
  const lockProviderToSelf = isProvider && !existing;
  showModal(`
    <h3>${existing ? "Edit student" : "Add student"}</h3>
    ${lockProviderToSelf ? `<div class="info-box">This will be added to your caseload and sent to your clinic administrator for review.</div>` : ""}
    <form id="student-form">
      <div class="grid grid-2">
        <div class="field"><label>Full name</label><input name="name" required value="${s.name || ""}"></div>
        <div class="field"><label>Student ID</label><input name="student_ext_id" value="${s.student_ext_id || ""}"></div>
        <div class="field"><label>School</label><select name="school_id" required>
          ${ref.schools.map(sc => `<option value="${sc.id}" ${s.school_id === sc.id ? "selected" : ""}>${sc.code ? `${sc.code} — ` : ""}${sc.name}</option>`).join("")}
        </select></div>
        <div class="field"><label>Grade</label><input name="grade" value="${s.grade || ""}"></div>
        <div class="field"><label>Disability / diagnosis</label><input name="disability" value="${s.disability || ""}"></div>
        ${lockProviderToSelf ? `<div class="field"><label>Provider</label><input value="${CURRENT_USER.name} (you)" disabled></div>` : `
        <div class="field"><label>Provider</label><select name="provider_id">
          <option value="">Unassigned</option>
          ${ref.providers.map(p => `<option value="${p.id}" ${s.provider_id === p.id ? "selected" : ""}>${p.name}</option>`).join("")}
        </select></div>`}
        <div class="field"><label>Eligibility date</label><input type="date" name="eligibility_date" value="${(s.eligibility_date||"").slice(0,10)}"></div>
        <div class="field"><label>IEP date</label><input type="date" name="iep_date" value="${(s.iep_date||"").slice(0,10)}"></div>
        <div class="field"><label>Service start</label><input type="date" name="service_start" value="${(s.service_start||"").slice(0,10)}"></div>
        <div class="field"><label>Service end</label><input type="date" name="service_end" value="${(s.service_end||"").slice(0,10)}"></div>
        <div class="field"><label>Sessions / week</label><input type="number" step="0.5" min="0" name="sessions_per_week" value="${s.sessions_per_week || 1}"></div>
        <div class="field"><label>Duration (minutes)</label><input type="number" min="5" name="duration_minutes" value="${s.duration_minutes || 30}"></div>
        <div class="field"><label>Individual or group</label><select name="group_individual">
          <option value="individual" ${s.group_individual!=="group"?"selected":""}>Individual</option>
          <option value="group" ${s.group_individual==="group"?"selected":""}>Group</option>
        </select></div>
        <div class="field"><label>Status</label><select name="status">
          <option value="active" ${s.status==="active"?"selected":""}>Active</option>
          <option value="inactive" ${s.status==="inactive"?"selected":""}>Inactive</option>
          <option value="archived" ${s.status==="archived"?"selected":""}>Archived</option>
        </select></div>
      </div>
      <div class="field"><label>Administrative comments</label><textarea name="comments" rows="2">${s.comments || ""}</textarea></div>
      <div class="actions">
        <button type="button" class="btn btn-outline" id="cancel-btn">Cancel</button>
        <button type="submit" class="btn btn-primary">${existing ? "Save changes" : "Add student"}</button>
      </div>
    </form>
  `, (modal, close) => {
    modal.querySelector("#cancel-btn").addEventListener("click", close);
    modal.querySelector("#student-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = qs(e.target);
      data.sessions_per_week = parseFloat(data.sessions_per_week);
      data.duration_minutes = parseInt(data.duration_minutes, 10);
      if (!data.provider_id) delete data.provider_id;
      try {
        if (existing) await api.patch(`/api/students/${existing.id}`, data);
        else await api.post("/api/students", data);
        toast(existing ? "Student updated." : (lockProviderToSelf ? "Student added — your admin has been notified." : "Student added."));
        close();
        onSaved();
      } catch (err) { toast(err.message, true); }
    });
  });
}

export async function renderStudentDetail(content, id) {
  const canEdit = CURRENT_USER.role !== "provider";
  const [{ student, months, transfers, upcoming_sessions }, ref] = await Promise.all([
    api.get(`/api/students/${id}`), loadRefData(),
  ]);
  const school = ref.schools.find(s => s.id === student.school_id);
  const provider = ref.providers.find(p => p.id === student.provider_id);
  const thisMonth = months.find(m => m.status !== "not_yet_due") ? months.find(m => new Date(m.month + "-01") <= new Date()) : months[0];
  const currentMonth = new Date().toISOString().slice(0, 7);
  const cm = months.find(m => m.month === currentMonth) || months[0];

  content.innerHTML = `
    <div class="toolbar">
      <a href="#/students">&larr; Back to students</a>
      <div class="spacer"></div>
      ${canEdit && student.status !== "archived" ? `<button class="btn btn-outline" id="edit-btn">Edit</button>
      <button class="btn btn-outline" id="transfer-btn">Transfer</button>
      <button class="btn btn-outline" id="merge-btn">Merge duplicate…</button>` : ""}
    </div>
    ${student.status === "archived" ? `<div class="info-box">This record is archived${student.comments && student.comments.includes("Merged into") ? " — merged into another record." : "."}</div>` : ""}

    <div class="grid grid-3">
      <div class="card">
        <h3>Student</h3>
        <div style="font-size:20px;font-weight:700;margin:4px 0;">${student.name}</div>
        <div class="small">${student.student_ext_id || "No ID on file"} · Grade ${student.grade || "—"}</div>
        <div class="small" style="margin-top:8px;">${student.disability || "No diagnosis on file"}</div>
      </div>
      <div class="card">
        <h3>Assignment</h3>
        <div>${school ? `${school.name}${school.code ? ` (${school.code})` : ""}` : "—"}</div>
        <div class="small">Provider: ${provider ? provider.name : "Unassigned"}</div>
        <div class="small">${student.sessions_per_week}x/week · ${student.duration_minutes} min · ${student.is_group ? "Group" : "Individual"}</div>
      </div>
      <div class="card">
        <h3>Dates</h3>
        <div class="small">Eligibility: ${fmtDate(student.eligibility_date)}</div>
        <div class="small">IEP: ${fmtDate(student.iep_date)}</div>
        <div class="small">Service: ${fmtDate(student.service_start)} – ${fmtDate(student.service_end)}</div>
      </div>
    </div>

    ${cm ? `
    <div class="section-title"><h3>This month (${cm.month})</h3></div>
    <div class="grid grid-4">
      <div class="card"><h3>Target</h3><div class="stat">${cm.target}</div>${cm.is_prorated ? `<div class="stat-sub">Standard ${cm.standard_target}, prorated (${cm.active_days}/${cm.days_in_month} active days)</div>` : `<div class="stat-sub">Standard month</div>`}</div>
      <div class="card"><h3>Completed</h3><div class="stat">${cm.completed}</div></div>
      <div class="card"><h3>Remaining</h3><div class="stat">${cm.remaining}</div></div>
      <div class="card"><h3>Status</h3><div style="margin-top:8px;">${pacePill(cm.status)}</div><div class="stat-sub">${cm.compliance_pct}% of monthly target</div></div>
    </div>` : ""}

    <div class="section-title"><h3>Monthly compliance — school year</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Month</th><th>Target</th><th>Completed</th><th>Excused</th><th>Provider-caused</th><th>Makeup needed</th><th>Status</th></tr></thead>
      <tbody>
        ${months.map(m => `<tr><td>${m.month}${m.is_prorated ? " *" : ""}</td><td>${m.target}</td><td>${m.completed}</td><td>${m.excused}</td><td>${m.cancelled_by_provider}</td><td>${m.makeup_needed}</td><td>${pacePill(m.status)}</td></tr>`).join("")}
      </tbody>
    </table></div>
    <p class="small">* Prorated for a partial month of service (rounded up to a whole session).</p>

    <div class="section-title"><h3>Upcoming sessions</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Date</th><th>Time</th><th>Duration</th><th>Status</th></tr></thead>
      <tbody>
        ${upcoming_sessions.map(s => `<tr><td>${fmtDate(s.session_date)}</td><td>${s.start_time}</td><td>${s.duration_minutes} min</td><td>${s.status}</td></tr>`).join("") || `<tr><td colspan="4" class="empty">Nothing scheduled.</td></tr>`}
      </tbody>
    </table></div>

    ${transfers.length ? `
    <div class="section-title"><h3>Transfer history</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Effective date</th><th>Reason</th></tr></thead>
      <tbody>${transfers.map(t => `<tr><td>${fmtDate(t.effective_date)}</td><td>${t.reason || "—"}</td></tr>`).join("")}</tbody>
    </table></div>` : ""}

    ${student.comments ? `<div class="section-title"><h3>Administrative comments</h3></div><div class="card">${student.comments}</div>` : ""}
  `;

  if (canEdit && student.status !== "archived") {
    content.querySelector("#edit-btn").addEventListener("click", () => openStudentForm(ref, student, () => renderStudentDetail(content, id)));
    content.querySelector("#transfer-btn").addEventListener("click", () => openTransferForm(ref, student, () => renderStudentDetail(content, id)));
    content.querySelector("#merge-btn").addEventListener("click", async () => {
      const { students: all } = await api.get("/api/students?status=all");
      const candidates = all.filter(s => s.id !== student.id && s.status !== "archived");
      openMergeForm(student, candidates, () => renderStudentDetail(content, id));
    });
  }
}

function openMergeForm(student, candidates, onSaved) {
  showModal(`
    <h3>Merge a duplicate into ${student.name}</h3>
    <p class="small">Pick the duplicate record. Its attendance, schedule, and makeup history move over to ${student.name} (the survivor), and the duplicate is archived, not deleted, so nothing is lost. If both records happen to share the exact same session, ${student.name}'s copy of that record is kept and the duplicate's is discarded.</p>
    <form id="merge-form">
      <div class="field"><label>Duplicate record to merge in</label><select name="duplicate_student_id" required>
        <option value="">Select a student…</option>
        ${candidates.map(c => `<option value="${c.id}">${c.name}${c.student_ext_id ? ` (${c.student_ext_id})` : ""}</option>`).join("")}
      </select></div>
      <div class="field"><label>Reason</label><input name="reason" placeholder="e.g. Duplicate record from Excel import" required></div>
      <div class="actions">
        <button type="button" class="btn btn-outline" id="cancel-btn">Cancel</button>
        <button type="submit" class="btn btn-primary">Merge</button>
      </div>
    </form>
  `, (modal, close) => {
    modal.querySelector("#cancel-btn").addEventListener("click", close);
    modal.querySelector("#merge-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = qs(e.target);
      if (!confirm(`This will archive the duplicate record and move its history into ${student.name}. This can't be undone from the UI. Continue?`)) return;
      try {
        const resp = await api.post(`/api/students/${student.id}/merge`, data);
        toast(`Merged. ${resp.moved_sessions} session(s) and ${resp.moved_attendance} attendance record(s) moved over.`);
        close();
        onSaved();
      } catch (err) { toast(err.message, true); }
    });
  });
}

function openTransferForm(ref, student, onSaved) {
  showModal(`
    <h3>Transfer ${student.name}</h3>
    <p class="small">Past records stay with the original provider and school. Future appointments under the old assignment are sent to the approvals queue for review.</p>
    <form id="transfer-form">
      <div class="field"><label>New provider</label><select name="to_provider_id">
        <option value="">No change</option>
        ${ref.providers.map(p => `<option value="${p.id}">${p.name}</option>`).join("")}
      </select></div>
      <div class="field"><label>New school</label><select name="to_school_id">
        <option value="">No change</option>
        ${ref.schools.map(s => `<option value="${s.id}">${s.code ? `${s.code} — ` : ""}${s.name}</option>`).join("")}
      </select></div>
      <div class="field"><label>Effective date</label><input type="date" name="effective_date" required></div>
      <div class="field"><label>Reason</label><input name="reason" required></div>
      <div class="actions">
        <button type="button" class="btn btn-outline" id="cancel-btn">Cancel</button>
        <button type="submit" class="btn btn-primary">Transfer</button>
      </div>
    </form>
  `, (modal, close) => {
    modal.querySelector("#cancel-btn").addEventListener("click", close);
    modal.querySelector("#transfer-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = qs(e.target);
      if (!data.to_provider_id) delete data.to_provider_id;
      if (!data.to_school_id) delete data.to_school_id;
      try {
        const resp = await api.post(`/api/students/${student.id}/transfer`, data);
        toast(`Transfer recorded. ${resp.future_sessions_needing_review} future session(s) sent for review.`);
        close();
        onSaved();
      } catch (err) { toast(err.message, true); }
    });
  });
}
