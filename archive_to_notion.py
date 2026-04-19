"""
Claude Code チャット履歴 → Notion 自動アーカイブスクリプト

使い方:
  python archive_to_notion.py --page "PDFツール" --session latest
  python archive_to_notion.py --page "PDFツール" --session <session_id>
  python archive_to_notion.py --page "PDFツール" --session latest --dry-run

環境変数:
  NOTION_API_TOKEN: Notion Integration トークン
  NOTION_DATABASE_ID: アプリケーション開発DBのID
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

# ============================================================
# 設定
# ============================================================

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Notion APIのrich_textブロックの文字数上限
NOTION_TEXT_LIMIT = 2000


# ============================================================
# Claude Code ログ読み取り
# ============================================================

def find_project_dirs() -> list[Path]:
    """Claude Codeのプロジェクトディレクトリ一覧を取得"""
    if not CLAUDE_PROJECTS_DIR.exists():
        print(f"エラー: {CLAUDE_PROJECTS_DIR} が見つかりません。Claude Codeがインストールされていますか？")
        sys.exit(1)
    
    dirs = []
    for d in CLAUDE_PROJECTS_DIR.iterdir():
        if d.is_dir():
            dirs.append(d)
    return sorted(dirs)


def find_session_files(project_dir: Optional[Path] = None) -> list[Path]:
    """JSONLセッションファイルの一覧を取得"""
    search_dirs = [project_dir] if project_dir else find_project_dirs()
    
    files = []
    for d in search_dirs:
        for f in d.rglob("*.jsonl"):
            if f.name != "history.jsonl":
                files.append(f)
    
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)


def parse_session_jsonl(filepath: Path) -> list[dict]:
    messages = []
    
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            msg = _extract_message(entry)
            if msg:
                messages.append(msg)
    
    return messages


def _extract_message(entry: dict) -> Optional[dict]:
    if "type" in entry and entry["type"] == "message":
        role = entry.get("role", "unknown")
        content = _extract_content(entry.get("message", entry))
        timestamp = entry.get("timestamp", "")
        if content:
            return {"role": role, "content": content, "timestamp": timestamp}
    
    if "role" in entry and "content" in entry:
        role = entry["role"]
        content = _extract_content(entry)
        timestamp = entry.get("timestamp", "")
        if content:
            return {"role": role, "content": content, "timestamp": timestamp}
    
    if "message" in entry and isinstance(entry["message"], dict):
        msg = entry["message"]
        if "role" in msg:
            role = msg["role"]
            content = _extract_content(msg)
            timestamp = entry.get("timestamp", msg.get("timestamp", ""))
            if content:
                return {"role": role, "content": content, "timestamp": timestamp}
    
    return None


def _extract_content(entry: dict) -> str:
    content = entry.get("content", "")
    
    if isinstance(content, str):
        return content
    
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "tool_use":
                    tool_name = item.get("name", "unknown")
                    tool_input = json.dumps(item.get("input", {}), ensure_ascii=False, indent=2)
                    parts.append(f"[ツール使用: {tool_name}]\n{tool_input}")
                elif item.get("type") == "tool_result":
                    result_content = item.get("content", "")
                    if isinstance(result_content, list):
                        texts = [r.get("text", "") for r in result_content if isinstance(r, dict)]
                        result_content = "\n".join(texts)
                    parts.append(f"[ツール結果]\n{result_content}")
        return "\n".join(parts)
    
    return str(content) if content else ""


# ============================================================
# ダイジェスト生成
# ============================================================

def generate_digest(messages: list[dict]) -> str:
    digest_parts = []
    
    for i, msg in enumerate(messages):
        role = msg["role"]
        content = msg["content"]
        
        if role in ("user", "human"):
            summary = _truncate(content, 200)
            digest_parts.append(f"👤 ユーザー: {summary}")
        
        elif role == "assistant":
            summary = _truncate(content, 300)
            digest_parts.append(f"🤖 Claude: {summary}")
    
    return "\n\n".join(digest_parts)


def _truncate(text: str, max_len: int) -> str:
    text = re.sub(r'\[ツール使用:.*?\][\s\S]*?(?=\n\n|\Z)', '[ツール使用省略]', text)
    text = re.sub(r'\[ツール結果\][\s\S]*?(?=\n\n|\Z)', '[ツール結果省略]', text)
    
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


# ============================================================
# Notion API
# ============================================================

class NotionClient:
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_API_VERSION,
        }
    
    def search_page_in_database(self, database_id: str, page_title: str) -> Optional[str]:
        url = f"{NOTION_BASE_URL}/databases/{database_id}/query"
        
        payload = {
            "filter": {
                "property": "title",
                "title": {"contains": page_title}
            }
        }
        
        resp = requests.post(url, headers=self.headers, json=payload)
        
        if resp.status_code != 200:
            return self._search_page_fallback(database_id, page_title)
        
        data = resp.json()
        results = data.get("results", [])
        
        if not results:
            return self._search_page_fallback(database_id, page_title)
        
        return results[0]["id"]
    
    def _search_page_fallback(self, database_id: str, page_title: str) -> Optional[str]:
        url = f"{NOTION_BASE_URL}/databases/{database_id}"
        resp = requests.get(url, headers=self.headers)
        
        if resp.status_code != 200:
            print(f"エラー: データベース取得に失敗 (status={resp.status_code})")
            print(resp.text)
            return None
        
        db_info = resp.json()
        properties = db_info.get("properties", {})
        
        title_prop_name = None
        for prop_name, prop_info in properties.items():
            if prop_info.get("type") == "title":
                title_prop_name = prop_name
                break
        
        if not title_prop_name:
            print("エラー: データベースにタイトルプロパティが見つかりません")
            return None
        
        url = f"{NOTION_BASE_URL}/databases/{database_id}/query"
        payload = {
            "filter": {
                "property": title_prop_name,
                "title": {"contains": page_title}
            }
        }
        
        resp = requests.post(url, headers=self.headers, json=payload)
        if resp.status_code != 200:
            print(f"エラー: ページ検索に失敗 (status={resp.status_code})")
            print(resp.text)
            return None
        
        results = resp.json().get("results", [])
        if not results:
            print(f"エラー: '{page_title}' に一致するページが見つかりません")
            return None
        
        return results[0]["id"]
    
    def append_blocks(self, block_id: str, children: list[dict]) -> bool:
        url = f"{NOTION_BASE_URL}/blocks/{block_id}/children"
        
        for i in range(0, len(children), 100):
            batch = children[i:i + 100]
            payload = {"children": batch}
            
            resp = requests.patch(url, headers=self.headers, json=payload)
            if resp.status_code != 200:
                print(f"エラー: ブロック追加に失敗 (status={resp.status_code})")
                print(resp.text)
                return False
        
        return True


# ============================================================
# Notionブロック構築
# ============================================================

def _rich_text(text: str) -> list[dict]:
    if not text:
        return [{"type": "text", "text": {"content": ""}}]
    
    chunks = []
    for i in range(0, len(text), NOTION_TEXT_LIMIT):
        chunks.append({
            "type": "text",
            "text": {"content": text[i:i + NOTION_TEXT_LIMIT]}
        })
    return chunks


def _paragraph_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich_text(text)}
    }


def _code_block(code: str, language: str = "python") -> dict:
    return {
        "object": "block",
        "type": "code",
        "code": {"rich_text": _rich_text(code), "language": language}
    }


def _heading2_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": _rich_text(text)}
    }


def _divider_block() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _toggle_block(title: str, children: list[dict]) -> dict:
    return {
        "object": "block",
        "type": "toggle",
        "toggle": {"rich_text": _rich_text(title), "children": children}
    }


def extract_code_blocks(text: str) -> list[tuple[str, str, str]]:
    pattern = r'```(\w*)\n(.*?)```'
    
    parts = []
    last_end = 0
    
    for match in re.finditer(pattern, text, re.DOTALL):
        before = text[last_end:match.start()].strip()
        language = match.group(1) or "plain text"
        code = match.group(2).strip()
        parts.append((before, code, language))
        last_end = match.end()
    
    remaining = text[last_end:].strip()
    if remaining:
        parts.append((remaining, "", ""))
    
    if not parts:
        parts.append((text, "", ""))
    
    return parts


def build_content_blocks(text: str, role: str) -> list[dict]:
    blocks = []
    
    parts = extract_code_blocks(text)
    
    for before_text, code, language in parts:
        if before_text:
            for chunk in _split_text(before_text, 1800):
                blocks.append(_paragraph_block(chunk))
        
        if code:
            lang_map = {
                "py": "python", "js": "javascript", "ts": "typescript",
                "sh": "bash", "shell": "bash", "yml": "yaml", "": "plain text",
            }
            notion_lang = lang_map.get(language, language)
            blocks.append(_code_block(code, notion_lang))
    
    return blocks


def _split_text(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    
    chunks = []
    paragraphs = text.split("\n\n")
    current = ""
    
    for para in paragraphs:
        if len(current) + len(para) + 2 > max_len:
            if current:
                chunks.append(current)
            current = para
        else:
            current = current + "\n\n" + para if current else para
    
    if current:
        chunks.append(current)
    
    result = []
    for chunk in chunks:
        if len(chunk) <= max_len:
            result.append(chunk)
        else:
            for i in range(0, len(chunk), max_len):
                result.append(chunk[i:i + max_len])
    
    return result


def build_archive_blocks(messages: list[dict], session_file: str) -> list[dict]:
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d %H:%M")
    
    digest_text = generate_digest(messages)
    digest_children = build_content_blocks(digest_text, "digest")
    
    if not digest_children:
        digest_children = [_paragraph_block("（メッセージなし）")]
    
    detail_children = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        timestamp = msg.get("timestamp", "")
        
        if role in ("user", "human"):
            role_label = "👤 ユーザー"
        elif role == "assistant":
            role_label = "🤖 Claude"
        else:
            role_label = f"📌 {role}"
        
        ts_str = ""
        if timestamp:
            try:
                if isinstance(timestamp, (int, float)):
                    ts_str = datetime.fromtimestamp(timestamp / 1000 if timestamp > 1e12 else timestamp).strftime(" [%H:%M:%S]")
                elif isinstance(timestamp, str):
                    ts_str = f" [{timestamp}]"
            except (ValueError, OSError):
                pass
        
        detail_children.append(_paragraph_block(f"━━━ {role_label}{ts_str} ━━━"))
        content_blocks = build_content_blocks(content, role)
        detail_children.extend(content_blocks)
    
    if not detail_children:
        detail_children = [_paragraph_block("（メッセージなし）")]
    
    detail_toggles = []
    if len(detail_children) <= 100:
        detail_toggles.append(_toggle_block(f"📋 詳細ログ（{len(messages)}メッセージ）", detail_children))
    else:
        for idx, i in enumerate(range(0, len(detail_children), 95)):
            batch = detail_children[i:i + 95]
            detail_toggles.append(_toggle_block(f"📋 詳細ログ Part {idx + 1}", batch))
    
    blocks = [
        _divider_block(),
        _heading2_block(f"📅 {date_str} 開発セッション"),
        _paragraph_block(f"セッションファイル: {session_file}"),
    ]
    
    if len(digest_children) <= 100:
        blocks.append(_toggle_block("📝 ダイジェスト", digest_children))
    else:
        for idx, i in enumerate(range(0, len(digest_children), 95)):
            batch = digest_children[i:i + 95]
            blocks.append(_toggle_block(f"📝 ダイジェスト Part {idx + 1}", batch))
    
    blocks.extend(detail_toggles)
    
    return blocks


# ============================================================
# メイン処理
# ============================================================

def list_sessions():
    files = find_session_files()
    
    if not files:
        print("セッションファイルが見つかりません。")
        return
    
    print("\n📁 利用可能なセッション:")
    print("-" * 80)
    
    for i, f in enumerate(files[:20]):
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        size = f.stat().st_size
        project = f.parent.name
        print(f"  {i + 1:2d}. [{mtime.strftime('%Y-%m-%d %H:%M')}] {project}/{f.name} ({size:,} bytes)")
    
    if len(files) > 20:
        print(f"  ... 他 {len(files) - 20} ファイル")


def main():
    parser = argparse.ArgumentParser(
        description="Claude Code チャット履歴を Notion にアーカイブ",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python archive_to_notion.py --list
  python archive_to_notion.py --page "PDFツール" --session latest
  python archive_to_notion.py --page "PDFツール" --session latest --dry-run
  python archive_to_notion.py --page "PDFツール" --session /path/to/session.jsonl
        """
    )
    
    parser.add_argument("--page", type=str, help="Notionページのタイトル（部分一致）")
    parser.add_argument("--session", type=str, default="latest",
                        help="セッション指定: 'latest', 番号, またはファイルパス")
    parser.add_argument("--list", action="store_true", help="セッション一覧を表示")
    parser.add_argument("--dry-run", action="store_true", help="Notionに送信せず内容を確認")
    parser.add_argument("--token", type=str, help="Notion APIトークン")
    parser.add_argument("--database-id", type=str, help="Notion DB ID")
    
    args = parser.parse_args()
    
    if args.list:
        list_sessions()
        return
    
    if not args.page:
        parser.error("--page でNotionページ名を指定してください。")
    
    token = args.token or os.environ.get("NOTION_API_TOKEN")
    if not token:
        print("エラー: NOTION_API_TOKEN を環境変数に設定するか、--token で指定してください。")
        sys.exit(1)
    
    database_id = args.database_id or os.environ.get("NOTION_DATABASE_ID")
    if not database_id:
        print("エラー: NOTION_DATABASE_ID を環境変数に設定するか、--database-id で指定してください。")
        sys.exit(1)
    
    session_path = None
    
    if args.session == "latest":
        files = find_session_files()
        if not files:
            print("エラー: セッションファイルが見つかりません。")
            sys.exit(1)
        session_path = files[0]
        print(f"📂 最新セッション: {session_path}")
    
    elif args.session.isdigit():
        files = find_session_files()
        idx = int(args.session) - 1
        if idx < 0 or idx >= len(files):
            print(f"エラー: セッション番号 {args.session} は範囲外です。")
            sys.exit(1)
        session_path = files[idx]
    
    else:
        session_path = Path(args.session)
        if not session_path.exists():
            print(f"エラー: ファイルが見つかりません: {session_path}")
            sys.exit(1)
    
    print(f"📖 セッション読み取り中: {session_path.name}")
    messages = parse_session_jsonl(session_path)
    
    if not messages:
        print("⚠️  メッセージが見つかりませんでした。")
        sys.exit(1)
    
    user_msgs = sum(1 for m in messages if m["role"] in ("user", "human"))
    asst_msgs = sum(1 for m in messages if m["role"] == "assistant")
    print(f"   ユーザー: {user_msgs}件, Claude: {asst_msgs}件, 合計: {len(messages)}件")
    
    blocks = build_archive_blocks(messages, session_path.name)
    print(f"📦 Notionブロック数: {len(blocks)}")
    
    if args.dry_run:
        print("\n🔍 ドライラン — Notionには送信しません")
        digest = generate_digest(messages)
        print("\n📝 ダイジェスト:")
        print(digest[:2000])
        print("\n✅ ドライラン完了。")
        return
    
    client = NotionClient(token)
    
    print(f"🔍 Notionページ検索: '{args.page}'")
    page_id = client.search_page_in_database(database_id, args.page)
    
    if not page_id:
        print(f"エラー: Notionデータベースに '{args.page}' が見つかりません。")
        sys.exit(1)
    
    print(f"📤 Notionに送信中...")
    success = client.append_blocks(page_id, blocks)
    
    if success:
        print("✅ アーカイブ完了！")
    else:
        print("❌ アーカイブに失敗しました。")
        sys.exit(1)


if __name__ == "__main__":
    main()
