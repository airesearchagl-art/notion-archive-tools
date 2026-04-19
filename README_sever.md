# Notion Archive MCP Server

Claude Codeのチャット履歴をNotionに自動アーカイブするMCPサーバーです。

## できること

Claude Codeの会話中に、以下のように指示するだけでNotionにアーカイブが残ります：

```
「このセッションをNotionの'PDFツール'にアーカイブして」
```

### 3つのツール

| ツール | 用途 |
|---|---|
| `notion_list_sessions` | Claude Codeのセッション一覧を表示 |
| `notion_archive_session` | JSONLログを読み取ってNotionに自動送信 |
| `notion_archive_text` | Claudeが会話をまとめて直接Notionに書き込み |

### Notionに追記される構造

```
📅 2026-04-19 14:30 開発セッション
├── ▶ 📝 ダイジェスト（トグル）
│   ├── 👤 ユーザー: ○○の機能を実装して...
│   ├── 🤖 Claude: 実装しました...
│   └── [コードブロック]
└── ▶ 📋 詳細ログ（トグル）
    ├── ━━━ 👤 ユーザー [14:30:15] ━━━
    ├── (全文)
    └── ━━━ 🤖 Claude [14:30:45] ━━━
        └── (全文 + コードブロック)
```

## セットアップ

### 1. 依存パッケージのインストール

```bash
pip install "mcp[cli]" httpx pydantic
```

### 2. Notion側の準備

1. [Notion Integrations](https://www.notion.so/my-integrations) でAPIトークンを取得
2. NotionデータベースのURLからIDを取得：
   ```
   https://www.notion.so/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx?v=...
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                        これがデータベースID（32文字）
   ```
3. データベースに右上 `•••` → `接続` でインテグレーションを追加

### 3. Claude Codeへの登録

#### 方法A: CLIコマンド（推奨）

```bash
claude mcp add notion-archive \
  -e NOTION_API_TOKEN=ntn_xxxxxxxxxxxx \
  -e NOTION_DATABASE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
  -- python C:\path\to\server.py
```

#### 方法B: .mcp.json を直接編集

```json
{
  "mcpServers": {
    "notion-archive": {
      "command": "python",
      "args": ["C:\\Users\\username\\notion_archive_mcp\\server.py"],
      "env": {
        "NOTION_API_TOKEN": "ntn_xxxxxxxxxxxx",
        "NOTION_DATABASE_ID": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
      }
    }
  }
}
```

> **Windowsの注意点**: `python` が見つからない場合は `cmd` ラッパーを使用：
> ```json
> { "command": "cmd", "args": ["/c", "python", "C:\\path\\to\\server.py"] }
> ```

#### 方法C: グローバル設定（全プロジェクトで利用）

`~/.claude.json` に方法Bと同じJSON構造を追記。

### 4. 接続確認

Claude Codeで `/mcp` を実行し、`notion-archive: connected` と表示されればOKです。

## 使い方

### パターン1: セッションログを自動アーカイブ

```
このセッションをNotionの「PDFツール」にアーカイブして
```

### パターン2: Claudeに会話をまとめさせてアーカイブ

```
この会話のダイジェストと詳細をまとめて、Notionの「履歴タイムライン」にアーカイブして
```

### パターン3: セッション一覧を確認してから選択

```
Claude Codeのセッション一覧を見せて
→ 3番のセッションをNotionの「VE系統図」にアーカイブして
```

## トラブルシューティング

| 症状 | 原因と対処 |
|---|---|
| `/mcp` で表示されない | `.mcp.json` の場所やJSON形式を確認。Claude Codeを再起動。 |
| `NOTION_API_TOKEN が設定されていません` | `.mcp.json` の `env` にトークンが正しく記載されているか確認 |
| ページが見つからない | Notionインテグレーションがデータベースに接続されているか確認 |
| セッションが見つからない | `~/.claude/projects/` にJSONLファイルがあるか確認 |
| ブロック追加エラー 403 | インテグレーションの「Insert content」権限を確認 |
