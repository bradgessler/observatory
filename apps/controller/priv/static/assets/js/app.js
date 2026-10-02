// JavaScript budget: every hook here exists because the browser will not hand
// the behaviour to the server any other way. Everything else is LiveView.
//   Stick     touch-and-pull with a heartbeat (no pointer bindings in LiveView; safety)
//   SkyZoom   pinch-to-zoom is a gesture; the map itself is server-rendered SVG
//   SkyPhoto  reads pixels from a photo on the phone (candidate to move server-side)
//   Geo       the browser only gives location to JS
//   Clock     the phone's own clock, time zone and daylight saving are only known to
//             the browser; sent once, so the server can say what a hand controller
//             wants and set a box's clock that has no internet time
//   Hls       video playback; loads hls.js lazily where <video> can't play HLS itself
//   Terminal  a shell's output is a byte stream of cursor moves, redraws and colour,
//             and its input is raw keys (Ctrl-C, a password that must not echo). Only
//             a terminal emulator draws that; xterm.js is vendored and loaded on first use
//   Awake     the screen wake lock is a browser API: a phone at the eyepiece
//             shouldn't go dark while a hand is on the pad, and only the page
//             can ask the phone for that
//   ⌘K       Search opens itself (a popover) on ⌘K, Ctrl-K or "/": a page can't stop
//             the browser's own ⌘K/Ctrl-K (focus the address bar) without
//             preventDefault, and "/" has to be ignored while typing in a field,
//             which only the browser knows. Not a hook: a listener on the window
// Arrow keys use phx-window-keydown/keyup, not a hook.

// No bundler: phoenix.min.js and phoenix_live_view.min.js are loaded from
// /vendor and expose the `Phoenix` and `LiveView` globals.

const Hooks = {};

