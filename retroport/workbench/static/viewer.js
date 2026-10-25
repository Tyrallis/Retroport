"use strict";
// The workbench's model viewer (WebGL2): models as /api/preview and /api/body send them, skinned on
// the GPU and playing their Stand animation - bones, texture animations (scrolling, turning UVs),
// colour and transparency tracks, and particle emitters - each batch drawn with the client's texture
// combiner for its shader (glows, environment maps, masks; see shaderOf). A scene is
// parts: a body, models attached to its points (helm, shoulders, buckle), collection pieces driven by
// its bones, or loose models. Left-drag turns, right-drag pans, the wheel zooms, double-click resets.

// uCoord: which coordinates each of a batch's three textures reads - 0 the first UVs, 1 the second,
// 2 an environment map (the reflection of the view off the surface); uEdge fades it at grazing angles
const VS = `#version 300 es
in vec3 aPos; in vec3 aNrm; in vec2 aUv; in vec2 aUv2; in vec4 aW; in uvec4 aB;
uniform mat4 uMvp; uniform mat4 uView; uniform mat4 uModel; uniform highp sampler2D uBones; uniform bool uSkinned;
uniform mat4 uUvMat; uniform mat4 uUv2Mat; uniform mat4 uUv3Mat; uniform ivec3 uCoord; uniform bool uEdge;
uniform float uPush;
out vec3 vN; out vec2 vUv; out vec2 vUv2; out vec2 vUv3; out float vEdge; out float vFace;
mat4 bone(uint i) {
  int x = int(i) * 4;
  return mat4(texelFetch(uBones, ivec2(x, 0), 0), texelFetch(uBones, ivec2(x + 1, 0), 0),
              texelFetch(uBones, ivec2(x + 2, 0), 0), texelFetch(uBones, ivec2(x + 3, 0), 0));
}
vec2 coord(int c, vec2 env) { return c == 1 ? aUv2 : (c == 2 ? env : aUv); }
void main() {
  mat4 skin = mat4(1.0);
  float s = aW.x + aW.y + aW.z + aW.w;
  if (uSkinned && s > 0.001)
    skin = (aW.x * bone(aB.x) + aW.y * bone(aB.y) + aW.z * bone(aB.z) + aW.w * bone(aB.w)) / s;
  mat4 m = uModel * skin;
  vec4 wp = m * vec4(aPos + aNrm * uPush, 1.0);
  vN = mat3(m) * aNrm;
  vec3 e = normalize((uView * wp).xyz), n = normalize(mat3(uView) * vN);
  vec3 r = e - n * (2.0 * dot(e, n));
  vec2 env = normalize(vec3(r.xy, r.z + 1.0)).xy * 0.5 + 0.5;
  float f = clamp(abs(dot(e, n)), 0.0, 1.0);
  vEdge = uEdge ? clamp(2.7 * f * f - 0.4, 0.0, 1.0) : 1.0;
  vFace = f;
  vUv = (uUvMat * vec4(coord(uCoord.x, env), 0.0, 1.0)).xy;
  vUv2 = (uUv2Mat * vec4(coord(uCoord.y, env), 0.0, 1.0)).xy;
  vUv3 = (uUv3Mat * vec4(coord(uCoord.z, env), 0.0, 1.0)).xy;
  gl_Position = uMvp * wp;
}`;
// uPs: the batch's pixel combiner (PS below) - how its textures make a lit colour (d), an unlit glow
// added on top (sp) and an opacity (a). uWgt: the weights of its three textures.
const FS = `#version 300 es
precision mediump float;
in vec3 vN; in vec2 vUv; in vec2 vUv2; in vec2 vUv3; in float vEdge; in float vFace;
uniform int uFx; uniform vec3 uC0; uniform vec3 uC1; uniform vec3 uC2; uniform vec3 uFxEdge; uniform vec2 uFxA;
uniform sampler2D uTex; uniform bool uHasTex; uniform sampler2D uTex2; uniform sampler2D uTex3;
uniform int uPs; uniform vec3 uWgt; uniform bool uKeyTex; uniform bool uMask;
uniform float uAlphaRef; uniform bool uUnlit; uniform bool uOpaque; uniform bool uPremul;
uniform vec3 uLight; uniform vec4 uTint;
out vec4 outColor;
void main() {
  vec4 t0 = uHasTex ? texture(uTex, vUv) : vec4(0.55, 0.55, 0.58, 1.0);
  // a creature's state effects (retail's GradientEffect and OutlineEffect): 2 its outline - the
  // pushed-out back faces in the edge colour, a rim round its silhouette; 1 its gradient - a glow from
  // the first colour where it faces you through the second to the third at its edges, added on top
  if (uFx > 0) {
    if (uHasTex && uAlphaRef > 0.1 && t0.a < 0.5) discard;
    if (uFx == 2) { outColor = vec4(uFxEdge, 1.0); return; }
    float t = clamp(1.0 - vFace, 0.0, 1.0);
    vec3 c = t < 0.5 ? mix(uC0, uC1, t * 2.0) : mix(uC1, uC2, t * 2.0 - 1.0);
    float ga = mix(uFxA.x, uFxA.y, t) * t;
    outColor = vec4(c * ga, ga);
    return;
  }
  vec4 t1 = texture(uTex2, vUv2), t2 = texture(uTex3, vUv3);
  vec3 d = t0.rgb, sp = vec3(0.0);
  float a = 1.0;
  switch (uPs) {
    case 1: case 31: case 33: a = t0.a; break;
    case 2: d = t0.rgb * t1.rgb; a = t1.a; break;
    case 3: d = t0.rgb * t1.rgb * 2.0; a = t1.a * 2.0; break;
    case 4: d = t0.rgb * t1.rgb * 2.0; break;
    case 5: d = t0.rgb * t1.rgb; break;
    case 6: d = t0.rgb * t1.rgb; a = t0.a * t1.a; break;
    case 7: d = t0.rgb * t1.rgb * 2.0; a = t0.a * t1.a * 2.0; break;
    case 8: a = t0.a + t1.a; sp = t1.rgb; break;
    case 9: d = t0.rgb * t1.rgb * 2.0; a = t0.a; break;
    case 10: a = t0.a; sp = t1.rgb; break;
    case 11: d = t0.rgb * t1.rgb; a = t0.a; break;
    case 12: d = mix(t0.rgb * t1.rgb * 2.0, t0.rgb, t0.a); break;
    case 13: sp = t1.rgb * t1.a; break;
    case 14: sp = t1.rgb * t1.a * (1.0 - t0.a); break;
    case 15: d = mix(t0.rgb * t1.rgb * 2.0, t0.rgb, t0.a); sp = t2.rgb * t2.a * uWgt.z; break;
    case 16: a = t0.a; sp = t1.rgb * t1.a; break;
    case 17: a = t0.a + t1.a * dot(t1.rgb, vec3(0.3, 0.59, 0.11)); sp = t1.rgb * t1.a * (1.0 - t0.a); break;
    case 18: d = mix(mix(t0.rgb, t1.rgb, t1.a), t0.rgb, t0.a); break;
    case 19: d = mix(t0.rgb * t1.rgb * 2.0, t2.rgb, t2.a); break;
    case 20: sp = t1.rgb * t1.a * uWgt.y; break;
    case 21: a = t0.a + t1.a; sp = t1.rgb * (1.0 - t0.a); break;
    case 22: d = mix(t0.rgb * t1.rgb, t0.rgb, t0.a); break;
    case 23: a = t0.a; sp = t1.rgb * t1.a * uWgt.y; break;
    case 24: d = mix(t0.rgb, t1.rgb, t1.a); sp = t0.rgb * t0.a * uWgt.x; break;
    case 25: { float g = clamp(t2.a * uWgt.z, 0.0, 1.0);
               d = mix(t0.rgb * t1.rgb * 2.0, t0.rgb, t0.a) * (1.0 - g); sp = t2.rgb * g; break; }
    case 26: case 28: { vec4 x = mix(mix(t0, t1, clamp(uWgt.y, 0.0, 1.0)), t2, clamp(uWgt.z, 0.0, 1.0));
               d = x.rgb; a = x.a; break; }
    case 27: d = mix(mix(t0.rgb * t1.rgb * 2.0, t2.rgb, t2.a), t0.rgb, t0.a); break;
    case 29: d = mix(t0.rgb, t1.rgb, t1.a); break;
    case 30: a = t0.a; break;
    case 35: { vec4 x = t0 * t1 * t2; d = x.rgb; a = x.a; break; }
    default: break;
  }
  // a packed shader over three textures: the third is the batch's mask (the ring of a ground circle,
  // the outline of a glow plane) - it multiplies whatever the first two made, colour and alpha
  if (uMask) { d *= t2.rgb; sp *= t2.rgb; a *= t2.a; }
  if (uKeyTex) a = t0.a;                     // an alpha-keyed batch with an opaque combiner: cut by its texture
  a = clamp(a * vEdge, 0.0, 1.0) * uTint.a;
  if (a < uAlphaRef) discard;
  float l = uUnlit ? 1.0 : 0.42 + 0.75 * abs(dot(normalize(vN), uLight));
  vec4 o = vec4(d * l * uTint.rgb + sp, uOpaque ? 1.0 : a);
  if (uPremul) o.rgb *= o.a;
  outColor = o;
}`;
const PVS = `#version 300 es
in vec3 aPos; in vec2 aUv; in vec4 aCol;
uniform mat4 uMvp;
out vec2 vUv; out vec4 vCol;
void main() { vUv = aUv; vCol = aCol; gl_Position = uMvp * vec4(aPos, 1.0); }`;
const PFS = `#version 300 es
precision mediump float;
in vec2 vUv; in vec4 vCol;
uniform sampler2D uTex; uniform float uAlphaRef;
out vec4 outColor;
void main() { vec4 c = texture(uTex, vUv) * vCol; if (c.a < uAlphaRef) discard; outColor = c; }`;
const MAX_PARTICLES = 600;

