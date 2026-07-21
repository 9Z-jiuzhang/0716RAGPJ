/**
 * TechStart Pro · 全局动效（原生 SPA，无 React/Tailwind）
 * - 粒子网络背景
 * - 按钮涟漪
 * - 卡片鼠标聚光
 * - CountUp 数值滚动
 */

const prefersReduced =
  typeof window !== "undefined" &&
  window.matchMedia &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** 固定全屏粒子网络（底层，不拦截指针） */
export function initBackgroundEffects() {
  if (prefersReduced) return;
  if (document.getElementById("bgFxCanvas")) return;

  const wrap = document.createElement("div");
  wrap.className = "bg-fx";
  wrap.setAttribute("aria-hidden", "true");

  const canvas = document.createElement("canvas");
  canvas.id = "bgFxCanvas";
  canvas.className = "bg-fx-canvas";
  wrap.appendChild(canvas);
  document.body.prepend(wrap);

  const ctx = canvas.getContext("2d", { alpha: true });
  let w = 0;
  let h = 0;
  let dpr = 1;
  let raf = 0;
  const particles = [];
  const COUNT = 48;
  const LINK = 120;

  const resize = () => {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = window.innerWidth;
    h = window.innerHeight;
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };

  const seed = () => {
    particles.length = 0;
    for (let i = 0; i < COUNT; i += 1) {
      particles.push({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.35,
        vy: (Math.random() - 0.5) * 0.35,
        r: 0.8 + Math.random() * 1.4,
      });
    }
  };

  const cssColor = (name, fallback) => {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  };

  const tick = () => {
    ctx.clearRect(0, 0, w, h);
    const fill = cssColor("--color-primary", "#818cf8");
    const linkBase = cssColor("--color-focus-ring", "rgba(129, 140, 248, 0.35)");
    for (const p of particles) {
      p.x += p.vx;
      p.y += p.vy;
      if (p.x < 0 || p.x > w) p.vx *= -1;
      if (p.y < 0 || p.y > h) p.vy *= -1;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.globalAlpha = 0.35;
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.globalAlpha = 1;
    }
    for (let i = 0; i < particles.length; i += 1) {
      for (let j = i + 1; j < particles.length; j += 1) {
        const a = particles[i];
        const b = particles[j];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const dist = Math.hypot(dx, dy);
        if (dist > LINK) continue;
        const alpha = (1 - dist / LINK) * 0.35;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = linkBase;
        ctx.globalAlpha = alpha;
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
    }
    raf = requestAnimationFrame(tick);
  };

  resize();
  seed();
  window.addEventListener("resize", () => {
    resize();
    seed();
  });
  raf = requestAnimationFrame(tick);

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      cancelAnimationFrame(raf);
    } else {
      raf = requestAnimationFrame(tick);
    }
  });
}

/** 按钮点击涟漪（事件委托，100ms 内可见） */
function bindRipple() {
  if (prefersReduced) return;
  document.addEventListener(
    "click",
    (e) => {
      const btn = e.target.closest?.(".btn");
      if (!btn || btn.disabled) return;
      const rect = btn.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height);
      const x = e.clientX - rect.left - size / 2;
      const y = e.clientY - rect.top - size / 2;
      const ripple = document.createElement("span");
      ripple.className = "btn-ripple";
      ripple.style.width = `${size}px`;
      ripple.style.height = `${size}px`;
      ripple.style.left = `${x}px`;
      ripple.style.top = `${y}px`;
      btn.appendChild(ripple);
      window.setTimeout(() => ripple.remove(), 320);
    },
    true
  );
}

/** 卡片鼠标追踪高光（已关闭） */
function bindSpotlight() {
  /* no-op: 去除鼠标周围点亮 */
}

/**
 * CountUp：将 [data-count-up] 从 0 滚到目标值
 * @param {ParentNode} [root=document]
 */
export function runCountUps(root = document) {
  if (prefersReduced) {
    root.querySelectorAll("[data-count-up]").forEach((el) => {
      el.textContent = el.getAttribute("data-count-up") || "0";
    });
    return;
  }
  root.querySelectorAll("[data-count-up]").forEach((el) => {
    const raw = el.getAttribute("data-count-up");
    if (raw === null || raw === "-" || raw === "") return;
    const target = Number(raw);
    if (!Number.isFinite(target)) {
      el.textContent = raw;
      return;
    }
    const duration = 700;
    const start = performance.now();
    const from = 0;
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - (1 - t) ** 3;
      el.textContent = String(Math.round(from + (target - from) * eased));
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

/** 一次性初始化全局动效 */
let started = false;
export function initMotion() {
  if (started) return;
  started = true;
  initBackgroundEffects();
  bindRipple();
  bindSpotlight();
}
