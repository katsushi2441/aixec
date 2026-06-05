<?php
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

function display_model_number($model) {
    $model = trim((string)$model);
    if ($model === '') return '';
    if (preg_match('/^(?:HSH|MMS\d*)-(.+)$/i', $model, $m)) {
        return $m[1];
    }
    return $model;
}

if (!function_exists('api_get')) {
function api_get($path, $params = array()) {
    $params = array_merge(array('path' => ltrim($path, '/')), $params);
    $url = 'https://aixec.exbridge.jp/api.php?' . http_build_query($params);
    $ch = curl_init($url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 20);
    $body = curl_exec($ch);
    $error = curl_error($ch);
    curl_close($ch);
    if ($body === false || $body === '') {
        return array('ok' => false, 'error' => $error ?: 'API error');
    }
    $json = json_decode($body, true);
    return is_array($json) ? $json : array('ok' => false, 'error' => 'Invalid API response');
}
}

function h($value) {
    return htmlspecialchars((string)$value, ENT_QUOTES, 'UTF-8');
}

function yen($value) {
    if ($value === null || $value === '') return '';
    return '¥' . number_format((int)$value);
}

function plain_text($value) {
    $value = preg_replace('/\s+/u', ' ', strip_tags((string)$value));
    return trim($value);
}

function text_excerpt($value, $length = 96) {
    $text = html_entity_decode(strip_tags((string)$value), ENT_QUOTES | ENT_HTML5, 'UTF-8');
    $text = preg_replace('/https?:\/\/\S+/u', '', $text);
    $text = preg_replace('/\bwidth\s*=\s*["\']?\d+%?["\']?/iu', '', $text);
    $text = trim(preg_replace('/\s+/u', ' ', $text));
    if ($text === '') return '';
    if (mb_strlen($text, 'UTF-8') <= $length) return $text;
    return mb_substr($text, 0, $length, 'UTF-8') . '…';
}

function post_title_from_content($content) {
    $plain = html_entity_decode(strip_tags((string)$content), ENT_QUOTES | ENT_HTML5, 'UTF-8');
    $lines = preg_split('/\R/u', $plain);
    foreach ($lines as $line) {
        $line = trim(preg_replace('/\s+/u', ' ', $line));
        if ($line !== '' && stripos($line, 'width=') === false) {
            return mb_strlen($line, 'UTF-8') > 46 ? mb_substr($line, 0, 46, 'UTF-8') . '…' : $line;
        }
    }
    return 'AIxSNS 新着情報';
}

function short_date($value) {
    $ts = strtotime((string)$value);
    if (!$ts) return '';
    return date('n/j H:i', $ts);
}

function copy_text_description($html) {
    $html = (string)$html;
    $affiliate_pat = 'amazon\.co\.jp|rakuten\.co\.jp|hb\.afl\.rakuten|tag=bittensorman|\/go\.php\?';
    // アフィリエイトURLを含む<p>ブロックごと除去
    $html = preg_replace('/<p\b[^>]*>[\s\S]*?(?:' . $affiliate_pat . ')[\s\S]*?<\/p>/i', '', $html);
    // アフィリエイトリンク（aタグごと中身も除去）
    $html = preg_replace(
        '/<a\b[^>]*href=["\'][^"\']*(?:' . $affiliate_pat . ')[^"\']*["\'][^>]*>.*?<\/a>/is',
        '',
        $html
    );
    // ブロック要素を改行に変換
    $html = preg_replace('/<\/?\s*(?:p|div|br|li|tr|h[1-6]|section|blockquote|pre)\b[^>]*>/i', "\n", $html);
    $html = strip_tags($html);
    $html = html_entity_decode($html, ENT_QUOTES | ENT_HTML5, 'UTF-8');
    // 行ごとにトリム・連続空行は1行に圧縮
    $lines = explode("\n", $html);
    $out = array(); $prev_empty = false;
    foreach ($lines as $line) {
        $line = trim($line);
        if ($line === '') {
            if (!$prev_empty) $out[] = '';
            $prev_empty = true;
        } else {
            $out[] = $line;
            $prev_empty = false;
        }
    }
    return trim(implode("\n", $out));
}

function absolute_site_url($url) {
    $url = (string)$url;
    if ($url === '') return '';
    if (preg_match('/^https?:\/\//i', $url)) return $url;
    if ($url[0] === '/') return 'https://aixec.exbridge.jp' . $url;
    return 'https://aixec.exbridge.jp/' . $url;
}

function current_affiliate_keyword($q, $detail) {
    if (is_array($detail) && !empty($detail)) {
        $model_raw = !empty($detail['model_number']) ? (string)$detail['model_number'] : '';
        if (strpos($model_raw, ':') !== false && !empty($detail['name'])) {
            return clean_affiliate_keyword_part($detail['name']);
        }
        $parts = array();
        if (!empty($detail['maker'])) $parts[] = clean_affiliate_keyword_part($detail['maker']);
        $display_model = $model_raw !== '' ? display_model_number($model_raw) : '';
        if ($display_model !== '') $parts[] = $display_model;
        $keyword = trim(implode(' ', $parts));
        if ($keyword !== '') return $keyword;
    }
    if ($q !== '') return $q;
    return '電動工具';
}

function clean_affiliate_keyword_part($value) {
    $value = preg_replace('/【(?:公式|送料無料|激安|セール)】/u', ' ', (string)$value);
    $value = preg_replace('/(?:楽天市場店|公式|送料無料|激安|セール)/u', ' ', $value);
    $value = preg_replace('/\s+/u', ' ', trim($value));
    return $value;
}

