// Shared Three.js r170 PBR scene/mesh/texture helpers for PewPew 3D web games
import * as THREE from "../vendor/three.module.min.js";

export { THREE };

export const SECTORS = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5];

export const POOL_BALL_HEX = {
  0: "#f7f5ee",
  1: "#f5c524",
  2: "#2265df",
  3: "#dc312d",
  4: "#8733c9",
  5: "#f26b1d",
  6: "#1a8c45",
  7: "#872322",
  8: "#16181f",
  9: "#f5c524",
  10: "#2265df",
  11: "#dc312d",
  12: "#8733c9",
  13: "#f26b1d",
  14: "#1a8c45",
  15: "#872322",
};

export function createPubRenderer(canvas, { fov = 44, near = 0.05, far = 40, camPos = [0, 1.4, 2.2], lookAt = [0, 0, 0], ortho = false, alpha = false } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance", alpha });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.12;

  const scene = new THREE.Scene();
  if (alpha) {
    renderer.setClearColor(0x000000, 0);
    scene.background = null;
    scene.fog = null;
  } else {
    scene.background = new THREE.Color("#0d0b0a");
    scene.fog = new THREE.FogExp2("#0d0b0a", ortho ? 0.0 : 0.085);
  }

  const w = canvas.clientWidth || canvas.width || 540;
  const h = canvas.clientHeight || canvas.height || 360;
  const aspect = w / Math.max(h, 1);
  let camera;
  if (ortho) {
    const halfH = 0.68;
    const halfW = halfH * aspect;
    camera = new THREE.OrthographicCamera(-halfW, halfW, halfH, -halfH, near, far);
    camera.up.set(0, 0, -1);
  } else {
    camera = new THREE.PerspectiveCamera(fov, aspect, near, far);
  }
  camera.position.set(...camPos);
  camera.lookAt(...lookAt);
  renderer.setSize(w, h, false);

  const hemi = new THREE.HemisphereLight(0xffe8c8, 0x1a1e2e, 0.72);
  scene.add(hemi);

  const keySpot = new THREE.SpotLight(0xfff1d6, 3.6, 18, Math.PI * 0.42, 0.55, 1.2);
  keySpot.position.set(0.4, 3.8, 1.2);
  keySpot.castShadow = true;
  keySpot.shadow.mapSize.set(1024, 1024);
  keySpot.shadow.bias = -0.0005;
  scene.add(keySpot);
  scene.add(keySpot.target);

  const rim = new THREE.DirectionalLight(0x6bbcff, 0.65);
  rim.position.set(-2.5, 2.2, -2.5);
  scene.add(rim);

  const syncSize = () => {
    const cw = canvas.clientWidth || canvas.width || 540;
    const ch = canvas.clientHeight || canvas.height || 360;
    if (cw > 0 && ch > 0 && (canvas.width !== Math.round(cw * renderer.getPixelRatio()) || canvas.height !== Math.round(ch * renderer.getPixelRatio()))) {
      const a = cw / ch;
      if (camera.isOrthographicCamera) {
        let hh = 0.68;
        let hw = hh * a;
        if (hw < 1.20) {
          hw = 1.20;
          hh = hw / a;
        }
        camera.left = -hw;
        camera.right = hw;
        camera.top = hh;
        camera.bottom = -hh;
      } else {
        camera.aspect = a;
      }
      camera.updateProjectionMatrix();
      renderer.setSize(cw, ch, false);
    }
  };

  return { renderer, scene, camera, keySpot, syncSize };
}

