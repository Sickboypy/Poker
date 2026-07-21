/* ============================================================
   MESA FINAL v2 — multi-usuario
   Cuentas, admin de partida, cajas con aprobación, sync en vivo
   ============================================================ */

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const view = $("#view");

const state = {
  me: null,
  tab: "home",
  activeGame: null,
  lastGameJSON: "",
  celebratedGameId: null,
  newPlayerEmoji: "🂡",
  authMode: "login",
  poller: null,
};

const EMOJIS = ["🂡", "🦈", "🐺", "🦅", "🃏", "🎩", "🕶️", "🐉", "🦂", "👽", "🤠", "🐯", "💀", "🦁", "🍀", "🔥"];

/* ---------------- API ---------------- */

async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && state.me) {
      state.me = null;
      showAuth();
    }
    const msg = data && data.detail ? data.detail : "Error de conexión";
    throw new Error(typeof msg === "string" ? msg : "Datos inválidos");
  }
  return data;
}

/* ---------------- Sonido (WebAudio) ---------------- */

const sound = {
  enabled: localStorage.getItem("mf_sound") !== "off",
  ctx: null,
  ensure() {
    if (!this.ctx) this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (this.ctx.state === "suspended") this.ctx.resume();
    return this.ctx;
  },
  tone(freq, start, dur, type = "sine", gain = 0.15) {
    const ctx = this.ensure();
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    g.gain.setValueAtTime(0, ctx.currentTime + start);
    g.gain.linearRampToValueAtTime(gain, ctx.currentTime + start + 0.015);
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + start + dur);
    osc.connect(g).connect(ctx.destination);
    osc.start(ctx.currentTime + start);
    osc.stop(ctx.currentTime + start + dur + 0.05);
  },
  click() { if (this.enabled) { this.tone(2200, 0, 0.04, "square", 0.06); this.tone(1100, 0.015, 0.05, "triangle", 0.08); } },
  select() { if (this.enabled) this.tone(660, 0, 0.08, "triangle", 0.1); },
  coin() {
    if (!this.enabled) return;
    this.tone(988, 0, 0.09, "square", 0.07);
    this.tone(1319, 0.08, 0.22, "square", 0.07);
  },
  ding() {
    if (!this.enabled) return;
    this.tone(1568, 0, 0.3, "sine", 0.12);
    this.tone(2093, 0.05, 0.35, "sine", 0.08);
  },
  bust() {
    if (!this.enabled) return;
    const ctx = this.ensure();
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = "sawtooth";
    osc.frequency.setValueAtTime(300, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(60, ctx.currentTime + 0.4);
    g.gain.setValueAtTime(0.22, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.45);
    osc.connect(g).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.5);
  },
  fanfare() {
    if (!this.enabled) return;
    const notes = [523.25, 659.25, 783.99, 1046.5, 1318.5];
    notes.forEach((f, i) => {
      this.tone(f, i * 0.12, 0.35, "triangle", 0.14);
      this.tone(f / 2, i * 0.12, 0.35, "sine", 0.08);
    });
    this.tone(1046.5, 0.75, 0.9, "triangle", 0.16);
    this.tone(523.25, 0.75, 0.9, "sine", 0.1);
  },
  error() { if (this.enabled) { this.tone(220, 0, 0.15, "square", 0.08); this.tone(180, 0.1, 0.2, "square", 0.08); } },
};

function updateSoundIcon() { $("#sound-toggle").textContent = sound.enabled ? "🔊" : "🔇"; }
$("#sound-toggle").addEventListener("click", () => {
  sound.enabled = !sound.enabled;
  localStorage.setItem("mf_sound", sound.enabled ? "on" : "off");
  updateSoundIcon();
  if (sound.enabled) sound.select();
});

function vibrate(pattern) { if (navigator.vibrate) navigator.vibrate(pattern); }

/* ---------------- Toast / Sheet / Confeti ---------------- */

let toastTimer;
function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("error", isError);
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 2600);
  if (isError) { sound.error(); vibrate([60, 40, 60]); }
}

function openSheet(html) {
  $("#sheet").innerHTML = html;
  $("#sheet-backdrop").classList.remove("hidden");
}
function closeSheet() { $("#sheet-backdrop").classList.add("hidden"); }
$("#sheet-backdrop").addEventListener("click", (e) => {
  if (e.target.id === "sheet-backdrop") closeSheet();
});

function launchConfetti(durationMs = 4500) {
  const canvas = $("#confetti-canvas");
  const ctx = canvas.getContext("2d");
  canvas.width = innerWidth;
  canvas.height = innerHeight;
  const colors = ["#e3b34c", "#f3ebd8", "#c9962e", "#d6493e", "#3d6ea5"];
  const pieces = Array.from({ length: 140 }, () => ({
    x: Math.random() * canvas.width,
    y: -20 - Math.random() * canvas.height * 0.5,
    w: 6 + Math.random() * 6,
    h: 10 + Math.random() * 8,
    vy: 2 + Math.random() * 3.5,
    vx: -1.2 + Math.random() * 2.4,
    rot: Math.random() * Math.PI,
    vr: -0.12 + Math.random() * 0.24,
    color: colors[(Math.random() * colors.length) | 0],
  }));
  const start = performance.now();
  (function frame(now) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const p of pieces) {
      p.y += p.vy;
      p.x += p.vx + Math.sin(now / 300 + p.rot) * 0.6;
      p.rot += p.vr;
      if (p.y > canvas.height + 20) { p.y = -20; p.x = Math.random() * canvas.width; }
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot);
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
      ctx.restore();
    }
    if (now - start < durationMs) requestAnimationFrame(frame);
    else ctx.clearRect(0, 0, canvas.width, canvas.height);
  })(start);
}

