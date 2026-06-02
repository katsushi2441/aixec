<?php
function lp_api($path, $params = array()) {
    $p = array_merge(array('path' => ltrim($path, '/')), $params);
    $url = 'https://aixec.exbridge.jp/api.php?' . http_build_query($p);
    $ch = curl_init($url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 15);
    $body = curl_exec($ch);
    curl_close($ch);
    $d = json_decode($body, true);
    return is_array($d) ? $d : array();
}

$id = isset($_GET['id']) ? (int)$_GET['id'] : 0;
if (!$id) { http_response_code(400); exit('id が必要です'); }

// ポーリング用チェック
if (!empty($_GET['check'])) {
    header('Content-Type: application/json');
    $res = lp_api('lp/status', array('id' => $id));
    echo json_encode(array('ready' => !empty($res['ready'])));
    exit;
}

// 商品情報取得（スラグ取得用）
$res = lp_api('products/' . $id);
$item = $res['item'] ?? array();
if (empty($item)) { http_response_code(404); exit('商品が見つかりません'); }

// スラグ生成
$maker  = $item['maker'] ?? '';
$model  = $item['model_number'] ?? ($item['jan'] ?? '');
$slug   = mb_strtolower(trim($maker) . '-' . trim($model), 'UTF-8');
$slug   = preg_replace('/\s+/', '-', $slug);
$product_url = '/product/' . rawurlencode($slug ?: $id);

// AI説明が既にあれば商品ページへリダイレクト
if (!empty($item['book_description_ai'])) {
    header('Location: ' . $product_url);
    exit;
}

// 生成ステータス確認 & 必要なら生成開始
$status_res = lp_api('lp/generate', array('id' => $id));
if (!empty($status_res['status']) && $status_res['status'] === 'ready') {
    header('Location: ' . $product_url);
    exit;
}

// 生成中ローディング画面
$name = htmlspecialchars($item['name'] ?? '', ENT_QUOTES, 'UTF-8');
?><!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>詳細説明を生成中... | AIxEC</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,system-ui,"Hiragino Sans",sans-serif;background:#f5f6f6;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px}
.box{background:#fff;border-radius:8px;padding:40px 32px;max-width:480px;width:100%;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,.08)}
.spinner{width:40px;height:40px;border:4px solid #e0e0e0;border-top-color:#55c500;border-radius:50%;animation:spin .8s linear infinite;margin:0 auto 24px}
@keyframes spin{to{transform:rotate(360deg)}}
h2{font-size:17px;font-weight:700;margin-bottom:8px;line-height:1.5}
.name{color:#333;font-size:14px;margin-bottom:8px}
.note{font-size:13px;color:rgba(0,0,0,.5);margin-top:8px}
</style>
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-2528616930208188"
     crossorigin="anonymous"></script>
</head>
<body>
<div class="box">
  <div class="spinner"></div>
  <h2>詳細説明を生成中です</h2>
  <?php if ($name): ?><p class="name"><?= $name ?></p><?php endif; ?>
  <p class="note">AIが書籍の詳しい説明・考察を作成しています。<br>そのままお待ちください。</p>
</div>
<script>
(function(){
  var id = <?= $id ?>, url = <?= json_encode($product_url) ?>;
  function check() {
    fetch('/lp.php?id=' + id + '&check=1')
      .then(function(r){ return r.json(); })
      .then(function(d){ d.ready ? (location.href = url) : setTimeout(check, 3000); })
      .catch(function(){ setTimeout(check, 5000); });
  }
  setTimeout(check, 3000);
})();
</script>
</body>
</html>
