# Project AIxEC (アイゼック) Specification

## 1. プロジェクト概要
**AIxEC（アイゼック）** は、20年の歴史を持つドメイン `exdirect.net` の資産を最大限に活用し、AI駆動でEC運営とアフィリエイト収益化を自動化する、VS Code完結型のハイブリッド型商品管理システム（PIM）である。

## 2. コア・コンセプト
*   **VS Code Centric:** すべての操作（データ登録、CSV生成、サイト反映）をVS Codeのターミナルまたはエディタ内から実行する。
*   **AI Driven:** RTX 3090のローカルLLM（Ollama等）を使い、商品情報の収集、リライト、SEO最適化を自動化。
*   **Hybrid Revenue:** 自社EC（おちゃのこネット）、Amazonでの販売と、アフィリエイトへの誘導を動的に切り替える。
*   **No-Touch Backoffice:** 「売らずに稼ぐ（アフィリエイト）」へシフトし、在庫・発送リスクを最小化。

## 3. システムアーキテクチャ
*   **Master DB:** SQLite（JANコードを主キーとした商品マスタ）。
*   **Backend:** PHP 軽量フレームワーク（Slim / Flight 等）。
*   **Frontend:** `exdirect.net` は比較サイト形式へ。将来的に **JPYC決済** 機能を搭載予定。
*   **Hardware:** NVIDIA RTX 3090 搭載サーバー。

## 4. 主要機能（ワークフロー）
### ① インプット（収集）
*   URLをトリガーに商品情報をスクレイピングし、AIが情報を構造化してDBへ登録。
*   ネットで見つけた情報を即座に取り込むインターフェースの構築。

### ② プロセッシング（管理）
*   仕入れ値に基づいた各チャネルの販売価格自動計算。
*   AIによる商品説明、レビュー、比較コンテンツの生成。
*   Amazon/楽天/自社サイトのリンクを網羅した比較データの生成。

### ③ アウトプット（連携）
*   **おちゃのこネット:** CSV生成 ＆ Playwrightによる自動アップロード。
*   **Amazon:** セラーセントラル用CSV生成、またはAPIによる同期。

## 5. 技術スタック
*   **Language:** PHP 8.3+, Python 3.10+
*   **Framework:** Slim Framework (PHP), FastAPI (Python - オプション)
*   **Automation:** Playwright
*   **Database:** SQLite
*   **Payment:** JPYC (Future Work)

## 6. AI (Codex/x402) への指示
あなたは私の副操縦士です。このファイルを常に参照し、私の指示に応じてPHPによるAPI構築、Pythonによる自動化スクリプト、およびDB設計をサポートしてください。