// Terminal: the shell lives on the server, in a real pseudo-terminal; this only
// draws it and hands over keys. Bytes arrive base64-encoded, because a terminal
// stream is not always valid UTF-8 and JSON has to be. Keys go up as "keys",
// the one parameter the server's log is told never to print.
Hooks.Terminal = {
  mounted() {
    const base = "/assets/vendor/xterm/";
    const load = (tag, attrs) =>
      new Promise((ok, no) => {
        const el = Object.assign(document.createElement(tag), attrs);
        el.onload = ok;
        el.onerror = no;
        document.head.appendChild(el);
      });

    const ready = window.Terminal
      ? Promise.resolve()
      : Promise.all([
          load("link", { rel: "stylesheet", href: base + "xterm.css" }),
          load("script", { src: base + "xterm.js" }),
        ]);

    ready.then(() => {
      // One shell, one size, for every viewer: 120 columns, whatever the
      // window. Sized to the window, it came out 36 wide on a phone and 66 on
      // this page, and fwup's 76-column progress line wrapped, so each \r
      // redrew only the wrapped tail and left a line behind per percent. A
      // narrow screen scrolls sideways instead; the percentage is at the left.
      const term = new window.Terminal({
        cols: 120,
        rows: 30,
        cursorBlink: true,
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        fontSize: 13,
        theme: { background: "#000000" },
      });
      term.open(this.el);
      this.term = term;

      this.handleEvent("term_output", ({ data }) => {
        term.write(Uint8Array.from(atob(data), (c) => c.charCodeAt(0)));
      });

      // Keys always go up and the server decides whether to take them: who may
      // type can change while the page is open, and the browser is not the
      // place that decision is enforced.
      term.onData((keys) => this.pushEvent("term_input", { keys }));
      if (this.el.dataset.canType === "true") term.focus();

      this.pushEvent("term_open", { cols: term.cols, rows: term.rows });
    });
  },

  destroyed() {
    if (this.term) this.term.dispose();
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


// The stick: touch anywhere on the pad, pull to move. The vector from the
// touch-down point sets direction; distance sets speed (server maps it on a
// log scale). Re-sent every 250 ms while held so the mount's deadman stays
// fed; letting go (or the page hiding) sends stick_end. Mouse works the same.
Hooks.Stick = {
  mounted() {
    const pad = this.el, knob = pad.querySelector("[data-knob]");
    // Fixed mode: a plain button with data-dir. Hold = send that direction at
    // full magnitude every 250 ms; release = stick_end. No knob, no drag.
    if (pad.dataset.dir) {
      const v = { up: [0, 1], down: [0, -1], left: [-1, 0], right: [1, 0] }[pad.dataset.dir] || [0, 0];
      let timer = null, id = null;
      const send = () => this.pushEvent("stick", { x: v[0], y: v[1], mag: 1 });
      const start = (e) => { if (timer) return; e.preventDefault(); id = e.pointerId; pad.classList.add("pressed"); send(); timer = setInterval(send, 250); };
      const stop = (e) => { if (!timer) return; if (e && e.pointerId !== undefined && e.pointerId !== id) return; clearInterval(timer); timer = null; pad.classList.remove("pressed"); this.pushEvent("stick_end", {}); };
      pad.addEventListener("pointerdown", start);
      pad.addEventListener("pointerup", stop);
      pad.addEventListener("pointercancel", stop);
      pad.addEventListener("pointerleave", stop);
      pad.addEventListener("contextmenu", (e) => e.preventDefault());
      window.addEventListener("blur", () => stop());
      document.addEventListener("visibilitychange", () => document.hidden && stop());
      this.end = stop;
      return;
    }
    const lockX = pad.dataset.lock === "x";          // a strip: horizontal pull only
    const axis = pad.dataset.axis || null;           // which mount axis a strip drives
    // data-origin="touch": zero is where the thumb lands, not the pad's centre
    // (an eye at the eyepiece can't see where the centre is); data-reach is
    // the pull in px for full speed, data-dead the still zone as a share of it
    const fromTouch = pad.dataset.origin === "touch";
    const reach = Number(pad.dataset.reach) || 0, deadShare = Number(pad.dataset.dead) || 0.12;
    const R = () => reach || (lockX ? pad.getBoundingClientRect().width / 2 - 28 : pad.getBoundingClientRect().width / 2);
    let origin = null, at = { x: 0, y: 0 }, vec = { x: 0, y: 0, mag: 0 }, timer = null, active = null;
    const show = (dx, dy) => { knob.style.transform = `translate(${at.x + dx}px, ${at.y + dy}px)`; knob.classList.toggle("live", !!origin); };
    const send = () => this.pushEvent("stick", vec);
    const update = (cx, cy) => {
      const r = R(), dead = r * deadShare;
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
      const centre = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
      origin = fromTouch ? { x: e.clientX, y: e.clientY } : centre;
      at = { x: origin.x - centre.x, y: origin.y - centre.y };
      update(e.clientX, e.clientY);
      send();
      timer = setInterval(send, 250);
      try { navigator.vibrate && navigator.vibrate(6); } catch (_) {}
    };
    // the 250 ms interval carries the latest vector; pushing on every
    // pointermove (60-120 Hz) floods the server and stale reports outlive the release
    const move = (e) => { if (e.pointerId !== active) return; e.preventDefault(); update(e.clientX, e.clientY); };
    const end = (e) => {
      if (active === null || (e && e.pointerId !== undefined && e.pointerId !== active)) return;
      clearInterval(timer); timer = null; active = null; origin = null;
      at = { x: 0, y: 0 };
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
    // the chart's own frame, from the server (each projection has its own shape)
    const parse = () => (svg.dataset.base || svg.getAttribute("viewBox")).trim().split(/\s+/).map(Number);
    let base = parse();
    let vb = [...base];
    const pts = new Map();
    let pinch = null, moved = false;
    const apply = () => svg.setAttribute("viewBox", vb.join(" "));
    const clamp = () => {
      vb[2] = Math.min(base[2], Math.max(base[2] / 13, vb[2]));
      vb[3] = vb[2] * base[3] / base[2];
      vb[0] = Math.max(base[0], Math.min(base[0] + base[2] - vb[2], vb[0]));
      vb[1] = Math.max(base[1], Math.min(base[1] + base[3] - vb[3], vb[1]));
    };
    const toSvg = (x, y) => {
      const r = svg.getBoundingClientRect();
      return [vb[0] + (x - r.left) / r.width * vb[2], vb[1] + (y - r.top) / r.height * vb[3]];
    };
    const zoomAt = (cx, cy, f) => {
      const [sx, sy] = toSvg(cx, cy);
      const w = Math.min(base[2], Math.max(base[2] / 13, vb[2] * f));
      const s = w / vb[2];
      vb = [sx - (sx - vb[0]) * s, sy - (sy - vb[1]) * s, w, w * base[3] / base[2]];
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
    // keep our zoom across LiveView patches; a different chart (another projection) starts unzoomed
    this.rebase = () => {
      const b = parse();
      if (b.join(" ") !== base.join(" ")) { base = b; vb = [...base]; }
      apply();
    };
  },
  updated() { this.rebase && this.rebase(); },
};


// HLS playback. Safari plays it natively in <video>; every other browser
// needs hls.js, which is the one library we ship — loaded only when a
// stream is actually on screen and the browser can't do it alone. The
// server sets data-src once the playlist exists; clearing it stops playback.
// Picture-in-picture must survive leaving the page: when the element is torn
// down by navigation while it is the PiP video, it is parked (hidden) on
// <body>, outside anything LiveView patches, and keeps playing until PiP ends.
const inPip = (v) => document.pictureInPictureElement === v || v.webkitPresentationMode === "picture-in-picture";
const parkPip = (v, hls) => {
  v.id = "video-feed-pip";
  v.style.cssText = "position:fixed;left:-9999px;top:0;width:2px;height:2px;opacity:0;pointer-events:none";
  document.body.appendChild(v);
  window.__pip = v;
  const done = () => { if (inPip(v)) return; if (hls) hls.destroy(); v.remove(); if (window.__pip === v) window.__pip = null; };
  v.addEventListener("leavepictureinpicture", done);
  v.addEventListener("webkitpresentationmodechanged", () => setTimeout(done, 0));
};
const unparkPip = () => { const v = window.__pip; if (!v) return; try { document.exitPictureInPicture && document.exitPictureInPicture(); } catch (_) {} v.remove(); window.__pip = null; };

Hooks.Hls = {
  mounted() { this.attach(); },
  updated() { if (this.el.dataset.src !== this.src) this.attach(); },
  destroyed() { this.leaving = true; this.detach(); },
  detach() {
    if (this.tele) { clearInterval(this.tele); this.tele = null; }
    if (this.leaving && inPip(this.el)) { parkPip(this.el, this.hls); this.hls = null; return; }
    if (this.hls) { this.hls.destroy(); this.hls = null; }
    this.el.removeAttribute("src"); this.el.load && this.el.load();
  },
  // Once a second: how far behind reality this picture is, and the frame rate
  // actually being decoded here. Latency comes from the segments' wall-clock
  // stamps (hls.js exposes it; Safari gives getStartDate) — exact, assuming
  // the clocks agree. Without a stamp we only know the distance to the live
  // edge, reported as a lower bound.
  telemetry() {
    const v = this.el;
    let frames = null, t0 = performance.now();
    this.tele = setInterval(() => {
      let fps = null;
      const q = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : null;
      const now = performance.now();
      if (q) { if (frames !== null) fps = (q.totalVideoFrames - frames) / ((now - t0) / 1000); frames = q.totalVideoFrames; t0 = now; }
      let latency = null, exact = false;
      if (this.hls && Number.isFinite(this.hls.latency) && this.hls.latency > 0) { latency = this.hls.latency; exact = true; }
      else if (v.getStartDate) { const sd = v.getStartDate(); if (sd && !isNaN(sd.getTime())) { latency = (Date.now() - (sd.getTime() + v.currentTime * 1000)) / 1000; exact = true; } }
      if (latency === null && v.seekable && v.seekable.length) latency = Math.max(0, v.seekable.end(v.seekable.length - 1) - v.currentTime);
      this.pushEvent("telemetry", { latency, exact, fps: fps === null ? null : Math.round(fps), paused: v.paused });
    }, 1000);
  },
  attach() {
    const v = this.el, src = v.dataset.src;
    this.detach();
    this.src = src;
    // the stream was stopped: a parked PiP player has nothing left to play
    if (!src) { unparkPip(); return; }
    if (v.canPlayType("application/vnd.apple.mpegurl")) { v.src = src; v.play().catch(() => {}); this.telemetry(); return; }
    const go = () => {
      if (!window.Hls || !window.Hls.isSupported()) { this.pushEvent("player", { state: "unsupported" }); return; }
      this.hls = new window.Hls({ liveSyncDurationCount: 3, enableWorker: true });
      this.hls.on(window.Hls.Events.ERROR, (_, d) => { if (d.fatal) this.pushEvent("player", { state: "error", detail: d.details }); });
      this.hls.loadSource(src);
      this.hls.attachMedia(v);
      v.play().catch(() => {});
      this.telemetry();
    };
    if (window.Hls) return go();
    const s = document.createElement("script");
    s.src = "/vendor/hls/hls.min.js"; s.onload = go; s.onerror = () => this.pushEvent("player", { state: "noscript" });
    document.head.appendChild(s);
  },
};

// "Use my location": ask the browser once, hand lat/lon to the server.
// Clock: once, on connect. The standard offset is the one of January and July
// that is further behind UTC, so daylight saving reads right in either hemisphere.
// Awake: a button that keeps this phone's screen on (and says so) until it is
// tapped again or the page goes away. The phone drops the lock whenever the
// page is hidden; it is taken again when the page comes back. A phone that
// can't do it says so on the button, and nothing else changes.
Hooks.Awake = {
  mounted() {
    this.on = false;
    this.lock = null;
    this.label = this.el.textContent.trim();
    if (!("wakeLock" in navigator)) {
      this.el.disabled = true;
      this.el.textContent = "Screen Lock Not Supported Here";
      return;
    }
    this.take = async () => {
      try {
        this.lock = await navigator.wakeLock.request("screen");
      } catch (e) {
        this.on = false;
        this.show();
      }
    };
    this.show = () => {
      this.el.setAttribute("aria-pressed", String(this.on));
      this.el.textContent = this.on ? "Screen Stays On" : this.label;
    };
    this.el.addEventListener("click", async () => {
      this.on = !this.on;
      if (this.on) await this.take();
      else if (this.lock) { this.lock.release(); this.lock = null; }
      this.show();
    });
    this.visible = () => { if (this.on && document.visibilityState === "visible") this.take(); };
    document.addEventListener("visibilitychange", this.visible);
  },
  // LiveView re-renders the button: keep what it says
  updated() { if (this.show) this.show(); },
  destroyed() {
    if (this.visible) document.removeEventListener("visibilitychange", this.visible);
    if (this.lock) this.lock.release();
  },
};

Hooks.Clock = {
  mounted() {
    const now = new Date();
    const year = now.getFullYear();
    const jan = new Date(year, 0, 1).getTimezoneOffset();
    const jul = new Date(year, 6, 1).getTimezoneOffset();
    let tz = "";
    try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (_) {}
    this.pushEvent("clock", { now_ms: Date.now(), tz: tz, offset_min: -now.getTimezoneOffset(), std_offset_min: -Math.max(jan, jul) });
  },
};

Hooks.Geo = {
  mounted() {
    this.el.addEventListener("click", () => {
      // browsers give location only to https pages; a box serves http
      if (!window.isSecureContext) { this.pushEvent("site_error", { reason: "insecure" }); return; }
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
// On a weak link (a phone at the edge of the box's Wi-Fi) one of the scripts
// loaded before this one can fail to arrive, and then nothing on the page
// works while it looks fine. Seen in the VM: phoenix.min.js dropped, every key
// dead, no sign why. Reload once; if the second try fails too, say so.
if (!window.Phoenix || !window.LiveView) {
  let retried = false;
  try { retried = sessionStorage.getItem("obs-reloaded") === "1"; sessionStorage.setItem("obs-reloaded", "1"); } catch (_) {}

  if (!retried) {
    location.reload();
  } else {
    const p = Object.assign(document.createElement("p"), { className: "notice", textContent: "The page did not finish loading. Reload to try again." });
    p.setAttribute("role", "status");
    document.body.appendChild(p);
  }
} else {
  try { sessionStorage.removeItem("obs-reloaded"); } catch (_) {}

  const liveSocket = new LiveView.LiveSocket("/live", Phoenix.Socket, {
    hooks: Hooks,
    params: { _csrf_token: csrfToken },
  });
  liveSocket.connect();
  window.liveSocket = liveSocket;

  // ⌘K (Ctrl-K, or "/" when not typing): open Search, fresh. The popover does
  // the rest (focus, Escape, a tap outside); see Controller.Spotlight.
  window.addEventListener("keydown", (e) => {
    const box = document.getElementById("spotlight");
    if (!box || !box.showPopover) return;
    const t = e.target;
    const typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
    const chord = (e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === "k";
    if (!chord && !(e.key === "/" && !typing && !e.metaKey && !e.ctrlKey && !e.altKey)) return;
    e.preventDefault();
    if (box.matches(":popover-open")) { box.hidePopover(); return; }
    liveSocket.execJS(box, '[["push",{"event":"reset","target":"#spotlight"}]]');
    box.showPopover();
  });
}
