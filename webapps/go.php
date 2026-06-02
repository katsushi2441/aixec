<?php
date_default_timezone_set("Asia/Tokyo");

function hlog_field($value) {
    return str_replace(array("|", "\n", "\r"), array("", "", ""), trim((string)$value));
}

define("SIMPLETRACK_INTERNAL_KEY", "aixec-go-track-v1");
define("RAKUTEN_AFFILIATE_ID", "0b569b8b.f76b5de7.0b569b8c.0b66a994");

function go_is_bot_ua($ua) {
    $ua = strtolower(trim((string)$ua));
    if ($ua === '') return true;
    $bot_words = array(
        'bot', 'crawler', 'spider', 'slurp', 'crawl', 'mediapartners',
        'curl', 'wget', 'python', 'httpclient', 'scrapy', 'headless',
        'phantom', 'selenium', 'playwright', 'puppeteer',
        'facebookexternalhit', 'meta-externalagent', 'twitterbot', 'slackbot', 'discordbot',
        'linebot', 'googlebot', 'googleother', 'google-read-aloud', 'bingbot', 'duckduckbot', 'baiduspider',
        'yandexbot', 'ahrefsbot', 'semrushbot', 'mj12bot', 'petalbot',
        'bytespider', 'claudebot', 'gptbot', 'oai-searchbot', 'ccbot', 'perplexitybot',
        'applebot', 'amazonbot'
    );
    foreach ($bot_words as $word) {
        if (strpos($ua, $word) !== false) return true;
    }
    return false;
}

function api_get($path, $params) {
    $params = array_merge(array('path' => ltrim($path, '/')), $params);
    $url = 'https://aixec.exbridge.jp/api.php?' . http_build_query($params);
    $ch = curl_init($url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 12);
    $body = curl_exec($ch);
    curl_close($ch);
    if ($body === false || $body === '') return array();
    $json = json_decode($body, true);
    return is_array($json) ? $json : array();
}

function amazon_url($keyword, $asin, $jan = '') {
    if (preg_match('/^[A-Z0-9]{10}$/', $asin)) {
        return 'https://www.amazon.co.jp/dp/' . $asin . '?tag=bittensorman-22';
    }
    $jan = preg_replace('/\D/', '', (string)$jan);
    if (preg_match('/^\d{8,14}$/', $jan)) {
        return 'https://www.amazon.co.jp/s?k=' . rawurlencode($jan) . '&tag=bittensorman-22';
    }
    return 'https://www.amazon.co.jp/s?k=' . rawurlencode($keyword) . '&tag=bittensorman-22';
}

function rakuten_search_affiliate_url($keyword) {
    $search = 'https://search.rakuten.co.jp/search/mall/' . rawurlencode($keyword) . '/';
    return rakuten_affiliate_wrap_url($search);
}

function rakuten_affiliate_wrap_url($url) {
    return 'https://hb.afl.rakuten.co.jp/hgc/' . RAKUTEN_AFFILIATE_ID . '/?pc='
        . rawurlencode($url)
        . '&m=' . rawurlencode($url);
}

function rakuten_is_affiliate_url($url) {
    return strpos((string)$url, 'https://hb.afl.rakuten.co.jp/') === 0;
}

function rakuten_direct_or_affiliate_url($url) {
    $url = trim((string)$url);
    if ($url === '') return '';
    if (rakuten_is_affiliate_url($url)) return $url;
    if (strpos($url, 'https://books.rakuten.co.jp/') === 0 || strpos($url, 'https://item.rakuten.co.jp/') === 0) {
        return rakuten_affiliate_wrap_url($url);
    }
    return '';
}

function product_by_model($model) {
    $model = trim((string)$model);
    if ($model === '') return array();
    $res = api_get('products', array('q' => $model, 'limit' => 5));
    if (empty($res['ok']) || empty($res['items']) || !is_array($res['items'])) return array();
    foreach ($res['items'] as $item) {
        $item_model = isset($item['model_number']) ? (string)$item['model_number'] : '';
        if ($item_model === $model) {
            return $item;
        }
    }
    return $res['items'][0];
}

function product_by_id($pid) {
    $pid = preg_replace('/\D/', '', (string)$pid);
    if ($pid === '') return array();
    $res = api_get('products/' . $pid, array());
    if (empty($res['ok']) || empty($res['item']) || !is_array($res['item'])) return array();
    return $res['item'];
}

function product_jan_by_model($model) {
    $item = product_by_model($model);
    return !empty($item['jan']) ? preg_replace('/\D/', '', (string)$item['jan']) : '';
}

