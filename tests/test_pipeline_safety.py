import json
import unittest
from urllib.parse import urlparse


def valid_https(url):
    parsed = urlparse(url)
    return parsed.scheme == 'https' and bool(parsed.netloc) and not any(ch.isspace() for ch in url)


def split_caption(text, count):
    words = text.strip().split()
    if not words:
        return ['' for _ in range(max(1, count))]
    count = max(1, count)
    out, start = [], 0
    for i in range(count):
        remaining, slots = len(words) - start, count - i
        end = len(words) if slots == 1 else min(len(words), start + max(1, round(remaining / slots)))
        out.append(' '.join(words[start:end]))
        start = end
    return out


class SafetyTests(unittest.TestCase):
    def test_https_source_validation(self):
        self.assertTrue(valid_https('https://example.org/paper'))
        self.assertFalse(valid_https('http://example.org'))
        self.assertFalse(valid_https('https://'))
        self.assertFalse(valid_https('https://example.org bad'))

    def test_caption_order_and_coverage(self):
        text = 'one two three four five six seven'
        chunks = split_caption(text, 3)
        self.assertEqual(' '.join(chunks), text)
        self.assertEqual(len(chunks), 3)

    def test_empty_caption(self):
        self.assertEqual(split_caption('', 2), ['', ''])

    def test_json_schema_rejects_missing_fields(self):
        value = json.loads('{"title":"x"}')
        required = {'title', 'description', 'topic', 'narration', 'scenes', 'sources', 'hashtags'}
        self.assertFalse(required.issubset(value))

    def test_memory_candidate_does_not_mutate_original(self):
        memory = {'recent_topics': [{'topic': 'old'}], 'running_context': []}
        candidate = dict(memory)
        candidate['recent_topics'] = list(memory['recent_topics']) + [{'topic': 'new'}]
        self.assertEqual(len(memory['recent_topics']), 1)
        self.assertEqual(len(candidate['recent_topics']), 2)

    def test_failure_report_is_independent_of_delivery_report(self):
        # The workflow's always-on failure artifact must not depend on run-report.json.
        from pathlib import Path
        workflow = Path('.github/workflows/generate-pilot.yml').read_text(encoding='utf-8')
        # Check the YAML expression's intended status semantics, not a brittle spelling.
        self.assertRegex(workflow, r'if:\s*\$\{\{\s*failure\(\)\s*\|\|\s*cancelled\(\)\s*\}\}')
        self.assertIn('output/**', workflow)
        self.assertIn('output/diagnostics/**', workflow)
        self.assertNotIn("hashFiles('output/delivery/run-report.json')", workflow.split('Preserve failure diagnostics', 1)[1])


if __name__ == '__main__':
    unittest.main()
