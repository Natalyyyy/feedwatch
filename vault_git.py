#!/usr/bin/env python3
"""Serialized vault transactions. Stdlib only; never continue without the lock."""
import argparse
from contextlib import contextmanager
import fcntl
import os
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


def git(vault, *args, check=True):
    result = subprocess.run(['git', '-C', str(vault), *args], capture_output=True, text=True, timeout=60)
    if check and result.returncode:
        raise RuntimeError('git '+args[0]+': '+result.stderr[-1200:])
    return result


def pull(vault):
    for kind in ('rebase-merge', 'rebase-apply'):
        name = git(vault, 'rev-parse', '--git-path', kind).stdout.strip()
        path = Path(name)
        if not path.is_absolute(): path = Path(vault)/path
        if path.is_dir():
            git(vault, 'rebase', '--abort')
            break
    git(vault, 'fetch', '--quiet', 'origin', 'main')
    try:
        git(vault, '-c', 'rebase.autoStash=true', 'rebase', '--quiet', 'origin/main')
    except RuntimeError:
        git(vault, 'rebase', '--abort', check=False)
        raise


def publish(vault, message, paths):
    if not paths: raise ValueError('explicit output paths required')
    for name in paths:
        path = Path(name)
        if path.is_absolute() or '..' in path.parts: raise ValueError('output paths must be vault-relative')
    # --only prevents an unrelated staged draft from entering this commit.
    git(vault, 'add', '--', *paths)
    changes = git(vault, 'diff', '--cached', '--quiet', '--', *paths, check=False)
    if changes.returncode == 1:
        git(vault, 'commit', '--quiet', '--only', '-m', message, '--', *paths)
    elif changes.returncode:
        raise RuntimeError('cannot inspect staged output')
    for attempt in range(3):
        result = git(vault, 'push', '--quiet', 'origin', 'main', check=False)
        if result.returncode == 0: return
        if attempt < 2: pull(vault)
    raise RuntimeError('push failed after 3 attempts; local commit retained')


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
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print('ERROR: vault transaction: '+str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__': sys.exit(main())
