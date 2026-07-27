/**
 * 环境粒子场（移植自 RAG-第一组 EnvParticleField）
 * perspective：整齐透视网格；可选中心疏、四边密的层次（非粒子飞散）
 * radial：旧实验布局，默认关闭
 * 共享高度场起伏；鼠标邻近提亮。
 */

const POINTER_FOCUS_VIEWPORT_RATIO = 0.2;
const ENABLE_POINTER_FOCUS = true;
/** @type {"radial" | "perspective"} */
const LAYOUT_MODE = "perspective";
/** 在整齐网格上做「中心→四边」层次；效果不佳改为 false 即回退 */
const ENABLE_CENTER_SPREAD = true;

function fade(t) {
  return t * t * (3 - 2 * t);
}

function smoothstep(edge0, edge1, x) {
  const t = Math.max(0, Math.min(1, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

function hash2(ix, iy) {
  const n = Math.sin(ix * 127.1 + iy * 311.7) * 43758.5453123;
  return n - Math.floor(n);
}

function valueNoise(x, y) {
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  const fx = x - x0;
  const fy = y - y0;
  const ux = fade(fx);
  const uy = fade(fy);
  const a = hash2(x0, y0);
  const b = hash2(x0 + 1, y0);
  const c = hash2(x0, y0 + 1);
  const d = hash2(x0 + 1, y0 + 1);
  return a + (b - a) * ux + (c - a) * uy + (a - b - c + d) * ux * uy;
}

function fbm(x, y) {
  let v = 0;
  let a = 0.5;
  let f = 1;
  for (let i = 0; i < 3; i++) {
    v += a * valueNoise(x * f, y * f);
    f *= 2.02;
    a *= 0.5;
  }
  return v;
}

function heightField(wx, wz, t) {
  const morph = t * 0.045;
  const drift = t * 0.055;
  const n = fbm(wx * 0.85 + drift, wz * 0.75 + morph);
  const w1 = Math.sin(wx * 2.15 + wz * 1.05 + t * 0.28);
  const w2 = Math.sin(wx * 1.05 - wz * 1.65 + t * 0.18);
  const w3 = Math.sin(wx * 3.4 + wz * 0.4 + t * 0.12 + n * 1.2);
  return (n - 0.5) * 0.52 + w1 * 0.26 + w2 * 0.16 + w3 * 0.1;
}

function hexToRgb(color) {
  const raw = String(color || "").trim();
  const hexMatch = raw.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (hexMatch) {
    let h = hexMatch[1];
    if (h.length === 3) h = h.split("").map((c) => c + c).join("");
    return {
      r: parseInt(h.slice(0, 2), 16),
      g: parseInt(h.slice(2, 4), 16),
      b: parseInt(h.slice(4, 6), 16),
    };
  }
  const rgbMatch = raw.match(/rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/i);
  if (rgbMatch) {
    return {
      r: Math.round(Number(rgbMatch[1])),
      g: Math.round(Number(rgbMatch[2])),
      b: Math.round(Number(rgbMatch[3])),
    };
  }
  return { r: 61, g: 155, b: 255 };
}

function readThemePrimary() {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--color-primary").trim();
  return raw || "#3D9BFF";
}

function makeSoftDotSprite(rgb, size = 20) {
  const c = document.createElement("canvas");
  c.width = size;
  c.height = size;
  const g = c.getContext("2d");
  const mid = size / 2;
  const { r, g: gg, b } = rgb;
  const grd = g.createRadialGradient(mid, mid, 0, mid, mid, mid * 0.9);
  grd.addColorStop(0, `rgba(${Math.min(255, r + 40)}, ${Math.min(255, gg + 35)}, ${Math.min(255, b + 30)}, 1)`);
  grd.addColorStop(0.35, `rgba(${r}, ${gg}, ${b}, 0.88)`);
  grd.addColorStop(0.7, `rgba(${r}, ${gg}, ${b}, 0.32)`);
  grd.addColorStop(1, `rgba(${r}, ${gg}, ${b}, 0)`);
  g.fillStyle = grd;
  g.beginPath();
  g.arc(mid, mid, mid * 0.9, 0, Math.PI * 2);
  g.fill();
  return c;
}

/**
 * @param {HTMLElement} host
 * @param {{ fixed?: boolean }} [opts]
 * @returns {{ setPausePointerFocus: (v: boolean) => void, destroy: () => void }}
 */
export function mountEnvParticleField(host, { fixed = false } = {}) {
  if (!host) {
    return { setPausePointerFocus() {}, destroy() {} };
  }

  const wrap = document.createElement("div");
  wrap.className = `env-particle-field${fixed ? " env-particle-field--fixed" : ""}`;
  wrap.setAttribute("aria-hidden", "true");
  const canvas = document.createElement("canvas");
  canvas.className = "env-particle-field__canvas";
  wrap.appendChild(canvas);
  host.appendChild(wrap);

  let rafId = 0;
  let gridPoints = [];
  let softDot = null;
  let softDotKey = "";
  let softDotTheme = null;
  let softDotThemeKey = "";
  let viewW = 0;
  let viewH = 0;
  let gridCols = 0;
  let gridRows = 0;
  let pauseFocus = false;
  let destroyed = false;

  const pointer = { x: 0, y: 0, sx: 0, sy: 0, active: false, focus: 0 };

  function isLightTheme() {
    return document.documentElement.getAttribute("data-theme") === "light";
  }

  /** 日间：偏深主色点（浅底可读）；夜间：亮灰点（深底可读） */
  function ambientDotRgb() {
    if (isLightTheme()) {
      const primary = hexToRgb(readThemePrimary());
      return {
        r: Math.round(primary.r * 0.42 + 36),
        g: Math.round(primary.g * 0.45 + 52),
        b: Math.round(primary.b * 0.52 + 88),
      };
    }
    return { r: 232, g: 234, b: 240 };
  }

  function ensureSoftDot() {
    const key = `${isLightTheme() ? "light" : "dark"}:${readThemePrimary()}`;
    if (softDot && softDotKey === key) return softDot;
    softDotKey = key;
    softDot = makeSoftDotSprite(ambientDotRgb(), 20);
    return softDot;
  }

  function ensureSoftDotTheme() {
    const key = `focus:${isLightTheme() ? "light" : "dark"}:${readThemePrimary()}`;
    if (softDotTheme && softDotThemeKey === key) return softDotTheme;
    softDotThemeKey = key;
    const { r, g, b } = hexToRgb(readThemePrimary());
    const c = document.createElement("canvas");
    c.width = 28;
    c.height = 28;
    const gctx = c.getContext("2d");
    const grd = gctx.createRadialGradient(14, 14, 0, 14, 14, 13);
    if (isLightTheme()) {
      grd.addColorStop(0, `rgba(${Math.min(255, r + 20)}, ${Math.min(255, g + 15)}, ${Math.min(255, b + 10)}, 1)`);
      grd.addColorStop(0.3, `rgba(${r}, ${g}, ${b}, 0.78)`);
      grd.addColorStop(0.65, `rgba(${r}, ${g}, ${b}, 0.3)`);
      grd.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);
    } else {
      grd.addColorStop(0, `rgba(${Math.min(255, r + 80)}, ${Math.min(255, g + 70)}, ${Math.min(255, b + 60)}, 1)`);
      grd.addColorStop(0.25, `rgba(${r}, ${g}, ${b}, 0.88)`);
      grd.addColorStop(0.55, `rgba(${r}, ${g}, ${b}, 0.38)`);
      grd.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);
    }
    gctx.fillStyle = grd;
    gctx.beginPath();
    gctx.arc(14, 14, 13, 0, Math.PI * 2);
    gctx.fill();
    softDotTheme = c;
    return softDotTheme;
  }

  function invalidateSprites() {
    softDot = null;
    softDotKey = "";
    softDotTheme = null;
    softDotThemeKey = "";
  }

  function initParticleGrid(width, height) {
    gridPoints = [];
    if (LAYOUT_MODE === "radial") {
      // 角向更密、径向略疏，避免出现明显圆环感
      gridCols = Math.max(96, Math.min(140, Math.round(width / 14)));
      gridRows = Math.max(48, Math.min(72, Math.round(height / 16)));
      const tau = Math.PI * 2;
      for (let j = 0; j < gridRows; j++) {
        const r0 = (j + 0.5) / gridRows;
        for (let i = 0; i < gridCols; i++) {
          const theta = ((i + (j % 2) * 0.5) / gridCols) * tau;
          const jitterR = (hash2(i + 3, j + 11) - 0.5) * 0.018;
          const jitterT = (hash2(i + 19, j + 7) - 0.5) * 0.04;
          gridPoints.push({ r0: r0 + jitterR, theta: theta + jitterT, i, j });
        }
      }
      return;
    }

    gridCols = Math.max(110, Math.min(160, Math.round(width / 12)));
    gridRows = Math.max(70, Math.min(100, Math.round(height / 11)));
    for (let j = 0; j < gridRows; j++) {
      const v = (j / (gridRows - 1)) * 1.12 - 0.02;
      for (let i = 0; i < gridCols; i++) {
        const u = (i / (gridCols - 1)) * 1.36 - 0.18;
        gridPoints.push({ u, v, i, j });
      }
    }
  }

  function projectPerspective(p, width, height, t, fieldDrift, slowMorph) {
    const wx = p.u * 6.2 + fieldDrift;
    const wz = p.v * 4.4;
    let elev = heightField(wx, wz + slowMorph * 0.25, t);
    const depth = 0.92 + Math.max(0, Math.min(1, p.v)) * 0.85;
    const persp = 1 / depth;
    const xSpan = width * (1.42 + (1 - Math.min(1, Math.max(0, p.v))) * 0.55);
    const x = width * 0.5 + (p.u - 0.5) * xSpan * (0.5 + 0.5 * persp);
    const vClamped = Math.max(0, Math.min(1.15, p.v));
    const yBase = height * (-0.06 + vClamped * 1.08);
    const amp = height * (0.035 + Math.min(1, Math.max(0, p.v)) * 0.055);
    const elevScale = 0.45 + Math.min(1, Math.max(0, p.v)) * 0.45;

    // 以画面中心偏上为焦点（对齐标题区），算椭圆半径 0→中心 1→近边角
    const nx = x / width - 0.5;
    const ny = yBase / height - 0.42;
    const rad = Math.sqrt((nx * nx) / 0.52 + (ny * ny) / 0.4);

    // 轻微径向波只作用在高度，点仍钉在网格上
    if (ENABLE_CENTER_SPREAD) {
      const ripple = Math.sin(rad * 5.8 - t * 0.95);
      elev = elev * (0.9 + ripple * 0.12) + ripple * 0.045;
    }

    const y = yBase - elev * amp * elevScale * (0.8 + persp * 0.35);

    let clearFade;
    if (ENABLE_CENTER_SPREAD) {
      // 中心更透、往四边逐渐铺满，网格结构不变
      clearFade = 0.18 + 0.82 * smoothstep(0.06, 0.92, rad);
    } else {
      const nx2 = x / width - 0.5;
      const ny2 = y / height - 0.4;
      const clearR = (nx2 * nx2) / 0.28 + (ny2 * ny2) / 0.07;
      clearFade = 0.62 + 0.38 * Math.min(1, clearR);
    }

    const crest = 0.75 + Math.max(0, elev) * 0.85;
    const farFade = 0.55 + Math.min(1, Math.max(0, p.v)) * 0.45;
    const pulse = ENABLE_CENTER_SPREAD ? 0.9 + 0.1 * Math.sin(rad * 5.8 - t * 0.95) : 1;
    const baseA = isLightTheme() ? 0.62 : 0.55;
    const a = baseA * farFade * clearFade * crest * pulse;
    const edgeBoost = ENABLE_CENTER_SPREAD ? 0.92 + 0.18 * smoothstep(0.2, 1.05, rad) : 1;
    const s =
      (1.05 + Math.min(1, Math.max(0, p.v)) * 1.85) * (0.9 + Math.max(0, elev) * 0.4) * edgeBoost;
    return { x, y, a, s, elev, amp };
  }

  function projectRadial(p, width, height, t, fieldDrift, slowMorph) {
    // 径向循环：中心诞生 → 向外扩散 → 边缘淡出，再回到中心
    const expand = ((p.r0 + t * 0.055) % 1 + 1) % 1;
    const wx = Math.cos(p.theta) * 3.4 + fieldDrift * 0.65;
    const wz = Math.sin(p.theta) * 3.4 + expand * 2.8;
    const elev = heightField(wx, wz + slowMorph * 0.25, t);

    const ang = p.theta + elev * 0.12 + fieldDrift * 0.04;
    // 略偏椭圆，铺满四角；elev 做轻微径向扰动
    const maxRx = width * 0.78;
    const maxRy = height * 0.78;
    const rr = Math.min(1.15, Math.pow(expand, 0.9) + elev * 0.028);
    const x = width * 0.5 + Math.cos(ang) * rr * maxRx;
    const y = height * 0.5 + Math.sin(ang) * rr * maxRy;

    const birth = smoothstep(0.02, 0.14, expand);
    const death = 1 - smoothstep(0.78, 0.98, expand);
    // 正中留一口气给标题/图标，避免中心过亮
    const hole = 0.55 + 0.45 * smoothstep(0.06, 0.22, expand);
    const crest = 0.78 + Math.max(0, elev) * 0.7;
    const baseA = isLightTheme() ? 0.58 : 0.52;
    const a = baseA * birth * death * hole * crest;
    const s = (1.05 + expand * 1.55) * (0.88 + Math.max(0, elev) * 0.35);
    const amp = Math.min(width, height) * 0.04;
    return { x, y, a, s, elev, amp };
  }

  function resizeParticleCanvas() {
    if (destroyed) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    viewW = window.innerWidth;
    viewH = window.innerHeight;
    canvas.width = Math.floor(viewW * dpr);
    canvas.height = Math.floor(viewH * dpr);
    canvas.style.width = `${viewW}px`;
    canvas.style.height = `${viewH}px`;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    invalidateSprites();
    ensureSoftDot();
    ensureSoftDotTheme();
    initParticleGrid(viewW, viewH);
  }

  function onPointerMove(e) {
    if (!ENABLE_POINTER_FOCUS || pauseFocus) return;
    pointer.x = e.clientX;
    pointer.y = e.clientY;
    pointer.active = true;
  }

  function onPointerLeaveWindow() {
    pointer.active = false;
  }

  function onDocumentMouseOut(e) {
    if (!e.relatedTarget) onPointerLeaveWindow();
  }

  function drawParticles(ts) {
    if (destroyed) return;
    const ctx = canvas.getContext("2d");
    const width = viewW || window.innerWidth;
    const height = viewH || window.innerHeight;
    const t = (ts || 0) * 0.001;
    const sprite = ensureSoftDot();
    const spriteTheme = ensureSoftDotTheme();
    const fieldDrift = t * 0.09;
    const slowMorph = t * 0.035;

    if (ENABLE_POINTER_FOCUS) {
      if (!pointer.sx && !pointer.sy) {
        pointer.sx = pointer.x || width * 0.5;
        pointer.sy = pointer.y || height * 0.5;
      }
      pointer.sx += (pointer.x - pointer.sx) * 0.14;
      pointer.sy += (pointer.y - pointer.sy) * 0.14;
      const targetFocus = pointer.active && !pauseFocus ? 1 : 0;
      pointer.focus += (targetFocus - pointer.focus) * 0.08;
    } else {
      pointer.focus = 0;
    }

    const focusR = Math.min(width, height) * POINTER_FOCUS_VIEWPORT_RATIO;
    const focusR2 = focusR * focusR;
    const hasFocus = ENABLE_POINTER_FOCUS && pointer.focus > 0.01;

    ctx.clearRect(0, 0, width, height);

    for (let n = 0; n < gridPoints.length; n++) {
      const p = gridPoints[n];
      const proj =
        LAYOUT_MODE === "radial"
          ? projectRadial(p, width, height, t, fieldDrift, slowMorph)
          : projectPerspective(p, width, height, t, fieldDrift, slowMorph);
      let { x, y, a, s, elev, amp } = proj;

      if (x < -40 || x > width + 40 || y < -40 || y > height + 40) continue;

      let fall = 0;
      if (hasFocus) {
        const dx = x - pointer.sx;
        const dy = y - pointer.sy;
        fall = Math.exp(-(dx * dx + dy * dy) / focusR2) * pointer.focus;
        if (fall > 0.02) {
          a *= 1 + fall * 1.15;
          s *= 1 + fall * 0.5;
          // 径向模式下沿半径外推一点，强化「扩散」手感
          if (LAYOUT_MODE === "radial") {
            const cx = width * 0.5;
            const cy = height * 0.5;
            const ox = x - cx;
            const oy = y - cy;
            const len = Math.hypot(ox, oy) || 1;
            const push = fall * amp * 0.35;
            x += (ox / len) * push;
            y += (oy / len) * push;
          } else {
            y += fall * Math.max(0, elev) * amp * 0.18;
          }
        }
      }

      if (a < 0.08) continue;

      if (fall > 0.04) {
        const mix = Math.min(1, fall * 1.35);
        ctx.globalAlpha = Math.min(0.75, a * (1 - mix * 0.55));
        ctx.drawImage(sprite, x - s, y - s, s * 2, s * 2);
        ctx.globalAlpha = Math.min(0.88, a * mix * 0.95);
        const sb = s * (1 + mix * 0.2);
        ctx.drawImage(spriteTheme, x - sb, y - sb, sb * 2, sb * 2);
      } else {
        ctx.globalAlpha = Math.min(0.92, a);
        ctx.drawImage(sprite, x - s, y - s, s * 2, s * 2);
      }
    }

    ctx.globalAlpha = 1;
    rafId = window.requestAnimationFrame(drawParticles);
  }

  function start() {
    resizeParticleCanvas();
    if (rafId) window.cancelAnimationFrame(rafId);
    rafId = window.requestAnimationFrame(drawParticles);
  }

  function stop() {
    if (rafId) window.cancelAnimationFrame(rafId);
    rafId = 0;
  }

  const attrObserver = new MutationObserver(() => invalidateSprites());
  attrObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class", "data-theme", "style"],
  });

  window.addEventListener("resize", resizeParticleCanvas);
  window.addEventListener("mousemove", onPointerMove, { passive: true });
  window.addEventListener("mouseleave", onPointerLeaveWindow);
  document.addEventListener("mouseout", onDocumentMouseOut);
  start();

  return {
    setPausePointerFocus(v) {
      pauseFocus = !!v;
      if (pauseFocus) pointer.active = false;
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      stop();
      window.removeEventListener("resize", resizeParticleCanvas);
      window.removeEventListener("mousemove", onPointerMove);
      window.removeEventListener("mouseleave", onPointerLeaveWindow);
      document.removeEventListener("mouseout", onDocumentMouseOut);
      attrObserver.disconnect();
      wrap.remove();
    },
  };
}
