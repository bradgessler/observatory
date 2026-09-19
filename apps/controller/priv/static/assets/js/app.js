// No bundler: phoenix.min.js and phoenix_live_view.min.js are loaded from
// /vendor and expose the `Phoenix` and `LiveView` globals.

const Hooks = {};

// Press-and-hold slew. Pushes "hold" on pointerdown and every 300 ms while
// held; the server's deadman stops the axis if it hasn't heard from us within
// 900 ms, so a dropped connection can't leave the mount running.
Hooks.Hold = {
  mounted() {
    const axis = this.el.dataset.axis;
    const dir = this.el.dataset.dir;
    let timer = null;

    const start = (e) => {
      e.preventDefault();
      if (timer) return;
      this.el.classList.add("pressed");
      this.pushEvent("hold", { axis, dir });
      timer = setInterval(() => this.pushEvent("hold", { axis, dir }), 300);
      try { navigator.vibrate && navigator.vibrate(8); } catch (_) {}
    };

    const stop = (e) => {
      if (!timer) return;
      e && e.preventDefault();
      clearInterval(timer);
      timer = null;
      this.el.classList.remove("pressed");
      this.pushEvent("release", { axis });
    };

    this.el.addEventListener("pointerdown", start);
    this.el.addEventListener("pointerup", stop);
    this.el.addEventListener("pointercancel", stop);
    this.el.addEventListener("pointerleave", stop);
    this.el.addEventListener("contextmenu", (e) => e.preventDefault());
    window.addEventListener("blur", stop);
    document.addEventListener("visibilitychange", () => document.hidden && stop());
    this.stop = stop;
  },
  destroyed() { this.stop && this.stop(); },
};

// Arrow keys on a laptop behave like the D-pad; space is STOP.
Hooks.Keys = {
  mounted() {
    const down = new Set();
    window.addEventListener("keydown", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
      if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " "].includes(e.key)) return;
      e.preventDefault();
      if (e.key !== " " && down.has(e.key)) return; // ignore auto-repeat; hold timer covers it
      down.add(e.key);
      this.pushEvent("key", { key: e.key, type: "down" });
      if (e.key !== " ") this.timers = this.timers || {};
      if (e.key !== " " && !this.timers[e.key]) {
        this.timers[e.key] = setInterval(() => this.pushEvent("key", { key: e.key, type: "down" }), 300);
      }
    });
    window.addEventListener("keyup", (e) => {
      if (!down.has(e.key)) return;
      down.delete(e.key);
      if (this.timers && this.timers[e.key]) { clearInterval(this.timers[e.key]); delete this.timers[e.key]; }
      this.pushEvent("key", { key: e.key, type: "up" });
    });
  },
};


// Sky photo: trace where the sky stops in each column (bright sky above,
// dark trees/houses below) right here in the browser, then hand the boundary
// to the server. The server plate-solves the same photo to turn columns into
// compass directions and rows into altitude.
Hooks.SkyPhoto = {
  mounted() {
    const input = this.el.querySelector("input[type=file]");
    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      if (!file) return;
      const img = new Image();
      img.onload = () => {
        const W = 96, H = 64;
        const c = document.createElement("canvas");
        c.width = W; c.height = H;
        const ctx = c.getContext("2d");
        ctx.drawImage(img, 0, 0, W, H);
        const d = ctx.getImageData(0, 0, W, H).data;
        const lum = (x, y) => { const i = (y * W + x) * 4; return 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]; };
        // sky brightness reference: median of the top 15% of rows
        const top = [];
        for (let y = 0; y < Math.floor(H * 0.15); y++) for (let x = 0; x < W; x++) top.push(lum(x, y));
        top.sort((a, b) => a - b);
        const sky = top[Math.floor(top.length / 2)];
        const all = [];
        for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) all.push(lum(x, y));
        all.sort((a, b) => a - b);
        const dark = all[Math.floor(all.length * 0.1)];
        const thresh = dark + (sky - dark) * 0.45;
        const cols = [];
        for (let x = 0; x < W; x++) {
          // walk down from the top; the first run of 3 dark rows is the boundary
          let yb = H;
          for (let y = 0; y < H - 2; y++) {
            if (lum(x, y) < thresh && lum(x, y + 1) < thresh && lum(x, y + 2) < thresh) { yb = y; break; }
          }
          cols.push([(x + 0.5) / W, yb / H]);
        }
        this.pushEvent("photo_cols", { cols, width: img.naturalWidth, height: img.naturalHeight, sky, dark });
      };
      img.src = URL.createObjectURL(file);
    });
  },
};


