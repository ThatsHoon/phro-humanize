"""humanize_run.py 런처 — 결정적 단계 묶음이 기존 스크립트와 같은 결과를 내는지.

SKILL.md 는 Phase 1(run 할당·입력 저장·shim)과 Phase 2.4~2.5(서법 복원·쉼표
제거·게이트)를 이 런처 한 번으로 부른다. 런타임 에이전트에 Bash 가 없어
백업을 못 하므로, 백업 계약(final_prev.md·final_pre_finalize.md)도
여기서 지킨다. stdlib only, claude CLI 불필요.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_RUN = _ROOT / "scripts" / "humanize_run.py"
_SHIM = _ROOT / "scripts" / "prepare_monolith_input.py"

SAMPLE = (
    "인공지능 기술의 발전은 우리 사회에 다양한 변화를 가져오고 있습니다. "
    "결론적으로, 이는 시사하는 바가 크다고 할 수 있습니다. "
    "또한 효율성을 제고할 수 있을 것으로 보입니다."
)


def _run(args: list[str], cwd: Path, stdin: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    return subprocess.run(
        [sys.executable, str(_RUN), *args], cwd=cwd, env=env,
        input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )


def _kv(out: str) -> dict[str, str]:
    return dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln and not ln.startswith(" "))


class PrepareTests(unittest.TestCase):
    def test_input_file_creates_tagged_run_and_normalizes_newlines(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            # BOM + CRLF — 윈도에서 저장한 파일. 원문은 LF 로 들어가야 게이트가 줄마다 변경으로 세지 않는다.
            # 300자를 넘겨야 tail 미리보기도 나온다.
            (work / "in.txt").write_bytes(("﻿" + "\r\n\r\n".join([SAMPLE] * 4) + "\r\n").encode("utf-8"))
            proc = _run(["prepare", "--input-file", "in.txt", "--genre", "essay"], work)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            kv = _kv(proc.stdout)
            rd = Path(kv["run_dir"])
            self.assertTrue(rd.is_dir())
            self.assertRegex(rd.name, r"^\d{4}-\d{2}-\d{2}-\d{3}-[0-9a-f]{4}$", "세션 태그 자동 부착")
            self.assertEqual(kv["run_id"], rd.name)
            self.assertIn(kv["route_hint"], {"light", "standard", "heavy"})
            self.assertTrue((Path(kv["skill_root"]) / "scripts" / "humanize_run.py").is_file())
            body = (rd / "01_input.txt").read_text(encoding="utf-8")
            self.assertNotIn("\r", body)
            self.assertFalse(body.startswith("﻿"))
            self.assertIn("head", kv, "파일 입력이면 장르 추정용 head 미리보기")
            self.assertIn("tail", kv)

    def test_stdin_input(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            proc = _run(["prepare", "--input-file", "-", "--genre", "column"], work, stdin=SAMPLE + "\n")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            kv = _kv(proc.stdout)
            body = (Path(kv["run_dir"]) / "01_input.txt").read_text(encoding="utf-8")
            self.assertEqual(body.strip(), SAMPLE)
            self.assertNotIn("head", kv, "stdin 은 오케스트레이터가 이미 본문을 봤다 — 미리보기 생략")

    def test_rerun_backs_up_existing_final(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            kv = _kv(_run(["prepare", "--text", SAMPLE], work).stdout)
            rd = Path(kv["run_dir"])
            (rd / "final.md").write_text("이전 윤문본\n", encoding="utf-8")
            proc = _run(["prepare", "--run-dir", str(rd), "--genre", "essay"], work)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual((rd / "final_prev.md").read_text(encoding="utf-8"), "이전 윤문본\n")


class FinishTests(unittest.TestCase):
    def _run_dir(self, work: Path, final: str) -> Path:
        kv = _kv(_run(["prepare", "--text", SAMPLE], work).stdout)
        rd = Path(kv["run_dir"])
        (rd / "final.md").write_text(final, encoding="utf-8")
        return rd

    def test_finish_runs_all_steps_and_returns_gate_code(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            rd = self._run_dir(work, SAMPLE.replace("결론적으로, ", "") + "\n")
            proc = _run(["finish", "--run-dir", str(rd), "--genre", "essay", "--pre-finalize"], work)
            out = proc.stdout + proc.stderr
            self.assertIn("[서법 복원]", out)
            self.assertIn("gate:", out)
            self.assertIn(f"gate_exit={proc.returncode}", out)
            self.assertIn(proc.returncode, (0, 1))
            self.assertTrue((rd / "final_pre_finalize.md").is_file(), "heavy 는 finalize 직전 백업")

    def test_abort_backs_up_for_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            rd = self._run_dir(work, "전혀 다른 글이다. 원문과 겹치는 데가 없다.\n")
            proc = _run(["finish", "--run-dir", str(rd), "--genre", "essay"], work)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertTrue((rd / "final_prev.md").is_file(), "exit 2 면 롤백 재실행 대비 백업")
            self.assertFalse((rd / "final_pre_finalize.md").exists())

    def test_missing_files_is_undecidable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proc = _run(["finish", "--run-dir", "_workspace/none", "--genre", "essay"], Path(td))
            self.assertEqual(proc.returncode, 3, "판정 불가는 3 — 경고(1)로 읽히면 안 된다")

    def test_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            rd = self._run_dir(work, "윤문본\n")
            proc = _run(["snapshot", "--run-dir", str(rd)], work)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual((rd / "final_pre_finalize.md").read_text(encoding="utf-8"), "윤문본\n")


class ShimInputFileTests(unittest.TestCase):
    def test_text_and_input_file_are_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            (work / "in.txt").write_text(SAMPLE, encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(_SHIM), "--text", SAMPLE, "--input-file", "in.txt"],
                cwd=work, capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=60,
            )
            self.assertNotEqual(proc.returncode, 0)

    def test_cp949_file_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            (work / "in.txt").write_bytes(SAMPLE.encode("cp949"))
            proc = subprocess.run(
                [sys.executable, str(_SHIM), "--input-file", "in.txt", "--run-dir", "_workspace/x"],
                cwd=work, capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            body = (work / "_workspace" / "x" / "01_input.txt").read_text(encoding="utf-8")
            self.assertEqual(body, SAMPLE)


class RuntimeAgentToolScopeTests(unittest.TestCase):
    """런타임 3종은 Bash 없이 파일 도구만 쓴다. monolith·finalizer 는 Edit 가 있어야
    쓴 뒤의 국소 수정이 파일 전체 재출력으로 번지지 않는다."""

    def test_runtime_agents_are_tool_restricted(self) -> None:
        for name in ("humanize-monolith", "humanize-diagnostician", "humanize-finalizer"):
            head = (_ROOT / "agents" / f"{name}.md").read_text(encoding="utf-8").split("---", 2)[1]
            with self.subTest(agent=name):
                self.assertRegex(head, r"tools: Read, Write")
                self.assertNotIn("Bash", head.split("tools:", 1)[1].splitlines()[0])
                if name != "humanize-diagnostician":
                    self.assertIn("Edit", head.split("tools:", 1)[1].splitlines()[0])
                self.assertIn("omitClaudeMd: true", head)
                self.assertRegex(head, r"maxTurns: \d+")


if __name__ == "__main__":
    unittest.main()
