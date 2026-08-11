import { api } from "../api.js";
import { el, fmtDay, fmtTime, todayISO, addDaysISO, statusBadge, resultLabel, ATTENDANCE_RESULTS, toast, showModal, qs } from "../utils.js";
import { CURRENT_USER } from "../main.js";

function mondayOf(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  const day = d.getDay(); // 0=Sun
  const diff = day === 0 ? -6 : 1 - day;
  d.setDate(d.getDate() + diff);
  return d.toISOString().slice(0, 10);
}

let weekStart = mondayOf(todayISO());
export let filterProviderId = "";

/** Called from other views (e.g. the Dashboard's provider workload table) to jump
 * straight to one provider's schedule instead of the whole clinic's. */
export function viewProviderSchedule(providerId) {
  filterProviderId = String(providerId);
  location.hash = "#/schedule";
}

export async function renderSchedule(content) {
  const canManage = CURRENT_USER.role !== "provider";
  const [refProviders, refSchools, refStudents] = await Promise.all([
    canManage ? api.get("/api/users?role=provider") : Promise.resolve({ users: [] }),
    api.get("/api/schools"),
    api.get("/api/students"),
  ]);
  const weekEnd = addDaysISO(weekStart, 6);
  const providerQs = canManage && filterProviderId ? `&provider_id=${filterProviderId}` : "";
  const { sessions } = await api.get(`/api/schedule?start=${weekStart}&end=${weekEnd}${providerQs}`);

  const byDay = {};
  for (let i = 0; i < 7; i++) {
    const d = addDaysISO(weekStart, i);
    byDay[d] = sessions.filter(s => s.session_date === d).sort((a, b) => a.start_time.localeCompare(b.start_time));
  }

  content.innerHTML = `
    <div class="toolbar">
      <button class="btn btn-outline btn-sm" id="prev-week">&larr; Prior week</button>
      <div style="font-weight:700;">${fmtDay(weekStart)} – ${fmtDay(weekEnd)}</div>
      <button class="btn btn-outline btn-sm" id="next-week">Next week &rarr;</button>
      ${canManage ? `
      <select id="provider-filter">
        <option value="">All providers</option>
        ${refProviders.users.map(p => `<option value="${p.id}" ${String(p.id) === filterProviderId ? "selected" : ""}>${p.name}</option>`).join("")}
      </select>` : ""}
      <div class="spacer"></div>
      <button class="btn btn-outline" id="propose-recurring">+ Recurring schedule</button>
      <button class="btn btn-primary" id="new-session">+ New session</button>
    </div>
    <div id="days"></div>
  `;

  if (canManage) {
    content.querySelector("#provider-filter").addEventListener("change", (e) => {
      filterProviderId = e.target.value;
      renderSchedule(content);
    });
  }

  const daysEl = content.querySelector("#days");
  daysEl.innerHTML = Object.entries(byDay).map(([date, list]) => `
    <div class="day-group">
      <div class="day-label">${fmtDay(date)}</div>
      ${list.map(s => `
        <div class="session-row" data-id="${s.id}">
          <div class="time">${fmtTime(s.start_time)}</div>
          <div class="who">
            <div class="students">${s.students.map(st => st.name).join(", ")}</div>
            <div class="meta">${s.provider_name} · ${s.school_name} · ${s.duration_minutes} min ${s.session_type === "group" ? "· group" : ""}</div>
          </div>
          <div>${statusBadge(s.status)}</div>
          <div class="acts">
            <button class="btn btn-outline btn-sm" data-attend="${s.id}">Attendance</button>
            <button class="btn btn-outline btn-sm" data-reschedule="${s.id}">Reschedule</button>
          </div>
        </div>
      `).join("") || `<div class="small" style="padding:6px 2px;">No sessions.</div>`}
    </div>
  `).join("");

  content.querySelector("#prev-week").addEventListener("click", () => { weekStart = addDaysISO(weekStart, -7); renderSchedule(content); });
  content.querySelector("#next-week").addEventListener("click", () => { weekStart = addDaysISO(weekStart, 7); renderSchedule(content); });

  content.querySelectorAll("[data-attend]").forEach(b => b.addEventListener("click", () => {
    const session = sessions.find(s => s.id == b.dataset.attend);
    openAttendanceModal(session, () => renderSchedule(content));
  }));
  content.querySelectorAll("[data-reschedule]").forEach(b => b.addEventListener("click", () => {
    const session = sessions.find(s => s.id == b.dataset.reschedule);
    openRescheduleModal(session, () => renderSchedule(content));
  }));

  content.querySelector("#new-session").addEventListener("click", () =>
    openNewSessionModal(refProviders.users, refSchools.schools, refStudents.students, () => renderSchedule(content)));
  content.querySelector("#propose-recurring").addEventListener("click", () =>
    openRecurringModal(refProviders.users, refSchools.schools, refStudents.students, () => renderSchedule(content)));
}

