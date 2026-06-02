<?php
session_start();
date_default_timezone_set("Asia/Tokyo");

$BASE_HOST = 'https://aixec.exbridge.jp';
$THIS_FILE = 'aixtubeg.php';
$ADMIN     = 'xb_bittensor';
$HYPERFRAMES_API_BASE = rtrim(getenv('HYPERFRAMES_API_BASE') ?: 'http://exbridge.ddns.net:9944', '/');

$x_keys = array();
$x_keys_file = __DIR__ . '/x_api_keys.sh';
if (file_exists($x_keys_file)) {
    foreach (file($x_keys_file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (preg_match('/(?:export\s+)?(\w+)=["\']?([^"\'#\r\n]*)["\']?/', $line, $m)) {
            $x_keys[trim($m[1])] = trim($m[2]);
        }
    }
}
$x_client_id     = $x_keys['X_API_KEY']    ?? '';
$x_client_secret = $x_keys['X_API_SECRET'] ?? '';
$x_redirect_uri  = $BASE_HOST . '/' . $THIS_FILE;

function h($s) { return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8'); }
function base64url($d) { return rtrim(strtr(base64_encode($d), '+/', '-_'), '='); }
function gen_verifier() { $b=''; for($i=0;$i<32;$i++) $b.=chr(mt_rand(0,255)); return base64url($b); }
function gen_challenge($v) { return base64url(hash('sha256', $v, true)); }
function x_post($url, $data, $headers) {
    $opts = array('http'=>array('method'=>'POST','header'=>implode("\r\n",$headers)."\r\n",'content'=>$data,'timeout'=>12,'ignore_errors'=>true));
    return json_decode(@file_get_contents($url, false, stream_context_create($opts)) ?: '{}', true);
}
function x_get($url, $token) {
    $opts = array('http'=>array('method'=>'GET','header'=>"Authorization: Bearer $token\r\nUser-Agent: AIxTubeCreator/1.0\r\n",'timeout'=>12,'ignore_errors'=>true));
    return json_decode(@file_get_contents($url, false, stream_context_create($opts)) ?: '{}', true);
}

function valid_job_id($id) {
    return preg_match('/^[A-Za-z0-9_-]{8,96}$/', (string)$id);
}

function hyperframes_request($method, $path, $payload = null, $timeout = 30) {
    global $HYPERFRAMES_API_BASE;
    $url = $HYPERFRAMES_API_BASE . $path;
    $ch = curl_init($url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, $timeout);
    curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $method);
    curl_setopt($ch, CURLOPT_HTTPHEADER, array('Content-Type: application/json', 'Accept: application/json'));
    if ($payload !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($payload, JSON_UNESCAPED_UNICODE));
    }
    $body = curl_exec($ch);
    $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);
    curl_close($ch);
    if ($body === false || $error) {
        return array('ok' => false, 'status' => 0, 'error' => $error ?: 'HyperFrames API request failed');
    }
    $json = json_decode($body, true);
    if (!is_array($json)) $json = array('raw' => $body);
    return array('ok' => ($status >= 200 && $status < 300), 'status' => $status, 'data' => $json, 'body' => $body);
}

