# Codex git push 手順

このサーバのCodexからGitHubへpushする時は、毎回まずSSH agentを確認する。
失敗してからやり直すのではなく、以下の成功手順を使う。

## 1. 使えるSSH agentを探す

```bash
for s in /tmp/ssh-*/agent.*; do
  echo "-- $s"
  SSH_AUTH_SOCK="$s" ssh-add -L 2>&1 | head -2
  SSH_AUTH_SOCK="$s" ssh -o BatchMode=yes -T git@github.com 2>&1 | head -3
done
```

成功例:

```text
Hi katsushi2441! You've successfully authenticated, but GitHub does not provide shell access.
```

この表示が出た `SSH_AUTH_SOCK` を使う。

2026-06-07時点で成功した例:

```bash
SSH_AUTH_SOCK=/tmp/ssh-XXXXXX1CDlcM/agent.3865478
```

別のagentでも同じ鍵が入っていれば使える。

## 2. pushする

```bash
cd /home/kojima/exdirect/aixec
SSH_AUTH_SOCK=/tmp/ssh-XXXXXX1CDlcM/agent.3865478 git push origin main
```

`SSH_AUTH_SOCK` はその時点で成功確認できたものに置き換える。

## 3. 先にremoteを確認する

```bash
git remote -v
```

期待:

```text
origin  git@github.com:katsushi2441/aixec.git (fetch)
origin  git@github.com:katsushi2441/aixec.git (push)
```

HTTPSになっていたら直す。

```bash
git remote set-url origin git@github.com:katsushi2441/aixec.git
```

## 4. SSH認証失敗時

以下が出た場合:

```text
Permission denied (publickey)
```

原因はだいたい `SSH_AUTH_SOCK` 未指定。
もう一度「1. 使えるSSH agentを探す」からやる。

`ssh-add -L` が以下なら、そのagentは使えない。

```text
The agent has no identities.
Could not open a connection to your authentication agent.
```

## 5. pullだけならHTTPSで逃がせる

SSH認証がない時でも、公開repoの取得だけなら以下で可能。

```bash
git fetch https://github.com/katsushi2441/aixec.git main
git rebase FETCH_HEAD
```

ただしpushはSSH認証が必要。

## 6. 今回の実績

2026-06-07、以下でpush成功。

```bash
SSH_AUTH_SOCK=/tmp/ssh-XXXXXX1CDlcM/agent.3865478 git push origin main
```

成功コミット:

```text
2615b6a Answer AIxEC migration questions
```
