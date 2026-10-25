"use strict";
// The Mounts page: retail's mounts - previewed with your character in the saddle - put in the 3.3.5
// client and server as a creature (model, skins, sounds), a mount spell (speeds) and the item that
// teaches it (retroport/workbench/mounts.py does the work).

const MT = {page: 0, total: 0, loading: false, token: 0, state: null, since: 0, timer: null, wired: false};
const MT_KINDS = {ground: "Ground", flying: "Flying", aquatic: "Aquatic"};
// the mount's own animations to show it with (3.3.5 ids), and the rider's
const MT_ANIMS = [[0, "Stand"], [4, "Walk"], [5, "Run"], [193, "Hover"], [135, "Fly"]];
const MT_RIDER = 91;                                   // Mount: the rider's seated loop

// retail's source text: colour codes and inline textures out
const mtPlain = s => String(s || "").replace(/\|c[0-9A-Fa-f]{8}/g, "").replace(/\|r/g, "").replace(/\|T[^|]*\|t/g, "")
  .replace(/\|n/g, "\n");
const mtSpeed = v => `+${(+v || 0) + 1}%`;

async function mtSearch(reset) {
  if (reset) { MT.page = 0; $("#mt-grid").replaceChildren(); $("#mt-more").hidden = true; }
  if (MT.loading && !reset) return;
  const token = ++MT.token;
  MT.loading = true;
  $("#mt-summary").textContent = MT.page ? "" : "Searching… (the first time reads retail's mount tables)";
  try {
    const res = await api("/api/mounts", {q: $("#mt-q").value.trim(), kind: $("#mt-kind").value, page: MT.page});
    if (token !== MT.token) return;
    MT.source = res.source || MT.source;
    $("#mt-grid").append(...res.rows.map(mtCard));
    const shown = $("#mt-grid").children.length;
    $("#mt-summary").textContent = res.total ? `${res.total.toLocaleString()} mounts` +
      (shown < res.total ? ` · showing ${shown.toLocaleString()}` : "") : "Nothing matches.";
    $("#mt-more").hidden = shown >= res.total;
  } catch (e) { $("#mt-summary").textContent = e.message; }
  finally { if (token === MT.token) MT.loading = false; }
}

const mtInBasket = id => !!(MT.state && MT.state.basket.some(e => e.id === id));
const mtInGame = id => !!(MT.state && MT.state.installed.some(e => e.id === id));

function mtCard(m) {
  const sub = [MT_KINDS[m.kind], m.item ? m.item.name : "no item", `spell ${m.spell}`].join(" · ");
  const add = el("button", {class: "add" + (mtInBasket(m.id) ? " in" : ""), title: "Add to the mount basket",
    onclick: async ev => { ev.stopPropagation(); const b = ev.currentTarget; await mtToggle(m);
                           b.classList.toggle("in", mtInBasket(m.id)); b.textContent = mtInBasket(m.id) ? "✓" : "+"; }},
    mtInBasket(m.id) ? "✓" : "+");
  return el("div", {class: "card", "data-mount": m.id, onclick: () => mtOpen(m.id)},
    icon(m.icon || (m.item && m.item.icon), m.item ? m.item.quality : 4, "", MT.source || "retail"),
    el("div", {class: "meta"},
      el("div", {class: "name", title: m.name}, m.name),
      el("div", {class: "sub"}, sub, mtInGame(m.id) ? el("span", {class: "badge"}, "in your game") : null)),
    add);
}

async function mtToggle(m, opts = {}) {
  const b = MT.state.basket, i = b.findIndex(e => e.id === m.id);
  if (i >= 0 && !opts.keep) b.splice(i, 1);
  else if (i >= 0) Object.assign(b[i], opts);
  else b.push({id: m.id, name: m.name, display: (opts.display || m.displays[0]),
               ground: opts.ground ?? 99, flying: opts.flying ?? (m.kind === "flying" ? 279 : 0)});
  MT.state.basket = await post("/api/mounts/basket", b);
  mtRenderBasket();
  if (!opts.keep) toast(i >= 0 ? `${m.name} taken out of the mount basket` : `${m.name} added to the mount basket`);
}

