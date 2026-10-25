"use strict";
// The Spells page: retail spells' visuals, played as the game plays them - every model each event of
// the cast puts on the caster, the target or the ground, at its point, offset, turn and scale, from
// its moment to its end, and the missiles in flight (retroport/workbench/spells.py reads the tables).

const SP = {page: 0, total: 0, loading: false, token: 0, open: null, stage: null, wired: false};
const SP_DIST = 12;                    // yards between the stand-in caster and the target

function spParams() {
  const p = {q: $("#sp-q").value.trim(), models: $("#sp-models").checked ? 1 : 0};
  if ($("#sp-kind").value) {
    p.kind = $("#sp-kind").value;
    if (!$("#sp-key").hidden && $("#sp-key").value) p.key = $("#sp-key").value;
    if (!$("#sp-sub").hidden && $("#sp-sub").value) p.sub = $("#sp-sub").value;
  }
  return p;
}

// Wowhead's spell menus: a kind (class abilities, talents, mounts...), then a class, race, pet family
// or profession, then a specialization or hero tree (spellcats.py files every spell)
const SP_CLASS_KINDS = new Set(["abilities", "spec", "talents", "hero", "pvp", "glyphs"]);
async function spLoadFilters() {
  const kind = $("#sp-kind");
  kind.disabled = true;
  kind.firstChild.textContent = "Reading spell categories…";
  try { SP.filters = await api("/api/spells/filters"); }
  catch (e) { kind.firstChild.textContent = "All spells"; kind.disabled = false; toast(e.message); return; }
  kind.firstChild.textContent = "All spells";
  for (const g of SP.filters.kinds) {
    if (!g.kinds.length) continue;
    kind.append(el("optgroup", {label: g.group}, ...g.kinds.map(k => el("option", {value: k.id}, k.name))));
  }
  kind.disabled = false;
}

function spFilterMenus() {
  const f = SP.filters || {}, kind = $("#sp-kind").value, key = $("#sp-key"), sub = $("#sp-sub");
  const fill = (sel, first, items) => {
    const keep = sel.value;
    sel.replaceChildren(el("option", {value: ""}, first), ...items.map(x => el("option", {value: x.id}, x.name)));
    if ([...sel.options].some(o => o.value === keep)) sel.value = keep;
  };
  key.hidden = sub.hidden = true;
  if (SP_CLASS_KINDS.has(kind)) {
    fill(key, "Any class", (f.classes || []).filter(c => !["Adventurer", "Traveler"].includes(c.name)));
    key.hidden = false;
    const list = kind === "hero" ? f.hero : kind === "spec" || kind === "pvp" ? f.specs : null;
    if (list && key.value) {
      fill(sub, kind === "hero" ? "Any hero tree" : "Any specialization", list.filter(s => String(s.class) === key.value));
      sub.hidden = false;
    }
  } else if (["pet", "racial", "profession"].includes(kind)) {
    fill(key, {pet: "Any pet family", racial: "Any race", profession: "Any profession"}[kind], f[kind] || []);
    key.hidden = false;
  }
  $("#sp-bulk").hidden = !kind;
}