function celebrate(winner) {
  $("#celebration-emoji").textContent = winner.emoji;
  $("#celebration-name").textContent = winner.username;
  $("#celebration").classList.remove("hidden");
  sound.fanfare();
  vibrate([80, 60, 80, 60, 200]);
  launchConfetti();
}
$("#celebration-close").addEventListener("click", () => {
  $("#celebration").classList.add("hidden");
  render();
});

/* ---------------- Utilidades ---------------- */

function fmtDate(iso) {
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return d.toLocaleDateString("es", { weekday: "short", day: "numeric", month: "short" }) +
    " · " + d.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return d.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
}
const medal = (pos) => ({ 1: "🥇", 2: "🥈", 3: "🥉" }[pos] || `${pos}º`);
const money = (n) => "$" + Number(n).toLocaleString("es");

function approvedCajas(game, userId) {
  return game.buyins.filter((b) => b.user.id === userId && b.status === "approved").length;
}
function hasPendingCaja(game, userId) {
  return game.buyins.some((b) => b.user.id === userId && b.status === "pending");
}

/* ---------------- Auth ---------------- */

function showAuth() {
  stopPolling();
  $("#auth").classList.remove("hidden");
  $("#tabbar").classList.add("hidden");
  $("#me-chip").classList.add("hidden");
  view.innerHTML = "";
  $("#auth-emojis").innerHTML = EMOJIS.map((e) =>
    `<button class="emoji-option ${e === state.newPlayerEmoji ? "selected" : ""}" data-emoji="${e}">${e}</button>`
  ).join("");
  $$("#auth-emojis .emoji-option").forEach((b) =>
    b.addEventListener("click", () => {
      sound.select();
      state.newPlayerEmoji = b.dataset.emoji;
      $$("#auth-emojis .emoji-option").forEach((x) => x.classList.toggle("selected", x === b));
    })
  );
  setAuthMode(state.authMode);
}

function setAuthMode(mode) {
  state.authMode = mode;
  $("#auth-tab-login").classList.toggle("active", mode === "login");
  $("#auth-tab-register").classList.toggle("active", mode === "register");
  $("#auth-emoji-wrap").classList.toggle("hidden", mode === "login");
  $("#auth-submit").textContent = mode === "login" ? "Entrar" : "Crear cuenta y entrar";
  $("#auth-pass").autocomplete = mode === "login" ? "current-password" : "new-password";
  $("#auth-error").classList.add("hidden");
}

$("#auth-tab-login").addEventListener("click", () => setAuthMode("login"));
$("#auth-tab-register").addEventListener("click", () => setAuthMode("register"));

async function submitAuth() {
  const username = $("#auth-user").value.trim();
  const password = $("#auth-pass").value;
  const errEl = $("#auth-error");
  errEl.classList.add("hidden");
  if (!username || !password) {
    errEl.textContent = "Completá usuario y contraseña";
    errEl.classList.remove("hidden");
    return;
  }
  try {
    const path = state.authMode === "login" ? "/auth/login" : "/auth/register";
    const body = state.authMode === "login"
      ? { username, password }
      : { username, password, emoji: state.newPlayerEmoji };
    state.me = await api(path, { method: "POST", body: JSON.stringify(body) });
    sound.fanfare();
    enterApp();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.classList.remove("hidden");
    sound.error();
  }
}
$("#auth-submit").addEventListener("click", submitAuth);
$("#auth-pass").addEventListener("keydown", (e) => { if (e.key === "Enter") submitAuth(); });

function enterApp() {
  $("#auth").classList.add("hidden");
  $("#tabbar").classList.remove("hidden");
  const chip = $("#me-chip");
  chip.textContent = `${state.me.emoji} ${state.me.username}`;
  chip.classList.remove("hidden");
  render();
}

/* ---------------- Navegación y polling ---------------- */

$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    sound.click();
    vibrate(10);
    state.tab = btn.dataset.tab;
    render();
  });
});

function stopPolling() {
  if (state.poller) { clearInterval(state.poller); state.poller = null; }
}

function startPolling() {
  stopPolling();
  state.poller = setInterval(async () => {
    if (document.hidden) return;
    try {
      const games = await api("/games?status=open,in_progress");
      const g = games[0] || null;
      const changed = JSON.stringify(g) !== state.lastGameJSON;
      const prev = state.activeGame;
      state.activeGame = g;
      state.lastGameJSON = JSON.stringify(g);

      // Si la partida que seguiamos termino, mostrar resultado + festejo
      if (prev && !g) {
        const done = await api(`/games/${prev.id}`);
        if (done.status === "finished" && state.celebratedGameId !== done.id) {
          state.celebratedGameId = done.id;
          if (state.tab === "game") renderResult(done);
          celebrate(done.winner);
          markTabs();
          return;
        }
      }
      if (changed && state.tab === "game" && !isSheetOpen()) renderGameTab();
      markTabs();
    } catch { /* sin conexión momentánea: se reintenta */ }
  }, 3000);
}

function isSheetOpen() {
  return !$("#sheet-backdrop").classList.contains("hidden");
}

async function refreshActive() {
  const games = await api("/games?status=open,in_progress");
  state.activeGame = games[0] || null;
  state.lastGameJSON = JSON.stringify(state.activeGame);
}

