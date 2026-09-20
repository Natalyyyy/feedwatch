#!/usr/bin/env python3
"""Serialized vault transactions. Stdlib only; never continue without the lock."""
import argparse
from contextlib import contextmanager
import fcntl
import os
import stat
import tempfile
from pathlib import Path
import subprocess
import sys
import time


@contextmanager
def locked(path=None, wait=None):
    path = Path(path or os.environ.get('VAULT_LOCK_PATH', str(Path.home()/'.vault-git.lock')))
    wait = float(wait if wait is not None else os.environ.get('VAULT_LOCK_WAIT_SEC', '120'))
    inherited = os.environ.get('VAULT_LOCK_FD', '')
    if inherited.isdigit():
        try:
            current = os.fstat(int(inherited))
            expected = path.stat()
            matches = (current.st_dev, current.st_ino) == (expected.st_dev, expected.st_ino)
        except OSError:
            matches = False
        if matches:
            yield int(inherited)
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        deadline = time.monotonic()+max(0, wait)
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('vault lock timeout; operation was not run')
                time.sleep(min(.05, max(0, deadline-time.monotonic())))
        try:
            yield handle.fileno()
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def git(vault, *args, check=True, binary=False):
    # -- is not sufficient: Git still interprets magic/glob pathspecs after it.
    result = subprocess.run(['git', '--literal-pathspecs', '-C', str(vault), *args],
                            capture_output=True, text=not binary,
                            **({} if binary else {'errors': 'surrogateescape'}), timeout=60)
    if check and result.returncode:
        error = os.fsdecode(result.stderr) if binary else result.stderr
        raise RuntimeError('git '+args[0]+': '+error[-1200:])
    return result


def names(vault, *args):
    return {os.fsdecode(name) for name in git(vault, *args, binary=True).stdout.split(b'\0') if name}


def git_path(vault, name):
    path = Path(git(vault, 'rev-parse', '--git-path', name).stdout.rstrip('\n'))
    return path if path.is_absolute() else Path(vault)/path


def rebasing(vault):
    return any(git_path(vault, kind).is_dir() for kind in ('rebase-merge', 'rebase-apply'))


class AutostashConflict(RuntimeError):
    """Unmerged index without a rebase: possibly failed autostash application."""


def check_conflicts(vault):
    if git(vault, 'ls-files', '-u', '-z', binary=True).stdout:
        if not rebasing(vault):
            raise AutostashConflict('unmerged index without rebase (autostash/merge conflict); stash retained')
        raise RuntimeError('rebase conflict; resolve or abort before publishing')


def check_index_lock(vault):
    if os.path.lexists(git_path(vault, 'index.lock')):
        raise RuntimeError('index.lock is occupied; no automatic removal')


