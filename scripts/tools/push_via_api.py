#!/usr/bin/env python3
"""当 git 协议被网络阻断时，用 GitHub REST API 推送本地提交（兜底工具）。

适用场景：`github.com:443` 不通（git push 超时），但 `api.github.com` 可直连。
原理：逐提交调用 git data API —— blob → tree → commit → update-ref，
完整保留提交信息（message / author / committer / date）与目录结构。

用法：
    python push_via_api.py <token> <base_sha> <commit_sha> [<commit_sha> ...]

    # base_sha 为远端当前 HEAD，例如：
    git ls-remote https://github.com/<owner>/<repo>.git main

依赖：httpx（后端虚拟环境里已有）。脚本内不硬编码任何凭据，token 从参数传入。
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from typing import Any

import httpx

OWNER = "huigezhi"
REPO = "AI_Knowledge_Compiler"
BASE = f"https://api.github.com/repos/{OWNER}/{REPO}"

HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "Content-Type": "application/json",
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


def git_bytes(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def changed_files(commit: str) -> list[tuple[str, str]]:
    out = git("diff", "--name-status", "--no-renames", f"{commit}~1", commit).strip()
    return [(line.split("\t")[0].strip(), line.split("\t")[1].strip()) for line in out.splitlines() if "\t" in line]


def file_mode(commit: str, path: str) -> str:
    out = git("ls-tree", commit, "--", path).strip()
    return out.split()[0] if out else "100644"


def commit_meta(commit: str) -> dict[str, Any]:
    fmt = "%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI%x00%B"
    p = git("show", "-s", f"--format={fmt}", commit).split("\x00")
    return {
        "author_name": p[0], "author_email": p[1], "author_date": p[2],
        "committer_name": p[3], "committer_email": p[4], "committer_date": p[5],
        "message": p[6],
    }


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 2
    token, base_sha, commits = argv[1], argv[2], argv[3:]
    headers = {**HEADERS, "Authorization": f"Bearer {token}"}

    with httpx.Client(trust_env=False, timeout=60.0) as client:  # 直连，绕过环境代理
        probe = client.get(BASE, headers=headers)
        if probe.status_code != 200:
            print(f"API 不可达: {probe.status_code} {probe.text[:200]}")
            return 1
        print(f"repo ok: {probe.json()['full_name']}")

        current = base_sha
        tree_base = client.get(f"{BASE}/git/commits/{base_sha}", headers=headers).json()["tree"]["sha"]

        for commit in commits:
            meta = commit_meta(commit)
            entries: list[dict[str, Any]] = []
            for status, path in changed_files(commit):
                if status == "D":
                    entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
                    continue
                content = git_bytes("cat-file", "blob", f"{commit}:{path}")
                r = client.post(
                    f"{BASE}/git/blobs", headers=headers,
                    json={"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
                )
                if r.status_code not in (200, 201):
                    print(f"blob 失败 {path}: {r.status_code} {r.text[:200]}")
                    return 1
                entries.append({"path": path, "mode": file_mode(commit, path), "type": "blob", "sha": r.json()["sha"]})

            r = client.post(f"{BASE}/git/trees", headers=headers, json={"base_tree": tree_base, "tree": entries})
            if r.status_code not in (200, 201):
                print(f"tree 失败: {r.status_code} {r.text[:200]}")
                return 1
            new_tree = r.json()["sha"]

            r = client.post(f"{BASE}/git/commits", headers=headers, json={
                "message": meta["message"], "tree": new_tree, "parents": [current],
                "author": {"name": meta["author_name"], "email": meta["author_email"], "date": meta["author_date"]},
                "committer": {"name": meta["committer_name"], "email": meta["committer_email"], "date": meta["committer_date"]},
            })
            if r.status_code not in (200, 201):
                print(f"commit 失败: {r.status_code} {r.text[:200]}")
                return 1
            created = r.json()
            current, tree_base = created["sha"], created["tree"]["sha"]
            print(f"pushed {commit[:7]} -> {current[:7]}  ({len(entries)} files)")

        r = client.patch(f"{BASE}/git/refs/heads/main", headers=headers, json={"sha": current})
        if r.status_code != 200:
            print(f"ref 更新失败: {r.status_code} {r.text[:200]}")
            return 1
        print(json.dumps({"new_head": current}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