function openNewSessionModal(providers, schools, students, onSaved) {
  const isProviderOnly = CURRENT_USER.role === "provider";
  const providerOptions = isProviderOnly
    ? `<option value="${CURRENT_USER.id}">${CURRENT_USER.name}</option>`
    : providers.map(p => `<option value="${p.id}">${p.name}</option>`).join("");
  showModal(`
    <h3>New session</h3>
    <form id="session-form">
      <div class="field"><label>Provider</label><select name="provider_id" ${isProviderOnly ? "disabled" : ""}>${providerOptions}</select></div>
      <div class="field"><label>Type</label><select name="session_type" id="type-select">
        <option value="individual">Individual</option><option value="group">Group</option>
      </select></div>
      <div class="field" id="student-field"><label>Student</label><select name="student_id">
        ${students.map(s => `<option value="${s.id}">${s.name}</option>`).join("")}
      </select></div>
      <div class="field" id="students-field" style="display:none;"><label>Students (group)</label>
        <select name="student_ids" multiple size="6">${students.map(s => `<option value="${s.id}">${s.name}</option>`).join("")}</select>
      </div>
      <div class="field"><label>School</label><select name="school_id">${schools.map(s => `<option value="${s.id}">${s.code ? `${s.code} — ` : ""}${s.name}</option>`).join("")}</select></div>
      <div class="field"><label>Date</label><input type="date" name="date" required value="${todayISO()}"></div>
      <div class="field"><label>Start time</label><input type="time" name="start_time" required value="09:00"></div>
      <div class="field"><label>Duration (minutes)</label><input type="number" name="duration_minutes" value="30" min="5" required></div>
      <div class="actions">
        <button type="button" class="btn btn-outline" id="cancel-btn">Cancel</button>
        <button type="submit" class="btn btn-primary">Create</button>
      </div>
    </form>
  `, (modal, close) => {
    modal.querySelector("#cancel-btn").addEventListener("click", close);
    modal.querySelector("#type-select").addEventListener("change", (e) => {
      const isGroup = e.target.value === "group";
      modal.querySelector("#student-field").style.display = isGroup ? "none" : "";
      modal.querySelector("#students-field").style.display = isGroup ? "" : "none";
    });
    modal.querySelector("#session-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = e.target;
      const isGroup = form.session_type.value === "group";
      const payload = {
        provider_id: parseInt(form.provider_id.value, 10),
        school_id: parseInt(form.school_id.value, 10),
        date: form.date.value,
        start_time: form.start_time.value,
        duration_minutes: parseInt(form.duration_minutes.value, 10),
        session_type: form.session_type.value,
      };
      if (isGroup) {
        payload.student_ids = Array.from(form.student_ids.selectedOptions).map(o => parseInt(o.value, 10));
      } else {
        payload.student_id = parseInt(form.student_id.value, 10);
      }
      try {
        await api.post("/api/schedule", payload);
        toast("Session created.");
        close(); onSaved();
      } catch (err) {
        if (err.status === 409) {
          if (confirm(`${err.message}. Override with a recorded reason? (goes to the approvals queue)`)) {
            const reason = prompt("Reason for overriding this conflict:");
            if (reason) {
              try {
                await api.post("/api/schedule", { ...payload, override_reason: reason });
                toast("Submitted for conflict-override approval.");
                close(); onSaved();
              } catch (err2) { toast(err2.message, true); }
            }
          }
        } else {
          toast(err.message, true);
        }
      }
    });
  });
}

