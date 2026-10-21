"use strict";
// The Creatures page: retail's creature models, previewed in 3D and installed for a client with
// WarcraftXL's wxl.modern-m2 (retroport/workbench/creatures.py does the work).

const CR = {page: 0, total: 0, loading: false, token: 0, state: null, since: 0, timer: null, open: null};

function crParams() {
  return {q: $("#cr-q").value.trim(), named: $("#cr-named").checked ? 1 : 0, humanoids: $("#cr-humanoids").checked ? 1 : 0};
}

async function crSearch(reset) {
  const p = crParams();
  if (reset) { CR.page = 0; $("#cr-grid").replaceChildren(); $("#cr-more").hidden = true; }
  if (CR.loading && !reset) return;
  const token = ++CR.token;
  CR.loading = true;
  $("#cr-summary").textContent = CR.page ? "" : "Searching… (the first time reads retail's creature tables)";
  try {
    const res = await api("/api/creatures", {...p, page: CR.page});
    if (token !== CR.token) return;
    CR.total = res.total;
    $("#cr-grid").append(...res.rows.map(crCard));
    const shown = $("#cr-grid").children.length;
    $("#cr-summary").textContent = res.total ? `${res.total.toLocaleString()} creature displays · retail ${res.build}` +
      (shown < res.total ? ` · showing ${shown.toLocaleString()}` : "") : "Nothing matches.";
    $("#cr-more").hidden = shown >= res.total;
  } catch (e) { $("#cr-summary").textContent = e.message; }
  finally { if (token === CR.token) CR.loading = false; }
}

function crInBasket(display) { return !!(CR.state && CR.state.basket.some(e => e.display === display)); }
function crInGame(display) { return !!(CR.state && CR.state.installed.some(e => e.display === display)); }

function crCard(r) {
  const sub = [`display ${r.display}`, r.stem, r.textures.length ? plural(r.textures.length, "skin") : ""].filter(Boolean).join(" · ");
  const add = el("button", {class: "add" + (crInBasket(r.display) ? " in" : ""), title: "Add to the creature basket",
    onclick: ev => { ev.stopPropagation(); crToggle(r); const b = ev.currentTarget; setTimeout(() => { b.classList.toggle("in", crInBasket(r.display)); b.textContent = crInBasket(r.display) ? "✓" : "+"; }, 300); }},
    crInBasket(r.display) ? "✓" : "+");
  return el("div", {class: "card", "data-display": r.display, onclick: () => crOpen(r.display)},
    el("div", {class: "cr-glyph", "aria-hidden": "true"}, (r.name || "?").slice(0, 1).toUpperCase()),
    el("div", {class: "meta"},
      el("div", {class: "name", title: r.name}, r.name),
      el("div", {class: "sub", title: r.path}, sub,
        r.humanoid ? el("span", {class: "badge dim", title: "A dressed humanoid NPC: its look is baked from character parts"}, "humanoid") : null,
        crInGame(r.display) ? el("span", {class: "badge", title: "Installed by an earlier creature install"}, "in your game") : null)),
    add);
}

async function crToggle(r) {
  const b = CR.state.basket;
  const i = b.findIndex(e => e.display === r.display);
  if (i >= 0) b.splice(i, 1);
  else b.push({display: r.display, name: r.name, level: 80, faction: 14, rank: 0, scale: 1});
  await crSaveBasket();
  toast(i >= 0 ? `${r.name} taken out of the creature basket` : `${r.name} added to the creature basket`);
}

async function crSaveBasket() {
  CR.state.basket = await post("/api/creatures/basket", CR.state.basket);
  crRenderBasket();
}

