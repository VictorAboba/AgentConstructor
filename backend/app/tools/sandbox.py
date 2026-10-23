"""Execution environments for agent tools.

Every run gets its own workspace directory (data/workspaces/<run_id>). File tools work on that
directory directly and refuse paths that escape it. Commands run either:
  * docker — inside a throwaway container with the workspace bind-mounted at /workspace,
             no network by default, CPU/memory/pids limits (recommended);
  * local  — as a subprocess with cwd=workspace and secrets stripped from the environment.
             Path checks still apply to file tools, but shell commands are NOT isolated.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ..db import DATA_DIR

WORKSPACES = DATA_DIR / "workspaces"
SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


@dataclass
class SandboxConfig:
    type: str = "docker"  # docker | local
    image: str = "python:3.12-slim"
    network: bool = False
    memory: str = "1g"
    cpus: float = 1.0
    timeout: int = 60  # default per-command timeout, seconds

    @classmethod
    def from_dict(cls, d: dict | None) -> "SandboxConfig":
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class SandboxError(Exception):
    pass


def docker_available() -> bool:
    return shutil.which("docker") is not None


_docker_status: tuple[float, bool, str] = (0.0, False, "")


async def docker_status() -> tuple[bool, str]:
    """(daemon reachable, detail); cached for 15 s since `docker info` is slow."""
    global _docker_status
    ts, ok, detail = _docker_status
    if time.time() - ts < 15:
        return ok, detail
    if not docker_available():
        ok, detail = False, "docker CLI not found"
    else:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "info", "--format", "{{.ServerVersion}}", stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL)
            out, err = await asyncio.wait_for(proc.communicate(), timeout=8)
            ok = proc.returncode == 0 and bool(out.strip())
            detail = f"docker {_decode(out).strip()}" if ok else "Docker daemon is not running (start Docker Desktop)"
        except (asyncio.TimeoutError, OSError):
            ok, detail = False, "Docker daemon did not respond"
    _docker_status = (time.time(), ok, detail)
    return ok, detail


def _find_bash() -> str | None:
    if sys.platform == "win32":
        for p in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
            if Path(p).exists():
                return p
        found = shutil.which("bash")
        # System32\bash.exe is the WSL launcher: different filesystem view, skip it.
        if found and "system32" not in found.lower():
            return found
        return None
    return shutil.which("bash") or shutil.which("sh")


def _decode(b: bytes) -> str:
    return b.decode("utf-8", errors="replace")


class Sandbox:
    kind = "base"

    def __init__(self, run_id: str, cfg: SandboxConfig):
        self.run_id = run_id
        self.cfg = cfg
        self.root = (WORKSPACES / run_id).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, path: str | None) -> Path:
        p = (path or ".").strip()
        if p.startswith("/workspace"):
            p = p[len("/workspace"):].lstrip("/") or "."
        candidate = Path(p)
        full = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        if full != self.root and self.root not in full.parents:
            raise SandboxError(f"path escapes the workspace: {path}")
        return full

    def seed(self, files: dict[str, str]) -> None:
        for rel, content in (files or {}).items():
            target = self.resolve(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    async def exec(self, command: str, timeout: int | None = None) -> ExecResult:
        raise NotImplementedError

    async def run_python(self, code: str, timeout: int | None = None) -> ExecResult:
        tmp = self.root / ".sandbox"
        tmp.mkdir(exist_ok=True)
        name = f"snippet_{os.urandom(4).hex()}.py"
        (tmp / name).write_text(code, encoding="utf-8")
        try:
            return await self._python_file(f".sandbox/{name}", timeout)
        finally:
            (tmp / name).unlink(missing_ok=True)

    async def _python_file(self, rel: str, timeout: int | None) -> ExecResult:
        return await self.exec(f"python3 {rel}", timeout)

    async def _communicate(self, proc: asyncio.subprocess.Process, timeout: int) -> ExecResult:
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return ExecResult(proc.returncode or 0, _decode(out), _decode(err))
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            return ExecResult(-1, "", f"command timed out after {timeout}s", timed_out=True)


class LocalSandbox(Sandbox):
    kind = "local"

    def _env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not any(m in k.upper() for m in SECRET_MARKERS)}
        env["HOME"] = str(self.root)
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    async def exec(self, command: str, timeout: int | None = None) -> ExecResult:
        timeout = timeout or self.cfg.timeout
        bash = _find_bash()
        if bash:
            proc = await asyncio.create_subprocess_exec(
                bash, "-c", command, cwd=str(self.root), env=self._env(),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL)
        else:
            proc = await asyncio.create_subprocess_shell(
                command, cwd=str(self.root), env=self._env(),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL)
        return await self._communicate(proc, timeout)

    async def _python_file(self, rel: str, timeout: int | None) -> ExecResult:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, rel, cwd=str(self.root), env=self._env(),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL)
        return await self._communicate(proc, timeout or self.cfg.timeout)


class DockerSandbox(Sandbox):
    kind = "docker"

    def __init__(self, run_id: str, cfg: SandboxConfig):
        super().__init__(run_id, cfg)
        self.container = f"agentconstructor-{run_id}"
        self.shell = "sh"

    async def _docker(self, *args: str, timeout: int = 600) -> ExecResult:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL)
        return await self._communicate(proc, timeout)

    async def start(self) -> None:
        ok, detail = await docker_status()
        if not ok:
            raise SandboxError(f"{detail}. Start Docker or switch the graph's sandbox to 'local'.")
        r = await self._docker("image", "inspect", self.cfg.image, timeout=60)
        if r.exit_code != 0:
            pull = await self._docker("pull", self.cfg.image, timeout=900)
            if pull.exit_code != 0:
                raise SandboxError(f"docker pull {self.cfg.image} failed: {pull.stderr.strip()[:500]}")
        args = ["run", "-d", "--rm", "--name", self.container,
                "--memory", self.cfg.memory, "--cpus", str(self.cfg.cpus), "--pids-limit", "512",
                "-v", f"{self.root}:/workspace", "-w", "/workspace", "-e", "HOME=/workspace"]
        if not self.cfg.network:
            args += ["--network", "none"]
        r = await self._docker(*args, self.cfg.image, "sleep", "infinity", timeout=120)
        if r.exit_code != 0:
            raise SandboxError(f"docker run failed: {r.stderr.strip()[:500]}")
        probe = await self._docker("exec", self.container, "sh", "-c", "command -v bash", timeout=30)
        self.shell = "bash" if probe.exit_code == 0 and probe.stdout.strip() else "sh"

    async def stop(self) -> None:
        await self._docker("rm", "-f", self.container, timeout=60)

    async def exec(self, command: str, timeout: int | None = None) -> ExecResult:
        timeout = timeout or self.cfg.timeout
        # `timeout` inside the container kills the process tree; the outer wait is a backstop.
        r = await self._docker("exec", self.container, "timeout", "-s", "KILL", str(timeout), self.shell, "-c", command,
                               timeout=timeout + 15)
        if r.exit_code == 137 and not r.timed_out:
            r.timed_out = True
            r.stderr += f"\ncommand killed after {timeout}s"
        return r


def make_sandbox(run_id: str, cfg: SandboxConfig) -> Sandbox:
    if cfg.type == "docker":
        return DockerSandbox(run_id, cfg)
    return LocalSandbox(run_id, cfg)
