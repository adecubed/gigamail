// GigaMail — il logo "GIGA" in Three.js: lettere estruse, fulmine al posto della I,
// gradiente blu -> rosa sulle facce e bordo navy sui fianchi, corsivo, animato piano.
// Monta un canvas dentro #giga-3d; l'<img> con il PNG resta come fallback.
import * as THREE from "three";
import { TTFLoader } from "three/addons/loaders/TTFLoader.js";
import { Font } from "three/addons/loaders/FontLoader.js";
import { TextGeometry } from "three/addons/geometries/TextGeometry.js";
import { mergeVertices } from "three/addons/utils/BufferGeometryUtils.js";

// Luckiest Guy (OFL), servito da Google Fonts con CORS. Ha lo stesso carattere del PNG.
const FONT_URL = "https://fonts.gstatic.com/s/luckiestguy/v25/_gP_1RrxsjcxVyin9l9n_j2hTd5z.ttf";

const TOP = new THREE.Color("#4fc3ff");   // blu in alto
const MID = new THREE.Color("#8f8cf0");   // passaggio
const BOT = new THREE.Color("#ff5fcf");   // rosa in basso
const EDGE = 0x17233f;                    // navy del bordo

export function mount(host, opts = {}) {
  const reduced = opts.still || matchMedia("(prefers-reduced-motion: reduce)").matches;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance",
      preserveDrawingBuffer: !!opts.preserveDrawingBuffer });
  } catch (e) {
    console.warn("WebGL unavailable, keeping PNG logo", e);
    host.classList.add("nogl");
    return;
  }
  renderer.setPixelRatio(opts.pixelRatio ?? Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  host.appendChild(renderer.domElement);

  const scene  = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(26, 2, 0.1, 100);

  scene.add(new THREE.HemisphereLight(0xffffff, 0x8899bb, 1.5));
  const key = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(-2, 3, 5); scene.add(key);
  const rim = new THREE.DirectionalLight(0xffe0ff, 0.6); rim.position.set(3, -2, 2); scene.add(rim);

  const logo = new THREE.Group();
  scene.add(logo);

  const faceMat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.42, metalness: 0.05 });
  const edgeMat = new THREE.MeshStandardMaterial({ color: EDGE, roughness: 0.55, metalness: 0.1 });

  const S = 1;                       // corpo del carattere
  const DEPTH = 0.22 * S;            // spessore
  const BEVEL = 0.045 * S;           // bordo navy visibile sul davanti
  const SHEAR = 0.16;                // corsivo
  const extrude = { depth: DEPTH, bevelEnabled: true, bevelThickness: BEVEL, bevelSize: BEVEL, bevelSegments: 3, curveSegments: 10 };

  // fulmine: poligono in unita' di S, da sopra le lettere a sotto la base
  function boltGeometry() {
    const p = [[0.24, 1.10], [0.66, 1.10], [0.46, 0.62], [0.70, 0.62], [0.12, -0.22], [0.30, 0.40], [0.06, 0.40]];
    const shape = new THREE.Shape(p.map(([x, y]) => new THREE.Vector2(x * S, y * S)));
    return new THREE.ExtrudeGeometry(shape, extrude);
  }

  const letters = [];   // { mesh, from, to } per l'accensione a scalare
  function build(font) {
    const parts = [];
    const glyph = (ch) => new TextGeometry(ch, { font, size: S, ...extrude });
    parts.push(glyph("G"));
    parts.push(boltGeometry());
    parts.push(glyph("G"));
    parts.push(glyph("A"));

    // affiancamento: ogni pezzo parte dove finisce il precedente, con un piccolo sormonto
    let x = 0;
    const boxes = [];
    parts.forEach((g, i) => {
      g.computeBoundingBox();
      const b = g.boundingBox;
      const gap = (i === 1 || i === 2) ? -0.06 * S : 0.02 * S;   // il fulmine si incastra tra le G
      g.translate(-b.min.x + x + (i ? gap : 0), 0, 0);
      g.computeBoundingBox();
      boxes.push(g.boundingBox.clone());
      x = g.boundingBox.max.x;
    });

    // gradiente per vertice sull'altezza complessiva
    const all = new THREE.Box3();
    boxes.forEach((b) => all.union(b));
    const h = all.max.y - all.min.y;
    const tmp = new THREE.Color();
    parts.forEach((g) => {
      const pos = g.attributes.position, col = new Float32Array(pos.count * 3);
      for (let i = 0; i < pos.count; i++) {
        const t = THREE.MathUtils.clamp((pos.getY(i) - all.min.y) / h, 0, 1);
        if (t < 0.5) tmp.lerpColors(BOT, MID, t / 0.5); else tmp.lerpColors(MID, TOP, (t - 0.5) / 0.5);
        col[i * 3] = tmp.r; col[i * 3 + 1] = tmp.g; col[i * 3 + 2] = tmp.b;
      }
      g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    });

    // corsivo e centratura
    const shear = new THREE.Matrix4().makeShear(SHEAR, 0, 0, 0, 0, 0);
    const center = all.getCenter(new THREE.Vector3());
    parts.forEach((g, i) => {
      g.translate(-center.x, -center.y, -DEPTH / 2);
      g.applyMatrix4(shear);
      const m = new THREE.Mesh(g, [faceMat, edgeMat]);
      logo.add(m);
      letters.push(m);
    });
    logoWidth = (all.max.x - all.min.x) + h * SHEAR;
    resize();
    requestAnimationFrame(() => host.classList.add("ready"));
  }

  let logoWidth = 3.4;
  function resize() {
    const w = host.clientWidth, hh = host.clientHeight;
    if (!w || !hh) return;
    renderer.setSize(w, hh, false);
    camera.aspect = w / hh;
    camera.updateProjectionMatrix();
    // il logo occupa ~86% della larghezza del canvas
    const visible = logoWidth / 0.86;
    camera.position.set(0, 0, (visible / 2) / Math.tan((camera.fov * Math.PI / 180) / 2) / camera.aspect);
    camera.lookAt(0, 0, 0);
  }
  new ResizeObserver(resize).observe(host);
  resize();

  new TTFLoader().load(FONT_URL, (json) => build(new Font(json)), undefined, (e) => {
    console.warn("logo font unavailable, keeping PNG logo", e);
    host.classList.add("nogl");
    renderer.setAnimationLoop(null); renderer.dispose();
  });

  const target = { tx: 0, ty: 0 }, state = { tx: 0, ty: 0 };
  if (matchMedia("(hover: hover) and (pointer: fine)").matches) {
    addEventListener("pointermove", (e) => {
      target.tx = (e.clientX / innerWidth - 0.5) * 0.5;
      target.ty = (e.clientY / innerHeight - 0.5) * 0.3;
    });
  }

  const t0 = performance.now();
  const easeOutBack = (x) => { const c = 1.7; return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); };

  let stopped = false;
  const frame = () => {
    if (!host.isConnected) { if (!stopped) { stopped = true; renderer.setAnimationLoop(null); renderer.dispose(); } return; }
    if (host.offsetParent === null) return;   // fuori pagina: niente render, ma il loop resta vivo
    const t = (performance.now() - t0) / 1000;
    letters.forEach((m, i) => {
      const k = reduced ? 1 : THREE.MathUtils.clamp((t - i * 0.12) / 0.7, 0, 1);
      m.scale.setScalar(Math.max(0.001, easeOutBack(k)));
    });
    state.tx += (target.tx - state.tx) * 0.05;
    state.ty += (target.ty - state.ty) * 0.05;
    logo.rotation.y = state.tx + (reduced ? 0 : Math.sin(t * 0.6) * 0.22);
    logo.rotation.x = state.ty + (reduced ? 0 : Math.sin(t * 0.45) * 0.06);
    logo.position.y = reduced ? 0 : Math.sin(t * 0.9) * 0.03;
    renderer.render(scene, camera);
  };
  renderer.setAnimationLoop(frame);
  host.__frame = frame;
}

const host = document.getElementById("giga-3d");
if (host) mount(host);
export default mount;
