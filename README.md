# notion-archive-tools

Claude CodeのチャットセッションをNotionにアーカイブするツールThe集です。

## ツール一覧

| ファイル | 対象 | 実行方法 |
|---|---|---|
| `archive_to_notion.py` | デスクトップ版Claude / Claude Code（コマンド実行） | `python archive_to_notion.py` |
| `server.py` | Claude Code ターミナル版（MCP連携） | Claude Codeに登録して自然言語で操作 |

---

## archive_to_notion.py — コマンド実行型（デスクトップ版Claude向け）

`~/.claude/projects/` 以下のJSONLセッションログを読み取り、指定したNotionページにアーカイブします。
**セッション終了後にコマンドで手動実行**するスタイルです。

### 特徴
- 依存: `pip install requests` のみ
- `--dry-run` で送信前に内容確認が可能
- `--list` でセッション一覧を表示して番号指定できる

### クイックスタート

```bash
# 環境変数を設定
export NOTION_API_TOKEN=ntn_xxxxxxxxxxxx
export NOTION_DATABASE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# 最新セッションをアーカイブ
python archive_to_notion.py --page "PDFツール" --session latest

# Windowsの場合は notion_archive.bat も利用可能
notion_archive.bat "PDFツール"
```

詳細は [README_notion_archive.md](README_notion_archive.md) を参照。

---

## server.py — MCP連携型（Claude Code ターミナル版向け）

Claude Codeの**MCP（Model Context Protocol）サーバー**として動作します。
Claude Codeの会話中に自然言語で指示するだけでNotionにアーカイブが実行されます。

### 特徴
- 依存: `pip install "mcp[cli]" httpx pydantic`
- Claudeに「アーカイブして」と伝えるだけで動作（コマンド不要）
- `notion_archive_text` ツールでClaudeが会話を要約してそのままNotionに書き込める

### クイックスタート

```bash
# 依存インストール
pip install "mcp[cli]" httpx pydantic

# Claude Codeに登録
claude mcp add notion-archive \
  -e NOTION_API_TOKEN=ntn_xxxxxxxxxxxx \
  -e NOTION_DATABASE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
  -- python /path/to/server.py
```

登録後、Claude Codeで:
```
このセッションをNotionの「PDFツール」にアーカイブして
```
と伝えるだけで自動実行されます。

詳細は [README_sever.md](README_sever.md) を参照。

---

## どちらを使うべきか

| 状況 | 推奨ツール |
|---|---|
| デスクトップ版Claudeを使っている | `archive_to_notion.py` |
| Claude Codeをターミナルで使っている | `server.py`（MCP登録） |
| シンプルに試したい | `archive_to_notion.py` |
| 会話中にシームレスにアーカイブしたい | `server.py` |
| Claudeに要約も任せたい | `server.py`（`notion_archive_text` ツール） |

## 共通セットアップ

1. [Notion Integrations](https://www.notion.so/my-integrations) でAPIトークンを取得
2. NotionデータベースのURLからデータベースIDを取得
3. データベースにインテグレーションを接続（`•••` → `接続`）
4. 環境変数 `NOTION_API_TOKEN` と `NOTION_DATABASE_ID` を設定
