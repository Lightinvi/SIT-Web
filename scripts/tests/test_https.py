"""Test HTTPS configuration generation without root, a VM, or issuing certificates."""

from pathlib import Path
import subprocess
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "setup-https.sh"


class HttpsTests(unittest.TestCase):
    def render(self, domain, port="8080"):
        return subprocess.run(
            ["bash", str(SCRIPT), "--print-config", domain, port],
            capture_output=True, text=True,
        )

    def test_site_and_proxy_headers(self):
        result = self.render("sit-web.sytes.net")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("server_name sit-web.sytes.net;", result.stdout)
        self.assertIn("proxy_pass http://127.0.0.1:8080;", result.stdout)
        self.assertIn("proxy_set_header X-Forwarded-Proto $scheme;", result.stdout)
        self.assertIn("proxy_set_header X-Forwarded-For $remote_addr;", result.stdout)
        self.assertNotIn("ssl_certificate", result.stdout)

    def test_custom_application_port(self):
        result = self.render("sit-web.sytes.net", "9080")
        self.assertEqual(result.returncode, 0)
        self.assertIn("127.0.0.1:9080", result.stdout)

    def test_invalid_domain_is_rejected(self):
        for domain in ("example.com;", "../example.com", "example..com", "-bad.example.com", "example.com.", "*.example.com"):
            with self.subTest(domain=domain):
                self.assertNotEqual(self.render(domain).returncode, 0)

    def test_reserved_or_invalid_ports_are_rejected(self):
        for port in ("80", "443", "0", "65536", "8080;", "-1"):
            with self.subTest(port=port):
                self.assertNotEqual(self.render("sit-web.sytes.net", port).returncode, 0)


if __name__ == "__main__":
    unittest.main()