function product_jan($product) {
    foreach (array('jan', 'gtin') as $key) {
        if (!empty($product[$key])) {
            $jan = preg_replace('/\D/', '', (string)$product[$key]);
            if (preg_match('/^\d{8,14}$/', $jan)) return $jan;
        }
    }
    $description = isset($product['description']) ? (string)$product['description'] : '';
    if ($description !== '' && preg_match('/JAN(?:コード)?[^\d]*(\d{8,14})/u', $description, $m)) {
        return $m[1];
    }
    return '';
}

function clean_rakuten_keyword($keyword) {
    $keyword = preg_replace('/【(?:送料無料|激安|セール)】/u', ' ', (string)$keyword);
    $keyword = preg_replace('/(?:送料無料|激安|セール)/u', ' ', $keyword);
    $keyword = preg_replace('/\s+/u', ' ', trim($keyword));
    return $keyword;
}

function search_model($model) {
    $model = trim((string)$model);
    if ($model === '') return '';
    if (preg_match('/^(?:HSH|MMS\d*)-(.+)$/i', $model, $m)) {
        return $m[1];
    }
    return $model;
}

function rakuten_token($value) {
    return strtolower(preg_replace('/[^a-z0-9]/i', '', (string)$value));
}

function rakuten_item_matches($item, $preferred) {
    $haystack = '';
    foreach (array('item_name', 'item_url', 'affiliate_url', 'item_code') as $key) {
        if (!empty($item[$key])) $haystack .= ' ' . $item[$key];
    }
    $haystack_token = rakuten_token($haystack);
    $needle = rakuten_token(search_model($preferred));
    if ($needle !== '' && strpos($haystack_token, $needle) !== false) return true;
    return false;
}

function rakuten_item_affiliate_url($item) {
    foreach (array('affiliate_url', 'item_url') as $key) {
        if (empty($item[$key])) continue;
        $url = rakuten_direct_or_affiliate_url($item[$key]);
        if ($url !== '') return $url;
    }
    return '';
}

function rakuten_first_affiliate_url($keyword, $preferred = '') {
    $keyword = trim((string)$keyword);
    if ($keyword === '') return '';
    $res = api_get('rakuten/search', array('q' => $keyword, 'hits' => 5));
    $items = (!empty($res['ok']) && !empty($res['result']['items']) && is_array($res['result']['items'])) ? $res['result']['items'] : array();
    if (!$items) return '';
    if ($preferred !== '') {
        foreach ($items as $item) {
            if (rakuten_item_matches($item, $preferred)) {
                $url = rakuten_item_affiliate_url($item);
                if ($url !== '') return $url;
            }
        }
    }
    return rakuten_item_affiliate_url($items[0]);
}

function rakuten_url($keyword, $jan, $model, $product) {
    if (!empty($product['rakuten_url']) && stripos((string)$product['rakuten_url'], '/go.php') === false) {
        $product_rakuten_url = rakuten_direct_or_affiliate_url($product['rakuten_url']);
        if ($product_rakuten_url !== '') return $product_rakuten_url;
    }
    $jan = preg_replace('/\D/', '', (string)$jan);
    $maker = !empty($product['maker']) ? trim((string)$product['maker']) : '';
    $model_for_search = search_model($model);
    $candidates = array();
    if ($jan !== '') $candidates[] = $jan;
    if ($maker !== '' && $model_for_search !== '') $candidates[] = $maker . ' ' . $model_for_search;
    if ($model_for_search !== '') $candidates[] = $model_for_search;
    if (!$candidates) $candidates[] = clean_rakuten_keyword($keyword);
    $seen = array();
    foreach ($candidates as $candidate) {
        $candidate = trim((string)$candidate);
        if ($candidate === '' || isset($seen[$candidate])) continue;
        $seen[$candidate] = true;
        $url = rakuten_first_affiliate_url($candidate, $model_for_search);
        if ($url !== '') return $url;
    }
    $fallback = ($maker !== '' && $model_for_search !== '') ? ($maker . ' ' . $model_for_search) : ($model_for_search !== '' ? $model_for_search : clean_rakuten_keyword($keyword));
    return rakuten_search_affiliate_url($fallback);
}

