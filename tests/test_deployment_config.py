"""Static deployment-boundary tests that do not require Docker or ECS access."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeploymentConfigTests(unittest.TestCase):
    def test_history_get_does_not_consume_evaluation_post_rate_limit(self) -> None:
        for filename in ("multi-agent-arena.conf", "multi-agent-arena-gray.conf"):
            with self.subTest(filename=filename):
                nginx = (ROOT / "deploy" / "nginx" / filename).read_text(encoding="utf-8")
                mapping = re.search(
                    r"map \$request_method \$evaluation_post_limit_key\s*\{([^}]+)\}",
                    nginx,
                )
                self.assertIsNotNone(mapping)
                self.assertEqual(
                    mapping.group(1).split(),
                    ["default", '"";', "POST", "$binary_remote_addr;"],
                )
                self.assertIn(
                    "limit_req_zone $evaluation_post_limit_key "
                    "zone=evaluation_post_by_ip:10m rate=1r/m;",
                    nginx,
                )
                self.assertNotIn(
                    "limit_req_zone $binary_remote_addr zone=evaluation_by_ip", nginx
                )

    def test_controller_unit_fails_closed_when_sandbox_network_is_not_ready(self) -> None:
        unit = (
            ROOT / "deploy" / "systemd" / "multi-agent-arena-sandbox-controller.service"
        ).read_text(encoding="utf-8")
        check_script = (ROOT / "deploy" / "systemd" / "check-sandbox-network.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("Environment=SANDBOX_DOCKER_NETWORK=app_arena_sandbox", unit)
        self.assertIn(
            "ExecStartPre=/usr/local/libexec/multi-agent-arena/check-sandbox-network",
            unit,
        )
        self.assertIn('expected_driver="bridge"', check_script)
        self.assertIn('expected_internal="true"', check_script)
        self.assertIn('expected_subnet="172.30.0.0/24"', check_script)
        self.assertIn('expected_gateway="172.30.0.1"', check_script)
        self.assertIn("--format '{{.Driver}}'", check_script)
        self.assertIn("--format '{{.Internal}}'", check_script)
        self.assertIn("--format '{{.Name}}'", check_script)
        self.assertIn("--format '{{(index .IPAM.Config 0).Subnet}}'", check_script)
        self.assertIn("--format '{{(index .IPAM.Config 0).Gateway}}'", check_script)
        self.assertIn("User=arena-sandbox", unit)
        self.assertIn("SupplementaryGroups=docker", unit)
        self.assertNotIn("0.0.0.0", check_script)

    def test_sandbox_audit_log_is_separate_and_retained_for_three_days(self) -> None:
        unit = (
            ROOT / "deploy" / "systemd" / "multi-agent-arena-sandbox-controller.service"
        ).read_text(encoding="utf-8")
        logrotate = (
            ROOT / "deploy" / "logrotate" / "multi-agent-arena-sandbox-audit"
        ).read_text(encoding="utf-8")

        self.assertIn("StateDirectory=multi-agent-arena-sandbox-audit", unit)
        self.assertIn("StateDirectoryMode=0750", unit)
        self.assertIn(
            "Environment=ARENA_SANDBOX_AUDIT_LOG=/var/lib/multi-agent-arena-sandbox-audit/tasks.jsonl",
            unit,
        )
        self.assertIn("/var/lib/multi-agent-arena-sandbox-audit/tasks.jsonl", logrotate)
        self.assertIn("daily", logrotate)
        self.assertIn("rotate 3", logrotate)
        self.assertIn("maxage 3", logrotate)
        self.assertIn("compress", logrotate)
        self.assertIn("create 0640 arena-sandbox arena-sandbox", logrotate)

    def test_formal_domain_nginx_template_enforces_https_and_modern_tls(self) -> None:
        nginx = (ROOT / "deploy" / "nginx" / "multi-agent-arena.conf").read_text(
            encoding="utf-8"
        )

        self.assertIn("server_name tomato-agent-arena.me;", nginx)
        self.assertIn("return 301 https://$host$request_uri;", nginx)
        self.assertIn("listen 443 ssl http2;", nginx)
        self.assertIn(
            "ssl_certificate /etc/letsencrypt/live/tomato-agent-arena.me/fullchain.pem;",
            nginx,
        )
        self.assertIn(
            "ssl_certificate_key /etc/letsencrypt/live/tomato-agent-arena.me/privkey.pem;",
            nginx,
        )
        self.assertIn("ssl_protocols TLSv1.2 TLSv1.3;", nginx)
        self.assertIn("ssl_session_tickets off;", nginx)
        self.assertIn(
            'add_header Strict-Transport-Security "max-age=31536000" always;',
            nginx,
        )
        self.assertNotIn("TLSv1 TLSv1.1", nginx)

    def test_evaluation_route_requires_the_approved_management_allowlist(self) -> None:
        approved_source = "36.248.198.60/32"

        for filename in ("multi-agent-arena.conf", "multi-agent-arena-gray.conf"):
            nginx = (ROOT / "deploy" / "nginx" / filename).read_text(encoding="utf-8")
            evaluation_route = re.search(
                r"location = /api/evaluations \{(.*?)^    \}",
                nginx,
                re.DOTALL | re.MULTILINE,
            )

            self.assertIsNotNone(evaluation_route)
            route = evaluation_route.group(1)
            self.assertIn(f"allow {approved_source};", route)
            self.assertIn("deny all;", route)
            self.assertLess(
                route.index(f"allow {approved_source};"),
                route.index("deny all;"),
            )
            self.assertIn("limit_req zone=evaluation_post_by_ip nodelay;", route)
            self.assertIn("limit_req_status 429;", route)
            self.assertIn("proxy_read_timeout 220s;", route)

            api_route = re.search(r"location /api/ \{(.*?)^    \}", nginx, re.DOTALL | re.MULTILINE)
            self.assertIsNotNone(api_route)
            self.assertNotIn("allow ", api_route.group(1))
            self.assertNotIn("deny all;", api_route.group(1))

    def test_deployment_example_uses_approved_formal_domain(self) -> None:
        environment = (ROOT / ".env.deploy.example").read_text(encoding="utf-8")

        self.assertIn("CORS_ORIGINS=https://tomato-agent-arena.me", environment)

    def test_compose_keeps_postgres_off_sandbox_network(self) -> None:
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

        postgres_block = re.search(r"  postgres:\n(.*?)(?=\n  backend:)", compose, re.DOTALL)
        backend_block = re.search(r"  backend:\n(.*?)(?=\nnetworks:)", compose, re.DOTALL)

        self.assertIsNotNone(postgres_block)
        self.assertIsNotNone(backend_block)
        self.assertNotIn("arena_sandbox", postgres_block.group(1))
        self.assertRegex(backend_block.group(1), r"(?m)^      - arena_sandbox$")
        self.assertRegex(
            compose,
            r"(?ms)^  arena_sandbox:\n    driver: bridge\n    internal: true\n"
            r"    ipam:\n      config:\n        - subnet: 172\.30\.0\.0/24\n          gateway: 172\.30\.0\.1$",
        )

    def test_deployment_example_defaults_evaluation_to_disabled_private_controller(self) -> None:
        environment = (ROOT / ".env.deploy.example").read_text(encoding="utf-8")

        self.assertIn("EVALUATION_ENABLED=false", environment)
        self.assertIn("EVALUATION_TOTAL_TIMEOUT_SECONDS=210", environment)
        self.assertIn("SANDBOX_CONTROLLER_URL=http://172.30.0.1:8001", environment)
        self.assertIn("SANDBOX_CONTROLLER_TIMEOUT_SECONDS=10", environment)

    def test_backend_image_includes_versioned_judge_cases(self) -> None:
        dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("COPY judge_cases ./judge_cases", dockerfile)

    def test_backend_image_uses_audited_hash_locked_dependencies(self) -> None:
        dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
        lockfile = (ROOT / "backend" / "requirements.lock").read_text(encoding="utf-8")

        self.assertRegex(
            dockerfile,
            r"FROM python:3\.12-slim@sha256:[0-9a-f]{64}",
        )
        self.assertIn("COPY requirements.lock ./", dockerfile)
        self.assertIn("--isolated", dockerfile)
        self.assertIn("--only-binary=:all:", dockerfile)
        self.assertIn("--index-url https://mirrors.aliyun.com/pypi/simple/", dockerfile)
        self.assertIn("--require-hashes", dockerfile)
        self.assertIn("-r requirements.lock", dockerfile)
        self.assertNotIn("--extra-index-url", dockerfile)
        self.assertNotIn("--trusted-host", dockerfile)
        self.assertNotIn("http://", dockerfile)

        requirements = re.findall(r"^([a-z0-9][a-z0-9_.-]*(?:\[[a-z0-9_,.-]+\])?==[^\s]+) \\\\?$", lockfile, re.MULTILINE)
        hashes = re.findall(r"^    --hash=sha256:[0-9a-f]{64}$", lockfile, re.MULTILINE)

        self.assertEqual(34, len(requirements))
        self.assertEqual(len(requirements), len(hashes))
        self.assertIn("fastapi==0.115.6", requirements)
        self.assertIn("uvicorn[standard]==0.34.0", requirements)
        self.assertIn("sqlalchemy[asyncio]==2.0.36", requirements)


if __name__ == "__main__":
    unittest.main()