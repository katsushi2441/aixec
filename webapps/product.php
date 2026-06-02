<?php
$slug = isset($_GET['slug']) ? trim($_GET['slug']) : (isset($_GET['id']) ? trim($_GET['id']) : '');
$_GET['id'] = $slug;
include __DIR__ . '/index.php';
