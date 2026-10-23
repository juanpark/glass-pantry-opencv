// Draws web/scene.js's shapes with three.js (plan v4 slice 5). Read-only; loaded only when the person opens the 3D
// view. Everything about where things go is decided in scene.js; this file only chooses materials and the camera.
import * as THREE from "three";
import {OrbitControls} from "three/addons/controls/OrbitControls.js";
import {sceneOf, cameraFor} from "./scene.js";

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

/** Draw `twin` (layout `row`) into `host`. Returns {dispose}. */
export function mount(host, twin, row){
  const {cabinet: {w: W, h: H, d: D}, parts} = sceneOf(twin, row);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf4f2ee);
  const cam = new THREE.PerspectiveCamera(35, host.clientWidth / host.clientHeight, 10, 20000);
  const frame = () => {  // the whole cabinet in view at this aspect (scene.js, tested for every layout)
    const c = cameraFor({w: W, h: H, d: D}, cam.aspect, cam.fov);
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
      const geo = p.shape === "cyl" ? new THREE.CylinderGeometry(w / 2, w / 2, h, 24) : new THREE.BoxGeometry(w, h, d);
      const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({color: PALETTE[k++ % PALETTE.length], roughness: 0.6}));
      m.position.copy(c); scene.add(m);
      const t = tag(p.label); t.position.set(c.x, p.box[1] + h + 30, c.z + 20); scene.add(t);
    }
  }

  let alive = true;
  const fit = () => {  // a new size reframes the whole cabinet
    cam.aspect = host.clientWidth / host.clientHeight; cam.updateProjectionMatrix(); frame(); ctl.update();
    ren.setSize(host.clientWidth, host.clientHeight);
  };
  const ro = new ResizeObserver(fit); ro.observe(host);
  (function loop(){ if(!alive) return; ctl.update(); ren.render(scene, cam); requestAnimationFrame(loop); })();
  return {dispose(){ alive = false; ro.disconnect(); ctl.dispose(); ren.dispose(); ren.domElement.remove(); }};
}
