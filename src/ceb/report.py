"""Self-contained local HTML report for a CEB run — no external assets, no third-party JS,
opens straight from disk. Scenario rows expand to per-trial checks and the full conversation;
the filter/expand/export controls are a few lines of inline vanilla JS with the triage tables
embedded in the page, so the file stays a single portable artefact. Generated automatically
alongside the JSON report whenever the CLI is given --out."""
from __future__ import annotations

import html
import json
from typing import Any

_AXIS_ORDER = (
    "policy_safety", "runtime", "conversation_experience", "action_correctness",
    "flow_control", "recovery", "business_outcome",
)

_STYLE = """
/* Light, corporate palette — restrained slate neutrals with a single navy accent. Deliberately
   not theme-switching: the report is read and shared as a light document. */
:root {
  --bg: #f7f8fa; --surface: #ffffff; --surface-2: #f2f4f7; --border: #e3e7ec;
  --border-strong: #cbd2db;
  --text: #1f2a37; --text-muted: #5b6875; --text-faint: #8b96a3;
  --accent: #2f5d94;
  --good: #2e6b4a; --good-dim: #edf4f0;
  --warn: #8a6516; --warn-dim: #faf3e6;
  --bad: #a8423e; --bad-dim: #fbeeed;
  --shadow: 0 1px 2px rgba(31,42,55,.06);
  --mono: ui-monospace, "SF Mono", "Cascadia Code", Consolas, "Liberation Mono", monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font-family: var(--sans);
  line-height: 1.6; -webkit-font-smoothing: antialiased; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 44px 26px 90px; }
header.top { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline;
  gap: 12px; padding-bottom: 22px; border-bottom: 1px solid var(--border); margin-bottom: 32px; }
.eyebrow { font-family: var(--mono); font-size: 11.5px; letter-spacing: .06em; color: var(--accent); }
h1 { font-family: var(--mono); font-size: 21px; font-weight: 500; margin: 4px 0 0; letter-spacing: -.01em; }
.meta { font-family: var(--mono); font-size: 12px; color: var(--text-faint); text-align: right; line-height: 1.8; }
h2 { font-family: var(--sans); font-size: 13.5px; color: var(--text-muted); margin: 0 0 16px; font-weight: 500; }
section { margin-bottom: 42px; }
.stat-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.stat { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow);
  padding: 16px 18px; display: flex; flex-direction: column; gap: 4px; }
.stat .label { font-family: var(--sans); font-size: 12px; color: var(--text-muted); }
.stat .value { font-family: var(--mono); font-size: 25px; font-weight: 500; font-variant-numeric: tabular-nums; letter-spacing: -.02em; }
.stat .value.bad { color: var(--bad); }
.stat .value.good { color: var(--good); }
.axis-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px 26px; }
.axis-row { display: grid; grid-template-columns: 150px 1fr 54px; align-items: center; gap: 12px; }
.axis-name { font-family: var(--mono); font-size: 12px; color: var(--text-muted); }
.axis-track { position: relative; height: 5px; background: var(--surface-2); border-radius: 4px; overflow: hidden; }
.axis-fill { position: absolute; inset: 0; background: var(--accent); opacity: .75; border-radius: 4px; }
.axis-pct { font-family: var(--mono); font-size: 12px; text-align: right; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.chip { display: inline-flex; align-items: center; gap: 5px; font-family: var(--mono); font-size: 11px;
  font-weight: 500; padding: 2px 9px; border-radius: 20px; }
.chip.pass { background: var(--good-dim); color: var(--good); }
.chip.fail { background: var(--bad-dim); color: var(--bad); }
.chip.wording { background: var(--warn-dim); color: var(--warn); }

/* --- controls --- */
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 18px; }
.toolbar input[type=search], .toolbar select {
  background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 10px;
  padding: 8px 11px; font-family: var(--sans); font-size: 12.5px; box-shadow: var(--shadow); }
.toolbar input[type=search] { flex: 1 1 240px; min-width: 190px; }
.toolbar input[type=search]:focus, .toolbar select:focus { outline: none; border-color: var(--border-strong); }
.seg { display: inline-flex; background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 2px; gap: 2px; box-shadow: var(--shadow); }
.seg button { background: none; border: none; color: var(--text-muted); font-family: var(--sans); font-size: 12.5px;
  padding: 6px 11px; border-radius: 8px; cursor: pointer; display: inline-flex; align-items: center; gap: 7px; }
.seg button[aria-pressed="true"] { background: var(--surface-2); color: var(--text); box-shadow: inset 0 0 0 1px var(--border); }
.seg button .n { font-family: var(--mono); font-size: 11px; font-variant-numeric: tabular-nums;
  color: var(--text-faint); background: var(--surface-2); border-radius: 20px; padding: 1px 7px; }
.seg button[aria-pressed="true"] .n { background: var(--surface); color: var(--text-muted); }
.seg button[data-status="fail"] .n, .seg button[data-status="p0"] .n { color: var(--bad); }
.seg button[data-status="wording"] .n { color: var(--warn); }
.seg button[data-status="pass"] .n { color: var(--good); }
.btn { background: var(--surface); color: var(--text-muted); border: 1px solid var(--border); border-radius: 10px;
  padding: 8px 12px; font-family: var(--sans); font-size: 12.5px; cursor: pointer; box-shadow: var(--shadow); }
.btn:hover { color: var(--accent); border-color: var(--border-strong); }
.btn:disabled { opacity: .45; cursor: not-allowed; }
.btn:disabled:hover { color: var(--text-muted); border-color: var(--border); }
.count { font-family: var(--mono); font-size: 12px; color: var(--text-faint); margin-left: auto; }

/* --- scenario grid ---
   Card anatomy, fixed top to bottom so the eye lands in the same place on every card:
   status + trial ratio · scenario id · why it failed · tags. */
.scen-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 12px; align-items: start; }
details.card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
  box-shadow: var(--shadow); overflow: hidden; }
details.card[open] { grid-column: 1 / -1; border-color: var(--border-strong); box-shadow: 0 2px 10px rgba(31,42,55,.07); }
details.card > summary { list-style: none; cursor: pointer; padding: 14px 16px 13px; display: flex;
  flex-direction: column; gap: 10px; min-height: 150px; }
details.card[open] > summary { min-height: 0; }
details.card > summary::-webkit-details-marker { display: none; }
details.card > summary:hover { background: var(--surface-2); }

.card-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.status { display: inline-flex; align-items: center; gap: 6px; font-family: var(--sans); font-size: 12px;
  font-weight: 500; }
.status::before { content: ""; width: 7px; height: 7px; border-radius: 50%; flex: none; }
.status.fail { color: var(--bad); } .status.fail::before { background: var(--bad); }
.status.pass { color: var(--good); } .status.pass::before { background: var(--good); }
.ratio { font-family: var(--mono); font-size: 12px; color: var(--text-faint); font-variant-numeric: tabular-nums; }
.ratio b { font-size: 16px; font-weight: 600; color: var(--text); }
.card.is-fail .ratio b { color: var(--bad); }

.card-title { font-family: var(--mono); font-size: 12.5px; line-height: 1.45; color: var(--text);
  word-break: break-word; }
.card-reason { background: var(--surface-2); border-radius: 10px; padding: 9px 11px; display: flex;
  flex-direction: column; gap: 3px; }
.reason-head { display: flex; align-items: baseline; gap: 7px; }
.sev-badge { font-family: var(--mono); font-size: 10px; font-weight: 700; letter-spacing: .03em;
  padding: 1px 6px; border-radius: 5px; flex: none; }
.sev-badge.P0 { background: var(--bad-dim); color: var(--bad); }
.sev-badge.P1 { background: var(--warn-dim); color: var(--warn); }
.sev-badge.P2 { background: var(--surface); color: var(--text-faint); }
.reason-name { font-family: var(--mono); font-size: 11.5px; color: var(--text); word-break: break-word; }
.reason-detail { font-family: var(--sans); font-size: 11.5px; color: var(--text-muted);
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.card-foot { display: flex; flex-wrap: wrap; gap: 5px; margin-top: auto; }
.tag { font-family: var(--mono); font-size: 10.5px; color: var(--text-muted); background: var(--surface-2);
  border-radius: 20px; padding: 2px 8px; }
.tag.warn { background: var(--warn-dim); color: var(--warn); }
.card-body { padding: 4px 16px 18px; border-top: 1px solid var(--border); }
.trial { border-left: 2px solid var(--border); padding: 4px 0 10px 14px; margin-top: 14px; }
.trial.fail { border-left-color: var(--bad); }
.trial.pass { border-left-color: var(--good); }
.trial h4 { font-family: var(--mono); font-size: 11.5px; margin: 0 0 8px; font-weight: 500; color: var(--text-muted); }
.check-line { font-family: var(--mono); font-size: 11.5px; color: var(--text-muted); margin: 4px 0; }
.check-line .sev { font-weight: 600; }
.check-line .sev.P0 { color: var(--bad); }
.check-line .sev.P1 { color: var(--warn); }
.check-line .sev.P2 { color: var(--text-faint); }
details.convo { margin-top: 12px; }
details.convo > summary { cursor: pointer; list-style: none; font-family: var(--sans); font-size: 12px;
  color: var(--text-muted); padding: 5px 0; }
details.convo > summary::-webkit-details-marker { display: none; }
details.convo > summary::before { content: "▸ "; color: var(--text-faint); font-size: 10px; }
details.convo[open] > summary::before { content: "▾ "; }
.convo-body { border-left: 1px solid var(--border); padding-left: 12px; margin-top: 4px; }
.turn { font-family: var(--mono); font-size: 11.5px; margin: 7px 0; display: grid;
  grid-template-columns: 62px 1fr; gap: 10px; align-items: start; }
.turn .who { color: var(--text-faint); font-size: 10px; letter-spacing: .04em; padding-top: 2px; }
.turn.user .who { color: var(--accent); }
.turn.tool .who { color: var(--warn); }
.turn .said { white-space: pre-wrap; word-break: break-word; }
/* the model's own words are what a triage pass reads — keep them the most legible line */
.turn.assistant .said { color: var(--text); background: var(--surface-2); border-radius: 9px; padding: 6px 10px; }
.turn.user .said { color: var(--text-muted); }
.turn.tool .said { color: var(--text-faint); font-size: 11px; }
.note { font-family: var(--mono); font-size: 11px; color: var(--text-faint); margin: 10px 0 0; }
.empty { font-family: var(--sans); font-size: 13px; color: var(--text-faint); padding: 28px 4px; }
footer { margin-top: 52px; padding-top: 20px; border-top: 1px solid var(--border); font-family: var(--mono);
  font-size: 11.5px; color: var(--text-faint); display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
"""


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _stat(label: str, value: str, tone: str = "") -> str:
    return f'<div class="stat"><span class="label">{_esc(label)}</span><span class="value {tone}">{_esc(value)}</span></div>'


