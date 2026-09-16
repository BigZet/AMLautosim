"""Minimal shared blue theme for the workshop UI."""

from nicegui import ui

CSS = """
:root { --ink:#192b46; --muted:#77869a; --line:#dde5ef; --paper:#f5f8fc; --accent:#1555a2; }
body { background:var(--paper); color:var(--ink); font-family:Arial,Helvetica,sans-serif; }
.nicegui-content { padding:0; gap:0; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
.auth-shell { min-height:100vh; display:flex; align-items:center; justify-content:center; width:100%; padding:28px 20px; }
.auth-main { width:100%; max-width:380px; }
.auth-brand { color:#174a88; font-size:17px; font-weight:600; text-align:center; margin-bottom:24px; letter-spacing:.3px; }
.auth-form { width:100%; padding:28px; background:white; border:1px solid var(--line); border-radius:14px; gap:18px; }
.form-title { font-size:24px; font-weight:600; line-height:1.3; margin:0; }
.auth-switch { display:flex; border-bottom:1px solid var(--line); width:100%; margin-bottom:2px; gap:26px; }
.auth-switch a { padding:10px 0; font-size:14px; color:var(--muted); }
.auth-switch .selected { color:var(--accent); border-bottom:2px solid var(--accent); font-weight:600; }
.q-field--outlined .q-field__control { border-radius:8px; background:#fff; }
.q-field__label { color:#77869a; }
.primary-button { width:100%; border-radius:8px; height:46px; font-weight:500; }
.form-note { font-size:12px; color:var(--muted); line-height:1.5; }
.auth-footer { text-align:center; font-size:12px; margin-top:20px; }
.auth-footer a { color:#77869a; }
.error-box { background:#fff0ee; color:#a3352a; border:1px solid #f3d5d0; border-radius:8px; padding:12px; font-size:13px; width:100%; white-space:pre-line; }
.success-box { background:#edf5ff; color:#1555a2; border-radius:8px; padding:12px; font-size:13px; width:100%; }
.brand { display:flex; gap:10px; align-items:center; font-size:16px; font-weight:600; color:var(--accent); }
.app-header { background:#fff; border-bottom:1px solid var(--line); padding:18px 30px; width:100%; align-items:center; }
.header-identity { align-items:center; gap:22px; min-width:0; flex:1; flex-wrap:nowrap; }
.header-identity .brand { flex-shrink:0; white-space:nowrap; }
.header-game-title { border-left:1px solid var(--line); padding-left:22px; color:#526783; font-size:15px; font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
@media (max-width:600px) { .header-identity { flex-basis:100%; gap:14px; } .header-game-title { padding-left:14px; font-size:14px; } }
.header-actions { align-items:center; gap:4px; flex-wrap:nowrap; padding-left:14px; border-left:1px solid #e9edf3; }
.header-user-name { font-size:13px; color:#52647c; }
.header-text-link { display:inline-flex; justify-content:center; align-items:center; gap:7px; height:32px; padding:0 11px; border-radius:7px; background:#f0f4f9; font-size:13px; font-weight:500; color:#34577e; white-space:nowrap; text-decoration:none; transition:background .15s; }
.header-text-link .q-icon { order:-1; font-size:16px; color:#5a7a9e; }
.header-text-link:hover { background:#e3edf8; color:#1555a2; text-decoration:none; }
.header-text-link:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
.header-exit { width:32px; min-width:32px; height:32px; border-radius:7px; color:#6e8198 !important; }
.header-exit .q-icon { font-size:18px; }
.header-action { display:inline-flex; align-items:center; justify-content:center; gap:8px; height:38px; padding:0 14px; border-radius:10px; font-size:13px; font-weight:500; line-height:20px; white-space:nowrap; text-decoration:none; transition:background .15s,border-color .15s; }
.header-action .q-icon { font-size:18px; }
a.header-action .q-icon { order:-1; }
.header-action:hover { text-decoration:none; }
.header-action:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
.header-action-soft { color:var(--accent); background:#edf4fd; border:1px solid #e1ebf8; }
.header-action-soft:hover { background:#dfecfc; border-color:#c8dcf4; }
.header-action-quiet { border:1px solid var(--line); background:white; box-shadow:none; }
.header-action-quiet:hover { background:#f5f8fc; }
.game-guide { max-width:1040px; gap:24px; }
.guide-intro { max-width:760px; padding:12px 0 8px; gap:12px; }
.guide-eyebrow { color:var(--accent); font-size:13px; font-weight:600; }
.guide-title { font-size:34px; font-weight:600; line-height:1.2; }
.guide-lead { font-size:16px; color:#657892; line-height:1.7; }
.guide-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; width:100%; }
.guide-step { gap:12px; }
.guide-number { color:#397fbd; background:#edf4fd; padding:6px 10px; border-radius:8px; font-size:13px; font-weight:600; }
.guide-copy { color:#657892; font-size:14px; line-height:1.65; }
.guide-interface { gap:8px; }
.guide-feature { width:100%; flex-wrap:nowrap; gap:16px; padding:18px 0; border-bottom:1px solid #edf1f6; }
.guide-feature:last-child { border-bottom:0; padding-bottom:0; }
.guide-feature-icon { font-size:22px; color:var(--accent); background:#edf4fd; border-radius:10px; padding:10px; flex-shrink:0; }
.guide-feature-text { gap:6px; min-width:0; }
.guide-footnote { font-size:12px; color:#7c8ba0; line-height:1.5; }
@media (max-width:600px) { .guide-grid { grid-template-columns:1fr; } .guide-title { font-size:27px; } }
.workspace { max-width:1180px; padding:32px 24px; margin:0 auto; width:100%; gap:24px; }
.panel { background:#fff; border:1px solid var(--line); border-radius:12px; box-shadow:none; padding:24px; width:100%; }
.muted { color:var(--muted); }
.header-game-status { display:flex; align-items:center; gap:7px; color:#61728a; font-size:12px; line-height:18px; white-space:nowrap; margin-right:4px; padding-right:0; }
.header-game-status::before { content:""; width:6px; height:6px; border-radius:50%; background:var(--status-color,#77869a); flex-shrink:0; }
.waiting-room { width:100%; min-height:380px; align-items:center; justify-content:center; gap:18px; background:white; border:1px solid var(--line); border-radius:16px; padding:32px; }
.waiting-icon { color:#397fbd; background:#edf5ff; border-radius:50%; padding:20px; font-size:34px; }
.scenario-layout { display:grid; grid-template-columns:minmax(0,1fr) 310px; gap:24px; width:100%; align-items:start; }
.scenario-editor { width:100%; min-width:0; gap:16px; }
.operation-picker { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; width:100%; }
.operation-choice { min-height:66px; padding:12px 14px; background:white !important; border:1px solid var(--line); border-radius:12px; color:var(--ink) !important; box-shadow:0 2px 5px #192b4603; transition:border-color .15s, background .15s; }
.operation-choice:hover { border-color:#9cbce1; background:#f8fbff !important; }
.operation-choice:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
.operation-choice .q-btn__content { display:flex; flex-wrap:nowrap; justify-content:center; align-items:center; gap:12px; width:100%; text-align:center; font-size:13px; font-weight:500; line-height:1.4; }
.operation-choice .q-btn__content > .q-icon:first-child { margin:0; flex-shrink:0; width:36px; height:36px; font-size:20px; border-radius:10px; background:#edf4fd; color:var(--accent); }
@media (max-width:480px) { .operation-picker { grid-template-columns:1fr; } }


.operation-card { width:100%; padding:20px; gap:16px; border:1px solid var(--line); border-radius:12px; box-shadow:none; }
.operation-header { width:100%; align-items:center; flex-wrap:nowrap; gap:4px; }
.operation-title { flex:1; min-width:0; line-height:1.45; padding-right:8px; }
.operation-header > .q-space { display:none; }
.operation-header > .q-btn { width:28px; min-width:28px; flex-shrink:0; }
.operation-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px 12px; width:100%; align-items:start; }
.operation-parameter { width:100%; min-width:0; }
.operation-parameter .q-field__native { overflow-wrap:anywhere; }
.operation-parameter .q-field__native > span { white-space:normal; line-height:1.4; padding:3px 0; }
.operation-toggle { min-height:40px; font-size:12px; align-self:center; }
.operation-toggle .q-toggle__label { line-height:1.4; }
@media (max-width:600px) { .operation-fields { grid-template-columns:1fr; } .operation-card { padding:16px; } }
.operation-description { width:100%; color:var(--muted); font-size:12px; }
.operation-description .q-item { min-height:28px; padding:0; }
.scenario-summary { position:sticky; top:20px; gap:14px; padding:20px; }
.scenario-summary .q-btn { width:100%; border-radius:8px; }
.scenario-summary .text-xl { font-size:20px; }
.scenario-goal { width:100%; gap:8px; padding:16px; border-radius:10px; background:#edf5ff; }
.resource-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; width:100%; }
.resource-overview { width:100%; }
.resource-overview .resource-grid { grid-template-columns:repeat(4,minmax(0,1fr)); }
.resource-overview .resource-tile { background:white; border:1px solid var(--line); padding:12px; }
.resource-tile { padding:10px; gap:6px; background:#f7f9fc; border-radius:8px; min-width:0; }
.resource-tile .text-lg { font-size:16px; }
.submission-conditions { width:100%; gap:7px; border-top:1px solid var(--line); padding-top:14px; margin-top:2px; }
.condition-row { width:100%; flex-wrap:nowrap; align-items:center; gap:7px; min-height:24px; font-size:11px; }
.condition-icon { font-size:14px; flex-shrink:0; }
.condition-ok .condition-icon { color:#388772; }
.condition-pending .condition-icon { color:#8b9cb1; }
.condition-label { flex:1; color:#52647c; }
.condition-value { color:#243d5c; white-space:nowrap; font-variant-numeric:tabular-nums; font-size:11px; }
.condition-help { color:#a25431; font-size:12px; line-height:1.4; padding:7px 9px; background:#fff6ef; border-radius:6px; width:100%; }
.submission-ready { font-size:12px; color:#247c62; margin-top:4px; }
.save-indicator { width:100%; text-align:center; color:#8190a3; font-size:11px; }
.submit-scenario { width:100%; min-height:42px; border-radius:10px !important; box-shadow:none !important; font-size:14px; font-weight:500; }
.submit-scenario .q-icon { font-size:18px; }
.submit-scenario.disabled, .submit-scenario:disabled, .submit-scenario[aria-disabled="true"] { opacity:1 !important; background:#edf1f6 !important; color:#8a99ac !important; }
.scenario-hint { padding:10px 12px; border-left:3px solid #8bb3df; background:#f4f8fe; color:#466183; font-size:12px; border-radius:4px; width:100%; }
.scoring-wait { width:100%; max-width:880px; margin:0 auto; gap:20px; }
.waiting-hero { width:100%; align-items:center; text-align:center; padding:30px 24px 24px; gap:12px; border:1px solid #dce7f5; border-radius:18px; box-shadow:none; background:linear-gradient(155deg,#fff 25%,#edf5ff); }
.waiting-symbol { display:flex; align-items:center; justify-content:center; width:60px; height:60px; border-radius:18px; background:#e5f0ff; color:var(--accent); font-size:30px; }
.waiting-title { font-size:26px; font-weight:600; line-height:1.3; }
.waiting-caption { color:#657892; font-size:14px; }
.waiting-stages { align-items:center; justify-content:center; flex-wrap:wrap; gap:24px; margin:10px 0 2px; }
.waiting-stage { align-items:center; gap:6px; font-size:12px; color:#8998ab; }
.waiting-stage .q-icon { font-size:18px; }
.waiting-stage.is-active { color:var(--accent); }
.waiting-note { align-items:center; gap:5px; font-size:11px; color:#7b8da5; }
.submitted-summary { gap:16px; }
.submitted-target { width:100%; align-items:center; gap:8px; padding:10px 12px; background:#f0f7f5; color:#287663; border-radius:9px; font-size:12px; }
.submitted-target-value { margin-left:auto; font-variant-numeric:tabular-nums; }
.submitted-operations { width:100%; border-top:1px solid var(--line); font-size:14px; }
.submitted-operations .q-item { padding:12px 0; }
.submitted-operation { align-items:center; flex-wrap:nowrap; gap:12px; padding:12px 0; border-top:1px solid #edf1f6; }
.submitted-operation-index { width:24px; flex-shrink:0; color:#91a1b6; font-size:12px; }
.submitted-operation-title { flex:1; font-size:13px; }
.submitted-operation-amount { font-size:13px; font-weight:500; white-space:nowrap; font-variant-numeric:tabular-nums; }
.result-workspace { width:100%; gap:20px; }
.result-tabs { width:100%; background:white; border:1px solid var(--line); border-radius:12px; padding:4px; color:var(--accent); }
.result-tabs .q-tab { text-transform:none; min-height:60px; }
.result-tab-panels .q-tab-panel { overflow:visible; }
.result-tab-panels .q-panel { overflow:visible; }
.result-tab-panels .result-hero { margin-bottom:20px; }
.result-hero { width:100%; display:flex; justify-content:space-between; align-items:center; gap:24px; padding:32px; border-radius:16px; background:linear-gradient(120deg,#123e79,#206ab0); color:white; }
.result-score { font-size:56px; font-weight:700; line-height:1.1; letter-spacing:-2px; }
.result-score-caption { color:#d4e8ff; font-size:14px; }
.result-rank { align-items:center; gap:10px; padding:20px 28px; background:#ffffff12; border:1px solid #ffffff30; border-radius:12px; flex-shrink:0; }
.result-metrics { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; width:100%; }
.result-metric { gap:12px; padding:20px; }
.risk-badge { font-size:12px; border-radius:16px; padding:4px 10px; }
.risk-normal { background:#e9f5ef; color:#27634e; }
.risk-review { background:#fff4df; color:#8a5b12; }
.risk-suspicious { background:#fcece9; color:#9d3a30; }
.result-operation { width:100%; padding:16px 0; border-bottom:1px solid var(--line); gap:6px; }
@media (max-width:700px) {
 .result-hero { padding:24px; flex-wrap:wrap; }
 .result-score { font-size:44px; }
 .result-rank { align-items:flex-start; padding:14px 18px; }
 .result-metrics { grid-template-columns:1fr; }
}
@media (max-width:900px) {
 .scenario-layout { grid-template-columns:minmax(0,1fr); }
 .scenario-summary { position:static; }
}
@media (max-width:600px) {
 .resource-overview .resource-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
 .auth-form { padding:24px; }
 .workspace { padding:20px 14px; }
 .app-header { padding:14px 18px; }
}

.resource-overview { position:sticky; top:0; z-index:5; background:var(--paper); padding:12px; border-bottom:1px solid var(--line); }
.operation-card .q-expansion-item__content { padding:12px; }
.operation-card .q-item__label { overflow-wrap:anywhere; }
@media (max-width:600px) { .resource-grid { grid-template-columns:repeat(3,minmax(0,1fr)); } }
"""


def setup():
    ui.colors(
        primary="#1555a2", secondary="#397fbd", positive="#247c62", negative="#ad4535"
    )
    ui.add_css(CSS)


def brand():
    with ui.element("div").classes("brand"):
        ui.label("AML Практикум")


def auth_layout(audience="play"):
    with (
        ui.element("main").classes("auth-shell"),
        ui.element("section").classes("auth-main"),
    ):
        ui.label("AML Практикум").classes("auth-brand w-full")
        form = ui.column().classes("auth-form")
        with ui.element("div").classes("auth-footer"):
            ui.link(
                "Вход участника" if audience == "admin" else "Вход организатора",
                "/play/login" if audience == "admin" else "/admin/login",
            )
    return form
