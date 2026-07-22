// SkillsScraper frontend. All work is delegated to the `skills-scraper` binary via Tauri
// commands (see src-tauri/src/main.rs). Uses the global Tauri API
// (withGlobalTauri = true), so it runs without a bundler.

const invoke = window.__TAURI__?.core?.invoke;
const listen = window.__TAURI__?.event?.listen;

let portal = "public";
// Last-loaded rows per tab, kept so a sort change can re-render without re-fetching.
let browseItems = [];
let searchItems = [];
// The last query actually run, so portal/type changes can re-run the search.
let lastSearchQuery = "";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function setStatus(msg, cls = "") {
  const bar = $("#statusbar");
  bar.textContent = msg;
  bar.className = "statusbar" + (cls ? " " + cls : "");
}

// A segmented/toggle group: clicking sets .active and returns the value via cb.
function wireGroup(rootSel, attr, onSelect) {
  $$(`${rootSel} button`).forEach((b) => {
    b.addEventListener("click", () => {
      $$(`${rootSel} button`).forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      onSelect(b.dataset[attr]);
    });
  });
}
const selected = (rootSel, attr) => $(`${rootSel} button.active`)?.dataset[attr];

// Activate the button whose data-<attr> === val without firing a click event —
// used to restore saved portal/tab state on launch.
function setGroupActive(rootSel, attr, val) {
  $$(`${rootSel} button`).forEach((b) => b.classList.toggle("active", b.dataset[attr] === val));
}

// Selector changes take effect immediately — no extra button press. Explicit
// buttons remain only where input/confirmation is needed (Fetch IDs, Search query).
function refreshActiveTab() {
  const active = $(".panel.active")?.dataset.panel;
  if (active === "browse") $("#browseBtn").click();
  else if (active === "search" && lastSearchQuery) $("#searchBtn").click();
}