function markTabs() {
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === state.tab));
  const wrap = $('.tab[data-tab="game"] .tab-icon-wrap');
  const existing = $(".tab-badge", wrap);
  if (state.activeGame && !existing) {
    wrap.classList.add("tab-badge-wrap");
    const dot = document.createElement("span");
    dot.className = "tab-badge";
    wrap.appendChild(dot);
  } else if (!state.activeGame && existing) {
    existing.remove();
  }
}

async function render() {
  if (!state.me) return showAuth();
  try { await refreshActive(); } catch {}
  markTabs();
  startPolling();
  const renderers = { home: renderHome, game: renderGameTab, history: renderHistory, users: renderUsers, profile: renderProfile };
  try {
    await renderers[state.tab]();
  } catch (e) {
    view.innerHTML = `<div class="empty"><span class="e-icon">🔌</span><p>${esc(e.message)}</p></div>`;
  }
}

/* ---------------- Ranking ---------------- */

async function renderHome() {
  const stats = await api("/stats");
  const lb = stats.leaderboard.filter((s) => s.games_played > 0);

  let html = "";
  if (state.activeGame) {
    const g = state.activeGame;
    const label = g.status === "open" ? "Partida abierta, esperando jugadores" : "Partida en curso";
    const sub = g.status === "open"
      ? `${g.participants.length} anotados`
      : `${g.participants.filter((p) => p.position === null && (p.role || "player") === "player").length} siguen en pie`;
    html += `
      <button class="active-banner" id="go-active" style="width:100%">
        <span class="dot"></span>
        <span class="info" style="text-align:left"><b>${label}</b><span>${sub}</span></span>
        <span class="go">Ir →</span>
      </button>`;
  }

  html += `<div class="hero-count">Noches jugadas: <b>${stats.total_games}</b></div>`;

  if (lb.length === 0) {
    html += `
      <div class="empty">
        <span class="e-icon">♠️</span>
        <p>Todavía no hay partidas terminadas.<br>Armá la primera noche desde la pestaña Partida.</p>
      </div>`;
  } else {
    const [p1, p2, p3] = lb;
    html += `<div class="section-title">Podio histórico</div><div class="podium">`;
    html += podiumSlot(p1, 1) + podiumSlot(p2, 2) + podiumSlot(p3, 3);
    html += `</div><div class="section-title">Ranking</div><div class="card" style="padding:0">`;
    lb.forEach((s, i) => {
      html += `
        <div class="rank-row">
          <span class="rank-pos">${i + 1}</span>
          <span class="rank-emoji">${s.user.emoji}</span>
          <span class="rank-name">${esc(s.user.username)}
            ${s.current_streak >= 2 ? `<span class="rank-streak">🔥 ${s.current_streak} seguidas</span>` : ""}
          </span>
          <span class="rank-stats">
            <div class="rank-wins">${s.wins}</div>
            <div class="rank-sub">${s.games_played} jugadas · ${s.total_buyins} 🪙</div>
          </span>
        </div>`;
    });
    html += `</div>`;
  }

  view.innerHTML = html;
  $("#go-active")?.addEventListener("click", () => { state.tab = "game"; render(); });
}

function podiumSlot(s, pos) {
  if (!s) return `<div class="podium-slot podium-${pos}" style="opacity:.35"><span class="p-emoji">—</span><div class="p-name">Vacante</div></div>`;
  return `
    <div class="podium-slot podium-${pos}">
      <span class="p-medal">${medal(pos)}</span>
      <span class="p-emoji">${s.user.emoji}</span>
      <div class="p-name">${esc(s.user.username)}</div>
      <div class="p-wins">${s.wins} ${s.wins === 1 ? "victoria" : "victorias"}</div>
    </div>`;
}

/* ---------------- Pestaña Partida ---------------- */

async function renderGameTab() {
  const g = state.activeGame;
  if (!g) return renderCreate();
  if (g.status === "open") return renderLobby(g);
  return renderLive(g);
}

async function renderCreate() {
  const types = await api("/game-types");
  let selectedType = "knockout";

  let html = `<div class="section-title">Armar partida nueva</div>`;
  for (const t of types) {
    const locked = !t.available;
    html += `
      <button class="type-card ${t.id === selectedType ? "selected" : ""} ${locked ? "locked" : ""}"
              data-type="${t.id}" ${locked ? "data-locked=1" : ""}>
        <span class="t-icon">${t.id === "knockout" ? "☠️" : "💰"}</span>
        <span class="t-info">
          <div class="t-label">${esc(t.label)}</div>
          <div class="t-desc">${esc(t.description)}</div>
        </span>
        ${locked ? `<span class="t-soon">Pronto</span>` : ""}
      </button>`;
  }

  html += `
    <div class="section-title">Valor de la caja (opcional)</div>
    <div class="card">
      <input type="number" id="buyin-amount" inputmode="numeric" min="0" placeholder="Ej: 50000"
        style="width:100%;background:rgba(8,25,18,.6);border:1.5px solid var(--line);border-radius:14px;padding:13px 14px;color:var(--cream);font-size:16px" />
      <p style="font-size:12px;color:var(--cream-faint);margin-top:8px">
        Si lo cargás, la app calcula el pozo y cuánto puso cada uno.
      </p>
    </div>
    <div class="start-fixed">
      <button class="btn btn-gold" id="create-game">Abrir la mesa ♠</button>
      <p style="text-align:center;font-size:12px;color:var(--cream-faint);margin-top:8px">
        Vos vas a ser el administrador de esta partida
      </p>
    </div>`;

  view.innerHTML = html;

  $$("[data-type]").forEach((b) =>
    b.addEventListener("click", () => {
      if (b.dataset.locked) { toast("Esa modalidad llega pronto 🔒"); return; }
      sound.select();
      selectedType = b.dataset.type;
      $$("[data-type]").forEach((x) => x.classList.toggle("selected", x === b));
    })
  );

  $("#create-game").addEventListener("click", async () => {
    const raw = $("#buyin-amount").value.trim();
    const amount = raw ? Number(raw) : null;
    if (raw && (isNaN(amount) || amount < 0)) { toast("El valor de la caja no es válido", true); return; }
    try {
      const game = await api("/games", {
        method: "POST",
        body: JSON.stringify({ game_type: selectedType, buy_in_amount: amount }),
      });
      state.activeGame = game;
      state.lastGameJSON = JSON.stringify(game);
      sound.ding();
      vibrate([30, 30, 30]);
      renderGameTab();
      markTabs();
    } catch (e) { toast(e.message, true); }
  });
}

