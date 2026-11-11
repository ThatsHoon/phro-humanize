#!/usr/bin/env python3
"""humanize-korean 오케스트레이터 런처 — 결정적 단계를 Bash 1회로 묶는다.

SKILL.md 가 메인 세션에 시키던 결정적 단계(세션 태그·run 디렉터리 할당·입력 저장·
shim·route_hint 읽기 / 서법 복원·쉼표 제거·게이트·백업)에는 LLM 판단이 없다.
그런데 단계마다 도구 호출을 따로 하면 왕복마다 메인 세션 컨텍스트 전체가 다시
읽힌다. 이 런처는 그 묶음을 서브커맨드 하나로 끝낸다. 각 단계는 기존 스크립트를
그대로 부르므로 판정 로직은 바뀌지 않는다.

  prepare  [--input-file PATH|- | --text STR] [--run-dir DIR] --genre G
           [--session-tag T] [--diagnosis F] [--chunk] [--no-sanitize] [--baseline F]
      새 run 이면 세션 태그를 자동으로 만든다(shim 이 _workspace/<날짜>-NNN-<TAG>/ 를
      원자적으로 할당). 기존 run 에 final.md 가 있으면 final_prev.md 로 백업한 뒤
      shim 을 돌린다. shim 출력 뒤에 skill_root= 를 붙이고, 파일 경로 입력이면
      장르 추정·챗봇 잔재 확인용 head=/tail= 미리보기를 붙인다.

  finish   --run-dir DIR --genre G [--all-commas] [--ignore-markup] [--pre-finalize]
      restore_modality → strip_injected_commas(--all-commas 면 --all) → verify_gates.
      게이트 exit code 를 그대로 돌려준다(0 수렴 / 1 경고 / 2 중단 / 3 판정 불가).
      exit 1 이거나 --pre-finalize 면 final.md 를 final_pre_finalize.md 로,
      exit 2 면 final_prev.md 로 복사해 둔다(finalize·롤백 재실행 대비).

  gate     --run-dir DIR --genre G [--ignore-markup]
      verify_gates 만. finalize 뒤 최종 변경률 확정용.

  snapshot --run-dir DIR
      final.md → final_pre_finalize.md 복사만. 게이트 외 사유(자체검증 실패·사용자
      요청)로 finalize 를 승급할 때 쓴다.

런타임 에이전트는 `tools` 에 Bash 가 없어 파일 복사를 하지 못한다.
백업을 여기서 하는 이유다.

stdlib only. 위치 규칙: 이 파일은 `${SKILL_ROOT}/scripts/` 에 있고, 형제 스크립트를
같은 디렉터리에서 찾는다(플러그인·심링크·--copy 설치 모두 동일).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent

sys.path.insert(0, str(HERE))
import console as _console  # noqa: E402

HEAD_CHARS = 300
TAIL_CHARS = 150


def _env() -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _script(name: str, args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(HERE / name), *args]
    if capture:
        return subprocess.run(
            cmd, env=_env(), stdout=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace",
        )
    sys.stdout.flush()
    sys.stderr.flush()
    return subprocess.run(cmd, env=_env())


def _resolve(run_dir: str) -> Path:
    rd = Path(run_dir)
    return rd if rd.is_absolute() else Path.cwd() / rd


def _copy(rd: Path, src: str, dst: str, why: str) -> None:
    s = rd / src
    if s.is_file():
        shutil.copyfile(s, rd / dst)
        print(f"backup={src} -> {dst} ({why})")


def _one_line(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------


def cmd_prepare(a: argparse.Namespace) -> int:
    if a.run_dir is None and a.input_file is None and a.text is None:
        print("error: --run-dir 또는 --input-file/--text 중 하나가 필요하다", file=sys.stderr)
        return 2

    if a.run_dir is not None:
        rd = _resolve(a.run_dir)
        if rd.is_dir():
            _copy(rd, "final.md", "final_prev.md", "재실행 전 이전 윤문본 보존")

    shim_args = ["--genre", a.genre]
    if a.run_dir is not None:
        shim_args += ["--run-dir", a.run_dir]
    if a.input_file is not None:
        shim_args += ["--input-file", a.input_file]
    if a.text is not None:
        shim_args += ["--text", a.text]
    tag = a.session_tag
    if a.run_dir is None and not tag:
        tag = secrets.token_hex(2)
    if tag:
        shim_args += ["--session-tag", tag]
    if a.diagnosis:
        shim_args += ["--diagnosis", a.diagnosis]
    if a.chunk:
        shim_args.append("--chunk")
    if a.no_sanitize:
        shim_args.append("--no-sanitize")
    if a.baseline:
        shim_args += ["--baseline", a.baseline]

    proc = _script("prepare_monolith_input.py", shim_args, capture=True)
    out = proc.stdout or ""
    sys.stdout.write(out)
    if proc.returncode != 0:
        return proc.returncode

    run_dir = next(
        (ln.split("=", 1)[1].strip() for ln in out.splitlines() if ln.startswith("run_dir=")),
        None,
    )
    if run_dir is None and a.run_dir is not None:
        run_dir = str(_resolve(a.run_dir))
    print(f"skill_root={SKILL_ROOT}")
    if run_dir:
        print(f"run_id={Path(run_dir).name}")

    # 파일 입력은 오케스트레이터가 본문을 보지 않았다. 장르 추정(첫 300자)과
    # 챗봇 잔재(머리·꼬리) 확인에 필요한 만큼만 보여 준다.
    if a.input_file not in (None, "-") and run_dir:
        src = Path(run_dir) / "01_input.txt"
        if src.is_file():
            body = src.read_text(encoding="utf-8")
            print(f"chars={len(body)}")
            print(f"head={_one_line(body[:HEAD_CHARS])}")
            if len(body) > HEAD_CHARS:
                print(f"tail={_one_line(body[-TAIL_CHARS:])}")
    return 0


# ---------------------------------------------------------------------------
# finish / gate / snapshot
# ---------------------------------------------------------------------------


def _paths(a: argparse.Namespace) -> tuple[Path, Path, Path] | None:
    rd = _resolve(a.run_dir)
    before, after = rd / "01_input.txt", rd / "final.md"
    missing = [p.name for p in (before, after) if not p.is_file()]
    if missing:
        print(f"error: {rd} 에 {', '.join(missing)} 없음 — 판정 불가", file=sys.stderr)
        return None
    return rd, before, after


def _gate(a: argparse.Namespace, before: Path, after: Path) -> int:
    args = ["--before", str(before), "--after", str(after), "--genre", a.genre]
    if a.ignore_markup:
        args.append("--ignore-markup")
    return _script("verify_gates.py", args).returncode


def cmd_finish(a: argparse.Namespace) -> int:
    p = _paths(a)
    if p is None:
        return 3
    rd, before, after = p
    io = ["--before", str(before), "--after", str(after), "--out", str(after)]

    rc = _script("restore_modality.py", io).returncode
    if rc != 0:
        print(f"error: restore_modality 실패(exit {rc}) — 판정 불가", file=sys.stderr)
        return 3
    rc = _script("strip_injected_commas.py", io + (["--all"] if a.all_commas else [])).returncode
    if rc != 0:
        print(f"error: strip_injected_commas 실패(exit {rc}) — 판정 불가", file=sys.stderr)
        return 3

    gate_rc = _gate(a, before, after)
    if gate_rc == 2:
        _copy(rd, "final.md", "final_prev.md", "exit 2 — 롤백 재실행 대비")
    elif gate_rc == 1 or (a.pre_finalize and gate_rc == 0):
        _copy(rd, "final.md", "final_pre_finalize.md", "finalize 직전 원본")
    print(f"gate_exit={gate_rc}")
    return gate_rc


def cmd_gate(a: argparse.Namespace) -> int:
    p = _paths(a)
    if p is None:
        return 3
    _, before, after = p
    gate_rc = _gate(a, before, after)
    print(f"gate_exit={gate_rc}")
    return gate_rc


def cmd_snapshot(a: argparse.Namespace) -> int:
    rd = _resolve(a.run_dir)
    if not (rd / "final.md").is_file():
        print(f"error: {rd / 'final.md'} 없음", file=sys.stderr)
        return 3
    _copy(rd, "final.md", "final_pre_finalize.md", "finalize 직전 원본")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="humanize-korean 결정적 단계 런처")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("prepare", help="run 할당 + 입력 저장 + shim (+ final.md 백업)")
    pp.add_argument("--run-dir")
    src = pp.add_mutually_exclusive_group()
    src.add_argument("--input-file", help="입력 파일 경로, `-` 면 stdin")
    src.add_argument("--text")
    pp.add_argument("--genre", default="essay")
    pp.add_argument("--session-tag")
    pp.add_argument("--diagnosis")
    pp.add_argument("--chunk", action="store_true")
    pp.add_argument("--no-sanitize", action="store_true")
    pp.add_argument("--baseline")
    pp.set_defaults(func=cmd_prepare)

    for name, func, helptext in (
        ("finish", cmd_finish, "서법 복원 + 쉼표 제거 + 게이트 (+ 백업)"),
        ("gate", cmd_gate, "게이트만 (finalize 뒤 재확인)"),
    ):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--run-dir", required=True)
        sp.add_argument("--genre", default="essay")
        sp.add_argument("--ignore-markup", action="store_true")
        if name == "finish":
            sp.add_argument("--all-commas", action="store_true",
                            help="진단이 C-11 을 지목한 standard·heavy 경로 전용")
            sp.add_argument("--pre-finalize", action="store_true",
                            help="게이트 결과와 무관하게 final_pre_finalize.md 백업(heavy)")
        sp.set_defaults(func=func)

    sn = sub.add_parser("snapshot", help="final.md → final_pre_finalize.md")
    sn.add_argument("--run-dir", required=True)
    sn.set_defaults(func=cmd_snapshot)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(_console.run_gate(main))
