<?php
date_default_timezone_set('Asia/Tokyo');
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');
if (isset($_SERVER['REQUEST_METHOD']) && $_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    exit;
}

function api_get($path, $params) {
    $params = array_merge(array('path' => ltrim($path, '/')), $params);
    $url = 'https://aixec.exbridge.jp/api.php?' . http_build_query($params);
    $ch = curl_init($url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 15);
    $body = curl_exec($ch);
    curl_close($ch);
    if ($body === false || $body === '') return array();
    $json = json_decode($body, true);
    return is_array($json) ? $json : array();
}

function make_slug($maker, $model, $name) {
    if (preg_match('/^([^-]+)-(.+)$/', $model, $m)) {
        if ($name === '' || mb_strpos($name, $m[1]) === false) {
            $model = $m[2];
        }
    }
    $digits = preg_replace('/\D/u', '', (string)$model);
    if (preg_match('/^[0-9]{10,14}$/', $digits) && trim($name) !== '') {
        $s = $digits . '-' . trim($name);
    } else {
        $s = trim($maker) . '-' . trim($model);
    }
    $s = preg_replace('/[\s\/\(\)\[\]\\\\\.]+/u', '-', $s);
    $s = preg_replace('/-+/', '-', $s);
    return trim($s, '-');
}

function absolute_url($url) {
    $url = (string)$url;
    if ($url === '') return '';
    if (preg_match('/^https?:\/\//i', $url)) return $url;
    if ($url[0] === '/') return 'https://aixec.exbridge.jp' . $url;
    return 'https://aixec.exbridge.jp/' . $url;
}

function log_query_params($line) {
    $parts = explode(' | ', $line);
    if (count($parts) < 3) return array();
    $query = parse_url(trim($parts[2]), PHP_URL_QUERY);
    if (!$query) return array();
    $params = array();
    parse_str($query, $params);
    return $params;
}

function ranking_keys_from_log($limit) {
    $path = __DIR__ . '/access.log';
    if (!is_readable($path)) return array();
    $lines = file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    if (!$lines) return array();
    $counts = array();
    for ($i = count($lines) - 1; $i >= 0; $i--) {
        $params = log_query_params($lines[$i]);
        $click = isset($params['click']) ? strtolower($params['click']) : '';
        $to = isset($params['to']) ? strtolower($params['to']) : '';
        if ($click !== 'rakuten' && $to !== 'rakuten') continue;
        $pid = isset($params['product_id']) ? trim($params['product_id']) : '';
        if ($pid === '' && isset($params['pid'])) $pid = trim($params['pid']);
        $jan = isset($params['jan']) ? preg_replace('/\D/', '', $params['jan']) : '';
        $model = isset($params['model_number']) ? trim($params['model_number']) : '';
        if ($model === '' && isset($params['model'])) $model = trim($params['model']);
        if ($pid !== '') {
            $key = 'id:' . $pid;
        } elseif ($jan !== '') {
            $key = 'jan:' . $jan;
        } elseif ($model !== '') {
            $key = 'model:' . $model;
        } else {
            continue;
        }
        if (!isset($counts[$key])) $counts[$key] = array('key' => $key, 'clicks' => 0);
        $counts[$key]['clicks']++;
    }
    usort($counts, function($a, $b) {
        if ($a['clicks'] == $b['clicks']) return 0;
        return ($a['clicks'] > $b['clicks']) ? -1 : 1;
    });
    return array_slice($counts, 0, $limit * 3);
}

function resolve_product($key) {
    if (strpos($key, 'id:') === 0) {
        $res = api_get('products/' . substr($key, 3), array());
        return !empty($res['ok']) && !empty($res['item']) ? $res['item'] : null;
    }
    $q = substr($key, strpos($key, ':') + 1);
    $res = api_get('products', array('q' => $q, 'limit' => 8));
    if (empty($res['ok']) || empty($res['items']) || !is_array($res['items'])) return null;
    foreach ($res['items'] as $item) {
        if (strpos($key, 'jan:') === 0 && !empty($item['jan']) && preg_replace('/\D/', '', $item['jan']) === $q) return $item;
        if (strpos($key, 'model:') === 0 && !empty($item['model_number']) && $item['model_number'] === $q) return $item;
    }
    return $res['items'][0];
}

function is_book_product($item) {
    if (!$item) return false;
    if (!empty($item['internal_sku']) && strpos($item['internal_sku'], 'rakuten_books:') === 0) return true;
    if (!empty($item['image_url']) && strpos($item['image_url'], '/images/products/books/') === 0) return true;
    return false;
}

function rakuten_click_url($item) {
    $params = array('to' => 'rakuten', 'kw' => isset($item['name']) ? $item['name'] : '本');
    if (!empty($item['id'])) $params['pid'] = $item['id'];
    if (!empty($item['model_number'])) $params['model'] = $item['model_number'];
    if (!empty($item['jan'])) $params['jan'] = preg_replace('/\D/', '', $item['jan']);
    return 'https://aixec.exbridge.jp/go.php?' . http_build_query($params);
}