async function crOpen(display) {
  const d = await api("/api/creature", {display});
  CR.open = display;
  $$("#cr-grid .card.sel").forEach(c => c.classList.remove("sel"));
  $$(`#cr-grid .card[data-display="${display}"]`).forEach(c => c.classList.add("sel"));
  const pb = previewBox("creature");
  const picker = pb.controls.querySelector(".pv-pick");
  if (picker) picker.hidden = true;                        // a creature has no race or sex to pick
  const load = shown => pb.load(async () => {
    const v = pb.v, token = ++PV.token;
    pb.info.textContent = "Loading the model…";
    try {
      const p = await api("/api/creature/preview", {display: shown});
      if (token !== PV.token) return;
      v.clear();
      v.add(p.mesh, {texUrl: texUrl(p.source)});
      v.fit("front");
      v.canvas.hidden = false;
      v.draw();
      pb.info.textContent = `${p.mesh.vertices.toLocaleString()} vertices · ${p.mesh.triangles.toLocaleString()} triangles · ` +
        `${plural(p.mesh.batches.length, "batch")}`;
      notes(pb.info, p.notes);
      if (p.mesh.anim_problem) notes(pb.info, [`Shown in its bind pose: ${p.mesh.anim_problem}`]);
      pb.textures.replaceChildren(...(p.row.textures || []).map(t => textureThumb(p.source)({fdid: t, name: `skin ${t}`})));
    } catch (e) { if (token === PV.token) pb.info.textContent = e.message; }
  });
  if (pb.v) load(display);

  // The skin picked under the preview is the one Add puts in the basket: the title, the details and
  // the button follow it.
  const title = el("h2", {class: "d-title"}), subtitle = el("div", {class: "muted"});
  const addBtn = el("button", {class: "btn"}), details = el("div");
  let shown = d;
  const markCard = x => $$(`#cr-grid .card[data-display="${x}"] .add`).forEach(b => {
    b.classList.toggle("in", crInBasket(x)); b.textContent = crInBasket(x) ? "✓" : "+"; });
  const render = x => {
    shown = x;
    CR.open = x.display;
    title.textContent = x.name;
    subtitle.textContent = `Creature display ${x.display} · model ${x.model}`;
    addBtn.textContent = crInBasket(x.display) ? "Take this skin out of the creature basket" : "Add this skin to the creature basket";
    const creatures = x.creatures.length ? el("div", {class: "small"}, x.creatures.map(([id, name]) =>
      el("div", {}, `${name} `, el("span", {class: "muted"}, `#${id}`)))) : el("div", {class: "muted small"}, "No retail creature names this display.");
    details.replaceChildren(...[
      section("Model", el("div", {class: "kv"},
        ...kv("Path", x.path || "(not in the listfile)"), ...kv("Model FileDataID", x.model), ...kv("Display", x.display),
        ...kv("Scale", `${x.scale} × model ${x.model_scale}`), ...kv("Skins", x.textures.join(", ") || "none"),
        ...kv("Collision", x.collision.map(c => c.toFixed(2)).join(" × ")))),
      section("Retail creatures with this look", creatures),
      x.humanoid ? el("div", {class: "warnline"}, "A dressed humanoid: retail builds its look from character models and a baked " +
        "texture, which this page does not port - it would stand there undressed.") : null,
    ].filter(Boolean));
  };
  addBtn.addEventListener("click", async () => { await crToggle(shown); render(shown); markCard(shown.display); });
  render(d);
  if (d.variations.length > 1) {
    pb.add(versionChips(d.variations.map(x => ({
      label: x.label, on: x.display === display,
      title: `display ${x.display}` + (x.displays > 1 ? ` (and ${x.displays - 1} more with the same skin)` : ""),
      pick: async () => { load(x.display); try { render(await api("/api/creature", {display: x.display})); } catch (e) { toast(e.message); } },
    }))));
  }
  showDrawer([title, subtitle, section("Preview", pb.box), el("div", {class: "actions"}, addBtn), details]);
}

// ---------------------------------------------------------------------------- basket and install
async function crLoadState() {
  try { CR.state = await api("/api/creatures/state"); } catch (e) { CR.state = {basket: [], installed: [], settings: {}, job: {}}; }
  $("#cr-count").textContent = CR.state.basket.length || "";
  crRenderBasket();
  crRenderJob(CR.state.job || {});
}

function crSelect(options, value, onChange) {
  const s = el("select", {}, Object.entries(options).map(([k, v]) => el("option", {value: k, selected: +k === +value}, v)));
  s.addEventListener("change", () => onChange(+s.value));
  return s;
}

function crField(label, input) { return el("label", {class: "cr-f"}, el("span", {}, label), input); }

function crNum(value, step, onChange, attrs = {}) {
  const i = el("input", {type: "number", value, step, ...attrs});
  i.addEventListener("change", () => onChange(+i.value));
  return i;
}