function amazon_affiliate_search_url($keyword) {
    return 'https://www.amazon.co.jp/s?k=' . rawurlencode($keyword) . '&tag=bittensorman-22';
}

define("RAKUTEN_AFFILIATE_ID", "0b569b8b.f76b5de7.0b569b8c.0b66a994");

function rakuten_search_affiliate_url($keyword) {
    $search = 'https://search.rakuten.co.jp/search/mall/' . rawurlencode($keyword) . '/';
    return 'https://hb.afl.rakuten.co.jp/hgc/' . RAKUTEN_AFFILIATE_ID . '/?pc='
        . rawurlencode($search)
        . '&m=' . rawurlencode($search);
}

function rakuten_affiliate_search_url($keyword) {
    $res = api_get('rakuten/search', array('q' => $keyword, 'hits' => 1));
    if (!empty($res['ok']) && !empty($res['result']['items'][0]['affiliate_url'])) {
        return $res['result']['items'][0]['affiliate_url'];
    }
    return rakuten_search_affiliate_url($keyword);
}

function affiliate_click_url($provider, $keyword, $detail) {
    $params = array(
        'to' => $provider,
        'kw' => $keyword,
        'from' => 'product',
    );
    if (is_array($detail) && !empty($detail['id'])) {
        $params['pid'] = $detail['id'];
        $params['from'] = 'product:' . (int)$detail['id'];
    }
    if (is_array($detail) && !empty($detail['model_number'])) {
        $params['model'] = display_model_number($detail['model_number']);
    }
    if (($provider === 'rakuten' || $provider === 'amazon') && is_array($detail) && !empty($detail['jan'])) {
        $params['jan'] = preg_replace('/\D/', '', $detail['jan']);
    }
    if ($provider === 'amazon' && is_array($detail) && !empty($detail['asin'])) {
        $params['asin'] = strtoupper(trim($detail['asin']));
    }
    return '/go.php?' . http_build_query($params);
}

function normalize_description_affiliate_links($description, $detail) {
    if (!is_array($detail) || trim((string)$description) === '') return (string)$description;
    $keyword = current_affiliate_keyword('', $detail);
    return preg_replace_callback('/href=("|\')([^"\']*go\.php\?[^"\']*)\1/i', function($m) use ($detail, $keyword) {
        $quote = $m[1];
        $href = html_entity_decode($m[2], ENT_QUOTES | ENT_HTML5, 'UTF-8');
        $query = parse_url($href, PHP_URL_QUERY);
        if ($query === null || $query === false) return $m[0];
        parse_str($query, $params);
        $provider = isset($params['to']) ? strtolower(trim((string)$params['to'])) : '';
        if ($provider !== 'rakuten' && $provider !== 'amazon') return $m[0];
        $clean = absolute_site_url(affiliate_click_url($provider, $keyword, $detail));
        return 'href=' . $quote . h($clean) . $quote;
    }, (string)$description);
}

function description_has_affiliate($description, $provider) {
    $description = (string)$description;
    if ($description === '') return false;
    if ($provider === 'amazon') {
        return stripos($description, 'amazon.co.jp') !== false
            || stripos($description, 'tag=bittensorman-22') !== false
            || stripos($description, 'to=amazon') !== false;
    }
    if ($provider === 'rakuten') {
        return stripos($description, 'rakuten.co.jp') !== false
            || stripos($description, 'hb.afl.rakuten.co.jp') !== false
            || stripos($description, 'to=rakuten') !== false;
    }
    return false;
}

function xdirect_product_url($detail) {
    if (!empty($detail['own_store_url']) && strpos($detail['own_store_url'], 'exdirect.net/product/') !== false) return $detail['own_store_url'];
    if (!empty($detail['source_url']) && strpos($detail['source_url'], 'exdirect.net/product/') !== false) return $detail['source_url'];
    return '';
}

function aixtube_product_url($detail) {
    if (is_array($detail) && !empty($detail['id'])) {
        $video_id = (int)$detail['id'];
        if ($video_id && file_exists(__DIR__ . '/video/' . $video_id . '.mp4')) {
            return '/aixtube.php?v=' . rawurlencode((string)$video_id);
        }
    }
    return '/aixtube.php';
}

