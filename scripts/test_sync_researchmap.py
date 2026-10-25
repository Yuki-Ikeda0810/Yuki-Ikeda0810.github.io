import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sync_researchmap as sync


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(sync.CACHE.read_text(encoding="utf-8"))

    def test_translation_fallback_and_current_dates(self):
        self.assertEqual(sync.localized({"ja": "日本語"}, "en"), "日本語")
        self.assertEqual(sync.period({"from_date": "2023-04", "to_date": "9999"}, "en"), "2023-04 – Present")

    def test_remote_text_is_escaped_and_unsafe_urls_are_not_rendered(self):
        self.data["published_papers"]["items"] = [{
            "paper_title": {"en": '<script>alert("test")</script>'},
            "@id": "javascript:alert(1)",
        }]
        html = sync.render_publications(self.data, "en")
        self.assertNotIn("<script>", html)
        self.assertNotIn("javascript:", html)
        self.assertIn("&lt;script&gt;", html)

    def test_missing_markers_fail_without_silently_replacing_content(self):
        with self.assertRaises(ValueError):
            sync.replace_block("<main>Manually edited content</main>", "career", "New")

    def test_private_entries_and_incomplete_career(self):
        self.assertEqual(sync.public_items([{"display": "private"}]), [])
        raw = {"permalink": "yukiikeda", "affiliations": [], "@graph": [
            {"@type": kind, "items": [], "total_items": 0} for kind in sync.TYPES
        ]}
        raw["@graph"][0]["total_items"] = 2
        with self.assertRaises(ValueError):
            sync.normalize(raw)

    def test_media_order_limit_fallback_and_safe_output(self):
        self.data["media_coverage"] = {"total": 12, "items": [
            {"media_coverage_title": {"ja": f"Report {i:02d}<script>"},
             "publication_date": f"2026-01-{i:02d}",
             "publisher": {"ja": "Publisher & Co"},
             "@id": "javascript:alert(1)"} for i in range(1, 13)
        ]}
        html = sync.render_media(self.data, "en")
        self.assertEqual(html.count('<li>'), 10)
        self.assertLess(html.index('Report 12'), html.index('Report 11'))
        self.assertNotIn('Report 02', html)
        self.assertNotIn('<script>', html)
        self.assertNotIn('javascript:', html)
        self.assertIn('Publisher &amp; Co', html)
        self.assertIn('10 shown / 12 public records', html)
        self.assertIn('rel="noopener noreferrer"', html)

    def test_media_old_snapshot_and_empty_records(self):
        self.data.pop("media_coverage", None)
        self.assertIn('next successful sync', sync.render_media(self.data, 'en'))
        self.data['media_coverage'] = {'total': 0, 'items': []}
        self.assertIn('No public media coverage', sync.render_media(self.data, 'en'))

    def test_media_url_priority_and_languages(self):
        item = {
            '@id': sync.API + '/media_coverage/123',
            'description': {
                'ja': 'URL (JP) : https://example.com/ja',
                'en': 'URL (EN): https://example.com/en?a=1&b=2',
            },
            'see_also': [{'@id': 'https://example.com/shared'}],
        }
        self.assertEqual(sync.media_url(item, 'ja'), 'https://example.com/ja')
        self.assertEqual(sync.media_url(item, 'en'), 'https://example.com/en?a=1&b=2')
        del item['description']['en']
        self.assertEqual(sync.media_url(item, 'en'), 'https://example.com/shared')
        item['description']['ja'] += '\nURL (EN): https://example.com/english'
        self.assertEqual(sync.media_url(item, 'en'), 'https://example.com/english')
        item.pop('description')
        item.pop('see_also')
        for lang in ('ja', 'en'):
            self.assertEqual(sync.media_url(item, lang), sync.PROFILE + '/media_coverage/123?lang=' + lang)

    def test_media_unsafe_and_unlabelled_urls_are_ignored(self):
        item = {
            'description': {'en': 'https://example.com/unlabelled\nURL (EN): javascript:alert(1)'},
            'see_also': [{'@id': 'javascript:alert(2)'}, {'@id': 'https://example.com/shared'}],
        }
        self.assertEqual(sync.media_url(item, 'en'), 'https://example.com/shared')
        item['see_also'] = []
        self.assertEqual(sync.media_url(item, 'en'), sync.PROFILE + '/media_coverage?lang=en')

    def test_research_outputs_and_source_links_use_page_language(self):
        for lang in ('ja', 'en'):
            html = sync.render_publications(self.data, lang)
            self.assertIn('?lang=' + lang + '"', html)
            self.assertNotIn('?lang=' + ('ja' if lang == 'en' else 'en'), html)

    def test_normalize_keeps_media_link_fields(self):
        item = {'description': {'en': 'URL (EN): https://example.com/en'},
                'see_also': [{'@id': 'https://example.com/ja'}]}
        raw = {'permalink': 'yukiikeda', 'affiliations': [], '@graph': [
            {'@type': kind, 'items': [item] if kind == 'media_coverage' else [], 'total_items': 1 if kind == 'media_coverage' else 0}
            for kind in sync.TYPES
        ]}
        self.assertEqual(sync.normalize(raw)['media_coverage']['items'], [item])

    def test_network_failure_preserves_snapshot_and_renders_both_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "en").mkdir()
            cache = root / "researchmap.json"
            original = json.dumps(self.data)
            cache.write_text(original, encoding="utf-8")
            template = "<main><!-- researchmap:publications:start --><!-- researchmap:publications:end --><!-- researchmap:career:start --><!-- researchmap:career:end --><!-- researchmap:media:start --><!-- researchmap:media:end --></main>"
            for path in (root / "index.html", root / "en/index.html"):
                path.write_text(template, encoding="utf-8")
            with patch.object(sync, "ROOT", root), patch.object(sync, "CACHE", cache), patch.object(sync, "fetch", side_effect=TimeoutError("test timeout")), patch("sys.argv", ["sync", "--allow-stale"]):
                sync.main()
            self.assertEqual(cache.read_text(encoding="utf-8"), original)
            self.assertIn("Current affiliations", (root / "en/index.html").read_text(encoding="utf-8"))
            self.assertIn("現在の所属", (root / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
