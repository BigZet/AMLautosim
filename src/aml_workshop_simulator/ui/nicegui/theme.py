"""Minimal shared blue theme for the workshop UI."""

from nicegui import ui

CSS = """
:root { --ink:#192b46; --muted:#77869a; --line:#dde5ef; --paper:#f5f8fc; --accent:#1555a2; }
body { background:var(--paper); color:var(--ink); font-family:Arial,Helvetica,sans-serif; }
.nicegui-content { padding:0; gap:0; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
.auth-shell { --accent:#2354D6; --muted:#696E82; --line:#EDEEF2; --q-primary:#2354D6; min-height:100vh; display:flex; align-items:center; justify-content:center; width:100%; padding:28px 20px; background:radial-gradient(ellipse at center,#fff 0%,#fff 25%,#f7f9fd 100%); color:#252525; }
.auth-main { width:100%; max-width:380px; }
.auth-brand { color:var(--accent); font-size:23px; line-height:1.3; font-weight:600; text-align:center; margin-bottom:24px; letter-spacing:-.3px; }
.auth-form { width:100%; padding:14px 28px 28px; background:linear-gradient(160deg,#fff 60%,#fafbff); border:1px solid #e8edf4; border-radius:16px; gap:14px; box-shadow:0 16px 40px rgba(35,84,214,.075),0 2px 6px rgba(25,43,70,.025); }
.auth-form .q-field--outlined .q-field__control:before { border-color:#C8CCDB; }
.auth-form .q-field--outlined .q-field__control:hover:before { border-color:#9299B0; }
.auth-form .q-field--error .q-field__control:before { border-color:var(--q-negative); }
.auth-form .primary-button { height:44px; margin-top:4px; background:linear-gradient(120deg,#3263dd,#2354D6) !important; box-shadow:0 4px 10px rgba(35,84,214,.16); }
.auth-form .primary-button:not(.disabled):hover { background:linear-gradient(120deg,#2958ce,#1F4ABC) !important; }
.auth-form .q-field__label { color:var(--muted); }
.auth-form .q-field__native { color:#252525; }
.auth-form .q-field__append .q-icon { font-size:20px; color:#8A90A3; transition:color .15s; }
.auth-form .q-field__append .q-icon:hover { color:var(--accent); }
.form-title { font-size:24px; font-weight:600; line-height:1.3; margin:0; }
.auth-admin-title { width:100%; padding:10px 0 12px; margin:0 0 2px; border-bottom:1px solid var(--line); text-align:center; font-size:18px; font-weight:500; line-height:1.4; color:var(--accent); }
.auth-switch { display:flex; justify-content:center; border-bottom:1px solid var(--line); width:100%; margin-bottom:2px; gap:26px; }
.auth-switch a { padding:10px 0; font-size:14px; color:var(--muted); }
.auth-switch .selected { color:var(--accent); border-bottom:2px solid var(--accent); font-weight:600; }
.q-field--outlined .q-field__control { border-radius:8px; background:#fff; }
.q-field__label { color:#77869a; }
.primary-button { width:100%; border-radius:8px; height:46px; font-weight:500; }
.form-note { font-size:12px; color:var(--muted); line-height:1.5; }
.auth-footer { text-align:center; font-size:12px; margin-top:16px; }
.auth-shell-with-bottom-link { position:relative; min-height:100dvh; padding-top:64px; padding-bottom:64px; }
.auth-shell-with-bottom-link .auth-footer { position:absolute; bottom:16px; left:0; width:100%; margin:0; }
.auth-footer a { display:inline-block; padding:8px 12px; color:var(--muted); font-size:12px; font-weight:400; text-decoration:none; transition:color .15s; }
.auth-footer a:hover { color:var(--accent); text-decoration:underline; }
.auth-shell-with-bottom-link .auth-footer a { color:#bdc3cf; }
.auth-shell-with-bottom-link .auth-footer a:hover, .auth-shell-with-bottom-link .auth-footer a:focus-visible { color:var(--muted); }
.auth-footer a:focus-visible, .auth-switch a:focus-visible { outline:2px solid #4478FF; outline-offset:3px; }
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
.scenario-submit-footer .q-btn { width:100%; border-radius:8px; }
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
.shap-panel { gap:10px; }
.shap-note { font-size:12px; line-height:1.5; color:#78869a; }
.shap-tabs { color:#718099; border-bottom:1px solid #edf1f6; }
.shap-tabs .q-tab { padding:0 14px; min-height:38px; }
.shap-panels .q-tab-panel { padding:4px 0 0; }
.shap-table table { table-layout:fixed; width:100%; }
.shap-table th:first-child, .shap-table td:first-child { width:60%; }
.shap-table th { color:#78869a; font-size:12px; font-weight:400; }
.shap-table th, .shap-table td { padding:9px 12px; border-color:#edf1f6 !important; }
.shap-table td { font-size:13px; overflow-wrap:anywhere; font-variant-numeric:tabular-nums; }
.shap-impact { display:flex; flex-direction:column; gap:6px; color:#536174; }
.shap-track { position:relative; width:100%; height:7px; background:#f2f4f7; border-radius:2px; }
.shap-track::after { content:""; position:absolute; left:50%; top:-2px; bottom:-2px; width:1px; background:#bdc7d3; }
.shap-bar { position:absolute; top:0; height:7px; border-radius:2px; }
.shap-bar-positive { background:linear-gradient(to right,#e6bc9f,#ba6344); }
.shap-bar-negative { background:linear-gradient(to right,#328474,#abd2c8); }
@media(max-width:600px) { .shap-table th:first-child, .shap-table td:first-child { width:52%; } .shap-table th, .shap-table td { padding:8px 5px; font-size:12px; } }
.submitted-summary { gap:16px; }
.submitted-target { width:100%; align-items:center; gap:8px; padding:10px 12px; background:#f0f7f5; color:#287663; border-radius:9px; font-size:12px; }
.submitted-target-value { margin-left:auto; font-variant-numeric:tabular-nums; }
.submitted-costs { width:100%; gap:6px 24px; align-items:baseline; }
.submitted-cost { gap:6px; align-items:baseline; font-size:12px; }
.submitted-cost-label { color:#78869a; }
.submitted-cost-value { color:#43536b; font-variant-numeric:tabular-nums; white-space:nowrap; }
@media(max-width:600px) { .submitted-costs { flex-direction:column; gap:6px; } .submitted-cost { width:100%; justify-content:space-between; } }
.submitted-resources { display:grid; grid-template-columns:1.4fr 1fr 1fr; width:100%; gap:24px; padding:4px 0 8px; }
.submitted-resource { gap:4px; min-width:0; }
.submitted-resource-label { font-size:12px; color:var(--muted); }
.submitted-resource-value { font-size:20px; line-height:1.3; font-weight:500; font-variant-numeric:tabular-nums; }
.submitted-operations { width:100%; gap:0; font-size:14px; }
.submitted-list-title { font-size:13px; font-weight:500; color:#68758a; padding:4px 0 10px; }
.submitted-operation { display:grid; grid-template-columns:24px minmax(0,1fr) auto; width:100%; align-items:start; gap:10px; padding:12px 0; border-top:1px solid #edf1f6; }
.submitted-operation-index { color:#91a1b6; font-size:12px; line-height:20px; }
.submitted-operation-body { min-width:0; gap:3px; }
.submitted-operation-title { font-size:13px; line-height:20px; }
.submitted-operation-detail { color:#78869a; font-size:12px; line-height:1.5; overflow-wrap:anywhere; }
.submitted-operation-amount { font-size:13px; line-height:20px; font-weight:500; white-space:nowrap; font-variant-numeric:tabular-nums; }
@media(max-width:600px) {
 .submitted-resources { gap:12px; }
 .submitted-resource-value { font-size:17px; }
 .submitted-operation { grid-template-columns:18px minmax(0,1fr); gap:4px 8px; }
 .submitted-operation-amount { grid-column:2; }
}

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
.score-calculation { gap:10px; }
.score-breakdown { width:100%; }
.score-breakdown-row { display:flex; justify-content:space-between; align-items:baseline; gap:16px; padding:6px 0; font-size:13px; line-height:1.4; }
.score-breakdown-label { color:#718099; }
.score-breakdown-value { white-space:nowrap; font-variant-numeric:tabular-nums; color:#43516a; }
.score-breakdown-total { border-top:1px solid #edf1f6; margin-top:5px; padding-top:10px; font-weight:600; }
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
 .auth-form { padding:12px 24px 24px; }
 .workspace { padding:20px 14px; }
 .app-header { padding:14px 18px; }
}

.resource-overview { position:sticky; top:0; z-index:5; background:var(--paper); padding:12px; border-bottom:1px solid var(--line); }
.operation-card .q-expansion-item__content { padding:12px; }
.operation-card .q-item__label { overflow-wrap:anywhere; }
@media (max-width:600px) { .resource-grid { grid-template-columns:repeat(3,minmax(0,1fr)); } }

/* Active participant editor: compact, scoped independently of auth and results. */
.chain-workspace, .chain-picker-dialog { --accent:#2354D6; --ink:#252525; --muted:#696E82; --line:#EDEEF2; --q-primary:#2354D6; color:var(--ink); }
body:has(.chain-workspace) { background:radial-gradient(ellipse at center,#fff 25%,#f7f9fd 100%); }
body:has(.chain-workspace) .app-header { border-color:#EDEEF2; }
body:has(.chain-workspace) .brand { color:#2354D6; font-size:19px; }
.chain-workspace .participant-nav { gap:24px; border-bottom:1px solid var(--line); }
.chain-workspace .participant-nav a { padding:8px 0 12px; color:var(--muted); text-decoration:none; }
.chain-workspace .participant-nav a.selected { color:var(--accent); border-bottom:2px solid var(--accent); font-weight:600; }
.chain-workspace .scenario-layout { grid-template-columns:minmax(0,1fr) 320px; gap:24px; }
.chain-workspace .scenario-editor { gap:14px; }
.chain-workspace .resource-overview { padding:0; background:transparent; border:0; position:static; }
.resource-summary { width:100%; display:grid; grid-template-columns:minmax(0,1fr) 230px; align-items:center; gap:36px; padding:8px 0 12px; }
.resource-balance { gap:7px; min-width:0; }
.resource-caption { font-size:12px; line-height:17px; color:#737d8e; }
.resource-amount-row { gap:5px; align-items:baseline; flex-wrap:nowrap; }
.resource-amount { font-size:30px; line-height:36px; font-weight:500; letter-spacing:-.9px; color:#25334c; font-variant-numeric:tabular-nums; white-space:nowrap; }
.resource-currency { font-size:21px; color:#8993a3; }
.resource-meters { width:100%; gap:14px; }
.resource-meter { width:100%; gap:6px; }
.resource-meter-heading { width:100%; align-items:center; justify-content:space-between; gap:12px; }
.resource-meter-value { font-size:13px; line-height:17px; color:#46546c; font-variant-numeric:tabular-nums; }
.resource-meter-bar { color:#8aa3e3 !important; border-radius:3px; overflow:hidden; }
.resource-meter-bar .q-linear-progress__track { background:#e8edf6; opacity:1; }
.resource-summary .resource-negative { color:#b83b39; }
.chain-toolbar { width:100%; align-items:center; gap:10px; }
.chain-toolbar .q-btn { min-height:40px; border-radius:9px; }
.chain-workspace .chain-add { background:linear-gradient(120deg,#3263dd,#2354D6) !important; box-shadow:0 3px 8px #2354d61a; }
.chain-workspace .chain-order { color:var(--muted) !important; }
.chain-section-label { font-size:12px; color:var(--muted); margin-top:2px; }
.chain-workspace .operation-card { padding:0; background:#fff; border:1px solid #e5e9f1; border-radius:12px; overflow:hidden; box-shadow:0 3px 12px #192b4605; }
.chain-workspace .operation-card > .q-expansion-item__container > .q-item { padding:14px 16px; min-height:70px; }
.chain-workspace .operation-card > .q-expansion-item__container > .q-item .q-item__label { font-weight:500; line-height:1.5 !important; }
.chain-workspace .operation-card .q-item__label--caption { color:var(--muted); font-size:12px; font-weight:400 !important; }
.chain-workspace .operation-card > .q-expansion-item__container > .q-expansion-item__content { padding:0 16px 16px; }
.chain-workspace .operation-heading { min-width:0; gap:3px; }
.chain-workspace .operation-heading-amount { white-space:nowrap; font-variant-numeric:tabular-nums; }
.chain-workspace .operation-name { gap:3px 10px; align-items:baseline; font-size:15px; font-weight:500; line-height:1.45; color:#253247; }
.chain-workspace .operation-caption { font-size:12px; line-height:1.4; color:#7a8597; }
.chain-workspace .operation-actions-slot { padding-left:12px; }
.chain-workspace .operation-actions { flex-wrap:nowrap; gap:2px; }
.chain-workspace .operation-actions .q-btn { width:32px; min-width:32px; height:32px; color:#7c899e !important; border-radius:7px; }
.chain-workspace .operation-actions .q-icon { font-size:19px; }
.chain-workspace .operation-actions .q-btn:hover { color:#2354d6 !important; background:#f1f5fc; }
.chain-workspace .operation-actions .operation-delete:hover { color:#b44d4d !important; background:#fff3f2; }
.chain-workspace .operation-fields { gap:14px 16px; padding-top:4px; }
.chain-workspace .operation-timing { width:100%; gap:5px; }
.chain-workspace .operation-moment { font-size:11px; color:#7a8597; padding-left:1px; }
@media (max-width:700px) {
 .chain-workspace .operation-card > .q-expansion-item__container > .q-item { flex-wrap:wrap; gap:6px 0; }
 .chain-workspace .operation-heading { flex-basis:calc(100% - 40px); }
 .chain-workspace .operation-actions-slot { order:3; flex-basis:100%; padding-left:0; align-items:flex-end; }
 .chain-workspace .operation-actions .q-btn { width:36px; min-width:36px; height:36px; }
 .chain-workspace .operation-fields { grid-template-columns:1fr; gap:12px; }
}
.chain-workspace .q-field--outlined .q-field__control:before { border-color:#C8CCDB; }
.chain-workspace .q-field__label { color:var(--muted); }
.chain-workspace .scenario-summary { padding:20px; border:1px solid #e5e9f1; border-radius:16px; background:linear-gradient(160deg,#fff 65%,#fafbff); box-shadow:0 10px 28px #2354d60a; gap:12px; }
.chain-workspace .scenario-goal { background:transparent; padding:0 0 4px; gap:8px; }
.goal-value-row { width:100%; justify-content:space-between; align-items:baseline; gap:8px; }
.goal-amount-row { align-items:baseline; gap:5px; }
.goal-amount { font-size:26px; line-height:32px; font-weight:500; letter-spacing:-.5px; color:#2354D6; font-variant-numeric:tabular-nums; }
.goal-currency { font-size:15px; color:#788399; }
.goal-percent { font-size:12px; color:#7c8ca6; }
.goal-target { font-size:11px; }
.scenario-fees { width:100%; justify-content:space-between; align-items:baseline; font-size:12px; padding:0 0 16px; border-bottom:1px solid #eff1f6; }
.scenario-submit-footer { width:100%; gap:5px; }
.chain-workspace .scenario-submit-footer .save-indicator { font-size:10px; line-height:14px; color:#a6afbe; text-align:right; padding:0 2px; }
.scenario-corrections { width:100%; gap:12px; padding:12px; margin-top:10px; border-radius:8px; background:#fff8f3; border-left:3px solid #d59672; }
.corrections-heading { font-size:13px; font-weight:600; color:#a25431; margin-bottom:2px; }
.correction-row { width:100%; align-items:flex-start; flex-wrap:nowrap; gap:9px; }
.correction-step { flex-shrink:0; padding:2px 6px; display:flex; align-items:center; justify-content:center; border-radius:5px; background:#f7e8dc; color:#975132; font-size:11px; font-weight:500; line-height:18px; white-space:nowrap; }
.correction-row .correction-step-link { flex:0 0 auto; width:auto; min-width:0; min-height:22px; padding:2px 6px; border-radius:5px; color:#975132 !important; cursor:pointer; }
.correction-step-link:hover { background:#efd6c3; }
.correction-step-link:focus-visible { outline:2px solid #a25431; outline-offset:2px; }
.operation-card { scroll-margin-block:24px; }
[data-correction-highlight] { animation:correction-highlight 2.2s ease-out; }
@keyframes correction-highlight {
  0%, 35% { box-shadow:0 0 0 2px #d59672; background-color:#fff8f3; }
  100% { box-shadow:0 0 0 2px transparent; }
}
@media (prefers-reduced-motion:reduce) {
  [data-correction-highlight] { animation:none; outline:2px solid #d59672; outline-offset:2px; }
}
.correction-text { flex:1; min-width:0; font-size:12px; line-height:18px; color:#65534b; overflow-wrap:anywhere; }
.chain-workspace .summary-details > .q-expansion-item__container > .q-item { padding:8px 0; min-height:36px; font-size:13px; }
.chain-workspace .summary-details .q-expansion-item__content { padding-top:6px; }
.chain-workspace .has-blockers > .q-expansion-item__container > .q-item { color:#a34b28; }
.chain-workspace .has-blockers .q-item__section--avatar { min-width:30px; padding-right:8px; }
.chain-workspace .has-blockers .q-item__section--avatar .q-icon { font-size:19px; }
.chain-workspace .submission-conditions { padding-top:0; border:0; margin:0; gap:8px; }
.chain-workspace .submission-conditions .section-caption { display:block; }
.chain-workspace .condition-row, .chain-workspace .condition-value { font-size:12px; }
.chain-workspace .submit-scenario { min-height:44px; }
.chain-workspace .submit-scenario:not(.disabled) { background:linear-gradient(120deg,#3263dd,#2354D6) !important; }
.chain-empty { width:100%; padding:32px 20px; align-items:center; gap:10px; border:1px dashed #ccd5e4; border-radius:12px; color:var(--muted); background:#ffffffb3; }
.chain-picker-dialog { padding:24px; gap:12px; border-radius:16px; }
.chain-picker-dialog .operation-choice { width:100%; min-height:52px; border-color:#EDEEF2; border-radius:10px; }
.chain-picker-dialog .operation-choice .q-btn__content { justify-content:flex-start; text-align:left; }
.chain-workspace a:focus-visible, .chain-workspace .q-btn:focus-visible { outline:2px solid #4478FF; outline-offset:3px; }
@media (max-width:900px) {
 .chain-workspace .scenario-layout { grid-template-columns:minmax(0,1fr); }
 .chain-workspace .scenario-summary { position:static; grid-row:1; }
 .chain-workspace .resource-overview { position:static; }
}
@media (max-width:480px) {
 .resource-summary { grid-template-columns:minmax(0,1fr) minmax(110px,.8fr); gap:18px; padding:4px 0 8px; }
 .resource-amount { font-size:22px; line-height:30px; letter-spacing:-.6px; }
 .resource-currency { font-size:16px; }
 .chain-toolbar .q-btn { flex:1; font-size:12px; }
 .chain-workspace .operation-card > .q-expansion-item__container > .q-item { padding:12px; }
}
.chain-catalog { width:100%; display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:6px; padding:0; background:transparent; border:0; box-shadow:none; }
.chain-workspace .chain-catalog .operation-choice { width:100%; min-height:58px; padding:8px 4px; border-radius:8px; box-shadow:none; border:0; background:#eef2f9 !important; color:#526078 !important; transition:background .15s,color .15s; }
.chain-workspace .chain-catalog .operation-choice:hover { background:#f0f5ff !important; color:#2354D6 !important; border-color:#cedcf8; }
.chain-catalog .operation-choice .q-btn__content { flex-direction:column; justify-content:center; text-align:center; font-size:12px; font-weight:400; gap:4px; color:#43516b; }
.chain-catalog .operation-choice .q-icon { width:20px !important; height:20px !important; font-size:18px !important; background:transparent !important; }
.section-caption { color:#696E82; font-size:13px; font-weight:600; }
.expense-summary { gap:6px; padding:12px 0; border-bottom:1px solid #EDEEF2; }
.expense-summary .text-sm { font-size:12px; }
.expense-row { width:100%; justify-content:space-between; gap:4px 8px; font-size:12px; }
.expense-row > :last-child { font-variant-numeric:tabular-nums; }
.open-conditions { gap:8px; }
.chain-workspace .condition-help { padding:7px 0 7px 9px; border-left:2px solid #e5bbaa; border-radius:0; background:transparent; }
.chain-workspace .correction-title { color:#a34b28; margin-top:10px; }
.chain-workspace .scenario-summary { position:static; }
.profile-workspace { --accent:#2354D6; --muted:#696E82; --line:#EDEEF2; --q-primary:#2354D6; color:#252525; }
.profile-workspace .participant-nav { gap:24px; border-bottom:1px solid #EDEEF2; }
.profile-workspace .participant-nav a { padding:8px 0 12px; color:#696E82; text-decoration:none; }
.profile-workspace .participant-nav a.selected { color:#2354D6; border-bottom:2px solid #2354D6; font-weight:600; }
.profile-section { width:100%; min-width:0; padding:24px; gap:14px; background:#fff; border:1px solid #e5e9f1; border-radius:16px; box-shadow:0 8px 24px #2354d608; }
.profile-section-title { font-size:18px; font-weight:600; color:#2354D6; }
.rules-page { gap:14px; padding:20px 24px; }
.rules-page .profile-subsection { padding-top:12px; gap:6px; }
.rules-page > .rules-columns { padding-top:12px; }
.rules-page > .rules-columns .rules-heading { margin-bottom:4px; }
.rules-columns { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); width:100%; gap:32px; }
.rules-section { width:100%; gap:2px; min-width:0; }
.rules-heading { font-size:14px; font-weight:600; color:#35435a; }
.rules-fact { width:100%; align-items:baseline; justify-content:space-between; flex-wrap:nowrap; gap:12px; padding:2px 0; font-size:13px; }
.rules-fact-label { color:#68758a; }
.rules-fact-value { text-align:right; font-variant-numeric:tabular-nums; }
.rules-note { color:#788399; font-size:12px; line-height:1.5; }
.rules-operations-table th { color:#7a8597; font-size:12px; font-weight:400; }
.rules-operations-table td { font-size:13px; font-variant-numeric:tabular-nums; border-color:#eff2f7 !important; }
.rules-operations-table th, .rules-operations-table td { padding:8px 12px !important; }
.rules-operations-table th:first-child, .rules-operations-table td:first-child { padding-left:0 !important; }
.rules-operations-table th:last-child, .rules-operations-table td:last-child { padding-right:0 !important; }
.rules-operations-mobile { display:none; width:100%; gap:14px; }
.rules-operation-mobile { width:100%; gap:3px; padding-bottom:16px; border-bottom:1px solid #eff1f6; }
@media(max-width:700px) { .rules-operations-table { display:none; } .rules-operations-mobile { display:flex; } }
@media(max-width:700px) { .rules-columns { grid-template-columns:minmax(0,1fr); gap:16px; } .rules-fact { flex-wrap:wrap; } .rules-costs { gap:4px; } }
.profile-description { max-width:80ch; line-height:1.65; color:#526078; }
.profile-overview { width:100%; gap:8px; }
.profile-overview .profile-description { max-width:none; font-size:14px; line-height:1.5; }
.profile-period { font-size:12px; color:#696E82; line-height:1.5; }
.profile-totals { max-width:600px; }
.profile-totals .profile-metric { padding:10px 14px; gap:3px; }
.profile-subsection { width:100%; min-width:0; gap:10px; padding-top:20px; border-top:1px solid #EDEEF2; }
.profile-fact { width:100%; padding:16px; gap:7px; border:1px solid #EDEEF2; border-radius:10px; background:#fafbfe; }
.fact-status { font-size:12px; font-weight:500; color:#526078; background:#edf2fa; padding:4px 8px; border-radius:6px; }
.profile-history-table { min-width:0; overflow:auto; }
.profile-metrics { width:100%; display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; }
.profile-metric { padding:12px 14px; gap:5px; background:#f5f7fc; border-radius:10px; }
.profile-party-row { width:100%; align-items:baseline; justify-content:space-between; gap:8px; padding:8px 0; border-bottom:1px solid #f0f2f6; }
.fact-details-grid { width:100%; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px 24px; }
.fact-detail { gap:3px; min-width:0; }
body:has(.profile-workspace) { background:radial-gradient(ellipse at center,#fff 25%,#f7f9fd 100%); }
body:has(.profile-workspace) .brand { color:#2354D6; font-size:19px; }
@media (max-width:600px) {
 .chain-catalog { grid-template-columns:repeat(3,minmax(0,1fr)); }
 .profile-section { padding:16px; }
 .fact-details-grid { grid-template-columns:minmax(0,1fr); }
 .chain-workspace .scenario-summary { grid-row:auto; }
}

/* Shared touch, keyboard and small-screen contract. */
*, *::before, *::after { box-sizing:border-box; }
.workspace, .panel, .q-tab-panel, .q-dialog__inner > div { min-width:0; }
.workspace { overflow-wrap:anywhere; }
button:focus-visible, a:focus-visible, input:focus-visible, [tabindex]:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
.header-exit, .header-text-link, .participant-nav a, .q-btn { min-height:44px; min-width:44px; }
.chain-workspace .operation-actions .operation-menu-button { width:auto; min-width:108px; height:44px; }
.operation-menu { display:flex; flex-direction:column; padding:6px; max-width:calc(100vw - 24px); }
.operation-menu .q-btn { justify-content:flex-start; min-height:44px; }
.operation-menu .q-btn__content { justify-content:flex-start; }
.q-dialog__inner > .q-card { max-height:calc(100dvh - 32px); overflow-y:auto; overflow-wrap:anywhere; }
.q-table__container { max-width:100%; }
.q-table__middle { overflow-x:auto; }
.chain-workspace .save-indicator { font-size:13px; text-align:left; color:var(--ink); }
.open-conditions > .q-expansion-item__container > .q-item { min-height:44px; padding:4px 0; }
@media (max-width:700px) {
 .workspace { padding:16px max(12px,env(safe-area-inset-right)) max(24px,env(safe-area-inset-bottom)) max(12px,env(safe-area-inset-left)); }
 .chain-workspace .scenario-layout { display:flex; flex-direction:column; gap:16px; }
 .chain-workspace .scenario-summary { order:-1; width:100%; padding:14px; gap:8px; }
 .chain-workspace .scenario-editor { width:100%; min-width:0; }
 .chain-workspace .scenario-summary .goal-amount { font-size:22px; line-height:28px; }
 .chain-workspace .scenario-summary .scenario-fees { padding:0; font-size:12px; }
 .chain-workspace .operation-actions-slot { flex-basis:auto; margin-left:auto; }
 .chain-workspace .operation-card > .q-expansion-item__container > .q-item { padding:10px 12px; }
 .chain-catalog { grid-template-columns:repeat(2,minmax(0,1fr)); }
 .header-user-name { max-width:55%; overflow-wrap:anywhere; }
 .app-header { gap:8px; }
 .header-identity { flex-wrap:wrap; }
 .header-game-title { white-space:normal; border:0; padding-left:0; }
 .q-tab { min-width:0; padding:0 10px; }
 .auth-shell { padding:20px 12px max(56px,env(safe-area-inset-bottom)); }
 .auth-shell-with-bottom-link .auth-footer { position:static; margin-top:16px; }
 .auth-shell-with-bottom-link { flex-direction:column; }
}
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
        ui.element("main").classes(
            "auth-shell auth-shell-with-bottom-link" if audience == "play" else "auth-shell"
        ),
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
