<?php
session_start();
date_default_timezone_set("Asia/Tokyo");
$API_BASE  = 'http://localhost:8081';
$BASE_URL  = 'https://aiknowledgecms.exbridge.jp';
$THIS_FILE = 'affiliate.php';
$SITE_NAME = 'AIxEC Affiliate';
$ADMIN     = 'xb_bittensor';

/* X API キー読み込み */
$x_keys_file = __DIR__ . '/x_api_keys.sh';
$x_keys = array();
if (file_exists($x_keys_file)) {
    foreach (file($x_keys_file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (preg_match('/(?:export\s+)?(\w+)=["\']?([^"\'#\r\n]*)["\']?/', $line, $m))
            $x_keys[trim($m[1])] = trim($m[2]);
    }
}
$x_client_id     = $x_keys['X_API_KEY']    ?? '';
$x_client_secret = $x_keys['X_API_SECRET'] ?? '';
$x_redirect_uri  = $BASE_URL . '/' . $THIS_FILE;

function aff_base64url($d) { return rtrim(strtr(base64_encode($d), '+/', '-_'), '='); }
function aff_gen_verifier() {
    $b = ''; for ($i = 0; $i < 32; $i++) $b .= chr(mt_rand(0, 255)); return aff_base64url($b);
}
function aff_gen_challenge($v) { return aff_base64url(hash('sha256', $v, true)); }
function aff_x_post($url, $data, $headers) {
    $opts = array('http' => array('method' => 'POST', 'header' => implode("\r\n", $headers) . "\r\n", 'content' => $data, 'timeout' => 12, 'ignore_errors' => true));
    $r = @file_get_contents($url, false, stream_context_create($opts));
    return json_decode($r ?: '{}', true);
}
function aff_x_get($url, $token) {
    $opts = array('http' => array('method' => 'GET', 'header' => "Authorization: Bearer $token\r\nUser-Agent: AffiliateManager/1.0\r\n", 'timeout' => 12, 'ignore_errors' => true));
    $r = @file_get_contents($url, false, stream_context_create($opts));
    return json_decode($r ?: '{}', true);
}
function api_call($path, $params = array()) {
    global $API_BASE;
    $url = rtrim($API_BASE, '/') . $path . ($params ? '?' . http_build_query($params) : '');
    $opts = array('http' => array('method' => 'GET', 'timeout' => 15, 'ignore_errors' => true));
    $r = @file_get_contents($url, false, stream_context_create($opts));
    return json_decode($r ?: '{}', true);
}
function api_post($path, $payload) {
    global $API_BASE;
    $url  = rtrim($API_BASE, '/') . $path;
    $body = json_encode($payload, JSON_UNESCAPED_UNICODE);
    $opts = array('http' => array('method' => 'POST', 'header' => "Content-Type: application/json\r\n", 'content' => $body, 'timeout' => 15, 'ignore_errors' => true));
    $r = @file_get_contents($url, false, stream_context_create($opts));
    return json_decode($r ?: '{}', true);
}
function parse_input($input) {
    $input = trim($input);
    if (preg_match('|amazon\.co\.jp.*/(?:dp|gp/product)/([A-Z0-9]{10})|', $input, $m))
        return array('type' => 'asin', 'value' => $m[1]);
    if (preg_match('/amazon\.com.*\/([A-Z0-9]{10})(?:\/|\?|$)/', $input, $m))
        return array('type' => 'asin', 'value' => $m[1]);
    if (preg_match('/(\d{13})/', $input, $m))
        return array('type' => 'jan', 'value' => $m[1]);
    if (preg_match('/^[A-Z0-9]{10}$/', $input))
        return array('type' => 'asin', 'value' => $input);
    return array('type' => 'unknown', 'value' => $input);
}
function h($s) { return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8'); }

/* X OAuth フロー */
if (isset($_GET['aff_logout'])) { session_destroy(); header('Location: ' . $x_redirect_uri); exit; }
if (isset($_GET['aff_login'])) {
    $ver = aff_gen_verifier();
    $chal = aff_gen_challenge($ver);
    $state = md5(uniqid('', true));
    $_SESSION['aff_code_verifier'] = $ver;
    $_SESSION['aff_oauth_state']   = $state;
    $p = array('response_type' => 'code', 'client_id' => $x_client_id, 'redirect_uri' => $x_redirect_uri,
               'scope' => 'tweet.read users.read', 'state' => $state, 'code_challenge' => $chal, 'code_challenge_method' => 'S256');
    header('Location: https://twitter.com/i/oauth2/authorize?' . http_build_query($p)); exit;
}
if (isset($_GET['code'], $_GET['state'], $_SESSION['aff_oauth_state'])) {
    if ($_GET['state'] === $_SESSION['aff_oauth_state']) {
        $post = http_build_query(array('grant_type' => 'authorization_code', 'code' => $_GET['code'],
            'redirect_uri' => $x_redirect_uri, 'code_verifier' => $_SESSION['aff_code_verifier'], 'client_id' => $x_client_id));
        $cred = base64_encode($x_client_id . ':' . $x_client_secret);
        $data = aff_x_post('https://api.twitter.com/2/oauth2/token', $post, array('Content-Type: application/x-www-form-urlencoded', 'Authorization: Basic ' . $cred));
        if (isset($data['access_token'])) {
            $_SESSION['aff_access_token'] = $data['access_token'];
            unset($_SESSION['aff_oauth_state'], $_SESSION['aff_code_verifier']);
            $me = aff_x_get('https://api.twitter.com/2/users/me', $data['access_token']);
            if (isset($me['data']['username'])) $_SESSION['aff_username'] = $me['data']['username'];
        }
    }
    header('Location: ' . $x_redirect_uri); exit;
}

$session_user = $_SESSION['aff_username'] ?? '';
$is_admin     = ($session_user === $ADMIN);
$logged_in    = ($session_user !== '');

/* 商品リスト API（内部 AJAX 用） */
if (isset($_GET['api_products'])) {
    header('Content-Type: application/json; charset=utf-8');
    $limit  = min(50, max(1, (int)($_GET['limit'] ?? 30)));
    $offset = max(0, (int)($_GET['offset'] ?? 0));
    $res = api_call('/products', array('affiliate' => 'true', 'limit' => $limit, 'offset' => $offset));
    echo json_encode(array('items' => $res['items'] ?? array()), JSON_UNESCAPED_UNICODE);
    exit;
}

/* ルックアップ（JSON応答） */
if (isset($_GET['lookup']) && $is_admin) {
    header('Content-Type: application/json; charset=utf-8');
    $q = trim($_GET['q'] ?? '');
    if (!$q) { echo json_encode(array('ok' => false, 'error' => 'empty')); exit; }
    $parsed = parse_input($q);
    if ($parsed['type'] === 'jan') {
        $res = api_call('/lookup', array('jan' => $parsed['value']));
    } elseif ($parsed['type'] === 'asin') {
        $res = api_call('/lookup', array('asin' => $parsed['value']));
    } else {
        $res = array('ok' => false, 'found' => false, 'product' => array());
    }
    echo json_encode($res, JSON_UNESCAPED_UNICODE);
    exit;
}

/* 登録処理（管理者のみ） */
$register_msg = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['action']) && $_POST['action'] === 'register' && $is_admin) {
    $payload = array(
        'name'               => trim($_POST['name'] ?? ''),
        'jan'                => preg_replace('/\D/', '', $_POST['jan'] ?? ''),
        'asin'               => preg_replace('/[^A-Z0-9]/', '', strtoupper($_POST['asin'] ?? '')),
        'maker'              => trim($_POST['maker'] ?? ''),
        'description'        => trim($_POST['description'] ?? ''),
        'sale_price'         => (int)preg_replace('/\D/', '', $_POST['sale_price'] ?? '0'),
        'amazon_url'         => trim($_POST['amazon_url'] ?? ''),
        'rakuten_url'        => trim($_POST['rakuten_url'] ?? ''),
        'affiliate_priority' => 'affiliate',
        'status'             => 'published',
    );
    if (empty($payload['name'])) {
        $register_msg = 'error:商品名は必須です';
    } else {
        $res = api_post('/products', $payload);
        if (!empty($res['ok'])) {
            $register_msg = 'ok:登録しました: ' . $res['item']['name'];
        } else {
            $register_msg = 'error:登録失敗: ' . ($res['error'] ?? '不明');
        }
    }
}
?><!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Affiliate Manager | AIxEC</title>
<meta name="robots" content="noindex">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #fff; color: #222; font-family: -apple-system, 'Helvetica Neue', sans-serif; }

