<?php
session_start();
date_default_timezone_set("Asia/Tokyo");
$API_PROXY = 'https://aixec.exbridge.jp/api.php';
$BASE_URL  = 'https://aixec.exbridge.jp';
$THIS_FILE = 'affiliate.php';
$ADMIN     = 'xb_bittensor';

/* X API キー読み込み */
$x_keys = array();
$x_keys_file = __DIR__ . '/x_api_keys.sh';
if (file_exists($x_keys_file)) {
    foreach (file($x_keys_file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (preg_match('/(?:export\s+)?(\w+)=["\']?([^"\'#\r\n]*)["\']?/', $line, $m))
            $x_keys[trim($m[1])] = trim($m[2]);
    }
}
$x_client_id     = $x_keys['X_API_KEY']    ?? '';
$x_client_secret = $x_keys['X_API_SECRET'] ?? '';
$x_redirect_uri  = $BASE_URL . '/' . $THIS_FILE;

function h($s) { return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8'); }

function aff_base64url($d) { return rtrim(strtr(base64_encode($d), '+/', '-_'), '='); }
function aff_gen_verifier() { $b=''; for($i=0;$i<32;$i++) $b.=chr(mt_rand(0,255)); return aff_base64url($b); }
function aff_gen_challenge($v) { return aff_base64url(hash('sha256', $v, true)); }
function aff_x_post($url, $data, $headers) {
    $opts = array('http'=>array('method'=>'POST','header'=>implode("\r\n",$headers)."\r\n",'content'=>$data,'timeout'=>12,'ignore_errors'=>true));
    return json_decode(@file_get_contents($url, false, stream_context_create($opts)) ?: '{}', true);
}
function aff_x_get($url, $token) {
    $opts = array('http'=>array('method'=>'GET','header'=>"Authorization: Bearer $token\r\nUser-Agent: AffiliateManager/1.0\r\n",'timeout'=>12,'ignore_errors'=>true));
    return json_decode(@file_get_contents($url, false, stream_context_create($opts)) ?: '{}', true);
}
function api_call($path, $params = array()) {
    global $API_PROXY;
    $p = array_merge(array('path' => ltrim($path, '/')), $params);
    $url = $API_PROXY . '?' . http_build_query($p);
    $ch = curl_init($url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 15);
    $body = curl_exec($ch);
    curl_close($ch);
    $d = json_decode($body, true);
    return is_array($d) ? $d : array();
}
function api_post($path, $payload) {
    global $API_PROXY;
    $url  = $API_PROXY . '?path=' . urlencode(ltrim($path, '/'));
    $body = json_encode($payload, JSON_UNESCAPED_UNICODE);
    $ch = curl_init($url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 15);
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
    curl_setopt($ch, CURLOPT_HTTPHEADER, array('Content-Type: application/json'));
    $resp = curl_exec($ch);
    curl_close($ch);
    $d = json_decode($resp, true);
    return is_array($d) ? $d : array();
}
function parse_input($input) {
    $input = trim($input);
    if (preg_match('#amazon\.co\.jp.*/(?:dp|gp/product)/([A-Z0-9]{10})#', $input, $m)) return array('type'=>'asin','value'=>$m[1]);
    if (preg_match('#amazon\.com.*/([A-Z0-9]{10})(?:/|\?|$)#', $input, $m))             return array('type'=>'asin','value'=>$m[1]);
    if (preg_match('/(\d{13})/', $input, $m))                                            return array('type'=>'jan', 'value'=>$m[1]);
    if (preg_match('/^[A-Z0-9]{10}$/', $input))                                         return array('type'=>'asin','value'=>$input);
    return array('type'=>'unknown','value'=>$input);
}

/* X OAuth */
if (isset($_GET['aff_logout'])) { session_destroy(); header('Location: '.$x_redirect_uri); exit; }
if (isset($_GET['aff_login'])) {
    $ver=$ver=aff_gen_verifier(); $chal=aff_gen_challenge($ver); $state=md5(uniqid('',true));
    $_SESSION['aff_code_verifier']=$ver; $_SESSION['aff_oauth_state']=$state;
    $p=array('response_type'=>'code','client_id'=>$x_client_id,'redirect_uri'=>$x_redirect_uri,
             'scope'=>'tweet.read users.read','state'=>$state,'code_challenge'=>$chal,'code_challenge_method'=>'S256');
    header('Location: https://twitter.com/i/oauth2/authorize?'.http_build_query($p)); exit;
}
if (isset($_GET['code'],$_GET['state'],$_SESSION['aff_oauth_state']) && $_GET['state']===$_SESSION['aff_oauth_state']) {
    $post=http_build_query(array('grant_type'=>'authorization_code','code'=>$_GET['code'],
        'redirect_uri'=>$x_redirect_uri,'code_verifier'=>$_SESSION['aff_code_verifier'],'client_id'=>$x_client_id));
    $cred=base64_encode($x_client_id.':'.$x_client_secret);
    $data=aff_x_post('https://api.twitter.com/2/oauth2/token',$post,array('Content-Type: application/x-www-form-urlencoded','Authorization: Basic '.$cred));
    if (isset($data['access_token'])) {
        $_SESSION['aff_access_token']=$data['access_token'];
        unset($_SESSION['aff_oauth_state'],$_SESSION['aff_code_verifier']);
        $me=aff_x_get('https://api.twitter.com/2/users/me',$data['access_token']);
        if (isset($me['data']['username'])) $_SESSION['aff_username']=$me['data']['username'];
    }
    header('Location: '.$x_redirect_uri); exit;
}

$session_user = $_SESSION['aff_username'] ?? '';
$is_admin     = ($session_user === $ADMIN);

/* AJAX: 商品リスト */
if (isset($_GET['api_products'])) {
    header('Content-Type: application/json; charset=utf-8');
    $limit  = min(60, max(1, (int)($_GET['limit'] ?? 30)));
    $offset = max(0, (int)($_GET['offset'] ?? 0));
    $maker  = trim($_GET['maker'] ?? '');
    $params = array('no_xdirect'=>'true','limit'=>$limit,'offset'=>$offset);
    if ($maker !== '') $params['maker'] = $maker;
    $res = api_call('/products', $params);
    echo json_encode(array('items' => $res['items'] ?? array()), JSON_UNESCAPED_UNICODE);
    exit;
}

/* AJAX: タグ（メーカー）一覧 */
if (isset($_GET['api_tags'])) {
    header('Content-Type: application/json; charset=utf-8');
    $res = api_call('/products/makers');
    echo json_encode(array('makers' => $res['makers'] ?? array()), JSON_UNESCAPED_UNICODE);
    exit;
}

/* AJAX: 商品登録（管理者のみ） */
if (isset($_GET['register_ajax']) && $is_admin) {
    header('Content-Type: application/json; charset=utf-8');
    $data  = json_decode(file_get_contents('php://input'), true);
    $input = trim($data['input'] ?? '');
    if (!$input) { echo json_encode(array('status'=>'error','error'=>'入力が空です')); exit; }

    $parsed = parse_input($input);
    if ($parsed['type'] === 'jan')
        $lookup = api_call('/lookup', array('jan'  => $parsed['value']));
    elseif ($parsed['type'] === 'asin')
        $lookup = api_call('/lookup', array('asin' => $parsed['value']));
    else { echo json_encode(array('status'=>'error','error'=>'URLまたはJAN/ASINを入力してください')); exit; }

    if (empty($lookup['found'])) { echo json_encode(array('status'=>'error','error'=>'商品情報が見つかりません')); exit; }
    $p = $lookup['product'];

    $payload = array(
        'name'               => $p['name']        ?? '',
        'jan'                => $p['jan']         ?? ($parsed['type']==='jan'  ? $parsed['value'] : ''),
        'asin'               => $p['asin']        ?? ($parsed['type']==='asin' ? $parsed['value'] : ''),
        'maker'              => $p['maker']       ?? '',
        'description'        => $p['description'] ?? '',
        'sale_price'         => (int)($p['sale_price'] ?? 0),
        'affiliate_priority' => 'affiliate',
        'status'             => 'published',
    );
    if (empty($payload['name'])) { echo json_encode(array('status'=>'error','error'=>'商品名が取得できません')); exit; }

    $reg = api_post('/products', $payload);
    if (empty($reg['ok'])) { echo json_encode(array('status'=>'error','error'=>$reg['error']??'登録失敗')); exit; }

    $product_id = $reg['item']['id'];
    $title      = $reg['item']['name'];

    // Ollamaで説明文生成トリガー（非同期）
    api_call('/lp/generate', array('id' => $product_id));

    echo json_encode(array('status'=>'ok','title'=>$title,'id'=>$product_id), JSON_UNESCAPED_UNICODE);
    exit;
}
$BASE_HOST = 'https://aixec.exbridge.jp';
$detail_id = isset($_GET['id']) ? (int)$_GET['id'] : 0;
$detail    = null;
if ($detail_id > 0) {
    $res    = api_call('products/' . $detail_id);
    $detail = (!empty($res['ok']) && !empty($res['item'])) ? $res['item'] : null;
}

if ($detail) {
    $page_title = $detail['name']
        . (!empty($detail['maker']) ? ' | ' . $detail['maker'] : '')
        . ' | AIxEC アフィリエイト';
    $page_desc  = !empty($detail['description'])
        ? mb_substr($detail['description'], 0, 120, 'UTF-8')
        : $detail['name'] . ' のアフィリエイト情報。Amazon・楽天で購入できます。';
    $page_url   = $BASE_HOST . '/affiliate.php?id=' . $detail_id;
    $page_image = !empty($detail['image_url']) ? $detail['image_url'] : $BASE_HOST . '/images/affiliate.png';
} else {
    $page_title = 'AIxEC アフィリエイト商品 | Amazon・楽天の書籍・ガジェット情報';
    $page_desc  = 'AI技術・開発書・ガジェットなど厳選商品をAmazon・楽天アフィリエイトリンクでご紹介。AIxECがセレクトしたおすすめ商品一覧。';
    $page_url   = $BASE_HOST . '/affiliate.php';
    $page_image = $BASE_HOST . '/images/affiliate.png';
}
?><!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title><?php echo h($page_title); ?></title>
<meta name="description" content="<?php echo h($page_desc); ?>">
<link rel="canonical" href="<?php echo h($page_url); ?>">
<meta property="og:type"        content="website">
<meta property="og:title"       content="<?php echo h($page_title); ?>">
<meta property="og:description" content="<?php echo h($page_desc); ?>">
<meta property="og:url"         content="<?php echo h($page_url); ?>">
<meta property="og:image"       content="<?php echo h($page_image); ?>">
<meta property="og:site_name"   content="AIxEC">
<meta property="og:locale"      content="ja_JP">
<meta name="twitter:card"        content="summary_large_image">
<meta name="twitter:title"       content="<?php echo h($page_title); ?>">
<meta name="twitter:description" content="<?php echo h($page_desc); ?>">
<meta name="twitter:image"       content="<?php echo h($page_image); ?>">
<meta name="twitter:site"        content="@xb_bittensor">
<?php if ($detail): ?>
<script type="application/ld+json">
<?php echo json_encode(array(
    '@context'    => 'https://schema.org',
    '@type'       => 'Product',
    'name'        => $detail['name'],
    'image'       => $detail['image_url'] ?? '',
    'description' => $detail['description'] ?? '',
    'brand'       => array('@type' => 'Brand', 'name' => $detail['maker'] ?? ''),
    'offers'      => array(
        '@type'         => 'Offer',
        'priceCurrency' => 'JPY',
        'price'         => (int)($detail['sale_price'] ?? 0),
        'availability'  => 'https://schema.org/InStock',
    ),
), JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT); ?>
</script>
<?php endif; ?>
<style>
:root{--accent:#55c500;--accent-dark:#3d9400;--ink:#1a1a1a;--muted:#888;--line:#e5e7eb;--red:#bf0000}
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f9fafb;color:var(--ink);font-family:-apple-system,'Hiragino Sans',sans-serif}

/* ヘッダー */
.header{background:#fff;border-bottom:1px solid var(--line);padding:12px 20px;position:sticky;top:0;z-index:200;display:flex;align-items:center;gap:10px}
.header h1{font-size:17px;font-weight:700}
.badge{background:var(--accent);color:#fff;font-size:11px;padding:2px 8px;border-radius:10px}
.userbar{display:flex;align-items:center;gap:.6rem;font-size:.8rem;margin-left:auto}
.userbar strong{color:#059669}
.btn-sm{border:1px solid var(--line);padding:3px 10px;border-radius:4px;color:var(--muted);text-decoration:none;font-size:.75rem}
.btn-sm:hover{border-color:#dc2626;color:#dc2626}
.btn-login-sm{border:1px solid var(--accent);padding:4px 12px;border-radius:4px;color:var(--accent-dark);text-decoration:none;font-size:.75rem}
.btn-login-sm:hover{background:#f0fce8}

/* 管理者フォーム */
.admin-form{background:#f0fce8;border-bottom:2px solid var(--accent);padding:14px 20px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.admin-form-label{font-size:12px;color:var(--accent-dark);font-weight:700;white-space:nowrap}
.admin-form input[type=text]{flex:1;min-width:200px;border:1px solid #c6e6a4;border-radius:6px;padding:7px 12px;font-size:13px;outline:none}
.admin-form input[type=text]:focus{border-color:var(--accent)}
.admin-register-btn{background:var(--accent);color:#fff;border:none;border-radius:6px;padding:7px 18px;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap;transition:background .15s}
.admin-register-btn:hover{background:var(--accent-dark)}
.admin-register-btn:disabled{background:#bbb;cursor:not-allowed}
.admin-status{font-size:12px;padding:4px 10px;border-radius:4px;display:none}
.admin-status.ok{background:#dcfce7;color:#166534;display:inline-block}
.admin-status.err{background:#fee2e2;color:#991b1b;display:inline-block}
.admin-status.loading{background:#f0fce8;color:var(--accent-dark);display:inline-block}

/* タグフィルタ */
.tag-filter{background:#fff;border-bottom:1px solid var(--line);padding:10px 20px;display:flex;flex-wrap:wrap;gap:6px;align-items:flex-start;max-height:148px;overflow-y:auto}
.tag-filter-label{font-size:12px;color:var(--muted);white-space:nowrap;margin-right:2px}
.tag-btn{background:#f0f0f0;border:1px solid var(--line);border-radius:20px;padding:3px 12px;font-size:12px;color:#555;text-decoration:none;cursor:pointer;transition:all .15s;white-space:nowrap}
.tag-btn:hover{border-color:var(--accent);color:var(--accent-dark)}
.tag-btn.active{background:var(--accent);border-color:var(--accent);color:#fff}

/* グリッド */
.container{max-width:1100px;margin:0 auto;padding:12px 16px 80px}
.count-bar{font-size:13px;color:var(--muted);padding:8px 0 12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}
@media(min-width:600px){.grid{grid-template-columns:repeat(auto-fill,minmax(180px,1fr))}}
@media(min-width:900px){.grid{grid-template-columns:repeat(auto-fill,minmax(200px,1fr))}}

.card{background:#fff;border:1px solid var(--line);border-radius:6px;overflow:hidden;cursor:pointer;transition:box-shadow .15s,border-color .15s;text-decoration:none;display:flex;flex-direction:column}
.card:hover{box-shadow:0 2px 8px rgba(0,0,0,.1);border-color:#bbb}
.card-img-wrap{width:100%;aspect-ratio:3/4;overflow:hidden;background:#f5f5f5;display:flex;align-items:center;justify-content:center}
.card-img-wrap img{width:100%;height:100%;object-fit:contain}
.card-body{padding:10px 10px 12px;display:flex;flex-direction:column;flex:1}
.card-maker{font-size:11px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-bottom:4px}
.card-name{font-size:13px;font-weight:600;line-height:1.5;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;margin-bottom:auto}
.card-price{font-size:14px;font-weight:700;color:var(--red);margin-top:8px}

.empty-msg{text-align:center;color:var(--muted);padding:60px 20px;font-size:15px}

/* 詳細パネル */
.detail-overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:300;display:flex;justify-content:flex-end;opacity:0;pointer-events:none;transition:opacity .25s}
.detail-overlay.open{opacity:1;pointer-events:all}
.detail-panel{background:#fff;width:100%;max-width:420px;height:100%;overflow-y:auto;padding:20px;position:relative;transform:translateX(100%);transition:transform .25s}
.detail-overlay.open .detail-panel{transform:translateX(0)}
.panel-close{position:absolute;top:14px;right:16px;background:none;border:none;font-size:22px;cursor:pointer;color:var(--muted);line-height:1}
.panel-close:hover{color:var(--ink)}
.panel-img{width:100%;max-width:180px;display:block;margin:0 auto 16px;border:1px solid var(--line);border-radius:4px}
.panel-maker{font-size:12px;color:var(--muted);margin-bottom:6px}
.panel-name{font-size:18px;font-weight:700;line-height:1.5;margin-bottom:8px}
.panel-price{font-size:20px;font-weight:700;color:var(--red);margin-bottom:14px}
.panel-desc{font-size:13px;line-height:1.8;color:#444;border-top:1px solid var(--line);padding-top:14px;margin-bottom:16px;max-height:300px;overflow-y:auto}
.panel-ai-desc{font-size:13px;line-height:1.8;color:#333;margin-bottom:16px}
.panel-actions{display:flex;flex-direction:column;gap:10px;margin-bottom:16px}
.btn-amazon{display:block;text-align:center;background:#ff9900;color:#fff;text-decoration:none;border-radius:6px;padding:12px;font-size:15px;font-weight:700}
.btn-amazon:hover{background:#e08800}
.btn-rakuten{display:block;text-align:center;background:#bf0000;color:#fff;text-decoration:none;border-radius:6px;padding:12px;font-size:15px;font-weight:700}
.btn-rakuten:hover{background:#990000}
.panel-btns2{display:flex;gap:8px}
.copy-btn2{flex:1;background:none;border:1px solid var(--line);border-radius:6px;padding:9px;font-size:13px;color:var(--muted);cursor:pointer}
.copy-btn2:hover{border-color:var(--accent);color:var(--accent-dark)}
.copy-btn2.copied{border-color:#22c55e;color:#22c55e}
.x-btn2{flex:1;display:flex;align-items:center;justify-content:center;background:#000;color:#fff;text-decoration:none;border-radius:6px;padding:9px;font-size:13px}
.x-btn2:hover{background:#333}

#load-sentinel{height:1px}
#load-indicator{text-align:center;padding:16px;font-size:13px;color:var(--muted);display:none}

#copy-toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%);background:#111;color:#fff;padding:10px 22px;border-radius:20px;font-size:13px;opacity:0;pointer-events:none;transition:opacity .3s;z-index:999}
#copy-toast.show{opacity:1}
</style>
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-BP0650KDFR"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-BP0650KDFR');
</script>
<script>
(function () {
    var s = document.createElement('script');
    s.src = '/simpletrack.php'
        + '?url=' + encodeURIComponent(location.href)
        + '&ref=' + encodeURIComponent(document.referrer);
    document.head.appendChild(s);
})();
</script>
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-2528616930208188"
     crossorigin="anonymous"></script>
</head>
<body>

<!-- ヘッダー -->
<div class="header">
  <div style="font-size:20px">🛒</div>
  <h1>Affiliate</h1>
  <span class="badge">AIxEC</span>
  <span class="badge">URL2AI</span>
  <div class="userbar">
    <?php if ($session_user): ?>
    <strong>@<?= h($session_user) ?></strong>
    <a href="?aff_logout=1" class="btn-sm">logout</a>
    <?php else: ?>
    <a href="?aff_login=1" class="btn-login-sm">X でログイン</a>
    <?php endif; ?>
  </div>
</div>
<?php include __DIR__ . '/vwork_promo.php'; ?>

<?php if ($is_admin): ?>
<div class="admin-form">
  <span class="admin-form-label">URL/ID</span>
  <input type="text" id="admin-url-input" placeholder="Amazon/楽天URL、ASIN、JAN/ISBN">
  <button class="admin-register-btn" id="admin-register-btn" onclick="adminRegister()">登録</button>
  <span class="admin-status" id="admin-status"></span>
</div>
<?php endif; ?>

<!-- タグフィルタ -->
<div class="tag-filter" id="tag-filter">
  <span class="tag-filter-label">タグ:</span>
  <span class="tag-btn active" data-maker="" onclick="filterByMaker(this,'')">すべて</span>
</div>

<!-- 商品グリッド -->
<div class="container">
  <div class="count-bar" id="count-bar">読み込み中...</div>
  <div class="grid" id="product-grid"></div>
  <div id="load-sentinel"></div>
  <div id="load-indicator">読み込み中...</div>
</div>

<!-- 詳細パネル -->
<div class="detail-overlay" id="detail-overlay" onclick="overlayClick(event)">
  <div class="detail-panel" id="detail-panel">
    <button class="panel-close" onclick="closeDetail()">×</button>
    <img id="d-img" class="panel-img" src="/images/noimage.jpg" alt="">
    <div class="panel-maker" id="d-maker"></div>
    <div class="panel-name" id="d-name"></div>
    <div class="panel-price" id="d-price"></div>
    <div class="panel-desc" id="d-desc"></div>
    <div class="panel-ai-desc" id="d-ai"></div>
    <div class="panel-actions">
      <a id="d-amazon" class="btn-amazon" href="#" target="_blank" rel="noopener nofollow">Amazon で見る →</a>
      <a id="d-rakuten" class="btn-rakuten" href="#" target="_blank" rel="noopener nofollow">楽天で見る →</a>
    </div>
    <div class="panel-btns2">
      <button class="copy-btn2" id="d-copy" onclick="copyDetail()">📋 コピー</button>
      <a class="x-btn2" id="d-x" href="#" target="_blank" rel="noopener">𝕏 投稿</a>
    </div>
  </div>
</div>

<div id="copy-toast">コピーしました</div>

<script>
var ALL_ITEMS      = [];
var API_OFFSET     = 0;
var API_LIMIT      = 30;
var API_DONE       = false;
var LOADING        = false;
var CUR_MAKER      = '';
var CUR_PRODUCT    = null;
var AUTO_OPEN_DONE = false;

function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function yen(n){ return n ? '¥'+Number(n).toLocaleString() : ''; }

/* ── タグ読み込み ── */
fetch('affiliate.php?api_tags=1')
  .then(function(r){ return r.json(); })
  .then(function(d){
    var tf = document.getElementById('tag-filter');
    (d.makers||[]).forEach(function(m){
      var span = document.createElement('span');
      span.className = 'tag-btn';
      span.dataset.maker = m.maker;
      span.textContent = m.maker + ' ' + m.count;
      span.onclick = function(){ filterByMaker(this, m.maker); };
      tf.appendChild(span);
    });
  });

function filterByMaker(el, maker) {
  document.querySelectorAll('.tag-btn').forEach(function(b){ b.classList.remove('active'); });
  el.classList.add('active');
  CUR_MAKER  = maker;
  ALL_ITEMS  = [];
  API_OFFSET = 0;
  API_DONE   = false;
  document.getElementById('product-grid').innerHTML = '';
  document.getElementById('count-bar').textContent = '読み込み中...';
  loadProducts();
}

/* ── 商品読み込み ── */
function loadProducts() {
  if (API_DONE || LOADING) return;
  LOADING = true;
  document.getElementById('load-indicator').style.display = 'block';
  var url = 'affiliate.php?api_products=1&offset='+API_OFFSET+'&limit='+API_LIMIT;
  if (CUR_MAKER) url += '&maker='+encodeURIComponent(CUR_MAKER);
  fetch(url)
    .then(function(r){ return r.json(); })
    .then(function(d){
      var items = d.items || [];
      if (items.length < API_LIMIT) API_DONE = true;
      API_OFFSET += items.length;
      ALL_ITEMS   = ALL_ITEMS.concat(items);
      renderCards(items);
      if (!AUTO_OPEN_DONE) {
        AUTO_OPEN_DONE = true;
        var _pid = new URLSearchParams(location.search).get('id');
        if (_pid) {
          for (var _i = 0; _i < ALL_ITEMS.length; _i++) {
            if (String(ALL_ITEMS[_i].id) === _pid) { openDetail(_i); break; }
          }
        }
      }
      document.getElementById('count-bar').textContent = ALL_ITEMS.length + '件' + (API_DONE ? '' : '〜');
      document.getElementById('load-indicator').style.display = 'none';
      LOADING = false;
    })
    .catch(function(){
      document.getElementById('load-indicator').style.display = 'none';
      LOADING = false;
    });
}

/* ── カードレンダリング ── */
function renderCards(items) {
  var grid = document.getElementById('product-grid');
  if (items.length === 0 && ALL_ITEMS.length === 0) {
    grid.innerHTML = '<div class="empty-msg">商品がありません</div>';
    return;
  }
  items.forEach(function(p, rel) {
    var idx = ALL_ITEMS.length - items.length + rel;
    var img = esc(p.image_url || '/images/noimage.jpg');
    var card = document.createElement('div');
    card.className = 'card';
    card.dataset.idx = idx;
    card.innerHTML =
      '<div class="card-img-wrap"><img src="'+img+'" alt="'+esc(p.name)+'" loading="lazy"></div>'
      +'<div class="card-body">'
      +'<div class="card-maker">'+esc(p.maker||'')+'</div>'
      +'<div class="card-name">'+esc(p.name)+'</div>'
      +(p.sale_price ? '<div class="card-price">'+yen(p.sale_price)+'</div>' : '')
      +'</div>';
    (function(i, pid) {
      card.onclick = function() {
        history.replaceState(null, '', '/affiliate.php?id=' + pid);
        openDetail(i);
      };
    })(idx, p.id);
    grid.appendChild(card);
  });
}

/* ── 詳細パネル ── */
function openDetail(idx) {
  var p = ALL_ITEMS[idx];
  if (!p) return;
  CUR_PRODUCT = p;
  document.getElementById('d-img').src = p.image_url || '/images/noimage.jpg';
  document.getElementById('d-img').alt = p.name || '';
  document.getElementById('d-maker').textContent = p.maker || '';
  document.getElementById('d-name').textContent  = p.name  || '';
  document.getElementById('d-price').textContent = yen(p.sale_price);
  document.getElementById('d-desc').innerHTML    = p.description
    ? p.description.replace(/\n/g,'<br>') : '<span style="color:#bbb">説明なし</span>';
  document.getElementById('d-ai').innerHTML = p.book_description_ai || '';

  var amazonEl  = document.getElementById('d-amazon');
  var rakutenEl = document.getElementById('d-rakuten');

  function goUrl(provider) {
    var params = 'to='+provider+'&kw='+encodeURIComponent(p.name||'')+'&pid='+encodeURIComponent(p.id||'');
    var jan = (p.jan||'').replace(/\D/g,'');
    if (jan)        params += '&jan='+encodeURIComponent(jan);
    if (p.asin)     params += '&asin='+encodeURIComponent(p.asin);
    if (p.model_number) params += '&model='+encodeURIComponent(p.model_number);
    return '/go.php?'+params;
  }

  if (p.amazon_url || p.asin) {
    amazonEl.href = goUrl('amazon');
    amazonEl.style.display = 'block';
  } else {
    amazonEl.style.display = 'none';
  }
  if (p.rakuten_url || p.jan) {
    rakutenEl.href = goUrl('rakuten');
    rakutenEl.style.display = 'block';
  } else {
    rakutenEl.style.display = 'none';
  }

  var shareLines = [p.name];
  if (p.maker) shareLines.push(p.maker);
  if (p.description) shareLines.push((p.description).substring(0,80)+(p.description.length>80?'…':''));
  shareLines.push('');
  if (p.amazon_url || p.asin)    shareLines.push('Amazon: ' + amazonEl.href);
  if (p.rakuten_url || p.jan)    shareLines.push('楽天: '   + rakutenEl.href);
  var shareText = shareLines.join('\n');

  document.getElementById('d-x').href = 'https://twitter.com/intent/tweet?text=' + encodeURIComponent(shareText);

  var overlay = document.getElementById('detail-overlay');
  overlay.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeDetail() {
  document.getElementById('detail-overlay').classList.remove('open');
  document.body.style.overflow = '';
}
function overlayClick(e) { if (e.target===document.getElementById('detail-overlay')) closeDetail(); }

document.addEventListener('keydown', function(e){ if(e.key==='Escape') closeDetail(); });

function copyDetail() {
  var p = CUR_PRODUCT;
  if (!p) return;
  var amazonEl  = document.getElementById('d-amazon');
  var rakutenEl = document.getElementById('d-rakuten');
  var lines = [p.name];
  if (p.maker) lines.push(p.maker);
  if (p.description) lines.push((p.description).substring(0,80)+(p.description.length>80?'…':''));
  lines.push('');
  if (amazonEl  && amazonEl.style.display  !== 'none') lines.push('Amazon: ' + amazonEl.href);
  if (rakutenEl && rakutenEl.style.display !== 'none') lines.push('楽天: '   + rakutenEl.href);
  navigator.clipboard.writeText(lines.join('\n')).then(function(){
    var btn = document.getElementById('d-copy');
    btn.textContent='✓ コピー済'; btn.classList.add('copied');
    setTimeout(function(){ btn.textContent='📋 コピー'; btn.classList.remove('copied'); }, 2000);
    showToast('コピーしました');
  });
}

function showToast(msg){ var t=document.getElementById('copy-toast'); t.textContent=msg; t.classList.add('show'); setTimeout(function(){ t.classList.remove('show'); },2000); }

/* ── 無限スクロール ── */
var observer = new IntersectionObserver(function(entries){
  if (entries[0].isIntersecting) loadProducts();
}, { rootMargin:'300px' });
observer.observe(document.getElementById('load-sentinel'));
loadProducts();

<?php if ($is_admin): ?>
function adminRegister() {
  var input  = document.getElementById('admin-url-input').value.trim();
  var btn    = document.getElementById('admin-register-btn');
  var status = document.getElementById('admin-status');
  if (!input) { status.textContent='URL/IDを入力してください'; status.className='admin-status err'; return; }
  btn.disabled = true;
  status.textContent = '商品情報を取得中...';
  status.className = 'admin-status loading';
  var xhr = new XMLHttpRequest();
  xhr.open('POST', 'saveaffiliate.php', true);
  xhr.setRequestHeader('Content-Type', 'application/json');
  xhr.onreadystatechange = function() {
    if (xhr.readyState !== 4) return;
    btn.disabled = false;
    try {
      var res = JSON.parse(xhr.responseText);
      if (res.status === 'ok') {
        status.textContent = '登録完了: ' + res.title;
        status.className = 'admin-status ok';
        document.getElementById('admin-url-input').value = '';
        setTimeout(function(){ location.reload(); }, 1500);
      } else if (res.status === 'duplicate') {
        status.textContent = '既に登録済みです: ' + res.title;
        status.className = 'admin-status ok';
      } else {
        status.textContent = 'エラー: ' + (res.error || '不明');
        status.className = 'admin-status err';
      }
    } catch(e) { status.textContent='通信エラー'; status.className='admin-status err'; }
  };
  xhr.send(JSON.stringify({ input: input }));
}
document.getElementById('admin-url-input').addEventListener('keydown', function(e){ if(e.key==='Enter') adminRegister(); });
<?php endif; ?>
</script>
</body>
</html>
