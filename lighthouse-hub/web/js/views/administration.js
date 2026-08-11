import { api } from "../api.js";
import { fmtDate, resultLabel, ATTENDANCE_RESULTS, toast, showModal, qs } from "../utils.js";

const MAKEUP_REQUIRED = new Set(["provider_absent", "provider_cancelled"]);

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",")[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export async function renderAdministration(content) {
  const [settingsResp, { imports }] = await Promise.all([api.get("/api/settings"), api.get("/api/imports")]);
  const { settings, env_overridden, email_configured } = settingsResp;

  content.innerHTML = `
    <div class="tabs">
      <button class="active" data-tab="settings">Settings</button>
      <button data-tab="import">Roster Import</button>
      <button data-tab="reference">Attendance &amp; Cancellation Reasons</button>
    </div>
    <div id="tab-body"></div>
  `;

  const tabs = content.querySelectorAll(".tabs button");
  tabs.forEach(t => t.addEventListener("click", () => {
    tabs.forEach(x => x.classList.remove("active"));
    t.classList.add("active");
    draw(t.dataset.tab);
  }));

  function draw(tab) {
    const body = content.querySelector("#tab-body");
    if (tab === "settings") drawSettings(body);
    else if (tab === "import") drawImport(body);
    else drawReference(body);
  }

  function drawSettings(body) {
    const isEnvSet = (key) => (env_overridden || []).includes(key);
    const smtpField = (key, label, type = "text", extra = "") => `
      <div class="field">
        <label>${label}${isEnvSet(key) ? ` <span class="small">(set by ${key.toUpperCase()} environment variable — the field below is ignored)</span>` : ""}</label>
        <input type="${type}" name="${key}" value="${settings[key] || ""}" ${isEnvSet(key) ? "disabled" : ""} ${extra}>
      </div>`;
    // The password field is a special case: the server only ever sends back a masked
    // placeholder (never the real saved password), so pre-filling the input's actual value
    // with that mask caused browser password managers to fight with what you typed over it.
    // Leave it blank instead - the placeholder text just indicates whether one's on file.
    const passwordSet = !!settings.smtp_password; // masked value if set, empty if not
    const smtpPasswordField = `
      <div class="field">
        <label>Password${isEnvSet("smtp_password") ? ` <span class="small">(set by SMTP_PASSWORD environment variable — the field below is ignored)</span>` : ""}</label>
        <input type="password" name="smtp_password" autocomplete="new-password"
          placeholder="${isEnvSet("smtp_password") ? "" : passwordSet ? "Currently set — leave blank to keep it" : "App password, not your regular login password"}"
          ${isEnvSet("smtp_password") ? "disabled" : ""}>
      </div>`;
    body.innerHTML = `
      <div class="card" style="max-width:520px;">
        <h3>School year</h3>
        <form id="settings-form">
          <div class="field"><label>School year start</label><input type="date" name="school_year_start" value="${settings.school_year_start || ""}"></div>
          <div class="field"><label>School year end</label><input type="date" name="school_year_end" value="${settings.school_year_end || ""}"></div>
          <div class="field"><label>Daily provider email time</label><input type="time" name="daily_email_time" value="${settings.daily_email_time || "06:00"}"></div>
          <button class="btn btn-primary" type="submit">Save settings</button>
        </form>
      </div>

      <div class="card" style="max-width:520px;margin-top:16px;">
        <h3>Email delivery (SMTP)</h3>
        <div class="${email_configured ? "info-box" : "error-box"}" style="margin-bottom:14px;">
          ${email_configured ? "Email is configured — alerts and sign-in codes will actually be sent." : "Not configured yet — alerts and sign-in codes are only printed to the server console until this is filled in."}
        </div>
        <form id="smtp-form">
          ${smtpField("smtp_host", "SMTP host", "text", 'placeholder="smtp.gmail.com"')}
          ${smtpField("smtp_port", "Port", "number", 'placeholder="587"')}
          ${smtpField("smtp_username", "Username")}
          ${smtpPasswordField}
          ${smtpField("smtp_from_email", "From address", "email", 'placeholder="Defaults to the username above"')}
          <button class="btn btn-primary" type="submit">Save email settings</button>
          <button type="button" class="btn btn-outline" id="test-email-btn">Send test email to myself</button>
        </form>
        <p class="small" style="margin-top:14px;">
          For Gmail: use an <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener">app password</a>
          (not your normal password — Google blocks regular logins from apps like this), host <code>smtp.gmail.com</code>,
          port <code>587</code>. On a real deployment, setting these as environment variables
          (<code>SMTP_HOST</code>, <code>SMTP_PORT</code>, <code>SMTP_USERNAME</code>, <code>SMTP_PASSWORD</code>,
          <code>SMTP_FROM_EMAIL</code>) instead of typing them here is recommended, since it keeps the password out
          of the database.
        </p>
      </div>
    `;
    body.querySelector("#settings-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await api.post("/api/settings", qs(e.target));
        toast("Settings saved.");
      } catch (err) { toast(err.message, true); }
    });
    body.querySelector("#smtp-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await api.post("/api/settings", qs(e.target));
        toast("Email settings saved.");
        renderAdministration(content);
      } catch (err) { toast(err.message, true); }
    });
    body.querySelector("#test-email-btn").addEventListener("click", async () => {
      try {
        const resp = await api.post("/api/settings/test-email");
        toast(`Test email sent to ${resp.sent_to}.`);
      } catch (err) { toast(err.message, true); }
    });
  }

  function drawReference(body) {
    body.innerHTML = `
      <p class="small">These attendance results are fixed by the system (they drive makeup and compliance
      calculations), shown here for reference.</p>
      <div class="table-wrap"><table>
        <thead><tr><th>Result</th><th>Requires makeup</th><th>Counts toward compliance</th></tr></thead>
        <tbody>
          ${ATTENDANCE_RESULTS.map(r => `<tr><td>${resultLabel(r)}</td><td>${MAKEUP_REQUIRED.has(r) ? "Yes" : "No"}</td><td>${r === "completed" ? "Yes" : "No (excluded, not counted against compliance)"}</td></tr>`).join("")}
        </tbody>
      </table></div>
    `;
  }

  function drawImport(body) {
    body.innerHTML = `
      <div class="card" style="max-width:520px;">
        <h3>Upload a roster (.xlsx)</h3>
        <p class="small">Expected columns (any order, header names are flexible): Student ID, Name, School,
        Grade, Disability, Eligibility Date, IEP Date, Service Start, Service End, Provider, Sessions Per
        Week, Duration Minutes, Individual or Group. Rows are previewed before anything is created —
        nothing is added to the roster until you approve.</p>
        <input type="file" id="file-input" accept=".xlsx">
      </div>
      <div id="preview-area"></div>
      <div class="section-title"><h3>Import history</h3></div>
      <div class="table-wrap"><table>
        <thead><tr><th>File</th><th>Rows</th><th>Status</th><th>Uploaded</th></tr></thead>
        <tbody>${imports.map(i => `<tr class="clickable" data-id="${i.id}"><td>${i.filename || "—"}</td><td>${i.row_count}</td><td>${i.status}</td><td>${fmtDate(i.created_at.slice(0,10))}</td></tr>`).join("") || `<tr><td colspan="4" class="empty">No imports yet.</td></tr>`}</tbody>
      </table></div>
    `;
    body.querySelector("#file-input").addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      try {
        const b64 = await fileToBase64(file);
        const resp = await api.post("/api/imports/roster", { filename: file.name, content_base64: b64 });
        renderPreview(body, resp.id, resp.preview);
      } catch (err) { toast(err.message, true); }
    });
    body.querySelectorAll("tr[data-id]").forEach(r => r.addEventListener("click", async () => {
      const { import: imp } = await api.get(`/api/imports/${r.dataset.id}`);
      if (imp.status === "pending") renderPreview(body, imp.id, imp.preview);
      else toast(`This import was already ${imp.status}.`);
    }));
  }

  function renderPreview(body, importId, preview) {
    const area = body.querySelector("#preview-area");
    const willImport = preview.rows.filter(r => r.will_import).length;
    const needsReview = preview.rows.filter(r => r.will_import && (r.review_flags || []).length).length;
    area.innerHTML = `
      <div class="section-title"><h3>Preview — ${preview.rows.length} row(s), ${willImport} will be added${needsReview ? ` (${needsReview} flagged for review after import)` : ""}</h3></div>
      <p class="small">Every row with a name gets added, even if the school, provider, dates, or frequency couldn't be matched - those just get a "needs review" note on the student instead of being left out. Only a missing name or a likely duplicate is skipped entirely.</p>
      ${preview.missing_required_columns.length ? `<div class="error-box">Missing required column(s): ${preview.missing_required_columns.join(", ")}</div>` : ""}
      <div class="table-wrap"><table>
        <thead><tr><th>Row</th><th>Name</th><th>School</th><th>Provider</th><th>Frequency</th><th>Notes</th></tr></thead>
        <tbody>
          ${preview.rows.map(r => `
            <tr style="${r.will_import ? "" : "opacity:.5;"}">
              <td>${r.row_number}</td><td>${r.name || "—"}</td>
              <td>${r.school_raw || "—"}${r.school_id ? "" : " ⚠"}</td>
              <td>${r.provider_raw || "Unassigned"}</td>
              <td>${r.sessions_per_week}x/wk · ${r.duration_minutes}min</td>
              <td class="small">${
                !r.will_import ? `Not added: ${r.blocking_flags.join("; ")}`
                : (r.review_flags && r.review_flags.length) ? `Added, needs review: ${r.review_flags.join("; ")}`
                : "Ready"
              }</td>
            </tr>
          `).join("")}
        </tbody>
      </table></div>
      <div class="toolbar">
        <button class="btn btn-outline" id="reject-btn">Reject import</button>
        <button class="btn btn-primary" id="approve-btn" ${willImport === 0 ? "disabled" : ""}>Approve &amp; add ${willImport} student(s)</button>
      </div>
    `;
    area.querySelector("#approve-btn").addEventListener("click", async () => {
      try {
        const resp = await api.post(`/api/imports/${importId}/approve`);
        toast(`Added ${resp.created} student(s). ${resp.skipped} row(s) skipped.`);
        renderAdministration(content);
      } catch (err) { toast(err.message, true); }
    });
    area.querySelector("#reject-btn").addEventListener("click", async () => {
      await api.post(`/api/imports/${importId}/reject`);
      toast("Import rejected.");
      renderAdministration(content);
    });
  }

  draw("settings");
}
