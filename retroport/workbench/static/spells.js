"use strict";
// The Spells page: retail spells' visuals, played as the game plays them - every model each event of
// the cast puts on the caster, the target or the ground, at its point, offset, turn and scale, from
// its moment to its end, and the missiles in flight (retroport/workbench/spells.py reads the tables).

const SP = {page: 0, total: 0, loading: false, token: 0, open: null, stage: null, wired: false};
const SP_DIST = 12;                    // yards between the stand-in caster and the target

function spParams() {
  return {q: $("#sp-q").value.trim(), models: $("#sp-models").checked ? 1 : 0};
}

async function spSearch(reset) {
  const p = spParams();
  if (reset) { SP.page = 0; $("#sp-grid").replaceChildren(); $("#sp-more").hidden = true; }
  if (SP.loading && !reset) return;
  const token = ++SP.token;
  SP.loading = true;
  $("#sp-summary").textContent = SP.page ? "" : "Searching… (the first time reads retail's spell tables: a few minutes)";
  try {
    const res = await api("/api/spells", {...p, page: SP.page});
    if (token !== SP.token) return;
    SP.total = res.total;
    SP.source = res.source;
    $("#sp-grid").append(...res.rows.map(spCard));
    const shown = $("#sp-grid").children.length;
    $("#sp-summary").textContent = res.total ? `${res.total.toLocaleString()} spells · retail ${res.build}` +
      (shown < res.total ? ` · showing ${shown.toLocaleString()}` : "") : "Nothing matches.";
    $("#sp-more").hidden = shown >= res.total;
  } catch (e) { $("#sp-summary").textContent = e.message; }
  finally { if (token === SP.token) SP.loading = false; }
}

function spCard(r) {
  const sub = [`spell ${r.id}`, r.models ? plural(r.models, "model") : "no models",
               r.visuals > 1 ? plural(r.visuals, "visual") : ""].filter(Boolean).join(" · ");
  return el("div", {class: "card", "data-spell": r.id, onclick: () => spOpen(r.id)},
    icon(r.icon, null, "", SP.source),
    el("div", {class: "meta"},
      el("div", {class: "name", title: r.name}, r.name),
      el("div", {class: "sub"}, sub)));
}

// ---------------------------------------------------------------------------- the cast's clock
// When each event happens (ms from the start of the cast), for this spell's cast time, travel time
// and duration. An aura or channel without a duration is shown for 4 seconds.
function spMoments(timing, flying) {
  const C = timing.cast || 0, L = timing.launch || 0;
  const speed = timing.speed > 0 ? timing.speed : (flying ? 30 : 0);
  const F = speed > 0 ? SP_DIST / speed * 1000 : 0;
  const D = timing.duration > 0 ? Math.min(timing.duration, 30000) : 4000;
  const hit = C + L + F;
  return {1: 0, 2: C, 3: C, 4: C + L, 5: hit, 6: hit, 7: hit, 8: hit + D, 9: hit, 10: hit + D, 11: C, 12: C + D};
}

function spPlan(detail, visual, meshes) {
  const flying = visual.missiles.length > 0;
  const at = spMoments(detail.timing, flying);
  const when = e => at[e] ?? at[3];
  const dur = m => { const d = (meshes.get(spKey(m)) || {}).duration || 0; return Math.max(600, Math.min(d || 2000, 8000)); };
  const rows = [];
  for (const e of visual.events) {
    for (const m of e.models) {
      const from = when(e.start) + (e.offset[0] || 0) + (e.kit_delay[0] || 0) + (m.delay || 0) * 1000;
      let to = e.end === 13 ? from + dur(m) : when(e.end) + (e.end_offset[0] || 0);
      if (to <= from) to = from + dur(m);
      rows.push({kind: "model", e, m, from, to});
    }
  }
  for (const m of visual.missiles) rows.push({kind: "missile", m, from: at[4], to: Math.max(at[5], at[4] + 300)});
  const length = Math.max(2000, ...rows.map(r => r.to)) + 800;
  return {rows, length, at};
}

