<?php
header('Content-Type: application/xml; charset=UTF-8');

$BASE_HOST = 'https://aixec.exbridge.jp';
$VIDEO_DIR = __DIR__ . '/video';
$max = isset($_GET['limit']) ? (int)$_GET['limit'] : 5000;
if ($max < 1) $max = 5000;
if ($max > 5000) $max = 5000;

function x($value) {
    return htmlspecialchars((string)$value, ENT_XML1 | ENT_QUOTES, 'UTF-8');
}

function api_get($path, $params = array()) {
    $params = array_merge(array('path' => ltrim($path, '/')), $params);
    $url = 'https://aixec.exbridge.jp/api.php?' . http_build_query($params);
    $ch = curl_init($url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 20);
    $body = curl_exec($ch);
    curl_close($ch);
    if ($body === false || $body === '') return array();
    $json = json_decode($body, true);
    return is_array($json) ? $json : array();
}

function absolute_site_url($url) {
    global $BASE_HOST;
    $url = (string)$url;
    if ($url === '') return '';
    if (preg_match('/^https?:\/\//i', $url)) return $url;
    if ($url[0] === '/') return $BASE_HOST . $url;
    return $BASE_HOST . '/' . $url;
}

function clean_text($html, $limit = 900) {
    $text = html_entity_decode(strip_tags((string)$html), ENT_QUOTES | ENT_HTML5, 'UTF-8');
    $text = preg_replace('/\s+/u', ' ', $text);
    $text = trim($text);
    if (mb_strlen($text, 'UTF-8') > $limit) {
        $text = mb_substr($text, 0, $limit, 'UTF-8') . '...';
    }
    return $text;
}

$files = glob($VIDEO_DIR . '/*.mp4') ?: array();
usort($files, function($a, $b) {
    return filemtime($b) - filemtime($a);
});
$files = array_slice($files, 0, $max);

$ids = array();
$file_by_id = array();
foreach ($files as $file) {
    $key = basename($file, '.mp4');
    if (!preg_match('/^\d+$/', $key)) continue;
    $ids[] = $key;
    $file_by_id[$key] = $file;
}

$products = array();
foreach (array_chunk($ids, 180) as $chunk) {
    $res = api_get('products', array('ids' => implode(',', $chunk), 'limit' => count($chunk)));
    if (!empty($res['ok']) && !empty($res['items']) && is_array($res['items'])) {
        foreach ($res['items'] as $item) {
            if (!empty($item['id'])) $products[(string)$item['id']] = $item;
        }
    }
}

echo '<?xml version="1.0" encoding="UTF-8"?>' . "\n";
echo '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:video="http://www.google.com/schemas/sitemap-video/1.1">' . "\n";
foreach ($ids as $id) {
    if (empty($products[$id]) || empty($file_by_id[$id])) continue;
    $item = $products[$id];
    $title = !empty($item['name']) ? $item['name'] : ('AIxEC 書籍紹介動画 ' . $id);
    $desc_source = !empty($item['book_description_ai']) ? $item['book_description_ai'] : (isset($item['description']) ? $item['description'] : '');
    $desc = clean_text($desc_source);
    if ($desc === '') $desc = $title . ' の書籍紹介ショート動画です。';
    $thumb = !empty($item['image_url']) ? absolute_site_url($item['image_url']) : $BASE_HOST . '/images/noimage.jpg';
    $loc = $BASE_HOST . '/aixtube.php?v=' . rawurlencode($id);
    $content = $BASE_HOST . '/video/' . rawurlencode(basename($file_by_id[$id]));
    echo "  <url>\n";
    echo '    <loc>' . x($loc) . "</loc>\n";
    echo "    <video:video>\n";
    echo '      <video:thumbnail_loc>' . x($thumb) . "</video:thumbnail_loc>\n";
    echo '      <video:title>' . x($title) . "</video:title>\n";
    echo '      <video:description>' . x($desc) . "</video:description>\n";
    echo '      <video:content_loc>' . x($content) . "</video:content_loc>\n";
    echo '      <video:publication_date>' . x(date('c', filemtime($file_by_id[$id]))) . "</video:publication_date>\n";
    echo "    </video:video>\n";
    echo "  </url>\n";
}
echo "</urlset>\n";