def _axis_row(name: str, score: float | None) -> str:
    pct = 0.0 if score is None else score
    return (
        f'<div class="axis-row"><span class="axis-name">{_esc(name)}</span>'
        f'<div class="axis-track"><div class="axis-fill" style="width:{pct}%"></div></div>'
        f'<span class="axis-pct">{"n/a" if score is None else f"{pct:.1f}%"}</span></div>'
    )


_ROLE_LABEL = {"user": "müşteri", "assistant": "model", "tool": "araç"}


def _turn(step: dict[str, Any]) -> str:
    role = str(step.get("role", ""))
    if role == "tool":
        args = json.dumps(step.get("arguments", {}), ensure_ascii=False)
        result = json.dumps(step.get("result", {}), ensure_ascii=False)
        body = f"{step.get('name', '')}({args})\n→ {result[:400]}"
    else:
        body = str(step.get("content", "") or "")
    if not body.strip():
        return ""
    return (f'<div class="turn {_esc(role)}"><span class="who">{_esc(_ROLE_LABEL.get(role, role))}</span>'
            f'<span class="said">{_esc(body)}</span></div>')


def _trial_block(run: dict[str, Any]) -> str:
    tone = "pass" if run.get("passed") else "fail"
    label = "PASS" if run.get("passed") else "FAIL"
    head = f'<h4>seed={_esc(run.get("seed"))} · <span class="chip {tone}">{label}</span></h4>'
    failures = [c for c in run.get("checks", []) if c.get("passed") is False]
    checks = "".join(
        f'<div class="check-line"><span class="sev {_esc(c.get("severity", "P1"))}">'
        f'{_esc(c.get("severity", "P1"))}</span> {_esc(c.get("name", ""))} '
        f'<span style="opacity:.8">[{_esc(c.get("axis", ""))}]</span> — {_esc(c.get("detail", ""))}</div>'
        for c in failures
    ) or '<div class="check-line">every check passed</div>'
    missing = [
        f'<div class="check-line">objective <b>{_esc(o["id"])}</b> missing: {_esc(", ".join(o["missing_milestones"]))}</div>'
        for o in run.get("objectives", []) if o.get("missing_milestones")
    ]
    if run.get("execution_error"):
        missing.append(f'<div class="check-line"><span class="sev P0">RUN</span> execution_error: {_esc(run["execution_error"])}</div>')
    turns = "".join(_turn(step) for step in run.get("transcript", []))
    if turns:
        nodes = " → ".join(str(n) for n in run.get("visited_nodes", []) if n)
        # A failing trial is opened to read what the model actually said, so its conversation is
        # shown expanded; a passing one stays folded to keep the grid scannable.
        head_note = f'<div class="note">user-plan: {_esc(nodes)}</div>' if nodes else ""
        transcript = (
            f'<details class="convo" {"open" if not run.get("passed") else ""}>'
            f'<summary>konuşma · {len(run.get("transcript", []))} adım</summary>'
            f'{head_note}<div class="convo-body">{turns}</div></details>'
        )
    else:
        transcript = ('<p class="note">Bu raporda transkript yok — konuşmaları yakalamak için sweep\'i '
                      'yeniden koşun (transkript kaydı eklenmeden önce üretilen raporlarda bulunmaz).</p>')
    return f'<div class="trial {tone}">{head}{checks}{"".join(missing)}{transcript}</div>'


