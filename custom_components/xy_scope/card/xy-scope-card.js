// XY Scope card: the scope's live trace on a dashboard.
//
// Drawn from the box's own planned frame, fetched through Home Assistant
// (GET /api/xy_scope/frame), never a JS copy of the figure maths. Density is
// brightness: consecutive samples are joined with additive segments, so where
// the planner packs samples close the trace glows and the jumps between
// strokes -- drawn dim -- stay faint, the trade being made on the tube.
//
//   type: custom:xy-scope-card
//   entity: select.xy_scope_screen   # optional with one display
//   fps: 8                           # optional, 1-15

const GREEN = "80,255,130";

class XyScopeCard extends HTMLElement {
  static getStubConfig(hass) {
    const entity = Object.keys(hass.states)
      .find((id) => id.startsWith("select.xy_scope"));
    return entity ? { entity } : {};
  }

  setConfig(config) {
    const fps = Number(config.fps ?? 8);
    this._config = { ...config, fps: Math.min(15, Math.max(1, fps || 8)) };
    this._restart();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._canvas) this._build();
  }

  getCardSize() { return 4; }

  getGridOptions() { return { columns: 6, rows: 4, min_columns: 3, min_rows: 2 }; }

  connectedCallback() {
    this._live = true;
    this._visible = () => this._restart();
    document.addEventListener("visibilitychange", this._visible);
    this._restart();
  }

  disconnectedCallback() {
    this._live = false;
    document.removeEventListener("visibilitychange", this._visible);
    this._restart();
  }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        ha-card { overflow: hidden; background: #040805; cursor: pointer; }
        .wrap { position: relative; padding: 8px; }
        canvas { display: block; width: 100%; }
        .note { position: absolute; inset: 0; display: flex; align-items: center;
                justify-content: center; color: rgba(${GREEN},0.6);
                font: 500 14px var(--ha-font-family-body, sans-serif); }
        .note:empty { display: none; }
      </style>
      <ha-card><div class="wrap"><canvas></canvas><div class="note"></div></div></ha-card>`;
    this._canvas = root.querySelector("canvas");
    this._note = root.querySelector(".note");
    // Tap for the screen picker: the select's more-info dialog.
    root.querySelector("ha-card").addEventListener("click", () => {
      const entityId = this._entity();
      if (!entityId) return;
      this.dispatchEvent(new CustomEvent("hass-more-info", {
        bubbles: true, composed: true, detail: { entityId } }));
    });
    new ResizeObserver(() => this._draw()).observe(this._canvas.parentElement);
    this._restart();
  }

  _entity() {
    if (this._config?.entity) return this._config.entity;
    return Object.keys(this._hass?.states ?? {})
      .find((id) => id.startsWith("select.xy_scope"));
  }

  // One timer, running only while the card is on screen and the tab is
  // visible: every poll makes the box plan an extra frame.
  _restart() {
    clearInterval(this._timer);
    this._timer = null;
    if (this._live && this._canvas && this._config && !document.hidden) {
      this._poll();
      this._timer = setInterval(() => this._poll(), 1000 / this._config.fps);
    }
  }

  async _poll() {
    if (this._busy || !this._hass) return;
    this._busy = true;
    const entityId = this._config.entity;
    const query = entityId ? `?entity_id=${encodeURIComponent(entityId)}` : "";
    try {
      this._frame = await this._hass.callApi("GET", `xy_scope/frame${query}`);
      this._error = null;
    } catch (err) {
      this._error = err?.body?.message || err?.message || "Display unreachable";
    } finally {
      this._busy = false;
    }
    this._draw();
  }

  _draw() {
    const cv = this._canvas;
    if (!cv) return;
    const f = this._frame;
    // The tube as calibrated: what every figure fills at 100%.
    const h = f?.max_scale || 1;
    const w = Math.min(1, h * (f?.aspect || 1));
    const dpr = window.devicePixelRatio || 1;
    const cssW = cv.parentElement.clientWidth - 16;
    if (cssW <= 0) return;
    cv.style.height = `${cssW * h / w}px`;
    cv.width = Math.round(cssW * dpr);
    cv.height = Math.round(cssW * h / w * dpr);
    const W = cv.width, H = cv.height;
    const cx = cv.getContext("2d");
    cx.clearRect(0, 0, W, H);

    const stale = this._error || !f?.playing;
    this._note.textContent = this._error ? this._error
      : f && !f.playing ? "Not playing" : "";
    if (!f?.pts?.length) return;

    const map = (x, y) => [(x + w) / (2 * w) * W, (h - y) / (2 * h) * H];
    const jump = new Set(f.jumps);
    const p = f.pts, n = p.length / 2;
    const lit = stale ? 0.15 : 0.5;
    cx.globalCompositeOperation = "lighter";
    cx.lineCap = "round";
    for (let i = 0; i < n - 1; i++) {
      const [ax, ay] = map(p[2 * i], p[2 * i + 1]);
      const [bx, by] = map(p[2 * i + 2], p[2 * i + 3]);
      const isJump = jump.has(i + 1);
      cx.strokeStyle = `rgba(${GREEN},${isJump ? 0.07 : lit})`;
      cx.lineWidth = (isJump ? 1 : 1.6) * dpr;
      cx.beginPath();
      cx.moveTo(ax, ay);
      cx.lineTo(bx, by);
      cx.stroke();
    }
  }
}

customElements.define("xy-scope-card", XyScopeCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "xy-scope-card",
  name: "XY Scope",
  description: "The oscilloscope display's live trace. Tap it to change the screen.",
  preview: true,
});