function playerTag(g, userId) {
  let t = "";
  if (userId === g.admin.id) t += ` <span class="admin-tag">Admin</span>`;
  if (userId === state.me.id) t += ` <span class="you-tag">Vos</span>`;
  return t;
}

function potBar(g) {
  const total = g.buyins.filter((b) => b.status === "approved").length;
  let html = `<div class="pot-bar">
    <div class="pot-item"><div class="pv">${g.participants.length}</div><div class="pl">Jugadores</div></div>
    <div class="pot-item"><div class="pv">${total} 🪙</div><div class="pl">Cajas</div></div>`;
  if (g.buy_in_amount) {
    html += `<div class="pot-item"><div class="pv">${money(total * g.buy_in_amount)}</div><div class="pl">Pozo</div></div>`;
  }
  return html + `</div>`;
}

function adminPendingCard(g) {
  const isAdmin = g.admin.id === state.me.id;
  if (!isAdmin) return "";
  const pendingBuyins = g.buyins.filter((b) => b.status === "pending");
  if (!pendingBuyins.length) return "";

  let html = `<div class="section-title">Solicitudes</div><div class="card pending-card">`;
  for (const b of pendingBuyins) {
    html += `
      <div class="pending-row">
        <span class="pr-emoji">${b.user.emoji}</span>
        <span class="pr-text"><b>${esc(b.user.username)}</b><span>pide una caja 🪙</span></span>
        <button class="mini-btn mini-no" data-reject="${b.id}">✕</button>
        <button class="mini-btn mini-ok" data-approve="${b.id}">Aprobar</button>
      </div>`;
  }
  return html + `</div>`;
}

function bindPendingActions(g) {
  $$("[data-approve]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        const updated = await api(`/games/${g.id}/buyins/${b.dataset.approve}/approve`, { method: "POST" });
        sound.coin();
        vibrate(20);
        updateGame(updated);
      } catch (e) { toast(e.message, true); }
    })
  );
  $$("[data-reject]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        const updated = await api(`/games/${g.id}/buyins/${b.dataset.reject}/reject`, { method: "POST" });
        sound.click();
        updateGame(updated);
      } catch (e) { toast(e.message, true); }
    })
  );
}

function myActionButtons(g) {
  const mine = g.participants.find((p) => p.user.id === state.me.id);
  if (!mine || mine.position !== null) return "";
  const pending = hasPendingCaja(g, state.me.id);
  const isSpectator = mine.role === "spectator";
  let html = `<div class="my-actions">`;
  if (isSpectator) {
    // El espectador solo puede pedir caja para sumarse a jugar
    html += pending
      ? `<button class="btn btn-ghost" disabled>🪙 Caja pedida, esperando…</button>`
      : `<button class="btn btn-gold" id="ask-caja">🪙 Comprar caja y jugar</button>`;
    return html + `</div>`;
  }
  html += pending
    ? `<button class="btn btn-ghost" disabled>🪙 Caja pedida…</button>`
    : `<button class="btn btn-gold" id="ask-caja">🪙 Pedir caja</button>`;
  if (g.status === "in_progress") {
    html += `<button class="btn btn-ghost" id="ask-exit">🏳️ Retirarme</button>`;
  }
  return html + `</div>`;
}

function bindMyActions(g) {
  $("#ask-caja")?.addEventListener("click", async () => {
    try {
      const updated = await api(`/games/${g.id}/buyins`, { method: "POST" });
      sound.coin();
      vibrate(20);
      toast("Caja pedida, esperando al admin 🪙");
      updateGame(updated);
    } catch (e) { toast(e.message, true); }
  });
  $("#ask-exit")?.addEventListener("click", () => {
    const alive = g.participants.filter((p) => p.position === null && (p.role || "player") === "player");
    openSheet(`
      <h3>¿Retirarte de la partida?</h3>
      <p>Salís al instante y te llevás el puesto ${alive.length}º de esta noche. No se puede deshacer desde acá.</p>
      <div class="btn-row">
        <button class="btn btn-ghost" id="sheet-cancel">Sigo jugando</button>
        <button class="btn btn-danger" id="sheet-ok">🏳️ Retirarme</button>
      </div>`);
    $("#sheet-cancel").addEventListener("click", closeSheet);
    $("#sheet-ok").addEventListener("click", async () => {
      closeSheet();
      sound.bust();
      vibrate([50, 30, 90]);
      try {
        const updated = await api(`/games/${g.id}/exit`, { method: "POST" });
        updateGame(updated);
      } catch (e) { toast(e.message, true); }
    });
  });
}