// --- Tabs & portal ---
wireGroup("#tabs", "tab", (tab) => {
  $$(".panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === tab));
  // Entering Browse shows the current portal's items right away.
  if (tab === "browse") $("#browseBtn").click();
  else if (tab === "search" && lastSearchQuery) $("#searchBtn").click();
  touchSession({ tab }); // remember the active tab for the next launch
});
wireGroup("#portalToggle", "portal", (p) => {
  portal = p;
  setStatus(portal === "all" ? "Portal: All (public + partner)" : `Portal: ${portal}`);
  // Portal is global: reflect it in the active tab immediately.
  refreshActiveTab();
  touchSession({ portal }); // remember the portal for the next launch
});
wireGroup("#fetchKind", "kind", () => {});
wireGroup("#browseKind", "kind", () => $("#browseBtn").click());
wireGroup("#searchKind", "kind", () => { if (lastSearchQuery) $("#searchBtn").click(); });
// Fetch option toggles are independent (multi-select), so each just flips its
// own active state on click.
$$("#fetchToggles .toggle").forEach((b) =>
  b.addEventListener("click", () => b.classList.toggle("active"))
);
const toggleOn = (opt) => $(`#fetchToggles [data-opt="${opt}"]`)?.classList.contains("active");

// Changing the sort re-applies immediately (no need to click List/Search again):
// re-sort what's already shown, or run the list if nothing is loaded yet.
wireGroup("#browseSort", "sort", () => {
  if (browseItems.length) renderBrowse();
  else $("#browseBtn").click();
});
wireGroup("#searchSort", "sort", () => {
  if (searchItems.length) renderSearch();
});

// The topbar portal is the single source of truth for every tab.
// "All" means both portals for the read tabs (Browse/Search); the concrete
// actions (Fetch/Login) fall back to public while full URLs still infer.
const portalsFor = () => (portal === "all" ? ["public", "partner"] : [portal]);
const concretePortal = () => (portal === "all" ? "public" : portal);

// Client-side sort so it works across merged "All" results without a re-fetch.
function sortItems(items, by) {
  const arr = items.slice();
  const byName = (a, b) => String(a.name).localeCompare(String(b.name), undefined, { sensitivity: "base" });
  if (by === "id") {
    arr.sort((a, b) => {
      const na = parseInt(a.id, 10), nb = parseInt(b.id, 10);
      if (!isNaN(na) && !isNaN(nb) && na !== nb) return na - nb;
      return String(a.id).localeCompare(String(b.id));
    });
  } else if (by === "status") {
    // Fetched first (newest download first), then unfetched, each by name.
    arr.sort((a, b) => {
      if (!!a.fetched !== !!b.fetched) return a.fetched ? -1 : 1;
      if (a.fetched && (b.scrapedTime || 0) !== (a.scrapedTime || 0)) {
        return (b.scrapedTime || 0) - (a.scrapedTime || 0);
      }
      return byName(a, b);
    });
  } else {
    arr.sort(byName);
  }
  return arr;
}

// --- Fetch ---
const consoleEl = $("#console");
function logLine(line) {
  consoleEl.textContent += line + "\n";
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

// While a browser-driving op runs (fetch / sync / login session), disable the
// controls that would start another. The backend also rejects concurrent browser
// ops (they share one Chrome profile), but this avoids the rejection entirely.
// Local-only actions (browse, search, open) stay usable throughout.
function setBrowserBusy(on) {
  // Note: the Browser button is intentionally NOT disabled — fetches are meant to
  // run while the persistent browser is open and reuse it (backlog #13).
  ["#fetchBtn", "#browseSyncBtn", "#queueRunBtn"].forEach((sel) => {
    const b = $(sel);
    if (b) b.disabled = on;
  });
}

// Tracks whether the persistent, reusable browser is open (backlog #13).
let browserOpen = false;
// The fetching-list runner awaits each fetch group's fetch-done via this resolver.
let queueDoneResolver = null;
if (listen) {
  listen("fetch-log", (e) => logLine(e.payload));
  // Each item the binary saves arrives as a fetch-item event, so Browse/Search
  // badges flip to "✓ fetched" live while a fetch is running.
  listen("fetch-item", (e) => applyItemSaved(e.payload));
  // The fetch hit a sign-in redirect: prompt the user to sign in in the visible
  // browser window, then resume the same session via continue_fetch.
  listen("fetch-auth-required", () => {
    $("#authModal").hidden = false;
    setStatus("Sign in in the browser window, then click Continue.", "busy");
  });
  listen("fetch-done", (e) => {
    setStatus(e.payload ? "Fetch complete." : "Fetch finished with errors.", e.payload ? "ok" : "");
    setBrowserBusy(false);
    $("#stopBtn").hidden = true;
    $("#authModal").hidden = true;
    // Re-list the visible read tab so newly-fetched items (e.g. labs found by
    // cascading a path) appear with their status and the counts settle.
    const active = $(".panel.active")?.dataset.panel;
    if (active === "browse") $("#browseBtn").click();
    else if (active === "search" && lastSearchQuery) $("#searchBtn").click();
    // A manual (non-queue) fetch is done, so the session is no longer fetching.
    // Queue runs manage this themselves (they span several fetch-done events).
    if (!queueRunning) setSessionFetch(false);
    // Advance the fetching-list runner (it awaits each group's fetch-done).
    if (queueDoneResolver) { const r = queueDoneResolver; queueDoneResolver = null; r(); }
  });
}

// applyItemSaved patches the loaded Browse/Search rows in place from a fetch-item
// payload ({portal, kind, id, name, scrapedTime, scrapedDate}) and re-renders the
// affected table (debounced, so a burst of saves doesn't thrash the DOM).
function applyItemSaved(payload) {
  let it;
  try { it = JSON.parse(payload); } catch { return; }
  const patch = (rows) => {
    let hit = false;
    for (const r of rows) {
      if (String(r.id) === String(it.id) && r.portal === it.portal) {
        r.fetched = true;
        r.scrapedTime = it.scrapedTime;
        r.scrapedDate = it.scrapedDate;
        hit = true;
      }
    }
    return hit;
  };
  if (patch(browseItems)) scheduleRender("browse");
  if (patch(searchItems)) scheduleRender("search");
  // A fetched item auto-completes its fetching-list entry (if queued).
  markQueueDone(it.portal, it.kind, it.id, it.name);
}

const renderTimers = {};
function scheduleRender(which) {
  if (renderTimers[which]) return;
  renderTimers[which] = setTimeout(() => {
    renderTimers[which] = null;
    if (which === "browse") renderBrowse();
    else renderSearch();
  }, 250);
}
async function runFetch() {
  const ids = $("#fetchIds").value.split(/[\s,]+/).filter(Boolean);
  if (!ids.length) { setStatus("Enter at least one ID or URL."); return; }
  consoleEl.textContent = "";
  setBrowserBusy(true);
  $("#stopBtn").hidden = false;
  $("#stopBtn").disabled = false;
  setStatus("Fetching…", "busy");
  if (portal === "all") {
    logLine("Note: portal is 'All' — bare IDs fetch as Public; full URLs use their own portal.");
  }
  const kind = selected("#fetchKind", "kind");
  setSessionFetch(true, { portal: concretePortal(), kind, ids, source: "manual" });
  try {
    await invoke("fetch", {
      portal: concretePortal(),
      kind,
      ids,
      force: toggleOn("force"),
      signin: toggleOn("signin"),
      toc: toggleOn("toc"),
      noTranscript: toggleOn("noTranscript"),
      headless: toggleOn("headless"),
    });
  } catch (err) {
    logLine("ERROR: " + err);
    setStatus("Fetch failed.", "");
    setBrowserBusy(false);
    $("#stopBtn").hidden = true;
    setSessionFetch(false);
  }
}
$("#fetchBtn").addEventListener("click", async () => {
  // If a persistent browser is open but stopped responding, a fetch can't reuse
  // it — ask the user to acknowledge closing it before launching a fresh one (#13).
  if (browserOpen) {
    try {
      const status = await invoke("browser_status");
      if (status === "stale") { $("#browserStaleModal").hidden = false; return; }
      if (status === "none") { browserOpen = false; }
    } catch (_) { /* probe failed; just proceed */ }
  }
  runFetch();
});

// Stop mirrors Ctrl+C on the CLI: SIGTERM the fetch subprocess so it stops
// cleanly (already-fetched items are kept). The fetch-done event then hides this
// button and re-enables the controls when the process actually exits.
$("#stopBtn").addEventListener("click", async () => {
  $("#stopBtn").disabled = true;
  setStatus("Stopping…", "busy");
  logLine("Stopping… (finishing safely, like Ctrl+C — completed items are kept)");
  try {
    await invoke("stop_fetch");
  } catch (err) {
    logLine("Stop failed: " + err);
    setStatus("Stop failed: " + err);
    $("#stopBtn").disabled = false;
  }
});

// --- Browse / Search tables ---
function renderRows(tableSel, countSel, items) {
  const tbody = $(`${tableSel} tbody`);
  tbody.innerHTML = "";
  for (const it of items) {
    const tr = document.createElement("tr");
    // Carry what a double-click needs to open (or explain) this row's Markdown.
    tr.dataset.id = it.id;
    tr.dataset.portal = it.portal;
    tr.dataset.kind = String(it.type).toLowerCase(); // path / course / lab
    tr.dataset.name = it.name;
    tr.dataset.fetched = it.fetched ? "1" : "";
    tr.title = it.fetched
      ? "Double-click to open its Markdown"
      : "Not fetched yet — fetch it to open its Markdown";
    if (it.fetched) tr.classList.add("openable");
    tr.innerHTML =
      `<td class="cell-id">${it.id}</td>` +
      `<td>${escapeHtml(it.name)}</td>` +
      `<td class="cell-type">${it.type}</td>` +
      `<td class="cell-portal"><span class="badge badge-${it.portal}">${it.portal}</span></td>` +
      `<td class="cell-status">${statusCell(it)}</td>`;
    tbody.appendChild(tr);
  }
  const fetched = items.filter((it) => it.fetched).length;
  $(countSel).textContent =
    `${items.length} item${items.length === 1 ? "" : "s"} · ${fetched} fetched`;
}

// statusCell renders the fetch status: a green "✓ date" when downloaded, a dim
// dash when not yet fetched.
function statusCell(it) {
  if (it.fetched) {
    const label = it.scrapedDate || "fetched";
    const title = it.scrapedDate ? `Fetched on ${it.scrapedDate}` : "Fetched";
    return `<span class="badge badge-fetched" title="${title}">✓ ${label}</span>`;
  }
  return `<span class="badge badge-unfetched" title="Not fetched yet">— not fetched</span>`;
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function renderBrowse() {
  renderRows("#browseTable", "#browseCount", sortItems(browseItems, selected("#browseSort", "sort")));
  clearPdfSelection(); // rows are rebuilt, so drop any Generate-PDF target
}
function renderSearch() {
  renderRows("#searchTable", "#searchCount", sortItems(searchItems, selected("#searchSort", "sort")));
}

// Double-click a row to open its Markdown in the OS default app. If the item
// isn't fetched yet, say so instead. Delegated on the tbody so it keeps working
// across re-renders.
async function onRowOpen(tr) {
  if (!tr) return;
  const { id, portal, kind, name } = tr.dataset;
  if (tr.dataset.fetched !== "1") {
    setStatus(`“${name}” isn’t fetched yet — fetch it first to open its Markdown.`);
    return;
  }
  setStatus(`Opening “${name}”…`, "busy");
  try {
    await invoke("open_md", { portal, kind, id });
    setStatus(`Opened “${name}”.`, "ok");
  } catch (err) {
    setStatus("Could not open Markdown: " + err);
  }
}
["#browseTable", "#searchTable"].forEach((sel) => {
  const tbody = $(`${sel} tbody`);
  if (tbody) tbody.addEventListener("dblclick", (e) => onRowOpen(e.target.closest("tr")));
});

$("#browseBtn").addEventListener("click", async () => {
  const kind = selected("#browseKind", "kind");
  setStatus("Loading…", "busy");
  try {
    const batches = await Promise.all(
      portalsFor().map((pk) => invoke("list_items", { portal: pk, kind }))
    );
    browseItems = batches.flat();
    renderBrowse();
    const where = portal === "all" ? "both portals" : portal;
    if (browseItems.length === 0) {
      setStatus(`No ${kind} stored yet — click Sync to fetch the catalog from the website.`, "");
    } else {
      setStatus(`Listed ${browseItems.length} from ${where}.`, "ok");
    }
  } catch (err) {
    setStatus("List failed: " + err);
  }
});

// Sync = pull the catalog from the website (opens a headless browser; slower).
// This is how an empty first-run database gets populated.
$("#browseSyncBtn").addEventListener("click", async () => {
  const kind = selected("#browseKind", "kind");
  setBrowserBusy(true);
  setStatus(`Syncing ${kind} from the website… (this can take a minute)`, "busy");
  try {
    const batches = await Promise.all(
      portalsFor().map((pk) => invoke("sync_items", { portal: pk, kind }))
    );
    browseItems = batches.flat();
    renderBrowse();
    setStatus(`Synced ${browseItems.length} ${kind} from the website.`, "ok");
  } catch (err) {
    setStatus("Sync failed: " + err);
  } finally {
    setBrowserBusy(false);
  }
});

$("#searchBtn").addEventListener("click", async () => {
  const query = $("#searchQuery").value.trim();
  if (!query) { setStatus("Enter a search query."); return; }
  lastSearchQuery = query;
  const kind = selected("#searchKind", "kind");
  // Portal scope comes from the global topbar control; "All" spans both.
  setStatus("Searching…", "busy");
  try {
    const batches = await Promise.all(
      portalsFor().map((pk) => invoke("search_items", { portal: pk, query, kind }))
    );
    searchItems = batches.flat();
    renderSearch();
    const where = portal === "all" ? "both portals" : portal;
    setStatus(`${searchItems.length} result(s) for “${query}” in ${where}.`, "ok");
  } catch (err) {
    setStatus("Search failed: " + err);
  }
});
$("#searchQuery").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#searchBtn").click(); });

// --- Persistent browser flow (backlog #13) ---
// The Browser button opens a browser that stays open; fetches reuse it, so the
// user doesn't get re-challenged for sign-in or need "Sign in first" each time.
$("#browserBtn").addEventListener("click", async () => {
  if (browserOpen) { $("#browserModal").hidden = false; return; }
  const lp = concretePortal();
  setStatus("Opening browser…", "busy");
  try {
    await invoke("open_browser", { portal: lp });
    browserOpen = true;
    $("#browserModal").hidden = false;
    setStatus(`Browser open for ${lp}. Sign in and browse; fetches reuse it.`, "ok");
  } catch (err) {
    setStatus("Could not open browser: " + err);
  }
});
$("#browserDismiss").addEventListener("click", () => { $("#browserModal").hidden = true; });
$("#browserClose").addEventListener("click", async () => {
  $("#browserModal").hidden = true;
  setStatus("Closing browser…", "busy");
  try {
    await invoke("close_browser");
    browserOpen = false;
    setStatus("Browser closed.", "");
  } catch (err) {
    setStatus("Could not close browser: " + err);
  }
});
// Reuse-impossible ack: the open browser stopped responding, so a fetch can't
// reuse it. Confirm before closing it and launching a fresh one.
$("#staleCancel").addEventListener("click", () => {
  $("#browserStaleModal").hidden = true;
  setStatus("Fetch canceled.");
});
$("#staleContinue").addEventListener("click", async () => {
  $("#browserStaleModal").hidden = true;
  try { await invoke("close_browser"); } catch (_) { /* best effort */ }
  browserOpen = false;
  runFetch();
});

// Continue a fetch that paused for sign-in: the user has signed in in the
// browser, so resume the same session.
$("#authContinue").addEventListener("click", async () => {
  $("#authModal").hidden = true;
  setStatus("Resuming fetch…", "busy");
  try {
    await invoke("continue_fetch");
  } catch (err) {
    setStatus("Could not resume: " + err);
  }
});

$("#vaultBtn").addEventListener("click", async () => {
  try { await invoke("open_vault"); } catch (err) { setStatus("Could not open vault: " + err); }
});

// --- PDF generation (backlog #5) ---
// Single-click a Browse row to target it, pick a theme, then Generate PDF. If
// the item isn't fully fetched we warn first; a path cascades to its sub-items.
let selectedItem = null;

function clearPdfSelection() {
  selectedItem = null;
  $$("#browseTable tr.selected").forEach((tr) => tr.classList.remove("selected"));
  const btn = $("#genPdfBtn");
  if (btn) btn.disabled = true;
}

$("#browseTable tbody").addEventListener("click", (e) => {
  const tr = e.target.closest("tr");
  if (!tr) return;
  $$("#browseTable tr.selected").forEach((r) => r.classList.remove("selected"));
  tr.classList.add("selected");
  selectedItem = { ...tr.dataset }; // id, portal, kind, name, fetched
  $("#genPdfBtn").disabled = false;
});

// Fill the theme picker once at startup (empty → generate uses the default).
(async () => {
  try {
    const themes = await invoke("list_themes");
    const sel = $("#pdfTheme");
    sel.innerHTML = "";
    for (const t of themes) {
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      sel.appendChild(opt);
    }
  } catch (_) {
    /* leave the picker empty; the binary falls back to the default theme */
  }
})();

async function runGeneratePdf() {
  if (!selectedItem) return;
  const { id, portal: pk, kind, name } = selectedItem;
  const theme = $("#pdfTheme").value || "";
  setStatus(`Generating PDF for “${name}”…`, "busy");
  try {
    await invoke("generate_pdf", { portal: pk, kind, id, theme });
    setStatus(`PDF generated for “${name}”. Opening…`, "ok");
    try {
      await invoke("open_pdf", { portal: pk, kind, id });
    } catch (_) {
      /* opening is best-effort — the file is already written */
    }
  } catch (err) {
    setStatus("PDF generation failed: " + err);
  }
}

// Check the item's own readiness (is it fetched?), then generate. Split out so
// the PDF-setup gate below can run first and resume here.
async function checkItemThenGenerate() {
  if (!selectedItem) return;
  const { id, portal: pk, kind, name } = selectedItem;
  setStatus(`Checking “${name}”…`, "busy");
  let status;
  try {
    status = await invoke("pdf_status", { portal: pk, kind, id });
  } catch (err) {
    setStatus("Could not check status: " + err);
    return;
  }
  if (status === "none") {
    setStatus(`“${name}” isn’t fetched yet — fetch it first.`);
    return;
  }
  if (status === "incomplete") {
    $("#pdfIncompleteText").textContent =
      `“${name}” isn’t fully fetched yet — the PDF may be missing sections. Generate anyway?`;
    $("#pdfIncompleteModal").hidden = false;
    return;
  }
  runGeneratePdf();
}

$("#genPdfBtn").addEventListener("click", async () => {
  if (!selectedItem) { setStatus("Select an item in the table first."); return; }
  if (!invoke) return;
  // Two different questions, asked in order: can this MACHINE render a PDF
  // (tools + fonts), and is this ITEM complete enough to be worth rendering.
  try {
    const report = await fetchPdfReport();
    if (toolsMissing(report)) {
      setStatus("PDF generation needs pandoc and typst — see PDF setup.");
      openPdfSetup(report, null);
      return;
    }
    if (fontsMissing(report) && !fontWarningDismissed) {
      setStatus("Some theme fonts are missing.");
      openPdfSetup(report, () => { fontWarningDismissed = true; checkItemThenGenerate(); });
      return;
    }
  } catch (err) {
    // A failed check must not block generation — the binary reports its own
    // error if the pipeline is genuinely broken.
    console.warn("pdf_doctor failed:", err);
  }
  checkItemThenGenerate();
});

$("#pdfIncompleteCancel").addEventListener("click", () => {
  $("#pdfIncompleteModal").hidden = true;
  setStatus("PDF canceled.");
});
$("#pdfIncompleteContinue").addEventListener("click", () => {
  $("#pdfIncompleteModal").hidden = true;
  runGeneratePdf();
});

// --- PDF setup: the toolchain and the theme's fonts (backlog #5) ---
// Rendering shells out to pandoc + typst and draws the theme's fonts from the
// system font book; none of that ships with the app. `pdf --doctor` reports
// what's missing and the per-OS step that fixes it. Missing TOOLS block
// generation; missing FONTS only degrade it — typst substitutes silently and
// still succeeds — so those are advisory, with a "Generate anyway".
let pdfSetupProceed = null;      // what to run if the user accepts the warning
let fontWarningDismissed = false; // don't re-nag about fonts every generate

const fetchPdfReport = async () =>
  JSON.parse(await invoke("pdf_doctor", { theme: $("#pdfTheme")?.value || "" }));

const toolsMissing = (r) => (r.tools || []).some((t) => !t.found);
const fontsMissing = (r) => r.fontsChecked && (r.fonts || []).some((f) => !f.found);

// A row's fix-it button: copy an install command, or open a download page in the
// user's real browser (never in this webview).
function setupAction(kind, value) {
  const btn = document.createElement("button");
  btn.className = "btn ghost";
  if (kind === "copy") {
    btn.textContent = "Copy";
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(value);
        btn.textContent = "Copied";
        setTimeout(() => { btn.textContent = "Copy"; }, 1200);
      } catch (_) {
        setStatus("Could not copy — select the command and copy it manually.");
      }
    });
  } else {
    btn.textContent = "Get it…";
    btn.addEventListener("click", () => {
      invoke("open_external", { url: value }).catch((e) => setStatus("" + e));
    });
  }
  return btn;
}

