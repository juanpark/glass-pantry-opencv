// Draws web/scene.js's shapes with three.js (plan v4 slice 5). Read-only; loaded only when the person opens the 3D
// view. Everything about where things go is decided in scene.js; this file only chooses materials and the camera.
import * as THREE from "three";
import {OrbitControls} from "three/addons/controls/OrbitControls.js";
import {sceneOf, cameraFor, levelBox, changeOf, firstShown} from "./scene.js";

const PALETTE = [0xd9a55b, 0x7fb3a6, 0xc96f5a, 0x8aa0c8, 0xb7c27a, 0xd08fb0, 0x9c8bd1, 0xe0c46c];

function tag(text){  // a readable name that always faces the camera
  const c = document.createElement("canvas"), x = c.getContext("2d"), fs = 44;
  x.font = `600 ${fs}px system-ui, sans-serif`;
  const w = Math.min(900, Math.ceil(x.measureText(text).width) + 28);
  c.width = w; c.height = fs + 24;
  x.font = `600 ${fs}px system-ui, sans-serif`; x.fillStyle = "rgba(255,255,255,.9)"; x.fillRect(0, 0, w, c.height);
  x.fillStyle = "#1b221e"; x.textBaseline = "middle"; x.fillText(text, 14, c.height / 2, w - 28);
  // the same size on screen however far the camera is, so names stay readable on a phone
  const s = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), depthTest: false, sizeAttenuation: false}));
  s.scale.set(w / c.height * 0.026, 0.026, 1);
  s.renderOrder = 10;
  return s;
}

const centre = b => new THREE.Vector3(b[0] + b[3] / 2, b[1] + b[4] / 2, b[2] + b[5] / 2);

/** Draw `twin` (layout `row`) into `host`. With `change` = {from: the fridge just before, level: the shelf that changed},
 * on that shelf only: things that left fade out, things that moved slide from where they stood, new things drop in.
 * Returns {dispose}. */
