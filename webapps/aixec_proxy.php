<?php
// AIxEC public proxy. Keep this file on the web hosting server; SQLite stays on the Linux API server.

$api_base = getenv('AIXEC_API_BASE');
if (!$api_base) {
    $api_base = 'http://exbridge.ddns.net:8081';
}

$path = isset($_GET['path']) ? $_GET['path'] : 'health';
$path = '/' . implode('/', array_map('rawurlencode', explode('/', ltrim($path, '/'))));
$url = rtrim($api_base, '/') . $path;
if (!empty($_SERVER['QUERY_STRING'])) {
    $query = $_GET;
    unset($query['path']);
    if ($query) {
        $url .= '?' . http_build_query($query);
    }
}

$method = $_SERVER['REQUEST_METHOD'];
$body = file_get_contents('php://input');

$ch = curl_init($url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $method);
$timeout = (strpos($path, '/lp/') === 0) ? 210 : 60;
curl_setopt($ch, CURLOPT_TIMEOUT, $timeout);
if ($method !== 'GET' && $body !== false) {
    curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
}
if (!empty($_SERVER['CONTENT_TYPE'])) {
    curl_setopt($ch, CURLOPT_HTTPHEADER, array('Content-Type: ' . $_SERVER['CONTENT_TYPE']));
}

$response = curl_exec($ch);
$status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$error = curl_error($ch);
curl_close($ch);

header('Content-Type: application/json; charset=utf-8');
if ($response === false || $response === '') {
    http_response_code(502);
    echo json_encode(array('ok' => false, 'error' => 'api proxy failed', 'detail' => $error), JSON_UNESCAPED_UNICODE);
    exit;
}
http_response_code($status ? $status : 200);
echo $response;