// ---------------------------------------------------------------------------- the drawer
async function mtOpen(id) {
  let d;
  try { d = await api("/api/mount", {id}); } catch (e) { toast(e.message); return; }
  if (!PV.races.length) { try { PV.races = await api("/api/races"); } catch (e) { /* the default list */ } }
  $$("#mt-grid .card.sel").forEach(c => c.classList.remove("sel"));
  $$(`#mt-grid .card[data-mount="${id}"]`).forEach(c => c.classList.add("sel"));
  const inB = () => MT.state.basket.find(e => e.id === d.id);
  const pick = {display: (inB() || {}).display || (d.looks[0] || {}).display || d.displays[0],
                ground: (inB() || {}).ground ?? 99, flying: (inB() || {}).flying ?? d.default_speed.flying, anim: 0};
  const pb = previewBox("mount");                 // its race and sex choice is the rider
  const animChips = versionChips(MT_ANIMS.filter(([a]) => d.kind === "flying" || (a !== 193 && a !== 135))
    .map(([a, n]) => ({label: n, on: a === 0, pick: () => { pick.anim = a; load(); }})));
  pb.add(animChips);
  if (d.looks.length > 1) pb.add(versionChips(d.looks.map((l, k) => ({label: `Look ${k + 1}`, title: `display ${l.display}`,
    on: l.display === pick.display, pick: () => { pick.display = l.display; load(); save(); }}))));

  const load = () => pb.load(async () => {
    const v = pb.v, token = ++PV.token;
    pb.info.textContent = "Loading the mount and its rider…";
    try {
      const p = await api("/api/creature/preview", {display: pick.display});
      const fdid = p.row && p.row.model;
      const wantM = [...new Set([pick.anim, 0])];
      const [mAnims, rider] = await Promise.all([
        fdid ? api("/api/spell/model-anims", {fdid, ids: wantM.join(",")}).catch(() => ({})) : {},
        mtRider().catch(e => ({problem: e.message}))]);
      if (token !== PV.token) return;
      v.clear();
      const a = mAnims[pick.anim] || mAnims[0];
      const loop = x => x ? T => ({tracks: x.bones, duration: x.duration, now: T % Math.max(1, x.duration)}) : undefined;
      const lift = pick.anim === 193 || pick.anim === 135 ? 2 : 0;
      const mount = v.add(p.mesh, {texUrl: texUrl(p.source), glow: p.glow, anim: loop(a), place: () => spPlaceAt([0, 0, lift], 0)});
      let seated = false;
      if (rider.body) {
        // the rider sits on the mount's attachment 0, as the client seats every rider
        const has = (p.mesh.attachments || []).some(x => x.id === 0) || true;
        v.add(rider.body.mesh, {texUrl: texUrl("bfa"), types: rider.types, visible: rider.visible, anim: rider.anim,
          place: vv => vv.attachMatrix({part: mount, id: 0}) || spPlaceAt([0, 0, lift + 1.5], 0)});
        seated = has;
      }
      v.fit("front");
      v.view.yaw = 1.15;                               // from the side: the mount's length, the rider's seat
      v.home = {...v.view, center: [...v.view.center]};
      v.canvas.hidden = false;
      v.draw();
      pb.info.textContent = `${p.mesh.vertices.toLocaleString()} vertices · ${MT_ANIMS.find(([x]) => x === pick.anim)[1]}` +
        (rider.body ? ` · ridden by a ${rider.who}${rider.anim ? "" : " (its body has no Mount animation)"}` : "");
      if (rider.problem) notes(pb.info, [`No rider (${rider.problem})`]);
      if (!a && pick.anim) notes(pb.info, [`This model has no ${MT_ANIMS.find(([x]) => x === pick.anim)[1]} animation`]);
      if (!seated) notes(pb.info, ["The model has no mount point (attachment 0): the rider would float"]);
      if (d.looks.length && d.looks.every(l => !l.textures.length))
        notes(pb.info, ["A customizable mount (Dragonriding era): retail builds its skin and parts from mount " +
                        "customization, which isn't ported - it shows untextured, with every part at once"]);
    } catch (e) { if (token === PV.token) pb.info.textContent = e.message; }
  });

  const save = () => { if (inB()) mtToggle(d, {keep: true, display: pick.display, ground: pick.ground, flying: pick.flying}); };
  const speedSel = (label, list, val, set) => {
    const s = el("select", {"aria-label": label}, list.map(x => el("option", {value: x, selected: x === +val}, mtSpeed(x))));
    s.addEventListener("change", () => { set(+s.value); save(); });
    return el("label", {class: "efield"}, el("span", {}, label), s);
  };
  const addBtn = el("button", {class: "btn"});
  const label = () => { addBtn.textContent = inB() ? "Take it out of the mount basket" : "Add it to the mount basket"; };
  addBtn.addEventListener("click", async () => {
    await mtToggle(d, inB() ? {} : {display: pick.display, ground: pick.ground, flying: pick.flying});
    label();
    $$(`#mt-grid .card[data-mount="${d.id}"] .add`).forEach(b => { b.classList.toggle("in", !!inB()); b.textContent = inB() ? "✓" : "+"; });
  });
  label();
  const speeds = el("div", {class: "erow"},
    speedSel("Ground speed", d.speeds.ground, pick.ground, v => pick.ground = v),
    d.kind === "flying" ? speedSel("Flight speed", d.speeds.flying, pick.flying, v => pick.flying = v) : null);
  const item = d.item ? el("div", {class: "kv"}, ...kv("Item", `${d.item.name} (retail ${d.item.id})`),
    ...kv("Quality", ["Poor", "Common", "Uncommon", "Rare", "Epic", "Legendary"][d.item.quality] || d.item.quality))
    : el("div", {class: "muted small"}, "Retail has no item for it: Install makes one named after the mount.");
  showDrawer([
    el("h2", {class: "d-title"}, d.name),
    el("div", {class: "muted"}, [`Mount ${d.id}`, MT_KINDS[d.kind], d.skill ? `riding ${d.skill}` : ""].filter(Boolean).join(" · ")),
    d.description ? el("p", {class: "small"}, d.description) : null,
    section("Preview", pb.box),
    el("div", {class: "actions"}, addBtn),
    section("Speeds", speeds, el("div", {class: "muted small"}, d.kind === "flying" ?
      "A flyer: it runs on the ground and flies where your server lets it (3.3.5's flying mounts)." :
      "A ground mount.")),
    section("Spell", el("div", {class: "small"},
      el("a", {href: "#", onclick: ev => { ev.preventDefault(); show("spells"); spOpen(d.spell); }}, `Retail spell ${d.spell}`),
      el("span", {class: "muted"}, ` · made on ${d.kind === "flying" ? "Swift Blue Gryphon (32242)" : "Swift Brown Steed (23229)"}'s mechanics`))),
    section("Item", item),
    d.source ? section("Where retail has it", el("div", {class: "small", style: "white-space:pre-line"}, mtPlain(d.source))) : null,
    section("Sounds", el("div", {class: "muted small"}, "Its creature sounds (steps aside, its calls, jumps, idle sounds) " +
      "and its summon sound come from retail, through the creature and spell installs.")),
  ].filter(Boolean));
  if (pb.v) load();
}

