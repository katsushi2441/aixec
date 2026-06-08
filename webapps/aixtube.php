<?php
$BASE_HOST = 'https://aixec.exbridge.jp';
$VIDEO_DIR = __DIR__ . '/video';
$VIDEO_WEB = '/video';

function h($value) {
    return htmlspecialchars((string)$value, ENT_QUOTES, 'UTF-8');
}

function api_get($path, $params = array()) {
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

function absolute_site_url($url) {
    global $BASE_HOST;
    $url = (string)$url;
    if ($url === '') return '';
    if (preg_match('/^https?:\/\//i', $url)) return $url;
    if ($url[0] === '/') return $BASE_HOST . $url;
    return $BASE_HOST . '/' . $url;
}

function make_slug($maker, $model, $name = '') {
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

function clean_text($html, $limit = 320) {
    $text = html_entity_decode(strip_tags((string)$html), ENT_QUOTES | ENT_HTML5, 'UTF-8');
    $text = preg_replace('/\s+/u', ' ', $text);
    $text = trim($text);
    if (mb_strlen($text, 'UTF-8') > $limit) {
        $text = mb_substr($text, 0, $limit, 'UTF-8') . '...';
    }
    return $text;
}

function is_safe_video_key($key) {
    return $key !== '' && !preg_match('#[\\\\/\x00-\x1F\x7F]#u', $key);
}

function video_file_for_key($key) {
    global $VIDEO_DIR;
    if (!is_safe_video_key($key)) return '';
    $name = preg_match('/\.mp4$/i', $key) ? $key : $key . '.mp4';
    $path = $VIDEO_DIR . '/' . $name;
    return is_file($path) ? $path : '';
}

function video_key_from_request() {
    if (isset($_GET['id']) && trim($_GET['id']) !== '') return trim($_GET['id']);
    if (isset($_GET['v']) && trim($_GET['v']) !== '') return trim($_GET['v']);
    return '';
}

function product_from_video_key($key) {
    $base = preg_replace('/\.mp4$/i', '', $key);
    if (preg_match('/^\d+$/', $base)) {
        $res = api_get('products/' . $base);
        return !empty($res['ok']) && !empty($res['item']) ? $res['item'] : array();
    }
    if (preg_match('/(97[89][0-9]{10})/', $base, $m)) {
        $res = api_get('products', array('q' => $m[1], 'limit' => 1));
        return !empty($res['ok']) && !empty($res['items'][0]) ? $res['items'][0] : array();
    }
    return array();
}

function isbn_from_product($product) {
    foreach (array('jan', 'gtin', 'model_number') as $field) {
        if (!empty($product[$field]) && preg_match('/(97[89][0-9]{10})/', preg_replace('/\D/', '', $product[$field]), $m)) {
            return $m[1];
        }
    }
    return '';
}

function rakuten_click_url($product) {
    $title = !empty($product['name']) ? $product['name'] : '商品';
    $params = array(
        'to' => 'rakuten',
        'kw' => $title,
        'from' => !empty($product['id']) ? ('aixtube:' . (int)$product['id']) : 'aixtube',
    );
    if (!empty($product['id'])) $params['pid'] = (int)$product['id'];
    if (!empty($product['model_number'])) $params['model'] = $product['model_number'];
    $isbn = isbn_from_product($product);
    if ($isbn !== '') $params['jan'] = $isbn;
    if (!empty($product['rakuten_url'])) $params['url'] = $product['rakuten_url'];
    return '/go.php?' . http_build_query($params);
}

function amazon_click_url($product) {
    $title = !empty($product['name']) ? $product['name'] : '商品';
    $params = array(
        'to' => 'amazon',
        'kw' => $title,
        'from' => !empty($product['id']) ? ('aixtube:' . (int)$product['id']) : 'aixtube',
    );
    if (!empty($product['id'])) $params['pid'] = (int)$product['id'];
    if (!empty($product['model_number'])) $params['model'] = $product['model_number'];
    if (!empty($product['asin'])) $params['asin'] = strtoupper(trim((string)$product['asin']));
    return '/go.php?' . http_build_query($params);
}

function video_key_for_product($product, $available_keys = null) {
    global $VIDEO_DIR;
    if (empty($product['id'])) return '';
    $id_key = (string)(int)$product['id'];
    if ($available_keys === null) {
        if (is_file($VIDEO_DIR . '/' . $id_key . '.mp4')) return $id_key;
    } elseif (isset($available_keys[$id_key])) {
        return $id_key;
    }
    $isbn = isbn_from_product($product);
    if ($isbn === '') return '';
    $files = glob($VIDEO_DIR . '/*' . $isbn . '*.mp4') ?: array();
    if (!$files) return '';
    usort($files, function($a, $b) { return filemtime($b) - filemtime($a); });
    return basename($files[0], '.mp4');
}

function list_video_keys($limit = 24) {
    global $VIDEO_DIR;
    $files = glob($VIDEO_DIR . '/*.mp4') ?: array();
    usort($files, function($a, $b) {
        return filemtime($b) - filemtime($a);
    });
    $out = array();
    foreach (array_slice($files, 0, $limit) as $file) {
        $out[] = basename($file, '.mp4');
    }
    return $out;
}

function searchable_video_key_map() {
    global $VIDEO_DIR;
    $files = glob($VIDEO_DIR . '/*.mp4') ?: array();
    $map = array();
    foreach ($files as $file) {
        $key = basename($file, '.mp4');
        $map[$key] = true;
    }
    return $map;
}

function book_genre_map() {
    static $map = null;
    if ($map !== null) return $map;
    $file = __DIR__ . '/data/book_genres.json';
    if (!is_readable($file)) {
        $map = array();
        return $map;
    }
    $json = json_decode(file_get_contents($file), true);
    $map = is_array($json) ? $json : array();
    return $map;
}

function book_genre_info($product_id) {
    $map = book_genre_map();
    $key = (string)(int)$product_id;
    $info = isset($map[$key]) && is_array($map[$key]) ? $map[$key] : array();
    return array(
        'keywords' => !empty($info['keywords']) && is_array($info['keywords']) ? $info['keywords'] : array(),
        'groups' => !empty($info['groups']) && is_array($info['groups']) ? $info['groups'] : array(),
    );
}

function has_overlap($a, $b) {
    if (!$a || !$b) return false;
    return (bool)array_intersect($a, $b);
}

function maker_reels_url($maker, $fallback_id = 0) {
    global $VIDEO_DIR;
    $maker = trim((string)$maker);
    if ($maker === '') {
        return $fallback_id ? '/reels.php?ids=' . (int)$fallback_id : '/reels.php';
    }
    $res = api_get('products', array('maker' => $maker, 'limit' => 120));
    $rows = array();
    if (!empty($res['ok']) && !empty($res['items']) && is_array($res['items'])) {
        foreach ($res['items'] as $item) {
            if (empty($item['id'])) continue;
            $id = (int)$item['id'];
            $path = $VIDEO_DIR . '/' . $id . '.mp4';
            if (!is_file($path)) continue;
            $rows[] = array('id' => $id, 'mtime' => filemtime($path));
        }
    }
    usort($rows, function($a, $b) {
        return $b['mtime'] - $a['mtime'];
    });
    $ids = array();
    foreach ($rows as $row) {
        $ids[] = $row['id'];
        if (count($ids) >= 10) break;
    }
    if (!$ids && $fallback_id) $ids[] = (int)$fallback_id;
    return $ids ? '/reels.php?ids=' . implode(',', $ids) : '/reels.php';
}

function related_video_keys_for_product($product_id, $maker, $current_key, $limit = 12) {
    global $VIDEO_DIR;
    $current_id = (int)$product_id;
    $current_info = $current_id ? book_genre_info($current_id) : array('keywords' => array(), 'groups' => array());
    $files = glob($VIDEO_DIR . '/*.mp4') ?: array();
    usort($files, function($a, $b) {
        return filemtime($b) - filemtime($a);
    });
    $exact = array();
    $group = array();
    $fresh = array();
    $seen = array((string)$current_key => true);
    foreach ($files as $file) {
        $key = basename($file, '.mp4');
        if (isset($seen[$key])) continue;
        $fresh[] = $key;
        if (!preg_match('/^\d+$/', $key)) continue;
        $info = book_genre_info((int)$key);
        if (has_overlap($current_info['keywords'], $info['keywords'])) {
            $exact[] = $key;
        } elseif (has_overlap($current_info['groups'], $info['groups'])) {
            $group[] = $key;
        }
    }
    $maker_keys = array();
    $maker = trim((string)$maker);
    if ($maker !== '') {
        $res = api_get('products', array('maker' => $maker, 'limit' => 120));
        $rows = array();
        if (!empty($res['ok']) && !empty($res['items']) && is_array($res['items'])) {
            foreach ($res['items'] as $item) {
                if (empty($item['id']) || (int)$item['id'] === $current_id) continue;
                $id = (int)$item['id'];
                $path = $VIDEO_DIR . '/' . $id . '.mp4';
                if (is_file($path)) $rows[] = array('key' => (string)$id, 'mtime' => filemtime($path));
            }
        }
        usort($rows, function($a, $b) { return $b['mtime'] - $a['mtime']; });
        foreach ($rows as $row) $maker_keys[] = $row['key'];
    }
    $out = array();
    foreach (array($exact, $group, $maker_keys, $fresh) as $bucket) {
        foreach ($bucket as $key) {
            if (isset($seen[$key])) continue;
            $seen[$key] = true;
            $out[] = $key;
            if (count($out) >= $limit) return $out;
        }
    }
    return $out;
}

$requested_key = video_key_from_request();
$search_query = isset($_GET['q']) ? trim($_GET['q']) : '';
$video_path = $requested_key !== '' ? video_file_for_key($requested_key) : '';

if ($requested_key !== '' && $video_path === '') {
    http_response_code(404);
}

$product = $video_path ? product_from_video_key($requested_key) : array();
$product_id = isset($product['id']) ? (int)$product['id'] : (preg_match('/^\d+$/', $requested_key) ? (int)$requested_key : 0);
$title = !empty($product['name']) ? $product['name'] : ($requested_key !== '' ? basename($requested_key, '.mp4') : 'AIxEC 商品紹介動画');
$maker = isset($product['maker']) ? $product['maker'] : '';
$isbn = isbn_from_product($product);
$jan = !empty($product['jan']) ? preg_replace('/\D/', '', $product['jan']) : ($isbn !== '' ? $isbn : '');
$description_html = !empty($product['book_description_ai']) ? $product['book_description_ai'] : (isset($product['description']) ? $product['description'] : '');
$description = clean_text($description_html, 420);
if ($description === '') {
    $parts = array($title);
    if ($maker !== '') $parts[] = $maker;
    if ($jan !== '') $parts[] = 'JAN: ' . $jan;
    $description = implode(' / ', $parts) . ' の商品紹介ショート動画です。';
}
$image_url = !empty($product['image_url']) ? absolute_site_url($product['image_url']) : $BASE_HOST . '/images/noimage.jpg';
$share_image_url = $BASE_HOST . '/images/aixtube.png';
$og_image_url = ($video_path && $image_url !== $BASE_HOST . '/images/noimage.jpg') ? $image_url : $share_image_url;
$video_key = preg_replace('/\.mp4$/i', '', $requested_key);
$video_url = $video_path ? $BASE_HOST . $VIDEO_WEB . '/' . rawurlencode(basename($video_path)) : '';
$page_url = $requested_key !== '' ? $BASE_HOST . '/aixtube.php?v=' . rawurlencode($video_key) : $BASE_HOST . '/aixtube.php';
$reels_url = maker_reels_url($maker, $product_id);
$product_slug = ($maker !== '' || !empty($product['model_number'])) ? make_slug($maker, isset($product['model_number']) ? $product['model_number'] : '', $title) : (string)$product_id;
$product_url = $product_slug !== '' ? '/product/' . rawurlencode($product_slug) : '/';
$rakuten_url = !empty($product) ? rakuten_click_url($product) : '';
$amazon_url = !empty($product) ? amazon_click_url($product) : '';
$top_affiliate_keyword = $search_query !== '' ? $search_query : '商品';
$top_rakuten_url = '/go.php?' . http_build_query(array('to' => 'rakuten', 'kw' => $top_affiliate_keyword, 'from' => 'aixtube'));
$top_amazon_url = '/go.php?' . http_build_query(array('to' => 'amazon', 'kw' => $top_affiliate_keyword, 'from' => 'aixtube'));
$upload_date = $video_path ? date('c', filemtime($video_path)) : date('c');
$page_title = $video_path ? '『' . $title . '』紹介動画 | AIxTube' : 'AIxTube | AIxEC 商品紹介動画';
$video_keys = !$video_path ? list_video_keys(36) : array();
$search_results = array();
$search_reels_ids = array();
if (!$video_path && $search_query !== '') {
    $available_keys = searchable_video_key_map();
    $res = api_get('products', array('q' => $search_query, 'limit' => 80));
    if (!empty($res['ok']) && !empty($res['items']) && is_array($res['items'])) {
        $seen = array();
        foreach ($res['items'] as $item) {
            $key = video_key_for_product($item, $available_keys);
            if ($key === '' || isset($seen[$key])) continue;
            $seen[$key] = true;
            $search_results[] = array('key' => $key, 'product' => $item);
            if (count($search_results) >= 36) break;
        }
    }
    usort($search_results, function($a, $b) {
        $af = video_file_for_key($a['key']);
        $bf = video_file_for_key($b['key']);
        return ($bf ? filemtime($bf) : 0) - ($af ? filemtime($af) : 0);
    });
    foreach ($search_results as $result) {
        if (count($search_reels_ids) >= 10) break;
        $pid = !empty($result['product']['id']) ? (int)$result['product']['id'] : 0;
        if ($pid && is_file($VIDEO_DIR . '/' . $pid . '.mp4')) {
            $search_reels_ids[] = $pid;
        }
    }
    $video_keys = array();
}
$related_keys = $video_path ? related_video_keys_for_product($product_id, $maker, $video_key, 12) : array();
$schema = null;
if ($video_path) {
    $schema = array(
        '@context' => 'https://schema.org',
        '@type' => 'VideoObject',
        'name' => $title,
        'description' => $description,
        'thumbnailUrl' => array($image_url),
        'uploadDate' => $upload_date,
        'contentUrl' => $video_url,
        'embedUrl' => $page_url,
        'publisher' => array('@type' => 'Organization', 'name' => 'AIxEC', 'url' => $BASE_HOST),
    );
}
?><!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?php echo h($page_title); ?></title>
<meta name="description" content="<?php echo h($description); ?>">
<link rel="canonical" href="<?php echo h($page_url); ?>">
<meta property="og:type" content="<?php echo $video_path ? 'video.other' : 'website'; ?>">
<meta property="og:title" content="<?php echo h($page_title); ?>">
<meta property="og:description" content="<?php echo h($description); ?>">
<meta property="og:url" content="<?php echo h($page_url); ?>">
<meta property="og:image" content="<?php echo h($og_image_url); ?>">
<?php if ($video_path): ?><meta property="og:video" content="<?php echo h($video_url); ?>">
<meta property="og:video:type" content="video/mp4">
<meta property="og:video:width" content="720">
<meta property="og:video:height" content="1280">
<?php endif; ?>
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="<?php echo h($page_title); ?>">
<meta name="twitter:description" content="<?php echo h($description); ?>">
<meta name="twitter:image" content="<?php echo h($og_image_url); ?>">
<?php if ($schema): ?><script type="application/ld+json"><?php echo json_encode($schema, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES); ?></script><?php endif; ?>
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
<style>
*{box-sizing:border-box}body{margin:0;background:#f7f8f4;color:#20231d;font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Yu Gothic",Meiryo,sans-serif}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 18px;border-bottom:1px solid #dfe5d5;background:#fff;position:sticky;top:0;z-index:10}.brand{display:flex;align-items:center;gap:10px;color:#20231d;text-decoration:none;font-weight:800;flex-shrink:0}.mark{width:36px;height:36px;border-radius:4px;background:#72bf44;color:#fff;display:flex;align-items:center;justify-content:center}.nav{display:flex;gap:10px;flex-wrap:wrap;justify-content:flex-end}.nav a{font-size:13px;color:#385b2d;text-decoration:none;border:1px solid #b8d9a5;background:#f3fbec;border-radius:4px;padding:7px 10px;white-space:nowrap;flex-shrink:0}.nav a.nav-rakuten{background:#bf0000;border-color:#bf0000;color:#fff}.nav a.nav-amazon{background:#f59b23;border-color:#f59b23;color:#241000}.wrap{max-width:1080px;margin:0 auto;padding:24px 16px 42px}.search{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;margin:0 0 20px}.search input{min-height:42px;border:1px solid #cfd8c8;border-radius:4px;padding:8px 12px;font-size:16px}.search button{min-height:42px;border:0;border-radius:4px;background:#385b2d;color:#fff;font-weight:700;padding:8px 18px;cursor:pointer}.player-grid{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:22px;align-items:start}.player{background:#050505;border-radius:6px;overflow:hidden}.player video{width:100%;display:block;aspect-ratio:9/16;max-height:78vh;object-fit:contain;background:#000}.meta{background:#fff;border:1px solid #dfe5d5;border-radius:6px;padding:18px}.meta h1{font-size:24px;line-height:1.45;margin:0 0 12px}.cover-link{display:block}.cover{width:100%;max-height:360px;object-fit:contain;background:#fff;border:1px solid #e4e4e4;border-radius:4px;margin-bottom:14px}.facts{display:grid;gap:8px;margin:14px 0}.fact{font-size:13px;color:#596050}.fact b{display:block;color:#20231d;font-size:12px}.desc{line-height:1.85;font-size:14px}.affiliate-box{margin:16px 0;padding:14px;border:2px solid #f59b23;border-radius:6px;background:#fff8e8}.affiliate-box strong{display:block;margin-bottom:4px;color:#5f3400;font-size:14px}.affiliate-box span{display:block;margin-bottom:12px;color:#66533a;font-size:12px;line-height:1.5}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.affiliate-actions{margin-top:0}.btn{display:inline-flex;align-items:center;justify-content:center;min-height:38px;padding:8px 13px;border-radius:4px;background:#72bf44;color:#fff;text-decoration:none;font-weight:700;border:0;cursor:pointer}.btn.amazon{background:#f59b23;color:#241000;box-shadow:0 2px 0 rgba(95,52,0,.18)}.btn.buy{background:#bf0000}.btn.sub{background:#fff;color:#385b2d;border:1px solid #b8d9a5}.section-title{font-size:18px;margin:28px 0 12px}.video-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}.tile{display:flex;flex-direction:column;background:#fff;border:1px solid #dfe5d5;border-radius:6px;padding:10px;color:#20231d;text-decoration:none}.tile img{width:100%;aspect-ratio:3/4;object-fit:contain;background:#fafafa;border-radius:4px}.tile span{display:block;margin-top:8px;font-size:13px;font-weight:700;line-height:1.45}.tile small{display:block;margin-top:4px;color:#66705f;font-size:12px;line-height:1.45}.empty{background:#fff;border:1px solid #dfe5d5;border-radius:6px;padding:24px;line-height:1.8}@media(max-width:820px){.player-grid{grid-template-columns:1fr}.meta{padding:14px}.meta h1{font-size:20px}.top{align-items:flex-start;flex-direction:column}.nav{justify-content:flex-start;flex-wrap:nowrap;width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}.nav::-webkit-scrollbar{display:none}.player video{max-height:none}.search{grid-template-columns:1fr}.search button{width:100%}.affiliate-actions .btn{width:100%}}
</style>
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-2528616930208188"
     crossorigin="anonymous"></script>
</head>
<body>
<header class="top">
  <a class="brand" href="/aixtube.php"><span class="mark">AIx</span><span>AIxTube</span></a>
  <nav class="nav">
    <a class="nav-amazon" href="<?php echo h($video_path && $amazon_url !== '' ? $amazon_url : $top_amazon_url); ?>" target="_blank" rel="nofollow sponsored noopener">Amazon</a>
    <a class="nav-rakuten" href="<?php echo h($video_path && $rakuten_url !== '' ? $rakuten_url : $top_rakuten_url); ?>" target="_blank" rel="nofollow sponsored noopener">楽天市場</a>
    <a href="/aixtubeg.php">AIxTubeG</a><a href="<?php echo h($video_path ? $reels_url : '/reels.php'); ?>">リールで見る</a><a href="/market_ranking.php">人気商品</a><a href="/books_ranking.php">人気書籍</a><a href="/">商品検索</a>
  </nav>
</header>
<main class="wrap">
<?php include __DIR__ . '/vwork_promo.php'; ?>
<?php if ($requested_key !== '' && !$video_path): ?>
  <div class="empty">動画ファイルが見つかりませんでした。<br><a href="/aixtube.php">AIxTube一覧へ戻る</a></div>
<?php elseif ($video_path): ?>
  <div class="player-grid">
    <section class="player">
      <video controls playsinline preload="metadata" poster="<?php echo h($image_url); ?>">
        <source src="<?php echo h($VIDEO_WEB . '/' . rawurlencode(basename($video_path))); ?>" type="video/mp4">
      </video>
    </section>
    <aside class="meta">
      <?php if ($amazon_url !== ''): ?><a class="cover-link" href="<?php echo h($amazon_url); ?>" target="_blank" rel="nofollow sponsored noopener"><?php elseif ($rakuten_url !== ''): ?><a class="cover-link" href="<?php echo h($rakuten_url); ?>" target="_blank" rel="nofollow sponsored noopener"><?php endif; ?>
      <img class="cover" src="<?php echo h($image_url); ?>" alt="<?php echo h($title); ?>">
      <?php if ($amazon_url !== '' || $rakuten_url !== ''): ?></a><?php endif; ?>
      <h1><?php echo h($title); ?></h1>
      <div class="facts">
        <?php if ($maker !== ''): ?><div class="fact"><b>メーカー</b><?php echo h($maker); ?></div><?php endif; ?>
        <?php if ($jan !== ''): ?><div class="fact"><b><?php echo $isbn !== '' ? 'ISBN' : 'JAN'; ?></b><?php echo h($jan); ?></div><?php endif; ?>
        <div class="fact"><b>動画公開日</b><?php echo h(date('Y-m-d', strtotime($upload_date))); ?></div>
      </div>
      <p class="desc"><?php echo h($description); ?></p>
      <?php if ($amazon_url !== '' || $rakuten_url !== ''): ?>
      <div class="affiliate-box">
        <strong>価格・在庫を確認</strong>
        <span>Amazonを優先表示しています。楽天市場の商品ページもあわせて確認できます。</span>
        <div class="actions affiliate-actions">
          <?php if ($amazon_url !== ''): ?><a class="btn amazon" href="<?php echo h($amazon_url); ?>" target="_blank" rel="nofollow sponsored noopener">Amazonで探す</a><?php endif; ?>
          <?php if ($rakuten_url !== ''): ?><a class="btn buy" href="<?php echo h($rakuten_url); ?>" target="_blank" rel="nofollow sponsored noopener">楽天市場でも見る</a><?php endif; ?>
        </div>
      </div>
      <?php endif; ?>
      <div class="actions">
        <a class="btn" href="<?php echo h($reels_url); ?>">リールで見る</a>
        <a class="btn sub" href="<?php echo h($product_url); ?>">商品ページ</a>
        <button class="btn sub" type="button" id="copyBtn">URLコピー</button>
      </div>
    </aside>
  </div>
  <?php if ($related_keys): ?>
  <h2 class="section-title">ほかの紹介動画</h2>
  <div class="video-list">
    <?php foreach ($related_keys as $key): $rp = product_from_video_key($key); $rt = !empty($rp['name']) ? $rp['name'] : $key; $ri = !empty($rp['image_url']) ? absolute_site_url($rp['image_url']) : $BASE_HOST . '/images/noimage.jpg'; ?>
    <a class="tile" href="/aixtube.php?v=<?php echo rawurlencode($key); ?>"><img src="<?php echo h($ri); ?>" alt=""><span><?php echo h($rt); ?></span></a>
    <?php endforeach; ?>
  </div>
  <?php endif; ?>
<?php else: ?>
  <h1 class="section-title">AIxEC 商品紹介動画</h1>
  <form class="search" action="/aixtube.php" method="get">
    <input type="search" name="q" value="<?php echo h($search_query); ?>" placeholder="商品名・メーカー・型番・JANで動画検索">
    <button type="submit">検索</button>
  </form>
  <?php if ($search_query !== ''): ?>
  <h2 class="section-title">「<?php echo h($search_query); ?>」の検索結果</h2>
  <?php if (!$search_results): ?>
  <div class="empty">該当する動画が見つかりませんでした。</div>
  <?php else: ?>
  <?php if ($search_reels_ids): ?>
  <div class="actions" style="margin:0 0 16px;">
    <a class="btn" href="/reels.php?ids=<?php echo h(implode(',', $search_reels_ids)); ?>">検索結果をリールで見る</a>
  </div>
  <?php endif; ?>
  <div class="video-list">
    <?php foreach ($search_results as $result): $key = $result['key']; $p = $result['product']; $t = !empty($p['name']) ? $p['name'] : $key; $img = !empty($p['image_url']) ? absolute_site_url($p['image_url']) : $BASE_HOST . '/images/noimage.jpg'; $m = !empty($p['maker']) ? $p['maker'] : ''; ?>
    <a class="tile" href="/aixtube.php?v=<?php echo rawurlencode($key); ?>"><img src="<?php echo h($img); ?>" alt=""><span><?php echo h($t); ?></span><?php if ($m !== ''): ?><small><?php echo h($m); ?></small><?php endif; ?></a>
    <?php endforeach; ?>
  </div>
  <?php endif; ?>
  <?php elseif (!$video_keys): ?>
  <div class="empty">動画がありません。</div>
  <?php else: ?>
  <div class="video-list">
    <?php foreach ($video_keys as $key): $p = product_from_video_key($key); $t = !empty($p['name']) ? $p['name'] : $key; $img = !empty($p['image_url']) ? absolute_site_url($p['image_url']) : $BASE_HOST . '/images/noimage.jpg'; $m = !empty($p['maker']) ? $p['maker'] : ''; ?>
    <a class="tile" href="/aixtube.php?v=<?php echo rawurlencode($key); ?>"><img src="<?php echo h($img); ?>" alt=""><span><?php echo h($t); ?></span><?php if ($m !== ''): ?><small><?php echo h($m); ?></small><?php endif; ?></a>
    <?php endforeach; ?>
  </div>
  <?php endif; ?>
<?php endif; ?>
</main>
<script>
var copyBtn = document.getElementById('copyBtn');
if (copyBtn) {
  copyBtn.addEventListener('click', function() {
    navigator.clipboard.writeText(location.href).then(function() {
      copyBtn.textContent = 'コピー済み';
      setTimeout(function(){ copyBtn.textContent = 'URLコピー'; }, 1800);
    });
  });
}
</script>
</body>
</html>