async function spBulk() {
  const p = spParams();
  if (!confirm(`Make every spell shown here (${SP.total.toLocaleString()}) a new spell? Each gets its plain visual, ` +
               `its own name and the first 3.3.5 spell suggested for its kind; you can change or remove any of them after.`)) return;
  const btn = $("#sp-bulk");
  btn.disabled = true; btn.textContent = "Making…";
  try {
    const r = await post("/api/spellport/bulk", p);
    SP.ports.ports = r.ports;
    spRenderPorts();
    toast(`${plural(r.added, "new spell")} made` + (r.skipped ? `, ${r.skipped} skipped` : "") +
          (r.skipped_examples.length ? ` (${r.skipped_examples.slice(0, 3).join("; ")})` : "") + " - Install puts them in the game");
  } catch (e) { toast(e.message); }
  btn.disabled = false; btn.textContent = "Make all shown";
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
  const dur = m => {
    const mesh = meshes.get(spKey(m)) || {}, play = spPlay(m, mesh);
    // a one-shot model: its intro once, then its outro
    const d = play.intro ? play.intro.duration + (play.outro ? play.outro.duration : 0) : mesh.duration || 0;
    return Math.max(600, Math.min(d || 2000, 8000));
  };
  const rows = [];
  for (const e of visual.events) {
    for (const m of e.models) {
      const from = when(e.start) + (e.offset[0] || 0) + (e.kit_delay[0] || 0) + (m.delay || 0) * 1000;
      let to = e.end === 13 ? from + dur(m) : when(e.end) + (e.end_offset[0] || 0);
      if (to <= from) to = from + dur(m);
      rows.push({kind: "model", e, m, from, to});
    }
    // area models (Blizzard's shards): copies at random points of the area, rate a second, while the
    // event lasts - each its own animation once, or for its lifetime (as wxl.retail-spellvisuals does)
    for (const a of e.area_models || []) {
      const from = when(e.start) + (e.offset[0] || 0) + (e.kit_delay[0] || 0);
      let to = e.end === 13 ? from + (detail.timing.duration || 1000) : when(e.end) + (e.end_offset[0] || 0);
      if (to <= from) to = from + 1000;
      const step = 1000 / Math.max(0.1, a.rate || 1), radius = SP.radius || 4;
      let seed = a.fdid % 9973 + 1;
      const rnd = () => (seed = seed * 16807 % 2147483647) / 2147483647;
      for (let t = from, k = 0; t < to && k < 80; t += step, k++) {
        const r = radius * Math.sqrt(rnd()), ang = rnd() * Math.PI * 2;
        const m = {...a, attachment: -1, offset: [r * Math.cos(ang), r * Math.sin(ang), 0],
                   rotation: [rnd() * Math.PI * 2, 0, 0], anims: [-1, -1, -1], flags: 0};
        const life = a.lifetime || dur(m);
        rows.push({kind: "model", e: {...e, end: a.lifetime ? 10 : 13}, m, from: t, to: t + life, copy: k > 0});
      }
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

// A retail effect model's animations, as the game plays them (wxl.retail-spellvisuals): Stand once as
// its intro, Hold for as long as its event lasts, Decay as it goes - or the kit's own start, loop and
// end. Each is {duration, bones}, or null for one the model lacks.
const SP_EFFECT_ANIMS = [0, 158, 159];
function spPlay(m, mesh) {
  const A = mesh.effectAnims || {}, [s, l, e] = m.anims || [-1, -1, -1], get = id => id >= 0 ? A[id] || null : null;
  const intro = s >= 0 ? get(s) : l >= 0 ? null : get(0);
  const loop = l >= 0 ? get(l) : get(158) || intro;
  return {intro, loop, outro: e >= 0 ? get(e) : get(159)};
}

function spEffectAnim(row, play) {
  const once = row.e.end === 13 || row.e.end === 0 || row.e.end === row.e.start;
  const introLen = play.intro ? play.intro.duration : 0;
  const pose = (a, now, loop) => a ? {tracks: a.bones, duration: a.duration,
    now: loop ? now % Math.max(1, a.duration) : Math.min(Math.max(0, now), a.duration - 1)} : null;
  return T => {
    const t = T - row.from;
    if (once) return t < introLen ? pose(play.intro, t) : pose(play.outro, t - introLen) || pose(play.intro, t);
    if (T >= row.to && play.outro) return pose(play.outro, T - row.to);
    if (t < introLen) return pose(play.intro, t);
    return pose(play.loop, t - introLen, true);
  };
}

function spAdd(v, row, mesh, stage) {
  const {m} = row;
  // an area's ground model (kit flag 0x8) is made one yard across its radius: stretched to the spell's
  const area = row.e.target === 3 && (m.flags & 8) && SP.radius ? SP.radius : 1;
  const scale = (m.scale || 1) * (m.attach_scale || 1) * area;
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
  const play = spPlay(m, mesh), anim = spEffectAnim(row, play);
  // a lasting model plays its outro after its event ends: it stays that much longer
  const once = (row.e.end === 13 || row.e.end === 0 || row.e.end === row.e.start);
  const window = [row.from, !once && play.outro ? row.to + play.outro.duration : row.to];
  const target = row.e.target;
  v.add(mesh, {texUrl: texUrl(SP.source), window, scale, offset: m.offset, anim, place: vv => {
    // a self-only spell (Bladestorm) is its own target: its target and ground events are on the caster
    if (target === 3) return spTurn(spPlaceAt(SP.selfOnly ? [0, 0, 0] : [SP_DIST, 0, 0], 0), m.rotation);
    const body = target === 1 || SP.selfOnly ? stage.caster : stage.target;
    // its positioner keeps it upright (a held book): at the point, turned as the body faces
    if (m.upright) return spTurn(spPlaceAt(M4.apply(spPoint(vv, body, m.attachment), [0, 0, 0]),
                                           body === stage.caster ? 0 : Math.PI), m.rotation);
    return spTurn(spPoint(vv, body, m.attachment), m.rotation);
  }});
}

// ---------------------------------------------------------------------------- the characters
// The race and sex picked under the preview, undressed, as caster and target. The caster plays what
// the spell's events on it ask for (an initial animation once, then its loop until the event ends);
// a spell that names none gets the ready-spell loop while casting and the cast at its end.
const SP_ANIM_NAMES = {51: "ReadySpellDirected", 52: "ReadySpellOmni", 53: "SpellCastDirected", 54: "SpellCastOmni",
                       126: "Whirlwind",
                       76: "ChannelCastDirected", 77: "ChannelCastOmni"};
async function spPeople(vis, timing) {
  const race = PV.race, sex = PV.sex;
  const body = await bodyOf(race, sex);
  const outfit = {pieces: [], dress_order: [], item_geosets: {}, problems: []};
  const skin = await compositeSkin(body, outfit, "bfa");
  const worn = wornGeosets(body, outfit);
  const types = {1: skin};
  if (body.hair) types[6] = `/tex/bfa/${body.hair}.png`;
  if (body.skin_extra) types[8] = `/tex/bfa/${body.skin_extra}.png`;

  const {wanted, ids} = spCasterWants(vis, timing);
  const anims = ids.length ? await api("/api/spell/body-anims", {race, sex, ids: ids.join(",")}) : {};
  const {anim, played, missing} = spCasterAnim(wanted, ids, anims);
  return {body, types, visible: id => shows(worn, id, true), anim, played, missing,
          who: `${body.name} ${sex ? "female" : "male"}`};
}

// what the caster plays: [{from, to, id, once, then}] (to is null for "as long as the animation lasts")
function spCasterWants(vis, timing) {
  const at = spMoments(timing, vis.missiles.length > 0);
  const when = e => at[e] ?? at[3];
  const wanted = [];
  let precast = false, cast = false;
  for (const e of vis.events) {
    if ((e.target !== 1 && !(SP.selfOnly && e.target !== 3)) || !e.anims || !e.anims.length) continue;
    const a = e.anims[0], from = when(e.start) + (e.offset[0] || 0);
    const to = e.end === 13 ? null : when(e.end) + (e.end_offset[0] || 0);
    if (a.initial >= 0) wanted.push({from, to: a.loop >= 0 ? null : to, id: a.initial, once: true, then: a.loop >= 0 ? {id: a.loop, to} : null});
    else if (a.loop >= 0) wanted.push({from, to, id: a.loop, once: false});
    if (a.initial < 0 && a.loop < 0) continue;     // no animation of its own: the defaults below play
    if (e.start === 1) precast = true;
    if (e.start === 3) cast = true;
  }
  if (!precast && timing.cast > 0) wanted.push({from: 0, to: timing.cast, id: 51, once: false});
  if (!cast) wanted.push({from: timing.cast || 0, to: null, id: 53, once: true});
  const ids = [...new Set(wanted.flatMap(w => [w.id, ...(w.then ? [w.then.id] : [])]))];
  return {wanted, ids};
}

// the caster's animation over time from [wanted] and the keyframes of each id ({id: {bones, duration}})
function spCasterAnim(wanted, ids, anims) {
  const segs = [];
  for (const w of wanted) {
    const a = anims[w.id];
    if (!a) continue;
    const end = w.to ?? w.from + a.duration;
    segs.push({from: w.from, to: Math.max(end, w.from + 1), a, once: w.once});
    if (w.then && anims[w.then.id]) {
      const b = anims[w.then.id], start = w.from + a.duration;
      const stop = w.then.to ?? start + b.duration;
      if (stop > start) segs.push({from: start, to: stop, a: b, once: false});
    }
  }
  segs.sort((x, y) => x.from - y.from);
  const anim = T => {
    let s = null;
    for (const x of segs) if (x.from <= T && T < x.to) s = x;
    if (!s) return null;
    const dt = T - s.from;
    return {tracks: s.a.bones, duration: s.a.duration, now: s.once ? Math.min(dt, s.a.duration - 1) : dt};
  };
  const played = ids.filter(i => anims[i]).map(i => SP_ANIM_NAMES[i] || `animation ${i}`);
  const missing = ids.filter(i => !anims[i]);
  return {anim, played, missing};
}

// A creature model in the preview (a summoned creature, a shapeshift form): its mesh, the keyframes
// of the animations asked for, and the model's FileDataID.
async function spCreature(display, ids) {
  const p = await api("/api/creature/preview", {display});
  const fdid = p.row && p.row.model;
  const anims = fdid && ids.length ? await api("/api/spell/model-anims", {fdid, ids: [...new Set(ids)].join(",")}).catch(() => ({})) : {};
  return {mesh: p.mesh, source: p.source, anims, fdid, glow: p.glow};
}

// The caster as the form the spell needs (Rage of the Sleeper: a bear): the form's model playing the
// spell's caster animations - a cast it lacks plays as its spell cast, else it stands.
async function spForm(form, vis, timing) {
  const {wanted, ids} = spCasterWants(vis, timing);
  const display = form.displays[PV.race] || form.displays["*"];
  const c = await spCreature(display, [...ids, 0, 51, 52, 53, 54]);
  const fill = {};
  for (const id of ids) fill[id] = c.anims[id] || c.anims[id === 51 || id === 52 ? 52 : 53] || c.anims[54] || c.anims[0] || null;
  const a = spCasterAnim(wanted, ids, fill), stand = c.anims[0];
  const anim = T => a.anim(T) || (stand ? {tracks: stand.bones, duration: stand.duration, now: T % stand.duration} : null);
  return {mesh: c.mesh, source: c.source, anim, played: a.played, who: form.name};
}

// ---------------------------------------------------------------------------- the drawer
async function spStage() {
  if (!SP.stage) SP.stage = api("/api/spell/stage").catch(e => { SP.stage = null; throw e; });
  return SP.stage;
}

async function spOpen(id) {
  let d;
  try { d = await api("/api/spell", {id}); } catch (e) { toast(e.message); return; }
  // the race choice lists your client's races (loaded with the item views, else here)
  if (!PV.races.length) { try { PV.races = await api("/api/races"); } catch (e) { /* the default list */ } }
  SP.open = id;
  $$("#sp-grid .card.sel").forEach(c => c.classList.remove("sel"));
  $$(`#sp-grid .card[data-spell="${id}"]`).forEach(c => c.classList.add("sel"));
  const pb = previewBox("spell");                        // its race and sex choice picks the stand-ins
  const t = d.timing;
  SP.selfOnly = !t.range;
  SP.radius = t.radius || 0;           // "Self Only": the caster is the target (its auras, its whirlwind)
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
  // the form the spell needs (Bear Form): the caster is shown as it, unless unticked
  const form = (d.forms || []).find(f => f.displays && Object.keys(f.displays).length);
  const formBox = el("input", {type: "checkbox", checked: true});
  if (form) pb.add(el("label", {class: "check small"}, formBox, ` Cast in ${form.name} (retail needs it)`));
  formBox.addEventListener("change", () => { if (visual) load(visual); });
  const summon = (d.summons || []).find(s => s.display);
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
      const people = await spPeople(vis, d.timing).catch(e => ({problem: e.message}));
      const shape = form && formBox.checked ? await spForm(form, vis, d.timing).catch(e => ({problem: e.message})) : null;
      const pet = summon ? await spCreature(summon.display, [0]).catch(e => ({problem: e.message})) : null;
      const stage = people.body ? null : await spStage();
      const models = [...vis.events.flatMap(e => [...e.models, ...(e.area_models || [])]), ...vis.missiles];
      const keys = [...new Map(models.map(m => [spKey(m), m])).values()];
      const meshes = new Map(), problems = [];
      await Promise.all(keys.map(async m => {
        try {
          const mesh = (await api("/api/spell/model", {fdid: m.fdid, texture: m.texture || 0})).mesh;
          // its intro, loop and outro: the kit's animations, else Stand, Hold and Decay (as in game)
          const want = [...new Set([...(m.anims || []).filter(x => x >= 0), ...SP_EFFECT_ANIMS])];
          mesh.effectAnims = await api("/api/spell/model-anims", {fdid: m.fdid, ids: want.join(",")}).catch(() => ({}));
          meshes.set(spKey(m), mesh);
        }
        catch (e) { problems.push(`${m.path || m.fdid}: ${e.message}`); }
      }));
      if (token !== PV.token) return;
      v.clear();
      const parts = shape && shape.mesh ? {
        caster: v.add(shape.mesh, {texUrl: texUrl(shape.source), place: () => spPlaceAt([0, 0, 0], 0), anim: shape.anim}),
        target: people.body ? v.add(people.body.mesh, {texUrl: texUrl("bfa"), types: people.types, visible: people.visible,
                                                      place: () => spPlaceAt([SP_DIST, 0, 0], Math.PI)})
                            : v.add((await spStage()).target.mesh, {texUrl: texUrl((await spStage()).target.source),
                                                                     place: () => spPlaceAt([SP_DIST, 0, 0], Math.PI)}),
      } : people.body ? {
        // the character you picked casts, playing the animations the spell's events ask for, at another
        caster: v.add(people.body.mesh, {texUrl: texUrl("bfa"), types: people.types, visible: people.visible,
                                         place: () => spPlaceAt([0, 0, 0], 0), anim: people.anim}),
        target: v.add(people.body.mesh, {texUrl: texUrl("bfa"), types: people.types, visible: people.visible,
                                         place: () => spPlaceAt([SP_DIST, 0, 0], Math.PI)}),
      } : {
        caster: v.add(stage.caster.mesh, {texUrl: texUrl(stage.caster.source), place: () => spPlaceAt([0, 0, 0], 0)}),
        target: v.add(stage.target.mesh, {texUrl: texUrl(stage.target.source), place: () => spPlaceAt([SP_DIST, 0, 0], Math.PI)}),
      };
      plan = spPlan(d, vis, meshes);
      // body glows (Avenging Wrath's gold, Bestial Wrath's red): the event's unit, from its start
      // moment to its end, fading in and out as the game does (wxl.retail-spellvisuals)
      const glows = vis.events.filter(e => e.glow && e.target !== 3).map(e => {
        const from = (plan.at[e.start] ?? plan.at[3]) + (e.offset[0] || 0);
        const to = e.end === 13 ? from + (e.glow.fade[0] || 0) * 1000 + 1000 : (plan.at[e.end] ?? plan.length);
        return {g: e.glow, from, to, on: e.target === 1 || SP.selfOnly ? "caster" : "target"};
      });
      for (const who of ["caster", "target"]) {
        const mine = glows.filter(x => x.on === who);
        if (!mine.length || !parts[who]) continue;
        parts[who].opts.glow = T => {
          for (const x of mine) {
            const fi = (x.g.fade[0] || 0) * 1000, fo = (x.g.fade[1] || 0) * 1000;
            if (T < x.from || T > x.to + fo) continue;
            let k = (fi ? Math.min(1, (T - x.from) / fi) : 1) * 0.7;   // as the game draws it (Glow.cpp kStrength)
            if (T > x.to) k *= fo ? Math.max(0, 1 - (T - x.to) / fo) : 0;
            const g = x.g;
            return {colors: g.colors, alphas: [g.alphas[0] * k, g.alphas[1] * k],
                    edge: g.halo_width && g.halo_width <= 2 && k > 0.35 ? g.halo : null};
          }
          return null;
        };
      }
      if (pet && pet.mesh) {
        // the summoned creature: there from the end of the cast, at the target's spot for an area spell
        // (an Infernal lands there), else beside the caster
        const stand = pet.anims[0];
        const ground = vis.events.some(e => e.target === 3 && e.models.length) && !SP.selfOnly;
        const spot = ground ? [SP_DIST, 0, 0] : [1.5, 3.2, 0];   // else behind the caster, as the camera sees it
        v.add(pet.mesh, {texUrl: texUrl(pet.source), glow: pet.glow, window: [plan.at[3], plan.length + 10000],
                         place: () => spPlaceAt(spot, 0),
                         anim: stand ? T => ({tracks: stand.bones, duration: stand.duration, now: T % stand.duration}) : undefined});
      }
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
        (shape && shape.mesh ? `cast in ${shape.who}` + (shape.played.length ? ` · plays ${shape.played.join(", ")}` : "") :
         people.body ? `cast by a ${people.who} at another ${SP_DIST} yards away` +
                       (people.played.length ? ` · plays ${people.played.join(", ")}` : "")
                     : `cast by a stand-in (Jaina) at a training post ${SP_DIST} yards away`) +
        (pet && pet.mesh ? ` · summons ${summon.name}` : "");
      if (shape && shape.problem) notes(pb.info, [`${form.name}: ${shape.problem}`]);
      if (pet && pet.problem) notes(pb.info, [`${summon.name}: ${pet.problem}`]);
      if (people.problem) notes(pb.info, [`No character body (${people.problem}): Jaina stands in`]);
      if (people.missing && people.missing.length) notes(pb.info, [`The body has no animation ${people.missing.join(", ")}`]);
      notes(pb.info, problems);
      if (plan.rows.some(r => r.m.moving)) notes(pb.info, ["Some models move along a scripted path (a positioner): shown at their first point"]);
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
      (e.area_models || []).length ? el("div", {class: "small"}, e.area_models.map(a => el("div", {class: "sp-model"},
        el("span", {}, a.path || `model ${a.fdid}`), " ",
        el("span", {class: "muted"}, `scattered over the area · ${+a.rate.toFixed(2)} a second` +
          (a.lifetime ? ` · each lasts ${a.lifetime / 1000} s` : ""))))) : null,
      e.other.length ? el("div", {class: "muted small"}, `Also: ${e.other.join(", ")}`) : null)),
      vis.missiles.length ? section("Missiles", el("div", {class: "small"}, vis.missiles.map(m => el("div", {class: "sp-model"},
        el("span", {}, m.path || `model ${m.fdid}`), " ",
        el("span", {class: "muted"}, `${m.attachment_name} → ${m.destination_name}`))))) : null);
  };

  const vis = d.visual_list;
  let shown = vis[0] || null;
  const port = spPortSection(d, () => shown);
  if (vis.length > 1) {
    pb.add(versionChips(vis.map((x, i) => ({
      label: `Visual ${x.id}` + (x.difficulty ? ` · difficulty ${x.difficulty}` : "") +
        (x.player_condition || x.unit_condition ? (x.baseline ? " · default" : " · with talents") : ""),
      on: i === 0, pick: () => { shown = x; renderVisual(x); load(x); port.showPlan(x); },
    }))));
  }
  // the tooltip as retail shows it (Wowhead's, every value filled in)
  const tip = el("div", {class: "sp-tooltip"}, el("span", {class: "muted small"}, "Asking Wowhead for the tooltip…"));
  api("/api/wowhead/spell-tooltip", {id: d.id}).then(t => tip.replaceChildren(
    el("img", {class: "sp-tip-icon", src: CR_ICON(t.icon), alt: "", width: 36, height: 36}),
    el("div", {class: "sp-tip-body"}, safeHtml(t.tooltip)))).catch(e => tip.replaceChildren(el("span", {class: "muted small"}, e.message)));
  const summoned = (d.summons || []).length ? section("Summons", el("div", {class: "small"}, d.summons.map(s => el("div", {},
    s.display ? el("a", {href: "#", title: "Open in Creatures", onclick: ev => { ev.preventDefault(); show_("creatures"); crOpen(s.display); }}, s.name)
              : el("span", {}, s.name),
    el("span", {class: "muted"}, ` #${s.npc}` + (s.display ? ` · display ${s.display}` : " · no display in the index")), " ",
    el("a", {href: `https://www.wowhead.com/npc=${s.npc}`, target: "_blank", rel: "noopener", class: "muted"}, "Wowhead"))))) : null;
  showDrawer([title, subtitle, tip, section("Preview", pb.box), summoned, section("Timeline", chart),
              vis.length ? section("Make a new spell", port.box) : null, details].filter(Boolean));
  if (!vis.length) { pb.info.textContent = "This spell has no visual."; return; }
  renderVisual(vis[0]);
  port.showPlan(vis[0]);
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
    ...plan.rows.filter(r => !r.copy).sort((a, b) => a.from - b.from).map(r => el("div", {class: "sp-row", title: `${(r.from / 1000).toFixed(2)} – ${(r.to / 1000).toFixed(2)} s`},
      el("div", {class: "sp-label"}, label(r)),
      el("div", {class: "sp-track"}, el("div", {class: "sp-bar" + (r.kind === "missile" ? " missile" : ""),
        style: `left:${pct(r.from)};width:${pct(r.to - r.from)}`})))),
    el("div", {class: "sp-playhead"}));
}

