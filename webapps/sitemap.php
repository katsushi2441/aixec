<?php
header("Content-Type: application/xml; charset=UTF-8");
$base_url = "https://aixec.exbridge.jp";

function sx($value){
    return htmlspecialchars((string)$value, ENT_XML1 | ENT_COMPAT, 'UTF-8');
}

function sitemap_api_get($path, $params = array()){
    global $base_url;
    $params = array_merge(array('path' => ltrim($path, '/')), $params);
    $url = $base_url . "/api.php?" . http_build_query($params);
    if(function_exists('curl_init')){
        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, 10);
        $body = curl_exec($ch);
        curl_close($ch);
    } else {
        $body = @file_get_contents($url);
    }
    $data = json_decode($body ?: '{}', true);
    return is_array($data) ? $data : array();
}

echo '<?xml version="1.0" encoding="UTF-8"?>';
echo "\n";
echo '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'."\n";

$static_pages = array(
    "index.php"          => "1.0",
    "affiliate.php"      => "0.9",
    "market_ranking.php" => "0.8",
    "books_ranking.php"  => "0.8",
    "reels.php"          => "0.8",
    "aixtube.php"        => "0.8",
    "sns.php"            => "0.8",
);

foreach($static_pages as $file => $priority){
    echo "<url>\n";
    echo "<loc>".sx($base_url."/".$file)."</loc>\n";
    echo "<lastmod>".date('Y-m-d')."</lastmod>\n";
    echo "<priority>".$priority."</priority>\n";
    echo "</url>\n";
}

$posts_res = sitemap_api_get('/posts', array('limit' => 200, 'offset' => 0, 'sitemap' => 1));
if(!empty($posts_res['items']) && is_array($posts_res['items'])){
    foreach($posts_res['items'] as $post){
        if(empty($post['id']) || empty($post['slug'])) continue;
        if(($post['author'] ?? '') === 'register') continue;
        $priority = (strpos((string)($post['kind'] ?? ''), 'kgrowth-') === 0) ? '0.8' : '0.7';
        echo "<url>\n";
        echo "<loc>".sx($base_url."/sns.php?slug=".rawurlencode($post['slug']))."</loc>\n";
        if(!empty($post['updated_at'])){
            echo "<lastmod>".sx(date('Y-m-d', strtotime($post['updated_at'])))."</lastmod>\n";
        } else {
            echo "<lastmod>".date('Y-m-d')."</lastmod>\n";
        }
        echo "<priority>".$priority."</priority>\n";
        echo "</url>\n";
    }
}

$product_file = __DIR__."/data/sitemap_products.json";
if(file_exists($product_file)){
    $products = json_decode(file_get_contents($product_file), true);
    if($products){
        foreach($products as $p){
            if(!isset($p['id'])) { continue; }
            $maker = isset($p['maker']) ? $p['maker'] : '';
            $model = isset($p['model_number']) ? $p['model_number'] : '';
            $s = strtolower(trim($maker).'-'.trim($model));
            $s = preg_replace('/[^a-z0-9]+/', '-', $s);
            $slug = trim($s, '-') ?: $p['id'];
            $url = $base_url."/product/".urlencode($slug);
            echo "<url>\n";
            echo "<loc>".sx($url)."</loc>\n";
            echo "<lastmod>".(isset($p['updated_at']) ? date('Y-m-d', strtotime($p['updated_at'])) : date('Y-m-d'))."</lastmod>\n";
            echo "<priority>0.7</priority>\n";
            echo "</url>\n";
        }
    }
}
echo "</urlset>\n";