const spKey = m => `${m.fdid}:${m.texture || 0}`;

// ---------------------------------------------------------------------------- placing models
function spPlaceAt(pos, yaw) {
  const c = Math.cos(yaw), s = Math.sin(yaw), m = M4.ident();
  m[0] = c; m[1] = s; m[4] = -s; m[5] = c;
  m[12] = pos[0]; m[13] = pos[1]; m[14] = pos[2];
  return m;
}
// yaw (about Z), pitch (Y), roll (X), radians
function spTurn(m, r) {
  const [yaw, pitch, roll] = r || [0, 0, 0];
  if (!yaw && !pitch && !roll) return m;
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch), cr = Math.cos(roll), sr = Math.sin(roll);
  const R = M4.ident();
  R[0] = cy * cp; R[1] = sy * cp; R[2] = -sp;
  R[4] = cy * sp * sr - sy * cr; R[5] = sy * sp * sr + cy * cr; R[6] = cp * sr;
  R[8] = cy * sp * cr + sy * sr; R[9] = sy * sp * cr - cy * sr; R[10] = cp * cr;
  return M4.mul(m, R);
}
function spPoint(v, body, id) {
  const m = id >= 0 ? v.attachMatrix({part: body, id}) : null;
  return m || v.modelMatrix(body) || IDENT;
}

function spAdd(v, row, mesh, stage) {
  const {m} = row, scale = (m.scale || 1) * (m.attach_scale || 1);
  if (row.kind === "missile") {
    // from the caster's point to the target's, nose first
    v.add(mesh, {texUrl: texUrl(SP.source), window: [row.from, row.to], scale, place: (vv, t) => {
      const a = M4.apply(spPoint(vv, stage.caster, m.attachment), [0, 0, 0]);
      const b = M4.apply(spPoint(vv, stage.target, m.destination >= 0 ? m.destination : 34), [0, 0, 0]);
      const f = Math.max(0, Math.min(1, (t - row.from) / ((row.to - row.from) || 1)));
      const p = a.map((x, k) => x + (b[k] - x) * f), d = sub(b, a);
      return spPlaceAt(p, Math.atan2(d[1], d[0]));
    }});
    return;
  }
  const target = row.e.target;
  v.add(mesh, {texUrl: texUrl(SP.source), window: [row.from, row.to], scale, offset: m.offset, place: vv => {
    if (target === 3) return spTurn(spPlaceAt([SP_DIST, 0, 0], 0), m.rotation);         // the ground at the target
    const body = target === 1 ? stage.caster : stage.target;
    return spTurn(spPoint(vv, body, m.attachment), m.rotation);
  }});
}

// ---------------------------------------------------------------------------- the drawer
async function spStage() {
  if (!SP.stage) SP.stage = api("/api/spell/stage").catch(e => { SP.stage = null; throw e; });
  return SP.stage;
}

