from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from azure_serialization import assign_reqs_to_steps, parse_existing_steps, rebuild_existing_steps_xml


class AzureSerializationTests(unittest.TestCase):
    def test_roundtrip_steps_xml(self):
        original = (
            '<steps id="0" last="1">'
            '<step id="1" type="ActionStep">'
            '<parameterizedString isformatted="true">&lt;P&gt;Open screen&lt;/P&gt;</parameterizedString>'
            '<parameterizedString isformatted="true">&lt;P&gt;Screen opens&lt;/P&gt;</parameterizedString>'
            '<description/>'
            '</step>'
            '</steps>'
        )
        parsed = parse_existing_steps(original)
        self.assertEqual(parsed[0]["text_action"], "Open screen")
        self.assertEqual(parsed[0]["text_expected"], "Screen opens")

        covers = assign_reqs_to_steps(parsed, [{"req_id": "REQ-1", "requirement_text": "open screen"}])
        rebuilt = rebuild_existing_steps_xml(parsed, covers)
        root = ET.fromstring(rebuilt)
        params = root.findall("step")[0].findall("parameterizedString")
        self.assertTrue(params[0].text and params[0].text.strip())
        self.assertEqual(len(list(params[0])), 0)


if __name__ == "__main__":
    unittest.main()