// Pinch to zoom / drag to pan the sky map by driving the SVG viewBox.
// Wheel zooms on a desktop; double-tap or double-click resets. A tap without
// movement still reaches the object underneath (pick) or the dome (clear).
Hooks.SkyZoom = {
  mounted() {
    const svg = this.el;
    const base = [-104, -104, 208, 208];
    let vb = [...base];
    const pts = new Map();
    let pinch = null, moved = false;
    const apply = () => svg.setAttribute("viewBox", vb.join(" "));
    const clamp = () => {
      vb[2] = vb[3] = Math.min(base[2], Math.max(16, vb[2]));
      vb[0] = Math.max(base[0], Math.min(base[0] + base[2] - vb[2], vb[0]));
      vb[1] = Math.max(base[1], Math.min(base[1] + base[3] - vb[3], vb[1]));
    };
    const toSvg = (x, y) => {
      const r = svg.getBoundingClientRect();
      return [vb[0] + (x - r.left) / r.width * vb[2], vb[1] + (y - r.top) / r.height * vb[3]];
    };
    const zoomAt = (cx, cy, f) => {
      const [sx, sy] = toSvg(cx, cy);
      const w = Math.min(base[2], Math.max(16, vb[2] * f));
      const s = w / vb[2];
      vb = [sx - (sx - vb[0]) * s, sy - (sy - vb[1]) * s, w, w];
      clamp(); apply();
    };
    const pinchState = () => {
      const [a, b] = [...pts.values()];
      return { d: Math.hypot(a[0] - b[0], a[1] - b[1]), cx: (a[0] + b[0]) / 2, cy: (a[1] + b[1]) / 2 };
    };
    svg.style.touchAction = "none";
    svg.addEventListener("pointerdown", (e) => {
      pts.set(e.pointerId, [e.clientX, e.clientY]);
      moved = false;
      if (pts.size === 2) pinch = pinchState();
    });
    const move = (e) => {
      if (!pts.has(e.pointerId)) return;
      const prev = pts.get(e.pointerId);
      pts.set(e.pointerId, [e.clientX, e.clientY]);
      if (pts.size === 1) {
        if (vb[2] >= base[2]) return;                 // not zoomed: nothing to pan
        const dx = e.clientX - prev[0], dy = e.clientY - prev[1];
        if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
        const r = svg.getBoundingClientRect();
        vb[0] -= dx / r.width * vb[2];
        vb[1] -= dy / r.height * vb[3];
        clamp(); apply();
      } else if (pts.size === 2) {
        moved = true;
        const now = pinchState();
        if (pinch && now.d > 0) zoomAt(now.cx, now.cy, pinch.d / now.d);
        pinch = now;
      }
    };
    const up = (e) => { pts.delete(e.pointerId); if (pts.size < 2) pinch = null; };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    // swallow the click that follows a drag/pinch so it doesn't pick or clear
    svg.addEventListener("click", (e) => { if (moved) { e.stopPropagation(); e.preventDefault(); moved = false; } }, true);
    svg.addEventListener("wheel", (e) => { e.preventDefault(); zoomAt(e.clientX, e.clientY, e.deltaY > 0 ? 1.15 : 0.87); }, { passive: false });
    svg.addEventListener("dblclick", (e) => { e.preventDefault(); vb = [...base]; apply(); });
    // keep our zoom across LiveView patches
    this.apply = apply;
  },
  updated() { this.apply && this.apply(); },
};


// "Use my location": ask the browser once, hand lat/lon to the server.
Hooks.Geo = {
  mounted() {
    this.el.addEventListener("click", () => {
      if (!navigator.geolocation) { this.pushEvent("site_error", { reason: "no geolocation in this browser" }); return; }
      this.el.disabled = true;
      navigator.geolocation.getCurrentPosition(
        (pos) => { this.el.disabled = false; this.pushEvent("site", { lat: pos.coords.latitude, lon: pos.coords.longitude, accuracy: pos.coords.accuracy }); },
        (err) => { this.el.disabled = false; this.pushEvent("site_error", { reason: err.message }); },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 }
      );
    });
  },
};

const csrfToken = document.querySelector("meta[name='csrf-token']").getAttribute("content");
const liveSocket = new LiveView.LiveSocket("/live", Phoenix.Socket, {
  hooks: Hooks,
  params: { _csrf_token: csrfToken },
});
liveSocket.connect();
window.liveSocket = liveSocket;