// state is "ok" | "bad" | "unknown"; action is [kind, value] or null.
function setupRow(state, name, detail, action) {
  const row = document.createElement("div");
  row.className = "setup-row " + state;
  const mark = document.createElement("span");
  mark.className = "setup-mark";
  mark.textContent = state === "ok" ? "✓" : state === "bad" ? "✗" : "?";
  const label = document.createElement("span");
  label.className = "setup-name";
  label.textContent = name;
  const det = document.createElement("span");
  det.className = "setup-detail" + (action && action[0] === "copy" ? " cmd" : "");
  det.textContent = detail || "";
  det.title = detail || "";
  row.append(mark, label, det);
  if (action) row.appendChild(setupAction(action[0], action[1]));
  return row;
}

// A group heading. `path` is kept in its own span because the heading is
// uppercased in CSS and a filesystem path must not be (~/Library/Fonts).
function setupGroup(text, path) {
  const g = document.createElement("div");
  g.className = "setup-group";
  g.textContent = text;
  if (path) {
    const p = document.createElement("span");
    p.className = "setup-group-path";
    p.textContent = " — install to " + path;
    g.appendChild(p);
  }
  return g;
}

function renderPdfSetup(r) {
  const list = $("#pdfSetupList");
  list.innerHTML = "";

  list.appendChild(setupGroup("Tools", ""));
  for (const t of r.tools || []) {
    if (t.found) {
      list.appendChild(setupRow("ok", t.name, t.version || t.path || "installed", null));
    } else if (t.install) {
      list.appendChild(setupRow("bad", t.name, t.install, ["copy", t.install]));
    } else {
      list.appendChild(setupRow("bad", t.name, t.url || "not installed",
        t.url ? ["open", t.url] : null));
    }
  }

  if ((r.fonts || []).length) {
    list.appendChild(setupGroup("Fonts", r.fontDir));
    for (const f of r.fonts) {
      if (!r.fontsChecked) {
        list.appendChild(setupRow("unknown", f.family, "needs typst before it can be checked", null));
      } else if (f.found) {
        list.appendChild(setupRow("ok", f.family, "installed", null));
      } else {
        list.appendChild(setupRow("bad", f.family, f.url || "not installed",
          f.url ? ["open", f.url] : null));
      }
    }
    if (r.fontNote) {
      const note = document.createElement("p");
      note.className = "setup-note";
      note.textContent = r.fontNote;
      list.appendChild(note);
    }
  }

  const blocked = toolsMissing(r);
  $("#pdfSetupSub").textContent = r.ok
    ? `Everything the “${r.theme}” theme needs is installed.`
    : blocked
      ? "PDF generation needs these tools. Install them, then Re-check."
      : "These fonts are missing — PDFs render with substitutes until you install them.";
  $("#pdfSetupAnyway").hidden = blocked || r.ok || !pdfSetupProceed;
}