$to = isset($_GET['to']) ? strtolower(trim($_GET['to'])) : '';
$kw = isset($_GET['kw']) ? trim($_GET['kw']) : '';
$pid = isset($_GET['pid']) ? trim($_GET['pid']) : '';
$model = isset($_GET['model']) ? trim($_GET['model']) : '';
$asin = isset($_GET['asin']) ? strtoupper(trim($_GET['asin'])) : '';
$jan = isset($_GET['jan']) ? trim($_GET['jan']) : '';
$direct_url = isset($_GET['url']) ? trim($_GET['url']) : '';
$ua = isset($_SERVER['HTTP_USER_AGENT']) ? $_SERVER['HTTP_USER_AGENT'] : '';
$from = isset($_GET['from']) ? trim((string)$_GET['from']) : '';
$ref = isset($_SERVER['HTTP_REFERER']) ? $_SERVER['HTTP_REFERER'] : '';

if (go_is_bot_ua($ua)) {
    header('Cache-Control: no-store');
    header('X-Robots-Tag: noindex, nofollow, noarchive');
    http_response_code(204);
    exit;
}

// プリフェッチ・プリレンダリングを除外（ブラウザ/OGPクローラーによる偽クリック防止）
$_purpose     = isset($_SERVER['HTTP_PURPOSE'])     ? strtolower(trim($_SERVER['HTTP_PURPOSE']))     : '';
$_sec_purpose = isset($_SERVER['HTTP_SEC_PURPOSE']) ? strtolower(trim($_SERVER['HTTP_SEC_PURPOSE'])) : '';
$_x_moz       = isset($_SERVER['HTTP_X_MOZ'])       ? strtolower(trim($_SERVER['HTTP_X_MOZ']))       : '';
if ($_purpose === 'prefetch' || $_sec_purpose === 'prefetch' || $_x_moz === 'prefetch') {
    header('Cache-Control: no-store');
    http_response_code(204);
    exit;
}

if ($from === '' && $ref === '') {
    header('Cache-Control: no-store');
    header('X-Robots-Tag: noindex, nofollow, noarchive');
    http_response_code(204);
    exit;
}

if ($kw === '') $kw = '電動工具';
$kw = mb_substr($kw, 0, 200, 'UTF-8');
$product = array();
if ($pid !== '') {
    $product = product_by_id($pid);
}
if (!$product && $model !== '') {
    $product = product_by_model($model);
}
if ($jan === '' && $product) {
    $jan = product_jan($product);
}
if ($jan === '' && $model !== '') {
    $jan = product_jan_by_model($model);
}
if ($asin === '' && !empty($product['asin'])) {
    $asin = strtoupper(trim((string)$product['asin']));
}

$direct_rakuten_url = rakuten_direct_or_affiliate_url($direct_url);

if ($direct_rakuten_url !== '') {
    $dest = $direct_rakuten_url;
} elseif ($to === 'amazon') {
    $dest = amazon_url($kw, $asin, $jan);
} elseif ($to === 'rakuten') {
    $dest = rakuten_url($kw, $jan, $model, $product);
} else {
    header('HTTP/1.1 400 Bad Request');
    echo 'bad request';
    exit;
}

$host = isset($_SERVER['HTTP_HOST']) ? $_SERVER['HTTP_HOST'] : 'aixec.exbridge.jp';
$request_uri = isset($_SERVER['REQUEST_URI']) ? $_SERVER['REQUEST_URI'] : '/go.php';
$click_url = 'https://' . $host . $request_uri;
$ip = isset($_SERVER['REMOTE_ADDR']) ? $_SERVER['REMOTE_ADDR'] : '';
if ($from === '' && $ref !== '') {
    $ref_parts = parse_url($ref);
    $ref_path = isset($ref_parts['path']) ? $ref_parts['path'] : '';
    $ref_query = isset($ref_parts['query']) ? ('?' . $ref_parts['query']) : '';
    $from = trim($ref_path . $ref_query);
}

$click_url .= (strpos($click_url, '?') === false ? '?' : '&')
    . 'click=' . rawurlencode($to)
    . '&product_id=' . rawurlencode($pid)
    . '&model_number=' . rawurlencode($model)
    . '&jan=' . rawurlencode($jan)
    . '&asin=' . rawurlencode($asin)
    . '&from=' . rawurlencode($from);

$track_url = 'https://aixec.exbridge.jp/simpletrack.php?' . http_build_query(array(
    'url' => $click_url,
    'ref' => $ref,
    'ip' => $ip,
    'ua' => $ua,
    'st_key' => SIMPLETRACK_INTERNAL_KEY,
));
$track_ctx = stream_context_create(array(
    'http' => array(
        'method' => 'GET',
        'timeout' => 2,
        'header' => "User-Agent: " . hlog_field($ua) . "\r\n",
        'ignore_errors' => true,
    )
));
@file_get_contents($track_url, false, $track_ctx);

header('Cache-Control: no-store');
header('Location: ' . $dest, true, 302);
exit;