// -- small matrix helpers (column-major, like GL) --------------------------------------------
const M4 = {
  ident: () => new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]),
  mul(a, b, o = new Float32Array(16)) {
    for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
      o[i * 4 + j] = a[j] * b[i * 4] + a[4 + j] * b[i * 4 + 1] + a[8 + j] * b[i * 4 + 2] + a[12 + j] * b[i * 4 + 3];
    }
    return o;
  },
  persp(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0]);
  },
  look(eye, at, up) {
    const z = norm(sub(eye, at)), x = norm(cross(up, z)), y = cross(z, x);
    return new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0,
                             -dot(x, eye), -dot(y, eye), -dot(z, eye), 1]);
  },
  // T(pivot + t) * R(q) * S(s) * T(-pivot)
  bone(p, t, q, s, o) {
    const [x, y, z, w] = q;
    const r = [1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w),
               2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w),
               2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)];
    for (let c = 0; c < 3; c++) for (let k = 0; k < 3; k++) o[c * 4 + k] = r[c * 3 + k] * s[c];
    o[3] = o[7] = o[11] = 0; o[15] = 1;
    for (let k = 0; k < 3; k++) {
      o[12 + k] = p[k] + t[k] - (o[k] * p[0] + o[4 + k] * p[1] + o[8 + k] * p[2]);
    }
    return o;
  },
  translate(m, v) {
    const o = new Float32Array(m);
    for (let k = 0; k < 3; k++) o[12 + k] = m[k] * v[0] + m[4 + k] * v[1] + m[8 + k] * v[2] + m[12 + k];
    return o;
  },
  apply(m, v) {
    return [0, 1, 2].map(k => m[k] * v[0] + m[4 + k] * v[1] + m[8 + k] * v[2] + m[12 + k]);
  },
  rotate(m, v) {
    return [0, 1, 2].map(k => m[k] * v[0] + m[4 + k] * v[1] + m[8 + k] * v[2]);
  },
};
const IDENT = M4.ident();

// -- retail physics (hair, cloth, wings, chains, plumes) -----------------------------------------
// The engine Equip Plus runs in the client (Kirazul's port of retail's), built to physics.wasm.
// A mesh whose model carries a .phys gets a simulation: each frame its bones go in (in the world),
// its dynamic bodies come out (in model space), and every bone under a moved one follows it.
const PHYS = {module: null, loading: null};
function physicsModule() {
  if (PHYS.module) return Promise.resolve(PHYS.module);
  if (!PHYS.loading) {
    const stub = () => 0;
    PHYS.loading = fetch("/static/physics.wasm").then(r => r.arrayBuffer())
      .then(buf => WebAssembly.instantiate(buf, {wasi_snapshot_preview1: {fd_close: stub, fd_seek: stub, fd_write: stub}}))
      .then(({instance}) => { instance.exports._initialize(); PHYS.module = instance.exports; return PHYS.module; })
      .catch(e => { console.warn("physics.wasm:", e); PHYS.loading = null; return null; });
  }
  return PHYS.loading;
}
function transpose(m, o = new Float64Array(16)) {
  for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) o[r * 4 + c] = m[c * 4 + r];
  return o;
}
// inverse of an affine column-major matrix
function invAffine(m) {
  const a = m[0], b = m[1], c = m[2], d = m[4], e = m[5], f = m[6], g = m[8], h = m[9], i = m[10];
  const det = a * (e * i - f * h) - d * (b * i - c * h) + g * (b * f - c * e);
  if (Math.abs(det) < 1e-12) return null;
  const k = 1 / det, o = new Float32Array(16);
  o[0] = (e * i - f * h) * k; o[1] = (c * h - b * i) * k; o[2] = (b * f - c * e) * k;
  o[4] = (f * g - d * i) * k; o[5] = (a * i - c * g) * k; o[6] = (c * d - a * f) * k;
  o[8] = (d * h - e * g) * k; o[9] = (b * g - a * h) * k; o[10] = (a * e - b * d) * k;
  for (let r = 0; r < 3; r++) o[12 + r] = -(o[r] * m[12] + o[4 + r] * m[13] + o[8 + r] * m[14]);
  o[15] = 1;
  return o;
}
function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
function norm(v) { const l = Math.hypot(v[0], v[1], v[2]) || 1; return [v[0] / l, v[1] / l, v[2] / l]; }
function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
function b64(s, Type) {
  const bin = atob(s), u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return new Type(u8.buffer);
}
const rnd = () => Math.random() * 2 - 1;

// One keyframe track at a time (ms): step or linear, quaternions normalised.
function sample(track, now, duration, globals, size) {
  if (!track || !track.t.length) return null;
  const loop = track.g >= 0 ? (globals[track.g] || 0) : duration;
  const t = loop > 0 ? now % loop : 0, times = track.t, v = track.v;
  if (times.length === 1 || t <= times[0]) return v.slice(0, size);
  const last = times.length - 1;
  if (t >= times[last]) return v.slice(last * size, last * size + size);
  let lo = 0, hi = last;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (times[mid] <= t) lo = mid; else hi = mid; }
  const a = lo * size, b = hi * size;
  if (track.i === 0) return v.slice(a, a + size);
  const f = (t - times[lo]) / ((times[hi] - times[lo]) || 1), out = new Array(size);
  let sign = 1;
  if (size === 4) { let d = 0; for (let k = 0; k < 4; k++) d += v[a + k] * v[b + k]; if (d < 0) sign = -1; }
  for (let k = 0; k < size; k++) out[k] = v[a + k] + (sign * v[b + k] - v[a + k]) * f;
  if (size === 4) { const l = Math.hypot(...out) || 1; for (let k = 0; k < 4; k++) out[k] /= l; }
  return out;
}
// a particle's over-its-life track at t in 0..1
function lifeValue(track, t, size) {
  if (!track || !track.t.length) return null;
  const times = track.t, v = track.v, last = times.length - 1;
  if (t <= times[0] || last === 0) return v.slice(0, size);
  if (t >= times[last]) return v.slice(last * size, last * size + size);
  let k = 0;
  while (k < last - 1 && times[k + 1] <= t) k++;
  const f = (t - times[k]) / ((times[k + 1] - times[k]) || 1), out = new Array(size);
  for (let i = 0; i < size; i++) out[i] = v[k * size + i] + (v[(k + 1) * size + i] - v[k * size + i]) * f;
  return out;
}
const value = (track, now, m, fallback) => (sample(track, now, m.duration, m.globals, 1) || [fallback])[0];

