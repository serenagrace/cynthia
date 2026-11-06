import subprocess

from cynthia.utils.version import is_alpha


def git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "HOME": str(repo),
        },
    )


def commit(repo, message):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)


def test_alpha_until_the_running_code_is_pushed_to_master(tmp_path):
    origin, repo = tmp_path / "origin.git", tmp_path / "repo"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(repo))
    (repo / "cynthia").mkdir()
    (repo / "cynthia" / "bot.py").write_text("v1\n")
    git(repo, "checkout", "-qb", "master")
    commit(repo, "release")
    # No origin/master yet: nothing to compare to, so not marked
    assert not is_alpha(repo)
    git(repo, "push", "-q", "origin", "master")
    assert not is_alpha(repo)

    # Edits outside the running code don't count
    (repo / "README.md").write_text("notes\n")
    (repo / "scratch.txt").write_text("x\n")
    assert not is_alpha(repo)

    # Uncommitted code, then a commit only on a development branch
    (repo / "cynthia" / "bot.py").write_text("v2\n")
    assert is_alpha(repo)
    git(repo, "checkout", "-qb", "development")
    commit(repo, "work")
    assert is_alpha(repo)
    git(repo, "push", "-q", "origin", "development")
    assert is_alpha(repo)

    # Released once master contains it
    git(repo, "push", "-q", "origin", "development:master")
    git(repo, "fetch", "-q")
    assert not is_alpha(repo)

    assert not is_alpha(tmp_path / "not-a-checkout")
