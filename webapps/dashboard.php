<?php
// Hermes / RQDB4AI Worker Dashboard
$api_base = 'https://aixec.exbridge.jp/api.php?path=';
$allowed_workers = array(
    'url2ai-polymarket-enqueue' => true,
    'url2ai-oss-enqueue' => true,
    'url2ai-finreport-enqueue' => true,
    'buzblogger-enqueue' => true,
    'horizon-worker-enqueue' => true,
    'aixec-market-pipeline-enqueue' => true,
    'aixec-register-market-worker-enqueue' => true,
    'aixec-growth-agent-enqueue' => true,
);

function dash_h($value) {
    return htmlspecialchars((string)$value, ENT_QUOTES, 'UTF-8');
}

function dash_fetch_json($path) {
    global $api_base;
    $url = $api_base . $path;
    $context = stream_context_create(array(
        'http' => array(
            'timeout' => 8,
            'header' => "User-Agent: Hermes-Dashboard/1.0\r\n"
        )
    ));
    $raw = @file_get_contents($url, false, $context);
    if ($raw === false || $raw === '') {
        return array();
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : array();
}

function dash_badge($status) {
    $status = (string)$status;
    $class = $status === 'ok' ? 'ok' : ($status === 'running' || $status === 'queued' ? 'warn' : 'down');
    return '<span class="badge ' . $class . '">' . dash_h($status ?: '-') . '</span>';
}

function render_ollama($data) {
    $servers = isset($data['servers']) && is_array($data['servers']) ? $data['servers'] : array();
    if (!$servers) return '<div class="status-msg">Ollama情報なし</div>';
    $html = '<table><thead><tr><th>サーバー</th><th>IP</th><th>状態</th><th>モデル</th></tr></thead><tbody>';
    foreach ($servers as $s) {
        $status = isset($s['status']) ? $s['status'] : '';
        $dot = $status === 'ok' ? 'dot-ok' : 'dot-down';
        $models = '';
        if (isset($s['models']) && is_array($s['models'])) {
            foreach ($s['models'] as $m) $models .= '<span class="model-tag">' . dash_h($m) . '</span>';
        }
        $html .= '<tr><td><span class="cell-label">サーバー</span><span class="dot ' . $dot . '"></span><span class="worker-name">' . dash_h(isset($s['name']) ? $s['name'] : '') . '</span></td><td class="url-cell"><span class="cell-label">IP</span>' . dash_h(isset($s['url']) ? $s['url'] : '') . '</td><td><span class="cell-label">状態</span>' . dash_badge($status) . '</td><td><span class="cell-label">モデル</span>' . ($models ?: '-') . '</td></tr>';
    }
    return $html . '</tbody></table>';
}

function render_workers($data) {
    global $allowed_workers;
    $workers = isset($data['workers']) && is_array($data['workers']) ? $data['workers'] : array();
    $workers = array_intersect_key($workers, $allowed_workers);
    if (!$workers) return '<div class="status-msg">報告なし</div>';
    uasort($workers, function($a, $b) {
        $ta = strtotime(isset($a['reported_at']) ? $a['reported_at'] : '') ?: 0;
        $tb = strtotime(isset($b['reported_at']) ? $b['reported_at'] : '') ?: 0;
        return $tb <=> $ta;
    });
    $html = '<table><thead><tr><th>Worker</th><th>状態</th><th>件数</th><th>最終実行</th><th>メモ</th></tr></thead><tbody>';
    foreach ($workers as $name => $w) {
        $html .= '<tr><td><span class="cell-label">Worker</span><span class="worker-name">' . dash_h($name) . '</span></td><td><span class="cell-label">状態</span>' . dash_badge(isset($w['status']) ? $w['status'] : '') . '</td><td><span class="cell-label">件数</span>' . dash_h(isset($w['items']) ? $w['items'] : '-') . '</td><td><span class="cell-label">最終実行</span>' . dash_h(isset($w['reported_at']) ? $w['reported_at'] : '-') . '</td><td><span class="cell-label">メモ</span>' . dash_h(isset($w['note']) ? $w['note'] : '-') . '</td></tr>';
    }
    return $html . '</tbody></table>';
}

function render_schedule($data) {
    global $allowed_workers;
    $workers = isset($data['schedule']['workers']) && is_array($data['schedule']['workers']) ? $data['schedule']['workers'] : array();
    $workers = array_values(array_filter($workers, function($w) use ($allowed_workers) {
        return isset($w['name']) && isset($allowed_workers[$w['name']]);
    }));
    if (!$workers) return '<div class="status-msg">スケジュールなし</div>';
    $html = '<table><thead><tr><th>時刻</th><th>Worker</th><th>Hermes</th><th>前回実行</th><th>内容</th></tr></thead><tbody>';
    foreach ($workers as $w) {
        $last_status = isset($w['last_status']) ? $w['last_status'] : '-';
        $last_class = $last_status === 'ok' ? 'ok' : ($last_status === 'error' ? 'down' : 'warn');
        $last_run = isset($w['last_run_at']) ? preg_replace('/T/', ' ', substr($w['last_run_at'], 0, 16)) : '-';
        $html .= '<tr><td><span class="cell-label">時刻</span><strong>' . dash_h(isset($w['time']) ? $w['time'] : '') . '</strong></td><td><span class="cell-label">Worker</span><span class="worker-name">' . dash_h(isset($w['name']) ? $w['name'] : '') . '</span></td><td><span class="cell-label">Hermes</span><span class="badge ' . $last_class . '">' . dash_h($last_status) . '</span></td><td><span class="cell-label">前回実行</span>' . dash_h($last_run) . '</td><td class="muted"><span class="cell-label">内容</span>' . dash_h(isset($w['note']) ? $w['note'] : '') . '</td></tr>';
    }
    return $html . '</tbody></table>';
}

$initial_ollama = dash_fetch_json('ollama/status');
$initial_workers = dash_fetch_json('worker/status');
$initial_schedule = dash_fetch_json('schedule');
?><!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hermes Worker Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans JP',sans-serif;background:#f6f8fb;color:#172033;padding:18px;line-height:1.55}
.shell{max-width:1180px;margin:0 auto}
.top{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:18px}
h1{font-size:24px;font-weight:900;color:#172033;letter-spacing:0}
h1 span{display:block;font-size:12px;font-weight:700;color:#6b7280;margin-top:3px}
h2{font-size:14px;font-weight:900;color:#334155;margin-bottom:12px;display:flex;align-items:center;justify-content:space-between;gap:10px}
.grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;margin-bottom:20px}
.card{background:#fff;border:1px solid #e5eaf0;border-radius:14px;padding:16px;box-shadow:0 8px 24px rgba(15,23,42,.05)}
.full{grid-column:1/-1}
table{width:100%;border-collapse:separate;border-spacing:0;font-size:13px}
th{text-align:left;padding:9px 10px;color:#64748b;font-weight:800;border-bottom:1px solid #e5eaf0;background:#f8fafc}
td{padding:10px;border-bottom:1px solid #eef2f6;vertical-align:top}
tr:last-child td{border-bottom:0}
tr:hover td{background:#fbfdff}
.badge{display:inline-flex;align-items:center;padding:3px 9px;border-radius:999px;font-size:11px;font-weight:900;white-space:nowrap}
.ok{background:#dcfce7;color:#166534}
.down{background:#fee2e2;color:#991b1b}
.warn{background:#fef3c7;color:#92400e}
.now-row td{background:#eff6ff!important;border-top:1px solid #bfdbfe;border-bottom:1px solid #bfdbfe}
.now-row td:first-child{border-left:4px solid #2563eb}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px}
.dot-ok{background:#22c55e}
.dot-down{background:#ef4444}
.dot-warn{background:#f59e0b}
.refresh{font-size:12px;color:#94a3b8;font-weight:700;white-space:nowrap}
.clock-card{text-align:right}
#clock{font-size:30px;font-weight:900;color:#2563eb;line-height:1}
#date{font-size:13px;color:#64748b;margin-top:5px}
.model-tag{background:#eef6ff;color:#1d4ed8;border:1px solid #dbeafe;padding:2px 7px;border-radius:999px;font-size:11px;margin:2px;display:inline-block}
.metric-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:8px 0 12px}
.metric{background:#f8fafc;border:1px solid #e5eaf0;border-radius:10px;padding:12px}
.metric b{display:block;color:#2563eb;font-size:22px;line-height:1.1}
.metric span{display:block;color:#64748b;font-size:11px;margin-top:4px;font-weight:700}
.muted{color:#64748b;font-size:12px}
.item-list{margin-top:10px;border-top:1px solid #e5eaf0;padding-top:8px}
.item-list div{font-size:12px;color:#334155;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:4px 0}
.status-msg{color:#64748b;font-size:13px;background:#f8fafc;border:1px solid #e5eaf0;border-radius:10px;padding:12px}
.cell-label{display:none}
.worker-name{font-weight:800;color:#0f172a}
.url-cell{font-size:11px;color:#64748b;word-break:break-all}
@media(max-width:760px){
  body{padding:12px;background:#fff}
  .top{align-items:flex-start;margin-bottom:12px}
  h1{font-size:20px}
  .clock-card{display:none}
  .grid{grid-template-columns:1fr;gap:12px}
  .card{border-radius:12px;padding:14px;box-shadow:none}
  .metric-grid{grid-template-columns:repeat(2,1fr)}
  table,thead,tbody,tr,td{display:block;width:100%}
  thead{display:none}
  tr{border:1px solid #e5eaf0;border-radius:12px;margin:8px 0;padding:9px 10px;background:#fff}
  td{border:0;padding:5px 0}
  tr:hover td{background:transparent}
  .now-row{background:#eff6ff;border-color:#bfdbfe}
  .now-row td{background:transparent!important;border:0}
  .now-row td:first-child{border-left:0}
  .cell-label{display:inline-block;min-width:74px;color:#94a3b8;font-size:11px;font-weight:800}
  .item-list div{white-space:normal}
}
</style>
</head>
<body>
<div class="shell">
<div class="top">
  <h1>Hermes Worker Dashboard<span>RQDB4AIジョブ投入・Worker実行結果・Ollama稼働状況</span></h1>
  <div class="clock-card"><div id="clock"></div><div id="date"></div></div>
</div>
<div class="grid">
  <div class="card">
    <h2>Ollama サーバー <span class="refresh" id="ollama-updated"></span></h2>
    <div id="ollama-status"><?php echo render_ollama($initial_ollama); ?></div>
  </div>
  <div class="card">
    <h2>Worker 最終実行 <span class="refresh" id="worker-updated"></span></h2>
    <div id="worker-status"><?php echo render_workers($initial_workers); ?></div>
  </div>
  <div class="card full">
    <h2>本日のスケジュール <span class="refresh" id="schedule-updated"></span></h2>
    <div id="schedule"><?php echo render_schedule($initial_schedule); ?></div>
  </div>
</div>
</div>
<script>
const API = 'https://aixec.exbridge.jp/api.php?path=';
const ALLOWED_WORKERS = new Set([
  'url2ai-polymarket-enqueue',
  'url2ai-oss-enqueue',
  'url2ai-finreport-enqueue',
  'buzblogger-enqueue',
  'horizon-worker-enqueue',
  'aixec-market-pipeline-enqueue',
  'aixec-register-market-worker-enqueue',
  'aixec-growth-agent-enqueue'
]);

function fmt(s){return s||'-'}
function esc(s){
  return String(s ?? '').replace(/[&<>"']/g, m => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[m]));
}
function now_hhmm(){
  const d=new Date();
  return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');
}

function updateClock(){
  const d=new Date();
  document.getElementById('clock').textContent=
    String(d.getHours()).padStart(2,'0')+':'+
    String(d.getMinutes()).padStart(2,'0')+':'+
    String(d.getSeconds()).padStart(2,'0');
  document.getElementById('date').textContent=
    d.getFullYear()+'/'+(d.getMonth()+1)+'/'+d.getDate()+'（'+['日','月','火','水','木','金','土'][d.getDay()]+'）';
}
setInterval(updateClock,1000);updateClock();

async function loadOllama(){
  try{
    const r=await fetch(API+'ollama/status');
    const d=await r.json();
    const servers=d.servers||[];
    let html='<table><thead><tr><th>サーバー</th><th>IP</th><th>状態</th><th>モデル</th></tr></thead><tbody>';
    for(const s of servers){
      const ok=s.status==='ok';
      const dot=ok?'dot-ok':'dot-down';
      const badge=ok?'ok':'down';
      const models=(s.models||[]).map(m=>`<span class="model-tag">${m}</span>`).join('')||'-';
      html+=`<tr><td><span class="cell-label">サーバー</span><span class="dot ${dot}"></span><span class="worker-name">${esc(s.name)}</span></td><td class="url-cell"><span class="cell-label">IP</span>${esc(s.url)}</td><td><span class="cell-label">状態</span><span class="badge ${badge}">${esc(s.status)}</span></td><td><span class="cell-label">モデル</span>${models}</td></tr>`;
    }
    html+='</tbody></table>';
    document.getElementById('ollama-status').innerHTML=html;
    document.getElementById('ollama-updated').textContent='更新: '+now_hhmm();
  }catch(e){document.getElementById('ollama-status').innerHTML='<div class="status-msg" style="color:#991b1b;background:#fef2f2;border-color:#fecaca">取得失敗</div>';}
}

async function loadWorkerStatus(){
  try{
    const r=await fetch(API+'worker/status');
    const d=await r.json();
    const ws=d.workers||{};
    const keys=Object.keys(ws).filter(name => ALLOWED_WORKERS.has(name));
    if(!keys.length){document.getElementById('worker-status').innerHTML='<div class="status-msg">報告なし</div>';return;}
    let html='<table><thead><tr><th>Worker</th><th>状態</th><th>件数</th><th>最終実行</th><th>メモ</th></tr></thead><tbody>';
    const sortedKeys=keys.sort((a,b)=>{
      const ta=Date.parse((ws[a]&&ws[a].reported_at)||'')||0;
      const tb=Date.parse((ws[b]&&ws[b].reported_at)||'')||0;
      if(tb!==ta) return tb-ta;
      return a.localeCompare(b);
    });
    for(const name of sortedKeys){
      const w=ws[name];
      const badge=w.status==='ok'?'ok':(w.status==='running'?'warn':'down');
      html+=`<tr><td><span class="cell-label">Worker</span><span class="worker-name">${esc(name)}</span></td><td><span class="cell-label">状態</span><span class="badge ${badge}">${esc(w.status)}</span></td><td><span class="cell-label">件数</span>${esc(w.items??'-')}</td><td><span class="cell-label">最終実行</span>${esc(fmt(w.reported_at))}</td><td><span class="cell-label">メモ</span>${esc(fmt(w.note))}</td></tr>`;
    }
    html+='</tbody></table>';
    document.getElementById('worker-status').innerHTML=html;
    document.getElementById('worker-updated').textContent='更新: '+now_hhmm();
  }catch(e){document.getElementById('worker-status').innerHTML='<div class="status-msg" style="color:#991b1b;background:#fef2f2;border-color:#fecaca">取得失敗</div>';}
}

async function loadSchedule(){
  try{
    const r=await fetch(API+'schedule');
    const d=await r.json();
    const workers=(d.schedule?.workers||[]).filter(w => ALLOWED_WORKERS.has(w.name));
    const cur=now_hhmm();
    let html='<table><thead><tr><th>時刻</th><th>Worker</th><th>Hermes</th><th>前回実行</th><th>内容</th></tr></thead><tbody>';
    for(const w of workers){
      const isNow=cur>=w.time&&(workers[workers.indexOf(w)+1]?cur<workers[workers.indexOf(w)+1].time:true);
      const rowCls=isNow?' class="now-row"':'';
      const hs=w.last_status||'-';
      const hcls=hs==='ok'?'ok':(hs==='error'?'down':'warn');
      const last=(w.last_run_at||'-').replace('T',' ').slice(0,16);
      html+=`<tr${rowCls}><td><span class="cell-label">時刻</span><strong>${esc(w.time)}</strong></td><td><span class="cell-label">Worker</span><span class="worker-name">${esc(w.name)}</span></td><td><span class="cell-label">Hermes</span><span class="badge ${hcls}">${esc(hs)}</span></td><td><span class="cell-label">前回実行</span>${esc(last)}</td><td class="muted"><span class="cell-label">内容</span>${esc(w.note||'')}</td></tr>`;
    }
    html+='</tbody></table>';
    document.getElementById('schedule').innerHTML=html;
    document.getElementById('schedule-updated').textContent='更新: '+now_hhmm();
  }catch(e){document.getElementById('schedule').innerHTML='<div class="status-msg" style="color:#991b1b;background:#fef2f2;border-color:#fecaca">取得失敗</div>';}
}

function loadAll(){loadOllama();loadWorkerStatus();loadSchedule();}
loadAll();
setInterval(loadOllama,30000);
setInterval(loadWorkerStatus,15000);
setInterval(loadSchedule,60000);
</script>
</body>
</html>