// the rider: the race and sex picked under the preview, undressed, playing Mount
async function mtRider() {
  const race = PV.race, sex = PV.sex;
  const body = await bodyOf(race, sex);
  const outfit = {pieces: [], dress_order: [], item_geosets: {}, problems: []};
  const skin = await compositeSkin(body, outfit, "bfa");
  const worn = wornGeosets(body, outfit);
  const types = {1: skin};
  if (body.hair) types[6] = `/tex/bfa/${body.hair}.png`;
  if (body.skin_extra) types[8] = `/tex/bfa/${body.skin_extra}.png`;
  const anims = await api("/api/spell/body-anims", {race, sex, ids: String(MT_RIDER)}).catch(() => ({}));
  const a = anims[MT_RIDER];
  return {body, types, visible: id => shows(worn, id, true), who: `${body.name} ${sex ? "female" : "male"}`,
          anim: a ? T => ({tracks: a.bones, duration: a.duration, now: T % Math.max(1, a.duration)}) : undefined};
}

// ---------------------------------------------------------------------------- basket and install
async function mtLoadState() {
  try { MT.state = await api("/api/mounts/state"); }
  catch (e) { MT.state = {basket: [], installed: [], ids: {}, job: {}, creature_settings: {}}; }
  $("#mt-count").textContent = MT.state.basket.length || "";
  mtRenderBasket();
  mtRenderJob(MT.state.job || {});
}

