/**
 * 全屏图片 Lightbox：Esc 关闭、方向键翻页、点击遮罩关闭。
 */

import { fetchChartImageBlob } from "/assets/js/citation-charts.js?v=chart-p2c";

function revokeBlobUrl(url) {
  const raw = String(url || "").trim();
  if (!raw.startsWith("blob:")) return;
  try {
    URL.revokeObjectURL(raw);
  } catch {
    /* ignore */
  }
}

export class ImageLightbox {
  constructor() {
    this.overlay = null;
    this.imgEl = null;
    this.counterEl = null;
    this.slides = [];
    this.index = 0;
    this.renderGeneration = 0;
    this.keyHandler = null;
  }

  mount() {
    if (this.overlay) return;
    const overlay = document.createElement("div");
    overlay.className = "image-lightbox";
    overlay.hidden = true;
    overlay.innerHTML = `
      <div class="image-lightbox-backdrop" data-lightbox-close></div>
      <div class="image-lightbox-panel" role="dialog" aria-modal="true" aria-label="图表预览">
        <button type="button" class="image-lightbox-close" data-lightbox-close aria-label="关闭">×</button>
        <button type="button" class="image-lightbox-nav image-lightbox-prev" data-lightbox-prev aria-label="上一张">‹</button>
        <div class="image-lightbox-stage">
          <img class="image-lightbox-img" alt="" />
          <div class="image-lightbox-counter"></div>
        </div>
        <button type="button" class="image-lightbox-nav image-lightbox-next" data-lightbox-next aria-label="下一张">›</button>
      </div>`;
    document.body.appendChild(overlay);
    this.overlay = overlay;
    this.imgEl = overlay.querySelector(".image-lightbox-img");
    this.counterEl = overlay.querySelector(".image-lightbox-counter");

    overlay.querySelectorAll("[data-lightbox-close]").forEach((el) => {
      el.addEventListener("click", () => this.close());
    });
    overlay.querySelector("[data-lightbox-prev]")?.addEventListener("click", () => this.step(-1));
    overlay.querySelector("[data-lightbox-next]")?.addEventListener("click", () => this.step(1));
  }

  revokeAllSlideBlobs() {
    for (const slide of this.slides) {
      if (slide?.blobUrl) {
        revokeBlobUrl(slide.blobUrl);
        delete slide.blobUrl;
      }
    }
    if (this.imgEl?.src?.startsWith("blob:")) {
      revokeBlobUrl(this.imgEl.src);
      this.imgEl.removeAttribute("src");
    }
  }

  async open(slides, startIndex = 0) {
    this.mount();
    this.revokeAllSlideBlobs();
    this.slides = Array.isArray(slides) ? slides.filter((s) => s?.path) : [];
    if (!this.slides.length) return;
    this.index = Math.min(Math.max(0, startIndex), this.slides.length - 1);
    this.overlay.hidden = false;
    document.body.classList.add("image-lightbox-open");
    this.bindKeys();
    const gen = ++this.renderGeneration;
    await this.renderCurrent(gen);
  }

  close() {
    if (!this.overlay) return;
    this.overlay.hidden = true;
    document.body.classList.remove("image-lightbox-open");
    this.renderGeneration += 1;
    this.revokeAllSlideBlobs();
    this.unbindKeys();
  }

  bindKeys() {
    if (this.keyHandler) return;
    this.keyHandler = (event) => {
      if (this.overlay?.hidden) return;
      if (event.key === "Escape") {
        event.preventDefault();
        this.close();
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        this.step(-1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        this.step(1);
      }
    };
    document.addEventListener("keydown", this.keyHandler);
  }

  unbindKeys() {
    if (!this.keyHandler) return;
    document.removeEventListener("keydown", this.keyHandler);
    this.keyHandler = null;
  }

  step(delta) {
    if (this.slides.length <= 1) return;
    this.index = (this.index + delta + this.slides.length) % this.slides.length;
    const gen = ++this.renderGeneration;
    void this.renderCurrent(gen);
  }

  async renderCurrent(expectedGen) {
    if (!this.imgEl || !this.slides.length) return;
    const slide = this.slides[this.index];
    const total = this.slides.length;
    if (this.counterEl) {
      this.counterEl.textContent = total > 1 ? `${this.index + 1} / ${total}` : "";
    }
    const prevBtn = this.overlay?.querySelector("[data-lightbox-prev]");
    const nextBtn = this.overlay?.querySelector("[data-lightbox-next]");
    if (prevBtn) prevBtn.hidden = total <= 1;
    if (nextBtn) nextBtn.hidden = total <= 1;

    this.imgEl.alt = slide.alt || "图表";
    this.overlay?.classList.add("is-loading");

    try {
      let src = slide.blobUrl || "";
      if (!src) {
        const blob = await fetchChartImageBlob(slide.path);
        if (expectedGen !== this.renderGeneration) return;
        if (slide.blobUrl) revokeBlobUrl(slide.blobUrl);
        src = URL.createObjectURL(blob);
        slide.blobUrl = src;
      }
      if (expectedGen !== this.renderGeneration) return;
      const prevSrc = this.imgEl.src;
      if (prevSrc && prevSrc.startsWith("blob:") && prevSrc !== src) {
        revokeBlobUrl(prevSrc);
      }
      this.imgEl.src = src;
    } catch {
      if (expectedGen !== this.renderGeneration) return;
      if (this.imgEl.src?.startsWith("blob:")) {
        revokeBlobUrl(this.imgEl.src);
      }
      this.imgEl.removeAttribute("src");
      this.imgEl.alt = (slide.alt || "图表") + "（加载失败）";
    } finally {
      if (expectedGen === this.renderGeneration) {
        this.overlay?.classList.remove("is-loading");
      }
    }
  }
}

export const imageLightbox = new ImageLightbox();
