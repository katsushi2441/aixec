<?php
$BASE_HOST  = 'https://aixec.exbridge.jp';
$page_title = 'AIxEC 書籍・ガジェット紹介リール | ショート動画でおすすめ商品をチェック';
$page_desc  = 'AI技術書・開発書・ガジェットなどの商品紹介ショート動画をリール形式でご覧いただけます。AIxECセレクトのおすすめ商品をサクッとチェック。';
$page_url   = $BASE_HOST . '/reels.php';
$page_image = $BASE_HOST . '/images/reels.png';

function h($s) { return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8'); }

function api_get($path, $params = array()) {
    $p = array_merge(array('path' => ltrim($path, '/')), $params);
    $url = 'https://aixec.exbridge.jp/api.php?' . http_build_query($p);
    $ch = curl_init($url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 10);
    $body = curl_exec($ch);
    curl_close($ch);
    if (!$body) return array();
    $d = json_decode($body, true);
    return is_array($d) ? $d : array();
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

function reels_rakuten_url($item) {
    $title = isset($item['name']) ? $item['name'] : '本';
    $params = array(
        'to' => 'rakuten',
        'kw' => $title,
        'from' => 'reels',
    );
    if (!empty($item['id'])) $params['pid'] = (int)$item['id'];
    if (!empty($item['model_number'])) $params['model'] = $item['model_number'];
    if (!empty($item['jan'])) $params['jan'] = preg_replace('/\D/', '', (string)$item['jan']);
    if (!empty($item['rakuten_url'])) $params['url'] = $item['rakuten_url'];
    return '/go.php?' . http_build_query($params);
}

// タブ別ランキングフィルタ
$tab_defs = array(
    'health'      => array('genre_id' => '001010010', 'hits' => 20),
    'ai'          => array('genre_id' => '001005', 'keyword' => 'AI', 'hits' => 20),
    'web3'        => array('keyword' => 'ブロックチェーン', 'hits' => 20),
    'programming' => array('genre_id' => '001005005', 'hits' => 20),
    'side_business' => array('keyword' => '副業', 'hits' => 20),
    'sole_proprietor_tax' => array('keyword' => '確定申告', 'hits' => 20),
    'investment_nisa' => array('keyword' => '新NISA', 'hits' => 20),
    'stock_investment' => array('keyword' => '株式投資', 'hits' => 20),
);
$tab = (isset($_GET['tab']) && isset($tab_defs[$_GET['tab']])) ? $_GET['tab'] : '';
$limit = isset($_GET['limit']) ? (int)$_GET['limit'] : 10;
if ($limit < 1) $limit = 10;
if ($limit > 50) $limit = 50;
$allowed_ids = null;
$id_rank = array();

// ?q= によるキーワード検索絞り込み（タブより優先）
if ($tab === '' && isset($_GET['q']) && $_GET['q'] !== '') {
    $qres = api_get('products', array('q' => $_GET['q'], 'limit' => 10));
    if (!empty($qres['ok']) && !empty($qres['items'])) {
        $allowed_ids = array_map(function($it){ return (int)$it['id']; }, $qres['items']);
        foreach ($allowed_ids as $pos => $pid) { $id_rank[$pid] = $pos; }
    } else {
        $allowed_ids = array();
    }
}
// ?ids= / ?isbns= による直接指定
if ($tab === '' && $allowed_ids === null && ((isset($_GET['ids']) && $_GET['ids'] !== '') || (isset($_GET['isbns']) && $_GET['isbns'] !== ''))) {
    $allowed_ids = array();
    $pos = 0;
    if (isset($_GET['ids']) && $_GET['ids'] !== '') {
        foreach (array_filter(array_map('intval', explode(',', $_GET['ids']))) as $pid) {
            if ($pid <= 0 || in_array($pid, $allowed_ids, true)) continue;
            $allowed_ids[] = $pid;
            $id_rank[$pid] = $pos++;
        }
    }
    if (isset($_GET['isbns']) && $_GET['isbns'] !== '') {
        $isbns = array();
        foreach (explode(',', $_GET['isbns']) as $isbn) {
            $clean = preg_replace('/\D/', '', $isbn);
            if ($clean !== '') $isbns[] = $clean;
        }
        if ($isbns) {
            $pres = api_get('products', array('isbns' => implode(',', $isbns), 'limit' => 100));
            $isbn_rank = array_flip($isbns);
            if (!empty($pres['ok']) && !empty($pres['items'])) {
                foreach ($pres['items'] as $pi) {
                    $pid = (int)$pi['id'];
                    if ($pid <= 0 || in_array($pid, $allowed_ids, true)) continue;
                    $allowed_ids[] = $pid;
                    $pi_isbn = preg_replace('/\D/', '', (string)(isset($pi['model_number']) ? $pi['model_number'] : (isset($pi['jan']) ? $pi['jan'] : '')));
                    $id_rank[$pid] = isset($isbn_rank[$pi_isbn]) ? ($pos + $isbn_rank[$pi_isbn]) : ($pos + 9999);
                }
            }
        }
    }
}
if ($tab !== '') {
    $rank_res = api_get('books/ranking', $tab_defs[$tab]);
    $rank_items = (!empty($rank_res['ok']) && !empty($rank_res['result']['items'])) ? $rank_res['result']['items'] : array();
    $isbns = array();
    foreach ($rank_items as $rb) {
        $isbn = preg_replace('/\D/', '', isset($rb['isbn']) ? $rb['isbn'] : '');
        if ($isbn !== '') $isbns[] = $isbn;
    }
    if ($isbns) {
        $isbn_rank = array_flip($isbns);
        $pres = api_get('products', array('isbns' => implode(',', $isbns), 'limit' => 100));
        $allowed_ids = array();
        if (!empty($pres['ok']) && !empty($pres['items'])) {
            foreach ($pres['items'] as $pi) {
                $pid = (int)$pi['id'];
                $allowed_ids[] = $pid;
                $pi_isbn = preg_replace('/\D/', '', (string)(isset($pi['model_number']) ? $pi['model_number'] : (isset($pi['jan']) ? $pi['jan'] : '')));
                $id_rank[$pid] = isset($isbn_rank[$pi_isbn]) ? $isbn_rank[$pi_isbn] : 9999;
            }
        }
    } else {
        $allowed_ids = array();
    }
}

$video_dir = __DIR__ . '/video/';
$files = glob($video_dir . '*.mp4') ?: array();
$ids = array_map(function($f) { return (int)basename($f, '.mp4'); }, $files);
if ($allowed_ids !== null) {
    $ids = array_values(array_intersect($ids, $allowed_ids));
    if ($id_rank) {
        usort($ids, function($a, $b) use ($id_rank) {
            return (isset($id_rank[$a]) ? $id_rank[$a] : 9999) - (isset($id_rank[$b]) ? $id_rank[$b] : 9999);
        });
    } else {
        rsort($ids);
    }
    $ids = array_slice($ids, 0, $limit);
} else {
    rsort($ids);
    $ids = array_slice($ids, 0, $limit);
}

$videos = array();
foreach ($ids as $id) {
    if (!$id) continue;
    $res = api_get('products/' . $id);
    $item = (!empty($res['ok']) && !empty($res['item'])) ? $res['item'] : array();
    $maker = isset($item['maker']) ? $item['maker'] : '';
    $model = isset($item['model_number']) ? $item['model_number'] : '';
    $name = isset($item['name']) ? $item['name'] : '';
    $slug = ($maker !== '' || $model !== '') ? make_slug($maker, $model, $name) : (string)$id;
    $videos[] = array(
        'id'        => $id,
        'title'     => isset($item['name']) ? $item['name'] : '',
        'maker'     => $maker,
        'image_url' => isset($item['image_url']) ? $item['image_url'] : '',
        'slug'      => $slug,
        'tube_url'  => '/aixtube.php?v=' . rawurlencode((string)$id),
        'rakuten_url' => reels_rakuten_url($item),
    );
}
?><!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
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
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"WebPage","name":<?php echo json_encode($page_title); ?>,"description":<?php echo json_encode($page_desc); ?>,"url":<?php echo json_encode($page_url); ?>,"publisher":{"@type":"Organization","name":"AIxEC","url":<?php echo json_encode($BASE_HOST); ?>}}
</script>
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
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%;background:#111;overflow:hidden;font-family:-apple-system,system-ui,"Hiragino Sans",sans-serif}
.player-wrap{display:flex;height:100vh;height:100dvh;align-items:stretch;justify-content:center}
.feed{width:100%;max-width:420px;height:100vh;height:100dvh;overflow-y:scroll;scroll-snap-type:y mandatory;-webkit-overflow-scrolling:touch;scrollbar-width:none;flex-shrink:0}
.feed::-webkit-scrollbar{display:none}
.slide{position:relative;height:100vh;height:100dvh;scroll-snap-align:start;overflow:hidden;background:#000}
.slide video{width:100%;height:100%;object-fit:contain;display:block}
.poster-overlay{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none}
.poster-overlay img{max-height:65vh;max-width:80%;object-fit:contain;border-radius:4px}
.grad{position:absolute;inset:0;background:linear-gradient(to bottom,rgba(0,0,0,.3) 0%,transparent 30%,transparent 55%,rgba(0,0,0,.75) 100%);pointer-events:none}
.info{position:absolute;bottom:0;left:0;right:60px;padding:20px 16px calc(env(safe-area-inset-bottom,0px) + 48px)}
.info .title{font-size:15px;font-weight:700;color:#fff;line-height:1.45;margin-bottom:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.info .maker{font-size:12px;color:rgba(255,255,255,.75);margin-bottom:14px}
.info .links{display:flex;gap:8px;flex-wrap:wrap}.info .product-link{display:inline-block;padding:7px 16px;background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.35);border-radius:20px;color:#fff;text-decoration:none;font-size:13px;font-weight:600;backdrop-filter:blur(4px)}.info .product-link.rakuten-link{background:rgba(191,0,0,.85);border-color:rgba(255,255,255,.3)}
.side{position:absolute;right:12px;bottom:calc(env(safe-area-inset-bottom,0px) + 52px);display:flex;flex-direction:column;gap:16px;align-items:center}
.side button{background:rgba(0,0,0,.45);border:none;border-radius:50%;width:44px;height:44px;color:#fff;font-size:20px;cursor:pointer;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px)}
.back{position:fixed;top:calc(env(safe-area-inset-top,0px) + 12px);left:16px;z-index:100;background:rgba(0,0,0,.45);border:none;border-radius:50%;width:40px;height:40px;color:#fff;font-size:18px;cursor:pointer;text-decoration:none;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px)}
.pc-nav{display:none;flex-direction:column;justify-content:center;gap:20px;padding:0 20px}
.pc-nav button{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.2);border-radius:50%;width:48px;height:48px;color:#fff;font-size:22px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .15s}
.pc-nav button:hover{background:rgba(255,255,255,.25)}
@media(min-width:600px){.pc-nav{display:flex}}
.empty{color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-size:16px}
.tabs{position:fixed;top:calc(env(safe-area-inset-top,0px) + 8px);left:50%;transform:translateX(-50%);z-index:100;display:flex;gap:6px;max-width:calc(100vw - 76px);overflow-x:auto;padding:4px 8px;background:rgba(0,0,0,.5);border-radius:20px;backdrop-filter:blur(6px);scrollbar-width:none;-webkit-overflow-scrolling:touch}
.tabs::-webkit-scrollbar{display:none}
.tabs a{color:rgba(255,255,255,.65);text-decoration:none;font-size:12px;font-weight:600;padding:4px 10px;border-radius:14px;white-space:nowrap;transition:background .15s,color .15s}
.tabs a.active{background:rgba(255,255,255,.25);color:#fff}
.tabs a:hover{color:#fff}
</style>
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-2528616930208188"
     crossorigin="anonymous"></script>
</head>
<body>
<a class="back" href="/">&#8592;</a>
<nav class="tabs">
  <a href="/aixtube.php">AIxTube</a>
  <?php $vwork_promo_variant = 'links'; include __DIR__ . '/vwork_promo.php'; ?>
  <a href="/reels.php" <?php if($tab==='') echo 'class="active"'; ?>>すべて</a>
  <a href="/reels.php?tab=health" <?php if($tab==='health') echo 'class="active"'; ?>>健康</a>
  <a href="/reels.php?tab=ai" <?php if($tab==='ai') echo 'class="active"'; ?>>AI</a>
  <a href="/reels.php?tab=web3" <?php if($tab==='web3') echo 'class="active"'; ?>>Web3</a>
  <a href="/reels.php?tab=programming" <?php if($tab==='programming') echo 'class="active"'; ?>>プログラミング</a>
  <a href="/reels.php?tab=side_business" <?php if($tab==='side_business') echo 'class="active"'; ?>>副業</a>
  <a href="/reels.php?tab=sole_proprietor_tax" <?php if($tab==='sole_proprietor_tax') echo 'class="active"'; ?>>確定申告</a>
  <a href="/reels.php?tab=investment_nisa" <?php if($tab==='investment_nisa') echo 'class="active"'; ?>>新NISA</a>
  <a href="/reels.php?tab=stock_investment" <?php if($tab==='stock_investment') echo 'class="active"'; ?>>株式投資</a>
</nav>
<?php if (empty($videos)): ?>
<div class="empty">動画がありません</div>
<?php else: ?>
<div class="player-wrap">
  <div class="pc-nav">
    <button onclick="goTo(current-1)" aria-label="前の動画">&#8593;</button>
    <button onclick="goTo(current+1)" aria-label="次の動画">&#8595;</button>
  </div>
  <div class="feed" id="feed">
  <?php foreach ($videos as $i => $v): ?>
  <div class="slide">
    <video src="/video/<?php echo (int)$v['id']; ?>.mp4"
           playsinline muted loop preload="<?php echo $i < 2 ? 'metadata' : 'none'; ?>">
    </video>
    <?php if ($v['image_url']): ?>
    <div class="poster-overlay"><img src="<?php echo h($v['image_url']); ?>" alt=""></div>
    <?php endif; ?>
    <div class="grad"></div>
    <div class="info">
      <?php if ($v['title']): ?><div class="title"><?php echo h($v['title']); ?></div><?php endif; ?>
      <?php if ($v['maker']): ?><div class="maker"><?php echo h($v['maker']); ?></div><?php endif; ?>
      <div class="links">
        <a class="product-link" href="<?php echo h($v['tube_url']); ?>">動画ページ</a>
        <a class="product-link" href="/product/<?php echo urlencode($v['slug']); ?>">商品を見る →</a>
        <a class="product-link rakuten-link" href="<?php echo h($v['rakuten_url']); ?>" target="_blank" rel="nofollow sponsored noopener">楽天で見る</a>
      </div>
    </div>
    <?php $share_url = 'https://aixec.exbridge.jp' . $v['tube_url']; ?>
    <div class="side">
      <button class="mute-btn" onclick="toggleMute()" aria-label="ミュート切替">🔇</button>
      <button class="share-x-btn" data-title="<?php echo h($v['title']); ?>" data-url="<?php echo h($share_url); ?>" aria-label="Xでシェア">𝕏</button>
      <button class="copy-slide-btn" data-title="<?php echo h($v['title']); ?>" data-url="<?php echo h($share_url); ?>" aria-label="コピー">📋</button>
    </div>
  </div>
  <?php endforeach; ?>
  </div>
</div>
<script>
var muted = true;
var current = 0;
var slides = Array.from(document.querySelectorAll('.slide'));
var feed = document.getElementById('feed');

function goTo(idx) {
  if (idx < 0 || idx >= slides.length) return;
  current = idx;
  slides[idx].scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function toggleMute() {
  muted = !muted;
  document.querySelectorAll('.slide video').forEach(function(v){ v.muted = muted; });
  document.querySelectorAll('.mute-btn').forEach(function(b){ b.textContent = muted ? '🔇' : '🔊'; });
}

document.addEventListener('keydown', function(e) {
  if (e.key === 'ArrowDown') goTo(current + 1);
  if (e.key === 'ArrowUp') goTo(current - 1);
});

var timers = new WeakMap();
var observer = new IntersectionObserver(function(entries) {
  entries.forEach(function(e) {
    var v = e.target.querySelector('video');
    if (!v) return;
    if (e.isIntersecting) {
      current = slides.indexOf(e.target);
      var next = e.target.nextElementSibling;
      if (next) { var nv = next.querySelector('video'); if (nv) nv.preload = 'auto'; }
      var t = setTimeout(function() {
        var po = e.target.querySelector('.poster-overlay');
        if (po) po.style.display = 'none';
        v.muted = muted;
        v.currentTime = 0;
        v.play().catch(function(){ v.muted = true; muted = true; v.play(); });
      }, 2000);
      timers.set(e.target, t);
    } else {
      var t = timers.get(e.target);
      if (t) { clearTimeout(t); timers.delete(e.target); }
      v.pause();
      v.currentTime = 0;
      var po = e.target.querySelector('.poster-overlay');
      if (po) po.style.display = '';
    }
  });
}, { root: feed, threshold: 0.75 });

slides.forEach(function(s){ observer.observe(s); });

document.addEventListener('click', function(e) {
  var xBtn = e.target.closest('.share-x-btn');
  if (xBtn) {
    var text = (xBtn.dataset.title || '') + '\n' + (xBtn.dataset.url || '');
    window.open('https://twitter.com/intent/tweet?text=' + encodeURIComponent(text), '_blank');
  }
  var cpBtn = e.target.closest('.copy-slide-btn');
  if (cpBtn) {
    var text = (cpBtn.dataset.title || '') + '\n' + (cpBtn.dataset.url || '');
    navigator.clipboard.writeText(text).then(function() {
      cpBtn.textContent = '✓';
      setTimeout(function() { cpBtn.textContent = '📋'; }, 2000);
    });
  }
});
</script>
<?php endif; ?>
</body>
</html>