function openRescheduleModal(session, onSaved) {
  showModal(`
    <h3>Reschedule session</h3>
    <p class="small">Moving within the same week applies immediately. Moving to another week or month is sent for approval (unless marked urgent).</p>
    <form id="resched-form">
      <div class="field"><label>New date</label><input type="date" name="new_date" required value="${session.session_date}"></div>
      <div class="field"><label>New start time</label><input type="time" name="new_start_time" required value="${session.start_time.slice(0,5)}"></div>
      <div class="field"><label>Reason</label><input name="reason" required></div>
      <div class="field"><label><input type="checkbox" name="urgent" value="1" style="width:auto;display:inline-block;margin-right:6px;">Urgent same-day change (apply immediately, review later)</label></div>
      <div class="actions">
        <button type="button" class="btn btn-outline" id="cancel-btn">Cancel</button>
        <button type="submit" class="btn btn-primary">Save</button>
      </div>
    </form>
  `, (modal, close) => {
    modal.querySelector("#cancel-btn").addEventListener("click", close);
    modal.querySelector("#resched-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = qs(e.target);
      data.urgent = !!data.urgent;
      try {
        const resp = await api.patch(`/api/schedule/${session.id}/reschedule`, data);
        toast(resp.applied_immediately ? "Session rescheduled." : "Submitted for approval.");
        close(); onSaved();
      } catch (err) { toast(err.message, true); }
    });
  });
}

async function openAttendanceModal(session, onSaved) {
  const { attendance } = await api.get(`/api/attendance?session_id=${session.id}`);
  const existingFor = (sid) => attendance.find(a => a.student_id === sid);

  showModal(`
    <h3>Attendance — ${session.students.map(s => s.name).join(", ")}</h3>
    <div class="small" style="margin-bottom:12px;">${session.session_date} at ${fmtTime(session.start_time)} · ${session.provider_name} · ${session.school_name}</div>
    <form id="att-form">
      ${session.students.map(st => {
        const ex = existingFor(st.id);
        return `
        <div class="card" style="margin-bottom:10px;">
          <h3>${st.name}</h3>
          <div class="field"><label>Result</label><select name="result_${st.id}">
            ${ATTENDANCE_RESULTS.map(r => `<option value="${r}" ${ex && ex.result === r ? "selected" : ""}>${resultLabel(r)}</option>`).join("")}
          </select></div>
          <div class="grid grid-2">
            <div class="field"><label>Actual time</label><input type="time" name="time_${st.id}" value="${ex && ex.actual_time ? ex.actual_time.slice(0,5) : session.start_time.slice(0,5)}"></div>
            <div class="field"><label>Actual duration (min)</label><input type="number" name="dur_${st.id}" value="${ex && ex.actual_duration_minutes ? ex.actual_duration_minutes : session.duration_minutes}"></div>
          </div>
          <div class="field"><label>Comment (optional)</label><input name="comment_${st.id}" value="${ex && ex.admin_comment ? ex.admin_comment : ""}"></div>
          ${ex && ex.locked ? `<div class="small">This record is locked (past service date) — saving will submit a correction request for approval.</div>` : ""}
        </div>`;
      }).join("")}
      <div class="actions">
        <button type="button" class="btn btn-outline" id="cancel-btn">Cancel</button>
        <button type="submit" class="btn btn-primary">Save attendance</button>
      </div>
    </form>
  `, (modal, close) => {
    modal.querySelector("#cancel-btn").addEventListener("click", close);
    modal.querySelector("#att-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = e.target;
      let pendingCount = 0;
      try {
        for (const st of session.students) {
          const result = form[`result_${st.id}`].value;
          const time = form[`time_${st.id}`].value;
          const dur = form[`dur_${st.id}`].value;
          const comment = form[`comment_${st.id}`].value;
          const payload = {
            session_id: session.id, student_id: st.id, result,
            actual_time: time, actual_duration_minutes: dur ? parseInt(dur, 10) : null,
            admin_comment: comment || null,
          };
          let resp;
          try {
            resp = await api.post("/api/attendance", payload);
          } catch (err) {
            if (err.status === 409 && err.extra && err.extra.requires_confirmation) {
              // Likely overlapping coverage: someone else already recorded a different result.
              if (!confirm(`${err.message}\n\nOverwrite it?`)) continue;
              resp = await api.post("/api/attendance", { ...payload, confirm_conflict: true });
            } else {
              throw err;
            }
          }
          if (resp && resp.pending_approval) pendingCount++;
        }
        toast(pendingCount ? `Saved. ${pendingCount} correction(s) sent for approval.` : "Attendance saved.");
        close(); onSaved();
      } catch (err) { toast(err.message, true); }
    });
  });
}