// ---------------------------------------------------------------------------- ports into the client
// A port puts one retail visual on one of the client's own spells; Install writes them all into
// Data\patch-S.MPQ (spellport.py), so casting that spell shows the retail effects.
async function spLoadPorts() {
  try { SP.ports = await api("/api/spellport"); } catch (e) { SP.ports = {ports: [], installed: [], patch: "patch-S.MPQ"}; }
  spRenderPorts();
}

async function spSavePorts(list) {
  SP.ports.ports = await post("/api/spellport/ports", list);
  spRenderPorts();
}

// New spells: each a retail spell's name, text, icon, timing and visual on the mechanics of one of
// your client's spells, with an id of its own. Install puts them in the client (Data\patch-S.MPQ)
// and the server's dbc folder; .learn <id> in game.
function spRenderPorts(result = SP.lastResult) {
  const st = SP.ports;
  if (!st) return;
  const key = p => `${p.id}:${p.template}:${p.visual}:${p.name}:${p.retail_visuals !== false}`;
  const installed = new Set((st.installed || []).map(key));
  const retailBox = p => {
    const box = el("input", {type: "checkbox", checked: p.retail_visuals !== false});
    box.addEventListener("change", async () => {
      try { await spSavePorts(st.ports.map(x => x === p ? {...x, retail_visuals: box.checked} : x)); }
      catch (e) { toast(e.message); }
    });
    return el("label", {class: "check small", title: "On: every retail model, at retail's moments, offsets, turns and " +
      "delays, drawn by the client mod wxl.retail-spellvisuals. Off: what fits 3.3.5's own kits."}, box, " retail visuals");
  };
  const rows = st.ports.map(p => el("div", {class: "sp-port"},
    el("b", {}, p.name), el("span", {class: "muted"}, ` #${p.id}`),
    el("span", {class: "muted small"}, ` · looks: `),
    el("a", {href: "#", onclick: ev => { ev.preventDefault(); spOpen(p.retail); }}, p.retail_name || `spell ${p.retail}`),
    el("span", {class: "muted small"}, ` · works like ${p.template_name} (${p.template})`),
    retailBox(p),
    installed.has(key(p))
      ? el("button", {class: "copy", title: "Copy the GM command", onclick: () => copy(`.learn ${p.id}`)}, `.learn ${p.id}`)
      : el("span", {class: "badge dim"}, "not installed yet"),
    el("button", {class: "remove", title: "Take this spell out at the next Install",
      onclick: async () => { try { await spSavePorts(st.ports.filter(x => x !== p)); } catch (e) { toast(e.message); } }}, "×")));
  const restart = el("input", {type: "checkbox", checked: !!SP.restart});
  restart.addEventListener("change", () => { SP.restart = restart.checked; });
  const wod = el("input", {type: "checkbox", checked: !st.options || st.options.wod_models !== false});
  const bodies = el("input", {type: "checkbox", checked: !!(st.options && st.options.bfa_bodies)});
  bodies.addEventListener("change", async () => {
    try { st.options = await post("/api/spellport/options", {bfa_bodies: bodies.checked}); }
    catch (e) { toast(e.message); }
  });
  const fly = el("input", {type: "checkbox", checked: !st.options || st.options.fly_everywhere !== false});
  fly.addEventListener("change", async () => {
    try { st.options = await post("/api/spellport/options", {fly_everywhere: fly.checked}); }
    catch (e) { toast(e.message); }
  });
  wod.addEventListener("change", async () => {
    try { st.options = await post("/api/spellport/options", {wod_models: wod.checked}); }
    catch (e) { toast(e.message); }
  });
  const go = el("button", {class: "btn", disabled: SP.installing}, SP.installing ? "Installing…" : "Install new spells");
  go.addEventListener("click", spInstall);
  const res = [];
  if (result) {
    if (!result.ok) res.push(el("div", {class: "warnline"}, `Install stopped: ${result.error}`));
    else {
      res.push(el("div", {class: "okline"}, result.made
        ? `Installed ${plural(result.made, "new spell")} into Data\\${result.patch}` +
          (result.server ? " and your server's spell tables." : " (no server dbc folder in Settings: the server can't cast them).") +
          (result.restarted && result.restarted.length ? ` Started again: ${result.restarted.join(" and ")}.`
                                                       : " Restart the worldserver and the client, then .learn the spell.")
        : `No new spells left: Data\\${result.patch} removed.`));
      if (result.note) res.push(el("div", {class: "warnline"}, result.note));
      if (result.shadowed && result.shadowed.length) res.push(el("div", {class: "warnline"},
        `A later patch overrides the spell tables: ${result.shadowed.join(", ")}`));
      for (const p of result.spells) if (p.notes.length) res.push(el("details", {class: "small"},
        el("summary", {}, `${p.name}: ${plural(p.notes.length, "note")}`),
        ...p.notes.map(n => el("div", {class: "muted"}, n))));
    }
  }
  $("#sp-ports").replaceChildren(
    el("h3", {}, `Your new spells · ${plural(st.ports.length, "spell")}`),
    rows.length ? el("div", {class: "sp-port-list"}, rows)
      : el("p", {class: "muted small"}, "None yet: open a spell and make a new spell from it."),
    el("div", {class: "sp-port-actions"}, go,
      el("label", {class: "check", title: "Close the client and the worldserver for the write and start them again after"},
        restart, " Restart the worldserver and client when done"),
      el("label", {class: "check", title: "On: your characters are WoD or BfA models, which have retail's newer animations - " +
        "spells play retail's own caster animations. Off: each newer animation plays as the 3.3.5 one retail falls back to. " +
        "Takes effect at the next Install."}, wod, " Retail caster animations"),
      el("label", {class: "check", title: "On: Install also puts BfA's character bodies in your client (Data\\patch-I.MPQ, " +
        "every classic race, both sexes; the first time takes a few minutes), and spells play their animations. " +
        "Off: Install takes them out again and your own bodies come back."}, bodies, " BfA character bodies"),
      el("label", {class: "check", title: "On: every area of Eastern Kingdoms, Kalimdor, Outland and Northrend lets flying " +
        "mounts fly, Dalaran too (AreaTable.dbc in your client and your server; Northrend still wants Cold Weather " +
        "Flying). Off: Install puts the areas back as they were. The worldserver reads it when it starts."},
        fly, " Fly everywhere")),
    ...res);
}

