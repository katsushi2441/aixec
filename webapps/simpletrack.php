<?php
date_default_timezone_set("Asia/Tokyo");

$logfile = __DIR__ . "/access.log";
define("SIMPLETRACK_INTERNAL_KEY", "aixec-go-track-v1");

function st_is_bot_ua($ua){
    $ua = strtolower(trim((string)$ua));
    if($ua === "") return true;
    $bot_words = array(
        "bot", "crawler", "spider", "slurp", "crawl", "mediapartners",
        "curl", "wget", "python", "httpclient", "scrapy", "headless",
        "phantom", "selenium", "playwright", "puppeteer",
        "facebookexternalhit", "meta-externalagent", "twitterbot", "slackbot", "discordbot",
        "linebot", "googlebot", "googleother", "google-read-aloud", "bingbot", "duckduckbot", "baiduspider",
        "yandexbot", "ahrefsbot", "semrushbot", "mj12bot", "petalbot",
        "bytespider", "claudebot", "gptbot", "oai-searchbot", "ccbot", "perplexitybot",
        "applebot", "amazonbot"
    );
    foreach($bot_words as $word){
        if(strpos($ua, $word) !== false) return true;
    }
    return false;
}

/* =========================
   ダッシュボードモード
========================= */
if(isset($_GET["dashboard"])){

    clearstatcache();   // ← ここに追加
    if(!function_exists("h")){
        function h($value){
            return htmlspecialchars((string)$value, ENT_QUOTES, "UTF-8");
        }
    }

    if(!file_exists($logfile)){
        die("log not found");
    }

    $range = isset($_GET["range"]) ? $_GET["range"] : "all";
    $range_days = array("1d" => 1, "7d" => 7, "30d" => 30, "90d" => 90);
    if(!isset($range_days[$range]) && $range !== "all"){
        $range = "all";
    }
    $range_start_ts = null;
    if($range !== "all"){
        $range_start_ts = ($range === "1d") ? strtotime("-24 hours") : strtotime("-" . ($range_days[$range] - 1) . " days 00:00:00");
    }
    $range_labels = array(
        "1d" => "直近24時間",
        "7d" => "直近1週間",
        "30d" => "直近30日",
        "90d" => "直近3か月",
        "all" => "すべて",
    );

    $pv_per_day = array();
    $url_count = array();
    $ref_count = array();
    $go_product_count = array();
    $go_from_count = array();
    $lines = file($logfile);


    foreach($lines as $line){

        $parts = explode(" | ", trim($line));
        if(count($parts) < 5) continue;

        $date = substr($parts[0],0,10);
        $url  = $parts[2];
        $ref  = $parts[3];
        $ua   = isset($parts[4]) ? $parts[4] : "";

        if(st_is_bot_ua($ua)) continue;
        $ts = strtotime($parts[0]);
        if($range_start_ts !== null && (!$ts || $ts < $range_start_ts)) continue;

        if(!isset($pv_per_day[$date])) $pv_per_day[$date] = 0;
        $pv_per_day[$date]++;

        if($url !== ""){
            $parsed_url = parse_url($url);
            $path = isset($parsed_url["path"]) ? $parsed_url["path"] : "";
            $is_go_php = ($path === "/go.php" || substr($path, -7) === "/go.php");
            $skip_dashboard_url = false;
            if($is_go_php){
                $params = array();
                if(!empty($parsed_url["query"])){
                    parse_str($parsed_url["query"], $params);
                }
                $to = isset($params["to"]) ? strtolower((string)$params["to"]) : "";
                if($to === "" && isset($params["click"])) $to = strtolower((string)$params["click"]);
                $kw = isset($params["kw"]) ? trim((string)$params["kw"]) : "";
                $pid = isset($params["product_id"]) ? trim((string)$params["product_id"]) : "";
                if($pid === "" && isset($params["pid"])) $pid = trim((string)$params["pid"]);
                $jan = isset($params["jan"]) ? preg_replace("/\D/", "", (string)$params["jan"]) : "";
                $asin = isset($params["asin"]) ? strtoupper(trim((string)$params["asin"])) : "";
                $model = isset($params["model_number"]) ? trim((string)$params["model_number"]) : "";
                if($model === "" && isset($params["model"])) $model = trim((string)$params["model"]);
                $from = isset($params["from"]) ? trim((string)$params["from"]) : "";
                if($from === "" && $ref !== ""){
                    $ref_parts = parse_url($ref);
                    $ref_path = isset($ref_parts["path"]) ? $ref_parts["path"] : "";
                    $ref_query = isset($ref_parts["query"]) ? ("?" . $ref_parts["query"]) : "";
                    $from = trim($ref_path . $ref_query);
                }
                if($from === "" && $ref === ""){
                    $skip_dashboard_url = true;
                }
                if($from === "") $from = "(unknown)";
                if(!$skip_dashboard_url){
                    $product_label = $kw !== "" ? $kw : ($pid !== "" ? "product_id:" . $pid : ($jan !== "" ? "JAN:" . $jan : ($asin !== "" ? "ASIN:" . $asin : $model)));
                    if($product_label === "") $product_label = "(unknown)";
                    $from_key = $to . "|" . $from;
                    if(!isset($go_from_count[$from_key])){
                        $go_from_count[$from_key] = array("to" => $to, "from" => $from, "clicks" => 0, "latest_at" => "");
                    }
                    $go_from_count[$from_key]["clicks"]++;
                    if($go_from_count[$from_key]["latest_at"] === "" || $parts[0] > $go_from_count[$from_key]["latest_at"]){
                        $go_from_count[$from_key]["latest_at"] = $parts[0];
                    }
                    $key = $to . "|" . $pid . "|" . $jan . "|" . $asin . "|" . $model . "|" . $from . "|" . $product_label;
                    if(!isset($go_product_count[$key])){
                        $go_product_count[$key] = array(
                            "to" => $to,
                            "product" => $product_label,
                            "pid" => $pid,
                            "jan" => $jan,
                            "asin" => $asin,
                            "model" => $model,
                            "from" => $from,
                            "clicks" => 0,
                            "latest_at" => "",
                        );
                    }
                    $go_product_count[$key]["clicks"]++;
                    if($go_product_count[$key]["latest_at"] === "" || $parts[0] > $go_product_count[$key]["latest_at"]){
                        $go_product_count[$key]["latest_at"] = $parts[0];
                    }
                }
            }
            if(!$skip_dashboard_url){
                if(!isset($url_count[$url])) $url_count[$url] = 0;
                $url_count[$url]++;
            }
        }

        if($ref !== ""){
            if(!isset($ref_count[$ref])) $ref_count[$ref] = 0;
            $ref_count[$ref]++;
        }
    }

    ksort($pv_per_day);
    arsort($url_count);
    arsort($ref_count);
    uasort($go_product_count, function($a, $b){
        $la = $a["latest_at"] ?? "";
        $lb = $b["latest_at"] ?? "";
        if($la !== $lb) return strcmp($lb, $la); // 最新順
        return ($a["clicks"] > $b["clicks"]) ? -1 : 1;
    });
    uasort($go_from_count, function($a, $b){
        $la = $a["latest_at"] ?? "";
        $lb = $b["latest_at"] ?? "";
        if($la !== $lb) return strcmp($lb, $la); // 最新順
        return ($a["clicks"] > $b["clicks"]) ? -1 : 1;
    });

    $filtered_urls = $url_count;
    $filtered_refs = $ref_count;

    $top_urls = array_slice($filtered_urls, 0, 20, true);
    $top_refs = array_slice($filtered_refs, 0, 20, true);
    $top_go_products = array_slice($go_product_count, 0, 50, true);
    $top_go_from = array_slice($go_from_count, 0, 50, true);

    $all_urls_array = array();
    foreach($filtered_urls as $u => $c){
        $all_urls_array[] = array(
            "url" => urldecode($u),
            "pv"  => $c
        );
    }
    $all_urls = json_encode($all_urls_array, JSON_UNESCAPED_UNICODE);

    $dates      = json_encode(array_keys($pv_per_day));
    $pv_counts  = json_encode(array_values($pv_per_day));

    $url_labels = json_encode(array_map('urldecode', array_keys($top_urls)), JSON_UNESCAPED_UNICODE);
    $url_counts = json_encode(array_values($top_urls));

    $ref_labels = json_encode(array_map('urldecode', array_keys($top_refs)), JSON_UNESCAPED_UNICODE);
    $ref_counts = json_encode(array_values($top_refs));
?>
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AIxEC Web Analytics</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
:root{--ink:rgba(0,0,0,.87);--muted:rgba(0,0,0,.54);--line:#e0e0e0;--soft:#f5f6f6;--accent:#55c500;--accent-dark:#468c00}
*{box-sizing:border-box}
body{margin:0;font-family:YakuHanJPs,-apple-system,system-ui,"Segoe UI","Hiragino Kaku Gothic ProN","Hiragino Sans",Meiryo,sans-serif;color:var(--ink);background:var(--soft);letter-spacing:0;line-height:1.8;word-break:break-all;overflow-wrap:break-word}
a{color:inherit}
.top{background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
.wrap{max-width:1100px;margin:0 auto;padding:12px 16px}
.bar{display:flex;align-items:center;justify-content:space-between;gap:18px}
.brand{display:flex;align-items:center;gap:12px;min-width:0;text-decoration:none}
.mark{width:36px;height:36px;border-radius:4px;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px}
.brand b{display:block;font-size:22px;line-height:1;letter-spacing:0}.brand span{display:block;color:var(--muted);font-size:12px;margin-top:4px;white-space:nowrap}
.dash-link{border:1px solid var(--line);background:#fff;border-radius:4px;padding:7px 11px;color:var(--muted);font-size:12px;white-space:nowrap;text-decoration:none}
.range-nav{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 16px}
.range-nav a{display:inline-flex;align-items:center;justify-content:center;min-height:34px;padding:6px 12px;border:1px solid var(--line);border-radius:999px;color:var(--muted);text-decoration:none;background:#fff;font-size:13px;font-weight:700}
.range-nav a.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.range-note{color:var(--muted);font-size:13px;margin:-8px 0 16px}
.hero{max-width:1100px;margin:0 auto;padding:32px 16px 20px}
.hero h1{font-size:32px;line-height:1.4;margin:0 0 10px;letter-spacing:0;color:var(--ink);font-weight:700}
.lead{color:var(--muted);font-size:15px;line-height:1.8;margin:0;max-width:760px}
.main{max-width:1100px;margin:0 auto;padding:16px 16px 48px}
.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:16px}
.stat{background:#fff;border:1px solid var(--line);border-radius:4px;padding:14px}
.stat small{display:block;color:var(--muted);font-size:12px}.stat strong{display:block;margin-top:4px;font-size:22px;line-height:1.2}
.canvasBox{background:#fff;border:1px solid var(--line);border-radius:4px;padding:18px;margin-bottom:16px}
.canvasBox h2{font-size:18px;line-height:1.4;font-weight:600;margin:0 0 12px}
table{
    width:100%;
    border-collapse:collapse;
}
th,td{
    border:1px solid var(--line);
    padding:8px;
    font-size:13px;
    word-break:break-all;
    background:#fff;
}
th{
    background:#fafafa;
    color:var(--muted);
    text-align:left;
}
canvas{background:#fff;border-radius:4px}
@media(max-width:760px){.stats{grid-template-columns:1fr}.hero h1{font-size:27px}.bar{align-items:flex-start}.brand span{white-space:normal}.dash-link{display:none}.canvasBox{padding:12px 8px}}
</style>
</head>
<body>
<header class="top"><div class="wrap">
  <div class="bar">
    <a class="brand" href="./"><div class="mark">AIx</div><div><b>AIxEC</b><span>AI x EC product intelligence</span></div></a>
    <a class="dash-link" href="./simpletrack.php?dashboard=1">Analytics</a>
  </div>
</div></header>
<section class="hero">
  <h1>AIxEC Web Analytics</h1>
  <p class="lead">AIxECのページ閲覧、商品ページ、Amazon・楽天へのクリックを確認します。</p>
</section>
<main class="main">
<div class="range-nav">
  <?php foreach($range_labels as $key => $label): ?>
    <a class="<?php echo $range === $key ? 'active' : ''; ?>" href="./simpletrack.php?dashboard=1&range=<?php echo h($key); ?>"><?php echo h($label); ?></a>
  <?php endforeach; ?>
</div>
<div class="range-note">表示期間: <?php echo h($range_labels[$range]); ?></div>
<div class="stats">
  <div class="stat"><small>Total PV</small><strong><?php echo number_format(array_sum($pv_per_day)); ?></strong></div>
  <div class="stat"><small>Tracked URLs</small><strong><?php echo number_format(count($url_count)); ?></strong></div>
  <div class="stat"><small>Referrers</small><strong><?php echo number_format(count($ref_count)); ?></strong></div>
</div>

<div class="canvasBox">
<h2>Daily PV</h2>
<canvas id="pvChart"></canvas>
</div>

<div class="canvasBox">
<h2>Top URLs</h2>
<canvas id="urlChart"></canvas>
</div>

<div class="canvasBox">
<h2>Top Referrers</h2>
<canvas id="refChart"></canvas>
</div>

<div class="canvasBox">
<h2>go.php 呼び出し元ページ</h2>
<table>
<thead>
<tr><th>#</th><th>呼び出し元</th><th>遷移先</th><th>最新クリック日時</th><th>クリック</th></tr>
</thead>
<tbody>
<?php if(empty($top_go_from)): ?>
<tr><td colspan="5">go.php のクリックはありません。</td></tr>
<?php else: ?>
<?php $from_idx = 1; foreach($top_go_from as $row): ?>
<tr>
  <td><?php echo $from_idx++; ?></td>
  <td><?php echo h($row["from"]); ?></td>
  <td><?php echo h($row["to"]); ?></td>
  <td><?php echo h($row["latest_at"]); ?></td>
  <td><?php echo number_format($row["clicks"]); ?></td>
</tr>
<?php endforeach; ?>
<?php endif; ?>
</tbody>
</table>
</div>

<div class="canvasBox">
<h2>go.php 商品別クリック</h2>
<table>
<thead>
<tr><th>#</th><th>商品</th><th>呼び出し元</th><th>遷移先</th><th>商品ID</th><th>JAN / ASIN / Model</th><th>最新クリック日時</th><th>クリック</th></tr>
</thead>
<tbody>
<?php if(empty($top_go_products)): ?>
<tr><td colspan="8">go.php のクリックはありません。</td></tr>
<?php else: ?>
<?php $go_idx = 1; foreach($top_go_products as $row): ?>
<tr>
  <td><?php echo $go_idx++; ?></td>
  <td><?php echo h($row["product"]); ?></td>
  <td><?php echo h($row["from"]); ?></td>
  <td><?php echo h($row["to"]); ?></td>
  <td><?php echo h($row["pid"]); ?></td>
  <td><?php echo h(trim($row["jan"] . " " . $row["asin"] . " " . $row["model"])); ?></td>
  <td><?php echo h($row["latest_at"]); ?></td>
  <td><?php echo number_format($row["clicks"]); ?></td>
</tr>
<?php endforeach; ?>
<?php endif; ?>
</tbody>
</table>
</div>

<div class="canvasBox">
<h2>Access URL Details</h2>
<table>
<thead>
<tr><th>#</th><th>URL</th><th>PV</th></tr>
</thead>
<tbody id="detailBody"></tbody>
</table>
</div>

<script>
const allData = <?php echo $all_urls; ?>;

let rendered = 0;
const tbody = document.getElementById("detailBody");

function renderRows(){

    const next = Math.min(rendered + 50, allData.length);

    for(let i = rendered; i < next; i++){

        const tr = document.createElement("tr");

        tr.innerHTML =
            "<td>"+(i+1)+"</td>" +
            "<td>"+allData[i].url+"</td>" +
            "<td>"+allData[i].pv+"</td>";

        tbody.appendChild(tr);
    }

    rendered = next;
}

renderRows();

window.addEventListener("scroll", function(){

    if(
        window.innerHeight + window.scrollY >=
        document.body.offsetHeight - 200
    ){
        if(rendered < allData.length){
            renderRows();
        }
    }
});

Chart.defaults.color = 'rgba(0,0,0,.7)';
Chart.defaults.borderColor = '#e0e0e0';

var isMobile = window.innerWidth < 760;

function stripOrigin(s) {
    return String(s).replace(/^https?:\/\/[^\/]+/, '') || '/';
}
function truncLabel(s, len) {
    return String(s).length > len ? String(s).slice(0, len) + '…' : String(s);
}
var labelLen = isMobile ? 32 : 72;

var rawUrlLabels = <?php echo $url_labels; ?>;
var rawRefLabels = <?php echo $ref_labels; ?>;
var urlLabels = rawUrlLabels.map(function(s){ return truncLabel(stripOrigin(s), labelLen); });
var refLabels = rawRefLabels.map(function(s){ return truncLabel(s, labelLen); });
var urlCounts = <?php echo $url_counts; ?>;
var refCounts = <?php echo $ref_counts; ?>;

if(isMobile){
    rawUrlLabels=rawUrlLabels.slice(0,10); rawRefLabels=rawRefLabels.slice(0,10);
    urlLabels=urlLabels.slice(0,10); urlCounts=urlCounts.slice(0,10);
    refLabels=refLabels.slice(0,10); refCounts=refCounts.slice(0,10);
}

new Chart(document.getElementById('pvChart'),{
    type:'line',
    data:{
        labels: <?php echo $dates; ?>,
        datasets:[{label:'Daily PV',data:<?php echo $pv_counts; ?>,borderColor:'#55c500',backgroundColor:'rgba(85,197,0,0.14)',tension:0.3,fill:true}]
    },
    options:{responsive:true,plugins:{legend:{labels:{font:{size:11}}}},scales:{y:{beginAtZero:true},x:{ticks:{maxTicksLimit:isMobile?7:20}}}}
});

function makeBarChart(id, labels, fullLabels, data, color) {
    var itemH = isMobile ? 30 : 28;
    var wrap = document.getElementById(id).parentNode;
    wrap.style.position = 'relative';
    wrap.style.height = (labels.length * itemH + 60) + 'px';
    return new Chart(document.getElementById(id),{
        type:'bar',
        data:{labels:labels,datasets:[{label:'',data:data,backgroundColor:color,borderRadius:3}]},
        options:{
            indexAxis:'y',
            responsive:true,
            maintainAspectRatio:false,
            plugins:{legend:{display:false},tooltip:{callbacks:{title:function(items){
                var idx=items[0].dataIndex;
                return fullLabels[idx]||labels[idx];
            }}}},
            scales:{
                x:{beginAtZero:true,ticks:{font:{size:isMobile?10:11}}},
                y:{
                    afterFit:function(axis){ axis.width = isMobile ? 150 : 260; },
                    ticks:{font:{size:isMobile?10:11}}
                }
            }
        }
    });
}

makeBarChart('urlChart', urlLabels, rawUrlLabels.map(stripOrigin), urlCounts, '#55c500');
makeBarChart('refChart', refLabels, rawRefLabels, refCounts, '#468c00');
</script>

</main>
</body>
</html>
<?php
exit;
}

/* =========================
   通常トラッキングモード
========================= */

// ---- 1. URLの取得 ----
if(isset($_GET["url"]) && $_GET["url"] !== ""){
    $url = filter_var($_GET["url"], FILTER_SANITIZE_URL);
    if(!preg_match('#^https?://#i', $url)){
        $url = "";
    }
} else {
    $url = isset($_SERVER["HTTP_HOST"])
        ? "https://" . $_SERVER["HTTP_HOST"] . strtok($_SERVER["REQUEST_URI"], "?")
        : "";
}

// ---- 2. リファラーの取得 ----
if(isset($_GET["ref"]) && $_GET["ref"] !== ""){
    $ref = filter_var($_GET["ref"], FILTER_SANITIZE_URL);
    if(!preg_match('#^https?://#i', $ref)){
        $ref = "";
    }
} else {
    $ref = isset($_SERVER["HTTP_REFERER"]) ? $_SERVER["HTTP_REFERER"] : "";
}

function sanitize_field($value){
    return str_replace(array("|", "\n", "\r"), array("", "", ""), trim($value));
}

// ---- 3. IP・UA ----
$internal_key = isset($_GET["st_key"]) ? (string)$_GET["st_key"] : "";
$internal_ok = ($internal_key !== "" && $internal_key === SIMPLETRACK_INTERNAL_KEY);

$ip = isset($_SERVER["REMOTE_ADDR"]) ? $_SERVER["REMOTE_ADDR"] : "";
if($internal_ok && isset($_GET["ip"]) && $_GET["ip"] !== ""){
    $ip = $_GET["ip"];
}
$ip = sanitize_field($ip);

$ua = isset($_SERVER["HTTP_USER_AGENT"]) ? $_SERVER["HTTP_USER_AGENT"] : "";
if($internal_ok && isset($_GET["ua"]) && $_GET["ua"] !== ""){
    $ua = $_GET["ua"];
}
$ua  = sanitize_field($ua);
$ref = sanitize_field($ref);
$url = sanitize_field($url);

if(st_is_bot_ua($ua)){
    header("Content-Type: application/javascript");
    echo "// ignored";
    exit;
}

// ---- 4. ログ書き込み ----
$line = date("Y-m-d H:i:s") . " | "
      . $ip  . " | "
      . $url . " | "
      . $ref . " | "
      . $ua  . "\n";

file_put_contents($logfile, $line, FILE_APPEND | LOCK_EX);

// ---- 5. レスポンス ----
header("Content-Type: application/javascript");
echo "// tracked";
exit;