function openPdfSetup(report, proceed) {
  pdfSetupProceed = proceed || null;
  renderPdfSetup(report);
  $("#pdfSetupModal").hidden = false;
}

function closePdfSetup() {
  $("#pdfSetupModal").hidden = true;
  pdfSetupProceed = null;
}

async function showPdfSetup(proceed) {
  if (!invoke) return;
  try {
    openPdfSetup(await fetchPdfReport(), proceed);
  } catch (err) {
    setStatus("Could not check the PDF setup: " + err);
  }
}

$("#pdfSetupClose").addEventListener("click", () => {
  closePdfSetup();
  setStatus("Ready.");
});
$("#pdfSetupAnyway").addEventListener("click", () => {
  const go = pdfSetupProceed;
  closePdfSetup();
  if (go) go();
});
$("#pdfSetupRecheck").addEventListener("click", async () => {
  if (!invoke) return;
  try {
    renderPdfSetup(await fetchPdfReport());
  } catch (err) {
    setStatus("Could not check the PDF setup: " + err);
  }
});
$("#settingsPdfCheck").addEventListener("click", () => showPdfSetup(null));

// --- Item management: right-click a Browse row (backlog #17) ---
let ctxTarget = null; // dataset snapshot of the right-clicked row
const rowMenu = $("#rowMenu");
const hideRowMenu = () => { rowMenu.hidden = true; };

