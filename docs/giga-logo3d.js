// GigaMail — il logo "GIGA" in Three.js, dalle sagome esatte del PNG.
// brand/gigamail-logo.shapes.json (ricavato dal PNG con il vettorizzatore in scripts/) contiene
// il contorno del bordo navy e le quattro forme colorate (G, fulmine, G, A). Il bordo diventa
// un piatto navy estruso, le forme un secondo strato davanti con il gradiente blu -> rosa.
// Monta un canvas dentro #giga-3d; l'<img> con il PNG resta come fallback.
import * as THREE from "three";

const SHAPES_URL = new URL("brand/gigamail-logo.shapes.json", import.meta.url);

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

  // facce piatte (colori esatti del PNG), fianchi navy illuminati (profondita' quando ruota)
  const faceMat  = new THREE.MeshBasicMaterial({ vertexColors: true });
  const edgeMat  = new THREE.MeshStandardMaterial({ color: EDGE, roughness: 0.6, metalness: 0.1 });
  const plateMat = new THREE.MeshBasicMaterial({ color: EDGE });

  const DEPTH = 0.20;   // spessore (il logo e' alto 1)
  const LIFT  = 0.02;   // le forme colorate stanno un pelo davanti al piatto navy

  const toShape = (poly) => {
    const shape = new THREE.Shape(poly.outer.map(([x, y]) => new THREE.Vector2(x, y)));
    for (const h of poly.holes) shape.holes.push(new THREE.Path(h.map(([x, y]) => new THREE.Vector2(x, y))));
    return shape;
  };

  const letters = [];   // gruppi, per l'entrata a scalare
  function build(data) {
    const plate = new THREE.ExtrudeGeometry(data.outline.map(toShape), { depth: DEPTH - LIFT, bevelEnabled: false });
    plate.computeBoundingBox();
    const box = plate.boundingBox;
    const center = box.getCenter(new THREE.Vector3());
    const h = box.max.y - box.min.y;

    const faces = data.faces.map((poly) => {
      const g = new THREE.ExtrudeGeometry(toShape(poly), { depth: DEPTH, bevelEnabled: false });
      g.translate(0, 0, LIFT);
      const pos = g.attributes.position, col = new Float32Array(pos.count * 3), tmp = new THREE.Color();
      for (let i = 0; i < pos.count; i++) {
        const t = THREE.MathUtils.clamp((pos.getY(i) - box.min.y) / h, 0, 1);
        if (t < 0.5) tmp.lerpColors(BOT, MID, t / 0.5); else tmp.lerpColors(MID, TOP, (t - 0.5) / 0.5);
        col[i * 3] = tmp.r; col[i * 3 + 1] = tmp.g; col[i * 3 + 2] = tmp.b;
      }
      g.setAttribute("color", new THREE.BufferAttribute(col, 3));
      return g;
    });

    [plate, ...faces].forEach((g) => g.translate(-center.x, -center.y, -DEPTH / 2));

    // piatto navy: una mesh; poi ogni forma colorata nel suo gruppo (cosi' entra a scalare)
    const plateGroup = new THREE.Group();
    plateGroup.add(new THREE.Mesh(plate, [plateMat, edgeMat]));
    logo.add(plateGroup); letters.push(plateGroup);
    faces.forEach((g) => {
      const L = new THREE.Group();
      L.add(new THREE.Mesh(g, [faceMat, edgeMat]));
      logo.add(L); letters.push(L);
    });

    logoWidth = box.max.x - box.min.x;
    resize();
    requestAnimationFrame(() => host.classList.add("ready"));
  }

  let logoWidth = 1.9;
  function resize() {
    const w = host.clientWidth, hh = host.clientHeight;
    if (!w || !hh) return;
    renderer.setSize(w, hh, false);
    camera.aspect = w / hh;
    camera.updateProjectionMatrix();
    // il logo occupa ~88% della larghezza del canvas
    const visible = logoWidth / 0.88;
    camera.position.set(0, 0, (visible / 2) / Math.tan((camera.fov * Math.PI / 180) / 2) / camera.aspect);
    camera.lookAt(0, 0, 0);
  }
  new ResizeObserver(resize).observe(host);
  resize();

  fetch(SHAPES_URL).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }).then(build).catch((e) => {
    console.warn("logo shapes unavailable, keeping PNG logo", e);
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
      const k = reduced ? 1 : THREE.MathUtils.clamp((t - i * 0.10) / 0.7, 0, 1);
      m.scale.setScalar(Math.max(0.001, easeOutBack(k)));
    });
    state.tx += (target.tx - state.tx) * 0.05;
    state.ty += (target.ty - state.ty) * 0.05;
    logo.rotation.y = state.tx + (reduced ? 0 : Math.sin(t * 0.6) * 0.22);
    logo.rotation.x = state.ty + (reduced ? 0 : Math.sin(t * 0.45) * 0.06);
    logo.position.y = reduced ? 0 : Math.sin(t * 0.9) * 0.02;
    renderer.render(scene, camera);
  };
  renderer.setAnimationLoop(frame);
  host.__frame = frame;
}

const host = document.getElementById("giga-3d");
if (host) mount(host);
export default mount;
