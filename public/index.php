<?php

$root = dirname(__DIR__);

require_once $root . '/src/Database.php';
require_once $root . '/src/Response.php';
require_once $root . '/src/ProductRepository.php';
require_once $root . '/src/ImportJobRepository.php';

function request_json()
{
    $raw = file_get_contents('php://input');
    if ($raw === '' || $raw === false) {
        return array();
    }
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        Response::error('invalid json', 400);
        exit;
    }
    return $data;
}

function migrate_if_needed(PDO $pdo, $root)
{
    $exists = $pdo->query("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")->fetch();
    if ($exists) {
        return;
    }
    $schema = file_get_contents($root . '/database/schema.sql');
    $pdo->exec($schema);
}

try {
    $pdo = Database::connect($root);
    migrate_if_needed($pdo, $root);

    $method = $_SERVER['REQUEST_METHOD'];
    $path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
    $path = rtrim($path, '/');
    if ($path === '') {
        $path = '/';
    }

    if ($method === 'GET' && ($path === '/' || $path === '/health')) {
        Response::json(array(
            'ok' => true,
            'name' => 'AIxEC',
            'php' => PHP_VERSION,
            'time' => date('c'),
        ));
        exit;
    }

    $products = new ProductRepository($pdo);

    if ($method === 'GET' && $path === '/products') {
        $limit = isset($_GET['limit']) ? max(1, min(200, (int)$_GET['limit'])) : 50;
        $offset = isset($_GET['offset']) ? max(0, (int)$_GET['offset']) : 0;
        Response::json(array('ok' => true, 'items' => $products->listProducts($limit, $offset)));
        exit;
    }

    if ($method === 'GET' && preg_match('#^/products/([^/]+)$#', $path, $m)) {
        $key = urldecode($m[1]);
        $item = null;
        if (ctype_digit($key)) {
            $item = $products->findById((int)$key);
        }
        if (!$item) {
            $item = $products->findByJan($key);
        }
        if (!$item) {
            $item = $products->findBySlug($key);
        }
        if (!$item) {
            Response::error('product not found', 404);
            exit;
        }
        Response::json(array('ok' => true, 'item' => $item));
        exit;
    }

    if ($method === 'POST' && $path === '/products') {
        $item = $products->upsert(request_json());
        Response::json(array('ok' => true, 'item' => $item), 201);
        exit;
    }

    if ($method === 'POST' && $path === '/import/url') {
        $data = request_json();
        if (empty($data['url'])) {
            Response::error('url is required', 400);
            exit;
        }
        $jobs = new ImportJobRepository($pdo);
        $job = $jobs->create($data['url'], $data);
        Response::json(array('ok' => true, 'job' => $job), 202);
        exit;
    }

    Response::error('not found', 404);
} catch (InvalidArgumentException $e) {
    Response::error($e->getMessage(), 400);
} catch (Exception $e) {
    Response::error($e->getMessage(), 500);
}