export function mount(host, twin, row, change = null){
  const {cabinet: {w: W, h: H, d: D}, parts} = sceneOf(twin, row);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf4f2ee);
  const cam = new THREE.PerspectiveCamera(35, host.clientWidth / host.clientHeight, 10, 20000);
  let home = null;  // after a change: the shelf that changed; otherwise the whole cabinet
  const frame = () => {  // the home view at this aspect (scene.js, tested for every layout)
    const c = home ? cameraFor(home, cam.aspect, cam.fov, home.at) : cameraFor({w: W, h: H, d: D}, cam.aspect, cam.fov);
    cam.position.set(...c.position); cam.lookAt(...c.target);
    return c.target;
  };
  const target = frame();
  const ren = new THREE.WebGLRenderer({antialias: true});
  ren.setPixelRatio(Math.min(devicePixelRatio, 2));
  ren.setSize(host.clientWidth, host.clientHeight);
  ren.domElement.style.touchAction = "none";  // one finger turns the fridge instead of scrolling the page
  host.append(ren.domElement);
  const ctl = new OrbitControls(cam, ren.domElement);
  ctl.target.set(...target); ctl.enableDamping = true; ctl.update();
  scene.add(new THREE.HemisphereLight(0xffffff, 0xb8b0a4, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4); sun.position.set(W, H * 1.5, D * 2); scene.add(sun);

  const shell = new THREE.Mesh(new THREE.BoxGeometry(W, H, D),
    new THREE.MeshStandardMaterial({color: 0xdfe3e1, transparent: true, opacity: 0.18, depthWrite: false}));
  shell.position.set(0, H / 2, 0); scene.add(shell);
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(shell.geometry), new THREE.LineBasicMaterial({color: 0x56635c}));
  edges.position.copy(shell.position); scene.add(edges);

  const glass = new THREE.MeshStandardMaterial({color: 0xbfe0e6, transparent: true, opacity: 0.45, roughness: 0.1});
  const drawer = new THREE.MeshStandardMaterial({color: 0xcfd6d3, transparent: true, opacity: 0.35});
  let k = 0;
  const diff = change ? changeOf(sceneOf(change.from, row).parts, parts, change.level) : {moved: [], added: [], gone: []};
  const movedFrom = new Map(diff.moved.map(m => [m.pid, m.from])), added = new Set(diff.added);
  const moves = [], things = [];  // moves: {obj, a: start, b: end, fade: -1 out | 0 | 1 in}
  const item = (p, colour) => {
    const [, , , w, h, d] = p.box, c = centre(p.box);
    const geo = p.shape === "cyl" ? new THREE.CylinderGeometry(w / 2, w / 2, h, 24) : new THREE.BoxGeometry(w, h, d);
    const g = new THREE.Group(), m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({color: colour, roughness: 0.6, transparent: true}));
    const t = tag(p.label); t.position.set(0, h / 2 + 30, 20);
    t.visible = false;  // names show for what just changed, or on a tap, so they never cover the fridge
    g.add(m, t); g.position.copy(c); g.userData = {tag: t, level: p.level}; scene.add(g); things.push(g);
    return g;
  };
  for(const p of parts){
    const [, , , w, h, d] = p.box, c = centre(p.box);
    if(p.kind === "compartment"){
      const o = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(w, h, d)),
        new THREE.LineBasicMaterial({color: p.cold ? 0x2e7d6b : 0x5b7fb0}));
      o.position.copy(c); scene.add(o);
    }else if(p.kind === "shelf" || p.kind === "drawer"){
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), p.kind === "shelf" ? glass : drawer);
      m.position.copy(c); scene.add(m);
    }else{
      const g = item(p, PALETTE[k++ % PALETTE.length]), on = change && p.level === change.level && p.pid;
      if(on && movedFrom.has(p.pid)) moves.push({obj: g, a: centre(movedFrom.get(p.pid)), b: c.clone(), fade: 0});
      else if(on && added.has(p.pid)) moves.push({obj: g, a: c.clone().add(new THREE.Vector3(0, 260, 0)), b: c.clone(), fade: 1});
    }
  }
  for(const p of diff.gone)  // gone from the shelf (to Unplaced): shown where it stood, then fades out
    moves.push({obj: item(p, 0xc0392b), a: centre(p.box), b: centre(p.box).add(new THREE.Vector3(0, 0, 120)), fade: -1});
  for(const m of moves) m.obj.userData.tag.visible = true;
  // the camera first glides from the whole fridge to the shelf that changed, then the change plays
  const lb = moves.length ? levelBox([...parts, ...diff.gone], change.level) : null;
  const camA = cam.position.clone(), tgtA = ctl.target.clone();
  home = lb || null;
  const START = home ? 1100 : 500, DUR = 1600, t0 = performance.now();
  let flying = !!home;
  const step = now => {
    if(flying){  // computed each frame, so a resize during the glide still ends on the shelf
      const near = cameraFor(home, cam.aspect, cam.fov, home.at);
      const f = Math.min(1, (now - t0) / 1000), e = f < 0.5 ? 2 * f * f : 1 - (-2 * f + 2) ** 2 / 2;
      cam.position.lerpVectors(camA, new THREE.Vector3(...near.position), e); ctl.target.lerpVectors(tgtA, new THREE.Vector3(...home.at), e);
      if(f >= 1) flying = false;
    }
    const t = Math.min(1, Math.max(0, (now - t0 - START) / DUR)), e = 1 - (1 - t) ** 3;
    for(const m of moves){
      m.obj.position.lerpVectors(m.a, m.b, e);
      const o = m.fade === 1 ? e : m.fade === -1 ? 1 - e : 1;
      m.obj.traverse(n => { if(n.material){ n.material.transparent = true; n.material.opacity = o; } });
      if(m.fade === -1 && t >= 1 && m.obj.visible){ m.obj.visible = false; things.splice(things.indexOf(m.obj), 1); }
    }
  };
  if(moves.length) step(t0);

  // a tap (not a drag) on a thing shows or hides its name
  const ray = new THREE.Raycaster(); let down = null;
  ren.domElement.addEventListener("pointerdown", e => { down = [e.clientX, e.clientY]; });
  ren.domElement.addEventListener("pointerup", e => {
    if(!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 6) return;
    const r = ren.domElement.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1), cam);
    const hit = firstShown(ray.intersectObjects(things, true));
    if(hit){ const t = hit.object.parent.userData.tag; t.visible = !t.visible; }
  });

  let alive = true;
  const fit = () => {  // a new size reframes the home view
    cam.aspect = host.clientWidth / host.clientHeight; cam.updateProjectionMatrix(); ctl.target.set(...frame()); ctl.update();
    ren.setSize(host.clientWidth, host.clientHeight);
  };
  const ro = new ResizeObserver(fit); ro.observe(host);
  (function loop(now){ if(!alive) return; if(moves.length) step(now ?? performance.now()); ctl.update(); ren.render(scene, cam); requestAnimationFrame(loop); })();
  return {dispose(){ alive = false; ro.disconnect(); ctl.dispose(); ren.dispose(); ren.domElement.remove(); }};
}