function crRenderBasket() {
  const st = CR.state;
  if (!st) return;
  $("#cr-count").textContent = st.basket.length || "";
  const save = debounce(crSaveBasket, 400);
  const rows = st.basket.map(e => {
    const name = el("input", {type: "text", value: e.name || "", maxlength: 100});
    name.addEventListener("input", () => { e.name = name.value; save(); });
    const sub = el("input", {type: "text", value: e.subname || "", maxlength: 100, placeholder: "subtitle"});
    sub.addEventListener("input", () => { e.subname = sub.value; save(); });
    return el("div", {class: "cr-row"},
      el("a", {href: "#", class: "cr-open", onclick: ev => { ev.preventDefault(); crOpen(e.display); }}, `#${e.display}`),
      crField("Name", name), crField("Subtitle", sub),
      crField("Level", crNum(e.level ?? 80, 1, v => { e.level = v; save(); }, {min: 1, max: 83})),
      crField("Faction", crSelect(st.factions, e.faction ?? 14, v => { e.faction = v; save(); })),
      crField("Rank", crSelect(st.ranks, e.rank ?? 0, v => { e.rank = v; save(); })),
      crField("Scale", crNum(e.scale ?? 1, 0.05, v => { e.scale = v; save(); }, {min: 0.05, max: 20})),
      el("button", {class: "remove", title: "Remove from the basket", onclick: async () => {
        st.basket = st.basket.filter(x => x !== e); await crSaveBasket(); }}, "×"));
  });
  // the basket panel is narrow while empty and grows with its rows (style.css .cr-top.full)
  $(".cr-top").classList.toggle("full", rows.length > 0);
  $("#cr-basket").replaceChildren(
    el("h3", {}, `Creature basket · ${plural(st.basket.length, "creature")}`),
    rows.length ? el("div", {class: "cr-rows"}, rows) : el("p", {class: "muted small"}, "Add creatures with + : Install puts them in your client and on your server."));
  const game = st.installed.map(e => el("div", {class: "cr-game"},
    el("a", {href: "#", onclick: ev => { ev.preventDefault(); crOpen(e.display); }}, e.name),
    el("span", {class: "muted small"}, e.ids ? ` entry ${e.ids.entry} · display ${e.ids.display}` : ""),
    e.ids ? el("button", {class: "copy", onclick: () => copy(`.npc add ${e.ids.entry}`)}, `.npc add ${e.ids.entry}`) : null,
    crInBasket(e.display) ? el("span", {class: "badge dim"}, "in the basket") : el("button", {class: "btn ghost small-btn",
      title: "Back in the basket: change its name, level or faction, or remove it, at the next Install",
      onclick: async () => { st.basket.push({...e, ids: undefined}); await crSaveBasket(); }}, "edit")));
  const s = st.settings || {};
  const conf = el("input", {type: "text", value: s.world_conf_set || "", placeholder: s.world_conf || "worldserver.conf"});
  const mysql = el("input", {type: "text", value: s.mysql_set || "", placeholder: s.mysql || "mysql.exe"});
  const run = el("input", {type: "checkbox", checked: s.run_sql !== false});
  const restart = el("input", {type: "checkbox", checked: !!s.restart});
  const saveSt = async () => {
    try {
      st.settings = await post("/api/creatures/settings",
        {world_conf: conf.value, mysql: mysql.value, run_sql: run.checked, restart: restart.checked});
      crRenderBasket();
    } catch (err) { toast(err.message); }
  };
  [conf, mysql, run, restart].forEach(i => i.addEventListener("change", saveSt));
  const ok = s.modern_m2 === "installed";
  $("#cr-game").replaceChildren(...[
    el("h3", {}, `In your game · ${plural(st.installed.length, "creature")}`),
    game.length ? el("div", {}, game) : el("p", {class: "muted small"}, "Nothing installed yet."),
    st.installed.length ? el("p", {class: "muted small"}, "To remove a creature: edit it, then × it in the basket and Install.") : null].filter(Boolean));
  $("#cr-where").replaceChildren(
    el("div", {class: ok ? "okline" : "warnline"}, `wxl.modern-m2 in your client: ${s.modern_m2 || "?"}`),
    el("div", {class: "small"}, `Client: ${s.client || "(Settings)"} · server dbc: ${s.server_dbc || "(none - the server's tables are left alone)"}`),
    el("div", {class: "small"}, `World database: ${s.database || "not found"}${s.world_conf ? ` (from ${s.world_conf})` : ""}`),
    el("div", {class: "form cr-db"},
      el("label", {class: "check"}, run, " Run the SQL on the world database (else it is saved for you to apply)"),
      el("label", {class: "check", title: "The client is closed and the worldserver shut down (it saves the players) " +
        "right before the patch is written, and both are started again when the install is done"},
        restart, " Restart the worldserver and client when the install is done"),
      crField("worldserver.conf (empty: found next to the server dbc folder)", conf),
      crField("MySQL client (empty: found on this computer)", mysql)));
}