async function spOpen(id) {
  let d;
  try { d = await api("/api/spell", {id}); } catch (e) { toast(e.message); return; }
  SP.open = id;
  $$("#sp-grid .card.sel").forEach(c => c.classList.remove("sel"));
  $$(`#sp-grid .card[data-spell="${id}"]`).forEach(c => c.classList.add("sel"));
  const pb = previewBox("spell");
  const picker = pb.controls.querySelector(".pv-pick");
  if (picker) picker.hidden = true;
  const t = d.timing;
  const secs = ms => `${(ms / 1000).toFixed(ms % 1000 ? 2 : 0)} s`;
  const title = el("h2", {class: "d-title"}, d.name);
  const subtitle = el("div", {class: "muted"}, [`Spell ${d.id}`, t.cast ? `${secs(t.cast)} cast` : "instant",
    t.duration > 0 ? `lasts ${secs(t.duration)}` : "", t.range ? `${t.range} yd` : "",
    t.speed ? `missile ${t.speed} yd/s` : ""].filter(Boolean).join(" · "));
  const play = el("button", {class: "btn ghost small-btn"}, "Pause");
  const slider = el("input", {type: "range", min: 0, max: 1000, value: 0, class: "sp-slider", "aria-label": "Time"});
  const clock = el("span", {class: "muted small sp-clock"}, "");
  const speed = el("select", {"aria-label": "Speed", title: "Slow motion"},
    [[1, "1×"], [0.5, "½×"], [0.25, "¼×"], [0.1, "⅒×"]].map(([x, n]) => el("option", {value: x}, n)));
  speed.addEventListener("change", () => { if (pb.v) pb.v.rate(+speed.value); });
  pb.add(el("div", {class: "sp-transport"}, play, slider, clock, speed));
  const chart = el("div", {class: "sp-chart"}), details = el("div");
  let plan = null, visual = null;

  play.addEventListener("click", () => {
    const v = pb.v; if (!v || !v.clock) return;
    v.pause(!v.clock.paused); play.textContent = v.clock.paused ? "Play" : "Pause";
  });
  slider.addEventListener("input", () => {
    const v = pb.v; if (!v || !v.clock) return;
    v.pause(true); play.textContent = "Play";
    v.seek(+slider.value / 1000 * v.clock.length);
  });

  const load = vis => pb.load(async () => {
    const v = pb.v, token = ++PV.token;
    visual = vis;
    pb.info.textContent = "Loading the stand-ins and the spell's models…";
    try {
      const stage = await spStage();
      const models = [...vis.events.flatMap(e => e.models), ...vis.missiles];
      const keys = [...new Map(models.map(m => [spKey(m), m])).values()];
      const meshes = new Map(), problems = [];
      await Promise.all(keys.map(async m => {
        try { meshes.set(spKey(m), (await api("/api/spell/model", {fdid: m.fdid, texture: m.texture || 0})).mesh); }
        catch (e) { problems.push(`${m.path || m.fdid}: ${e.message}`); }
      }));
      if (token !== PV.token) return;
      v.clear();
      const parts = {
        caster: v.add(stage.caster.mesh, {texUrl: texUrl(stage.caster.source), place: () => spPlaceAt([0, 0, 0], 0)}),
        target: v.add(stage.target.mesh, {texUrl: texUrl(stage.target.source), place: () => spPlaceAt([SP_DIST, 0, 0], Math.PI)}),
      };
      plan = spPlan(d, vis, meshes);
      for (const row of plan.rows) {
        const mesh = meshes.get(spKey(row.m));
        if (mesh) spAdd(v, row, mesh, parts);
      }
      // framed on the caster and the target, seen from the side: a huge ground effect doesn't push
      // the camera back
      v.fit("front");
      v.view = {yaw: -1.25, pitch: 0.3, dist: SP_DIST * 1.45, center: [SP_DIST / 2, 0, 1.2]};
      v.home = {...v.view, center: [...v.view.center]};
      v.canvas.hidden = false;
      let last = -1;
      v.timeline(plan.length, now => {
        const k = Math.floor(now / 50);
        if (k === last) return;
        last = k;
        slider.value = Math.round(now / plan.length * 1000);
        clock.textContent = `${(now / 1000).toFixed(1)} / ${(plan.length / 1000).toFixed(1)} s`;
        chart.style.setProperty("--playhead", `${now / plan.length * 100}%`);
      });
      v.rate(+speed.value);
      play.textContent = "Pause";
      pb.info.textContent = `${plural(plan.rows.length, "model")} on ${keys.length} file${keys.length === 1 ? "" : "s"} · ` +
        `cast by a stand-in (Jaina) at a training post ${SP_DIST} yards away`;
      notes(pb.info, problems);
      if (plan.rows.some(r => r.m.positioner)) notes(pb.info, ["Some models use a positioner (a scripted path): shown at their point"]);
      spChart(chart, plan);
    } catch (e) { if (token === PV.token) pb.info.textContent = e.message; }
  });

  const renderVisual = vis => {
    details.replaceChildren(...vis.events.map(e => section(
      `${e.start_name} → ${e.end_name} · on the ${e.target_name}` + (e.offset[0] ? ` · +${e.offset[0]} ms` : ""),
      e.models.length ? el("div", {class: "small"}, e.models.map(m => el("div", {class: "sp-model"},
        el("span", {}, m.path || `model ${m.fdid}`), " ",
        el("span", {class: "muted"}, `${m.attachment_name}` + (m.offset.some(x => x) ? ` · offset ${m.offset.map(x => +x.toFixed(2)).join(", ")}` : "") +
          ` · scale ${+((m.scale || 1) * (m.attach_scale || 1)).toFixed(2)}` + (m.delay ? ` · after ${m.delay}s` : "")))))
        : el("div", {class: "muted small"}, "No models."),
      e.other.length ? el("div", {class: "muted small"}, `Also: ${e.other.join(", ")}`) : null)),
      vis.missiles.length ? section("Missiles", el("div", {class: "small"}, vis.missiles.map(m => el("div", {class: "sp-model"},
        el("span", {}, m.path || `model ${m.fdid}`), " ",
        el("span", {class: "muted"}, `${m.attachment_name} → ${m.destination_name}`))))) : null);
  };

  const vis = d.visual_list;
  if (vis.length > 1) {
    pb.add(versionChips(vis.map((x, i) => ({
      label: `Visual ${x.id}` + (x.difficulty ? ` · difficulty ${x.difficulty}` : "") + (x.player_condition || x.unit_condition ? " · conditional" : ""),
      on: i === 0, pick: () => { renderVisual(x); load(x); },
    }))));
  }
  showDrawer([title, subtitle, section("Preview", pb.box), section("Timeline", chart), details]);
  if (!vis.length) { pb.info.textContent = "This spell has no visual."; return; }
  renderVisual(vis[0]);
  if (pb.v) load(vis[0]);
}

