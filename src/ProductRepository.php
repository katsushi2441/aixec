<?php

final class ProductRepository
{
    private $pdo;

    public function __construct(PDO $pdo)
    {
        $this->pdo = $pdo;
    }

    public function listProducts($limit, $offset)
    {
        $stmt = $this->pdo->prepare('SELECT * FROM products ORDER BY updated_at DESC LIMIT :limit OFFSET :offset');
        $stmt->bindValue(':limit', $limit, PDO::PARAM_INT);
        $stmt->bindValue(':offset', $offset, PDO::PARAM_INT);
        $stmt->execute();
        return $stmt->fetchAll();
    }

    public function findByJan($jan)
    {
        $stmt = $this->pdo->prepare('SELECT * FROM products WHERE jan = :jan');
        $stmt->execute(array(':jan' => $jan));
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findById($id)
    {
        $stmt = $this->pdo->prepare('SELECT * FROM products WHERE id = :id');
        $stmt->execute(array(':id' => (int)$id));
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findBySlug($slug)
    {
        $stmt = $this->pdo->query('SELECT * FROM products');
        foreach ($stmt->fetchAll() as $row) {
            if (self::toSlug($row['maker'] ?? '', $row['model_number'] ?? '', $row['name'] ?? '') === $slug) {
                return $row;
            }
        }
        return null;
    }

    public static function toSlug($maker, $model, $name = '')
    {
        if (preg_match('/^([^-]+)-(.+)$/', $model, $m)) {
            if ($name === '' || mb_strpos($name, $m[1]) === false) {
                $model = $m[2];
            }
        }
        $s = trim($maker) . '-' . trim($model);
        $s = preg_replace('/[\s\/\(\)\[\]\\\\\.]+/u', '-', $s);
        $s = preg_replace('/-+/', '-', $s);
        return trim($s, '-');
    }

    public function upsert(array $data)
    {
        if (empty($data['jan']) || empty($data['name'])) {
            throw new InvalidArgumentException('jan and name are required');
        }

        $fields = array(
            'jan', 'sku', 'name', 'maker', 'model_number', 'source_url', 'description',
            'cost_price', 'sale_price', 'amazon_url', 'rakuten_url', 'own_store_url',
            'affiliate_priority', 'status'
        );

        $values = array();
        foreach ($fields as $field) {
            $values[$field] = array_key_exists($field, $data) ? $data[$field] : null;
        }
        if (!$values['affiliate_priority']) {
            $values['affiliate_priority'] = 'auto';
        }
        if (!$values['status']) {
            $values['status'] = 'draft';
        }

        if ($this->findByJan($values['jan'])) {
            $sql = 'UPDATE products SET
                sku = :sku,
                name = :name,
                maker = :maker,
                model_number = :model_number,
                source_url = :source_url,
                description = :description,
                cost_price = :cost_price,
                sale_price = :sale_price,
                amazon_url = :amazon_url,
                rakuten_url = :rakuten_url,
                own_store_url = :own_store_url,
                affiliate_priority = :affiliate_priority,
                status = :status,
                updated_at = CURRENT_TIMESTAMP
                WHERE jan = :jan';
        } else {
            $sql = 'INSERT INTO products
                (jan, sku, name, maker, model_number, source_url, description, cost_price, sale_price,
                 amazon_url, rakuten_url, own_store_url, affiliate_priority, status, created_at, updated_at)
                VALUES
                (:jan, :sku, :name, :maker, :model_number, :source_url, :description, :cost_price, :sale_price,
                 :amazon_url, :rakuten_url, :own_store_url, :affiliate_priority, :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)';
        }

        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($values);
        return $this->findByJan($values['jan']);
    }
}