async function spInstall() {
  if (SP.installing) return;
  SP.installing = true; SP.lastResult = null; spRenderPorts();
  const wodOn = !SP.ports || !SP.ports.options || SP.ports.options.wod_models !== false;
  try { SP.lastResult = await post("/api/spellport/install", {restart: !!SP.restart, wod_models: wodOn}); }
  catch (e) { SP.lastResult = {ok: false, error: e.message}; }
  SP.installing = false;
  await spLoadPorts();
}

// the drawer's "Make a new spell" section: a name, the 3.3.5 spell whose mechanics it borrows (the
// suggestions fit the retail spell's kind and school), what the visual becomes in 3.3.5
function spPortSection(d, getVisual) {
  const box = el("div", {class: "sp-port-form"});
  const name = el("input", {type: "text", value: d.name, maxlength: 100, class: "sp-name", "aria-label": "Name"});
  const tplInput = el("input", {type: "number", min: 1, placeholder: "3.3.5 spell id", class: "sp-target", "aria-label": "Template spell"});
  const tplName = el("span", {class: "muted small"});
  const chips = el("div", {class: "chips"});
  const add = el("button", {class: "btn", disabled: true}, "Make this spell");
  const planBox = el("div", {class: "small"});
  let tpl = null;
  const pick = async id => {
    tplInput.value = id;
    tpl = null; add.disabled = true;
    if (!id) { tplName.textContent = ""; return; }
    tplName.textContent = "…";
    try { tpl = await api("/api/spellport/client-spell", {id}); tplName.textContent = `→ ${tpl.name}`; add.disabled = false; }
    catch (e) { tplName.textContent = e.message; }
  };
  tplInput.addEventListener("input", debounce(() => pick(+tplInput.value), 300));
  add.addEventListener("click", async () => {
    const vis = getVisual();
    if (!tpl || !vis) return;
    const list = SP.ports ? [...SP.ports.ports] : [];
    list.push({retail: d.id, retail_name: d.name, visual: vis.id, template: tpl.id, name: name.value.trim() || d.name});
    try {
      await spSavePorts(list);
      const made = SP.ports.ports[SP.ports.ports.length - 1];
      toast(`${made.name} will be spell ${made.id} after Install`);
    } catch (e) { toast(e.message); }
  });
  const showPlan = async vis => {
    planBox.replaceChildren(el("span", {class: "muted"}, "Working out the 3.3.5 kits…"));
    try {
      const pl = await api("/api/spellport/plan", {visual: vis.id, spell: d.id});
      chips.replaceChildren(...(pl.templates || []).map(t => el("button", {class: "chip", title: `Spell ${t.id}`,
        onclick: () => pick(t.id)}, t.name)));
      if (!tplInput.value && pl.templates && pl.templates.length) pick(pl.templates[0].id);
      const kits = Object.entries(pl.kits).map(([col, k]) => el("div", {},
        el("b", {}, pl.names[col] || col), ": ",
        [...Object.entries(k.slots).map(([s, m]) => `${(m.path || String(m.fdid)).split("/").pop()} (${s.replace("Effect", "").toLowerCase()})`),
         ...k.specials.map(m => `${(m.path || String(m.fdid)).split("/").pop()} (special)`)].join(", ") || "no models",
        k.anim != null ? el("span", {class: "muted"}, ` · animation ${k.anim}`) : null));
      if (pl.missile) kits.push(el("div", {}, el("b", {}, "missile"), `: ${(pl.missile.path || String(pl.missile.fdid)).split("/").pop()}`));
      planBox.replaceChildren(el("div", {class: "muted"}, `Looks (a ${pl.kind || "spell"} visual in 3.3.5):`), ...kits,
        pl.dropped.length ? el("details", {}, el("summary", {class: "muted"}, `${plural(pl.dropped.length, "thing")} 3.3.5 can't carry`),
          ...pl.dropped.map(x => el("div", {class: "muted"}, x))) : null);
    } catch (e) { planBox.replaceChildren(el("span", {class: "warnline"}, e.message)); }
  };
  box.append(
    el("div", {class: "sp-port-row"}, el("span", {class: "muted small"}, "Name"), name),
    el("div", {class: "sp-port-row"}, el("span", {class: "muted small"}, "Works like"), tplInput, tplName),
    chips,
    el("p", {class: "muted small"}, "Your new spell gets this retail spell's name, description, icon, cast time, range, duration, " +
      "cooldown, school and visual - and the mechanics (damage, effects, targets) of the 3.3.5 spell it works like."),
    el("div", {class: "sp-port-row"}, add), planBox);
  return {box, showPlan};
}

function spShow() {
  spLoadPorts();
  if (!SP.wired) {
    SP.wired = true;
    const run = debounce(() => spSearch(true), 300);
    $("#sp-q").addEventListener("input", run);
    $("#sp-q").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); spSearch(true); } });
    $("#sp-models").addEventListener("change", () => spSearch(true));
    $("#sp-kind").addEventListener("change", () => { $("#sp-key").value = ""; $("#sp-sub").value = ""; spFilterMenus(); spSearch(true); });
    $("#sp-key").addEventListener("change", () => { $("#sp-sub").value = ""; spFilterMenus(); spSearch(true); });
    $("#sp-sub").addEventListener("change", () => spSearch(true));
    $("#sp-bulk").addEventListener("click", spBulk);
    spLoadFilters();
    $("#sp-more").addEventListener("click", () => { if (!SP.loading) { SP.page++; spSearch(false); } });
  }
  if (!$("#sp-grid").children.length) spSearch(true);
}
