import { api, getToken, setToken } from "./api.js";
import { el, roleLabel, toast, LOGO_SVG } from "./utils.js";

import { renderLogin } from "./views/login.js";
import { renderDashboard } from "./views/dashboard.js";
import { renderSchedule } from "./views/schedule.js";
import { renderStudents, renderStudentDetail } from "./views/students.js";
import { renderProviders } from "./views/providers.js";
import { renderSchools, renderSchoolDetail } from "./views/schools.js";
import { renderMakeups } from "./views/makeups.js";
import { renderApprovals } from "./views/approvals.js";
import { renderReports } from "./views/reports.js";
import { renderAudit } from "./views/audit.js";
import { renderAlerts } from "./views/alerts.js";
import { renderAdministration } from "./views/administration.js";
import { renderAccount } from "./views/account.js";

const app = document.getElementById("app");
export let CURRENT_USER = null;

const NAV = [
  { hash: "#/dashboard", label: "Dashboard", roles: ["admin", "supervising_slp", "provider"] },
  { hash: "#/schedule", label: "Schedule", roles: ["admin", "supervising_slp", "provider"] },
  { hash: "#/students", label: "Students", roles: ["admin", "supervising_slp", "provider"] },
  { hash: "#/providers", label: "Providers", roles: ["admin", "supervising_slp"] },
  { hash: "#/schools", label: "Schools", roles: ["admin", "supervising_slp", "provider"] },
  { hash: "#/makeups", label: "Makeup Queue", roles: ["admin", "supervising_slp", "provider"] },
  { hash: "#/alerts", label: "Alerts", roles: ["admin", "supervising_slp", "provider"] },
  { hash: "#/approvals", label: "Approvals", roles: ["admin", "supervising_slp"] },
  { hash: "#/approvals", label: "My Requests", roles: ["provider"] },
  { hash: "#/reports", label: "Reports", roles: ["admin", "supervising_slp"] },
  { hash: "#/audit", label: "Audit History", roles: ["admin", "supervising_slp"] },
  { hash: "#/administration", label: "Administration", roles: ["admin", "supervising_slp"] },
];

const ROUTES = [
  { pattern: /^#\/dashboard$/, render: renderDashboard },
  { pattern: /^#\/schedule$/, render: renderSchedule },
  { pattern: /^#\/students$/, render: renderStudents },
  { pattern: /^#\/students\/(\d+)$/, render: (c, m) => renderStudentDetail(c, m[1]) },
  { pattern: /^#\/providers$/, render: renderProviders },
  { pattern: /^#\/schools$/, render: renderSchools },
  { pattern: /^#\/schools\/(\d+)$/, render: (c, m) => renderSchoolDetail(c, m[1]) },
  { pattern: /^#\/makeups$/, render: renderMakeups },
  { pattern: /^#\/alerts$/, render: renderAlerts },
  { pattern: /^#\/approvals$/, render: renderApprovals },
  { pattern: /^#\/reports$/, render: renderReports },
  { pattern: /^#\/audit$/, render: renderAudit },
  { pattern: /^#\/administration$/, render: renderAdministration },
  { pattern: /^#\/account$/, render: renderAccount },
];

function buildShell() {
  app.innerHTML = "";
  const shell = el(`
    <div class="shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="logo">${LOGO_SVG}</div>
          <div class="name">Lighthouse<br>Therapy Hub</div>
        </div>
        <nav id="sidebar-nav"></nav>
        <div class="foot">
          <div class="who">${CURRENT_USER.name}</div>
          <div>${roleLabel(CURRENT_USER.role)}</div>
          <button class="btn btn-outline btn-sm btn-block" id="account-btn" style="margin-top:10px;">My account</button>
          <button class="btn btn-outline btn-sm btn-block" id="logout-btn">Log out</button>
        </div>
      </aside>
      <div class="main">
        <div class="topbar"><h2 id="page-title">Dashboard</h2></div>
        <div class="content" id="content"></div>
      </div>
    </div>
  `);
  app.appendChild(shell);

  const navEl = shell.querySelector("#sidebar-nav");
  NAV.filter((n) => n.roles.includes(CURRENT_USER.role)).forEach((n) => {
    const a = el(`<a href="${n.hash}">${n.label}</a>`);
    navEl.appendChild(a);
  });

  shell.querySelector("#logout-btn").addEventListener("click", async () => {
    try { await api.post("/api/auth/logout"); } catch (e) {}
    setToken(null);
    CURRENT_USER = null;
    location.hash = "";
    boot();
  });
  shell.querySelector("#account-btn").addEventListener("click", () => { location.hash = "#/account"; });
}

function highlightNav() {
  document.querySelectorAll(".sidebar nav a").forEach((a) => {
    a.classList.toggle("active", location.hash.startsWith(a.getAttribute("href")));
  });
}

const TITLES = {
  "#/dashboard": "Dashboard", "#/schedule": "Schedule", "#/students": "Students",
  "#/providers": "Providers", "#/schools": "Schools", "#/makeups": "Makeup Queue", "#/alerts": "Alerts",
  "#/approvals": "Approvals", "#/reports": "Reports", "#/audit": "Audit History", "#/administration": "Administration", "#/account": "My Account",
};

async function router() {
  const hash = location.hash || "#/dashboard";
  const content = document.getElementById("content");
  if (!content) return;
  let matched = false;
  for (const r of ROUTES) {
    const m = hash.match(r.pattern);
    if (m) {
      matched = true;
      const base = "#/" + hash.slice(2).split("/")[0];
      document.getElementById("page-title").textContent = TITLES[base] || TITLES[hash] || "Lighthouse";
      content.innerHTML = `<div class="empty">Loading…</div>`;
      try {
        await r.render(content, m);
      } catch (err) {
        console.error(err);
        content.innerHTML = `<div class="error-box">${err.message || "Something went wrong loading this page."}</div>`;
      }
      break;
    }
  }
  if (!matched) { location.hash = "#/dashboard"; return; }
  highlightNav();
}

window.addEventListener("hashchange", router);

async function boot() {
  const token = getToken();
  if (!token) {
    renderLogin(app, onAuthenticated);
    return;
  }
  try {
    const me = await api.get("/api/auth/me");
    CURRENT_USER = me.user;
    onAuthenticated();
  } catch (e) {
    setToken(null);
    renderLogin(app, onAuthenticated);
  }
}

async function onAuthenticated() {
  const me = await api.get("/api/auth/me");
  CURRENT_USER = me.user;
  buildShell();
  if (!location.hash) location.hash = "#/dashboard";
  router();
}

boot();
