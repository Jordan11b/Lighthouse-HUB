export function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

// Simplified single-color mark based on the Lighthouse Therapy logo, sized to sit on the
// gold brand circle used in the sidebar and login screen (currentColor = navy).
export const LOGO_SVG = `
<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <g stroke="currentColor" stroke-width="2.5" stroke-linecap="round" fill="none" opacity="0.9">
    <path d="M30 34 L14 24 M30 34 L10 36 M30 34 L15 48"/>
    <path d="M70 34 L86 24 M70 34 L90 36 M70 34 L85 48"/>
  </g>
  <path d="M50 10 L60 26 H40 Z" fill="currentColor"/>
  <rect x="41.5" y="26" width="17" height="8" fill="currentColor"/>
  <rect x="45" y="26" width="1.6" height="8" style="fill:var(--gold)"/>
  <rect x="53.4" y="26" width="1.6" height="8" style="fill:var(--gold)"/>
  <path d="M42 34 H58 L67 82 H33 Z" fill="currentColor"/>
  <rect x="38" y="44" width="24" height="4" style="fill:var(--gold)"/>
  <rect x="36" y="56" width="28" height="4" style="fill:var(--gold)"/>
  <rect x="34" y="68" width="32" height="4" style="fill:var(--gold)"/>
  <path d="M27 82 H73 L79 92 H21 Z" fill="currentColor"/>
</svg>`;

export function fmtDate(d) {
  if (!d) return "—";
  const dt = new Date(d + "T00:00:00");
  if (isNaN(dt)) return d;
  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function fmtDay(d) {
  const dt = new Date(d + "T00:00:00");
  return dt.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
}

export function fmtTime(t) {
  if (!t) return "";
  const [h, m] = t.split(":").map(Number);
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${String(m).padStart(2, "0")} ${ampm}`;
}

export function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

export function addDaysISO(dateStr, days) {
  const dt = new Date(dateStr + "T00:00:00");
  dt.setDate(dt.getDate() + days);
  return dt.toISOString().slice(0, 10);
}

const STATUS_LABEL = {
  scheduled: "Scheduled", completed: "Completed", makeup_needed: "Makeup needed",
  makeup_scheduled: "Makeup scheduled", excused: "Excused", provider_cancelled: "Provider cancelled",
  awaiting_approval: "Awaiting approval", cancelled: "Cancelled",
};
const STATUS_COLOR = {
  scheduled: "blue", completed: "green", makeup_needed: "orange", makeup_scheduled: "purple",
  excused: "gray", provider_cancelled: "red", awaiting_approval: "yellow", cancelled: "gray",
};
export function statusBadge(status) {
  const color = STATUS_COLOR[status] || "gray";
  const label = STATUS_LABEL[status] || status;
  return `<span class="badge badge-${color}"><span class="dot"></span>${label}</span>`;
}

const RESULT_LABEL = {
  completed: "Completed", student_absent: "Student absent", student_refused: "Student refused",
  provider_absent: "Provider absent", provider_cancelled: "Provider canceled", school_closed: "School closed",
  school_testing: "School testing", field_trip: "Field trip", assembly: "Assembly",
  school_directed_unavailability: "School-directed unavailability", rescheduled: "Rescheduled",
  other_excused: "Other excused interruption",
};
export function resultLabel(r) { return RESULT_LABEL[r] || r; }
export const ATTENDANCE_RESULTS = Object.keys(RESULT_LABEL);

const PACE_LABEL = { on_target: "On target", at_risk: "At risk", behind: "Behind", not_yet_due: "Not yet due", needs_scheduling: "Needs scheduling" };
export function pacePill(status) {
  return `<span class="pill pill-${status}">${PACE_LABEL[status] || status}</span>`;
}

export function roleLabel(r) {
  return { admin: "Clinic administrator", supervising_slp: "Supervising SLP", provider: "Provider" }[r] || r;
}

let toastTimer = null;
export function toast(message, isError) {
  let node = document.getElementById("lh-toast");
  if (node) node.remove();
  node = el(`<div id="lh-toast" class="toast ${isError ? "err" : ""}">${message}</div>`);
  document.body.appendChild(node);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.remove(), 3200);
}

export function showModal(innerHtml, onMount) {
  const backdrop = el(`<div class="modal-backdrop"><div class="modal">${innerHtml}</div></div>`);
  document.body.appendChild(backdrop);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) backdrop.remove(); });
  if (onMount) onMount(backdrop, () => backdrop.remove());
  return backdrop;
}

export function qs(form) {
  const data = {};
  new FormData(form).forEach((v, k) => { data[k] = v; });
  return data;
}