// every model as a bar over the cast's time, with the event moments marked
function spChart(box, plan) {
  const pct = ms => `${ms / plan.length * 100}%`;
  const label = r => r.kind === "missile" ? `missile · ${r.m.path || r.m.fdid}` :
    `${r.e.start_name} · ${r.e.target_name}${r.e.target === 3 ? "" : " " + r.m.attachment_name} · ${(r.m.path || String(r.m.fdid)).split("/").pop()}`;
  const marks = [[1, "precast"], [3, "cast"], [6, "impact"], [8, "aura end"]]
    .filter(([e], i, a) => a.findIndex(([x]) => plan.at[x] === plan.at[e]) === i)
    .map(([e, n]) => el("div", {class: "sp-mark", style: `left:${pct(plan.at[e])}`, title: n}, el("span", {}, n)));
  box.replaceChildren(el("div", {class: "sp-marks"}, marks),
    ...plan.rows.sort((a, b) => a.from - b.from).map(r => el("div", {class: "sp-row", title: `${(r.from / 1000).toFixed(2)} – ${(r.to / 1000).toFixed(2)} s`},
      el("div", {class: "sp-label"}, label(r)),
      el("div", {class: "sp-track"}, el("div", {class: "sp-bar" + (r.kind === "missile" ? " missile" : ""),
        style: `left:${pct(r.from)};width:${pct(r.to - r.from)}`})))),
    el("div", {class: "sp-playhead"}));
}

function spShow() {
  if (!SP.wired) {
    SP.wired = true;
    const run = debounce(() => spSearch(true), 300);
    $("#sp-q").addEventListener("input", run);
    $("#sp-q").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); spSearch(true); } });
    $("#sp-models").addEventListener("change", () => spSearch(true));
    $("#sp-more").addEventListener("click", () => { if (!SP.loading) { SP.page++; spSearch(false); } });
  }
  if (!$("#sp-grid").children.length) spSearch(true);
}