$q = isset($_GET['q']) ? trim($_GET['q']) : '';
$id = isset($_GET['id']) ? trim($_GET['id']) : '';
$detail = null;
$error = null;
if ($id !== '') {
    $res = api_get('products/' . $id);
    if (!empty($res['ok'])) {
        $detail = $res['item'];
    } else {
        $error = isset($res['error']) ? $res['error'] : '商品が見つかりません';
    }
}
$list = api_get('products', array('limit' => 24, 'q' => $q));
$items = !empty($list['ok']) ? $list['items'] : array();
if (empty($list['ok']) && !$error) {
    $error = isset($list['error']) ? $list['error'] : '商品一覧を取得できません';
}
$genre_links = array(
    array('label' => '人気書籍', 'q' => '人気書籍'),
    array('label' => '芸能人・有名人の本', 'q' => '志村けん 大谷翔平 写真集 エッセイ'),
    array('label' => 'AI', 'q' => 'AI'),
    array('label' => 'IT・プログラミング', 'q' => 'プログラミング IT'),
    array('label' => '健康・医療', 'q' => '健康 医療'),
    array('label' => 'Web3', 'q' => 'Web3'),
    array('label' => '暗号資産', 'q' => '暗号資産 暗号通貨'),
    array('label' => 'ブロックチェーン', 'q' => 'ブロックチェーン'),
    array('label' => 'NFT', 'q' => 'NFT'),
    array('label' => 'DeFi', 'q' => 'DeFi'),
    array('label' => '副業', 'q' => '副業'),
    array('label' => '起業・個人事業', 'q' => '起業 個人事業'),
    array('label' => '確定申告', 'q' => '確定申告'),
    array('label' => '投資・新NISA', 'q' => '投資 新NISA NISA'),
    array('label' => '株式投資', 'q' => '株式投資 株'),
    array('label' => '工具・DIY', 'q' => '工具 DIY'),
    array('label' => '機械', 'q' => '機械'),
    array('label' => '型番商品', 'q' => '型番'),
    array('label' => 'マキタ', 'q' => 'マキタ TD173'),
    array('label' => 'HiKOKI', 'q' => 'HiKOKI WH36DC'),
    array('label' => '測定器', 'q' => 'レーザー墨出し器'),
    array('label' => 'ルーター', 'q' => 'YAMAHA RTX ルーター'),
    array('label' => 'NAS・UPS', 'q' => 'Synology DS NAS'),
    array('label' => 'トレカ', 'q' => 'トレカ'),
    array('label' => '美容・コスメ', 'q' => '美容 コスメ'),
    array('label' => 'サプリ', 'q' => 'サプリ'),
    array('label' => 'Amazon日用品・飲料', 'q' => '水 炭酸水 洗剤 日用品 まとめ買い'),
    array('label' => '消耗品・まとめ買い', 'q' => 'トイレットペーパー ティッシュ 洗剤 まとめ買い'),
    array('label' => 'ポータブル電源・防災電源', 'q' => 'ポータブル電源 防災 電源 家庭用蓄電池'),
    array('label' => '車中泊・キャンプ電源', 'q' => '車中泊 ポータブル電源 キャンプ 電源'),
    array('label' => 'インバーター発電機・大型UPS', 'q' => 'インバーター発電機 UPS 3000VA'),
    array('label' => 'AI PC・ゲーミング', 'q' => 'AI PC ゲーミング'),
    array('label' => 'ゲーミングPC', 'q' => 'ゲーミングPC RTX'),
    array('label' => 'GPU', 'q' => 'GeForce RTX'),
    array('label' => 'GPUサーバー', 'q' => 'GPU'),
    array('label' => 'AIワークステーション', 'q' => 'ワークステーション'),
    array('label' => 'RTX', 'q' => 'RTX ゲーミングPC'),
    array('label' => 'RTX 5090', 'q' => 'RTX5090'),
    array('label' => 'RTX 5080', 'q' => 'RTX5080'),
    array('label' => 'RTX 5070', 'q' => 'RTX5070'),
    array('label' => 'ミニPC', 'q' => 'ミニPC 32GB'),
    array('label' => 'DDR5メモリ', 'q' => 'DDR5 メモリ 64GB'),
    array('label' => '4Kモニター', 'q' => '4K モニター'),
    array('label' => 'メカニカルキーボード', 'q' => 'メカニカルキーボード'),
    array('label' => 'USBマイク', 'q' => 'USB マイク 配信'),
    array('label' => 'Webカメラ', 'q' => 'Webカメラ 4K'),
    array('label' => '外付けSSD', 'q' => '外付けSSD 2TB'),
    array('label' => 'キャプチャーボード', 'q' => 'キャプチャーボード'),
);
$sns_latest = array();
$sns_res = api_get('posts', array('limit' => 3, 'offset' => 0));
if (!empty($sns_res['ok']) && !empty($sns_res['items']) && is_array($sns_res['items'])) {
    $sns_latest = $sns_res['items'];
}
$affiliate_keyword = current_affiliate_keyword($q, $detail);
$amazon_click_url = affiliate_click_url('amazon', $affiliate_keyword, $detail);
$rakuten_click_url = affiliate_click_url('rakuten', $affiliate_keyword, $detail);
$aixtube_url = aixtube_product_url($detail);
$xdirect_banner_url = 'https://exdirect.net';
$detail_description = ($detail && !empty($detail['description'])) ? normalize_description_affiliate_links($detail['description'], $detail) : '';
$has_market_ai_description = $detail_description !== '' && strpos($detail_description, 'aixec-ai-description:start') !== false;
$show_amazon_detail_affiliate = $detail && !description_has_affiliate($detail_description, 'amazon');
$show_rakuten_detail_affiliate = $detail && !description_has_affiliate($detail_description, 'rakuten');
$site_title = 'AI駆動型ネット通販 AIxEC - AI x EC Product Index';
$page_title = $site_title;
$page_description = 'AIxECは、AIが自律的に商品情報を整理し、商品紹介動画の自動生成などを行う、AI駆動型の商品メディアです。楽天・Amazonなどへの購入導線と連携し、検索や動画から商品との出会いを広げます。';
$page_url = 'https://aixec.exbridge.jp/';
$page_image = 'https://aixec.exbridge.jp/images/aixec.png';
if ($detail) {
    $detail_display_model = !empty($detail['model_number']) ? display_model_number($detail['model_number']) : '';
    $title_parts = array();
    if (!empty($detail['name'])) $title_parts[] = $detail['name'];
    if (!empty($detail['maker']) && mb_strpos($detail['name'], $detail['maker']) === false) $title_parts[] = $detail['maker'];
    if ($detail_display_model !== '' && mb_strpos($detail['name'], $detail_display_model) === false) $title_parts[] = $detail_display_model;
    $page_title = trim(implode(' ', $title_parts)) . ' | AI駆動型ネット通販 AIxEC';
    $page_description = trim(implode(' ', $title_parts)) . ' の価格比較・商品情報ページです。Amazon・楽天・XDirectの商品情報を確認できます。';
    $canonical_slug = make_slug(
        isset($detail['maker']) ? $detail['maker'] : '',
        isset($detail['model_number']) ? $detail['model_number'] : '',
        isset($detail['name']) ? $detail['name'] : ''
    );
    $page_url = 'https://aixec.exbridge.jp/product/' . rawurlencode($canonical_slug !== '' ? $canonical_slug : (string)$detail['id']);
    if (!empty($detail['image_url']) && $detail['image_url'] !== '/images/noimage.jpg') {
        $page_image = absolute_site_url($detail['image_url']);
    }
} elseif ($q !== '') {
    $page_title = $q . ' の検索結果 | AIxEC';
    $page_description = $q . ' の商品情報・価格比較をAIxECで確認できます。';
    $page_url = 'https://aixec.exbridge.jp/index.php?q=' . rawurlencode($q);
}
$product_schema_json = '';
if ($detail) {
    $schema = array(
        '@context' => 'https://schema.org',
        '@type' => 'Product',
        'name' => isset($detail['name']) ? $detail['name'] : '',
        'description' => plain_text($page_description),
        'sku' => isset($detail['internal_sku']) ? $detail['internal_sku'] : '',
        'mpn' => !empty($detail['model_number']) ? display_model_number($detail['model_number']) : '',
        'brand' => array(
            '@type' => 'Brand',
            'name' => isset($detail['maker']) ? $detail['maker'] : '',
        ),
        'url' => $page_url,
        'offers' => array(
            '@type' => 'Offer',
            'url' => $page_url,
            'priceCurrency' => 'JPY',
            'availability' => 'https://schema.org/InStock',
            'itemCondition' => 'https://schema.org/NewCondition',
            'hasMerchantReturnPolicy' => array(
                '@type' => 'MerchantReturnPolicy',
                'applicableCountry' => 'JP',
                'returnPolicyCategory' => 'https://schema.org/MerchantReturnNotPermitted',
            ),
            'shippingDetails' => array(
                '@type' => 'OfferShippingDetails',
                'shippingRate' => array(
                    '@type' => 'MonetaryAmount',
                    'value' => 0,
                    'currency' => 'JPY',
                ),
                'shippingDestination' => array(
                    '@type' => 'DefinedRegion',
                    'addressCountry' => 'JP',
                ),
                'deliveryTime' => array(
                    '@type' => 'ShippingDeliveryTime',
                    'handlingTime' => array(
                        '@type' => 'QuantitativeValue',
                        'minValue' => 0,
                        'maxValue' => 1,
                        'unitCode' => 'DAY',
                    ),
                    'transitTime' => array(
                        '@type' => 'QuantitativeValue',
                        'minValue' => 1,
                        'maxValue' => 3,
                        'unitCode' => 'DAY',
                    ),
                ),
            ),
        ),
    );
    if (!empty($detail['image_url'])) {
        $schema['image'] = array(absolute_site_url($detail['image_url']));
    } else {
        $schema['image'] = array('https://aixec.exbridge.jp/images/aixec.png');
    }
    if (!empty($detail['jan'])) {
        $jan = preg_replace('/\D/', '', $detail['jan']);
        if (strlen($jan) === 13) {
            $schema['gtin13'] = $jan;
        } elseif (strlen($jan) === 14) {
            $schema['gtin14'] = $jan;
        }
    }
    if (isset($detail['sale_price']) && $detail['sale_price'] !== '') {
        $schema['offers']['price'] = (string)(int)$detail['sale_price'];
    }
    $product_schema_json = json_encode($schema, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
}
?><!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?php echo h($page_title); ?></title>
<meta name="description" content="<?php echo h($page_description); ?>">
<link rel="canonical" href="<?php echo h($page_url); ?>">
<meta property="og:title" content="<?php echo h($page_title); ?>">
<meta property="og:description" content="<?php echo h($page_description); ?>">
<meta property="og:type" content="website">
<meta property="og:url" content="<?php echo h($page_url); ?>">
<meta property="og:image" content="<?php echo h($page_image); ?>">
<meta property="og:site_name" content="AIxEC">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="<?php echo h($page_title); ?>">
<meta name="twitter:description" content="<?php echo h($page_description); ?>">
<meta name="twitter:image" content="<?php echo h($page_image); ?>">
<link rel="alternate" type="application/rss+xml" title="AIxSNSニュース RSS" href="https://aixec.exbridge.jp/sns.php?feed">
<?php if ($product_schema_json !== ''): ?>
<script type="application/ld+json"><?php echo $product_schema_json; ?></script>
<?php endif; ?>
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-2528616930208188"
     crossorigin="anonymous"></script>
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
:root{--ink:rgba(0,0,0,.87);--muted:rgba(0,0,0,.54);--line:#e0e0e0;--paper:#fff;--soft:#f5f6f6;--accent:#55c500;--accent-dark:#468c00;--red:#d32f2f}
*{box-sizing:border-box}
body{margin:0;font-family:YakuHanJPs,-apple-system,system-ui,"Segoe UI","Hiragino Kaku Gothic ProN","Hiragino Sans",Meiryo,sans-serif;color:var(--ink);background:var(--soft);letter-spacing:0;line-height:1.8;word-break:break-all;overflow-wrap:break-word}
a{color:inherit}
.top{background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
.wrap{max-width:1100px;margin:0 auto;padding:12px 16px}
.bar{display:flex;align-items:center;justify-content:space-between;gap:18px}
.brand{display:flex;align-items:center;gap:12px;min-width:0}
.brand-link{text-decoration:none}
.mark{width:36px;height:36px;border-radius:4px;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px}
.brand b{display:block;font-size:22px;line-height:1;letter-spacing:0}.brand span{display:block;color:var(--muted);font-size:12px;margin-top:4px;white-space:nowrap}
.brand-ogp{display:block;width:auto;height:42px;object-fit:contain}
.nav{display:flex;gap:10px;align-items:center}.nav a{font-size:13px;color:var(--muted);text-decoration:none;border:1px solid var(--line);background:#fff;border-radius:4px;padding:6px 10px}.nav a:hover{color:var(--accent-dark);border-color:#cfe8c4}
.nav-books-btn{display:none;font-size:13px;font-weight:600;color:var(--accent-dark);text-decoration:none;border:1px solid var(--accent);background:#eaf7d8;border-radius:4px;padding:6px 10px;white-space:nowrap;flex-shrink:0}
.nav-reels-btn{display:none;font-size:13px;font-weight:600;color:#fff;text-decoration:none;border:1px solid #333;background:#222;border-radius:4px;padding:6px 10px;white-space:nowrap;flex-shrink:0}
.nav-aixtube-btn{display:none;font-size:13px;font-weight:600;color:#fff;text-decoration:none;border:1px solid #385b2d;background:#385b2d;border-radius:4px;padding:6px 10px;white-space:nowrap;flex-shrink:0}
.nav-sns-btn{display:none;font-size:13px;font-weight:600;color:#b45309;text-decoration:none;border:1px solid #f59e0b;background:#fffbeb;border-radius:4px;padding:6px 10px;white-space:nowrap;flex-shrink:0}
.nav-mobile{display:none}
.count{border:1px solid var(--line);background:#fff;border-radius:4px;padding:7px 11px;color:var(--muted);font-size:12px;white-space:nowrap}
.hero{max-width:1100px;margin:0 auto;padding:32px 16px 24px}
.hero-inner{display:grid;grid-template-columns:minmax(0,720px) minmax(180px,300px);align-items:center;justify-content:space-between;gap:28px}
.hero h1{font-size:32px;line-height:1.4;margin:0 0 10px;letter-spacing:0;color:var(--ink);font-weight:700}
.lead{color:var(--muted);font-size:15px;line-height:1.8;margin:0;max-width:700px}
.hero-ogp{display:block;width:100%;max-width:300px;height:auto;justify-self:end}
.promo-stack{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:18px;width:100%}.promo-stack a{display:block;line-height:0}.promo-stack img{display:block;width:100%;height:auto}
.discovery{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(240px,.9fr);gap:12px;margin-top:18px;max-width:840px}
.discover-box{background:#fff;border:1px solid var(--line);border-radius:4px;padding:12px;min-width:0}
.discover-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
.discover-head b{font-size:13px;line-height:1.4}.discover-head a{font-size:12px;color:var(--accent-dark);text-decoration:none;white-space:nowrap}.discover-head a:hover{text-decoration:underline}
.genre-links{display:flex;flex-wrap:wrap;gap:7px}.genre-links a{display:inline-flex;align-items:center;min-height:30px;border:1px solid #d8ead0;background:#f7fcf3;color:#315f21;border-radius:999px;padding:4px 10px;font-size:12px;font-weight:700;text-decoration:none;line-height:1.35}.genre-links a:hover{border-color:var(--accent);background:#eef9e7}
.rss-list{display:grid;gap:8px}.rss-item{display:block;text-decoration:none;border-top:1px solid #f0f0f0;padding-top:8px}.rss-item:first-child{border-top:0;padding-top:0}.rss-title{display:block;font-size:13px;font-weight:700;line-height:1.45;color:var(--ink)}.rss-meta{display:block;margin-top:2px;color:var(--muted);font-size:11px}.rss-excerpt{display:block;margin-top:3px;color:var(--muted);font-size:12px;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.search{display:grid;grid-template-columns:1fr 96px;gap:8px;margin-top:20px;max-width:720px}.search input{height:42px;border:1px solid var(--line);border-radius:4px;padding:8px 12px;font-size:14px;background:#fff}.search input:focus{outline:0;border-color:var(--accent)}.search button{height:42px;border:0;border-radius:4px;background:var(--accent);color:#fff;font-size:14px;font-weight:600;padding:0 16px;cursor:pointer}.search button:hover{background:var(--accent-dark)}
.main{max-width:1100px;margin:0 auto;padding:16px 16px 48px}.error{background:#fff;border:1px solid #ffcdd2;color:var(--red);padding:12px;border-radius:4px;margin-bottom:16px}.section-head{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;margin:4px 0 12px}.section-head h2{font-size:20px;line-height:1.4;font-weight:600;margin:0}.section-head p{margin:0;color:var(--muted);font-size:13px}
.detail{background:#fff;border:1px solid var(--line);border-radius:4px;padding:20px;margin-bottom:24px}.maker-badge{display:inline-flex;align-items:center;max-width:100%;border:1px solid #cfe8c4;background:#f2fbef;color:var(--accent-dark);border-radius:4px;padding:3px 8px;font-size:12px;font-weight:700;margin:0 0 8px}.detail h1{font-size:24px;line-height:1.5;font-weight:600;margin:0 0 12px}.detail h1 a{text-decoration:none}.detail h1 a:hover{text-decoration:underline}.detail-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(180px,280px);gap:18px;align-items:start}.detail-image{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:4px;background:#fff}.facts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:14px 0}.fact{background:#fafafa;border:1px solid var(--line);border-radius:4px;padding:10px;min-width:0}.fact small{display:block;color:var(--muted);font-size:12px}.fact strong{display:block;margin-top:4px;overflow-wrap:anywhere}.buy-fact{display:flex;align-items:center}.buy-badge{display:inline-flex;align-items:center;justify-content:center;width:100%;min-height:40px;padding:6px 10px;border-radius:4px;background:var(--accent);color:#fff;text-decoration:none;font-weight:700;text-align:center;line-height:1.35}.buy-badge:hover{background:var(--accent-dark)}.desc{max-height:840px;overflow:auto;border-top:1px solid var(--line);padding-top:16px;line-height:1.8;color:var(--ink)}.affiliate-fallback{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:18px}.affiliate-box{border:1px solid var(--line);background:#fff;padding:12px;border-radius:4px}.affiliate-box p{margin:0 0 10px}.affiliate-box a{font-weight:700}.affiliate-box span{font-size:13px;color:var(--muted)}.affiliate-banner{display:block;line-height:0}.affiliate-banner img{display:block;width:100%;height:auto}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.card{display:flex;flex-direction:column;text-decoration:none;background:#fff;border:1px solid var(--line);border-radius:4px;min-height:204px;overflow:hidden}.card:hover{box-shadow:0 2px 4px rgba(0,0,0,.1);border-color:#c8c8c8}.thumb{height:46px;background:#fff;border-bottom:1px solid var(--line);color:var(--muted);display:flex;align-items:center;justify-content:space-between;padding:0 12px}.thumb b{font-size:14px;color:var(--accent)}.thumb span{font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:170px}.card-body{padding:16px;display:flex;flex-direction:column;flex:1}.card h3{font-size:15px;line-height:1.65;font-weight:600;margin:0 0 10px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}.row{display:flex;gap:6px;flex-wrap:wrap;color:var(--muted);font-size:12px}.chip{border:1px solid var(--line);background:#fafafa;border-radius:3px;padding:2px 6px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.price{font-size:18px;font-weight:700;margin-top:auto;padding-top:13px;color:#bf0000}.sku{font-family:SFMono-Regular,Consolas,"Liberation Mono",Menlo,monospace;color:var(--muted);font-size:11px;line-height:1.5;margin-top:7px;overflow-wrap:anywhere}.empty{background:#fff;border:1px solid var(--line);border-radius:4px;padding:34px;text-align:center;color:var(--muted)}
.detail-btn-row{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px}
.detail-copy-btn{display:inline-flex;align-items:center;gap:6px;background:none;border:1px solid var(--line);border-radius:4px;padding:8px 14px;font-size:13px;color:var(--muted);cursor:pointer;transition:all .15s}
.detail-copy-btn:hover{border-color:var(--accent);color:var(--accent-dark)}
.detail-copy-btn.copied{border-color:#22c55e;color:#22c55e}
.detail-x-btn{display:inline-flex;align-items:center;gap:5px;background:#000;color:#fff;border:1px solid #000;border-radius:4px;padding:8px 14px;font-size:13px;text-decoration:none;transition:background .15s}
.detail-x-btn:hover{background:#333;border-color:#333}
#copy-toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%);background:#111;color:#fff;padding:10px 22px;border-radius:20px;font-size:13px;opacity:0;pointer-events:none;transition:opacity .3s;z-index:999}
#copy-toast.show{opacity:1}
@media(max-width:1020px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.facts{grid-template-columns:repeat(2,minmax(0,1fr))}.hero-inner{grid-template-columns:minmax(0,1fr) 220px}.discovery{grid-template-columns:1fr;max-width:720px}}
@media(max-width:640px){.wrap,.hero,.main{padding-left:14px;padding-right:14px}.bar{align-items:center;gap:8px}.nav{display:none}.nav-mobile{display:flex;gap:8px;margin-top:10px;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}.nav-mobile::-webkit-scrollbar{display:none}.nav-mobile .nav-books-btn,.nav-mobile .nav-reels-btn,.nav-mobile .nav-aixtube-btn,.nav-mobile .nav-sns-btn{display:block}.count{display:none}.hero{padding-top:22px}.hero-inner,.detail-layout{grid-template-columns:1fr}.hero h1{font-size:27px}.hero-ogp{max-width:220px;justify-self:start}.discovery{grid-template-columns:1fr}.genre-links{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}.genre-links::-webkit-scrollbar{display:none}.genre-links a{white-space:nowrap;flex-shrink:0}.search{grid-template-columns:1fr}.search button{width:100%}.grid{grid-template-columns:1fr}.facts,.promo-stack,.affiliate-fallback{grid-template-columns:1fr}.brand span{white-space:normal}.brand-ogp{height:34px}}
</style>
</head>
<body>
<header class="top"><div class="wrap">
  <div class="bar">
    <a class="brand brand-link" href="/"><div class="mark">AIx</div><div><b>AIxEC</b><span>AI x EC product intelligence</span></div><img class="brand-ogp" src="/images/aixec.png" alt="AIxEC"></a>
    <?php
    $reels_url = '/reels.php';
    if ($q !== '') {
        $reels_url = '/reels.php?q=' . urlencode($q);
    }
    ?>
    <nav class="nav"><a href="/">商品検索</a><a href="/market_ranking.php">人気商品</a><a href="/books_ranking.php">人気書籍</a><a href="<?php echo h($aixtube_url); ?>">AIxTube</a><a href="<?php echo h($reels_url); ?>">▶ 商品動画</a><a href="/sns.php">🔔 新着情報</a></nav>
  </div>
  <div class="nav-mobile">
    <a class="nav-books-btn" href="/market_ranking.php">人気商品</a>
    <a class="nav-books-btn" href="/books_ranking.php">人気書籍</a>
    <a class="nav-aixtube-btn" href="<?php echo h($aixtube_url); ?>">AIxTube</a>
    <a class="nav-reels-btn" href="<?php echo h($reels_url); ?>">▶ 動画</a>
    <a class="nav-sns-btn" href="/sns.php">🔔 新着情報</a>
  </div>
</div></header>
<?php include __DIR__ . '/vwork_promo.php'; ?>
<section class="hero">
  <div class="hero-inner">
  <div>
    <h1>ECサイト運営を、AIで加速する。AIxEC</h1>
    <p class="lead">AIxECは、AIが自律的に商品情報を整理し、商品紹介動画の自動生成などを行う、AI駆動型の商品メディアです。楽天・Amazonなどへの購入導線と連携し、検索や動画から商品との出会いを広げます。</p>
    <div class="discovery" aria-label="商品ジャンルとAIxSNS最新情報">
      <section class="discover-box">
        <div class="discover-head">
          <b>ジャンルから探す</b>
          <a href="/index.php">すべての商品</a>
        </div>
        <div class="genre-links">
          <?php foreach ($genre_links as $genre): ?>
          <a href="/index.php?q=<?php echo urlencode($genre['q']); ?>"><?php echo h($genre['label']); ?></a>
          <?php endforeach; ?>
        </div>
      </section>
      <section class="discover-box">
        <div class="discover-head">
          <b>AIxSNS 最新情報</b>
          <a href="/sns.php?feed">RSS</a>
        </div>
        <div class="rss-list">
          <?php if ($sns_latest): ?>
            <?php foreach ($sns_latest as $post): ?>
            <a class="rss-item" href="/sns.php?id=<?php echo (int)($post['id'] ?? 0); ?>">
              <span class="rss-title"><?php echo h(post_title_from_content($post['content'] ?? '')); ?></span>
              <span class="rss-meta"><?php echo h(short_date($post['created_at'] ?? '')); ?><?php echo !empty($post['author']) ? ' / ' . h($post['author']) : ''; ?></span>
              <span class="rss-excerpt"><?php echo h(text_excerpt($post['content'] ?? '', 88)); ?></span>
            </a>
            <?php endforeach; ?>
          <?php else: ?>
            <a class="rss-item" href="/sns.php"><span class="rss-title">AIxSNSを見る</span><span class="rss-excerpt">AIxEC関連の更新情報を確認できます。</span></a>
          <?php endif; ?>
        </div>
      </section>
    </div>
    <form class="search" method="get" action="/index.php">
      <input name="q" value="<?php echo h($q); ?>" placeholder="商品名・メーカー・型番・JAN・ASINで検索">
      <button type="submit">検索</button>
    </form>
  </div>
  <img class="hero-ogp" src="/images/aixec.png" alt="AIxEC">
  </div>
    <div class="promo-stack">
      <a href="<?php echo h($amazon_click_url); ?>" target="_blank" rel="nofollow sponsored noopener">
        <img src="/images/amazon.png" alt="Amazon">
      </a>
      <a href="<?php echo h($rakuten_click_url); ?>" target="_blank" rel="nofollow sponsored noopener">
        <img src="/images/rakuten.png" alt="Rakuten">
      </a>
      <a href="<?php echo h($xdirect_banner_url); ?>" target="_blank" rel="noopener noreferrer">
        <img src="/images/xdirect.png" alt="XDirect">
      </a>
    </div>
  </div>
</section>
<main class="main">
<?php if ($error): ?><div class="error"><?php echo h($error); ?></div><?php endif; ?>
<?php if ($detail): ?>
<section class="detail">
  <?php $xdirect_url = xdirect_product_url($detail); ?>
  <div class="maker-badge"><?php echo h($detail['maker']); ?></div>
  <h1><?php if ($xdirect_url !== ''): ?><a href="<?php echo h($xdirect_url); ?>" target="_blank" rel="noopener noreferrer"><?php echo h($detail['name']); ?></a><?php else: ?><?php echo h($detail['name']); ?><?php endif; ?></h1>
  <div class="detail-layout">
  <div>
  <div class="facts">
    <div class="fact"><small>型番</small><strong><?php echo h(display_model_number($detail['model_number'])); ?></strong></div>
    <?php if (!empty($detail['jan'])): ?><div class="fact"><small>JAN</small><strong><?php echo h($detail['jan']); ?></strong></div><?php endif; ?>
    <div class="fact"><small>価格</small><strong><?php echo h(yen($detail['sale_price'])); ?></strong></div>
    <?php if ($xdirect_url !== ''): ?><div class="fact buy-fact"><a class="buy-badge" href="<?php echo h($xdirect_url); ?>" target="_blank" rel="noopener noreferrer">X-Directで購入する</a></div><?php endif; ?>
  </div>
  <div class="detail-btn-row">
    <button class="detail-copy-btn" onclick="copyProduct()">📋 コピー</button>
    <a class="detail-x-btn" id="detail-x-btn" href="#" target="_blank" rel="noopener">𝕏 Xに投稿</a>
  </div>
  <?php if (!empty($detail_description)): ?><div class="desc"><?php echo $detail_description; ?></div><?php endif; ?>
  <?php if (!empty($detail['book_description_ai'])): ?>
  <div class="desc" style="margin-top:16px;"><?php echo $detail['book_description_ai']; ?></div>
  <?php elseif (!$has_market_ai_description): ?>
  <div style="margin-top:16px;"><a href="/lp.php?id=<?php echo (int)($detail['id'] ?? 0); ?>" style="display:inline-block;padding:10px 18px;background:#55c500;color:#fff;border-radius:6px;text-decoration:none;font-size:14px;font-weight:700;">詳細説明をAI生成する →</a></div>
  <?php endif; ?>
  <?php $video_id = (int)($detail['id'] ?? 0); if ($video_id && file_exists(__DIR__ . '/video/' . $video_id . '.mp4')): ?>
  <div class="product-video" style="margin:16px 0;max-width:288px;"><video controls playsinline poster="<?php echo h(!empty($detail['image_url']) ? $detail['image_url'] : ''); ?>" style="width:100%;border-radius:6px;"><source src="/video/<?php echo $video_id; ?>.mp4" type="video/mp4"></video></div>
  <?php endif; ?>
  <?php if ($show_amazon_detail_affiliate || $show_rakuten_detail_affiliate): ?>
    <div class="affiliate-fallback">
      <?php if ($show_amazon_detail_affiliate): ?>
      <div class="affiliate-box">
        <p><a href="<?php echo h($amazon_click_url); ?>" target="_blank" rel="nofollow sponsored noopener">Amazonでも商品を探してみてください →</a><br><span>上のリンクをクリックしてAmazonのサイトでも商品をご確認ください。価格を比べてみて、お得な方でご購入ください。</span></p>
        <a class="affiliate-banner" href="<?php echo h($amazon_click_url); ?>" target="_blank" rel="nofollow sponsored noopener"><img src="/images/amazon.png" alt="Amazon"></a>
      </div>
      <?php endif; ?>
      <?php if ($show_rakuten_detail_affiliate): ?>
      <div class="affiliate-box">
        <p><a href="<?php echo h($rakuten_click_url); ?>" target="_blank" rel="nofollow sponsored noopener">楽天市場でも商品を探してみてください →</a><br><span>上のリンクをクリックして楽天市場でも商品をご確認ください。価格を比べてみて、お得な方でご購入ください。</span></p>
        <a class="affiliate-banner" href="<?php echo h($rakuten_click_url); ?>" target="_blank" rel="nofollow sponsored noopener"><img src="/images/rakuten.png" alt="Rakuten"></a>
      </div>
      <?php endif; ?>
    </div>
  <?php endif; ?>
  </div>
  <img class="detail-image" src="<?php echo h(!empty($detail['image_url']) ? $detail['image_url'] : '/images/noimage.jpg'); ?>" alt="<?php echo h($detail['name']); ?>">
  </div>
</section>
<?php endif; ?>
<?php if (!$items): ?>
  <div class="empty">商品が見つかりませんでした。</div>
<?php else: ?>
  <div class="section-head">
    <h2><?php echo $q !== '' ? '検索結果' : '商品一覧'; ?></h2>
    <p><?php echo $q !== '' ? 'キーワード: '.h($q) : '新着順に表示'; ?></p>
  </div>
  <div class="grid">
  <?php foreach ($items as $item): ?>
    <a class="card" href="/product/<?php echo urlencode(make_slug($item['maker'] ?? '', $item['model_number'] ?? '', $item['name'] ?? '') ?: $item['id']); ?><?php echo $q !== '' ? '?q='.urlencode($q) : ''; ?>">
      <div class="thumb"><img src="<?php echo h(!empty($item['image_url']) ? $item['image_url'] : '/images/noimage.jpg'); ?>" alt="<?php echo h($item['name']); ?>" style="height:36px;width:54px;object-fit:contain"><span><?php echo h($item['maker']); ?></span></div>
      <div class="card-body">
      <h3><?php echo h($item['name']); ?></h3>
      <div class="row"><span class="chip"><?php echo h($item['maker']); ?></span><span class="chip"><?php echo h($item['model_number']); ?></span></div>
      <div class="price"><?php echo h(yen($item['sale_price'])); ?></div>
      <div class="sku"><?php echo h($item['internal_sku']); ?></div>
      </div>
    </a>
  <?php endforeach; ?>
  </div>
<?php endif; ?>
</main>
<footer style="text-align:center;padding:24px 16px;font-size:12px;color:rgba(0,0,0,.45);">
  <a href="/return-policy.php" style="color:inherit;">返品ポリシー</a>　｜　<a href="/tokusho.php" style="color:inherit;">特定商取引法に基づく表記</a>
</footer>
<?php if ($detail): ?>
<script>
var _product = <?php echo json_encode(array(
    'name' => isset($detail['name']) ? $detail['name'] : '',
    'description' => copy_text_description($detail_description),
    'url' => $page_url,
), JSON_UNESCAPED_UNICODE); ?>;
function buildCopyText() {
    var lines = [_product.name, _product.url];
    if (_product.description) lines.push(_product.description);
    return lines.join('\n');
}
function copyProduct() {
    navigator.clipboard.writeText(buildCopyText()).then(function() {
        var btn = document.querySelector('.detail-copy-btn');
        btn.textContent = '☑ コピー済';
        btn.classList.add('copied');
        setTimeout(function() { btn.textContent = '📋 コピー'; btn.classList.remove('copied'); }, 2000);
        showToast('コピーしました');
    });
}
(function() {
    var xBtn = document.getElementById('detail-x-btn');
    if (xBtn) {
        xBtn.href = 'https://twitter.com/intent/tweet?text=' + encodeURIComponent(buildCopyText());
    }
})();
function showToast(msg) {
    var t = document.getElementById('copy-toast');
    t.textContent = msg; t.classList.add('show');
    setTimeout(function() { t.classList.remove('show'); }, 2000);
}
</script>
<?php endif; ?>
<div id="copy-toast">コピーしました</div>
</body>
</html>
