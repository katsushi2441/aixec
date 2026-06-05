<?php
function h($value) {
    return htmlspecialchars((string)$value, ENT_QUOTES, 'UTF-8');
}

function yen($value) {
    if ($value === null || $value === '') return '';
    return '¥' . number_format((int)$value);
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

function display_model_number($model) {
    $model = trim((string)$model);
    if ($model === '') return '';
    if (preg_match('/^(?:HSH|MMS\d*)-(.+)$/i', $model, $m)) {
        return $m[1];
    }
    return $model;
}

function make_slug($maker, $model, $name = '') {
    $model = display_model_number($model);
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

function clean_keyword_part($value) {
    $value = preg_replace('/【(?:公式|送料無料|激安|セール)】/u', ' ', (string)$value);
    $value = preg_replace('/(?:楽天市場店|公式|送料無料|激安|セール)/u', ' ', $value);
    return preg_replace('/\s+/u', ' ', trim($value));
}

function affiliate_keyword($item) {
    $model_raw = !empty($item['model_number']) ? (string)$item['model_number'] : '';
    if (strpos($model_raw, ':') !== false && !empty($item['name'])) {
        return clean_keyword_part($item['name']);
    }
    $parts = array();
    if (!empty($item['maker'])) $parts[] = clean_keyword_part($item['maker']);
    $model = $model_raw !== '' ? display_model_number($model_raw) : '';
    if ($model !== '') $parts[] = $model;
    if (!$parts && !empty($item['name'])) $parts[] = clean_keyword_part($item['name']);
    return trim(implode(' ', $parts));
}

function rakuten_click_url($item) {
    $kw = affiliate_keyword($item);
    if ($kw === '') $kw = isset($item['name']) ? $item['name'] : '楽天市場';
    $params = array('to' => 'rakuten', 'kw' => $kw, 'from' => 'market_ranking:' . (isset($_GET['tab']) ? $_GET['tab'] : ''));
    if (!empty($item['id'])) $params['pid'] = $item['id'];
    if (!empty($item['model_number'])) $params['model'] = display_model_number($item['model_number']);
    if (!empty($item['jan'])) $params['jan'] = preg_replace('/\D/', '', $item['jan']);
    return '/go.php?' . http_build_query($params);
}

function amazon_click_url($item) {
    $kw = affiliate_keyword($item);
    if ($kw === '') $kw = isset($item['name']) ? $item['name'] : 'Amazon';
    $params = array('to' => 'amazon', 'kw' => $kw, 'from' => 'market_ranking:' . (isset($_GET['tab']) ? $_GET['tab'] : ''));
    if (!empty($item['id'])) $params['pid'] = $item['id'];
    if (!empty($item['model_number'])) $params['model'] = display_model_number($item['model_number']);
    if (!empty($item['jan'])) $params['jan'] = preg_replace('/\D/', '', $item['jan']);
    if (!empty($item['asin'])) $params['asin'] = $item['asin'];
    return '/go.php?' . http_build_query($params);
}

function product_url($item) {
    $slug = make_slug(isset($item['maker']) ? $item['maker'] : '', isset($item['model_number']) ? $item['model_number'] : '', isset($item['name']) ? $item['name'] : '');
    if ($slug === '' && !empty($item['id'])) $slug = $item['id'];
    return '/product/' . rawurlencode($slug);
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

function click_counts_from_log() {
    $path = __DIR__ . '/access.log';
    if (!is_readable($path)) return array();
    $lines = file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    if (!$lines) return array();
    if (count($lines) > 30000) $lines = array_slice($lines, -30000);
    $counts = array();
    foreach ($lines as $line) {
        $params = log_query_params($line);
        $click = isset($params['click']) ? strtolower($params['click']) : '';
        $to = isset($params['to']) ? strtolower($params['to']) : '';
        if ($click !== 'rakuten' && $to !== 'rakuten') continue;
        $pid = isset($params['product_id']) ? trim($params['product_id']) : '';
        if ($pid === '' && isset($params['pid'])) $pid = trim($params['pid']);
        if ($pid === '' || !ctype_digit($pid)) continue;
        if (!isset($counts[$pid])) $counts[$pid] = 0;
        $counts[$pid]++;
    }
    return $counts;
}

function fetch_group_products($group, $limit = 500) {
    $items = array();
    $offset = 0;
    while (count($items) < $limit) {
        $res = api_get('products', array(
            'attr_name' => 'rakuten_genre_group',
            'attr_value' => $group,
            'limit' => 200,
            'offset' => $offset,
        ));
        $batch = (!empty($res['ok']) && !empty($res['items']) && is_array($res['items'])) ? $res['items'] : array();
        foreach ($batch as $item) $items[] = $item;
        if (count($batch) < 200) break;
        $offset += 200;
    }
    return array_slice($items, 0, $limit);
}

$tabs = array(
    'trading_cards' => array('label' => 'トレカ', 'lead' => '楽天市場から取得したトレーディングカード商品'),
    'beauty_cosmetics' => array('label' => '美容・コスメ', 'lead' => '楽天市場から取得した美容・コスメ商品'),
    'supplements' => array('label' => 'サプリ', 'lead' => '楽天市場から取得したサプリメント商品'),
    'portable_power_outdoor_appliances' => array('label' => 'ポータブル電源・防災電源', 'lead' => 'ポータブル電源、家庭用蓄電池、車中泊家電、発電機、大型UPSなどの高額商材'),
    'offgrid_power_inverters' => array('label' => '独立電源・インバーター', 'lead' => '電菱、未来舎、Renogy、Victron、EcoFlow、Jackeryなどのインバーター、コンバーター、バッテリー、太陽光パネル'),
    'amazon_daily_consumables' => array('label' => 'Amazon日用品・飲料・消耗品', 'lead' => '飲料水、炭酸水、プロテイン、洗剤、衛生用品、日用品などAmazonで買われやすい消耗品'),
    'ai_pc_gaming' => array('label' => 'AI PC・ゲーミング', 'lead' => 'GPU、ゲーミングPC、ミニPC、配信機材、PC周辺機器'),
    'model_number_products' => array('label' => '型番商品・工具機器', 'lead' => '工具、測定器、PC周辺機器、家電など型番で探されやすい商品'),
    'celebrity_books' => array('label' => '芸能人・有名人の本', 'lead' => 'テレビやSNSで気になった人物を、エッセイ・自伝・写真集・評伝で深掘りする書籍'),
);
$active = (isset($_GET['tab']) && array_key_exists($_GET['tab'], $tabs)) ? $_GET['tab'] : 'trading_cards';

$products = fetch_group_products($active, 500);
$click_counts = click_counts_from_log();
usort($products, function($a, $b) use ($click_counts) {
    $aid = isset($a['id']) ? (string)$a['id'] : '';
    $bid = isset($b['id']) ? (string)$b['id'] : '';
    $ac = isset($click_counts[$aid]) ? $click_counts[$aid] : 0;
    $bc = isset($click_counts[$bid]) ? $click_counts[$bid] : 0;
    if ($ac != $bc) return ($ac > $bc) ? -1 : 1;
    $au = isset($a['updated_at']) ? $a['updated_at'] : '';
    $bu = isset($b['updated_at']) ? $b['updated_at'] : '';
    return strcmp($bu, $au);
});
$ranking = array_slice($products, 0, 50);

$page_title = '楽天市場 商品人気ランキング | AI駆動型ネット通販 AIxEC';
$page_description = 'AIxECが楽天市場から取得しているトレカ、美容・コスメ、サプリ、AI PC・ゲーミング関連商品をジャンル別にランキング表示します。';
?><!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?php echo h($page_title); ?></title>
<meta name="description" content="<?php echo h($page_description); ?>">
<link rel="canonical" href="https://aixec.exbridge.jp/market_ranking.php">
<meta property="og:title" content="<?php echo h($page_title); ?>">
<meta property="og:description" content="<?php echo h($page_description); ?>">
<meta property="og:type" content="website">
<meta property="og:url" content="https://aixec.exbridge.jp/market_ranking.php">
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
:root{--ink:rgba(0,0,0,.87);--muted:rgba(0,0,0,.56);--line:#e0e0e0;--paper:#fff;--soft:#f5f6f6;--accent:#55c500;--accent-dark:#468c00;--red:#bf0000}
*{box-sizing:border-box}
body{margin:0;font-family:YakuHanJPs,-apple-system,system-ui,"Segoe UI","Hiragino Kaku Gothic ProN","Hiragino Sans",Meiryo,sans-serif;color:var(--ink);background:var(--soft);letter-spacing:0;line-height:1.75;word-break:break-word;overflow-wrap:anywhere}
a{color:inherit}
.top{background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
.wrap,.hero,.tabs,.main{max-width:1100px;margin:0 auto;padding-left:16px;padding-right:16px}
.wrap{padding-top:12px;padding-bottom:12px}.bar{display:flex;align-items:center;justify-content:space-between;gap:18px}
.brand{display:flex;align-items:center;gap:12px;min-width:0;text-decoration:none}.mark{width:36px;height:36px;border-radius:4px;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px}.brand b{display:block;font-size:22px;line-height:1}.brand span{display:block;color:var(--muted);font-size:12px;margin-top:4px}.brand-ogp{display:block;width:auto;height:42px;object-fit:contain}
.nav{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.nav a{font-size:13px;color:var(--muted);text-decoration:none;border:1px solid var(--line);background:#fff;border-radius:4px;padding:6px 10px}.nav a:hover{color:var(--accent-dark);border-color:#cfe8c4}.nav-mobile{display:none}
.nav-mobile a{font-size:13px;font-weight:600;text-decoration:none;border:1px solid var(--line);background:#fff;border-radius:4px;padding:6px 10px;white-space:nowrap;flex-shrink:0}
.hero{padding-top:24px}.hero h1{font-size:28px;line-height:1.4;margin:0 0 6px;font-weight:700}.lead{color:var(--muted);font-size:14px;margin:0}
.tabs{padding-top:16px}.tab-list{display:flex;gap:0;border-bottom:2px solid var(--line);overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}.tab-list::-webkit-scrollbar{display:none}.tab-list a{display:block;white-space:nowrap;padding:10px 18px;font-size:14px;font-weight:700;color:var(--muted);text-decoration:none;border-bottom:3px solid transparent;margin-bottom:-2px}.tab-list a.active{color:var(--accent-dark);border-bottom-color:var(--accent)}
.main{padding-top:16px;padding-bottom:48px}.section-head{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;margin:4px 0 12px}.section-head h2{font-size:20px;line-height:1.4;font-weight:700;margin:0}.section-head p{margin:0;color:var(--muted);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.card{background:#fff;border:1px solid var(--line);border-radius:4px;overflow:hidden;display:flex;flex-direction:column;min-height:390px}.card:hover{box-shadow:0 2px 4px rgba(0,0,0,.1);border-color:#c8c8c8}.rank{height:36px;display:flex;align-items:center;justify-content:space-between;padding:0 12px;border-bottom:1px solid var(--line);font-weight:700;color:var(--accent-dark)}.rank small{color:var(--muted);font-weight:400}.cover{display:flex;align-items:center;justify-content:center;height:190px;background:#fff;border-bottom:1px solid var(--line);padding:12px}.cover img{display:block;max-width:100%;max-height:166px;object-fit:contain}.body{padding:14px;display:flex;flex-direction:column;flex:1}.title{font-size:14px;line-height:1.65;font-weight:700;text-decoration:none;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}.title:hover{text-decoration:underline}.meta{color:var(--muted);font-size:12px;margin-top:9px}.price{font-size:17px;font-weight:700;margin-top:auto;padding-top:12px;color:var(--red)}.actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}.btn{display:flex;align-items:center;justify-content:center;min-height:36px;border-radius:4px;border:1px solid var(--line);text-decoration:none;font-size:12px;font-weight:700;background:#fff}.btn.primary{background:#bf0000;border-color:#bf0000;color:#fff}.empty{background:#fff;border:1px solid var(--line);border-radius:4px;padding:34px;text-align:center;color:var(--muted)}
@media(max-width:960px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:700px){.bar{align-items:flex-start;flex-direction:column;gap:8px}.nav{display:none}.nav-mobile{display:flex;gap:8px;margin-top:8px;overflow-x:auto;width:100%;-webkit-overflow-scrolling:touch;scrollbar-width:none}.nav-mobile::-webkit-scrollbar{display:none}.brand-ogp{height:34px}.hero h1{font-size:22px}.grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.card{min-height:auto}.cover{height:auto;padding:6px}.cover img{max-height:130px}.body{padding:10px}.price{font-size:14px}.tab-list a{padding:9px 13px;font-size:13px}.actions{grid-template-columns:1fr}}
@media(max-width:460px){.grid{grid-template-columns:1fr}.cover img{max-height:120px}}
</style>
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-2528616930208188"
     crossorigin="anonymous"></script>
</head>
<body>
<header class="top"><div class="wrap">
  <div class="bar">
    <a class="brand" href="/"><div class="mark">AIx</div><div><b>AIxEC</b><span>AI x EC product intelligence</span></div><img class="brand-ogp" src="/images/aixec.png" alt="AIxEC"></a>
    <nav class="nav"><a href="/">商品検索</a><a href="/market_ranking.php">人気商品</a><a href="/books_ranking.php">人気書籍</a><a href="/aixtube.php">AIxTube</a><a href="/reels.php">商品動画</a><a href="/sns.php">新着情報</a></nav>
  </div>
  <div class="nav-mobile">
    <a href="/market_ranking.php">人気商品</a>
    <a href="/books_ranking.php">人気書籍</a>
    <a href="/aixtube.php">AIxTube</a>
    <a href="/reels.php">動画</a>
    <a href="/sns.php">新着情報</a>
  </div>
</div></header>
<?php include __DIR__ . '/vwork_promo.php'; ?>

<section class="hero">
  <h1>楽天市場 商品人気ランキング</h1>
  <p class="lead">書籍以外の楽天市場取得ジャンルを、AIxEC内のクリック人気順と新着順で表示します。</p>
</section>

<div class="tabs">
  <nav class="tab-list">
    <?php foreach ($tabs as $key => $tab): ?>
    <a href="?tab=<?php echo h($key); ?>" class="<?php echo $active === $key ? 'active' : ''; ?>"><?php echo h($tab['label']); ?></a>
    <?php endforeach; ?>
  </nav>
</div>

<main class="main">
  <div class="section-head">
    <div>
      <h2><?php echo h($tabs[$active]['label']); ?></h2>
      <p><?php echo h($tabs[$active]['lead']); ?></p>
    </div>
    <p><?php echo count($ranking); ?>件表示</p>
  </div>
  <?php if (!$ranking): ?>
    <div class="empty">このジャンルの商品データがまだありません。</div>
  <?php else: ?>
  <div class="grid">
    <?php foreach ($ranking as $idx => $item):
        $pid = isset($item['id']) ? (string)$item['id'] : '';
        $clicks = isset($click_counts[$pid]) ? $click_counts[$pid] : 0;
        $img = !empty($item['image_url']) ? $item['image_url'] : '/images/noimage.jpg';
        $detail_url = product_url($item);
        $rakuten_url = rakuten_click_url($item);
        $amazon_url = amazon_click_url($item);
        $model = !empty($item['model_number']) ? display_model_number($item['model_number']) : '';
    ?>
    <article class="card">
      <div class="rank">#<?php echo $idx + 1; ?><small><?php echo $clicks ? (int)$clicks . ' clicks' : 'new'; ?></small></div>
      <a class="cover" href="<?php echo h($detail_url); ?>">
        <img src="<?php echo h($img); ?>" alt="<?php echo h($item['name']); ?>" loading="lazy">
      </a>
      <div class="body">
        <a class="title" href="<?php echo h($detail_url); ?>"><?php echo h($item['name']); ?></a>
        <div class="meta"><?php echo h(isset($item['maker']) ? $item['maker'] : ''); ?><?php if ($model !== ''): ?><br><?php echo h($model); ?><?php endif; ?></div>
        <div class="price"><?php echo h(yen(isset($item['sale_price']) ? $item['sale_price'] : '')); ?></div>
        <div class="actions">
          <a class="btn" href="<?php echo h($detail_url); ?>">商品を見る</a>
          <a class="btn primary" href="<?php echo h($amazon_url); ?>" target="_blank" rel="nofollow sponsored noopener">Amazonで見る</a>
          <a class="btn" href="<?php echo h($rakuten_url); ?>" target="_blank" rel="nofollow sponsored noopener">楽天で見る</a>
        </div>
      </div>
    </article>
    <?php endforeach; ?>
  </div>
  <?php endif; ?>
</main>
</body>
</html>
