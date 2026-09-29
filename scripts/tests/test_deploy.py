"""Exercise deployment sequencing without a Docker daemon or a remote VM."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class DeployTests(unittest.TestCase):
    """Verify remote deployment ordering and cleanup with a mock Docker executable."""
    def setUp(self):
        """Create an isolated deployment bundle, configuration, and controllable Docker stub."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.deploy = self.workspace / "deployment"
        self.deploy.mkdir()
        (self.deploy / ".env").write_text("SECRET_KEY=test-only\n")
        self.log = self.workspace / "docker.log"
        mock = self.workspace / "docker"
        mock.write_text(
            '#!/usr/bin/env bash\n'
            'printf "%s\\n" "$*" >> "$TEST_DOCKER_LOG"\n'
            'if [[ "$1" == login ]]; then cat > /dev/null; fi\n'
            'if [[ -n "${TEST_FAIL_ON:-}" && " $* " == *" $TEST_FAIL_ON "* ]]; then exit 42; fi\n'
        )
        mock.chmod(0o700)
        result = subprocess.run(
            ["mktemp", "-d", "/tmp/sit-web-deploy.XXXXXXXXXX"],
            check=True, capture_output=True, text=True,
        )
        self.bundle = Path(result.stdout.strip())
        self.addCleanup(shutil.rmtree, self.bundle, ignore_errors=True)
        (self.bundle / "registry.user").write_text("test-user\n")
        (self.bundle / "registry.token").write_text("test-token")
        (self.bundle / "images.env").write_text("FRONTEND_IMAGE=test-front\nBACKEND_IMAGE=test-back\n")
        shutil.copyfile(ROOT / "compose.production.yaml", self.bundle / "compose.production.yaml")
        shutil.copyfile(ROOT / "scripts/setup-https.sh", self.bundle / "setup-https.sh")
        self.env = {
            **os.environ,
            "PATH": f"{self.workspace}:{os.environ['PATH']}",
            "SIT_DEPLOY_DIR": str(self.deploy),
            "TEST_DOCKER_LOG": str(self.log),
            "TEST_FAIL_ON": "",
        }

    def run_remote(self, failure=""):
        """Run the remote script, optionally failing a chosen mock Docker operation."""
        self.env["TEST_FAIL_ON"] = failure
        return subprocess.run(
            ["bash", str(ROOT / "scripts/deploy-remote.sh"), str(self.bundle)],
            env=self.env, capture_output=True, text=True,
        )

    def test_success_pulls_before_up_and_removes_credentials(self):
        """Pull images before replacing services and remove temporary registry credentials."""
        result = self.run_remote()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.log.read_text().splitlines()
        pull = next(i for i, line in enumerate(commands) if line.endswith(" pull"))
        up = next(i for i, line in enumerate(commands) if " up -d " in line)
        self.assertLess(pull, up)
        self.assertIn("--force-recreate --wait --wait-timeout 120", commands[up])
        self.assertTrue((self.deploy / "images.env").is_file())
        self.assertTrue((self.deploy / "setup-https.sh").is_file())
        self.assertFalse(self.bundle.exists())

    def test_pull_failure_never_updates_containers(self):
        """Stop before container updates when pulling an image fails."""
        result = self.run_remote("pull")
        self.assertEqual(result.returncode, 42)
        self.assertNotIn(" up -d ", self.log.read_text())
        self.assertFalse((self.deploy / "images.env").exists())
        self.assertFalse(self.bundle.exists())

    def test_unhealthy_update_preserves_last_successful_metadata(self):
        """Keep the prior image metadata when updated services fail their health checks."""
        previous = self.deploy / "images.env"
        previous.write_text("previous-images\n")
        result = self.run_remote("up")
        self.assertEqual(result.returncode, 42)
        self.assertEqual(previous.read_text(), "previous-images\n")
        self.assertFalse(self.bundle.exists())

    def test_missing_vm_configuration_stops_before_docker(self):
        """Reject a deployment lacking the VM environment file before Docker is invoked."""
        (self.deploy / ".env").unlink()
        result = self.run_remote()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.bundle.exists())

    def test_runner_rejects_untrusted_image_reference_before_ssh(self):
        """Reject mutable image tags before any SSH connection is attempted."""
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/deploy-gcp.sh")],
            env={**self.env, "FRONTEND_IMAGE": "ghcr.io/example/frontend:latest",
                 "BACKEND_IMAGE": "unused", "GCP_VM_HOST": "example.com",
                 "GCP_VM_USER": "deploy", "GCP_VM_SSH_KEY": "test-key",
                 "GCP_VM_KNOWN_HOSTS": "test-host", "GHCR_USERNAME": "test-user",
                 "GHCR_PAT": "test-token"},
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected a GHCR digest reference", result.stderr)


if __name__ == "__main__":
    unittest.main()
