import { api } from "../api.js";
import { toast, qs, roleLabel } from "../utils.js";
import { CURRENT_USER } from "../main.js";

export async function renderAccount(content) {
  content.innerHTML = `
    <div class="grid grid-2">
      <div class="card">
        <h3>Profile</h3>
        <div style="font-size:18px;font-weight:700;margin:4px 0;">${CURRENT_USER.name}</div>
        <div class="small">${CURRENT_USER.email}</div>
        <div class="small">${roleLabel(CURRENT_USER.role)}</div>
      </div>
      <div class="card">
        <h3>Change password</h3>
        <form id="pw-form">
          <div class="field"><label>Current password</label><input type="password" name="current_password" required></div>
          <div class="field"><label>New password (min 8 characters)</label><input type="password" name="new_password" minlength="8" required></div>
          <button class="btn btn-primary" type="submit">Update password</button>
        </form>
      </div>
      <div class="card">
        <h3>Notification email</h3>
        <p class="small">Where sign-in codes and alerts go, if you'd rather receive them somewhere other than
        your login email (${CURRENT_USER.email}). Leave blank to use your login email.</p>
        <form id="notify-form">
          <div class="field"><label>Notification email</label><input type="email" name="notify_email" value="${CURRENT_USER.notify_email || ""}" placeholder="${CURRENT_USER.email}"></div>
          <button class="btn btn-primary" type="submit">Save</button>
        </form>
      </div>
    </div>
  `;
  content.querySelector("#pw-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api.post("/api/auth/change-password", qs(e.target));
      toast("Password updated.");
      e.target.reset();
    } catch (err) { toast(err.message, true); }
  });
  content.querySelector("#notify-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const resp = await api.post("/api/auth/me/notify-email", qs(e.target));
      CURRENT_USER.notify_email = resp.user.notify_email;
      toast("Notification email saved.");
    } catch (err) { toast(err.message, true); }
  });
}
