<?php
session_start();
date_default_timezone_set("Asia/Tokyo");
header('Content-Type: application/json; charset=utf-8');

$API_PROXY = 'https://aixec.exbridge.jp/api.php';
$ADMIN     = 'xb_bittensor';

$session_user = $_SESSION['aff_username'] ?? '';
$is_admin     = ($session_user === $ADMIN);

if (!$is_admin) {
    echo json_encode(array('status' => 'error', 'error' => '権限がありません'));
    exit;
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

$data  = json_decode(file_get_contents('php://input'), true);
$input = trim($data['input'] ?? '');

if (!$input) {
    echo json_encode(array('status' => 'error', 'error' => '入力が空です'));
    exit;
}

// 楽天Books/Kobo URL → cURLでページ取得→タイトルから商品名抽出→キーワード検索
$is_rakuten_url = preg_match('#books\.rakuten\.co\.jp/(rk|rb|e)/[^?\s]+#', $input) ||
                  preg_match('#kobo\.rakuten\.co\.jp#', $input);
if ($is_rakuten_url) {
    $ch = curl_init($input);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 15);
    curl_setopt($ch, CURLOPT_ENCODING, 'gzip');
    curl_setopt($ch, CURLOPT_HTTPHEADER, array('Accept-Language: ja', 'User-Agent: Mozilla/5.0'));
    $html = curl_exec($ch);
    curl_close($ch);
    // タイトル形式: "楽天[ストア名]: [商品名] - [著者] - [番号]"
    $page_name   = '';
    $page_maker  = '';
    $page_rakurl = $input;
    if (preg_match('/<title[^>]*>([^<]+)<\/title>/u', $html, $tm)) {
        $ptitle = $tm[1];
        if (preg_match('/^楽天[^:：]*[:：]\s*(.+?)\s+-\s+([^-]+?)\s+-\s+[\d]+\s*$/', $ptitle, $pm)) {
            $page_name  = trim($pm[1]);
            $page_maker = trim($pm[2]);
        } elseif (preg_match('/^楽天[^:：]*[:：]\s*(.+)$/', $ptitle, $pm)) {
            $page_name = trim($pm[1]);
        }
    }
    if (!$page_name) {
        echo json_encode(array('status' => 'error', 'error' => '楽天ページから商品名を取得できませんでした'));
        exit;
    }
    // Rakuten BooksTotal キーワード検索
    $lookup = api_call('/lookup', array('keyword' => $page_name));
    if (!empty($lookup['found'])) {
        $p = $lookup['product'];
    } else {
        // API で見つからない場合はページ情報で直接登録
        $p = array('name' => $page_name, 'maker' => $page_maker, 'jan' => '', 'description' => '', 'sale_price' => 0, 'image_url' => '');
    }
    $payload = array(
        'name'               => $p['name']        ?? $page_name,
        'jan'                => $p['jan']         ?? '',
        'asin'               => $p['asin']        ?? '',
        'maker'              => $p['maker']       ?? $page_maker,
        'description'        => $p['description'] ?? '',
        'sale_price'         => (int)($p['sale_price'] ?? 0),
        'image_url'          => $p['image_url']   ?? '',
        'rakuten_url'        => $p['rakuten_url'] ?? $page_rakurl,
        'affiliate_priority' => 'affiliate',
        'status'             => 'published',
    );
    $reg = api_post('/products', $payload);
    if (empty($reg['ok'])) {
        echo json_encode(array('status' => 'error', 'error' => $reg['error'] ?? '登録失敗'));
        exit;
    }
    $product_id = $reg['item']['id'];
    $title      = $reg['item']['name'];
    api_call('/lp/generate', array('id' => $product_id));
    echo json_encode(array('status' => 'ok', 'title' => $title, 'id' => $product_id), JSON_UNESCAPED_UNICODE);
    exit;
}

$parsed = parse_input($input);

if ($parsed['type'] === 'jan') {
    $lookup = api_call('/lookup', array('jan' => $parsed['value']));
} elseif ($parsed['type'] === 'asin') {
    $lookup = api_call('/lookup', array('asin' => $parsed['value']));
} else {
    echo json_encode(array('status' => 'error', 'error' => 'URLまたはJAN/ASINを入力してください'));
    exit;
}

if (empty($lookup['found'])) {
    echo json_encode(array('status' => 'error', 'error' => '商品情報が見つかりません'));
    exit;
}

$p = $lookup['product'];
$payload = array(
    'name'               => $p['name']        ?? '',
    'jan'                => $p['jan']         ?? ($parsed['type'] === 'jan'  ? $parsed['value'] : ''),
    'asin'               => $p['asin']        ?? ($parsed['type'] === 'asin' ? $parsed['value'] : ''),
    'maker'              => $p['maker']       ?? '',
    'description'        => $p['description'] ?? '',
    'sale_price'         => (int)($p['sale_price'] ?? 0),
    'image_url'          => $p['image_url']   ?? '',
    'rakuten_url'        => $p['rakuten_url'] ?? '',
    'affiliate_priority' => 'affiliate',
    'status'             => 'published',
);

if (empty($payload['name'])) {
    echo json_encode(array('status' => 'error', 'error' => '商品名が取得できません'));
    exit;
}

$reg = api_post('/products', $payload);
if (empty($reg['ok'])) {
    echo json_encode(array('status' => 'error', 'error' => $reg['error'] ?? '登録失敗'));
    exit;
}

$product_id = $reg['item']['id'];
$title      = $reg['item']['name'];

api_call('/lp/generate', array('id' => $product_id));

echo json_encode(array('status' => 'ok', 'title' => $title, 'id' => $product_id), JSON_UNESCAPED_UNICODE);