$("#browseTable tbody").addEventListener("contextmenu", (e) => {
  const tr = e.target.closest("tr");
  if (!tr) return;
  e.preventDefault();
  ctxTarget = { ...tr.dataset }; // id, portal, kind, name
  rowMenu.style.left = `${e.clientX}px`;
  rowMenu.style.top = `${e.clientY}px`;
  rowMenu.hidden = false;
});
document.addEventListener("click", hideRowMenu);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideRowMenu(); });
window.addEventListener("blur", hideRowMenu);

$("#ctxDelete").addEventListener("click", () => {
  if (!ctxTarget) return;
  $("#deleteText").textContent =
    `Delete “${ctxTarget.name}” (${ctxTarget.kind} ${ctxTarget.id})? This removes it from the database and its files. This cannot be undone.`;
  $("#deleteModal").hidden = false;
});
$("#deleteCancel").addEventListener("click", () => { $("#deleteModal").hidden = true; });
$("#deleteConfirm").addEventListener("click", async () => {
  $("#deleteModal").hidden = true;
  if (!ctxTarget) return;
  const { id, portal: pk, kind, name } = ctxTarget;
  setStatus(`Deleting “${name}”…`, "busy");
  try {
    await invoke("delete_item", { portal: pk, kind, id });
    setStatus(`Deleted “${name}”.`, "ok");
    $("#browseBtn").click(); // refresh the list
  } catch (err) {
    setStatus("Delete failed: " + err);
  }
});

$("#ctxRename").addEventListener("click", () => {
  if (!ctxTarget) return;
  $("#renameInput").value = ctxTarget.name || "";
  $("#renameModal").hidden = false;
  $("#renameInput").focus();
});
$("#renameCancel").addEventListener("click", () => { $("#renameModal").hidden = true; });
$("#renameConfirm").addEventListener("click", async () => {
  const name = $("#renameInput").value.trim();
  if (!name) { setStatus("Enter a new name."); return; }
  $("#renameModal").hidden = true;
  if (!ctxTarget) return;
  const { id, portal: pk, kind } = ctxTarget;
  setStatus(`Renaming to “${name}”…`, "busy");
  try {
    await invoke("rename_item", { portal: pk, kind, id, name });
    setStatus(`Renamed to “${name}”.`, "ok");
    $("#browseBtn").click(); // refresh the list
  } catch (err) {
    setStatus("Rename failed: " + err);
  }
});
$("#renameInput").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#renameConfirm").click(); });

