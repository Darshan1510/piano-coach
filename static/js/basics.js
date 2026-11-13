// Keyboard basics (PLAN 8.1): 3 short steps on the real keyboard. The user can do them again at
// any time (Learn, Words). The texts come from data/course/basics.json.

import { DrillPanel } from "/static/js/drill.js";
import { esc } from "/static/js/terms.js";

const ICON_OK = '<svg class="icon" viewBox="0 0 24 24"><path d="M5 12l5 5 9-10"/></svg>';

export class BasicsScreen {
  constructor({ link, api, piano, terms, reducedMotion, celebrate, onPractice, onDone }) {
    this.api = api;
    this.terms = terms;
    this.celebrate = celebrate;
    this.onPractice = onPractice;
    this.onDone = onDone;
    this.el = document.getElementById("basics-body");
    this.stepsEl = document.getElementById("basics-steps");
    this.panel = new DrillPanel(document.getElementById("basics-drill"), { link, api, piano, reducedMotion });
    this.course = null;
    this.stepId = null;
    this.taskId = null;
    document.getElementById("basics-next").addEventListener("click", () => this.next());
    document.getElementById("basics-start").addEventListener("click", () => this.startTask());
  }

  async show(stepId = null) {
    this.course = await this.api("/api/course");
    const steps = this.course.basics.steps;
    if (stepId) this.stepId = stepId;
    if (!this.stepId || !steps.find((s) => s.id === this.stepId)) {
      const firstOpen = steps.find((s) => s.tasks.some((t) => !t.done));
      this.stepId = (firstOpen || steps[0]).id;
    }
    const step = steps.find((s) => s.id === this.stepId);
    const open = step.tasks.find((t) => !t.done);
    if (!this.taskId || !step.tasks.find((t) => t.id === this.taskId)) this.taskId = (open || step.tasks[0]).id;
    this.render();
  }

  hide() {
    this.panel.stop();
  }

  render() {
    const steps = this.course.basics.steps;
    this.stepsEl.innerHTML = "";
    steps.forEach((s, i) => {
      const li = document.createElement("li");
      const done = s.tasks.every((t) => t.done);
      li.dataset.step = s.id;
      li.className = `${s.id === this.stepId ? "active" : ""}${done ? " done" : ""}`;
      li.tabIndex = 0;
      li.setAttribute("role", "button");
      if (s.id === this.stepId) li.setAttribute("aria-current", "step");
      li.innerHTML = `<span class="step-num"></span><span class="step-label">${esc(s.title)}</span>`;
      const go = () => { this.panel.stop(); this.stepId = s.id; this.taskId = null; this.show(s.id); };
      li.addEventListener("click", go);
      li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
      this.stepsEl.appendChild(li);
    });
    const step = steps.find((s) => s.id === this.stepId);
    const idx = steps.indexOf(step);
    document.getElementById("basics-title").textContent = `${idx + 1}. ${step.title}`;
    document.getElementById("basics-text").innerHTML = step.text.map((t) => `<li>${this.terms.markup(t)}</li>`).join("");
    const list = document.getElementById("basics-tasks");
    list.innerHTML = "";
    step.tasks.forEach((t, i) => {
      const li = document.createElement("li");
      li.className = `basics-task${t.id === this.taskId ? " now" : ""}${t.done ? " done" : ""}`;
      li.innerHTML = `<span class="basics-task-num">${t.done ? ICON_OK : i + 1}</span><span class="basics-task-text">${this.terms.markup(t.text)}</span>`;
      li.tabIndex = 0;
      li.setAttribute("role", "button");
      li.dataset.task = t.id;
      if (t.id === this.taskId) li.setAttribute("aria-current", "true");
      const pick = (byKey) => {
        this.panel.stop();
        this.taskId = t.id;
        this.render();
        if (byKey) { const again = list.querySelector(`[data-task="${t.id}"]`); if (again) again.focus(); }
      };
      li.addEventListener("click", (e) => { if (!e.target.closest(".term")) pick(false); });
      li.addEventListener("keydown", (e) => {
        if (e.target === li && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); pick(true); }
      });
      list.appendChild(li);
    });
    const task = step.tasks.find((t) => t.id === this.taskId);
    this._task = task;
    const allDone = steps.every((s) => s.tasks.every((t) => t.done));
    document.getElementById("basics-done").classList.toggle("hidden", !allDone);
    const isPractice = !!task.practice;
    document.getElementById("basics-drill").classList.toggle("hidden", isPractice);
    document.getElementById("basics-practice").classList.toggle("hidden", !isPractice);
    const start = document.getElementById("basics-start");
    start.textContent = isPractice ? "Start the 10 notes" : task.done ? "Do it again" : "Start";
    start.classList.toggle("primary", !task.done);
    this._nextButton(task.done);
    if (!isPractice) {
      const d = task.drill;
      const full = d.kind === "collect" || (d.steps || []).some((s) => !s.any || s.any.length > 6);
      const pitches = d.kind === "collect" ? d.pitches : (d.steps || []).flatMap((s) => s.any || s.all || []);
      this.panel.setup({
        ...(full ? { low: 36, high: 96 } : { pitches: pitches.length ? pitches : [60, 72] }),
        positions: task.hand ? [task.hand] : [], show: task.show, hintAfterWrong: step.id === "b1",
      });
      if (!task.done) this.startTask();
    }
  }

  _nextButton(done) {
    const steps = this.course.basics.steps;
    const step = steps.find((s) => s.id === this.stepId);
    const last = step === steps.at(-1) && this._task === step.tasks.at(-1);
    const btn = document.getElementById("basics-next");
    btn.textContent = last ? "Finish" : "Next";
    btn.classList.toggle("primary", done);
  }

  async startTask() {
    const task = this._task;
    if (!task) return;
    if (task.practice) {
      this.onPractice(task.practice);
      return;
    }
    try {
      await this.panel.start({ source: "basics", ref: task.id }, {
        onPass: async (st) => {
          task.done = true;
          const li = document.querySelector(".basics-task.now .basics-task-num");
          if (li) li.innerHTML = ICON_OK;
          document.querySelector(".basics-task.now")?.classList.add("done");
          document.getElementById("basics-start").textContent = "Do it again";
          document.getElementById("basics-start").classList.remove("primary");
          this._nextButton(true);
          this.celebrate(document.getElementById("basics-title"));
          const r = st.result || {};
          if (r.unlocked && r.unlocked.length) {
            await this.terms.load();
            await this.terms.firstUse(r.unlocked);
          }
          if (r.basics_new) this.onDone && this.onDone();
        },
      });
    } catch (err) {
      console.error(err);
    }
  }

  async next() {
    this.panel.stop();
    const steps = this.course.basics.steps;
    const step = steps.find((s) => s.id === this.stepId);
    const i = step.tasks.indexOf(this._task);
    if (i + 1 < step.tasks.length) {
      this.taskId = step.tasks[i + 1].id;
      return this.show(this.stepId);
    }
    const si = steps.indexOf(step);
    if (si + 1 < steps.length) {
      this.stepId = steps[si + 1].id;
      this.taskId = null;
      return this.show(this.stepId);
    }
    await this.show(this.stepId);
    if (this.course.basics.done) this.onDone && this.onDone(true);
  }
}
