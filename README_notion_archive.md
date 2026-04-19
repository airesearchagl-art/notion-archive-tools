# Claude Code → Notion 自動アーカイブツール

## 概要

Claude Codeのチャット履歴を、NotionのデータベースページにアーカイブするPythonスクリプトです。

### アーカイブ構造

```
Notionページ「PDFツール」の本文
│
├── (既存コンテンツ)
│
├── ━━━━━━━━━━━━━━━━━━
├── 📅 2026-04-19 14:30 開発セッション
├── セッションファイル: abc123.jsonl
│
├── ▶ 📝 ダイジェスト（トグル）
│   ├── 👤 ユーザー: ○○の機能を実装して...
│   ├── 🤖 Claude: 実装しました。以下が...
│   └── [コードブロック]
│
└── ▶ 📋 詳細ログ（トグル）
    ├── ━━━ 👤 ユーザー [14:30:15] ━━━
    ├── (全文)
    ├── ━━━ 🤖 Claude [14:30:45] ━━━
    └── (全文 + コードブロック)
```

## セットアップ

### 1. 必要な環境

- Python 3.9以上
- `requests` ライブラリ

```bash
pip install requests
```

### 2. Notion Integration の設定

1. [Notion Integrations](https://www.notion.so/my-integrations) にアクセス
2. APIトークンをコピー

### 3. Notion データベースIDの取得

```
https://www.notion.so/xxxxxxxx?v=yyyyyyyy
                    ^^^^^^^^
                    これがデータベースID
```

### 4. インテグレーションの接続

1. Notionでデータベースページを開く
2. 右上の `•••` → `接続` → インテグレーションを追加

### 5. 環境変数の設定

```powershell
[System.Environment]::SetEnvironmentVariable("NOTION_API_TOKEN", "ntn_xxxxxxxxxxxx", "User")
[System.Environment]::SetEnvironmentVariable("NOTION_DATABASE_ID", "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", "User")
```

## 使い方

```bash
# セッション一覧を確認
python archive_to_notion.py --list

# ドライラン（確認のみ）
python archive_to_notion.py --page "PDFツール" --session latest --dry-run

# 最新セッションをアーカイブ
python archive_to_notion.py --page "PDFツール" --session latest

# 番号指定
python archive_to_notion.py --page "PDFツール" --session 3

# ファイル直接指定
python archive_to_notion.py --page "PDFツール" --session "C:\Users\username\.claude\projects\my-project\abc123.jsonl"
```

## トラブルシューティング

### 「データベースにページが見つかりません」
- Notionインテグレーションがデータベースに接続されているか確認

### 「セッションファイルが見つかりません」
- `~/.claude/projects/` にJSONLファイルがあるか確認
- Windows: `C:\Users\<username>\.claude\projects\`

### Notion APIエラー 401
- APIトークンが正しいか確認

### Notion APIエラー 403
- インテグレーションがデータベースに接続されているか確認
- 「Insert content」権限が有効か確認