// --- Fetching list: a persistent queue (FEAT) -------------------------------
// One stateful list built from the Browse right-click menu or the Fetch tab,
// saved to disk (queue_load/queue_save) so it survives restarts and reflects
// live across tabs. Entry: { portal, kind, id, name, addedOn, completedOn,
// removedOn }; status is derived (removed → done → waiting).
let fetchQueue = [];
let queueRunning = false;

const qKey = (it) => `${it.portal}:${it.kind}:${it.id}`;
const qWaiting = (it) => !it.completedOn && !it.removedOn;
const qFinished = (it) => !!it.completedOn || !!it.removedOn;
const nowISO = () => new Date().toISOString();
const fmtDate = (iso) => (iso ? String(iso).slice(0, 10) : "—");

async function saveQueue() {
  if (!invoke) return;
  try { await invoke("queue_save", { data: JSON.stringify({ items: fetchQueue }) }); }
  catch (err) { console.warn("queue save failed", err); }
}

async function loadQueue() {
  if (invoke) {
    try {
      const raw = await invoke("queue_load");
      const parsed = JSON.parse(raw || "{}");
      fetchQueue = Array.isArray(parsed.items) ? parsed.items : [];
    } catch (_) { fetchQueue = []; }
  }
  renderQueue();
}

// Best-effort display name for a raw id, from the loaded Browse list.
function resolveName(portal, kind, id) {
  const hit = browseItems.find(
    (r) => String(r.id) === String(id) && r.portal === portal && String(r.type).toLowerCase() === kind
  );
  return hit ? hit.name : "";
}

function addToQueue({ portal, kind, id, name }) {
  if (!portal || !kind || !id) return;
  const key = `${portal}:${kind}:${id}`;
  const existing = fetchQueue.find((it) => qKey(it) === key);
  if (existing) {
    if (qWaiting(existing)) { setStatus(`“${existing.name || id}” is already in the list.`); return; }
    // Re-activate a finished entry.
    existing.completedOn = null;
    existing.removedOn = null;
    existing.addedOn = nowISO();
    if (name) existing.name = name;
  } else {
    fetchQueue.push({ portal, kind, id: String(id), name: name || "", addedOn: nowISO(), completedOn: null, removedOn: null });
  }
  saveQueue();
  renderQueue();
  setStatus(`Added ${kind} ${id} to the fetching list.`, "ok");
}

function removeFromQueue(key) {
  const it = fetchQueue.find((x) => qKey(x) === key);
  if (!it) return;
  // Soft-remove a waiting item (keeps a Removed timestamp); drop a finished row.
  if (qWaiting(it)) it.removedOn = nowISO();
  else fetchQueue = fetchQueue.filter((x) => qKey(x) !== key);
  saveQueue();
  renderQueue();
}

function clearFinished() {
  const before = fetchQueue.length;
  fetchQueue = fetchQueue.filter(qWaiting);
  if (fetchQueue.length !== before) { saveQueue(); renderQueue(); setStatus("Cleared finished items."); }
}

function markQueueDone(portal, kind, id, name) {
  const it = fetchQueue.find((x) => x.portal === portal && x.kind === kind && String(x.id) === String(id));
  if (!it || !qWaiting(it)) return;
  it.completedOn = nowISO();
  if (!it.name && name) it.name = name;
  saveQueue();
  renderQueue();
}

function renderQueue() {
  const tbody = $("#queueTable tbody");
  if (!tbody) return;
  const waiting = fetchQueue.filter(qWaiting);
  const finished = fetchQueue.filter(qFinished).reverse(); // most-recent finished first
  const rows = [...waiting, ...finished];
  tbody.innerHTML = "";
  if (!rows.length) {
    tbody.innerHTML =
      `<tr class="q-empty"><td colspan="8">Nothing queued. Right-click a Browse item → “Add to Fetching list”.</td></tr>`;
  } else {
    for (const it of rows) {
      const tr = document.createElement("tr");
      tr.className = it.removedOn ? "q-removed" : it.completedOn ? "q-done" : "q-waiting";
      tr.innerHTML =
        `<td class="cell-id">${it.id}</td>` +
        `<td>${escapeHtml(it.name || "—")}</td>` +
        `<td class="cell-type">${it.kind}</td>` +
        `<td class="cell-portal"><span class="badge badge-${it.portal}">${it.portal}</span></td>` +
        `<td class="q-time">${fmtDate(it.addedOn)}</td>` +
        `<td class="q-time q-done-time">${fmtDate(it.completedOn)}</td>` +
        `<td class="q-time">${fmtDate(it.removedOn)}</td>` +
        `<td class="q-act"><button class="q-remove" title="Remove from list" data-key="${qKey(it)}">✕</button></td>`;
      tbody.appendChild(tr);
    }
  }
  const n = waiting.length;
  $("#queueCount").textContent = fetchQueue.length
    ? `${n} waiting · ${fetchQueue.length} total`
    : "empty";
  $("#queueRunBtn").disabled = queueRunning || n === 0;
  updateSessionChip(); // keep the topbar session indicator in sync
}

// Remove-button clicks (delegated over the queue tbody).
$("#queueTable tbody").addEventListener("click", (e) => {
  const btn = e.target.closest(".q-remove");
  if (btn) removeFromQueue(btn.dataset.key);
});

// Add the right-clicked Browse row to the list.
$("#ctxAddQueue").addEventListener("click", () => {
  if (!ctxTarget) return;
  addToQueue({ portal: ctxTarget.portal, kind: ctxTarget.kind, id: ctxTarget.id, name: ctxTarget.name });
});

// Add the ids typed on the Fetch tab (names resolved best-effort).
$("#addQueueBtn").addEventListener("click", () => {
  const ids = $("#fetchIds").value.split(/[\s,]+/).filter(Boolean);
  if (!ids.length) { setStatus("Enter at least one ID to add."); return; }
  const kind = selected("#fetchKind", "kind");
  const pk = concretePortal();
  for (const id of ids) addToQueue({ portal: pk, kind, id, name: resolveName(pk, kind, id) });
  $("#fetchIds").value = "";
});

