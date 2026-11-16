"""Concurrency and cancellation controls around Blender Agent execution."""

import concurrent.futures
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters import operators
from adapters.common import write_json


class AgentControlTests(unittest.TestCase):
    def test_cancel_queued_job(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            jobs = root / "jobs"
            queue = root / "queue"
            jobs.mkdir()
            queue.mkdir()
            job_id = uuid.uuid4().hex
            write_json(
                jobs / (job_id + ".json"),
                {"ok": True, "job_id": job_id, "status": "queued"},
            )
            write_json(queue / (job_id + ".json"), {"job_id": job_id})
            with patch.object(operators, "AGENT_JOBS", jobs), patch.object(
                operators, "AGENT_QUEUE", queue
            ):
                result = operators.cancel_agent_job(job_id)
            self.assertEqual(result["status"], "cancelled")
            self.assertFalse((queue / (job_id + ".json")).exists())

    def test_claimed_job_cannot_be_cancelled(self):
        with tempfile.TemporaryDirectory() as folder:
            jobs = Path(folder) / "jobs"
            queue = Path(folder) / "queue"
            jobs.mkdir()
            queue.mkdir()
            job_id = uuid.uuid4().hex
            write_json(
                jobs / (job_id + ".json"),
                {"ok": True, "job_id": job_id, "status": "queued"},
            )
            with patch.object(operators, "AGENT_JOBS", jobs), patch.object(
                operators, "AGENT_QUEUE", queue
            ):
                with self.assertRaisesRegex(RuntimeError, "already claiming"):
                    operators.cancel_agent_job(job_id)

    def test_persistent_operator_start_is_serialized(self):
        active = 0
        maximum = 0
        counter_lock = threading.Lock()

        def fake_run(item, parameters, model):
            nonlocal active, maximum
            with counter_lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.05)
            with counter_lock:
                active -= 1
            return {"ok": True, "status": "running"}

        with patch.object(operators, "_run_persistent", side_effect=fake_run):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(operators.run_operator, "start_rhino_server", {})
                    for _ in range(2)
                ]
                for future in futures:
                    self.assertTrue(future.result()["ok"])
        self.assertEqual(maximum, 1)


if __name__ == "__main__":
    unittest.main()
