// WebSocket link to the backend: MIDI events, clock sync, delay reports.
// Clock sync (PLAN 4): ping/pong 5 times, offset = median of (t_server - midpoint).

export class Link {
  constructor() {
    this.handlers = {};
    this.offset = null; // seconds; server_time = client_time + offset
    this._samples = [];
    this._pending = new Map();
    this._pingId = 0;
    this._recv = [];
    this._paint = [];
    this.recentDelays = [];
    this.connect();
  }

  on(type, fn) {
    (this.handlers[type] ||= []).push(fn);
  }

  emit(type, data) {
    for (const fn of this.handlers[type] || []) fn(data);
    for (const fn of this.handlers["*"] || []) fn(data);
  }

  connect() {
    const ws = new WebSocket(`ws://${location.host}/ws`);
    this.ws = ws;
    ws.onopen = () => {
      this.emit("link", { up: true });
      this.syncClock();
      clearInterval(this._syncTimer);
      this._syncTimer = setInterval(() => this.syncClock(), 30000);
    };
    ws.onclose = () => {
      this.emit("link", { up: false });
      clearInterval(this._syncTimer);
      setTimeout(() => this.connect(), 1000);
    };
    ws.onmessage = (ev) => {
      const nowClient = performance.now() / 1000;
      const msg = JSON.parse(ev.data);
      if (msg.type === "pong") return this._onPong(msg, nowClient);
      if (msg.type === "note_on" && this.offset !== null && msg.t !== undefined) {
        this._trackDelay(msg, nowClient);
      }
      this.emit(msg.type, msg);
    };
  }

  send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj));
  }

  serverNow() {
    return this.offset === null ? null : performance.now() / 1000 + this.offset;
  }

  syncClock() {
    this._samples = [];
    for (let i = 0; i < 5; i++) {
      setTimeout(() => {
        const id = ++this._pingId;
        const t = performance.now() / 1000;
        this._pending.set(id, t);
        this.send({ type: "ping", id, t_client: t });
      }, i * 50);
    }
  }

  _onPong(msg, t1) {
    const t0 = this._pending.get(msg.id);
    if (t0 === undefined) return;
    this._pending.delete(msg.id);
    this._samples.push(msg.t_server - (t0 + t1) / 2);
    if (this._samples.length === 5) {
      const s = [...this._samples].sort((a, b) => a - b);
      this.offset = s[2];
    }
  }

  // Delay from the MIDI callback (server stamp) to WebSocket receipt and to the next frame.
  _trackDelay(msg, nowClient) {
    const recvMs = (nowClient + this.offset - msg.t) * 1000;
    this._recv.push(recvMs);
    requestAnimationFrame(() => {
      const paintMs = (performance.now() / 1000 + this.offset - msg.t) * 1000;
      this._paint.push(paintMs);
      this.recentDelays.push(paintMs);
      if (this.recentDelays.length > 50) this.recentDelays.shift();
      if (this._paint.length >= 10) {
        this.send({ type: "latency_report", recv_ms: this._recv, paint_ms: this._paint });
        this._recv = [];
        this._paint = [];
      }
    });
  }

  medianDelay() {
    if (!this.recentDelays.length) return null;
    const s = [...this.recentDelays].sort((a, b) => a - b);
    return s[Math.floor(s.length / 2)];
  }
}