function openRecurringModal(providers, schools, students, onSaved) {
  const isProviderOnly = CURRENT_USER.role === "provider";
  const providerOptions = isProviderOnly
    ? `<option value="${CURRENT_USER.id}">${CURRENT_USER.name}</option>`
    : providers.map(p => `<option value="${p.id}">${p.name}</option>`).join("");
  showModal(`
    <h3>Propose recurring schedule</h3>
    <p class="small">Recurring schedules take effect after approval, and stop automatically at the student's service end or IEP end date, whichever comes first.</p>
    <form id="rec-form">
      <div class="field"><label>Student</label><select name="student_id">${students.map(s => `<option value="${s.id}">${s.name}</option>`).join("")}</select></div>
      <div class="field"><label>Provider</label><select name="provider_id" ${isProviderOnly ? "disabled" : ""}>${providerOptions}</select></div>
      <div class="field"><label>School</label><select name="school_id">${schools.map(s => `<option value="${s.id}">${s.code ? `${s.code} — ` : ""}${s.name}</option>`).join("")}</select></div>
      <div class="field"><label>Day of week</label><select name="day_of_week">
        <option value="0">Monday</option><option value="1">Tuesday</option><option value="2">Wednesday</option>
        <option value="3">Thursday</option><option value="4">Friday</option>
      </select></div>
      <div class="field"><label>Start time</label><input type="time" name="start_time" value="09:00" required></div>
      <div class="field"><label>Duration (minutes)</label><input type="number" name="duration_minutes" value="30" required></div>
      <div class="field"><label>Effective start</label><input type="date" name="effective_start" required value="${todayISO()}"></div>
      <div class="field"><label>Reason</label><input name="reason" placeholder="Why this schedule?"></div>
      <div class="actions">
        <button type="button" class="btn btn-outline" id="cancel-btn">Cancel</button>
        <button type="submit" class="btn btn-primary">Submit for approval</button>
      </div>
    </form>
  `, (modal, close) => {
    modal.querySelector("#cancel-btn").addEventListener("click", close);
    modal.querySelector("#rec-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = qs(e.target);
      data.student_id = parseInt(data.student_id, 10);
      data.provider_id = parseInt(isProviderOnly ? CURRENT_USER.id : data.provider_id, 10);
      data.school_id = parseInt(data.school_id, 10);
      data.day_of_week = parseInt(data.day_of_week, 10);
      data.duration_minutes = parseInt(data.duration_minutes, 10);
      try {
        await api.post("/api/recurring", data);
        toast("Submitted for approval.");
        close(); onSaved();
      } catch (err) { toast(err.message, true); }
    });
  });
}