def _group_of(scenario_id: str) -> str:
    """The pack-ish family a scenario belongs to, taken from its id (tr_<group>_...). Used only
    to populate the group filter, so a best-effort split is enough."""
    parts = scenario_id.split("_")
    return parts[1] if len(parts) > 2 and parts[0] == "tr" else (parts[0] or "other")


def _scenario_cards(results: list[dict[str, Any]]) -> tuple[str, list[str], list[str]]:
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_scenario.setdefault(r["scenario_id"], []).append(r)
    cards, groups, axes = [], set(), set()
    counts = {"all": len(by_scenario), "fail": 0, "p0": 0, "wording": 0, "pass": 0}
    order = sorted(by_scenario, key=lambda sid: (sum(r["passed"] for r in by_scenario[sid]) == len(by_scenario[sid]), sid))
    for scenario_id in order:
        runs = by_scenario[scenario_id]
        passed = sum(r["passed"] for r in runs)
        total = len(runs)
        all_pass = passed == total
        failures = [c for r in runs if not r["passed"] for c in r.get("checks", []) if c["passed"] is False]
        failing_axes = sorted({str(c.get("axis", "")) for c in failures if c.get("axis")})
        has_p0 = any(c.get("severity") == "P0" for c in failures)
        wording = any(r.get("wording_only_suspect") for r in runs if not r["passed"])
        group = _group_of(scenario_id)
        counts["pass" if all_pass else "fail"] += 1
        counts["p0"] += has_p0
        counts["wording"] += wording
        groups.add(group)
        axes.update(failing_axes)
        severity = next((s for s in ("P0", "P1", "P2") if any(c.get("severity") == s for c in failures)), "")
        status = "pass" if all_pass else "fail"
        top = (f'<div class="card-top"><span class="status {status}">'
               f'{"geçti" if all_pass else "düştü"}</span>'
               f'<span class="ratio"><b>{passed}</b>/{total}</span></div>')
        title = f'<div class="card-title">{_esc(scenario_id)}</div>'
        reason = ""
        if failures:
            first = failures[0]
            reason = (
                f'<div class="card-reason"><div class="reason-head">'
                f'<span class="sev-badge {_esc(severity)}">{_esc(severity)}</span>'
                f'<span class="reason-name">{_esc(first["name"])}</span></div>'
                f'<div class="reason-detail">{_esc(str(first.get("detail", "")))}</div></div>'
            )
        tags = [f'<span class="tag">{_esc(group)}</span>']
        tags += [f'<span class="tag">{_esc(a)}</span>' for a in failing_axes[:2]]
        if wording:
            tags.append('<span class="tag warn">wording?</span>')
        foot = f'<div class="card-foot">{"".join(tags)}</div>'
        body = "".join(_trial_block(r) for r in sorted(runs, key=lambda r: (r.get("passed", False), r.get("seed", 0))))
        cards.append(
            f'<details class="card is-{status}" data-sid="{_esc(scenario_id)}" data-fail="{"0" if all_pass else "1"}" '
            f'data-p0="{"1" if has_p0 else "0"}" data-wording="{"1" if wording else "0"}" '
            f'data-group="{_esc(group)}" data-axes="{_esc(",".join(failing_axes))}">'
            f'<summary>{top}{title}{reason}{foot}</summary>'
            f'<div class="card-body">{body}</div></details>'
        )
    return "\n".join(cards), sorted(groups), sorted(axes), counts


