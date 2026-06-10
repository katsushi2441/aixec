<?php
function text_value($value) {
    if (is_array($value)) {
        foreach ($value as $part) {
            $text = text_value($part);
            if ($text !== '') return $text;
        }
        return '';
    }
    if ($value === null) return '';
    return trim((string)$value);
}

function h($value) {
    return htmlspecialchars(text_value($value), ENT_QUOTES, 'UTF-8');
}

function yen($value) {
    $value = text_value($value);
    if ($value === null || $value === '') return '';
    return '¥' . number_format((int)$value);
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

function log_query_params($line) {
    $parts = explode(' | ', $line);
    if (count($parts) < 3) return array();
    $url = trim($parts[2]);
    $query = parse_url($url, PHP_URL_QUERY);
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
    if (count($lines) > 10000) $lines = array_slice($lines, -10000);
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
        if (!isset($counts[$key])) {
            $counts[$key] = array('key' => $key, 'count' => 0);
        }
        $counts[$key]['count']++;
    }
    usort($counts, function($a, $b) {
        if ($a['count'] == $b['count']) return 0;
        return ($a['count'] > $b['count']) ? -1 : 1;
    });
    return array_slice($counts, 0, $limit * 2);
}

function resolve_product($key) {
    if (strpos($key, 'id:') === 0) {
        $id = substr($key, 3);
        $res = api_get('products/' . $id);
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
    if (!empty($item['image_url']) && strpos($item['image_url'], 'rakuten.co.jp') !== false && strpos($item['image_url'], '/book/') !== false) return true;
    $mn = preg_replace('/\D/', '', (string)($item['model_number'] ?? ''));
    if (strlen($mn) === 13 && (substr($mn, 0, 3) === '978' || substr($mn, 0, 3) === '979')) return true;
    $jan = preg_replace('/\D/', '', (string)($item['jan'] ?? ''));
    if (strlen($jan) === 13 && (substr($jan, 0, 3) === '978' || substr($jan, 0, 3) === '979')) return true;
    return false;
}

function rakuten_click_url($item) {
    $params = array(
        'to' => 'rakuten',
        'kw' => isset($item['name']) ? $item['name'] : '本',
        'from' => 'books_ranking:' . (isset($_GET['tab']) ? $_GET['tab'] : ''),
    );
    if (!empty($item['id'])) $params['pid'] = $item['id'];
    if (!empty($item['model_number'])) $params['model'] = $item['model_number'];
    if (!empty($item['jan'])) $params['jan'] = preg_replace('/\D/', '', $item['jan']);
    return '/go.php?' . http_build_query($params);
}

function amazon_click_url($item) {
    $keyword = isset($item['name']) ? $item['name'] : '';
    if ($keyword === '' && isset($item['title'])) $keyword = $item['title'];
    if ($keyword === '') $keyword = '本';
    $params = array(
        'to' => 'amazon',
        'kw' => $keyword,
        'from' => 'books_ranking:' . (isset($_GET['tab']) ? $_GET['tab'] : ''),
    );
    if (!empty($item['id'])) $params['pid'] = $item['id'];
    if (!empty($item['model_number'])) $params['model'] = $item['model_number'];
    if (!empty($item['jan'])) $params['jan'] = preg_replace('/\D/', '', $item['jan']);
    if (!empty($item['isbn'])) $params['jan'] = preg_replace('/\D/', '', $item['isbn']);
    return '/go.php?' . http_build_query($params);
}

// ── タブ定義 ──────────────────────────────────────────────────────────────
$tabs = array(
    'startup'     => array('label' => '起業・開業',        'type' => 'rakuten', 'params' => array('genre_id' => '001006018003', 'hits' => 20)),
    'management'  => array('label' => '経営・マネジメント','type' => 'rakuten', 'params' => array('genre_id' => '001006018', 'hits' => 20)),
    'health'      => array('label' => '健康・医療',        'type' => 'rakuten', 'params' => array('genre_id' => '001010010', 'hits' => 20)),
    'ai'          => array('label' => 'AI・テクノロジー',  'type' => 'rakuten', 'params' => array('genre_id' => '001005', 'keyword' => 'AI', 'hits' => 20)),
    'web3'        => array('label' => 'Web3・暗号資産',    'type' => 'rakuten', 'params' => array('keyword' => 'ブロックチェーン', 'hits' => 20)),
    'programming' => array('label' => 'プログラミング・IT','type' => 'rakuten', 'params' => array('genre_id' => '001005005', 'hits' => 20)),
    'click'       => array('label' => 'クリック人気順',    'type' => 'click'),
);

$active = (isset($_GET['tab']) && array_key_exists($_GET['tab'], $tabs)) ? $_GET['tab'] : 'health';

// ── データ取得（アクティブタブのみ）──────────────────────────────────────
$click_ranking = array();
$rakuten_books = array();

if ($tabs[$active]['type'] === 'click') {
    $limit = isset($_GET['limit']) ? (int)$_GET['limit'] : 10;
    if ($limit < 1) $limit = 10;
    if ($limit > 50) $limit = 50;
    $keys = ranking_keys_from_log($limit);

    // id: キーをバッチ取得（APIコール1回で済む）
    $id_keys = array(); $other_keys = array();
    foreach ($keys as $row) {
        if (strpos($row['key'], 'id:') === 0) $id_keys[]    = $row;
        else                                   $other_keys[] = $row;
    }
    $id_map = array();
    if ($id_keys) {
        $ids_str = implode(',', array_map(function($r){ return substr($r['key'],3); }, $id_keys));
        $batch = api_get('products', array('ids' => $ids_str, 'limit' => count($id_keys)));
        if (!empty($batch['ok']) && !empty($batch['items'])) {
            foreach ($batch['items'] as $it) { $id_map[(int)$it['id']] = $it; }
        }
    }
    $count_map = array();
    foreach ($keys as $row) { $count_map[$row['key']] = $row['count']; }

    foreach ($keys as $row) {
        $key = $row['key'];
        if (strpos($key, 'id:') === 0) {
            $item = isset($id_map[(int)substr($key,3)]) ? $id_map[(int)substr($key,3)] : null;
            if (!$item) $item = resolve_product($key);
        } else {
            $item = resolve_product($key);
        }
        if (!is_book_product($item)) continue;
        $item['_clicks'] = $count_map[$key] ?? $row['count'];
        $click_ranking[] = $item;
        if (count($click_ranking) >= $limit) break;
    }
} else {
    $res = api_get('books/ranking', $tabs[$active]['params']);
    $rakuten_books = (!empty($res['ok']) && !empty($res['result']['items'])) ? $res['result']['items'] : array();
}

$page_title = '人気書籍ランキング | AI駆動型ネット通販 AIxEC';
$page_description = 'AIxECでクリックされた楽天ブックス・Kobo商品の人気順ランキングです。';
?><!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?php echo h($page_title); ?></title>
<meta name="description" content="<?php echo h($page_description); ?>">
<link rel="canonical" href="https://aixec.exbridge.jp/books_ranking.php">
<meta property="og:title" content="<?php echo h($page_title); ?>">
<meta property="og:description" content="<?php echo h($page_description); ?>">
<meta property="og:type" content="website">
<meta property="og:url" content="https://aixec.exbridge.jp/books_ranking.php">
<meta property="og:image" content="https://aixec.exbridge.jp/images/aixec.png">
<meta name="twitter:card" content="summary_large_image">
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
:root{--ink:rgba(0,0,0,.87);--muted:rgba(0,0,0,.54);--line:#e0e0e0;--paper:#fff;--soft:#f5f6f6;--accent:#55c500;--accent-dark:#468c00;--red:#bf0000}
*{box-sizing:border-box}
body{margin:0;font-family:YakuHanJPs,-apple-system,system-ui,"Segoe UI","Hiragino Kaku Gothic ProN","Hiragino Sans",Meiryo,sans-serif;color:var(--ink);background:var(--soft);letter-spacing:0;line-height:1.8;word-break:break-all;overflow-wrap:break-word}
a{color:inherit}
.top{background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
.wrap{max-width:1100px;margin:0 auto;padding:12px 16px}
.bar{display:flex;align-items:center;justify-content:space-between;gap:18px}
.brand{display:flex;align-items:center;gap:12px;min-width:0;text-decoration:none}
.mark{width:36px;height:36px;border-radius:4px;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px}
.brand b{display:block;font-size:22px;line-height:1}.brand span{display:block;color:var(--muted);font-size:12px;margin-top:4px;white-space:nowrap}
.brand-ogp{display:block;width:auto;height:42px;object-fit:contain}
.nav{display:flex;gap:10px;align-items:center}.nav a{font-size:13px;color:var(--muted);text-decoration:none;border:1px solid var(--line);background:#fff;border-radius:4px;padding:6px 10px}.nav a:hover{color:var(--accent-dark);border-color:#cfe8c4}
.nav-books-btn{display:none;font-size:13px;font-weight:600;color:var(--accent-dark);text-decoration:none;border:1px solid var(--accent);background:#eaf7d8;border-radius:4px;padding:6px 10px;white-space:nowrap;flex-shrink:0}
.nav-reels-btn{display:none;font-size:13px;font-weight:600;color:#fff;text-decoration:none;border:1px solid #333;background:#222;border-radius:4px;padding:6px 10px;white-space:nowrap;flex-shrink:0}
.nav-aixtube-btn{display:none;font-size:13px;font-weight:600;color:#fff;text-decoration:none;border:1px solid #385b2d;background:#385b2d;border-radius:4px;padding:6px 10px;white-space:nowrap;flex-shrink:0}
.nav-sns-btn{display:none;font-size:13px;font-weight:600;color:#b45309;text-decoration:none;border:1px solid #f59e0b;background:#fffbeb;border-radius:4px;padding:6px 10px;white-space:nowrap;flex-shrink:0}
.nav-mobile{display:none}
.hero{max-width:1100px;margin:0 auto;padding:24px 16px 0}
.hero h1{font-size:28px;line-height:1.4;margin:0 0 6px;font-weight:700}.lead{color:var(--muted);font-size:14px;margin:0}
/* タブ */
.tabs{max-width:1100px;margin:0 auto;padding:0 16px}
.tab-list{display:flex;gap:0;border-bottom:2px solid var(--line);margin:16px 0 0;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}
.tab-list::-webkit-scrollbar{display:none}
.tab-list a{display:block;white-space:nowrap;padding:10px 18px;font-size:14px;font-weight:600;color:var(--muted);text-decoration:none;border-bottom:3px solid transparent;margin-bottom:-2px;transition:color .15s,border-color .15s}
.tab-list a:hover{color:var(--accent-dark)}
.tab-list a.active{color:var(--accent-dark);border-bottom-color:var(--accent)}
.tab-badge{display:inline-block;background:var(--soft);border:1px solid var(--line);border-radius:10px;font-size:11px;font-weight:400;padding:1px 7px;margin-left:5px;color:var(--muted)}
.tab-list a.active .tab-badge{background:#eaf7d8;border-color:#c4e29a;color:var(--accent-dark)}
/* コンテンツ */
.main{max-width:1100px;margin:0 auto;padding:16px 16px 48px}
.section-head{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;margin:4px 0 12px}
.section-head h2{font-size:20px;line-height:1.4;font-weight:600;margin:0}
.section-head p{margin:0;color:var(--muted);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.card{background:#fff;border:1px solid var(--line);border-radius:4px;overflow:hidden;display:flex;flex-direction:column;min-height:360px}
.card:hover{box-shadow:0 2px 4px rgba(0,0,0,.1);border-color:#c8c8c8}
.rank{height:36px;display:flex;align-items:center;justify-content:space-between;padding:0 12px;border-bottom:1px solid var(--line);font-weight:700;color:var(--accent-dark)}
.rank small{color:var(--muted);font-weight:400}
.cover{display:flex;align-items:center;justify-content:center;height:180px;background:#fff;border-bottom:1px solid var(--line);padding:12px}
.cover img{display:block;max-width:100%;max-height:156px;object-fit:contain}
.body{padding:14px;display:flex;flex-direction:column;flex:1}
.title{font-size:14px;line-height:1.65;font-weight:700;text-decoration:none;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
.title:hover{text-decoration:underline}
.meta{color:var(--muted);font-size:12px;margin-top:10px}
.price{font-size:17px;font-weight:700;margin-top:auto;padding-top:12px;color:var(--red)}
.actions{display:grid;grid-template-columns:1fr;gap:7px;margin-top:10px}
.btn{display:flex;align-items:center;justify-content:center;min-height:34px;padding:6px 9px;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--ink);font-size:13px;font-weight:700;text-align:center;text-decoration:none}
.btn.primary{background:#f59b23;border-color:#f59b23;color:#241000}
.btn.rakuten{background:#bf0000;border-color:#bf0000;color:#fff}
.empty{background:#fff;border:1px solid var(--line);border-radius:4px;padding:34px;text-align:center;color:var(--muted)}
@media(max-width:960px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:700px){.bar{align-items:flex-start;flex-direction:column;gap:8px}.brand{align-self:flex-start}.nav{display:none}.nav-mobile{display:flex;gap:8px;margin-top:8px;overflow-x:auto;width:100%;-webkit-overflow-scrolling:touch;scrollbar-width:none}.nav-mobile::-webkit-scrollbar{display:none}.nav-mobile .nav-books-btn,.nav-mobile .nav-reels-btn,.nav-mobile .nav-aixtube-btn,.nav-mobile .nav-sns-btn{display:block}.hero h1{font-size:22px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.brand span{white-space:normal}.brand-ogp{height:34px}.tab-list a{padding:9px 13px;font-size:13px;white-space:nowrap}.tab-badge{display:none}.grid{gap:6px}.card{min-height:auto;border-radius:2px}.card:hover{box-shadow:none}.cover{height:auto;padding:6px}.body{padding:10px}.price{font-size:14px}.tab-list{gap:4px}}
@media(max-width:460px){.grid{grid-template-columns:1fr}.grid{gap:4px}.card{min-height:auto;border-radius:2px}.cover{height:auto;padding:4px}.cover img{max-height:120px}.body{padding:8px}.price{font-size:13px}}
</style>
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-2528616930208188"
     crossorigin="anonymous"></script>
</head>
<body>
<header class="top"><div class="wrap">
  <div class="bar">
    <a class="brand" href="/"><div class="mark">AIx</div><div><b>AIxEC</b><span>AI x EC product intelligence</span></div><img class="brand-ogp" src="/images/aixec.png" alt="AIxEC"></a>
    <nav class="nav"><a href="/">商品検索</a><a href="/market_ranking.php">人気商品</a><a href="/books_ranking.php">人気書籍</a><a href="/aixtube.php">AIxTube</a><a href="/reels.php?tab=<?php echo h($active); ?>">▶ 商品動画</a><a href="/sns.php">🔔 新着情報</a></nav>
  </div>
  <div class="nav-mobile">
    <a class="nav-books-btn" href="/market_ranking.php">人気商品</a>
    <a class="nav-books-btn" href="/books_ranking.php">人気書籍</a>
    <a class="nav-aixtube-btn" href="/aixtube.php">AIxTube</a>
    <a class="nav-reels-btn" href="/reels.php?tab=<?php echo h($active); ?>">▶ 動画</a>
    <a class="nav-sns-btn" href="/sns.php">🔔 新着情報</a>
  </div>
</div></header>
<?php include __DIR__ . '/vwork_promo.php'; ?>

<section class="hero">
  <h1>人気書籍ランキング</h1>
  <p class="lead">カテゴリ別に楽天ブックスの人気書籍をチェック</p>
</section>

<div class="tabs">
  <nav class="tab-list">
    <?php foreach ($tabs as $key => $tab_def): ?>
    <a href="?tab=<?php echo h($key); ?>" class="<?php echo $active === $key ? 'active' : ''; ?>">
      <?php echo h($tab_def['label']); ?>
    </a>
    <?php endforeach; ?>
  </nav>
</div>

<main class="main">
  <?php if ($tabs[$active]['type'] === 'click'): ?>
  <div class="section-head">
    <h2><?php echo h($tabs[$active]['label']); ?></h2>
    <p><?php echo count($click_ranking); ?>件表示</p>
  </div>
  <?php if (!$click_ranking): ?>
    <div class="empty">まだ書籍のクリック履歴がありません。</div>
  <?php else: ?>
  <div class="grid">
    <?php foreach ($click_ranking as $idx => $item): $url = rakuten_click_url($item); $amazon_url = amazon_click_url($item); ?>
    <article class="card">
      <div class="rank">#<?php echo $idx + 1; ?><small><?php echo (int)$item['_clicks']; ?> clicks</small></div>
      <a class="cover" href="<?php echo h($url); ?>" target="_blank" rel="nofollow sponsored noopener">
        <img src="<?php echo h(!empty($item['image_url']) ? $item['image_url'] : '/images/noimage.jpg'); ?>" alt="<?php echo h($item['name']); ?>">
      </a>
      <div class="body">
        <a class="title" href="<?php echo h($url); ?>" target="_blank" rel="nofollow sponsored noopener"><?php echo h($item['name']); ?></a>
        <div class="meta"><?php echo h($item['maker']); ?><br><?php echo h($item['model_number']); ?></div>
        <div class="price"><?php echo h(yen($item['sale_price'])); ?></div>
        <div class="actions">
          <a class="btn primary" href="<?php echo h($amazon_url); ?>" target="_blank" rel="nofollow sponsored noopener">Amazonで見る</a>
          <a class="btn rakuten" href="<?php echo h($url); ?>" target="_blank" rel="nofollow sponsored noopener">楽天ブックスで見る</a>
        </div>
      </div>
    </article>
    <?php endforeach; ?>
  </div>
  <?php endif; ?>

  <?php else: ?>
  <div class="section-head">
    <h2><?php echo h($tabs[$active]['label']); ?></h2>
    <p>楽天ブックス 売上順（<?php echo count($rakuten_books); ?>件）</p>
  </div>
  <?php if (!$rakuten_books): ?>
    <div class="empty">データを取得できませんでした。</div>
  <?php else: ?>
  <div class="grid">
    <?php foreach ($rakuten_books as $idx => $book):
        $book_title = text_value(isset($book['title']) ? $book['title'] : '');
        $book_author = text_value(isset($book['author']) ? $book['author'] : '');
        $book_publisher = text_value(isset($book['publisher_name']) ? $book['publisher_name'] : '');
        $book_review = text_value(isset($book['review_average']) ? $book['review_average'] : '');
        $book_image = text_value(!empty($book['image_url']) ? $book['image_url'] : '/images/noimage.jpg');
        $book_dest = text_value(!empty($book['affiliate_url']) ? $book['affiliate_url'] : (isset($book['item_url']) ? $book['item_url'] : ''));
        $book_isbn = preg_replace('/\D/', '', text_value(isset($book['isbn']) ? $book['isbn'] : ''));
        $book_url = '/go.php?to=rakuten&from=' . urlencode('books_ranking:' . $active) . '&kw=' . urlencode($book_title) . '&jan=' . urlencode($book_isbn) . '&url=' . urlencode($book_dest);
        $amazon_url = amazon_click_url(array('title' => $book_title, 'isbn' => $book_isbn));
    ?>
    <article class="card">
      <div class="rank">#<?php echo $idx + 1; ?><small><?php echo h($book_review !== '' ? '★'.$book_review : ''); ?></small></div>
      <a class="cover" href="<?php echo h($book_url); ?>" target="_blank" rel="nofollow sponsored noopener">
        <img src="<?php echo h($book_image); ?>" alt="<?php echo h($book_title); ?>" loading="lazy">
      </a>
      <div class="body">
        <a class="title" href="<?php echo h($book_url); ?>" target="_blank" rel="nofollow sponsored noopener"><?php echo h($book_title); ?></a>
        <div class="meta"><?php echo h($book_author); ?><?php if ($book_publisher !== ''): ?><br><?php echo h($book_publisher); ?><?php endif; ?></div>
        <div class="price"><?php echo h(yen($book['item_price'])); ?></div>
        <div class="actions">
          <a class="btn primary" href="<?php echo h($amazon_url); ?>" target="_blank" rel="nofollow sponsored noopener">Amazonで見る</a>
          <a class="btn rakuten" href="<?php echo h($book_url); ?>" target="_blank" rel="nofollow sponsored noopener">楽天ブックスで見る</a>
        </div>
      </div>
    </article>
    <?php endforeach; ?>
  </div>
  <?php endif; ?>
  <?php endif; ?>
</main>
</body>
</html>
