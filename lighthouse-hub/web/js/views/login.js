import { api, setToken } from "../api.js";
import { el, LOGO_SVG } from "../utils.js";

export function renderLogin(app, onAuthenticated) {
  app.innerHTML = "";
  const wrap = el(`
    <div class="auth-shell">
      <div class="auth-card">
        <div class="auth-logo">${LOGO_SVG}</div>
        <h1>Lighthouse Therapy Hub</h1>
        <p class="sub">Sign in to your clinic account.</p>
        <div id="auth-error"></div>
        <div id="auth-body"></div>
      </div>
    </div>
  `);
  app.appendChild(wrap);
  renderLoginForm(wrap, onAuthenticated);
}

function showError(wrap, msg) {
  wrap.querySelector("#auth-error").innerHTML = msg ? `<div class="error-box">${msg}</div>` : "";
}

function renderLoginForm(wrap, onAuthenticated) {
  const body = wrap.querySelector("#auth-body");
  body.innerHTML = `
    <form id="login-form">
      <div class="field">
        <label>Email</label>
        <input type="email" name="email" required autocomplete="username" placeholder="you@lighthouse.example">
      </div>
      <div class="field">
        <label>Password</label>
        <input type="password" name="password" required autocomplete="current-password">
      </div>
      <button class="btn btn-primary btn-block" type="submit">Sign in</button>
    </form>
    <p class="small" style="margin-top:16px;">Accounts are invite-only. Ask your clinic administrator if you need access.</p>
  `;
  body.querySelector("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    showError(wrap, "");
    const fd = new FormData(e.target);
    try {
      const resp = await api.post("/api/auth/login", { email: fd.get("email"), password: fd.get("password") });
      setToken(resp.token);
      if (!resp.mfa_required) {
        onAuthenticated();
      } else {
        renderMfaVerify(wrap, resp.token, fd.get("email"), onAuthenticated);
      }
    } catch (err) {
      showError(wrap, err.message);
    }
  });
}

function renderMfaVerify(wrap, token, email, onAuthenticated) {
  wrap.querySelector(".sub").textContent = "Enter your sign-in code.";
  const body = wrap.querySelector("#auth-body");
  body.innerHTML = `
    <div class="info-box">We emailed a 6-digit code to ${email || "your account email"}. It expires in 10 minutes.</div>
    <form id="mfa-form">
      <div class="field">
        <label>6-digit code</label>
        <input type="text" name="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required autocomplete="one-time-code" autofocus>
      </div>
      <button class="btn btn-primary btn-block" type="submit">Verify</button>
    </form>
    <p class="small" style="margin-top:14px;">
      Didn't get it? <a href="#" id="resend-link">Send a new code</a>.
    </p>
  `;
  body.querySelector("#mfa-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    showError(wrap, "");
    const code = (new FormData(e.target).get("code") || "").trim().replace(/\D/g, "");
    try {
      await api.post("/api/auth/mfa/verify", { token, code });
      onAuthenticated();
    } catch (err) {
      showError(wrap, err.message);
    }
  });
  body.querySelector("#resend-link").addEventListener("click", async (e) => {
    e.preventDefault();
    showError(wrap, "");
    try {
      await api.post("/api/auth/mfa/resend", { token });
      e.target.textContent = "New code sent.";
      setTimeout(() => { e.target.textContent = "Send a new code"; }, 4000);
    } catch (err) {
      showError(wrap, err.message);
    }
  });
}