.header {
    background: #fff; border-bottom: 1px solid #e5e7eb;
    padding: 14px 20px; position: sticky; top: 0; z-index: 100;
    display: flex; align-items: center; gap: 12px;
}
.header h1 { font-size: 17px; font-weight: 700; color: #111; }
.header .badge { background: #f59e0b; color: #fff; font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.userbar { display: flex; align-items: center; gap: .75rem; font-size: .8rem; margin-left: auto; }
.userbar strong { color: #059669; }
.btn-sm { border: 1px solid #cbd5e1; padding: 3px 10px; border-radius: 4px; color: #64748b; text-decoration: none; font-size: .75rem; }
.btn-sm:hover { border-color: #dc2626; color: #dc2626; }
.btn-login-sm { border: 1px solid #f59e0b; padding: 4px 12px; border-radius: 4px; color: #f59e0b; text-decoration: none; font-size: .75rem; }
.btn-login-sm:hover { background: #fffbeb; }

.register-area {
    background: #fffbeb; border-bottom: 2px solid #f59e0b;
    padding: 16px 20px;
}
.register-area h2 { font-size: 13px; font-weight: 700; color: #92400e; margin-bottom: 12px; }
.lookup-row { display: flex; gap: 8px; margin-bottom: 12px; }
.lookup-row input { flex: 1; border: 1px solid #d1d5db; border-radius: 6px; padding: 8px 12px; font-size: 13px; }
.lookup-row input:focus { outline: none; border-color: #f59e0b; }
.btn-lookup { background: #f59e0b; color: #fff; border: none; border-radius: 6px; padding: 8px 16px; font-size: 13px; font-weight: 600; cursor: pointer; white-space: nowrap; }
.btn-lookup:hover { background: #d97706; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.form-grid .full { grid-column: 1 / -1; }
.form-group label { display: block; font-size: 11px; color: #6b7280; margin-bottom: 3px; }
.form-group input, .form-group textarea {
    width: 100%; border: 1px solid #d1d5db; border-radius: 6px;
    padding: 7px 10px; font-size: 13px;
}
.form-group input:focus, .form-group textarea:focus { outline: none; border-color: #f59e0b; }
.form-group textarea { resize: vertical; min-height: 64px; }
.btn-register { background: #059669; color: #fff; border: none; border-radius: 6px; padding: 9px 24px; font-size: 14px; font-weight: 700; cursor: pointer; margin-top: 10px; }
.btn-register:hover { background: #047857; }
.register-msg { margin-top: 8px; padding: 7px 12px; border-radius: 6px; font-size: 13px; }
.register-msg.ok  { background: #dcfce7; color: #166534; }
.register-msg.err { background: #fee2e2; color: #991b1b; }

.container { max-width: 640px; margin: 0 auto; padding: 0 0 80px; }
.count-bar { padding: 10px 20px; font-size: 13px; color: #888; border-bottom: 1px solid #f0f0f0; }

.product-card { border-bottom: 1px solid #f0f0f0; padding: 16px 20px; transition: background 0.15s; }
.product-card:hover { background: #fafafa; }
.product-name { font-size: 15px; font-weight: 700; color: #111; margin-bottom: 6px; }
.product-meta { font-size: 12px; color: #888; margin-bottom: 6px; display: flex; flex-wrap: wrap; gap: 10px; }
.product-desc { font-size: 13px; color: #555; line-height: 1.6; margin-bottom: 10px; }
.product-actions { display: flex; flex-wrap: wrap; gap: 6px; }

.copy-btn {
    background: none; border: 1px solid #e5e7eb; border-radius: 6px;
    padding: 5px 12px; font-size: 12px; color: #888; cursor: pointer; transition: all 0.15s;
}
.copy-btn:hover { border-color: #f59e0b; color: #f59e0b; }
.copy-btn.copied { border-color: #22c55e; color: #22c55e; }
.x-btn {
    background: #000; border: 1px solid #000; border-radius: 6px;
    padding: 5px 12px; font-size: 12px; color: #fff; text-decoration: none;
    display: inline-flex; align-items: center; gap: 4px; transition: background 0.15s;
}
.x-btn:hover { background: #333; }
.link-btn {
    border: 1px solid #e5e7eb; border-radius: 6px;
    padding: 5px 12px; font-size: 12px; color: #3b82f6; text-decoration: none; transition: all 0.15s;
}
.link-btn:hover { border-color: #3b82f6; background: #eff6ff; }
.price-badge { font-size: 13px; font-weight: 700; color: #dc2626; }

.empty { text-align: center; color: #bbb; padding: 80px 20px; font-size: 15px; }

#copy-toast {
    position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%);
    background: #111; color: #fff; padding: 10px 22px; border-radius: 20px;
    font-size: 13px; opacity: 0; pointer-events: none; transition: opacity 0.3s; z-index: 999;
}
#copy-toast.show { opacity: 1; }
</style>
</head>
<body>

<div class="header">
    <div style="font-size:22px">🛒</div>
    <h1>Affiliate</h1>
    <span class="badge">AIxEC</span>
    <div class="userbar">
        <?php if ($logged_in): ?>
        <strong>@<?= h($session_user) ?></strong>
        <a href="?aff_logout=1" class="btn-sm">logout</a>
        <?php else: ?>
        <a href="?aff_login=1" class="btn-login-sm">X でログイン</a>
        <?php endif; ?>
    </div>
</div>

<?php if ($is_admin): ?>
<div class="register-area">
    <h2>🔧 商品登録</h2>
    <div class="lookup-row">
        <input type="text" id="lookup-input" placeholder="Amazon/楽天URL、ASIN、JAN/ISBNを入力">
        <button class="btn-lookup" onclick="doLookup()">検索して入力</button>
    </div>
    <?php
    $msg_parts = $register_msg ? explode(':', $register_msg, 2) : array();
    $msg_type  = $msg_parts[0] ?? '';
    $msg_text  = $msg_parts[1] ?? '';
    if ($msg_text): ?>
    <div class="register-msg <?= h($msg_type) ?>"><?= h($msg_text) ?></div>
    <?php endif; ?>
    <form method="post">
        <input type="hidden" name="action" value="register">
        <div class="form-grid">
            <div class="form-group full">
                <label>商品名 *</label>
                <input type="text" name="name" id="f-name" required>
            </div>
            <div class="form-group">
                <label>著者 / メーカー</label>
                <input type="text" name="maker" id="f-maker">
            </div>
            <div class="form-group">
                <label>出版社</label>
                <input type="text" name="publisher" id="f-publisher">
            </div>
            <div class="form-group">
                <label>JAN / ISBN</label>
                <input type="text" name="jan" id="f-jan">
            </div>
            <div class="form-group">
                <label>ASIN</label>
                <input type="text" name="asin" id="f-asin">
            </div>
            <div class="form-group">
                <label>価格（円）</label>
                <input type="text" name="sale_price" id="f-price">
            </div>
            <div class="form-group full">
                <label>Amazon URL</label>
                <input type="text" name="amazon_url" id="f-amazon">
            </div>
            <div class="form-group full">
                <label>楽天 URL</label>
                <input type="text" name="rakuten_url" id="f-rakuten">
            </div>
            <div class="form-group full">
                <label>説明文</label>
                <textarea name="description" id="f-desc"></textarea>
            </div>
        </div>
        <button type="submit" class="btn-register">登録する</button>
    </form>
</div>
<?php endif; ?>

<div class="container">
<div class="count-bar" id="count-bar">読み込み中...</div>
<div id="product-list"></div>
<div id="load-sentinel" style="height:1px;"></div>
<div id="load-indicator" style="display:none;text-align:center;padding:16px;font-size:13px;color:#888;">読み込み中...</div>
</div>

<div id="copy-toast">コピーしました</div>

<script>
var API_OFFSET = 0;
var API_LIMIT  = 30;
var API_DONE   = false;
var all_items  = [];

function esc(s) {
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function yen(n) {
    return n ? '¥' + Number(n).toLocaleString() : '';
}

function loadProducts() {
    if (API_DONE) return;
    fetch('affiliate.php?api_products=1&offset=' + API_OFFSET + '&limit=' + API_LIMIT)
        .then(function(r){ return r.json(); })
        .then(function(d){
            var items = d.items || [];
            if (items.length < API_LIMIT) API_DONE = true;
            API_OFFSET += items.length;
            all_items = all_items.concat(items);
            renderItems(items);
            document.getElementById('count-bar').textContent = all_items.length + '件' + (API_DONE ? '' : '+');
            document.getElementById('load-indicator').style.display = 'none';
        })
        .catch(function(){
            document.getElementById('load-indicator').style.display = 'none';
        });
}

function renderItems(items) {
    var list = document.getElementById('product-list');
    if (items.length === 0 && all_items.length === 0) {
        list.innerHTML = '<div class="empty">登録された商品がありません</div>';
        return;
    }
    items.forEach(function(p, rel) {
        var idx = all_items.length - items.length + rel;
        var meta = [];
        if (p.jan)  meta.push('JAN: ' + esc(p.jan));
        if (p.asin) meta.push('ASIN: ' + esc(p.asin));
        if (p.maker) meta.push(esc(p.maker));
        var priceHtml = p.sale_price ? '<span class="price-badge">' + yen(p.sale_price) + '</span>' : '';
        var desc = p.description ? '<div class="product-desc">' + esc(p.description).substring(0, 120) + (p.description.length > 120 ? '...' : '') + '</div>' : '';
        var links = '';
        if (p.amazon_url)  links += '<a class="link-btn" href="' + esc(p.amazon_url)  + '" target="_blank" rel="noopener nofollow">Amazon →</a>';
        if (p.rakuten_url) links += '<a class="link-btn" href="' + esc(p.rakuten_url) + '" target="_blank" rel="noopener nofollow">楽天 →</a>';
        var html = '<div class="product-card" data-idx="' + idx + '">'
            + '<div class="product-name">' + esc(p.name) + '</div>'
            + (meta.length ? '<div class="product-meta">' + meta.join('<span style="color:#ddd">｜</span>') + (priceHtml ? '<span style="color:#ddd">｜</span>' + priceHtml : '') + '</div>' : (priceHtml ? '<div class="product-meta">' + priceHtml + '</div>' : ''))
            + desc
            + '<div class="product-actions">'
            + '<button class="copy-btn" onclick="copyProduct(' + idx + ')">📋 コピー</button>'
            + '<a class="x-btn" href="' + buildXUrl(p) + '" target="_blank" rel="noopener">𝕏</a>'
            + links
            + '</div></div>';
        list.insertAdjacentHTML('beforeend', html);
    });
}

function buildCopyText(p) {
    var lines = [];
    lines.push(p.name);
    if (p.maker) lines.push('著者: ' + p.maker);
    lines.push('');
    if (p.description) lines.push(p.description.substring(0, 200) + (p.description.length > 200 ? '…' : ''));
    lines.push('');
    if (p.sale_price) lines.push('価格: ¥' + Number(p.sale_price).toLocaleString());
    if (p.amazon_url)  lines.push('Amazon: ' + p.amazon_url);
    if (p.rakuten_url) lines.push('楽天: ' + p.rakuten_url);
    return lines.filter(function(l){ return l !== undefined; }).join('\n');
}

function buildXUrl(p) {
    var text = p.name + '\n';
    if (p.description) text += p.description.substring(0, 80) + '\n';
    text += (p.amazon_url || p.rakuten_url || '');
    return 'https://twitter.com/intent/tweet?text=' + encodeURIComponent(text);
}

function copyProduct(idx) {
    var p = all_items[idx];
    if (!p) return;
    navigator.clipboard.writeText(buildCopyText(p)).then(function() {
        var btn = document.querySelector('[data-idx="' + idx + '"] .copy-btn');
        if (btn) { btn.textContent = '✓ コピー済'; btn.classList.add('copied'); setTimeout(function(){ btn.textContent = '📋 コピー'; btn.classList.remove('copied'); }, 2000); }
        showToast('コピーしました');
    });
}

function showToast(msg) {
    var t = document.getElementById('copy-toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(function(){ t.classList.remove('show'); }, 2000);
}

/* IntersectionObserver で無限スクロール */
var sentinel = document.getElementById('load-sentinel');
var observer = new IntersectionObserver(function(entries) {
    if (entries[0].isIntersecting && !API_DONE) {
        document.getElementById('load-indicator').style.display = 'block';
        loadProducts();
    }
}, { rootMargin: '200px' });
observer.observe(sentinel);
loadProducts();

<?php if ($is_admin): ?>
/* ルックアップ */
function doLookup() {
    var q = document.getElementById('lookup-input').value.trim();
    if (!q) return;
    var btn = document.querySelector('.btn-lookup');
    btn.disabled = true;
    btn.textContent = '検索中...';
    fetch('affiliate.php?lookup=1&q=' + encodeURIComponent(q))
        .then(function(r){ return r.json(); })
        .then(function(d){
            btn.disabled = false;
            btn.textContent = '検索して入力';
            if (d.found && d.product) {
                var p = d.product;
                if (p.name)        document.getElementById('f-name').value    = p.name;
                if (p.maker)       document.getElementById('f-maker').value   = p.maker;
                if (p.publisher)   document.getElementById('f-publisher').value = p.publisher;
                if (p.jan)         document.getElementById('f-jan').value     = p.jan;
                if (p.asin)        document.getElementById('f-asin').value    = p.asin;
                if (p.sale_price)  document.getElementById('f-price').value   = p.sale_price;
                if (p.amazon_url)  document.getElementById('f-amazon').value  = p.amazon_url;
                if (p.rakuten_url) document.getElementById('f-rakuten').value = p.rakuten_url;
                if (p.description) document.getElementById('f-desc').value   = p.description;
            } else {
                alert('商品情報が見つかりませんでした。手動で入力してください。');
            }
        })
        .catch(function(){
            btn.disabled = false;
            btn.textContent = '検索して入力';
            alert('検索エラーが発生しました');
        });
}
document.getElementById('lookup-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') doLookup();
});
<?php endif; ?>
</script>

</body>
</html>