function updateGame(updated) {
  state.activeGame = updated.status === "open" || updated.status === "in_progress" ? updated : null;
  state.lastGameJSON = JSON.stringify(state.activeGame);
  if (updated.status === "finished") {
    if (state.celebratedGameId !== updated.id) {
      state.celebratedGameId = updated.id;
      renderResult(updated);
      celebrate(updated.winner);
    }
  } else {
    renderGameTab();
  }
  markTabs();
}

/* ---------- Lobby (partida abierta) ---------- */

function renderLobby(g) {
  const isAdmin = g.admin.id === state.me.id;
  const amIn = g.participants.some((p) => p.user.id === state.me.id);

  let html = `
    <div style="text-align:center">
      <span class="lobby-badge">🟡 Mesa abierta</span>
      <div class="live-header">
        <div class="lh-count">${g.participants.length}</div>
        <div class="lh-sub">anotados · admin: ${g.admin.emoji} ${esc(g.admin.username)}${g.buy_in_amount ? ` · caja ${money(g.buy_in_amount)}` : ""}</div>
      </div>
    </div>
    ${potBar(g)}
    ${adminPendingCard(g)}`;

  html += `<div class="section-title">En la mesa</div><div class="card" style="padding:0">`;
  for (const p of g.participants) {
    const cajas = approvedCajas(g, p.user.id);
    html += `
      <div class="player-row">
        <span class="p-emoji">${p.user.emoji}</span>
        <span class="p-name">${esc(p.user.username)}${playerTag(g, p.user.id)}</span>
        <span style="font-size:13px;color:var(--cream-dim)">${cajas ? cajas + " 🪙" : ""}</span>
      </div>`;
  }
  html += `</div>`;

  if (amIn) html += myActionButtons(g);

  if (isAdmin) {
    html += `
      <div class="btn-row" style="margin-top:12px">
        <button class="btn btn-ghost" id="cancel-btn" style="color:var(--red)">Cancelar</button>
        <button class="btn btn-gold" id="start-btn" ${g.participants.length < 2 ? "disabled" : ""}>Repartir ♠</button>
      </div>
      ${g.participants.length < 2 ? `<p class="wait-note"><span class="spin">♣</span> Esperando que se anote alguien más…</p>` : ""}`;
  } else if (!amIn) {
    html += `<button class="btn btn-gold" id="join-btn" style="margin-top:12px">Sentarme a la mesa ♠</button>`;
  } else {
    html += `
      <p class="wait-note"><span class="spin">♣</span> Esperando que ${esc(g.admin.username)} reparta…</p>
      <button class="btn btn-ghost" id="unjoin-btn" style="margin-top:8px">Bajarme de la mesa</button>`;
  }

  view.innerHTML = html;
  bindPendingActions(g);
  bindMyActions(g);

  $("#join-btn")?.addEventListener("click", async () => {
    try {
      const updated = await api(`/games/${g.id}/join`, { method: "POST" });
      sound.ding();
      vibrate([20, 20, 20]);
      updateGame(updated);
    } catch (e) { toast(e.message, true); }
  });
  $("#unjoin-btn")?.addEventListener("click", async () => {
    try {
      const updated = await api(`/games/${g.id}/unjoin`, { method: "POST" });
      sound.click();
      updateGame(updated);
    } catch (e) { toast(e.message, true); }
  });
  $("#start-btn")?.addEventListener("click", async () => {
    try {
      const updated = await api(`/games/${g.id}/start`, { method: "POST" });
      sound.fanfare();
      vibrate([30, 30, 60]);
      updateGame(updated);
    } catch (e) { toast(e.message, true); }
  });
  bindCancel(g);
}

function bindCancel(g) {
  $("#cancel-btn")?.addEventListener("click", () => {
    openSheet(`
      <h3>¿Cancelar la partida?</h3>
      <p>No se va a guardar ningún resultado de esta noche.</p>
      <div class="btn-row">
        <button class="btn btn-ghost" id="sheet-cancel">Volver</button>
        <button class="btn btn-danger" id="sheet-ok">Cancelar partida</button>
      </div>`);
    $("#sheet-cancel").addEventListener("click", closeSheet);
    $("#sheet-ok").addEventListener("click", async () => {
      try {
        await api(`/games/${g.id}/cancel`, { method: "POST" });
        closeSheet();
        state.activeGame = null;
        state.lastGameJSON = "null";
        toast("Partida cancelada");
        render();
      } catch (e) { closeSheet(); toast(e.message, true); }
    });
  });
}

/* ---------- Partida en vivo ---------- */

