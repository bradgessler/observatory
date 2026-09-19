// JavaScript budget: every hook here exists because the browser will not hand
// the behaviour to the server any other way. Everything else is LiveView.
//   Stick     touch-and-pull with a heartbeat (no pointer bindings in LiveView; safety)
//   SkyZoom   pinch-to-zoom is a gesture; the map itself is server-rendered SVG
//   SkyPhoto  reads pixels from a photo on the phone (candidate to move server-side)
//   Geo       the browser only gives location to JS
// Arrow keys use phx-window-keydown/keyup, not a hook.

// No bundler: phoenix.min.js and phoenix_live_view.min.js are loaded from
// /vendor and expose the `Phoenix` and `LiveView` globals.

const Hooks = {};




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


// The stick: touch anywhere on the pad, pull to move. The vector from the
// touch-down point sets direction; distance sets speed (server maps it on a
// log scale). Re-sent every 250 ms while held so the mount's deadman stays
// fed; letting go (or the page hiding) sends stick_end. Mouse works the same.
Hooks.Stick = {
  mounted() {
    const pad = this.el, knob = pad.querySelector("[data-knob]");
    const lockX = pad.dataset.lock === "x";          // a strip: horizontal pull only
    const axis = pad.dataset.axis || null;           // which mount axis a strip drives
    const R = () => (lockX ? pad.getBoundingClientRect().width / 2 - 28 : pad.getBoundingClientRect().width / 2);
    let origin = null, vec = { x: 0, y: 0, mag: 0 }, timer = null, active = null;
    const show = (dx, dy) => { knob.style.transform = `translate(${dx}px, ${dy}px)`; knob.classList.toggle("live", !!origin); };
    const send = () => this.pushEvent("stick", vec);
    const update = (cx, cy) => {
      const r = R(), dead = r * 0.12;
      let dx = cx - origin.x, dy = lockX ? 0 : cy - origin.y;
      const d = Math.hypot(dx, dy);
      if (d > r) { dx *= r / d; dy *= r / d; }
      const dist = Math.min(d, r);
      const mag = dist <= dead ? 0 : (dist - dead) / (r - dead);
      vec = { x: dist > 0 ? dx / Math.max(dist, 1e-6) : 0, y: dist > 0 ? -dy / Math.max(dist, 1e-6) : 0, mag };
      if (axis) vec.axis = axis;
      show(dx, dy);
    };
    const start = (e) => {
      if (active !== null) return;
      e.preventDefault();
      active = e.pointerId;
      pad.setPointerCapture(active);
      const rect = pad.getBoundingClientRect();
      origin = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
      update(e.clientX, e.clientY);
      send();
      timer = setInterval(send, 250);
      try { navigator.vibrate && navigator.vibrate(6); } catch (_) {}
    };
    const move = (e) => { if (e.pointerId !== active) return; e.preventDefault(); update(e.clientX, e.clientY); send(); };
    const end = (e) => {
      if (active === null || (e && e.pointerId !== undefined && e.pointerId !== active)) return;
      clearInterval(timer); timer = null; active = null; origin = null;
      show(0, 0);
      this.pushEvent("stick_end", {});
    };
    pad.addEventListener("pointerdown", start);
    pad.addEventListener("pointermove", move);
    pad.addEventListener("pointerup", end);
    pad.addEventListener("pointercancel", end);
    pad.addEventListener("lostpointercapture", end);
    pad.addEventListener("contextmenu", (e) => e.preventDefault());
    window.addEventListener("blur", () => end());
    document.addEventListener("visibilitychange", () => document.hidden && end());
    this.end = end;
  },
  destroyed() { this.end && this.end(); },
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