// The client's model shaders. A batch's shader id picks a pixel combiner (how its up to three textures
// mix - FS's uPs) and a vertex shader (which coordinates each texture reads). Ids with 0x8000 index
// the client's table; the others say it in bits (0x70: the first texture modulates, low 3 bits: how
// the second combines, 0x80/0x8: the first/second is an environment map, 0x4000: the second UVs).
const PS = {Opaque: 0, Mod: 1, Opaque_Mod: 2, Opaque_Mod2x: 3, Opaque_Mod2xNA: 4, Opaque_Opaque: 5, Mod_Mod: 6,
            Mod_Mod2x: 7, Mod_Add: 8, Mod_Mod2xNA: 9, Mod_AddNA: 10, Mod_Opaque: 11, Opaque_Mod2xNA_Alpha: 12,
            Opaque_AddAlpha: 13, Opaque_AddAlpha_Alpha: 14, Opaque_Mod2xNA_Alpha_Add: 15, Mod_AddAlpha: 16,
            Mod_AddAlpha_Alpha: 17, Opaque_Alpha_Alpha: 18, Opaque_Mod2xNA_Alpha_3s: 19, Opaque_AddAlpha_Wgt: 20,
            Mod_Add_Alpha: 21, Opaque_ModNA_Alpha: 22, Mod_AddAlpha_Wgt: 23, Opaque_Mod_Add_Wgt: 24,
            Opaque_Mod2xNA_Alpha_UnshAlpha: 25, Mod_Dual_Crossfade: 26, Opaque_Mod2xNA_Alpha_Alpha: 27,
            Mod_Masked_Dual_Crossfade: 28, Opaque_Alpha: 29, Guild: 30, Guild_NoBorder: 31, Guild_Opaque: 32,
            Mod_Depth: 33, Illum: 34, Mod_Mod_Mod_Const: 35};
// vertex shaders: [coordinates of textures 1-3 (0 first UVs, 1 second, 2 environment), edge fade]
const U1 = 0, U2 = 1, ENV = 2;
const VSH = {T1: [[U1]], Env: [[ENV]], T2: [[U2]], T1_T2: [[U1, U2]], T1_Env: [[U1, ENV]], Env_T1: [[ENV, U1]],
             Env_Env: [[ENV, ENV]], T1_T1: [[U1, U1]], T1_Env_T1: [[U1, ENV, U1]], T1_Env_T2: [[U1, ENV, U2]],
             T1_T2_T1: [[U1, U2, U1]], T1_T2_T3: [[U1, U2, U1]], Color_T1_T2_T3: [[U2, U1, U1]],
             EdgeFade_T1: [[U1], true], EdgeFade_T1_T2: [[U1, U2], true], EdgeFade_Env: [[ENV], true]};
const SHADER_TABLE = [
  ["Opaque_Mod2xNA_Alpha", "T1_Env"], ["Opaque_AddAlpha", "T1_Env"], ["Opaque_AddAlpha_Alpha", "T1_Env"],
  ["Opaque_Mod2xNA_Alpha_Add", "T1_Env_T1"], ["Mod_AddAlpha", "T1_Env"], ["Opaque_AddAlpha", "T1_T1"],
  ["Mod_AddAlpha", "T1_T1"], ["Mod_AddAlpha_Alpha", "T1_Env"], ["Opaque_Alpha_Alpha", "T1_Env"],
  ["Opaque_Mod2xNA_Alpha_3s", "T1_Env_T1"], ["Opaque_AddAlpha_Wgt", "T1_T1"], ["Mod_Add_Alpha", "T1_Env"],
  ["Opaque_ModNA_Alpha", "T1_Env"], ["Mod_AddAlpha_Wgt", "T1_Env"], ["Mod_AddAlpha_Wgt", "T1_T1"],
  ["Opaque_AddAlpha_Wgt", "T1_T2"], ["Opaque_Mod_Add_Wgt", "T1_Env"], ["Opaque_Mod2xNA_Alpha_UnshAlpha", "T1_Env_T1"],
  ["Mod_Dual_Crossfade", "T1"], ["Mod_Depth", "EdgeFade_T1"], ["Opaque_Mod2xNA_Alpha_Alpha", "T1_Env_T2"],
  ["Mod_Mod", "EdgeFade_T1_T2"], ["Mod_Masked_Dual_Crossfade", "T1_T2"], ["Opaque_Alpha", "T1_T1"],
  ["Opaque_Mod2xNA_Alpha_UnshAlpha", "T1_Env_T2"], ["Mod_Depth", "EdgeFade_Env"], ["Guild", "T1_T2_T1"],
  ["Guild_NoBorder", "T1_T2"], ["Guild_Opaque", "T1_T2_T1"], ["Illum", "T1_T1"], ["Mod_Mod_Mod_Const", "T1_T2_T3"],
  ["Mod_Mod_Mod_Const", "Color_T1_T2_T3"], ["Opaque", "T1"], ["Mod_Mod2x", "EdgeFade_T1_T2"],
];
// how many textures a combiner reads
const PS_TEXTURES = ps => [0, 1, 33, 34].includes(ps) ? 1 : ([15, 19, 25, 26, 27, 28, 30, 32, 35].includes(ps) ? 3 : 2);
// with a texture short, a combiner falls back to its first texture alone (opaque, or cut by its alpha)
const PS_MOD = new Set([1, 6, 7, 8, 9, 10, 11, 16, 17, 21, 23, 26, 28, 30, 31, 33, 35]);
function shaderOf(b) {
  const s = b.shader || 0, n = 1 + (b.layers || []).length;
  if (s & 0x8000) {
    const row = SHADER_TABLE[s & 0x7FFF];
    if (row) { const v = VSH[row[1]]; return {ps: PS[row[0]], coords: v[0], edge: !!v[1]}; }
    return {ps: PS.Mod, coords: [U1], edge: false};
  }
  if (n < 2) return {ps: s & 0x70 ? PS.Mod : PS.Opaque, coords: [s & 0x80 ? ENV : (s & 0x4000 ? U2 : U1)], edge: false};
  const mod = [PS.Mod_Mod2x, PS.Mod_Mod, PS.Mod_Mod2xNA, PS.Mod_AddNA, PS.Mod_Opaque, PS.Mod_Mod, PS.Mod_Mod, PS.Mod_Add];
  const opaque = [PS.Opaque_Mod2x, PS.Opaque_Mod, PS.Opaque_Mod2xNA, PS.Opaque_AddAlpha_Alpha, PS.Opaque_Opaque,
                  PS.Opaque_Mod, PS.Opaque_Mod, PS.Opaque_AddAlpha_Alpha];
  const ps = (s & 0x70 ? mod : opaque)[((s & 0xFF) ^ 4) & 7];
  const coords = s & 0x80 ? [ENV, s & 0x8 ? ENV : U1] : [U1, s & 0x8 ? ENV : (s & 0x4000 ? U2 : U1)];
  if (n >= 3) return {ps, coords: [...coords, U2], edge: false, mask: true};
  return {ps, coords, edge: false};
}