$("#queueClearBtn").addEventListener("click", clearFinished);
$("#queueRunBtn").addEventListener("click", () => runQueue());

// Run every waiting item: group by portal+type, fetch each group sequentially,
// awaiting its fetch-done before the next. Items auto-complete via fetch-item.
async function runQueue() {
  if (queueRunning) return;
  const waiting = fetchQueue.filter(qWaiting);
  if (!waiting.length) { setStatus("The fetching list has no waiting items."); return; }
  // If a reusable browser is open but unresponsive, a fetch can't reuse it (#13).
  if (browserOpen) {
    try {
      const status = await invoke("browser_status");
      if (status === "stale") { $("#browserStaleModal").hidden = false; return; }
      if (status === "none") { browserOpen = false; }
    } catch (_) { /* proceed */ }
  }
  const groups = [];
  const byKey = new Map();
  for (const it of waiting) {
    const key = `${it.portal}:${it.kind}`;
    let g = byKey.get(key);
    if (!g) { g = { portal: it.portal, kind: it.kind, ids: [] }; byKey.set(key, g); groups.push(g); }
    g.ids.push(it.id);
  }
  queueRunning = true;
  consoleEl.textContent = "";
  setBrowserBusy(true);
  setSessionFetch(true, { source: "queue", ids: waiting.map((w) => w.id) });
  for (const g of groups) {
    setStatus(`Fetching ${g.ids.length} ${g.kind}(s) from ${g.portal}…`, "busy");
    $("#stopBtn").hidden = false;
    $("#stopBtn").disabled = false;
    const done = new Promise((resolve) => { queueDoneResolver = resolve; });
    try {
      await invoke("fetch", {
        portal: g.portal, kind: g.kind, ids: g.ids,
        force: toggleOn("force"), signin: toggleOn("signin"), toc: toggleOn("toc"),
        noTranscript: toggleOn("noTranscript"), headless: toggleOn("headless"),
      });
    } catch (err) {
      logLine("ERROR: " + err);
      queueDoneResolver = null;
      break; // stop the runner on a launch failure (e.g. a browser op already running)
    }
    await done; // fetch-done resolves this; fetch-item events mark items complete
  }
  queueRunning = false;
  setSessionFetch(false);
  setStatus("Fetch queue finished.", "ok");
}

// --- Stateful session (FEAT) ------------------------------------------------
// A small session persisted to disk (session_load/session_save → session.json)
// so relaunching restores the portal + active tab, indicates in-progress work,
// and can tell a graceful stop from a sudden interruption: a clean window close
// stamps cleanExit/endedAt (Rust close handler), which a crash never reaches, so
// a leftover cleanExit=false means the previous run was interrupted. Timestamps
// are epoch millis (Date.now()) to match the Rust markers.
let session = null;

const activeTabName = () => $(".panel.active")?.dataset.panel || "fetch";
const fmtTime = (ms) => {
  if (!ms) return "?";
  try { return new Date(ms).toLocaleString(); } catch (_) { return "?"; }
};

async function sessionSave() {
  if (!invoke || !session) return;
  try { await invoke("session_save", { data: JSON.stringify(session) }); }
  catch (err) { console.warn("session save failed", err); }
}

// Merge a change into the live session and persist it, so the on-disk file always
// reflects the latest portal/tab/fetch state — even if the app is then killed.
function touchSession(patch) {
  if (!session) return;
  Object.assign(session, patch);
  sessionSave();
  updateSessionChip();
}

// Reflect the live session in the topbar chip: a running fetch, waiting items,
// or idle. Hover shows when this session started.
function updateSessionChip() {
  const chip = $("#sessionChip");
  if (!chip || !session) return;
  const waiting = fetchQueue.filter(qWaiting).length;
  let cls = "running", text = "Session: idle";
  if (session.fetchActive) { cls = "fetching"; text = "Session: fetching…"; }
  else if (waiting) { cls = "waiting"; text = `Session: ${waiting} queued`; }
  chip.className = "session-chip " + cls;
  chip.textContent = text;
  chip.title = `Session started ${fmtTime(session.startedAt)}`;
  chip.hidden = false;
}

// Record a fetch as in progress (or finished) in the session, so an interruption
// mid-fetch is preserved on disk and surfaced on the next launch.
function setSessionFetch(active, info) {
  if (!session) return;
  session.fetchActive = active;
  session.fetch = active ? { startedAt: Date.now(), ...info } : null;
  sessionSave();
  updateSessionChip();
}