function renderLive(g) {
  const isAdmin = g.admin.id === state.me.id;
  const amIn = g.participants.some((p) => p.user.id === state.me.id);
  const alive = g.participants.filter((p) => p.position === null && (p.role || "player") === "player");
  const spectators = g.participants.filter((p) => p.position === null && p.role === "spectator");
  const out = g.participants
    .filter((p) => p.position !== null)
    .sort((a, b) => b.position - a.position);

  let html = `
    <div class="live-header">
      <div class="lh-label">☠️ Eliminación directa</div>
      <div class="lh-count">${alive.length}</div>
      <div class="lh-sub">siguen en pie${isAdmin ? " · tocá una ficha para sacar a alguien" : ""}</div>
    </div>
    ${potBar(g)}
    ${adminPendingCard(g)}
    <div class="live-grid">`;

  for (const p of alive) {
    const cajas = approvedCajas(g, p.user.id);
    html += `
      <button class="chip ${p.user.id === state.me.id ? "mine" : ""} ${isAdmin ? "" : "static"}"
              data-bust="${p.user.id}" data-name="${esc(p.user.username)}" data-emoji="${p.user.emoji}">
        ${cajas ? `<span class="ch-cajas">${cajas}</span>` : ""}
        <span class="ch-emoji">${p.user.emoji}</span>
        <span class="ch-name">${esc(p.user.username)}</span>
      </button>`;
  }
  html += `</div>`;

  if (!isAdmin) html += myActionButtons(g);

  // Botón para que un usuario que no está en la partida entre como espectador
  if (!amIn) {
    html += `<button class="btn btn-ghost" id="spectate-btn" style="margin-top:4px">👀 Mirar como espectador</button>`;
  }

  if (spectators.length) {
    html += `<div class="section-title">Espectadores</div><div class="card" style="padding:0">`;
    for (const p of spectators) {
      const pending = hasPendingCaja(g, p.user.id);
      html += `
        <div class="player-row">
          <span class="p-emoji">👀</span>
          <span class="p-name">${esc(p.user.username)}${p.user.id === state.me.id ? ' <span class="you-tag">Vos</span>' : ""}</span>
          <span style="font-size:13px;color:var(--cream-dim)">${pending ? "🪙 caja pedida" : "mirando"}</span>
        </div>`;
    }
    html += `</div>`;
  }

  if (out.length) {
    html += `<div class="section-title">Afuera</div><div class="card out-list" style="padding:0">`;
    for (const p of out) {
      const cajas = approvedCajas(g, p.user.id);
      html += `
        <div class="out-row">
          <span class="o-pos">${p.position}º</span>
          <span class="o-emoji">${p.user.emoji}</span>
          <span class="o-name">${esc(p.user.username)}</span>
          <span class="o-cajas">${cajas ? cajas + " 🪙" : ""}</span>
          <span class="o-time">🕐 ${fmtTime(p.eliminated_at)}</span>
          <span class="o-x">✕</span>
        </div>`;
    }
    html += `</div>`;
  }

  if (isAdmin) {
    html += `
      ${myActionButtons(g)}
      <div class="btn-row" style="margin-top:10px">
        <button class="btn btn-ghost" id="undo-btn" ${out.length ? "" : "disabled"}>↩ Deshacer</button>
        <button class="btn btn-ghost" id="cancel-btn" style="color:var(--red)">Cancelar</button>
      </div>`;
  }

  view.innerHTML = html;
  bindPendingActions(g);
  bindMyActions(g);

  $("#spectate-btn")?.addEventListener("click", async () => {
    try {
      const updated = await api(`/games/${g.id}/join`, { method: "POST" });
      sound.select();
      toast("Entraste como espectador 👀");
      updateGame(updated);
    } catch (e) { toast(e.message, true); }
  });

  if (isAdmin) {
    $$("[data-bust]").forEach((b) =>
      b.addEventListener("click", () => {
        sound.click();
        confirmEliminate(g, Number(b.dataset.bust), b.dataset.name, false, b);
      })
    );
    $("#undo-btn")?.addEventListener("click", async () => {
      try {
        const updated = await api(`/games/${g.id}/undo`, { method: "POST" });
        sound.select();
        updateGame(updated);
      } catch (e) { toast(e.message, true); }
    });
    bindCancel(g);
  }
}

function confirmEliminate(g, userId, name, isExit, chipEl) {
  const alive = g.participants.filter((p) => p.position === null && (p.role || "player") === "player");
  const target = g.participants.find((p) => p.user.id === userId);
  openSheet(`
    <span class="sheet-emoji">${target ? target.user.emoji : "☠️"}</span>
    <h3 style="text-align:center">${isExit ? `¿Confirmar el retiro de ${esc(name)}?` : `¿${esc(name)} quedó afuera?`}</h3>
    <p style="text-align:center">Se lleva el puesto ${alive.length}º de esta noche.</p>
    <div class="btn-row">
      <button class="btn btn-ghost" id="sheet-cancel">No, sigue</button>
      <button class="btn btn-danger" id="sheet-ok">${isExit ? "🏳️ Confirmar salida" : "☠️ Eliminar"}</button>
    </div>`);
  $("#sheet-cancel").addEventListener("click", closeSheet);
  $("#sheet-ok").addEventListener("click", async () => {
    closeSheet();
    if (chipEl) chipEl.classList.add("busting");
    sound.bust();
    vibrate([50, 30, 90]);
    try {
      const updated = await api(`/games/${g.id}/eliminate`, {
        method: "POST",
        body: JSON.stringify({ user_id: userId }),
      });
      setTimeout(() => updateGame(updated), chipEl ? 520 : 0);
    } catch (e) { toast(e.message, true); renderGameTab(); }
  });
}

function renderResult(game) {
  const ordered = [...game.participants].sort((a, b) => (a.position || 99) - (b.position || 99));
  const totalCajas = game.buyins.filter((b) => b.status === "approved").length;
  let html = `
    <div class="result-winner">
      <div class="rw-crown">👑</div>
      <span class="rw-emoji">${game.winner.emoji}</span>
      <div class="rw-name">${esc(game.winner.username)}</div>
      <div class="rw-sub">Campeón de la noche${game.buy_in_amount ? ` · pozo ${money(totalCajas * game.buy_in_amount)}` : ""}</div>
    </div>
    <div class="section-title">Posiciones finales</div>
    <div class="card" style="padding:0">`;
  for (const p of ordered) {
    const cajas = approvedCajas(game, p.user.id);
    html += `
      <div class="pos-row ${p.position === 1 ? "top1" : ""}">
        <span class="ps-pos">${medal(p.position)}</span>
        <span class="ps-emoji">${p.user.emoji}</span>
        <span class="ps-name">${esc(p.user.username)}</span>
        <span class="ps-time" style="margin-right:8px">${cajas ? cajas + " 🪙" : ""}</span>
        <span class="ps-time">${p.position === 1 ? "👑 " + fmtTime(game.finished_at) : "🕐 " + fmtTime(p.eliminated_at)}</span>
      </div>`;
  }
  html += `</div>
    <button class="btn btn-gold" id="new-after" style="margin-top:16px">Otra partida ♠</button>`;

  view.innerHTML = html;
  $("#new-after").addEventListener("click", () => { state.tab = "game"; render(); });
}

