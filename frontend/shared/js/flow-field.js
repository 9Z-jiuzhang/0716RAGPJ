/**
 * 共享高度场透视点阵背景。
 * 点位是固定规则网格；只平移整场采样坐标，避免每个点独立随机抖动。
 */
export function initFlowField() {
  if (document.getElementById("flowFieldCanvas")) return;

  const canvas = document.createElement("canvas");
  canvas.id = "flowFieldCanvas";
  canvas.className = "flow-field-canvas";
  canvas.setAttribute("aria-hidden", "true");
  document.body.prepend(canvas);
  const ctx = canvas.getContext("2d", { alpha: true });
  let width = 0;
  let height = 0;
  let pixelRatio = 1;

  const resize = () => {
    pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.floor(width * pixelRatio);
    canvas.height = Math.floor(height * pixelRatio);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  };

  // 只有少量长波叠加，形成清晰的洋流波带。
  const elevation = (x, z, t) => {
    const waveA = Math.sin(x * 0.42 + z * 0.13 + t * 0.34) * 13;
    const waveB = Math.sin(x * 0.17 - z * 0.32 + t * 0.22 + 1.7) * 9;
    const waveC = Math.sin(x * 0.08 + z * 0.08 - t * 0.13) * 5;
    return waveA + waveB + waveC;
  };

  const draw = (now) => {
    const t = now * 0.001;
    // Canvas 直接承担整页背景，不与 body 的旧渐变叠加。
    const backdrop = ctx.createLinearGradient(0, 0, width, height);
    backdrop.addColorStop(0, "#F9FCFF");
    backdrop.addColorStop(0.52, "#F2F7FF");
    backdrop.addColorStop(1, "#F4FBF9");
    ctx.fillStyle = backdrop;
    ctx.fillRect(0, 0, width, height);
    const glow = ctx.createRadialGradient(width * 0.78, height * 0.26, 10, width * 0.78, height * 0.26, width * 0.55);
    glow.addColorStop(0, "rgba(153, 198, 255, .20)");
    glow.addColorStop(1, "rgba(153, 198, 255, 0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, width, height);
    if (width < 700 || height < 460) {
      requestAnimationFrame(draw);
      return;
    }

    // 整场采样坐标的统一缓慢平移，不产生个体乱抖。
    const driftX = t * 0.21;
    const driftZ = t * 0.16;
    const cols = Math.min(58, Math.max(36, Math.round(width / 28)));
    const rows = 25;
    // 让透视场覆盖内容中央，而不是只悬在页面上半部。
    const horizon = height * 0.18;
    const originX = width * 0.52;
    const spread = width * 1.16;
    const points = [];

    for (let iz = 0; iz < rows; iz += 1) {
      const z = iz / (rows - 1);
      const depth = 0.16 + z * 1.22;
      for (let ix = 0; ix < cols; ix += 1) {
        const x = (ix / (cols - 1) - 0.5) * spread;
        const worldX = x + driftX * 24;
        const worldZ = iz * 11 + driftZ * 24;
        const elev = elevation(worldX * 0.045, worldZ * 0.045, t);
        const perspective = 1 / depth;
        const screenX = originX + x * perspective * 0.92;
        const screenY = horizon + z * height * 0.76 - elev * perspective * 0.75;
        if (screenX < -20 || screenX > width + 20 || screenY < -20 || screenY > height + 20) continue;
        points.push({ screenX, screenY, elev, depth, perspective });
      }
    }

    // 远淡近亮；绘制顺序从远到近。
    points.sort((a, b) => b.depth - a.depth);
    for (const point of points) {
      const near = Math.max(0, Math.min(1, (point.depth - 0.16) / 1.22));
      const crest = Math.max(0, Math.min(1, (point.elev + 20) / 42));
      const radius = 0.55 + near * 1.65 + crest * 0.35;
      const alpha = 0.035 + near * 0.12 + crest * 0.10;
      const hue = crest > 0.64 ? "51, 145, 224" : "74, 170, 154";
      ctx.beginPath();
      ctx.fillStyle = `rgba(${hue}, ${alpha})`;
      ctx.arc(point.screenX, point.screenY, radius, 0, Math.PI * 2);
      ctx.fill();
    }
    requestAnimationFrame(draw);
  };

  resize();
  window.addEventListener("resize", resize, { passive: true });
  requestAnimationFrame(draw);
}
