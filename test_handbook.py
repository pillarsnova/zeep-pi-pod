"""The handbook is deterministic, offline and Admin-only; no hardware needed."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from api.handbook_routes import create_handbook_router
from documentation.builder import ROOT, build_html, compile_data, load_catalog
from documentation.rendering import contained_file, document_link, render_document


class HandbookBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = compile_data()
        cls.html = build_html()

    def test_bundle_is_deterministic_and_has_all_catalog_documents(self):
        self.assertEqual(self.html, build_html())
        catalog = load_catalog()
        count = sum(len(group['documents']) for group in catalog['groups'])
        self.assertEqual(len(self.data['documents']), count)
        self.assertGreater(count, 50)
        embedded = re.search(
            r'<script id="handbook-data" type="application/json">(.*?)</script>',
            self.html, re.S,
        ).group(1)
        self.assertEqual(json.loads(embedded), self.data)

    def test_current_documentation_and_onboarding_are_included(self):
        paths = {doc['path'] for doc in self.data['documents']}
        for source in [*ROOT.glob('docs/*.md'), *ROOT.glob('docs/onboarding/*.md')]:
            self.assertIn(source.relative_to(ROOT).as_posix(), paths)

    def test_internal_article_links_resolve(self):
        ids = {doc['id'] for doc in self.data['documents']}
        for doc in self.data['documents']:
            for target in re.findall(r'href="#/read/([^/"\s]+)', doc['html']):
                self.assertIn(target, ids, doc['path'])

    def test_no_runtime_requests_or_remote_assets(self):
        assets = ROOT / 'documentation/assets'
        script = (assets / 'handbook.js').read_text()
        self.assertNotIn('fetch(', script)
        self.assertNotIn('XMLHttpRequest', script)
        self.assertNotIn('WebSocket', script)
        self.assertNotRegex(self.html, r'<(?:script|link|img)[^>]+(?:src|href)="https?://')
        self.assertNotIn('@import', (assets / 'handbook.css').read_text())
        self.assertNotIn('@@DATA@@', self.html)

    def test_sanitizes_source_html_and_unsafe_urls(self):
        text = (
            '# Example\n\n<script>alert(1)</script>\n\n'
            '[bad](javascript:alert(1)) [file](file:///etc/passwd) '
            '[protocol](//tracker.example.com) ![pixel](https://tracker.example/p.png)\n\n'
            '[safe](https://example.com)'
        )
        result = render_document(text, ROOT / 'docs/README.md', ROOT, {})
        self.assertNotIn('<script>', result['html'])
        self.assertNotIn('<img', result['html'])
        self.assertNotIn('href="file:', result['html'])
        self.assertNotIn('href="javascript:', result['html'])
        self.assertNotIn('href="//', result['html'])
        self.assertIn('rel="noopener noreferrer"', result['html'])

    def test_duplicate_headings_have_unique_anchors(self):
        result = render_document(
            '# Title\n\n## ทดสอบ\n\n## ทดสอบ', ROOT / 'docs/README.md', ROOT, {}
        )
        anchors = [heading['id'] for heading in result['outline']]
        self.assertEqual(len(anchors), len(set(anchors)))

    def test_path_containment_and_link_scheme(self):
        source = ROOT / 'docs/README.md'
        for relative in ('/etc/passwd', '../outside.md', '.env', 'missing.md'):
            with self.assertRaises(ValueError):
                contained_file(ROOT, relative)
        for href in ('file:///etc/passwd', 'javascript:alert(1)', '/etc/passwd',
                     '../../outside.md', '//example.com'):
            self.assertIsNone(document_link(href, source, ROOT, {}))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'outside.md').symlink_to(source)
            with self.assertRaises(ValueError):
                contained_file(root, 'outside.md')

    def test_bundle_is_not_served_from_public_static_directory(self):
        self.assertFalse((ROOT / 'static/handbook.html').exists())
        self.assertFalse((ROOT / 'static/portal/index.html').exists())


class HandbookRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name) / 'index.html'
        self.bundle.write_text('<!doctype html><title>Internal handbook</title>')

        def admin(role: str | None = Header(default=None)):
            if role is None:
                raise HTTPException(401, 'Login required')
            if role != 'admin':
                raise HTTPException(403, 'Admin required')
            return {'role': role}

        app = FastAPI()
        app.include_router(create_handbook_router(bundle=self.bundle, require_admin=admin))
        self.client = TestClient(app)

    def test_anonymous_and_user_cannot_read_internal_docs(self):
        self.assertEqual(self.client.get('/handbook').status_code, 401)
        self.assertEqual(self.client.get('/handbook', headers={'role': 'user'}).status_code, 403)

    def test_admin_can_read_without_cache_or_external_requests(self):
        response = self.client.get('/handbook', headers={'role': 'admin'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers['cache-control'])
        self.assertIn("default-src 'none'", response.headers['content-security-policy'])
        self.assertEqual(response.headers['x-frame-options'], 'DENY')

    def test_missing_bundle_is_explicit_and_not_an_arbitrary_file_route(self):
        self.bundle.unlink()
        self.assertEqual(self.client.get('/handbook', headers={'role': 'admin'}).status_code, 404)
        self.assertEqual(self.client.get('/handbook/../../etc/passwd').status_code, 404)


if __name__ == '__main__':
    unittest.main()