function rakuten_book_click_url($book) {
    $params = array(
        'to' => 'rakuten',
        'kw' => isset($book['title']) ? $book['title'] : '本',
    );
    if (!empty($book['isbn'])) $params['jan'] = preg_replace('/\D/', '', $book['isbn']);
    $direct_url = !empty($book['affiliate_url']) ? $book['affiliate_url'] : (!empty($book['item_url']) ? $book['item_url'] : '');
    if ($direct_url !== '') $params['url'] = $direct_url;
    return 'https://aixec.exbridge.jp/go.php?' . http_build_query($params);
}

function fallback_books_ranking($limit, $offset_rank, $params = array()) {
    $params = array_merge(array('hits' => $limit), $params);
    $params['hits'] = $limit;
    $res = api_get('books/ranking', $params);
    $books = (!empty($res['ok']) && !empty($res['result']['items']) && is_array($res['result']['items']))
        ? $res['result']['items'] : array();
    $items = array();
    foreach ($books as $book) {
        $title = isset($book['title']) ? $book['title'] : '';
        if ($title === '') continue;
        $items[] = array(
            'rank' => $offset_rank + count($items) + 1,
            'clicks' => null,
            'id' => null,
            'title' => $title,
            'maker' => isset($book['publisher_name']) ? $book['publisher_name'] : '',
            'isbn' => isset($book['isbn']) ? $book['isbn'] : '',
            'price' => isset($book['item_price']) ? (int)$book['item_price'] : null,
            'image_url' => absolute_url(!empty($book['image_url']) ? $book['image_url'] : '/images/noimage.jpg'),
            'affiliate_url' => rakuten_book_click_url($book),
            'product_url' => !empty($book['item_url']) ? $book['item_url'] : '',
        );
        if (count($items) >= $limit) break;
    }
    return $items;
}

$limit = isset($_GET['limit']) ? (int)$_GET['limit'] : 10;
if ($limit < 1) $limit = 10;
if ($limit > 100) $limit = 100;

$tabs = array(
    'startup'     => array('label' => '起業・開業',        'params' => array('genre_id' => '001006018003')),
    'management'  => array('label' => '経営・マネジメント','params' => array('genre_id' => '001006018')),
    'ai'          => array('label' => 'AI・テクノロジー',  'params' => array('genre_id' => '001005', 'keyword' => 'AI')),
    'web3'        => array('label' => 'Web3・暗号資産',    'params' => array('keyword' => 'ブロックチェーン')),
    'programming' => array('label' => 'プログラミング・IT','params' => array('genre_id' => '001005005')),
    'health'      => array('label' => '健康・医療',        'params' => array('genre_id' => '001010010')),
);
$active_tab = isset($_GET['tab']) ? strtolower((string)$_GET['tab']) : '';

$items = array();
if ($active_tab !== '' && isset($tabs[$active_tab])) {
    $items = fallback_books_ranking($limit, 0, $tabs[$active_tab]['params']);
} else {
    $keys = ranking_keys_from_log($limit);
    foreach ($keys as $idx => $row) {
        $item = resolve_product($row['key']);
        if (!is_book_product($item)) continue;
        $slug = make_slug(isset($item['maker']) ? $item['maker'] : '', isset($item['model_number']) ? $item['model_number'] : '', isset($item['name']) ? $item['name'] : '');
        $items[] = array(
            'rank' => count($items) + 1,
            'clicks' => (int)$row['clicks'],
            'id' => isset($item['id']) ? (int)$item['id'] : null,
            'title' => isset($item['name']) ? $item['name'] : '',
            'maker' => isset($item['maker']) ? $item['maker'] : '',
            'isbn' => isset($item['jan']) ? $item['jan'] : '',
            'price' => isset($item['sale_price']) ? (int)$item['sale_price'] : null,
            'image_url' => absolute_url(!empty($item['image_url']) ? $item['image_url'] : '/images/noimage.jpg'),
            'affiliate_url' => rakuten_click_url($item),
            'product_url' => 'https://aixec.exbridge.jp/product/' . rawurlencode($slug !== '' ? $slug : (isset($item['id']) ? $item['id'] : '')),
        );
        if (count($items) >= $limit) break;
    }

    if (count($items) < $limit) {
        $existing = array();
        foreach ($items as $item) {
            if (!empty($item['isbn'])) $existing[preg_replace('/\D/', '', $item['isbn'])] = true;
        }
        $fallback_items = fallback_books_ranking($limit - count($items), count($items));
        foreach ($fallback_items as $item) {
            $isbn_key = !empty($item['isbn']) ? preg_replace('/\D/', '', $item['isbn']) : '';
            if ($isbn_key !== '' && isset($existing[$isbn_key])) continue;
            if ($isbn_key !== '') $existing[$isbn_key] = true;
            $items[] = $item;
            if (count($items) >= $limit) break;
        }
    }
}

echo json_encode(array(
    'ok' => true,
    'source' => 'aixec_books_ranking',
    'tab' => $active_tab !== '' && isset($tabs[$active_tab]) ? $active_tab : null,
    'generated_at' => date('c'),
    'count' => count($items),
    'items' => $items,
), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