// Restore the previous UI state, then open a fresh session. Must run after
// loadQueue so the banner can count waiting items.
async function initSession() {
  let prev = {};
  if (invoke) {
    try { prev = JSON.parse((await invoke("session_load")) || "{}") || {}; }
    catch (_) { prev = {}; }
  }

  // Restore the saved portal + active tab (low-risk UI state).
  if (["all", "public", "partner"].includes(prev.portal)) {
    portal = prev.portal;
    setGroupActive("#portalToggle", "portal", portal);
  }
  if (["fetch", "browse", "search"].includes(prev.tab)) {
    setGroupActive("#tabs", "tab", prev.tab);
    $$(".panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === prev.tab));
  }

  // A previous session that started but never marked a clean exit was interrupted
  // (crash / force-quit); if it was mid-fetch, fetchActive is still set.
  const interrupted = !!prev.startedAt && !prev.cleanExit;
  const wasFetching = interrupted && !!prev.fetchActive;

  // Open a fresh session carrying the restored UI state.
  session = {
    startedAt: Date.now(), endedAt: null, cleanExit: false,
    portal, tab: activeTabName(), fetchActive: false, fetch: null,
  };
  await sessionSave();
  updateSessionChip();

  // If we restored the Browse tab, list it so the restore is actually visible.
  if (activeTabName() === "browse") $("#browseBtn").click();

  showSessionBanner(interrupted, wasFetching, prev);
}

// Show the relaunch banner when the previous session was interrupted and/or the
// fetching list still has waiting items. Silent when there's nothing to resume.
function showSessionBanner(interrupted, wasFetching, prev) {
  const banner = $("#sessionBanner");
  if (!banner) return;
  const waiting = fetchQueue.filter(qWaiting).length;
  const plural = (n) => (n === 1 ? "" : "s");
  let msg = "";
  if (wasFetching) {
    const f = prev.fetch || {};
    const count = (f.ids || []).length;
    const what = f.kind ? `${count || ""} ${f.kind}${plural(count)}`.trim() : "a fetch";
    msg = `The previous session ended unexpectedly while fetching ${what}. ` +
      (waiting ? `${waiting} item${plural(waiting)} still waiting in the list.` : "It didn't finish.");
  } else if (interrupted) {
    msg = `The previous session (started ${fmtTime(prev.startedAt)}) didn't close cleanly.` +
      (waiting ? ` ${waiting} item${plural(waiting)} waiting in the list.` : "");
  } else if (waiting) {
    msg = `You have ${waiting} item${plural(waiting)} waiting in the fetching list.`;
  }
  if (!msg) { banner.hidden = true; return; }
  $("#sessionBannerIcon").textContent = (interrupted || wasFetching) ? "⚠" : "•";
  $("#sessionBannerText").textContent = msg;
  $("#sessionResume").hidden = waiting === 0; // nothing to resume if none waiting
  banner.hidden = false;
}

$("#sessionDismiss").addEventListener("click", () => { $("#sessionBanner").hidden = true; });
$("#sessionResume").addEventListener("click", () => {
  $("#sessionBanner").hidden = true;
  // Make the Fetch tab visible so the run is observable.
  setGroupActive("#tabs", "tab", "fetch");
  $$(".panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === "fetch"));
  touchSession({ tab: "fetch" });
  runQueue();
});

// --- Settings dialog (folders + default portal) ---
// The GUI persists these choices as settings.json; the Rust side maps them onto
// the CSB_* env vars the Go core honors (env > config.yaml > default), so they
// steer where files are read/written without any core change. A blank field
// falls back to the default, shown as the input's placeholder.
const SETTINGS_PATH_KEYS = ["data", "vault", "logs", "profile", "themes"];
let settingsDefaults = { paths: {}, portal: "public" };

const settingsInput = (key) => $(`#settingsModal input[data-key="${key}"]`);

// A path pointing inside a macOS .app bundle (e.g. the built-in themes under
// Contents/Resources) is never a durable user setting — it breaks when the app is
// renamed/moved/updated. Ignore such a persisted value so the live default (the
// current bundle) shows instead. Mirrors is_bundle_internal in the Rust side.
const isBundleInternal = (p) =>
  typeof p === "string" && (p.includes("/Contents/Resources/") || p.includes(".app/"));

// Populate the dialog from settings.json (values) + settings_defaults
// (placeholders). Reloads on every open so external edits are reflected.
async function loadSettings() {
  if (!invoke) return;
  try { settingsDefaults = JSON.parse((await invoke("settings_defaults")) || "{}") || {}; }
  catch (_) { settingsDefaults = { paths: {}, portal: "public" }; }
  let cfg = {};
  try { cfg = JSON.parse((await invoke("settings_load")) || "{}") || {}; }
  catch (_) { cfg = {}; }
  const paths = cfg.paths || {};
  const defPaths = settingsDefaults.paths || {};
  for (const key of SETTINGS_PATH_KEYS) {
    const input = settingsInput(key);
    if (!input) continue;
    const saved = paths[key] || "";
    // Drop a stale bundle-internal value so its live default placeholder shows.
    input.value = isBundleInternal(saved) ? "" : saved;
    input.placeholder = defPaths[key] || "";
  }
  const sel = $("#setPortal");
  if (sel) sel.value = cfg.portal || settingsDefaults.portal || "public";
}

function openSettings() { loadSettings(); $("#settingsModal").hidden = false; }
function closeSettings() { $("#settingsModal").hidden = true; }

// Native folder picker (tauri-plugin-dialog). Inert without the Tauri runtime.
async function chooseFolder(inputId) {
  const open = window.__TAURI__?.dialog?.open;
  if (!open) return;
  const current = $(`#${inputId}`)?.value || undefined;
  try {
    const picked = await open({ directory: true, multiple: false, defaultPath: current });
    if (typeof picked === "string" && picked) $(`#${inputId}`).value = picked;
  } catch (err) { setStatus("Folder picker failed: " + err); }
}

async function saveSettings() {
  const paths = {};
  for (const key of SETTINGS_PATH_KEYS) {
    const input = settingsInput(key);
    paths[key] = input ? input.value.trim() : "";
  }
  const portal = $("#setPortal")?.value || "public";
  const data = JSON.stringify({ paths, portal });
  if (invoke) {
    try { await invoke("settings_save", { data }); }
    catch (err) { setStatus("Could not save settings: " + err); return; }
  }
  closeSettings();
  setStatus("Settings saved. New folders apply to your next fetch.");
}

// Clear every field so each falls back to its placeholder/default (does not save
// until Save is pressed).
function resetSettings() {
  for (const key of SETTINGS_PATH_KEYS) {
    const input = settingsInput(key);
    if (input) input.value = "";
  }
  const sel = $("#setPortal");
  if (sel) sel.value = settingsDefaults.portal || "public";
}

$("#settingsBtn")?.addEventListener("click", openSettings);
$("#settingsCancel")?.addEventListener("click", closeSettings);
$("#settingsSave")?.addEventListener("click", saveSettings);
$("#settingsReset")?.addEventListener("click", resetSettings);
$$("#settingsModal [data-choose]").forEach((b) =>
  b.addEventListener("click", () => chooseFolder(b.dataset.choose))
);

// Boot: restore the queue first (the session banner counts its waiting items),
// then open/restore the session.
setStatus("Ready.");
(async () => {
  await loadQueue();
  await initSession();
})();