export function makeWoodTexture(baseHex = "#4a2a18", grainHex = "#2e170c") {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 512;
  const ctx = c.getContext("2d");
  ctx.fillStyle = baseHex;
  ctx.fillRect(0, 0, 512, 512);
  for (let y = 0; y < 512; y += 2) {
    const wave = Math.sin(y * 0.06) * 0.5 + 0.5;
    ctx.fillStyle = grainHex;
    ctx.globalAlpha = 0.08 + wave * 0.12;
    ctx.fillRect(0, y, 512, 1.5);
  }
  ctx.globalAlpha = 0.06;
  for (let i = 0; i < 42; i++) {
    ctx.fillStyle = i % 2 ? "#000000" : "#8b5634";
    ctx.fillRect(0, (i * 17) % 512, 512, 1 + (i % 3));
  }
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export function makeFeltTexture() {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 256;
  const ctx = c.getContext("2d");
  const grad = ctx.createRadialGradient(256, 128, 30, 256, 128, 310);
  grad.addColorStop(0, "#197f4c");
  grad.addColorStop(1, "#0d5230");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 512, 256);
  // Subtle woven baize micro-speckle
  for (let i = 0; i < 4200; i++) {
    ctx.fillStyle = i % 2 ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.05)";
    ctx.fillRect((i * 73) % 512, (i * 137) % 256, 1, 1);
  }
  // Baulk head string + spot
  ctx.strokeStyle = "rgba(255,255,255,0.16)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(128, 12);
  ctx.lineTo(128, 244);
  ctx.stroke();
  ctx.fillStyle = "rgba(255,255,255,0.22)";
  ctx.beginPath();
  ctx.arc(384, 128, 4, 0, Math.PI * 2);
  ctx.fill();
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export function makePoolBallTexture(num) {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 128;
  const ctx = c.getContext("2d");
  const color = POOL_BALL_HEX[num] || "#ffffff";
  const striped = num >= 9;

  ctx.fillStyle = striped ? "#f6f3ea" : color;
  ctx.fillRect(0, 0, 256, 128);

  if (striped) {
    ctx.fillStyle = color;
    ctx.fillRect(0, 30, 256, 68);
  }

  if (num > 0) {
    for (const cx of [64, 192]) {
      ctx.fillStyle = "#f9f7f2";
      ctx.beginPath();
      ctx.arc(cx, 64, 26, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#111319";
      ctx.font = "900 28px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(num), cx, 66);
    }
  } else {
    // Subtle pro-cup red alignment dots on cue ball
    for (const [cx, cy] of [[64, 64], [192, 64]]) {
      ctx.fillStyle = "#d92b2b";
      ctx.beginPath();
      ctx.arc(cx, cy, 5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export function makeDartboardTexture() {
  const c = document.createElement("canvas");
  c.width = 1024;
  c.height = 1024;
  const ctx = c.getContext("2d");
  const cx = 512, cy = 512;
  ctx.fillStyle = "#101216";
  ctx.fillRect(0, 0, 1024, 1024);

  const br = 395;
  ctx.beginPath();
  ctx.arc(cx, cy, br + 65, 0, Math.PI * 2);
  ctx.fillStyle = "#13151a";
  ctx.fill();

  for (let i = 0; i < 20; i++) {
    const a0 = ((i * 18 - 99) * Math.PI) / 180;
    const a1 = (((i + 1) * 18 - 99) * Math.PI) / 180;
    const even = i % 2 === 0;
    const seg = (rIn, rOut, col) => {
      ctx.beginPath();
      ctx.arc(cx, cy, rOut, a0, a1);
      ctx.arc(cx, cy, rIn, a1, a0, true);
      ctx.closePath();
      ctx.fillStyle = col;
      ctx.fill();
    };
    seg(br * 0.12, br * 0.56, even ? "#15171c" : "#f0e5c8");
    seg(br * 0.56, br * 0.64, even ? "#d92828" : "#159a4a");
    seg(br * 0.64, br * 0.92, even ? "#15171c" : "#f0e5c8");
    seg(br * 0.92, br * 1.0, even ? "#d92828" : "#159a4a");

    ctx.strokeStyle = "rgba(218,224,234,0.8)";
    ctx.lineWidth = 2.4;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(a0) * br * 0.12, cy + Math.sin(a0) * br * 0.12);
    ctx.lineTo(cx + Math.cos(a0) * br, cy + Math.sin(a0) * br);
    ctx.stroke();

    const midA = (a0 + a1) * 0.5;
    ctx.fillStyle = "#eef2f7";
    ctx.font = "900 32px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(SECTORS[i]), cx + Math.cos(midA) * (br + 36), cy + Math.sin(midA) * (br + 36));
  }

  for (const rad of [0.12, 0.56, 0.64, 0.92, 1.0]) {
    ctx.beginPath();
    ctx.arc(cx, cy, br * rad, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(218,224,234,0.85)";
    ctx.lineWidth = 2.4;
    ctx.stroke();
  }
  ctx.beginPath();
  ctx.arc(cx, cy, br * 0.12, 0, Math.PI * 2);
  ctx.fillStyle = "#159a4a";
  ctx.fill();
  ctx.beginPath();
  ctx.arc(cx, cy, br * 0.055, 0, Math.PI * 2);
  ctx.fillStyle = "#d92828";
  ctx.fill();

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export function createSoloCupMesh({ topR = 0.056, botR = 0.039, h = 0.145 } = {}) {
  const grp = new THREE.Group();
  // Iconic ribbed red Solo outer shell via LatheGeometry (clean closed wall under the rolled lip)
  const rAt = (f) => botR + (topR - botR) * f;
  const outerPts = [
    new THREE.Vector2(0, 0),
    new THREE.Vector2(botR, 0),
    new THREE.Vector2(rAt(0.22), h * 0.22),
    new THREE.Vector2(rAt(0.24) + 0.0014, h * 0.24),
    new THREE.Vector2(rAt(0.26), h * 0.26),
    new THREE.Vector2(rAt(0.52), h * 0.52),
    new THREE.Vector2(rAt(0.54) + 0.0014, h * 0.54),
    new THREE.Vector2(rAt(0.56), h * 0.56),
    new THREE.Vector2(rAt(0.80), h * 0.80),
    new THREE.Vector2(rAt(0.82) + 0.0014, h * 0.82),
    new THREE.Vector2(rAt(0.84), h * 0.84),
    new THREE.Vector2(topR, h * 0.96),
    new THREE.Vector2(topR * 1.03, h),
    new THREE.Vector2(topR * 0.96, h),
  ];
  const outerGeo = new THREE.LatheGeometry(outerPts, 32);
  const outerMat = new THREE.MeshPhysicalMaterial({
    color: 0xd9262e,
    roughness: 0.25,
    metalness: 0.02,
    clearcoat: 0.65,
    clearcoatRoughness: 0.18,
  });
  const outerMesh = new THREE.Mesh(outerGeo, outerMat);
  outerMesh.castShadow = true;
  outerMesh.receiveShadow = true;
  grp.add(outerMesh);

  // Inner white Solo sleeve meeting the outer rim seamlessly with zero seam gap
  const innerPts = [
    new THREE.Vector2(0, 0.006),
    new THREE.Vector2(botR * 0.92, 0.006),
    new THREE.Vector2(topR * 0.96, h),
  ];
  const innerGeo = new THREE.LatheGeometry(innerPts, 32);
  const innerMat = new THREE.MeshStandardMaterial({
    color: 0xf4f5f7,
    roughness: 0.34,
    side: THREE.BackSide,
  });
  grp.add(new THREE.Mesh(innerGeo, innerMat));

  // Rolled white lip torus sitting flush around top rim
  const rimGeo = new THREE.TorusGeometry(topR * 0.985, 0.0048, 12, 32);
  rimGeo.rotateX(Math.PI / 2);
  const rimMat = new THREE.MeshStandardMaterial({ color: 0xfafafa, roughness: 0.18 });
  const rim = new THREE.Mesh(rimGeo, rimMat);
  rim.position.y = h;
  rim.castShadow = true;
  grp.add(rim);

  // Amber liquid fill inside cup
  const beerGeo = new THREE.CircleGeometry(topR * 0.85, 28);
  beerGeo.rotateX(-Math.PI / 2);
  const beerMat = new THREE.MeshPhysicalMaterial({
    color: 0xe6a11c,
    roughness: 0.08,
    metalness: 0.05,
    clearcoat: 1.0,
    transparent: true,
    opacity: 0.92,
  });
  const beer = new THREE.Mesh(beerGeo, beerMat);
  beer.position.y = h * 0.72;
  grp.add(beer);

  return grp;
}

export function createDartMesh(flightHex = 0xf45d86) {
  const g = new THREE.Group();
  // Steel tip pointing along -Z
  const tipGeo = new THREE.ConeGeometry(0.003, 0.042, 12);
  tipGeo.rotateX(-Math.PI / 2);
  const tip = new THREE.Mesh(tipGeo, new THREE.MeshStandardMaterial({ color: 0xd0d6e0, metalness: 0.88, roughness: 0.2 }));
  tip.position.z = -0.021;
  g.add(tip);

  // Brass knurled barrel
  const barrelGeo = new THREE.CylinderGeometry(0.0068, 0.0056, 0.068, 16);
  barrelGeo.rotateX(Math.PI / 2);
  const barrel = new THREE.Mesh(barrelGeo, new THREE.MeshStandardMaterial({ color: 0xd7a84e, metalness: 0.82, roughness: 0.25 }));
  barrel.position.z = 0.032;
  barrel.castShadow = true;
  g.add(barrel);

  // Colored shaft
  const shaftGeo = new THREE.CylinderGeometry(0.0042, 0.0055, 0.062, 12);
  shaftGeo.rotateX(Math.PI / 2);
  const shaft = new THREE.Mesh(shaftGeo, new THREE.MeshStandardMaterial({ color: 0x1b1e28, roughness: 0.35 }));
  shaft.position.z = 0.095;
  g.add(shaft);

  // 4-fin crossed flights
  const finMat = new THREE.MeshStandardMaterial({ color: flightHex, roughness: 0.4, side: THREE.DoubleSide });
  const finGeo = new THREE.PlaneGeometry(0.045, 0.042);
  const f1 = new THREE.Mesh(finGeo, finMat);
  f1.rotation.y = Math.PI / 2;
  f1.position.z = 0.128;
  const f2 = f1.clone();
  f2.rotation.z = Math.PI / 2;
  g.add(f1, f2);
  return g;
}

export function createSuctionDartMesh(flightHex = 0xf45d86) {
  const g = new THREE.Group();
  // Flared rubber suction cup bell facing -Z
  const cupPts = [
    new THREE.Vector2(0.032, 0.0),
    new THREE.Vector2(0.029, 0.008),
    new THREE.Vector2(0.016, 0.022),
    new THREE.Vector2(0.010, 0.034),
    new THREE.Vector2(0.0, 0.034),
  ];
  const cupGeo = new THREE.LatheGeometry(cupPts, 24);
  cupGeo.rotateX(Math.PI / 2);
  const rubberMat = new THREE.MeshPhysicalMaterial({
    color: 0x1e2432,
    roughness: 0.28,
    clearcoat: 0.55,
    side: THREE.DoubleSide,
  });
  const cup = new THREE.Mesh(cupGeo, rubberMat);
  cup.position.z = -0.056;
  g.add(cup);

  const lip = new THREE.Mesh(
    new THREE.TorusGeometry(0.030, 0.0042, 10, 24),
    new THREE.MeshStandardMaterial({ color: 0x334155, roughness: 0.35 })
  );
  lip.position.z = -0.055;
  g.add(lip);

  // Chrome ferrule collar
  const collar = new THREE.Mesh(
    new THREE.CylinderGeometry(0.011, 0.012, 0.016, 18),
    new THREE.MeshStandardMaterial({ color: 0xd8e0ec, metalness: 0.9, roughness: 0.14 })
  );
  collar.rotation.x = Math.PI / 2;
  collar.position.z = -0.016;
  g.add(collar);

  // Neon foam shaft body
  const shaft = new THREE.Mesh(
    new THREE.CylinderGeometry(0.0095, 0.0115, 0.088, 20),
    new THREE.MeshStandardMaterial({ color: flightHex, roughness: 0.34, metalness: 0.08 })
  );
  shaft.rotation.x = Math.PI / 2;
  shaft.position.z = 0.036;
  shaft.castShadow = true;
  g.add(shaft);

  // Crossed swept tail fins
  const finShape = new THREE.Shape();
  finShape.moveTo(0, -0.009);
  finShape.lineTo(0.034, -0.024);
  finShape.lineTo(0.042, 0.024);
  finShape.lineTo(0, 0.022);
  finShape.closePath();
  const finGeo = new THREE.ExtrudeGeometry(finShape, { depth: 0.0025, bevelEnabled: false });
  finGeo.center();
  const finMat = new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.25, emissive: flightHex, emissiveIntensity: 0.14 });
  for (let i = 0; i < 4; i++) {
    const fin = new THREE.Mesh(finGeo, finMat);
    fin.rotation.y = Math.PI / 2;
    fin.rotation.z = (i * Math.PI) / 2;
    const ang = (i * Math.PI) / 2;
    fin.position.set(Math.cos(ang) * 0.015, Math.sin(ang) * 0.015, 0.095);
    g.add(fin);
  }
  return g;
}