function crRenderJob(j) {
  const running = j.state === "running";
  $("#cr-go").disabled = running;
  $("#cr-go").textContent = running ? "Installing…" : "Install creatures";
  $("#cr-steps").replaceChildren(...(j.steps || []).map(s => el("div", {class: "srow " + (s.state === "done" ? "ok" : s.state === "failed" ? "bad" : "")},
    s.state === "done" ? "✓ " : s.state === "failed" ? "✗ " : "… ", s.name)));
  const r = j.result;
  if (!r) { $("#cr-result").replaceChildren(); return; }
  const again = r.restarted && r.restarted.length ? `Started again: ${r.restarted.join(" and ")}.` : "";
  if (!r.ok) { $("#cr-result").replaceChildren(el("div", {class: "warnline"}, `Install stopped: ${r.error} ${again}`)); return; }
  $("#cr-result").replaceChildren(...[
    el("div", {class: "okline"}, `Installed ${plural(r.creatures.length, "creature")}.` +
      (r.sql_ran ? " The world database has them." : " Apply the SQL to your world database:")),
    r.sql_ran ? null : el("div", {class: "small"}, el("code", {}, `SOURCE ${r.sql.replace(/\\/g, "/")};`),
                          el("button", {class: "copy", onclick: () => copy(`SOURCE ${r.sql.replace(/\\/g, "/")};`)}, "copy")),
    el("p", {class: "small"}, again ? `${again} Once you're in the world, spawn one:` :
      "Restart the worldserver (it reads the creature tables at start), start the client, and spawn one:"),
    el("div", {class: "cr-npc"}, r.creatures.map(c => el("div", {},
      el("button", {class: "copy", onclick: () => copy(`.npc add ${c.entry}`)}, `.npc add ${c.entry}`), ` ${c.name} `,
      el("span", {class: "muted small"}, `display ${c.display} · model ${c.model}`),
      ...(c.notes || []).map(n => el("div", {class: "muted small"}, n)))))].filter(Boolean));
}

async function crPollJob() {
  clearTimeout(CR.timer);
  try {
    const j = await api("/api/creatures/job", {since: CR.since});
    if (j.log.length) {
      const log = $("#cr-log");
      log.textContent += j.log.join("\n") + "\n";
      log.scrollTop = log.scrollHeight;
    }
    CR.since = j.at;
    crRenderJob(j);
    if (j.state === "running") CR.timer = setTimeout(crPollJob, 800);
    else if (j.result) await crLoadState();
  } catch (e) { CR.timer = setTimeout(crPollJob, 2000); }
}

async function crInstall() {
  if (!CR.state.basket.length && !CR.state.installed.length) { toast("The creature basket is empty"); return; }
  try {
    $("#cr-log").textContent = ""; CR.since = 0;
    $("#cr-log-panel").open = true;
    crRenderJob(await post("/api/creatures/install", {}));
    crPollJob();
  } catch (e) { toast(e.message); }
}

function crShow() {
  if (!CR.wired) {
    CR.wired = true;
    const run = debounce(() => crSearch(true), 250);
    $("#cr-q").addEventListener("input", run);
    $("#cr-q").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); crSearch(true); } });
    $$("#cr-filters input[type=checkbox]").forEach(c => c.addEventListener("change", () => crSearch(true)));
    $("#cr-more").addEventListener("click", () => { if (!CR.loading) { CR.page++; crSearch(false); } });
    $("#cr-go").addEventListener("click", crInstall);
  }
  crLoadState().then(() => {
    if (!$("#cr-grid").children.length) crSearch(true);
    if (CR.state.job && CR.state.job.state === "running") crPollJob();
  });
}