/* ---------------- Historial ---------------- */

async function renderHistory() {
  const games = (await api("/games")).filter((gm) => gm.status === "finished");

  if (games.length === 0) {
    view.innerHTML = `
      <div class="empty">
        <span class="e-icon">📜</span>
        <p>El historial está vacío.<br>Cuando termine la primera partida, queda registrada acá.</p>
      </div>`;
    return;
  }

  let html = "";
  for (const gm of games) {
    const ordered = [...gm.participants].sort((a, b) => (a.position || 99) - (b.position || 99));
    const totalCajas = gm.buyins.filter((b) => b.status === "approved").length;
    const canDelete = state.me.is_super;
    html += `
      <div class="card hist-card">
        <div class="hist-head">
          <span class="h-date">${fmtDate(gm.finished_at)}</span>
          <span class="h-type">☠️ Eliminación</span>
          ${canDelete ? `<button class="h-del" data-delg="${gm.id}" aria-label="Borrar partida">🗑️</button>` : ""}
        </div>
        <div class="hist-rank">`;
    for (const p of ordered) {
      const cajas = approvedCajas(gm, p.user.id);
      html += `
          <div class="pos-row ${p.position === 1 ? "top1" : ""}">
            <span class="ps-pos">${medal(p.position)}</span>
            <span class="ps-emoji">${p.user.emoji}</span>
            <span class="ps-name">${esc(p.user.username)}</span>
            <span class="ps-time" style="margin-right:8px">${cajas ? cajas + " 🪙" : ""}</span>
            <span class="ps-time">${p.position === 1 ? "👑 " + fmtTime(gm.finished_at) : "🕐 " + fmtTime(p.eliminated_at)}</span>
          </div>`;
    }
    html += `
        </div>
        ${totalCajas ? `<div class="hist-others" style="padding-bottom:12px">${totalCajas} 🪙 en cajas${gm.buy_in_amount ? " &nbsp;·&nbsp; pozo " + money(totalCajas * gm.buy_in_amount) : ""}</div>` : ""}
      </div>`;
  }
  view.innerHTML = html;

  $$("[data-delg]").forEach((b) =>
    b.addEventListener("click", () => {
      openSheet(`
        <h3>¿Borrar esta partida?</h3>
        <p>Se elimina del historial y deja de contar para el ranking.</p>
        <div class="btn-row">
          <button class="btn btn-ghost" id="sheet-cancel">Cancelar</button>
          <button class="btn btn-danger" id="sheet-ok">Borrar</button>
        </div>`);
      $("#sheet-cancel").addEventListener("click", closeSheet);
      $("#sheet-ok").addEventListener("click", async () => {
        try {
          await api(`/games/${b.dataset.delg}`, { method: "DELETE" });
          closeSheet();
          toast("Partida borrada");
          renderHistory();
        } catch (e) { closeSheet(); toast(e.message, true); }
      });
    })
  );
}

/* ---------------- Perfil ---------------- */

async function renderProfile() {
  const stats = await api("/stats");
  const mine = stats.leaderboard.find((s) => s.user.id === state.me.id);

  let html = `
    <div class="profile-head">
      <span class="pf-emoji">${state.me.emoji}</span>
      <div class="pf-name">${esc(state.me.username)}${state.me.is_super ? ' <span class="admin-tag">Superadmin</span>' : ""}</div>
    </div>`;

  if (mine && mine.games_played > 0) {
    html += `
      <div class="stat-grid">
        <div class="stat-box"><div class="sv">${mine.wins}</div><div class="sl">Victorias</div></div>
        <div class="stat-box"><div class="sv">${Math.round(mine.win_rate * 100)}%</div><div class="sl">De victorias</div></div>
        <div class="stat-box"><div class="sv">${mine.games_played}</div><div class="sl">Noches jugadas</div></div>
        <div class="stat-box"><div class="sv">${mine.total_buyins} 🪙</div><div class="sl">Cajas totales</div></div>
        <div class="stat-box"><div class="sv">${mine.avg_position ?? "—"}</div><div class="sl">Posición promedio</div></div>
        <div class="stat-box"><div class="sv">${mine.current_streak >= 2 ? "🔥 " : ""}${mine.current_streak}</div><div class="sl">Racha actual</div></div>
      </div>`;
  } else if (!state.me.is_super) {
    html += `<div class="empty"><span class="e-icon">🃏</span><p>Todavía no jugaste ninguna noche.<br>Tus números van a aparecer acá.</p></div>`;
  }

  html += `
    <div class="section-title">Mi cuenta</div>
    <button class="btn btn-ghost" id="change-pass-btn" style="margin-bottom:10px">🔑 Cambiar mi contraseña</button>
    <button class="btn btn-ghost" id="logout-btn">Cerrar sesión</button>`;
  view.innerHTML = html;

  $("#change-pass-btn").addEventListener("click", () => {
    openSheet(`
      <h3>Cambiar contraseña</h3>
      <p>Ingresá tu contraseña actual y la nueva.</p>
      <input type="password" id="cp-current" placeholder="Contraseña actual" class="sheet-input" autocomplete="current-password" />
      <input type="password" id="cp-new" placeholder="Contraseña nueva (mín. 4)" class="sheet-input" autocomplete="new-password" />
      <div class="btn-row" style="margin-top:14px">
        <button class="btn btn-ghost" id="sheet-cancel">Cancelar</button>
        <button class="btn btn-gold" id="sheet-ok">Guardar</button>
      </div>`);
    $("#sheet-cancel").addEventListener("click", closeSheet);
    $("#sheet-ok").addEventListener("click", async () => {
      const current = $("#cp-current").value;
      const nw = $("#cp-new").value;
      if (!current || !nw) { toast("Completá los dos campos", true); return; }
      if (nw.length < 4) { toast("La nueva debe tener al menos 4 caracteres", true); return; }
      try {
        await api("/auth/change-password", {
          method: "POST",
          body: JSON.stringify({ current_password: current, new_password: nw }),
        });
        closeSheet();
        sound.ding();
        toast("Contraseña actualizada ✓");
      } catch (e) { toast(e.message, true); }
    });
  });

  $("#logout-btn").addEventListener("click", async () => {
    try { await api("/auth/logout", { method: "POST" }); } catch {}
    state.me = null;
    stopPolling();
    showAuth();
  });
}

