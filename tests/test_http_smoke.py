from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


class HttpSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.database_path = cls.root / "data" / "test_http.db"
        cls.artifacts = [
            Path(str(cls.database_path) + suffix) for suffix in ("", "-wal", "-shm")
        ]
        for artifact in cls.artifacts:
            artifact.unlink(missing_ok=True)

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            cls.port = listener.getsockname()[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        environment = os.environ.copy()
        environment["BUS_AGENT_DB_PATH"] = str(cls.database_path)
        environment["PYTHONIOENCODING"] = "utf-8"
        cls.server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(cls.port),
                "--log-level",
                "warning",
            ],
            cwd=cls.root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for _ in range(60):
            if cls.server.poll() is not None:
                output = cls.server.stdout.read() if cls.server.stdout else ""
                raise RuntimeError(f"测试服务启动失败：{output}")
            try:
                cls.request("/api/health")
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError("测试服务启动超时")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)
        if cls.server.stdout:
            cls.server.stdout.close()
        for artifact in cls.artifacts:
            artifact.unlink(missing_ok=True)

    @classmethod
    def request(
        cls,
        path: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
        expected_status: int = 200,
    ) -> tuple[dict, dict[str, str]]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            cls.base_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status = response.status
                data = json.loads(response.read().decode("utf-8"))
                headers = {key.lower(): value for key, value in response.headers.items()}
        except urllib.error.HTTPError as error:
            with error:
                status = error.code
                data = json.loads(error.read().decode("utf-8"))
                headers = {key.lower(): value for key, value in error.headers.items()}
        if status != expected_status:
            raise AssertionError(f"{method} {path}: 期望 {expected_status}，实际 {status}，响应 {data}")
        return data, headers

    def test_health_and_security_headers(self) -> None:
        data, headers = self.request("/api/health")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["version"], "1.2.0")
        self.assertEqual(data["transit_route_count"], 5)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertTrue(headers["x-request-id"])

    def test_real_guilin_transit_routes_are_available(self) -> None:
        data, _ = self.request("/api/transit/routes")
        self.assertEqual(data["count"], 5)
        self.assertEqual(data["total"], 5)
        self.assertFalse(data["is_realtime_gps"])
        self.assertEqual(data["trajectory_mode"], "simulated_on_real_route_geometry")
        self.assertEqual({item["ref"] for item in data["items"]}, {"1", "10", "16", "23", "24"})
        self.assertTrue(all(len(item["animation_path"]) >= 8 for item in data["items"]))

        filtered, _ = self.request("/api/transit/routes?ref=1&ref=23")
        self.assertEqual(filtered["count"], 2)
        self.assertEqual({item["ref"] for item in filtered["items"]}, {"1", "23"})

        route_id = filtered["items"][0]["id"]
        detail, _ = self.request(f"/api/transit/routes/{route_id}")
        self.assertEqual(detail["id"], route_id)
        self.request("/api/transit/routes/not-a-route", expected_status=422)
        self.request("/api/transit/routes/osm-999999999", expected_status=404)

    def test_validation_errors_are_consistent(self) -> None:
        data, _ = self.request("/api/snapshot?hour=99", expected_status=422)
        self.assertEqual(data["detail"], "请求参数校验失败")
        self.assertTrue(data["errors"])
        malformed, _ = self.request("/api/simulations/not-an-id", expected_status=422)
        self.assertEqual(malformed["detail"], "请求参数校验失败")
        extra, _ = self.request(
            "/api/simulations",
            method="POST",
            payload={"scenario": "peak", "hour": 11, "spot_id": "xs", "unknown": True},
            expected_status=422,
        )
        self.assertEqual(extra["detail"], "请求参数校验失败")

    def test_oversized_request_is_rejected(self) -> None:
        data, headers = self.request(
            "/api/simulations",
            method="POST",
            payload={"payload": "x" * 66_000},
            expected_status=413,
        )
        self.assertEqual(data["detail"], "请求体过大")
        self.assertEqual(headers["x-content-type-options"], "nosniff")

    def test_complete_simulation_workflow_is_idempotent(self) -> None:
        simulation, _ = self.request(
            "/api/simulations",
            method="POST",
            payload={"scenario": "event", "hour": 20, "spot_id": "ljs"},
            expected_status=201,
        )
        simulation_id = simulation["id"]
        conflict, _ = self.request(
            f"/api/simulations/{simulation_id}/evaluate",
            method="POST",
            expected_status=409,
        )
        self.assertIn("先下发", conflict["detail"])

        self.request(f"/api/simulations/{simulation_id}/dispatch", method="POST")
        dispatched, _ = self.request(
            f"/api/simulations/{simulation_id}/dispatch", method="POST"
        )
        self.assertEqual(dispatched["status"], "dispatched")
        self.assertEqual(len([event for event in dispatched["events"] if event["stage"] == 4]), 2)

        evaluated, _ = self.request(
            f"/api/simulations/{simulation_id}/evaluate", method="POST"
        )
        self.assertEqual(evaluated["status"], "evaluated")
        self.request(
            f"/api/simulations/{simulation_id}/exports",
            method="POST",
            payload={"format": "pdf"},
            expected_status=201,
        )
        filtered, _ = self.request("/api/simulations?scenario=event&status=evaluated&limit=8")
        self.assertGreaterEqual(filtered["total"], 1)
        self.assertTrue(all(item["scenario"] == "event" for item in filtered["items"]))
        self.assertTrue(all(item["status"] == "evaluated" for item in filtered["items"]))


if __name__ == "__main__":
    unittest.main()
