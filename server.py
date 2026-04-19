"""
Notion Archive MCP Server
Claude Codeのチャット履歴をNotionにアーカイブするMCPサーバー

セットアップ:
  1. pip install mcp httpx
  2. 環境変数を設定:
     - NOTION_API_TOKEN: Notion Integration トークン
     - NOTION_DATABASE_ID: アプリケーション開発DBのID
  3. Claude Codeに登録（下記README参照）
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"
NOTION_TEXT_LIMIT = 2000

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

mcp = FastMCP("notion_archive_mcp")


def _get_notion_headers() -> dict:
    token = os.environ.get("NOTION_API_TOKEN", "")
    if not token:
        raise ValueError("NOTION_API_TOKEN が設定されていません")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_API_VERSION,
    }


def _get_database_id() -> str:
    db_id = os.environ.get("NOTION_DATABASE_ID", "")
    if not db_id:
        raise ValueError("NOTION_DATABASE_ID が設定されていません")
    return db_id


async def _find_page_id(client: httpx.AsyncClient, page_title: str) -> Optional[str]:
    headers = _get_notion_headers()
    db_id = _get_database_id()

    resp = await client.get(f"{NOTION_BASE_URL}/databases/{db_id}", headers=headers)
    if resp.status_code != 200:
        raise ValueError(f"データベース取得エラー (status={resp.status_code}): {resp.text}")

    db_info = resp.json()
    title_prop = None
    for prop_name, prop_info in db_info.get("properties", {}).items():
        if prop_info.get("type") == "title":
            title_prop = prop_name
            break

    if not title_prop:
        raise ValueError("データベースにタイトルプロパティが見つかりません")

    payload = {
        "filter": {
            "property": title_prop,
            "title": {"contains": page_title}
        }
    }
    resp = await client.post(
        f"{NOTION_BASE_URL}/databases/{db_id}/query",
        headers=headers,
        json=payload,
    )
    if resp.status_code != 200:
        raise ValueError(f"ページ検索エラー (status={resp.status_code}): {resp.text}")

    results = resp.json().get("results", [])
    return results[0]["id"] if results else None


async def _append_blocks(client: httpx.AsyncClient, block_id: str, children: list[dict]) -> None:
    headers = _get_notion_headers()
    url = f"{NOTION_BASE_URL}/blocks/{block_id}/children"

    for i in range(0, len(children), 100):
        batch = children[i:i + 100]
        resp = await client.patch(url, headers=headers, json={"children": batch})
        if resp.status_code != 200:
            raise ValueError(f"ブロック追加エラー (status={resp.status_code}): {resp.text}")


def _find_session_files() -> list[Path]:
    if not CLAUDE_PROJECTS_DIR.exists():
        return []
    files = [f for f in CLAUDE_PROJECTS_DIR.rglob("*.jsonl") if f.name != "history.jsonl"]
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)


def _parse_session(filepath: Path) -> list[dict]:
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
    if entry.get("type") == "message":
        role = entry.get("role", "unknown")
        content = _extract_content(entry.get("message", entry))
        if content:
            return {"role": role, "content": content, "timestamp": entry.get("timestamp", "")}

    if "role" in entry and "content" in entry:
        content = _extract_content(entry)
        if content:
            return {"role": entry["role"], "content": content, "timestamp": entry.get("timestamp", "")}

    if "message" in entry and isinstance(entry["message"], dict):
        msg = entry["message"]
        if "role" in msg:
            content = _extract_content(msg)
            if content:
                return {"role": msg["role"], "content": content, "timestamp": entry.get("timestamp", msg.get("timestamp", ""))}

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
                    parts.append(f"[ツール使用: {item.get('name', 'unknown')}]")
                elif item.get("type") == "tool_result":
                    rc = item.get("content", "")
                    if isinstance(rc, list):
                        rc = "\n".join(r.get("text", "") for r in rc if isinstance(r, dict))
                    parts.append(f"[ツール結果]\n{rc}")
        return "\n".join(parts)
    return str(content) if content else ""


def _rich_text(text: str) -> list[dict]:
    if not text:
        return [{"type": "text", "text": {"content": ""}}]
    return [{"type": "text", "text": {"content": text[i:i + NOTION_TEXT_LIMIT]}}
            for i in range(0, len(text), NOTION_TEXT_LIMIT)]


def _paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text(text)}}


def _code(code: str, language: str = "python") -> dict:
    return {"object": "block", "type": "code", "code": {"rich_text": _rich_text(code), "language": language}}


def _heading2(text: str) -> dict:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich_text(text)}}


def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _toggle(title: str, children: list[dict]) -> dict:
    return {"object": "block", "type": "toggle", "toggle": {"rich_text": _rich_text(title), "children": children}}


def _split_text(text: str, max_len: int = 1800) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks, current = [], ""
    for para in text.split("\n\n"):
        if len(current) + len(para) + 2 > max_len:
            if current:
                chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    result = []
    for c in chunks:
        if len(c) <= max_len:
            result.append(c)
        else:
            for i in range(0, len(c), max_len):
                result.append(c[i:i + max_len])
    return result


def _extract_code_blocks(text: str) -> list[tuple[str, str, str]]:
    parts = []
    last_end = 0
    for match in re.finditer(r'```(\w*)\n(.*?)```', text, re.DOTALL):
        before = text[last_end:match.start()].strip()
        parts.append((before, match.group(2).strip(), match.group(1) or "plain text"))
        last_end = match.end()
    remaining = text[last_end:].strip()
    if remaining:
        parts.append((remaining, "", ""))
    if not parts:
        parts.append((text, "", ""))
    return parts


def _build_content_blocks(text: str) -> list[dict]:
    blocks = []
    lang_map = {"py": "python", "js": "javascript", "ts": "typescript",
                "sh": "bash", "shell": "bash", "yml": "yaml", "": "plain text"}
    for before, code, lang in _extract_code_blocks(text):
        if before:
            for chunk in _split_text(before):
                blocks.append(_paragraph(chunk))
        if code:
            blocks.append(_code(code, lang_map.get(lang, lang)))
    return blocks


def _truncate(text: str, max_len: int) -> str:
    text = re.sub(r'\[ツール使用:.*?\]', '[ツール使用省略]', text)
    text = re.sub(r'\[ツール結果\][\s\S]*?(?=\n\n|\Z)', '[ツール結果省略]', text)
    return text if len(text) <= max_len else text[:max_len] + "..."


def _generate_digest(messages: list[dict]) -> str:
    parts = []
    for msg in messages:
        if msg["role"] in ("user", "human"):
            parts.append(f"👤 ユーザー: {_truncate(msg['content'], 200)}")
        elif msg["role"] == "assistant":
            parts.append(f"🤖 Claude: {_truncate(msg['content'], 300)}")
    return "\n\n".join(parts)


def _build_archive_blocks(messages: list[dict], session_name: str) -> list[dict]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    digest = _generate_digest(messages)
    digest_children = _build_content_blocks(digest) or [_paragraph("（メッセージなし）")]

    detail_children = []
    for msg in messages:
        role_label = "👤 ユーザー" if msg["role"] in ("user", "human") else "🤖 Claude" if msg["role"] == "assistant" else f"📌 {msg['role']}"
        ts = msg.get("timestamp", "")
        ts_str = ""
        if ts:
            try:
                if isinstance(ts, (int, float)):
                    ts_str = f" [{datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts).strftime('%H:%M:%S')}]"
                elif isinstance(ts, str):
                    ts_str = f" [{ts}]"
            except (ValueError, OSError):
                pass
        detail_children.append(_paragraph(f"━━━ {role_label}{ts_str} ━━━"))
        detail_children.extend(_build_content_blocks(msg["content"]))

    if not detail_children:
        detail_children = [_paragraph("（メッセージなし）")]

    blocks = [
        _divider(),
        _heading2(f"📅 {now} 開発セッション"),
        _paragraph(f"セッションファイル: {session_name}"),
    ]

    for label, children in [("📝 ダイジェスト", digest_children), ("📋 詳細ログ", detail_children)]:
        if len(children) <= 100:
            blocks.append(_toggle(f"{label}（{len(messages)}メッセージ）", children))
        else:
            for idx, i in enumerate(range(0, len(children), 95)):
                blocks.append(_toggle(f"{label} Part {idx + 1}", children[i:i + 95]))

    return blocks


class ArchiveInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    page_title: str = Field(..., description="アーカイブ先のNotionページタイトル（部分一致で検索）", min_length=1, max_length=200)
    session: str = Field(default="latest", description="セッション指定。'latest'=最新, 数字=番号, またはJSONLファイルのフルパス")


class ListSessionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=10, description="表示するセッション数", ge=1, le=50)


class ArchiveTextInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    page_title: str = Field(..., description="アーカイブ先のNotionページタイトル", min_length=1, max_length=200)
    title: str = Field(..., description="セッションタイトル", min_length=1, max_length=200)
    digest: str = Field(..., description="ダイジェスト（要約テキスト）")
    detail: str = Field(default="", description="詳細ログ（省略可）")


@mcp.tool(name="notion_archive_session", annotations={"title": "Claude Codeセッションをアーカイブ", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def notion_archive_session(params: ArchiveInput) -> str:
    """Claude CodeのチャットセッションJSONLを読み取り、指定したNotionページにトグル形式でアーカイブします。"""
    files = _find_session_files()
    if not files:
        return "❌ セッションファイルが見つかりません。"

    session_path = None
    if params.session == "latest":
        session_path = files[0]
    elif params.session.isdigit():
        idx = int(params.session) - 1
        if idx < 0 or idx >= len(files):
            return f"❌ セッション番号 {params.session} は範囲外です（1〜{len(files)}）。"
        session_path = files[idx]
    else:
        session_path = Path(params.session)
        if not session_path.exists():
            return f"❌ ファイルが見つかりません: {params.session}"

    messages = _parse_session(session_path)
    if not messages:
        return f"⚠️ メッセージが見つかりません: {session_path.name}"

    user_count = sum(1 for m in messages if m["role"] in ("user", "human"))
    asst_count = sum(1 for m in messages if m["role"] == "assistant")
    blocks = _build_archive_blocks(messages, session_path.name)

    async with httpx.AsyncClient(timeout=60) as client:
        page_id = await _find_page_id(client, params.page_title)
        if not page_id:
            return f"❌ Notionデータベースに '{params.page_title}' が見つかりません。"
        await _append_blocks(client, page_id, blocks)

    return f"✅ アーカイブ完了！\n📄 ページ: {params.page_title}\n📂 セッション: {session_path.name}\n📊 ユーザー: {user_count}件, Claude: {asst_count}件\n📦 Notionブロック: {len(blocks)}件"


@mcp.tool(name="notion_list_sessions", annotations={"title": "Claude Codeセッション一覧", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def notion_list_sessions(params: ListSessionsInput) -> str:
    """Claude Codeのチャットセッション一覧を表示します。"""
    files = _find_session_files()
    if not files:
        return "セッションファイルが見つかりません。"

    lines = ["📁 Claude Code セッション一覧", "=" * 50]
    for i, f in enumerate(files[:params.limit]):
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        size_kb = f.stat().st_size / 1024
        project = f.parent.name
        lines.append(f"  {i + 1:2d}. [{mtime}] {project}/{f.name} ({size_kb:.1f} KB)")

    if len(files) > params.limit:
        lines.append(f"  ... 他 {len(files) - params.limit} ファイル")

    return "\n".join(lines)


@mcp.tool(name="notion_archive_text", annotations={"title": "テキストをNotionにアーカイブ", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def notion_archive_text(params: ArchiveTextInput) -> str:
    """自由テキスト（ダイジェスト+詳細）をNotionページにトグル形式で追記します。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    digest_children = _build_content_blocks(params.digest) or [_paragraph("（内容なし）")]
    detail_children = _build_content_blocks(params.detail) if params.detail else [_paragraph("（詳細なし）")]

    blocks = [_divider(), _heading2(f"📅 {now} {params.title}")]

    for label, children in [("📝 ダイジェスト", digest_children), ("📋 詳細ログ", detail_children)]:
        if len(children) <= 100:
            blocks.append(_toggle(label, children))
        else:
            for idx, i in enumerate(range(0, len(children), 95)):
                blocks.append(_toggle(f"{label} Part {idx + 1}", children[i:i + 95]))

    async with httpx.AsyncClient(timeout=60) as client:
        page_id = await _find_page_id(client, params.page_title)
        if not page_id:
            return f"❌ Notionデータベースに '{params.page_title}' が見つかりません。"
        await _append_blocks(client, page_id, blocks)

    return f"✅ アーカイブ完了！ ページ: {params.page_title} / タイトル: {params.title}"


if __name__ == "__main__":
    mcp.run()