@contextmanager
def parent_fd(vault, name):
    """Pin every parent directory, refusing symlinks rather than resolving them."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(vault, flags)
    try:
        for part in Path(name).parts[:-1]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def regular_bytes(name, dir_fd=None):
    # lstat, open without following a link, and fstat also cover replacement
    # between the type check and open. The actual removal uses rename below.
    info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError('automatic quarantine requires a regular file: '+str(name))
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    with os.fdopen(fd, 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise RuntimeError('file type changed: '+str(name))
        return handle.read()


def tree_entries(vault, sha):
    entries = {}
    for record in git(vault, 'ls-tree', '-r', '-z', sha, binary=True).stdout.split(b'\0'):
        if record:
            meta, name = record.split(b'\t', 1)
            mode, kind, oid = meta.split()
            entries[os.fsdecode(name)] = (mode, kind, oid.decode('ascii'))
    return entries


def check_tree_mapping(vault, entries):
    """Detect aliases by filesystem identity, without case/Unicode rewriting.

    Include directory prefixes: Foo/a and foo/b are ambiguous on macOS too.
    Hardlinked distinct paths are conservatively treated as ambiguous.
    """
    seen, visited = {}, set()
    for name in entries:
        parts = Path(name).parts
        for length in range(1, len(parts)+1):
            prefix = str(Path(*parts[:length]))
            if prefix in visited:
                continue
            visited.add(prefix)
            try:
                info = (vault/prefix).lstat()
            except FileNotFoundError:
                continue
            except NotADirectoryError as exc:
                raise RuntimeError('file blocks a remote directory: '+prefix) from exc
            if length < len(parts) and stat.S_ISLNK(info.st_mode):
                raise RuntimeError('symlink parent blocks remote path: '+prefix)
            identity = info.st_dev, info.st_ino
            if identity in seen and seen[identity] != prefix:
                raise RuntimeError('ambiguous filesystem mapping: '+repr((seen[identity], prefix)))
            seen[identity] = prefix


def check_new_tree_mapping(vault, entries):
    """Probe absent names too, using the filesystem rather than Unicode rules.

    This temporary namespace contains empty placeholders only, outside the vault.
    It is needed only for the exceptional collision-repair path.
    """
    with tempfile.TemporaryDirectory(prefix='.vault-git-map-', dir=vault.parent) as folder:
        probe = Path(folder)
        created = set()
        for name in entries:
            parts = Path(name).parts
            for length in range(1, len(parts)+1):
                prefix = str(Path(*parts[:length]))
                if prefix in created:
                    continue
                try:
                    if length < len(parts):
                        (probe/prefix).mkdir()
                    else:
                        with (probe/prefix).open('xb'):
                            pass
                except FileExistsError as exc:
                    raise RuntimeError('ambiguous remote tree on this filesystem: '+repr(name)) from exc
                created.add(prefix)


@contextmanager
def quarantine_collisions(vault, sha):
    entries = tree_entries(vault, sha)
    # Include ignored untracked files: Git can otherwise overwrite these silently.
    untracked = names(vault, 'ls-files', '--others', '-z')
    identities = set()
    for name in untracked:
        try:
            info = (vault/name).lstat()
        except FileNotFoundError:
            continue
        identities.add((info.st_dev, info.st_ino))
    candidates = []
    check_tree_mapping(vault, entries)
    for name, (mode, kind, oid) in entries.items():
        try:
            info = (vault/name).lstat()
        except FileNotFoundError:
            continue
        if (info.st_dev, info.st_ino) not in identities:
            continue
        if mode not in (b'100644', b'100755') or kind != b'blob' or not stat.S_ISREG(info.st_mode):
            raise RuntimeError('untracked collision is not a regular file: '+name)
        expected = git(vault, 'cat-file', 'blob', oid, binary=True).stdout
        with parent_fd(vault, name) as fd:
            if regular_bytes(Path(name).name, fd) != expected:
                raise RuntimeError('untracked file differs from fetched commit: '+name)
        candidates.append((name, expected))

    if candidates:
        check_new_tree_mapping(vault, entries)
    backup = None
    moved = []
    try:
        if candidates:
            # A sibling ensures rename is atomic or fails with EXDEV; never copy+unlink.
            backup = Path(tempfile.mkdtemp(prefix='.vault-git-quarantine-', dir=vault.parent))
            print('vault quarantine retained: '+str(backup), file=sys.stderr)
        for name, expected in candidates:
            destination = backup/name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with parent_fd(vault, name) as fd:
                os.rename(Path(name).name, destination, src_dir_fd=fd)
            moved.append((name, destination))
            if regular_bytes(destination) != expected:
                raise RuntimeError('file changed during quarantine; backup retained: '+str(destination))
        yield
    except BaseException:
        # Never overwrite a newly created path, even when rollback itself races.
        # Keeping the hardlink in quarantine also protects late writes via old FDs.
        for name, destination in reversed(moved):
            try:
                with parent_fd(vault, name) as fd:
                    os.link(destination, Path(name).name, dst_dir_fd=fd, follow_symlinks=False)
            except OSError:
                print('restore skipped; backup retained: '+str(destination), file=sys.stderr)
        raise
    # Intentionally retain backups even on success: a non-cooperating editor may
    # still write through a descriptor opened before rename. Cleanup is manual.


def pull(vault):
    vault = Path(git(vault, 'rev-parse', '--show-toplevel').stdout.rstrip('\n'))
    check_index_lock(vault)
    if rebasing(vault):
        git(vault, 'rebase', '--abort')
    check_conflicts(vault)
    git(vault, 'fetch', '--quiet', 'origin', 'main')
    sha = git(vault, 'rev-parse', '--verify', 'FETCH_HEAD^{commit}').stdout.strip()
    with quarantine_collisions(vault, sha):
        try:
            git(vault, '-c', 'rebase.autoStash=true', 'rebase', '--quiet', sha)
        except (RuntimeError, subprocess.TimeoutExpired):
            if rebasing(vault):
                git(vault, 'rebase', '--abort')
            check_conflicts(vault)
            raise
        # Git may return zero despite an autostash application conflict.
        check_conflicts(vault)


def publish(vault, message, paths):
    if not paths:
        raise ValueError('explicit output paths required')
    vault = Path(vault)
    branch = git(vault, 'symbolic-ref', '--quiet', 'HEAD').stdout.strip()
    if branch != 'refs/heads/main':
        raise RuntimeError('publish requires checked-out main, the branch being pushed')
    paths = [os.fspath(name) for name in paths]
    tracked = names(vault, 'ls-files', '-z')
    known = tracked | set(tree_entries(vault, 'HEAD'))
    for name in paths:
        path = Path(name)
        if (not name or path.is_absolute() or any(part in ('', '.', '..') for part in name.split('/'))
                or name.startswith(':') or any(char in name for char in '*?[]')
                or '.git' in path.parts or (vault/path).is_dir()):
            raise ValueError('exact vault-relative file paths required: '+repr(name))
        try:
            with parent_fd(vault, name):
                pass
        except FileNotFoundError:
            if name not in known:
                raise ValueError('output is not an exact existing or tracked file: '+name)
    if len(set(paths)) != len(paths):
        raise ValueError('duplicate output paths')
    check_index_lock(vault)
    check_conflicts(vault)
    if rebasing(vault):
        raise RuntimeError('unfinished rebase; cannot publish')
    allowed = set(paths)
    staged = names(vault, 'diff', '--cached', '--ita-visible-in-index', '--name-only', '--no-renames', '-z')
    if not staged <= allowed:
        raise RuntimeError('index contains staged files outside explicit output list')
    for name in paths:
        if name not in known and not os.path.lexists(vault/name):
            raise ValueError('output is not an exact existing or tracked file: '+name)
    expected = names(vault, 'diff', 'HEAD', '--ita-visible-in-index', '--name-only', '--no-renames', '-z', '--', *paths)
    expected.update(allowed - tracked)
    # A deletion already staged has no index/worktree entry for git add to match.
    to_add = [name for name in paths if name in tracked or os.path.lexists(vault/name)]
    if to_add:
        git(vault, 'add', '--', *to_add)
    check_conflicts(vault)
    actual = names(vault, 'diff', '--cached', '--ita-visible-in-index', '--name-only', '--no-renames', '-z')
    if actual != expected:
        raise RuntimeError('actual index differs from explicit changed output list; not committing')
    if actual:
        old_head = git(vault, 'rev-parse', 'HEAD').stdout.strip()
        expected_tree = git(vault, 'write-tree').stdout.strip()
        # Preserve both --only and installed validation hooks. A hook can still
        # mutate Git's temporary commit index, so validate the resulting commit.
        git(vault, 'commit', '--quiet', '--only', '-m', message, '--', *paths)
        new_head = git(vault, 'rev-parse', 'HEAD').stdout.strip()
        parents = git(vault, 'rev-list', '--parents', '-n', '1', new_head).stdout.split()[1:]
        committed_tree = git(vault, 'rev-parse', new_head+'^{tree}').stdout.strip()
        committed_paths = names(vault, 'diff-tree', '--no-commit-id', '--name-only',
                                '--no-renames', '-r', '-z', old_head, new_head)
        if parents != [old_head] or committed_tree != expected_tree or committed_paths != expected:
            # CAS cannot overwrite a concurrent ref update. Leave index/worktree
            # untouched; the rejected object is retained in the branch reflog.
            git(vault, 'update-ref', '-m', 'vault: reject unexpected commit contents',
                branch, old_head, new_head)
            raise RuntimeError('commit changed after index validation; branch restored; '
                               'index/worktree retained; rejected commit '+new_head)

    for attempt in range(2):
        result = git(vault, 'push', '--quiet', 'origin', 'main', check=False)
        if result.returncode == 0:
            return
        if attempt == 0:
            pull(vault)
    raise RuntimeError('push failed after 2 attempts; local commit retained')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', required=True)
    sub = parser.add_subparsers(dest='operation', required=True)
    sub.add_parser('pull')
    command = sub.add_parser('acquire-fd')
    command.add_argument('fd', type=int)
    command = sub.add_parser('publish')
    command.add_argument('--message', required=True)
    command.add_argument('paths', nargs='+')
    command = sub.add_parser('run')
    command.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.operation == 'acquire-fd':
            deadline = time.monotonic()+float(os.environ.get('VAULT_LOCK_WAIT_SEC', '120'))
            while True:
                try:
                    fcntl.flock(args.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return 0
                except BlockingIOError:
                    if time.monotonic() >= deadline: raise TimeoutError('vault lock timeout; operation was not run')
                    time.sleep(.05)
        with locked() as fd:
            if args.operation == 'pull': pull(args.vault)
            elif args.operation == 'publish': publish(args.vault, args.message, args.paths)
            else:
                cmd = args.command
                if cmd[:1] == ['--']: cmd = cmd[1:]
                if not cmd: raise ValueError('command required')
                env = dict(os.environ, VAULT_LOCK_FD=str(fd))
                return subprocess.run(cmd, env=env, pass_fds=(fd,)).returncode
        return 0
    except AutostashConflict as exc:
        print('ERROR: vault transaction: '+str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print('ERROR: vault transaction: '+str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__': sys.exit(main())
