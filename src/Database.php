<?php

final class Database
{
    private static $pdo;

    public static function connect($root)
    {
        if (self::$pdo instanceof PDO) {
            return self::$pdo;
        }

        $dbPath = getenv('AIXEC_DB');
        if (!$dbPath) {
            $dbPath = $root . '/storage/aixec.sqlite';
        } elseif ($dbPath[0] !== '/') {
            $dbPath = $root . '/' . $dbPath;
        }

        $dir = dirname($dbPath);
        if (!is_dir($dir)) {
            mkdir($dir, 0775, true);
        }

        self::$pdo = new PDO('sqlite:' . $dbPath);
        self::$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        self::$pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
        self::$pdo->exec('PRAGMA foreign_keys = ON');

        return self::$pdo;
    }
}
