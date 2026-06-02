<?php

final class ImportJobRepository
{
    private $pdo;

    public function __construct(PDO $pdo)
    {
        $this->pdo = $pdo;
    }

    public function create($sourceUrl, array $payload)
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO import_jobs (source_url, status, raw_payload, created_at, updated_at)
             VALUES (:source_url, :status, :raw_payload, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)'
        );
        $stmt->execute(array(
            ':source_url' => $sourceUrl,
            ':status' => 'queued',
            ':raw_payload' => json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES),
        ));
        return $this->find((int)$this->pdo->lastInsertId());
    }

    public function find($id)
    {
        $stmt = $this->pdo->prepare('SELECT * FROM import_jobs WHERE id = :id');
        $stmt->execute(array(':id' => $id));
        return $stmt->fetch();
    }
}
