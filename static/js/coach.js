// Weekly coach (Phase 6, riyaz/coach.py). The Progress page shows "This week": a summary from
// simple rules (no download, no network). When the user turns on the local coach in Settings
// and Ollama runs on this Mac, "Ask the coach" adds the coach's own words. When Ollama is not
// there, the page says "The coach is not running." The app works the same without it.

const $ = (id) => document.getElementById(id);

export class WeekCard {
  constructor({ api, terms }) {
    this.api = api;
    this.terms = terms;
    $("pg-coach-btn").addEventListener("click", () => this.ask());
  }

  _html(t) { return this.terms ? this.terms.markup(t) : t; }

  _fill(rule) {
    $("pg-week-title").textContent = rule.title;
    $("pg-week-lines").innerHTML = rule.lines.map((l) => `<li>${this._html(l)}</li>`).join("");
    $("pg-week-tips").innerHTML = rule.tips.length
      ? rule.tips.map((l) => `<li>${this._html(l)}</li>`).join("") : "<li class=\"muted\">No tips this week. Good work.</li>";
  }

  async show() {
    try {
      const w = await this.api("/api/coach/week");
      this._fill(w.rule);
      $("pg-coach-btn").classList.toggle("hidden", !w.settings.enabled);
      $("pg-coach").classList.add("hidden");
    } catch { /* the next visit shows it */ }
  }

  async ask() {
    const btn = $("pg-coach-btn");
    btn.disabled = true;
    btn.textContent = "The coach writes...";
    $("pg-coach").classList.remove("hidden");
    $("pg-coach-text").textContent = "Wait a moment.";
    try {
      const w = await this.api("/api/coach/summary", {});
      this._fill(w.rule);
      $("pg-coach-text").textContent = w.coach === "ok" ? w.llm : (w.coach_text || "The coach is not running.");
    } catch (err) {
      $("pg-coach-text").textContent = err.message;
    }
    btn.disabled = false;
    btn.textContent = "Ask the coach";
  }
}

// Settings: the local coach switch (off by default) and the model name.
export function bindCoachSettings(api) {
  const load = async () => {
    const st = await api("/api/settings/coach").catch(() => null);
    if (!st) return;
    $("set-coach").checked = st.enabled;
    $("set-coach-model").value = st.model;
    $("set-coach-status").textContent = st.enabled ? "" : "The coach is off.";
  };
  $("set-coach").addEventListener("change", async (e) => {
    await api("/api/settings/coach", { enabled: e.target.checked }).catch(() => {});
    load();
  });
  $("set-coach-model").addEventListener("change", async (e) => {
    await api("/api/settings/coach", { model: e.target.value }).catch(() => {});
    load();
  });
  $("set-coach-check").addEventListener("click", async () => {
    const out = $("set-coach-status");
    out.textContent = "The app looks for the coach...";
    const st = await api("/api/coach/status").catch(() => null);
    if (!st) { out.textContent = "The app cannot check the coach now."; return; }
    if (!st.enabled) out.textContent = "The coach is off. Turn on the switch first.";
    else if (!st.running) out.textContent = "The coach is not running. Start Ollama on this Mac.";
    else if (!st.model_ok) out.textContent = `Ollama runs, but it has no model ${st.model}.`;
    else out.textContent = "The coach is ready.";
  });
  return load;
}