function mtRenderBasket() {
  const st = MT.state;
  $("#mt-count").textContent = st.basket.length || "";
  $("#mt-basket").replaceChildren(el("h3", {}, `Mount basket · ${plural(st.basket.length, "mount")}`),
    st.basket.length ? el("div", {}, st.basket.map(e => el("div", {class: "cr-game"},
      el("a", {href: "#", onclick: ev => { ev.preventDefault(); mtOpen(e.id); }}, e.name),
      el("span", {class: "muted small"}, ` ${mtSpeed(e.ground)} ground` + (+e.flying ? ` · ${mtSpeed(e.flying)} flying` : "")),
      el("button", {class: "remove", title: "Take it out", onclick: async () => {
        st.basket = st.basket.filter(x => x !== e); st.basket = await post("/api/mounts/basket", st.basket); mtRenderBasket(); }}, "×"))))
      : el("p", {class: "muted small"}, "Add mounts with + : Install puts each in your client and on your server as a creature, a spell and an item."));
  $("#mt-game").replaceChildren(el("h3", {}, `In your game · ${plural(st.installed.length, "mount")}`),
    st.installed.length ? el("div", {}, st.installed.map(e => el("div", {class: "cr-game"},
      el("b", {}, e.name), " ",
      el("span", {class: "muted small"}, `spell ${e.spell_id || "?"} · item ${e.item_entry || "?"} `),
      e.item_entry ? el("button", {class: "copy", onclick: () => copy(`.additem ${e.item_entry}`)}, `.additem ${e.item_entry}`) : null,
      e.spell_id ? el("button", {class: "copy", onclick: () => copy(`.learn ${e.spell_id}`)}, `.learn ${e.spell_id}`) : null)))
      : el("p", {class: "muted small"}, "Nothing installed yet."));
  const s = st.creature_settings || {};
  $("#mt-where").replaceChildren(
    el("div", {class: "small"}, `Client: ${s.client || "(Settings)"} · world database: ${s.database || "not found"}`),
    el("div", {class: "small muted"}, "Install closes and starts the client and worldserver again when the Creatures page's " +
      "\"Restart\" box is ticked; it runs the creature and spell installs for the mounts, then writes their items."));
}

function mtRenderJob(j) {
  const running = j.state === "running";
  $("#mt-go").disabled = running;
  $("#mt-go").textContent = running ? "Installing…" : "Install mounts";
  $("#mt-steps").replaceChildren(...(j.steps || []).map(s => el("div", {class: "srow " + (s.state === "done" ? "ok" : s.state === "failed" ? "bad" : "")},
    s.state === "done" ? "✓ " : s.state === "failed" ? "✗ " : "… ", s.name)));
  const r = j.result;
  if (!r) { $("#mt-result").replaceChildren(); return; }
  if (!r.ok) { $("#mt-result").replaceChildren(el("div", {class: "warnline"}, `Install stopped: ${r.error}`)); return; }
  $("#mt-result").replaceChildren(el("div", {class: "okline"}, `Installed ${plural(r.mounts.length, "mount")}.`),
    el("div", {class: "cr-npc"}, r.mounts.map(m => el("div", {}, el("b", {}, m.name), " ",
      el("span", {class: "muted small"}, `display ${m.display} `),
      m.item_entry ? el("button", {class: "copy", onclick: () => copy(`.additem ${m.item_entry}`)}, `.additem ${m.item_entry}`) : null))));
}

async function mtPollJob() {
  clearTimeout(MT.timer);
  try {
    const j = await api("/api/mounts/job", {since: MT.since});
    if (j.log.length) {
      const log = $("#mt-log");
      log.textContent += j.log.join("\n") + "\n";
      log.scrollTop = log.scrollHeight;
    }
    MT.since = j.at;
    mtRenderJob(j);
    if (j.state === "running") MT.timer = setTimeout(mtPollJob, 800);
    else if (j.result) await mtLoadState();
  } catch (e) { MT.timer = setTimeout(mtPollJob, 2000); }
}

async function mtInstall() {
  try {
    $("#mt-log").textContent = "";
    MT.since = 0;
    mtRenderJob(await post("/api/mounts/install", {}));
    mtPollJob();
  } catch (e) { toast(e.message); }
}

function mtShow() {
  if (!MT.wired) {
    MT.wired = true;
    const run = debounce(() => mtSearch(true), 250);
    $("#mt-q").addEventListener("input", run);
    $("#mt-q").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); mtSearch(true); } });
    $("#mt-kind").addEventListener("change", () => mtSearch(true));
    $("#mt-more").addEventListener("click", () => { if (!MT.loading) { MT.page++; mtSearch(false); } });
    $("#mt-go").addEventListener("click", mtInstall);
  }
  mtLoadState().then(() => {
    if (!$("#mt-grid").children.length) mtSearch(true);
    if (MT.state.job && MT.state.job.state === "running") mtPollJob();
  });
}