def _turn_text(step: dict[str, Any]) -> str:
    if step.get("role") == "tool":
        args = json.dumps(step.get("arguments", {}), ensure_ascii=False)
        return f"{step.get('name', '')}({args}) -> {json.dumps(step.get('result', {}), ensure_ascii=False)}"
    return str(step.get("content", "") or "")


def _export_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One flat, spreadsheet-native table for the whole run: a row per conversation turn with the
    run's verdict and failing checks denormalised onto it. One table rather than three so a single
    export carries everything — filter by `sonuc` to triage, by `rol` to read only what the model
    said, pivot on `senaryo` for per-scenario counts. A run with no transcript still gets one row
    so it is never silently missing from the export."""
    rows: list[dict[str, Any]] = []
    for run in results:
        failures = [c for c in run.get("checks", []) if c.get("passed") is False]
        context = {
            "senaryo": run["scenario_id"],
            "seed": run.get("seed"),
            "sonuc": "geçti" if run.get("passed") else "düştü",
            "p0": run.get("p0_failures", 0),
            "wording_supheli": "evet" if run.get("wording_only_suspect") else "hayır",
            "dusen_kontroller": "; ".join(
                f"{c.get('severity', '')} {c.get('name', '')}" for c in failures
            ),
            "dusen_eksenler": "; ".join(sorted({str(c.get("axis", "")) for c in failures if c.get("axis")})),
        }
        turns = [step for step in run.get("transcript", []) if _turn_text(step).strip()]
        if not turns:
            rows.append({**context, "adim": "", "rol": "", "metin": ""})
            continue
        for step in turns:
            rows.append({
                **context,
                "adim": step.get("index"),
                "rol": _ROLE_LABEL.get(str(step.get("role", "")), str(step.get("role", ""))),
                "metin": _turn_text(step),
            })
    return rows


_SCRIPT = """
const DATA = __DATA__;
const $ = id => document.getElementById(id);
function csv(rows) {
  if (!rows.length) return "";
  const cols = Object.keys(rows[0]);
  const cell = v => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\\n;]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  return [cols.join(","), ...rows.map(r => cols.map(c => cell(r[c])).join(","))].join("\\n");
}
function save(name, text, mime) {
  // \\uFEFF: without the BOM Excel mis-decodes Turkish characters in the detail column.
  const blob = new Blob([mime.startsWith("text/csv") ? "\\uFEFF" + text : text], {type: mime});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click();
  a.remove(); URL.revokeObjectURL(url);
}
// Exports what is currently on screen: filtering to "düşen" then exporting yields only
// the failing runs, which is the common triage handoff.
$("export").onclick = () => {
  const visible = new Set(cards.filter(c => !c.hidden).map(c => c.dataset.sid));
  save("ceb-rapor.csv", csv(DATA.rows.filter(r => visible.has(r.senaryo))), "text/csv;charset=utf-8");
};