function absolute_url_for_ogp($url, $base) {
    $url = html_entity_decode(trim((string)$url), ENT_QUOTES | ENT_HTML5, 'UTF-8');
    if ($url === '') return '';
    if (preg_match('#^https?://#i', $url)) return $url;
    if (strpos($url, '//') === 0) return 'https:' . $url;
    $parts = parse_url($base);
    if (empty($parts['scheme']) || empty($parts['host'])) return '';
    $root = $parts['scheme'] . '://' . $parts['host'];
    if (strpos($url, '/') === 0) return $root . $url;
    $path = isset($parts['path']) ? preg_replace('#/[^/]*$#', '/', $parts['path']) : '/';
    return $root . $path . $url;
}
function fetch_ogp_card($url) {
    $url = trim((string)$url);
    if (!preg_match('#^https?://#i', $url)) return array('ok' => false, 'error' => 'invalid url');
    $ch = curl_init($url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
    curl_setopt($ch, CURLOPT_MAXREDIRS, 4);
    curl_setopt($ch, CURLOPT_TIMEOUT, 8);
    curl_setopt($ch, CURLOPT_USERAGENT, 'AIxTubeG OGP/1.0');
    curl_setopt($ch, CURLOPT_HTTPHEADER, array('Accept: text/html,application/xhtml+xml'));
    $html = curl_exec($ch);
    $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $final_url = curl_getinfo($ch, CURLINFO_EFFECTIVE_URL);
    $ctype = curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
    curl_close($ch);
    if (!$html || $status >= 400 || ($ctype && stripos($ctype, 'text/html') === false && stripos($ctype, 'application/xhtml') === false)) {
        return array('ok' => false, 'error' => 'fetch failed');
    }
    if (strlen($html) > 500000) $html = substr($html, 0, 500000);
    $meta = array();
    if (preg_match_all('/<meta\b[^>]+>/i', $html, $tags)) {
        foreach ($tags[0] as $tag) {
            $key = '';
            $val = '';
            if (preg_match('/\b(?:property|name)=["\']([^"\']+)["\']/i', $tag, $km)) $key = strtolower($km[1]);
            if (preg_match('/\bcontent=["\']([^"\']*)["\']/i', $tag, $vm)) $val = html_entity_decode($vm[1], ENT_QUOTES | ENT_HTML5, 'UTF-8');
            if ($key !== '' && $val !== '') $meta[$key] = $val;
        }
    }
    $title = isset($meta['og:title']) ? $meta['og:title'] : '';
    if ($title === '' && preg_match('/<title[^>]*>(.*?)<\/title>/is', $html, $tm)) {
        $title = html_entity_decode(trim(strip_tags($tm[1])), ENT_QUOTES | ENT_HTML5, 'UTF-8');
    }
    $desc = isset($meta['og:description']) ? $meta['og:description'] : (isset($meta['description']) ? $meta['description'] : '');
    $image = isset($meta['og:image']) ? absolute_url_for_ogp($meta['og:image'], $final_url ?: $url) : '';
    return array('ok' => true, 'url' => $final_url ?: $url, 'host' => parse_url($final_url ?: $url, PHP_URL_HOST) ?: '', 'title' => mb_substr(trim($title), 0, 140, 'UTF-8'), 'description' => mb_substr(trim($desc), 0, 220, 'UTF-8'), 'image' => $image);
}

if (isset($_GET['aff_logout'])) { session_destroy(); header('Location: '.$x_redirect_uri); exit; }
if (isset($_GET['aff_login'])) {
    $ver = gen_verifier(); $chal = gen_challenge($ver); $state = md5(uniqid('', true));
    $_SESSION['aff_code_verifier'] = $ver; $_SESSION['aff_oauth_state'] = $state;
    $p = array('response_type'=>'code','client_id'=>$x_client_id,'redirect_uri'=>$x_redirect_uri,
               'scope'=>'tweet.read users.read','state'=>$state,'code_challenge'=>$chal,'code_challenge_method'=>'S256');
    header('Location: https://twitter.com/i/oauth2/authorize?'.http_build_query($p)); exit;
}
if (isset($_GET['code'], $_GET['state'], $_SESSION['aff_oauth_state']) && $_GET['state'] === $_SESSION['aff_oauth_state']) {
    $post = http_build_query(array('grant_type'=>'authorization_code','code'=>$_GET['code'],
        'redirect_uri'=>$x_redirect_uri,'code_verifier'=>$_SESSION['aff_code_verifier'],'client_id'=>$x_client_id));
    $cred = base64_encode($x_client_id . ':' . $x_client_secret);
    $data = x_post('https://api.twitter.com/2/oauth2/token', $post, array('Content-Type: application/x-www-form-urlencoded','Authorization: Basic '.$cred));
    if (isset($data['access_token'])) {
        $_SESSION['aff_access_token'] = $data['access_token'];
        unset($_SESSION['aff_oauth_state'], $_SESSION['aff_code_verifier']);
        $me = x_get('https://api.twitter.com/2/users/me', $data['access_token']);
        if (isset($me['data']['username'])) $_SESSION['aff_username'] = $me['data']['username'];
    }
    header('Location: '.$x_redirect_uri); exit;
}

$session_user = $_SESSION['aff_username'] ?? '';
$is_admin = ($session_user === $ADMIN);
$not_admin_message = $session_user
    ? '@' . $session_user . ' でログイン中ですが、AIxTubeG管理者ではありません'
    : '管理者ログイン後にHyperFrames APIを確認します';

if (isset($_GET['api'])) {
    $api = (string)$_GET['api'];
    if ($api === 'ogp') {
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode(fetch_ogp_card(trim((string)($_GET['url'] ?? ''))), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        exit;
    }
    if (!$is_admin) {
        header('Content-Type: application/json; charset=utf-8', true, 403);
        echo json_encode(array('ok' => false, 'error' => 'admin login required'), JSON_UNESCAPED_UNICODE);
        exit;
    }
    if ($api === 'health') {
        header('Content-Type: application/json; charset=utf-8');
        $res = hyperframes_request('GET', '/health', null, 8);
        http_response_code($res['ok'] ? 200 : 502);
        echo json_encode($res['ok'] ? $res['data'] : array('ok' => false, 'error' => $res['error'] ?? 'health check failed'), JSON_UNESCAPED_UNICODE);
        exit;
    }
    if ($api === 'create') {
        header('Content-Type: application/json; charset=utf-8');
        $data = json_decode(file_get_contents('php://input'), true);
        $url = trim((string)($data['url'] ?? ''));
        if (!preg_match('#^https?://#i', $url)) {
            http_response_code(400);
            echo json_encode(array('ok' => false, 'error' => 'URLを入力してください'), JSON_UNESCAPED_UNICODE);
            exit;
        }
        $payload = array('url' => $url, 'render' => !empty($data['render']), 'draft' => !empty($data['draft']), 'use_ai' => !empty($data['use_ai']));
        $res = hyperframes_request('POST', '/api/aixtube/jobs', $payload, 30);
        http_response_code($res['ok'] ? 200 : 502);
        echo json_encode($res['ok'] ? $res['data'] : array('ok' => false, 'error' => $res['error'] ?? 'job create failed', 'status' => $res['status'] ?? 0, 'body' => $res['body'] ?? ''), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        exit;
    }
    if ($api === 'status') {
        header('Content-Type: application/json; charset=utf-8');
        $id = trim((string)($_GET['id'] ?? ''));
        if (!valid_job_id($id)) {
            http_response_code(400);
            echo json_encode(array('ok' => false, 'error' => 'invalid job id'), JSON_UNESCAPED_UNICODE);
            exit;
        }
        $res = hyperframes_request('GET', '/api/aixtube/jobs/' . rawurlencode($id), null, 20);
        http_response_code($res['ok'] ? 200 : 502);
        echo json_encode($res['ok'] ? $res['data'] : array('ok' => false, 'error' => $res['error'] ?? 'status fetch failed', 'status' => $res['status'] ?? 0, 'body' => $res['body'] ?? ''), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        exit;
    }
    if ($api === 'download') {
        $id = trim((string)($_GET['id'] ?? ''));
        if (!valid_job_id($id)) { http_response_code(400); echo 'invalid job id'; exit; }
        $url = $HYPERFRAMES_API_BASE . '/api/aixtube/jobs/' . rawurlencode($id) . '/download';
        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, 300);
        $body = curl_exec($ch);
        $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $ctype = curl_getinfo($ch, CURLINFO_CONTENT_TYPE) ?: 'application/octet-stream';
        $error = curl_error($ch);
        curl_close($ch);
        if ($body === false || $error || $status >= 400) {
            http_response_code($status >= 400 ? $status : 502);
            header('Content-Type: text/plain; charset=utf-8');
            echo $error ?: $body ?: 'download failed';
            exit;
        }
        $ext = stripos($ctype, 'html') !== false ? 'html' : 'mp4';
        header('Content-Type: ' . $ctype);
        header('Content-Disposition: attachment; filename="aixtubeg-' . preg_replace('/[^A-Za-z0-9_-]/', '', $id) . '.' . $ext . '"');
        header('Content-Length: ' . strlen($body));
        echo $body;
        exit;
    }
    header('Content-Type: application/json; charset=utf-8', true, 404);
    echo json_encode(array('ok' => false, 'error' => 'unknown api'), JSON_UNESCAPED_UNICODE);
    exit;
}

$health_dot_class = '';
$health_text = $not_admin_message;
if ($is_admin) {
    $health_res = hyperframes_request('GET', '/health', null, 8);
    if (!empty($health_res['ok'])) {
        $health_dot_class = ' ok';
        $health_text = 'HyperFrames API 接続OK';
    } else {
        $health_dot_class = ' err';
        $health_text = 'HyperFrames API 接続エラー: ' . ($health_res['error'] ?? ('HTTP ' . ($health_res['status'] ?? 0)));
    }
}

$page_title = 'AIxTubeG | URLからショート動画を非同期生成';
$page_desc = 'URLを入力してHyperFrames/AIxTubeの非同期ジョブを作成し、進捗確認とMP4ダウンロードまで行う動画生成システムです。';
$page_url = $BASE_HOST . '/' . $THIS_FILE;
$page_image = $BASE_HOST . '/images/aixtubeg.png';
?><!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title><?php echo h($page_title); ?></title>
<meta name="description" content="<?php echo h($page_desc); ?>">
<link rel="canonical" href="<?php echo h($page_url); ?>">
<meta property="og:type" content="website">
<meta property="og:title" content="<?php echo h($page_title); ?>">
<meta property="og:description" content="<?php echo h($page_desc); ?>">
<meta property="og:url" content="<?php echo h($page_url); ?>">
<meta property="og:image" content="<?php echo h($page_image); ?>">
<meta property="og:site_name" content="AIxEC">
<meta property="og:locale" content="ja_JP">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="<?php echo h($page_title); ?>">
<meta name="twitter:description" content="<?php echo h($page_desc); ?>">
<meta name="twitter:image" content="<?php echo h($page_image); ?>">
<meta name="twitter:site" content="@xb_bittensor">
<style>
:root{--accent:#55c500;--accent-dark:#3d9400;--ink:#17202a;--muted:#6b7280;--line:#e5e7eb;--bg:#f7faf8;--red:#bf0000;--blue:#2563eb}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:-apple-system,'Hiragino Sans','Yu Gothic',sans-serif}
.header{background:#fff;border-bottom:1px solid var(--line);padding:12px 20px;position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:10px}
.header h1{font-size:17px;font-weight:800}.brand-mark{width:30px;height:30px;border-radius:7px;background:#111;color:#fff;display:grid;place-items:center;font-weight:900;font-size:12px}
.badge{background:var(--accent);color:#fff;font-size:11px;padding:2px 8px;border-radius:10px}.userbar{display:flex;align-items:center;gap:.6rem;font-size:.8rem;margin-left:auto}.userbar strong{color:#059669}
.btn-sm,.btn-login-sm{border:1px solid var(--line);padding:4px 12px;border-radius:4px;color:var(--muted);text-decoration:none;font-size:.75rem;background:#fff}.btn-login-sm{border-color:var(--accent);color:var(--accent-dark)}
.nav{display:flex;gap:8px;margin-left:8px}.nav a{font-size:12px;color:#374151;text-decoration:none;border:1px solid var(--line);border-radius:4px;padding:5px 9px;white-space:nowrap}.nav a:hover{border-color:var(--accent);color:var(--accent-dark)}
.hero{background:#06131f;color:#fff;position:relative;overflow:hidden}.hero:before{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(6,19,31,.94),rgba(6,19,31,.72),rgba(6,19,31,.24)),url('/images/aixtubeg.png') center right/cover no-repeat;opacity:.95}
.hero-inner{position:relative;max-width:1100px;margin:0 auto;padding:58px 18px 64px}.kicker{font-size:12px;color:#b8f084;font-weight:800;margin-bottom:12px}.hero h2{font-size:34px;line-height:1.25;letter-spacing:0;margin-bottom:14px}.hero p{max-width:680px;color:#dbe7ef;line-height:1.8;font-size:15px}
.container{max-width:1100px;margin:0 auto;padding:18px 16px 80px}.panel{background:#fff;border:1px solid var(--line);border-radius:8px;padding:18px;margin-bottom:14px;box-shadow:0 2px 8px rgba(15,23,42,.04)}.panel h3{font-size:16px;margin-bottom:12px}
.creator-form{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:start}.url-input{width:100%;border:1px solid #cfd8dc;border-radius:6px;padding:12px 14px;font-size:15px;outline:none}.url-input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(85,197,0,.12)}
.primary-btn{background:var(--accent);color:#fff;border:none;border-radius:6px;padding:12px 22px;font-size:14px;font-weight:800;cursor:pointer;white-space:nowrap}.primary-btn:hover{background:var(--accent-dark)}.primary-btn:disabled{background:#a8b3a0;cursor:not-allowed}
.option-row{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:12px;color:#374151;font-size:13px}.option-row label{display:flex;align-items:center;gap:6px}.status-line{margin-top:12px;font-size:13px;color:var(--muted)}.status-line.ok{color:#166534}.status-line.err{color:#991b1b}
.ogp-card{display:none;margin-top:14px;border:1px solid var(--line);border-radius:8px;background:#fbfdff;overflow:hidden;grid-template-columns:140px minmax(0,1fr)}.ogp-card.open{display:grid}.ogp-card img{width:140px;height:110px;object-fit:cover;background:#eef2f7}.ogp-body{padding:12px;min-width:0}.ogp-host{font-size:11px;color:var(--muted);margin-bottom:5px}.ogp-title{font-weight:800;font-size:14px;line-height:1.45;margin-bottom:5px}.ogp-desc{font-size:12px;color:#4b5563;line-height:1.5}
.login-panel{text-align:center;padding:28px}.login-panel p{color:var(--muted);line-height:1.8;margin-bottom:18px}.health{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted)}.dot{width:9px;height:9px;border-radius:50%;background:#9ca3af}.dot.ok{background:#22c55e}.dot.err{background:#ef4444}
.jobs-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}.jobs-head h3{margin:0}.clear-btn{border:1px solid var(--line);background:#fff;border-radius:4px;padding:6px 10px;font-size:12px;color:var(--muted);cursor:pointer}.job-list{display:flex;flex-direction:column;gap:10px}
.job-card{border:1px solid var(--line);border-radius:8px;background:#fff;padding:14px}.job-top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.job-title{font-weight:800;font-size:14px;word-break:break-all}.job-id{font-size:11px;color:var(--muted);margin-top:4px;word-break:break-all}
.status-badge{border-radius:999px;padding:4px 10px;font-size:12px;font-weight:800;background:#eef2ff;color:#3730a3;white-space:nowrap}.status-badge.completed{background:#dcfce7;color:#166534}.status-badge.failed{background:#fee2e2;color:#991b1b}.status-badge.running,.status-badge.scripting,.status-badge.tts,.status-badge.rendering{background:#fff7ed;color:#9a3412}
.progress-wrap{height:8px;background:#eef2f7;border-radius:999px;overflow:hidden;margin:12px 0 8px}.progress-bar{height:100%;background:var(--accent);width:0%;transition:width .25s}.job-meta{display:flex;flex-wrap:wrap;gap:8px 14px;font-size:12px;color:var(--muted)}.job-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}.job-actions a,.job-actions button{border:1px solid var(--line);background:#fff;border-radius:5px;padding:8px 11px;font-size:12px;text-decoration:none;color:#374151;cursor:pointer}.job-actions .download{background:var(--blue);border-color:var(--blue);color:#fff}.logbox{display:none;margin-top:10px;background:#0b1220;color:#dbeafe;border-radius:6px;padding:10px;font-size:12px;line-height:1.5;white-space:pre-wrap;max-height:220px;overflow:auto}.empty{color:var(--muted);font-size:13px;padding:16px 0}
@media(max-width:720px){.header{padding:10px 12px;flex-wrap:wrap}.nav{order:3;width:100%;overflow-x:auto;margin-left:0}.hero h2{font-size:26px}.creator-form{grid-template-columns:1fr}.primary-btn{width:100%}.ogp-card{grid-template-columns:96px minmax(0,1fr)}.ogp-card img{width:96px;height:96px}.job-top{display:block}.status-badge{display:inline-block;margin-top:8px}.userbar{margin-left:0}}
</style>
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-BP0650KDFR"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-BP0650KDFR');</script>
<script>(function(){var s=document.createElement('script');s.src='/simpletrack.php?url='+encodeURIComponent(location.href)+'&ref='+encodeURIComponent(document.referrer);document.head.appendChild(s);})();</script>
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-2528616930208188"
     crossorigin="anonymous"></script>
</head>
<body>
<div class="header"><div class="brand-mark">AIx</div><h1>AIxTubeG</h1><span class="badge">HyperFrames</span><nav class="nav"><a href="/">商品検索</a><a href="/aixtube.php">AIxTube</a><a href="/affiliate.php">Affiliate</a><a href="/sns.php">新着情報</a></nav><div class="userbar"><?php if ($session_user): ?><strong>@<?php echo h($session_user); ?></strong><a href="?aff_logout=1" class="btn-sm">logout</a><?php else: ?><a href="?aff_login=1" class="btn-login-sm">X でログイン</a><?php endif; ?></div></div>
<section class="hero"><div class="hero-inner"><div class="kicker">URL to AIxTube Video</div><h2>URLからショート動画を非同期生成</h2><p>WebページURLをHyperFramesのAIxTubeジョブに登録し、台本生成、音声生成、レンダリングの進捗をポーリングします。完了後はMP4または生成HTMLをダウンロードできます。</p></div></section>
<main class="container">
<section class="panel"><div class="health"><span class="dot<?php echo $health_dot_class; ?>" id="health-dot"></span><span id="health-text"><?php echo h($health_text); ?></span></div></section>
<?php if ($is_admin): ?>
<section class="panel"><h3>生成ジョブを作成</h3><div class="creator-form"><input class="url-input" id="url-input" type="url" placeholder="https://exbridge.jp/seminar.html" autocomplete="url"><button class="primary-btn" id="create-btn" onclick="createJob()">生成ジョブ登録</button></div><div class="option-row"><label><input type="checkbox" id="render-opt" checked> MP4まで生成</label><label><input type="checkbox" id="draft-opt" checked> ドラフト品質</label><label><input type="checkbox" id="ai-opt" checked> AI台本生成</label></div><div class="status-line" id="form-status"></div><div class="ogp-card" id="ogp-card"><img id="ogp-img" src="/images/aixtubeg.png" alt=""><div class="ogp-body"><div class="ogp-host" id="ogp-host"></div><div class="ogp-title" id="ogp-title"></div><div class="ogp-desc" id="ogp-desc"></div></div></div></section>
<?php else: ?>
<section class="panel login-panel"><p>動画生成ジョブの登録には管理者ログインが必要です。進行中ジョブの確認と成果物ダウンロードは、管理者ログイン後に利用できます。</p><a href="?aff_login=1" class="btn-login-sm">X でログイン</a></section>
<?php endif; ?>
<section class="panel"><div class="jobs-head"><h3>ジョブ履歴</h3><button class="clear-btn" onclick="clearJobs()">履歴クリア</button></div><div id="job-list" class="job-list"></div></section>
</main>
<script>
var IS_ADMIN=<?php echo $is_admin ? 'true' : 'false'; ?>,STORAGE_KEY='aixtubeg_jobs_v1',jobs=loadJobs(),pollTimers={},ogpTimer=null;
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}function loadJobs(){try{return JSON.parse(localStorage.getItem(STORAGE_KEY)||'[]')}catch(e){return[]}}function saveJobs(){localStorage.setItem(STORAGE_KEY,JSON.stringify(jobs.slice(0,50)))}function setStatus(msg,cls){var el=document.getElementById('form-status');if(!el)return;el.textContent=msg||'';el.className='status-line '+(cls||'')}function statusLabel(s){return{queued:'待機中',running:'実行中',scripting:'AI台本生成中',tts:'音声生成中',rendering:'レンダリング中',completed:'完了',failed:'失敗'}[s]||s||'unknown'}function modeText(j){return[(j.render?'MP4':'HTML'),(j.draft?'ドラフト':'本番品質'),(j.use_ai?'AI台本':'固定台本')].join(' / ')}function upsertJob(job){if(!job||!job.id)return;var found=false;jobs=jobs.map(function(j){if(j.id===job.id){found=true;return Object.assign({},j,job)}return j});if(!found)jobs.unshift(job);saveJobs();renderJobs()}function apiJson(url,opt){return fetch(url,opt||{}).then(function(res){return res.text().then(function(text){var data={};try{data=text?JSON.parse(text):{}}catch(e){data={raw:text}}if(!res.ok)throw new Error(data.error||data.raw||('HTTP '+res.status));return data})})}
function checkHealth(){var dot=document.getElementById('health-dot'),text=document.getElementById('health-text');if(!IS_ADMIN){dot.className='dot';text.textContent=<?php echo json_encode($not_admin_message, JSON_UNESCAPED_UNICODE); ?>;return}var timeout=new Promise(function(_,reject){setTimeout(function(){reject(new Error('timeout'))},9000)});Promise.race([apiJson('aixtubeg.php?api=health'),timeout]).then(function(){dot.className='dot ok';text.textContent='HyperFrames API 接続OK'}).catch(function(e){dot.className='dot err';text.textContent='HyperFrames API 接続エラー: '+e.message})}
function createJob(){var input=document.getElementById('url-input'),btn=document.getElementById('create-btn'),url=(input.value||'').trim();if(!/^https?:\/\//i.test(url)){setStatus('URLを入力してください','err');return}btn.disabled=true;setStatus('ジョブを登録しています...','');apiJson('aixtubeg.php?api=create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url,render:document.getElementById('render-opt').checked,draft:document.getElementById('draft-opt').checked,use_ai:document.getElementById('ai-opt').checked})}).then(function(job){btn.disabled=false;input.value='';setStatus('ジョブ登録完了: '+job.id,'ok');upsertJob(job);pollJob(job.id,true)}).catch(function(e){btn.disabled=false;setStatus('エラー: '+e.message,'err')})}
function fetchOgp(url){if(!/^https?:\/\//i.test(url))return;apiJson('aixtubeg.php?api=ogp&url='+encodeURIComponent(url)).then(function(card){if(!card.ok)return;document.getElementById('ogp-img').src=card.image||'/images/aixtubeg.png';document.getElementById('ogp-host').textContent=card.host||'';document.getElementById('ogp-title').textContent=card.title||url;document.getElementById('ogp-desc').textContent=card.description||'';document.getElementById('ogp-card').classList.add('open')}).catch(function(){})}
function pollJob(id,immediate){if(!IS_ADMIN||!id)return;if(pollTimers[id])clearTimeout(pollTimers[id]);var run=function(){apiJson('aixtubeg.php?api=status&id='+encodeURIComponent(id)).then(function(job){upsertJob(job);if(job.status!=='completed'&&job.status!=='failed')pollTimers[id]=setTimeout(function(){pollJob(id,true)},5000)}).catch(function(e){var current=jobs.find(function(j){return j.id===id});if(current){current.poll_error=e.message;upsertJob(current)}pollTimers[id]=setTimeout(function(){pollJob(id,true)},10000)})};if(immediate)run();else pollTimers[id]=setTimeout(run,5000)}
function renderJobs(){var list=document.getElementById('job-list');if(!jobs.length){list.innerHTML='<div class="empty">ジョブ履歴はまだありません</div>';return}list.innerHTML=jobs.map(function(j){var p=Math.max(0,Math.min(100,Number(j.progress||0))),dl=j.status==='completed'?'<a class="download" href="aixtubeg.php?api=download&id='+encodeURIComponent(j.id)+'">ダウンロード</a>':'',log=j.log?'<button onclick="toggleLog(\\''+esc(j.id)+'\\')">ログ</button>':'',err=j.error?'<div class="status-line err">'+esc(j.error)+'</div>':'',pollErr=j.poll_error?'<div class="status-line err">ポーリング: '+esc(j.poll_error)+'</div>':'';return'<div class="job-card" id="job-'+esc(j.id)+'"><div class="job-top"><div><div class="job-title">'+esc(j.url||j.project||j.id)+'</div><div class="job-id">'+esc(j.id)+'</div></div><span class="status-badge '+esc(j.status)+'">'+esc(statusLabel(j.status))+'</span></div><div class="progress-wrap"><div class="progress-bar" style="width:'+p+'%"></div></div><div class="job-meta"><span>'+p+'%</span><span>'+esc(modeText(j))+'</span><span>created: '+esc(j.created_at||'')+'</span><span>updated: '+esc(j.updated_at||'')+'</span></div>'+err+pollErr+'<div class="job-actions"><button onclick="pollJob(\\''+esc(j.id)+'\\', true)">更新</button>'+dl+log+'<button onclick="removeJob(\\''+esc(j.id)+'\\')">削除</button></div>'+(j.log?'<pre class="logbox" id="log-'+esc(j.id)+'">'+esc(j.log)+'</pre>':'')+'</div>'}).join('')}
function toggleLog(id){var el=document.getElementById('log-'+id);if(el)el.style.display=el.style.display==='block'?'none':'block'}function removeJob(id){jobs=jobs.filter(function(j){return j.id!==id});saveJobs();renderJobs()}function clearJobs(){if(!confirm('ジョブ履歴をクリアしますか？'))return;jobs=[];saveJobs();renderJobs()}
if(IS_ADMIN){var input=document.getElementById('url-input');input.addEventListener('input',function(){clearTimeout(ogpTimer);var url=input.value.trim();ogpTimer=setTimeout(function(){fetchOgp(url)},700)});input.addEventListener('keydown',function(e){if(e.key==='Enter')createJob()})}renderJobs();checkHealth();jobs.forEach(function(j){if(j.status&&j.status!=='completed'&&j.status!=='failed')pollJob(j.id,false)});
</script>
</body>
</html>
