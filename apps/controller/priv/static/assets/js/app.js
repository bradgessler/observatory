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

const csrfToken = document.querySelector("meta[name='csrf-token']").getAttribute("content");
const liveSocket = new LiveView.LiveSocket("/live", Phoenix.Socket, {
  hooks: Hooks,
  params: { _csrf_token: csrfToken },
});
liveSocket.connect();
window.liveSocket = liveSocket;