let status = "all";
const cards = [...document.querySelectorAll("details.card")];
function apply() {
  const term = $("q").value.trim().toLowerCase();
  const group = $("f-group").value, axis = $("f-axis").value;
  let shown = 0;
  for (const card of cards) {
    const d = card.dataset;
    const ok =
      (status === "all"
        || (status === "fail" && d.fail === "1")
        || (status === "pass" && d.fail === "0")
        || (status === "p0" && d.p0 === "1")
        || (status === "wording" && d.wording === "1"))
      && (!group || d.group === group)
      && (!axis || d.axes.split(",").includes(axis))
      && (!term || d.sid.toLowerCase().includes(term) || card.textContent.toLowerCase().includes(term));
    card.hidden = !ok;
    if (ok) shown++;
  }
  $("count").textContent = shown + " / " + cards.length;
  $("empty").hidden = shown > 0;
}
$("q").oninput = apply;
$("f-group").onchange = apply;
$("f-axis").onchange = apply;
for (const b of document.querySelectorAll(".seg button")) {
  b.onclick = () => {
    document.querySelectorAll(".seg button").forEach(x => x.setAttribute("aria-pressed", x === b));
    status = b.dataset.status;
    apply();
  };
}
$("expand").onclick = () => {
  const visible = cards.filter(c => !c.hidden);
  const open = !visible.every(c => c.open);
  visible.forEach(c => c.open = open);
};
apply();
"""


def render_html(report: dict[str, Any]) -> str:
    """Render a full CLI run report (as returned by cli.run()) as a single,
    dependency-free HTML page — no CDN assets, safe to open straight from disk."""
    summary = report["summary"]
    gate = report.get("gate", {})
    axes = summary.get("axes", {})
    axis_rows = "\n".join(_axis_row(name, axes.get(name, {}).get("score")) for name in _AXIS_ORDER if name in axes)
    gate_tone = "good" if gate.get("passed") else "bad"
    gate_label = "PASS" if gate.get("passed") else "FAIL"
    cards, groups, failing_axes, counts = _scenario_cards(report.get("results", []))
    group_options = "".join(f'<option value="{_esc(g)}">{_esc(g)}</option>' for g in groups)
    axis_options = "".join(f'<option value="{_esc(a)}">{_esc(a)}</option>' for a in failing_axes)
    payload = json.dumps({"rows": _export_rows(report.get("results", []))}, ensure_ascii=False)
    # </script> inside embedded data would close the tag early and break the page.
    _script = _SCRIPT.replace("__DATA__", payload.replace("</", "<\\/"))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(report.get('benchmark', 'CEB'))} — {_esc(report.get('model', ''))}</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div>
      <span class="eyebrow">{_esc(report.get('benchmark', 'Conversation Execution Benchmark'))} · v{_esc(report.get('version', ''))}</span>
      <h1>{_esc(report.get('model', 'model-under-test'))}</h1>
    </div>
    <div class="meta">
      {summary.get('scenarios', 0)} scenarios · {summary.get('runs', 0)} runs<br>
      {_esc(report.get('created_at', ''))}
    </div>
  </header>

  <section>
    <h2>Summary</h2>
    <div class="stat-strip">
      {_stat("Pass@1", f"{summary.get('pass_at_1', 0):.2%}")}
      {_stat("Pass@k", f"{summary.get('pass_at_k', 0):.2%}")}
      {_stat("Pass^k", f"{summary.get('pass_pow_k', 0):.2%}")}
      {_stat("Release gate", gate_label, gate_tone)}
    </div>
  </section>

  <section>
    <h2>Axis scores</h2>
    <div class="axis-list">
      {axis_rows}
    </div>
  </section>

  <section>
    <h2>Scenarios ({summary.get('scenarios', 0)}) — failing first · click a card for trials and transcript</h2>
    <div class="toolbar">
      <input type="search" id="q" placeholder="scenario, check or transcript text…">
      <div class="seg">
        <button data-status="all" aria-pressed="true">tümü <span class="n">{counts["all"]}</span></button>
        <button data-status="fail" aria-pressed="false">düşen <span class="n">{counts["fail"]}</span></button>
        <button data-status="p0" aria-pressed="false">P0 <span class="n">{counts["p0"]}</span></button>
        <button data-status="wording" aria-pressed="false">wording? <span class="n">{counts["wording"]}</span></button>
        <button data-status="pass" aria-pressed="false">geçen <span class="n">{counts["pass"]}</span></button>
      </div>
      <select id="f-group"><option value="">all groups</option>{group_options}</select>
      <select id="f-axis"><option value="">all axes</option>{axis_options}</select>
      <button class="btn" id="expand">expand</button>
      <button class="btn" id="export" title="Görünen senaryoları konuşmalarıyla birlikte CSV olarak indirir">dışa aktar</button>
      <span class="count" id="count"></span>
    </div>
    <div class="scen-grid">
      {cards}
    </div>
    <p class="empty" id="empty" hidden>No scenario matches these filters.</p>
  </section>

  <footer>
    <span>p0_failures={summary.get('p0_failures', 0)} (root_cause={summary.get('p0_failures_root_cause', 0)})</span>
    <span>wording_only_suspect_runs={summary.get('wording_only_suspect_runs', 0)}</span>
  </footer>
</div>
<script>{_script}</script>
</body>
</html>
"""