/* ---------------- Usuarios ---------------- */

async function renderUsers() {
  const [users, stats] = await Promise.all([api("/users"), api("/stats")]);
  const statsById = {};
  for (const s of stats.leaderboard) statsById[s.user.id] = s;
  const isSuper = state.me.is_super;

  let html = `<div class="section-title">Usuarios registrados (${users.length})</div>`;
  if (isSuper) {
    html += `<p style="font-size:13px;color:var(--cream-dim);margin-bottom:12px">👑 Como superadmin podés resetear contraseñas y borrar usuarios.</p>`;
  }
  html += `<div class="card" style="padding:0">`;

  for (const u of users) {
    const st = statsById[u.id];
    const sub = st && st.games_played > 0
      ? `${st.wins} 🏆 · ${st.games_played} jugadas · ${st.total_buyins} 🪙`
      : (u.is_super ? "cuenta de administración" : "sin partidas todavía");
    html += `
      <div class="user-row">
        <span class="p-emoji">${u.emoji}</span>
        <span class="user-info">
          <span class="user-name">${esc(u.username)}${u.is_super ? ' <span class="admin-tag">Super</span>' : ""}</span>
          <span class="user-sub">${sub}</span>
        </span>
        ${isSuper && !u.is_super ? `
          <button class="mini-btn mini-no" data-reset="${u.id}" data-name="${esc(u.username)}">🔑</button>
          <button class="mini-btn mini-red" data-deluser="${u.id}" data-name="${esc(u.username)}">🗑️</button>
        ` : ""}
      </div>`;
  }
  html += `</div>`;
  view.innerHTML = html;

  if (!isSuper) return;

  $$("[data-reset]").forEach((b) =>
    b.addEventListener("click", () => {
      openSheet(`
        <h3>Resetear contraseña de ${b.dataset.name}</h3>
        <p>Se le va a asignar una contraseña nueva. Avisale cuál es.</p>
        <input type="password" id="rp-new" placeholder="Contraseña nueva (mín. 4)" class="sheet-input" autocomplete="new-password" />
        <div class="btn-row" style="margin-top:14px">
          <button class="btn btn-ghost" id="sheet-cancel">Cancelar</button>
          <button class="btn btn-gold" id="sheet-ok">Resetear</button>
        </div>`);
      $("#sheet-cancel").addEventListener("click", closeSheet);
      $("#sheet-ok").addEventListener("click", async () => {
        const nw = $("#rp-new").value;
        if (!nw || nw.length < 4) { toast("Mínimo 4 caracteres", true); return; }
        try {
          await api("/users/reset-password", {
            method: "POST",
            body: JSON.stringify({ user_id: Number(b.dataset.reset), new_password: nw }),
          });
          closeSheet();
          sound.ding();
          toast(`Contraseña de ${b.dataset.name} reseteada ✓`);
        } catch (e) { toast(e.message, true); }
      });
    })
  );

  $$("[data-deluser]").forEach((b) =>
    b.addEventListener("click", () => {
      openSheet(`
        <h3>¿Borrar a ${b.dataset.name}?</h3>
        <p>Se elimina el usuario y sus sesiones. Las partidas que jugó quedan en el historial.</p>
        <div class="btn-row">
          <button class="btn btn-ghost" id="sheet-cancel">Cancelar</button>
          <button class="btn btn-danger" id="sheet-ok">Borrar usuario</button>
        </div>`);
      $("#sheet-cancel").addEventListener("click", closeSheet);
      $("#sheet-ok").addEventListener("click", async () => {
        try {
          await api(`/users/${b.dataset.deluser}`, { method: "DELETE" });
          closeSheet();
          toast(`${b.dataset.name} borrado`);
          renderUsers();
        } catch (e) { closeSheet(); toast(e.message, true); }
      });
    })
  );
}

/* ---------------- Arranque ---------------- */

updateSoundIcon();
(async () => {
  try {
    state.me = await api("/auth/me");
    enterApp();
  } catch {
    showAuth();
  }
})();