class Viewer {
  constructor(canvas) {
    this.canvas = canvas;
    const gl = this.gl = canvas.getContext("webgl2", {antialias: true, premultipliedAlpha: false});
    if (!gl) throw new Error("WebGL2 is not available in this browser");
    const program = (vs, fs) => {
      const sh = (type, src) => {
        const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
        if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
        return s;
      };
      const p = gl.createProgram();
      gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p);
      if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
      return p;
    };
    this.prog = program(VS, FS);
    this.u = {};
    for (const n of ["uMvp", "uView", "uModel", "uBones", "uSkinned", "uTex", "uHasTex", "uTex2", "uTex3", "uPs", "uWgt", "uMask",
                     "uKeyTex", "uUvMat", "uUv2Mat", "uUv3Mat", "uCoord", "uEdge", "uAlphaRef", "uUnlit", "uOpaque",
                     "uPremul", "uLight", "uTint", "uPush", "uFx", "uC0", "uC1", "uC2", "uFxEdge", "uFxA"])
      this.u[n] = gl.getUniformLocation(this.prog, n);
    this.a = {};
    for (const n of ["aPos", "aNrm", "aUv", "aUv2", "aW", "aB"]) this.a[n] = gl.getAttribLocation(this.prog, n);
    this.pprog = program(PVS, PFS);
    this.pu = {mvp: gl.getUniformLocation(this.pprog, "uMvp"), tex: gl.getUniformLocation(this.pprog, "uTex"),
               ref: gl.getUniformLocation(this.pprog, "uAlphaRef")};
    this.pa = {pos: gl.getAttribLocation(this.pprog, "aPos"), uv: gl.getAttribLocation(this.pprog, "aUv"),
               col: gl.getAttribLocation(this.pprog, "aCol")};
    this.pvao = gl.createVertexArray(); this.pbuf = gl.createBuffer();
    gl.bindVertexArray(this.pvao); gl.bindBuffer(gl.ARRAY_BUFFER, this.pbuf);
    gl.enableVertexAttribArray(this.pa.pos); gl.vertexAttribPointer(this.pa.pos, 3, gl.FLOAT, false, 36, 0);
    gl.enableVertexAttribArray(this.pa.uv); gl.vertexAttribPointer(this.pa.uv, 2, gl.FLOAT, false, 36, 12);
    gl.enableVertexAttribArray(this.pa.col); gl.vertexAttribPointer(this.pa.col, 4, gl.FLOAT, false, 36, 20);
    gl.bindVertexArray(null);
    this.parts = []; this.textures = new Map(); this.start0 = performance.now(); this.last = 0;
    this.cull = gl.CCW;                              // M2 front faces wind counter-clockwise on screen
    this.view = {yaw: 0.35, pitch: 0.12, dist: 3, center: [0, 0, 0]};
    this.home = {...this.view};
    let drag = null;
    canvas.addEventListener("contextmenu", e => e.preventDefault());
    canvas.addEventListener("pointerdown", e => { drag = {x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey}; canvas.setPointerCapture(e.pointerId); });
    canvas.addEventListener("pointermove", e => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag.x = e.clientX; drag.y = e.clientY;
      const v = this.view;
      if (drag.pan) {
        const s = v.dist * 0.0018, cy = Math.cos(v.yaw), sy = Math.sin(v.yaw), sp = Math.sin(v.pitch), cp = Math.cos(v.pitch);
        const right = [-sy, cy, 0], up = [-sp * cy, -sp * sy, cp];
        for (let k = 0; k < 3; k++) v.center[k] += (-dx * right[k] + dy * up[k]) * s;
      } else {
        v.yaw -= dx * 0.01;
        v.pitch = Math.max(-1.45, Math.min(1.45, v.pitch + dy * 0.01));
      }
      this.draw();
    });
    canvas.addEventListener("pointerup", () => { drag = null; });
    canvas.addEventListener("wheel", e => { e.preventDefault(); this.view.dist *= Math.exp(e.deltaY * 0.001); this.draw(); }, {passive: false});
    canvas.addEventListener("dblclick", () => { this.view = {...this.home, center: [...this.home.center]}; this.draw(); });
  }

  // -- scene ------------------------------------------------------------------------------
  clear() {
    const gl = this.gl;
    for (const p of this.parts) {
      gl.deleteVertexArray(p.vao); p.buffers.forEach(b => gl.deleteBuffer(b)); gl.deleteTexture(p.boneTex);
      this.dropPhysics(p);
    }
    this.parts = [];
    this.clock = null;
  }

  // -- a timeline (the spell preview): parts with opts.window [from, to) ms show only then, and play
  // their own animation from their start. It loops over length ms; onTick(t) follows it.
  timeline(length, onTick = null) {
    const speed = this.clock ? this.clock.speed : 1;
    this.clock = {start: performance.now(), length: Math.max(1, length), paused: false, at: 0, last: 0, onTick, speed};
    this.draw();
  }
  time() {
    const c = this.clock;
    if (!c) return 0;
    return c.paused ? c.at : ((performance.now() - c.start) * c.speed) % c.length;
  }
  seek(t) {
    const c = this.clock;
    if (!c) return;
    c.at = Math.max(0, Math.min(c.length - 1, t));
    c.start = performance.now() - c.at / c.speed;
    for (const p of this.parts) for (const em of p.emitters) em.list = [];
    this.draw();
  }
  pause(on) {
    const c = this.clock;
    if (!c) return;
    if (on && !c.paused) { c.at = this.time(); c.paused = true; }
    else if (!on && c.paused) { c.paused = false; c.start = performance.now() - c.at / c.speed; }
    this.draw();
  }
  // slow motion: 1 is the game's pace
  rate(speed) {
    const c = this.clock;
    if (!c) return;
    const t = this.time();
    c.speed = speed;
    c.start = performance.now() - t / speed;
  }
  active(p, t) {
    const w = p.opts.window;
    return !w || !this.clock || (t >= w[0] && t < w[1]);
  }
  localTime(p, now, t) {
    const w = p.opts.window;
    return w && this.clock ? Math.max(0, t - w[0]) : now;
  }

  texture(src) {
    // src: a url, or a canvas (the body's composited skin)
    if (this.textures.has(src)) return this.textures.get(src);
    const gl = this.gl, t = {tex: gl.createTexture(), ready: false};
    this.textures.set(src, t);
    const upload = img => {
      gl.bindTexture(gl.TEXTURE_2D, t.tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
      gl.generateMipmap(gl.TEXTURE_2D);
      t.ready = true; this.draw();
    };
    if (typeof src === "string") {
      const img = new Image();
      img.onload = () => upload(img);
      img.onerror = () => { t.failed = true; };
      img.src = src;
    } else {
      upload(src);
    }
    return t;
  }

  // mesh: as the server sends it. opts: {texUrl(fdid), types: {textureType: url|canvas}, offset, visible(geoset),
  //   bodyOf: part (a collection: driven by that part's bones), attach: {part, id}, tint: [r,g,b,a]}
  add(mesh, opts = {}) {
    const gl = this.gl, vao = gl.createVertexArray(), buffers = [];
    gl.bindVertexArray(vao);
    const attr = (loc, data, size, type = gl.FLOAT, normalized = false, integer = false, stride = 0, offset = 0, buf = null) => {
      if (loc < 0) return buf;
      let b = buf;
      if (!b) { b = gl.createBuffer(); buffers.push(b); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW); }
      else gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.enableVertexAttribArray(loc);
      if (integer) gl.vertexAttribIPointer(loc, size, type, stride, offset);
      else gl.vertexAttribPointer(loc, size, type, normalized, stride, offset);
      return b;
    };
    const positions = b64(mesh.positions, Float32Array);
    attr(this.a.aPos, positions, 3);
    attr(this.a.aNrm, b64(mesh.normals, Float32Array), 3);
    attr(this.a.aUv, b64(mesh.uvs, Float32Array), 2);
    attr(this.a.aUv2, b64(mesh.uvs2 || mesh.uvs, Float32Array), 2);
    const skin = b64(mesh.skin, Uint8Array);
    const sb = attr(this.a.aW, skin, 4, gl.UNSIGNED_BYTE, true, false, 8, 0);
    attr(this.a.aB, skin, 4, gl.UNSIGNED_BYTE, false, true, 8, 4, sb);
    const ib = gl.createBuffer(); buffers.push(ib);
    const indices = b64(mesh.indices, Uint32Array);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.STATIC_DRAW);
    gl.bindVertexArray(null);
    const bones = mesh.bones || [];
    const part = {vao, buffers, mesh, bones, opts, offset: opts.offset || [0, 0, 0], world: [], mats: null, positions, indices, orient: null,
                  boneTex: gl.createTexture(), nb: Math.max(1, bones.length), visible: opts.visible || (() => true),
                  tint: opts.tint || [1, 1, 1, 1], uvMats: [], colors: [], weights: []};
    if (opts.glow) {
      let lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
      for (let i = 0; i < positions.length; i += 3)
        for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], positions[i + k]); hi[k] = Math.max(hi[k], positions[i + k]); }
      part.radius = Math.max(0.05, Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2);
    }
    part.mats = new Float32Array(part.nb * 16);
    for (let i = 0; i < part.nb; i++) part.mats.set(IDENT, i * 16);
    gl.bindTexture(gl.TEXTURE_2D, part.boneTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, part.nb * 4, 1, 0, gl.RGBA, gl.FLOAT, part.mats);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    // a collection follows its body's bones, matched by bone name hash, else key bone
    if (opts.bodyOf) {
      const body = opts.bodyOf.bones, byCrc = new Map(), byKey = new Map();
      body.forEach((b, i) => { if (b.c) byCrc.set(b.c, i); if (b.k >= 0) byKey.set(b.k, i); });
      part.map = bones.map(b => (b.c && byCrc.has(b.c)) ? byCrc.get(b.c) : (b.k >= 0 && byKey.has(b.k) ? byKey.get(b.k) : -1));
    }
    const url = fdid => fdid && opts.texUrl ? opts.texUrl(fdid) : null;
    part.batches = mesh.batches.map(b => {
      const src = b.texture ? url(b.texture) : (opts.types || {})[b.texture_type];
      const sh = shaderOf(b), need = sh.mask ? 3 : PS_TEXTURES(sh.ps), layers = b.layers || [];
      const extra = layers.slice(0, need - 1).map(l => { const u = url(l.texture); return u ? this.texture(u) : null; });
      return {...b, tex: src ? this.texture(src) : null, missing: !src && b.texture_type !== 0, sh, extra, need};
    });
    // drawn as the client draws a model's batches: by priority plane, lowest first (a hood's glowing eyes,
    // priority 4, over its dark inside, priority 0, whatever order the file lists them in)
    part.batches.sort((a, b) => (a.priority || 0) - (b.priority || 0));
    part.emitters = (mesh.particles || []).map(d => ({def: d, list: [], acc: 0, tex: this.texture(url(d.texture))}));
    if (mesh.physics && mesh.fdid && bones.length > 1 && opts.physics !== false) this.attachPhysics(part);
    this.parts.push(part);
    return part;
  }

  // fetches the model's physics row and makes its simulation; the part moves by it from then on
  async attachPhysics(part) {
    try {
      const [E, row] = await Promise.all([physicsModule(),
        fetch(`/api/physics?fdid=${part.mesh.fdid}`).then(r => r.json())]);
      if (!E || !row || !row.table64 || !this.parts.includes(part)) return;
      const bytes = Uint8Array.from(atob(row.table64), ch => ch.charCodeAt(0));
      const tp = E.ph_alloc(bytes.length);
      new Uint8Array(E.memory.buffer).set(bytes, tp);
      const h = E.ph_create(tp, bytes.length);
      E.ph_free(tp);
      if (!h) return;
      const n = part.bones.length, nb = E.ph_bodies(h), bodyBone = [];
      for (let i = 0; i < nb; i++) bodyBone.push(E.ph_body_bone(h, i));
      if (bodyBone.some(b => b !== 0xFFFF && b >= n)) { E.ph_destroy(h); return; }   // the row is not this file's
      const pv = E.ph_alloc(n * 12);
      new Float32Array(E.memory.buffer, pv, n * 3).set(part.bones.flatMap(b => b.v || [0, 0, 0]));
      part.phys = {E, h, bodyBone, pv, bw: E.ph_alloc(n * 128), pl: E.ph_alloc(128), out: E.ph_alloc(128), last: 0};
      this.physicsOn = this.physicsOn ?? true;
      this.draw();
    } catch (e) { console.warn("physics:", e); }
  }

  dropPhysics(p) {
    const ph = p.phys;
    if (!ph) return;
    [ph.pv, ph.bw, ph.pl, ph.out].forEach(x => ph.E.ph_free(x));
    ph.E.ph_destroy(ph.h);
    p.phys = null;
  }

  // one physics frame for a posed part: its bones (p.mats, model space) in, its dynamic bones out
  stepPhysics(p, nowMs) {
    const ph = p.phys, E = ph.E, n = p.bones.length;
    const model = this.modelMatrix(p);
    if (!model) return;
    const dt = ph.last ? Math.min(0.1, Math.max(0, (nowMs - ph.last) / 1000)) : 0;
    ph.last = nowMs;
    const D = new Float64Array(E.memory.buffer), tmp = new Float32Array(16), col = new Float64Array(16);
    const before = p.mats.slice(0, n * 16);
    for (let i = 0; i < n; i++) {
      M4.mul(model, before.subarray(i * 16, i * 16 + 16), tmp);
      D.set(transpose(tmp, col), ph.bw / 8 + i * 16);
    }
    D.set(transpose(model, col), ph.pl / 8);
    E.ph_step(ph.h, ph.bw, ph.pv, n, ph.pl, dt);
    const moved = new Uint8Array(n);
    ph.bodyBone.forEach((bone, i) => {
      if (bone === 0xFFFF || bone >= n || !E.ph_output(ph.h, i, ph.out)) return;
      const o = new Float64Array(E.memory.buffer, ph.out, 16);
      if (!o.every(Number.isFinite)) return;
      const m = new Float32Array(16);
      for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) m[c * 4 + r] = o[r * 4 + c];
      p.mats.set(m, bone * 16);
      moved[bone] = 1;
    });
    // every bone under a moved one is carried by that bone's change: B'c = B'a x Ba^-1 x Bc
    for (let c = 0; c < n; c++) {
      if (moved[c]) continue;
      let a = p.bones[c].p, guard = 0;
      while (a >= 0 && a < n && !moved[a] && guard++ < 256) a = p.bones[a].p;
      if (a < 0 || a >= n || !moved[a]) continue;
      const inv = invAffine(before.subarray(a * 16, a * 16 + 16));
      if (!inv) continue;
      const d = M4.mul(p.mats.subarray(a * 16, a * 16 + 16), inv);
      p.mats.set(M4.mul(d, before.subarray(c * 16, c * 16 + 16)), c * 16);
    }
  }

  animated() {
    if (this.clock && !this.clock.paused) return true;
    return this.parts.some(p => p.phys || p.bones.some(b => b.t || b.r || b.s) || p.opts.bodyOf || p.opts.attach || p.emitters.length ||
                                (p.mesh.uvanims || []).some(u => u.t || u.r || u.s) ||
                                (p.mesh.colors || []).length || (p.mesh.weights || []).some(w => w && w.t.length > 1));
  }

  // -- framing ------------------------------------------------------------------------------
  bounds() {
    let lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
    for (const p of this.parts) {
      if (p.opts.ghost) continue;
      const m = p.opts.attach ? this.attachMatrix(p.opts.attach) : p.orient;
      const b = this.drawnBounds(p), corners = [];
      if (!b) continue;
      for (const x of [0, 1]) for (const y of [0, 1]) for (const z of [0, 1]) corners.push([b[x][0], b[y][1], b[z][2]]);
      for (let c of corners) {
        if (m) c = M4.apply(m, c);
        for (let a = 0; a < 3; a++) { lo[a] = Math.min(lo[a], c[a] + p.offset[a]); hi[a] = Math.max(hi[a], c[a] + p.offset[a]); }
      }
    }
    if (lo[0] > hi[0]) { lo = [-1, -1, -1]; hi = [1, 1, 1]; }
    return [lo, hi];
  }

  // view: "front" (the model's +X faces you), "back" (its back: a cloak), "held" (a weapon or shield
  // stood up: see orientHeld)
  fit(view = "front", slot = 0) {
    this.update(0);
    let yaw = 0.35, pitch = 0.12;
    for (const p of this.parts) p.orient = null;
    if (view === "back") yaw = Math.PI - 0.35;
    if (view === "held") { this.orientHeld(slot); yaw = 0.2; pitch = 0.05; }
    const [lo, hi] = this.bounds(), ext = [0, 1, 2].map(a => hi[a] - lo[a]);
    const center = lo.map((v, a) => (v + hi[a]) / 2), r = Math.max(0.05, Math.hypot(...ext) / 2);
    this.view = {yaw, pitch, dist: r * 2.5, center};
    this.home = {...this.view, center: [...center]};
  }

  // the bind-pose bounds of what a part draws (a shared collection shows only some of its parts)
  drawnBounds(p) {
    // a model of particles alone (a ghost's fog) has no surface: it doesn't frame the view
    const mb = p.mesh.bounds;
    if (!p.mesh.vertices || !mb || mb[0][0] > mb[1][0]) return null;
    if (!p.opts.visible) return mb;
    const lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
    let any = false;
    for (const b of p.batches) {
      if (b.missing || !p.visible(b.geoset)) continue;
      for (let i = b.start; i < b.start + b.count; i++) {
        const v = p.indices[i] * 3;
        for (let a = 0; a < 3; a++) { const c = p.positions[v + a]; if (c < lo[a]) lo[a] = c; if (c > hi[a]) hi[a] = c; }
        any = true;
      }
    }
    return any ? [lo, hi] : null;
  }

  // the covariance of what the parts draw (bind pose), each triangle weighted by its area: a shield's
  // face counts, not the many small triangles of its chains or ribbons
  drawnCovariance() {
    let n = 0;
    const s = [0, 0, 0], ss = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
    const at = (p, i) => { const v = p.indices[i] * 3; return [p.positions[v], p.positions[v + 1], p.positions[v + 2]]; };
    for (const p of this.parts) for (const b of p.batches) {
      if (b.missing || !p.visible(b.geoset)) continue;
      for (let i = b.start; i + 2 < b.start + b.count; i += 3) {
        const A = at(p, i), B = at(p, i + 1), C = at(p, i + 2);
        const u = [B[0] - A[0], B[1] - A[1], B[2] - A[2]], w = [C[0] - A[0], C[1] - A[1], C[2] - A[2]];
        const area = 0.5 * Math.hypot(...cross(u, w));
        const x = [0, 1, 2].map(a => (A[a] + B[a] + C[a]) / 3);
        for (let a = 0; a < 3; a++) { s[a] += area * x[a]; for (let c = 0; c < 3; c++) ss[a][c] += area * x[a] * x[c]; }
        n += area;
      }
    }
    n = n || 1;
    return ss.map((row, a) => row.map((v, c) => v / n - (s[a] / n) * (s[c] / n)));
  }

  // A held item stood up: weapons and shields are modelled from the grip at the origin along +X (an
  // axe's head, a staff's crown, a shield's top), so +X goes up, and you face the flat side - the
  // thinner of Y and Z (a shield's front is +Y). Guns, bows and crossbows stay level, barrel along
  // the screen. Some shields and off-hands (Shadowlands' PvP ones, lanterns) are modelled along Z
  // instead: their long side stands up, +Z on top.
  orientHeld(slot) {
    let lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
    for (const p of this.parts) {
      const b = this.drawnBounds(p);
      if (b) for (let a = 0; a < 3; a++) { lo[a] = Math.min(lo[a], b[0][a]); hi[a] = Math.max(hi[a], b[1][a]); }
    }
    if (lo[0] > hi[0]) return;
    const thin = (hi[1] - lo[1]) <= (hi[2] - lo[2]) ? 1 : 2;
    // a shield's front is +Y; another item shows the side it reaches further out on
    const side = slot === 14 && thin === 1 ? 1 : (hi[thin] >= -lo[thin] ? 1 : -1);
    const f = [0, 0, 0]; f[thin] = side;                       // model axis that faces the camera
    const ranged = [15, 26].includes(slot);
    let up = ranged ? (thin === 2 ? [0, 1, 0] : [0, 0, 1]) : [1, 0, 0];
    if (slot === 14 || slot === 23) {
      // the long axis of the face (X and the other of Y and Z), from what the item draws
      const o2 = 3 - thin, c = this.drawnCovariance();
      const cxx = c[0][0], coo = c[o2][o2], cxo = c[0][o2], th = 0.5 * Math.atan2(2 * cxo, cxx - coo);
      const half = (cxx + coo) / 2, disc = Math.sqrt(Math.max(0, half * half - (cxx * coo - cxo * cxo)));
      const ratio = (half + disc) / Math.max(1e-9, half - disc), axis = [0, 0, 0];
      axis[0] = Math.cos(th); axis[o2] = Math.sin(th);
      if (slot === 14 && ratio > 1.4 && Math.abs(th) < Math.PI / 4) {
        up = axis;                                     // a shield modelled leaning, as it sits on the arm: its +X end on top
      } else if (ratio > 1.2 && Math.abs(th) > Math.PI / 4) {
        // modelled along the other axis: that axis up (the model's own, square to its face - horns or
        // spikes sticking out don't tilt it), its + end on top: a shield's top, the grip of an off-hand
        // that hangs from the hand (a lantern from its handle, a skull totem from its cord)
        up = [0, 0, 0];
        up[o2] = 1;
      }                                                // a round shield keeps +X up
    }
    const right = cross(up, f);
    const o = M4.ident();                                      // rows: view X = f, view Y = right, view Z = up
    for (let k = 0; k < 3; k++) { o[k * 4] = f[k]; o[k * 4 + 1] = right[k]; o[k * 4 + 2] = up[k]; }
    const mid = lo.map((v, a) => (v + hi[a]) / 2), c = M4.apply(o, mid);
    o[12] = mid[0] - c[0]; o[13] = mid[1] - c[1]; o[14] = mid[2] - c[2];
    for (const p of this.parts) p.orient = o;
  }

  // -- animation ----------------------------------------------------------------------------
  attachMatrix(att) {
    const body = att.part, a = (body.mesh.attachments || []).find(x => x[0] === att.id);
    if (!a) return null;
    const bm = body.world[a[1]] || IDENT;
    const local = M4.translate(bm, [a[2], a[3], a[4]]);
    // a body placed somewhere (a spell's target): its points are where it stands
    return body.opts.place ? M4.mul(this.modelMatrix(body), local) : local;
  }

  // opts.place(viewer, t): the part's frame from a callback (a spell's model on a stand-in, a missile
  // in flight); opts.scale: uniform scale after the offset
  modelMatrix(p) {
    let model = p.opts.place ? p.opts.place(this, this.time()) : p.opts.attach ? this.attachMatrix(p.opts.attach) : (p.orient || IDENT);
    if (!model) return null;
    if (p.offset[0] || p.offset[1] || p.offset[2]) model = M4.translate(model, p.offset);
    const s = p.opts.scale;
    if (s && s !== 1) {
      model = new Float32Array(model);
      for (let k = 0; k < 12; k++) if (k % 4 !== 3) model[k] *= s;
    }
    return model;
  }

  update(now0) {
    const eye = this.eye(), T = this.time();
    for (const p of this.parts) {
      const m = p.mesh, now = this.localTime(p, now0, T);
      // texture animations, colours and transparency
      p.uvMats = (m.uvanims || []).map(u => M4.bone([0.5, 0.5, 0], sample(u.t, now, m.duration, m.globals, 3) || [0, 0, 0],
        sample(u.r, now, m.duration, m.globals, 4) || [0, 0, 0, 1], sample(u.s, now, m.duration, m.globals, 3) || [1, 1, 1],
        new Float32Array(16)));
      p.colors = (m.colors || []).map(c => [...(sample(c.c, now, m.duration, m.globals, 3) || [1, 1, 1]),
                                            (sample(c.a, now, m.duration, m.globals, 1) || [1])[0]]);
      p.weights = (m.weights || []).map(w => (sample(w, now, m.duration, m.globals, 1) || [1])[0]);
      if (p.opts.bodyOf) continue;                       // bones after its body
      const n = p.bones.length;
      // opts.anim(t): another animation's keyframes for now ({tracks, duration, now}) - a caster's
      // spell animations over the timeline - else the mesh's own (Stand)
      const ov = p.opts.anim ? p.opts.anim(T) : null;
      const bnow = ov ? ov.now : now, bdur = ov ? ov.duration : m.duration;
      for (let i = 0; i < n; i++) {
        const b = p.bones[i], k = ov ? (ov.tracks[i] || {}) : b;
        const t = sample(k.t, bnow, bdur, m.globals, 3) || [0, 0, 0];
        const r = sample(k.r, bnow, bdur, m.globals, 4) || [0, 0, 0, 1];
        const s = sample(k.s, bnow, bdur, m.globals, 3) || [1, 1, 1];
        const local = M4.bone(b.v, t, r, s, new Float32Array(16));
        const w = b.p >= 0 && p.world[b.p] ? M4.mul(p.world[b.p], local) : local;
        if (b.f & 0x8) {                                   // a spherical billboard: turn it to the camera
          const pos = M4.apply(w, b.v), f = norm(sub(eye, pos)), rt = norm(cross([0, 0, 1], f)), up = cross(f, rt);
          const sc = [0, 1, 2].map(c => Math.hypot(w[c * 4], w[c * 4 + 1], w[c * 4 + 2]));
          [f, rt, up].forEach((ax, c) => { for (let k = 0; k < 3; k++) w[c * 4 + k] = ax[k] * sc[c]; });
          for (let k = 0; k < 3; k++) w[12 + k] = pos[k] - (w[k] * b.v[0] + w[4 + k] * b.v[1] + w[8 + k] * b.v[2]);
        }
        p.world[i] = w;
        p.mats.set(w, i * 16);
      }
    }
    for (const p of this.parts) {
      if (!p.opts.bodyOf) continue;
      const body = p.opts.bodyOf;
      p.map.forEach((bi, i) => { p.mats.set(bi >= 0 && body.world[bi] ? body.world[bi] : IDENT, i * 16); });
    }
    for (const p of this.parts) {
      if (!p.phys) continue;
      if (this.physicsOn === false) { p.phys.last = 0; continue; }
      this.stepPhysics(p, performance.now());
    }
  }

  // Particles: born at their emitter (on its bone) at its rate, flying out within its spread at its
  // speed, pulled by gravity and drag, living their lifespan; drawn as camera-facing sprites coloured,
  // faded and sized along their life, a sprite-sheet cell each.
  particles(now0, dt) {
    const T = this.time();
    for (const p of this.parts) {
      if (!p.emitters.length) continue;
      const model = this.modelMatrix(p);
      if (!model) continue;
      const m = p.mesh, now = this.localTime(p, now0, T), on = this.active(p, T);
      for (const em of p.emitters) {
        const d = em.def;
        for (const q of em.list) {
          q.age += dt;
          const g = q.grav;
          for (let k = 0; k < 3; k++) q.v[k] += g[k] * dt;
          const drag = Math.max(0, 1 - d.drag * dt);
          for (let k = 0; k < 3; k++) { q.v[k] *= drag; q.p[k] += q.v[k] * dt; }
        }
        em.list = em.list.filter(q => q.age < q.life);
        if (!on) continue;                                 // outside its time: what flies, flies on
        if (d.enabled && value(d.enabled, now, m, 1) < 0.5) continue;
        const rate = Math.max(0, value(d.rate, now, m, 0) + rnd() * d.rate_var);
        em.acc += rate * dt;
        let n = Math.min(Math.floor(em.acc), 60);
        em.acc -= Math.floor(em.acc);
        if (!n || em.list.length >= MAX_PARTICLES) continue;
        const frame = M4.mul(model, p.world[d.bone] || IDENT);
        // the model's scale (a spell's 0.15 rift) sizes and speeds its particles as well as its mesh
        const ms = Math.hypot(model[0], model[1], model[2]) || 1;
        const len = value(d.length, now, m, 0), wid = value(d.width, now, m, 0);
        const vr = value(d.vrange, now, m, 0), hr = value(d.hrange, now, m, 0);
        const speed = value(d.speed, now, m, 0), speedVar = value(d.speed_var, now, m, 0);
        const life = value(d.life, now, m, 1);
        let grav = sample(d.gravity, now, m.duration, m.globals, d.gravity && d.gravity.v.length > d.gravity.t.length ? 3 : 1) || [0];
        grav = grav.length === 3 ? M4.rotate(model, grav) : M4.rotate(model, [0, 0, -grav[0]]);
        while (n-- > 0 && em.list.length < MAX_PARTICLES) {
          const polar = Math.random() * vr, az = hr > 0 ? rnd() * hr : Math.random() * Math.PI * 2;
          const dir = [Math.sin(polar) * Math.cos(az), Math.sin(polar) * Math.sin(az), Math.cos(polar)];
          let local;
          if (d.type === 2) {                              // a sphere: from its surface, outward
            const r = len + Math.random() * Math.max(0, wid - len);
            local = [d.pos[0] + dir[0] * r, d.pos[1] + dir[1] * r, d.pos[2] + dir[2] * r];
          } else {                                         // a plane (and the rest): from its rectangle
            local = [d.pos[0] + rnd() * len / 2, d.pos[1] + rnd() * wid / 2, d.pos[2]];
          }
          const v = norm(M4.rotate(frame, dir)), sp = speed * (1 + rnd() * speedVar) * ms;
          em.list.push({p: M4.apply(frame, local), v: v.map(c => c * sp), age: 0, grav, s: ms,
                        life: Math.max(0.03, life + rnd() * d.life_var), r: Math.random(), r2: Math.random(),
                        spin: d.base_spin + rnd() * d.base_spin_var});
        }
      }
    }
  }

  drawParticles(mvp, view) {
    const gl = this.gl;
    const right = [view[0], view[4], view[8]], up = [view[1], view[5], view[9]];
    gl.useProgram(this.pprog);
    gl.uniformMatrix4fv(this.pu.mvp, false, mvp);
    gl.uniform1i(this.pu.tex, 0);
    gl.bindVertexArray(this.pvao);
    gl.depthMask(false); gl.enable(gl.BLEND);
    for (const p of this.parts) for (const em of p.emitters) {
      if (!em.list.length || !em.tex || !em.tex.ready) continue;
      const d = em.def, data = new Float32Array(em.list.length * 6 * 9);
      const cells = d.rows * d.cols, tw = [d.twinkle[2] > 0 ? d.twinkle[2] : 1, d.twinkle[3] > 0 ? d.twinkle[3] : 1];
      let o = 0;
      for (const q of em.list) {
        const t = q.age / q.life;
        const col = lifeValue(d.color, t, 3) || [1, 1, 1], a = (lifeValue(d.alpha, t, 1) || [1])[0];
        const sc = lifeValue(d.scale, t, 2) || [0.1, 0.1];
        const mul = (1 + (q.r * 2 - 1) * (d.scale_var[0] || 0)) * (tw[0] + (tw[1] - tw[0]) * q.r2);
        const sx = Math.max(0, sc[0] * mul * (q.s || 1)), sy = Math.max(0, sc[1] * mul * (q.s || 1));
        const cell = Math.floor((lifeValue(d.cells, t, 1) || [0])[0]) % cells;
        const u0 = (cell % d.cols) / d.cols, v0 = Math.floor(cell / d.cols) / d.rows, u1 = u0 + 1 / d.cols, v1 = v0 + 1 / d.rows;
        const ang = q.spin + d.spin * q.age * 1000, ca = Math.cos(ang), sa = Math.sin(ang);
        const rx = right.map((c, k) => (c * ca + up[k] * sa) * sx), ry = up.map((c, k) => (c * ca - right[k] * sa) * sy);
        const corner = (i, j, u, v) => {
          for (let k = 0; k < 3; k++) data[o++] = q.p[k] + rx[k] * i + ry[k] * j;
          data[o++] = u; data[o++] = v;
          data[o++] = col[0]; data[o++] = col[1]; data[o++] = col[2]; data[o++] = a;
        };
        corner(-1, -1, u0, v1); corner(1, -1, u1, v1); corner(1, 1, u1, v0);
        corner(-1, -1, u0, v1); corner(1, 1, u1, v0); corner(-1, 1, u0, v0);
      }
      gl.bindBuffer(gl.ARRAY_BUFFER, this.pbuf);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW);
      if (d.blend === 2 || d.blend === 1 || d.blend === 0) gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      else gl.blendFunc(gl.SRC_ALPHA, gl.ONE);           // add, blend-add: glows, sparks, flames
      gl.uniform1f(this.pu.ref, d.blend === 1 ? 0.5 : 0.004);
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, em.tex.tex);
      gl.drawArrays(gl.TRIANGLES, 0, o / 9);
    }
    gl.bindVertexArray(null);
  }

  eye() {
    const v = this.view, cp = Math.cos(v.pitch);
    return [v.center[0] + v.dist * cp * Math.cos(v.yaw), v.center[1] + v.dist * cp * Math.sin(v.yaw),
            v.center[2] + v.dist * Math.sin(v.pitch)];
  }

  play() {
    if (this._loop) return;
    const tick = () => {
      if (!this.canvas.isConnected || !this.animated()) { this._loop = 0; return; }
      this._draw(); this._loop = requestAnimationFrame(tick);
    };
    this._loop = requestAnimationFrame(tick);
  }

  draw() {
    if (this.animated()) return this.play();
    if (this._pending) return;
    this._pending = requestAnimationFrame(() => { this._pending = 0; this._draw(); });
  }

  bindTexture(unit, t, wrap) {
    const gl = this.gl;
    gl.activeTexture(unit);
    gl.bindTexture(gl.TEXTURE_2D, t.tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, wrap[0] ? gl.REPEAT : gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, wrap[1] ? gl.REPEAT : gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  }

  _draw() {
    const gl = this.gl, c = this.canvas, dpr = window.devicePixelRatio || 1;
    const w = Math.round(c.clientWidth * dpr), h = Math.round(c.clientHeight * dpr);
    if (!w || !h) return;
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    const now = performance.now() - this.start0, dt = this.last ? Math.min(0.1, (now - this.last) / 1000) : 0;
    this.last = now;
    const clk = this.clock, T = this.time();
    if (clk) {
      if (T < clk.last) for (const p of this.parts) for (const em of p.emitters) em.list = [];   // looped round
      clk.last = T;
      if (clk.onTick) clk.onTick(T);
    }
    this.update(now);
    // on a timeline, particles move at its pace: slowed with it, frozen while it's paused
    this.particles(now, clk ? (clk.paused ? 0 : dt * clk.speed) : dt);
    gl.viewport(0, 0, w, h);
    gl.clearColor(0.07, 0.08, 0.1, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE);
    const v = this.view, view = M4.look(this.eye(), v.center, [0, 0, 1]);
    const mvp = M4.mul(M4.persp(0.7, w / h, v.dist / 200, v.dist * 30), view);
    gl.useProgram(this.prog);
    gl.uniformMatrix4fv(this.u.uMvp, false, mvp);
    gl.uniformMatrix4fv(this.u.uView, false, view);
    gl.uniform3f(this.u.uLight, Math.cos(v.yaw + 0.6) * 0.6, Math.sin(v.yaw + 0.6) * 0.6, 0.53);
    gl.uniform1i(this.u.uTex, 0); gl.uniform1i(this.u.uBones, 1); gl.uniform1i(this.u.uTex2, 2); gl.uniform1i(this.u.uTex3, 3);
    const uvMat = (p, i) => i >= 0 && p.uvMats[i] ? p.uvMats[i] : IDENT;
    for (const pass of [0, 1]) {
      for (const p of this.parts) {
        if (!this.active(p, T)) continue;
        const model = this.modelMatrix(p);
        if (!model) continue;
        gl.uniformMatrix4fv(this.u.uModel, false, model);
        gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, p.boneTex);
        gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, p.nb * 4, 1, gl.RGBA, gl.FLOAT, p.mats);
        gl.uniform1i(this.u.uSkinned, 1);
        gl.bindVertexArray(p.vao);
        for (const b of p.batches) {
          if (b.missing || !p.visible(b.geoset)) continue;
          const col = b.color >= 0 && p.colors[b.color] ? p.colors[b.color] : [1, 1, 1, 1];
          const wgt = b.weight >= 0 && p.weights[b.weight] !== undefined ? p.weights[b.weight] : 1;
          const tint = [p.tint[0] * col[0], p.tint[1] * col[1], p.tint[2] * col[2], p.tint[3] * col[3] * wgt];
          if (tint[3] <= 0.003) continue;
          const blended = b.blend >= 2 || tint[3] < 1;
          if (blended !== (pass === 1)) continue;
          const mode = tint[3] < 1 && b.blend < 2 ? 2 : b.blend;
          this.blend(mode);
          gl.uniform1i(this.u.uPremul, mode === 7 ? 1 : 0);
          gl.uniform4fv(this.u.uTint, tint);
          const t = b.tex && b.tex.ready ? b.tex : null;
          // a see-through batch waits for its texture: drawn without one it's a solid card (a mantle's
          // light rays as two grey slabs while their texture loads - or forever, when it can't)
          if (!t && blended) continue;
          gl.uniform1i(this.u.uHasTex, t ? 1 : 0);
          if (t) this.bindTexture(gl.TEXTURE0, t, b.wrap);
          // the combiner, or the first texture alone while one of the others is missing or loading
          const sh = b.sh, full = b.extra.length === b.need - 1 && b.extra.every(x => x && x.ready);
          const ps = full ? sh.ps : (PS_MOD.has(sh.ps) ? PS.Mod : PS.Opaque);
          gl.uniform1i(this.u.uPs, ps);
          gl.uniform1i(this.u.uKeyTex, b.blend === 1 && !PS_MOD.has(ps) ? 1 : 0);
          gl.uniform3i(this.u.uCoord, sh.coords[0], sh.coords[1] ?? U1, sh.coords[2] ?? U1);
          gl.uniform1i(this.u.uEdge, sh.edge ? 1 : 0);
          gl.uniform1i(this.u.uMask, full && sh.mask ? 1 : 0);
          const layers = b.layers || [], wt = i => i >= 0 && p.weights[i] !== undefined ? p.weights[i] : 1;
          gl.uniform3f(this.u.uWgt, wt(b.weight), wt(layers[0] ? layers[0].weight : -1), wt(layers[1] ? layers[1].weight : -1));
          // a texture animation belongs to the coordinates, not the texture: the first UVs move by the
          // batch's first transform, the second UVs by its second, an environment map by none - so two
          // textures on the first UVs move together (a weapon's leaves don't slide a second texture sheet
          // across themselves because the batch's next transform scrolls a glow elsewhere)
          const m0 = uvMat(p, b.uvanim), m1 = uvMat(p, layers[0] ? layers[0].uvanim : -1);
          const matOf = c => c === U1 ? m0 : c === U2 ? m1 : IDENT;
          gl.uniformMatrix4fv(this.u.uUvMat, false, matOf(sh.coords[0]));
          gl.uniformMatrix4fv(this.u.uUv2Mat, false, matOf(sh.coords[1] ?? U1));
          // a mask has a transform of its own (most often none): it stays put under the scrolling layers
          gl.uniformMatrix4fv(this.u.uUv3Mat, false, sh.mask ? uvMat(p, layers[1] ? layers[1].uvanim : -1) : matOf(sh.coords[2] ?? U1));
          if (full) b.extra.forEach((x, i) => this.bindTexture(i ? gl.TEXTURE3 : gl.TEXTURE2, x, layers[i].wrap));
          gl.uniform1f(this.u.uAlphaRef, b.blend === 1 ? 0.5 : (b.blend >= 2 ? 0.004 : -1));
          gl.uniform1i(this.u.uUnlit, b.unlit ? 1 : 0);
          gl.uniform1i(this.u.uOpaque, b.blend === 0 && tint[3] >= 1 ? 1 : 0);
          // a one-sided material shows its front faces only, as the game draws it: a shell built round
          // a model (Gul'dan's glowing outline) then shows only at its silhouette, not over the body
          if (this.cull && b.two_sided === false) { gl.enable(gl.CULL_FACE); gl.cullFace(gl.BACK); gl.frontFace(this.cull); }
          else gl.disable(gl.CULL_FACE);
          gl.drawElements(gl.TRIANGLES, b.count, gl.UNSIGNED_INT, b.start * 4);
        }
      }
    }
    gl.disable(gl.CULL_FACE);
    this.drawGlow(T);
    gl.bindVertexArray(null);
    this.drawParticles(mvp, view);
    gl.depthMask(true); gl.disable(gl.BLEND);
  }

  // A part's state effects (opts.glow, from retail's GradientEffect and OutlineEffect): {edge: [r, g, b]}
  // draws its outline, {colors: [c0, c1, c2], alphas: [inner, edge]} its gradient glow. Over its solid
  // batches only (an alpha-keyed one cut by its texture), after everything else.
  drawGlow(T) {
    const gl = this.gl, u = this.u;
    for (const p of this.parts) {
      // a glow may follow the timeline: a function of it (a spell's aura glow)
      const g = typeof p.opts.glow === "function" ? p.opts.glow(T) : p.opts.glow;
      if (!g || !this.active(p, T)) continue;
      const model = this.modelMatrix(p);
      if (!model) continue;
      gl.uniformMatrix4fv(u.uModel, false, model);
      gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, p.boneTex);
      gl.bindVertexArray(p.vao);
      const solid = p.batches.filter(b => !b.missing && p.visible(b.geoset) && b.blend < 2);
      const each = () => {
        for (const b of solid) {
          const t = b.tex && b.tex.ready ? b.tex : null;
          gl.uniform1i(u.uHasTex, t ? 1 : 0);
          if (t) this.bindTexture(gl.TEXTURE0, t, b.wrap);
          gl.uniform3i(u.uCoord, b.sh.coords[0], U1, U1);
          gl.uniformMatrix4fv(u.uUvMat, false, b.uvanim >= 0 && p.uvMats[b.uvanim] ? p.uvMats[b.uvanim] : IDENT);
          gl.uniform1f(u.uAlphaRef, b.blend === 1 ? 0.5 : -1);
          gl.drawElements(gl.TRIANGLES, b.count, gl.UNSIGNED_INT, b.start * 4);
        }
      };
      if (g.edge) {
        // the outline: the model's back faces, pushed out a little, in the edge colour
        this.blend(0);
        gl.enable(gl.CULL_FACE); gl.cullFace(g.cull || gl.FRONT);
        gl.uniform1i(u.uFx, 2);
        gl.uniform3fv(u.uFxEdge, g.edge);
        gl.uniform1f(u.uPush, (g.width || 0.012) * (p.radius || 1));
        each();
        gl.disable(gl.CULL_FACE);
        gl.uniform1f(u.uPush, 0);
      }
      if (g.colors) {
        gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE); gl.depthMask(false); gl.depthFunc(gl.LEQUAL);
        gl.uniform1i(u.uFx, 1);
        gl.uniform3fv(u.uC0, g.colors[0]); gl.uniform3fv(u.uC1, g.colors[1]); gl.uniform3fv(u.uC2, g.colors[2]);
        gl.uniform2f(u.uFxA, g.alphas ? g.alphas[0] : 0.5, g.alphas ? g.alphas[1] : 0.8);
        each();
        gl.depthFunc(gl.LESS);
      }
      gl.uniform1i(u.uFx, 0);
    }
    gl.depthMask(true); gl.disable(gl.BLEND);
  }

  // M2 blend modes: 0 opaque, 1 alpha key, 2 alpha, 3 add (no alpha), 4 add, 5 modulate, 6 modulate x2,
  // 7 blend-add (premultiplied: the colour is added over what the alpha leaves)
  blend(mode) {
    const gl = this.gl;
    if (mode <= 1) { gl.disable(gl.BLEND); gl.depthMask(true); return; }
    gl.enable(gl.BLEND); gl.depthMask(false);
    if (mode === 2) gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    else if (mode === 3) gl.blendFunc(gl.ONE, gl.ONE);
    else if (mode === 4) gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
    else if (mode === 5) gl.blendFunc(gl.DST_COLOR, gl.ZERO);
    else if (mode === 6) gl.blendFunc(gl.DST_COLOR, gl.SRC_COLOR);
    else gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  }
}
window.Viewer = Viewer;
