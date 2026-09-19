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
import os
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


def resolve_commits(base_sha: str) -> list[str]:
    """确定要推送的本地提交列表。

    ``base_sha`` 是**远端**的 sha，本地对象库里通常不存在（由 API 生成），
    因此 ``rev-list base..HEAD`` 会失败；此时退回上次推送时记录的本地上次 HEAD。
    """
    try:
        return git("rev-list", "--reverse", f"{base_sha}..HEAD").split()
    except subprocess.CalledProcessError:
        state = read_state()
        local_base = state.get("local_head")
        if local_base:
            try:
                commits = git("rev-list", "--reverse", f"{local_base}..HEAD").split()
                print(f"base sha 本地不存在，改用上次推送的本地上次 HEAD {local_base[:7]}")
                return commits
            except subprocess.CalledProcessError:
                pass
        raise SystemExit(
            "无法自动确定待推送提交：base sha 不在本地对象库中。\n"
            "请显式传入要推送的本地 commit sha 列表，或用 --local-base 指定本地上次推送的 HEAD。"
        ) from None


def state_path() -> str:
    return os.path.join(git("rev-parse", "--git-dir").strip(), "akc-push-state.json")


def read_state() -> dict[str, str]:
    try:
        with open(state_path(), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def write_state(local_head: str, remote_head: str) -> None:
    with open(state_path(), "w", encoding="utf-8") as handle:
        json.dump({"local_head": local_head, "remote_head": remote_head}, handle, indent=2)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    token, base_sha = argv[1], argv[2]
    commits = argv[3:]
    if not commits or commits[0] == "--local-base":
        local_base = commits[1] if commits else None
        if local_base:
            commits = git("rev-list", "--reverse", f"{local_base}..HEAD").split()
        else:
            commits = resolve_commits(base_sha)
        print(f"自动展开待推送提交 {len(commits)} 个")

    if not commits:
        # 曾经踩过的坑：提交列表为空时仍然写状态文件，于是状态跑到真实远端之前，
        # 之后每次都算出「0 个待推送」却打印成功 —— 提交被静默吞掉。
        # 这里直接停下并保持状态不变，让问题可见。
        print(
            "没有待推送的提交。若你本地确实有未推送的提交，通常是状态文件超前了，\n"
            "请显式指定：push_via_api.py <token> <base_sha> --local-base <本地上次已推送的 HEAD>"
        )
        return 0

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

        # force=True：允许在历史被重写/补推时覆盖远端引用（此仓库无协作者，安全）
        r = client.patch(
            f"{BASE}/git/refs/heads/main",
            headers=headers,
            json={"sha": current, "force": True},
        )
        if r.status_code != 200:
            print(f"ref 更新失败: {r.status_code} {r.text[:200]}")
            return 1

        # 回读确认：光看 200 不够，引用可能没真正落上去
        check = client.get(f"{BASE}/git/ref/heads/main", headers=headers)
        landed = check.json().get("object", {}).get("sha") if check.status_code == 200 else None
        if landed != current:
            print(f"推送后校验失败：远端 refs/heads/main={landed}，期望 {current}")
            return 1

        write_state(git("rev-parse", "HEAD").strip(), current)
        print(json.dumps({"new_head": current, "pushed": len(commits)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
