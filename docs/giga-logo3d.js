// GigaMail — il logo "GIGA" in Three.js: lettere estruse, fulmine al posto della I,
// gradiente blu -> rosa sulle facce e bordo navy sui fianchi, corsivo, animato piano.
// Monta un canvas dentro #giga-3d; l'<img> con il PNG resta come fallback.
import * as THREE from "three";
import { TTFLoader } from "three/addons/loaders/TTFLoader.js";
import { Font } from "three/addons/loaders/FontLoader.js";

// Titan One (OFL), servito da Google Fonts con CORS: tondo, largo e pesante come il lettering del PNG.
const FONT_URL = "https://fonts.gstatic.com/s/titanone/v17/mFTzWbsGxbbS_J5cQcjClDgj.ttf";

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

  // facce piatte (colori esatti del PNG), fianchi navy illuminati (danno la profondita' quando ruota)
  const faceMat = new THREE.MeshBasicMaterial({ vertexColors: true });
  const edgeMat = new THREE.MeshStandardMaterial({ color: EDGE, roughness: 0.6, metalness: 0.1 });
  const plateMat = new THREE.MeshBasicMaterial({ color: EDGE });

  const S = 1;                       // corpo del carattere
  const DEPTH = 0.20 * S;            // spessore
  const OUTLINE = 0.075 * S;         // bordo navy piatto attorno a tutto
  const LIFT = 0.02 * S;             // le lettere colorate stanno un pelo davanti al piatto navy
  const SHEAR = 0.22;                // corsivo delle lettere
  const BOLT_SHEAR = 0.34;           // il fulmine e' piu' inclinato

  // fulmine: poligono in unita' di S, da sopra le lettere a sotto la base
  function boltShape() {
    const p = [[0.16, 1.14], [0.50, 1.14], [0.35, 0.66], [0.54, 0.66], [0.06, -0.26], [0.22, 0.42], [0.02, 0.42]];
    return new THREE.Shape(p.map(([x, y]) => new THREE.Vector2(x * S, y * S)));
  }

  const letters = [];   // gruppi lettera, per l'accensione a scalare
  function build(font) {
    // ogni pezzo: le sue shape e il suo corsivo
    const pieces = [
      { shapes: font.generateShapes("G", S), shear: SHEAR },
      { shapes: [boltShape()],              shear: BOLT_SHEAR, bolt: true },
      { shapes: font.generateShapes("G", S), shear: SHEAR },
      { shapes: font.generateShapes("A", S), shear: SHEAR },
    ];
    const colored = (shapes) => new THREE.ExtrudeGeometry(shapes, { depth: DEPTH, bevelEnabled: false, curveSegments: 12 });
    const plate   = (shapes) => new THREE.ExtrudeGeometry(shapes, { depth: DEPTH - LIFT, bevelEnabled: true,
      bevelSize: OUTLINE, bevelThickness: 0.001, bevelSegments: 1, curveSegments: 12 });

    // affiancamento sulle facce colorate: lettere quasi a contatto, fulmine incastrato tra le G
    let x = 0;
    const all = new THREE.Box3();
    pieces.forEach((pc, i) => {
      pc.face = colored(pc.shapes); pc.back = plate(pc.shapes);
      pc.face.computeBoundingBox();
      const b = pc.face.boundingBox;
      const gap = pc.bolt ? -0.12 * S : (i === 2 ? -0.12 * S : -0.01 * S);
      const dx = -b.min.x + x + (i ? gap : 0);
      pc.face.translate(dx, 0, LIFT); pc.back.translate(dx, 0, 0);
      pc.face.computeBoundingBox();
      all.union(pc.face.boundingBox);
      x = pc.face.boundingBox.max.x;
    });

    // gradiente per vertice sull'altezza complessiva (facce colorate)
    const h = all.max.y - all.min.y;
    const tmp = new THREE.Color();
    pieces.forEach((pc) => {
      const pos = pc.face.attributes.position, col = new Float32Array(pos.count * 3);
      for (let i = 0; i < pos.count; i++) {
        const t = THREE.MathUtils.clamp((pos.getY(i) - all.min.y) / h, 0, 1);
        if (t < 0.5) tmp.lerpColors(BOT, MID, t / 0.5); else tmp.lerpColors(MID, TOP, (t - 0.5) / 0.5);
        col[i * 3] = tmp.r; col[i * 3 + 1] = tmp.g; col[i * 3 + 2] = tmp.b;
      }
      pc.face.setAttribute("color", new THREE.BufferAttribute(col, 3));
    });

    // corsivo, centratura, mesh
    const center = all.getCenter(new THREE.Vector3());
    pieces.forEach((pc) => {
      const shear = new THREE.Matrix4().makeShear(pc.shear, 0, 0, 0, 0, 0);
      const L = new THREE.Group();
      [pc.face, pc.back].forEach((g, k) => {
        g.translate(-center.x, -center.y, -DEPTH / 2);
        g.applyMatrix4(shear);
        L.add(new THREE.Mesh(g, k === 0 ? [faceMat, edgeMat] : [plateMat, edgeMat]));
      });
      logo.add(L);
      letters.push(L);
    });
    logoWidth = (all.max.x - all.min.x) + 2 * OUTLINE + h * SHEAR;
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
