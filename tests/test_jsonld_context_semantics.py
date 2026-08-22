#!/usr/bin/env python3
"""End-to-end checks that compact ABox JSON and RDF expansion stay equivalent."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF, URIRef

ROOT = Path(__file__).resolve().parents[1]
ECL = Namespace("urn:ecl:")


class JsonLdContextSemanticEquivalenceTests(unittest.TestCase):
    def test_every_entity_raw_identity_matches_rdf_expansion(self) -> None:
        paths = sorted(set((ROOT / "knowledge/entities").rglob("*.json")) | set((ROOT / "knowledge/entities").rglob("*.jsonld")))
        self.assertTrue(paths)
        for path in paths:
            record = json.loads(path.read_text(encoding="utf-8"))
            entity_id = record["id"]
            entity_type = record["type"]
            subject = URIRef(f"urn:ecl:{entity_id}")
            graph = Graph().parse(path, format="json-ld")
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertIn((subject, RDF.type, ECL[entity_type]), graph)
                self.assertIn((subject, ECL.stableId, Literal(entity_id)), graph)

    def test_representative_relation_aliases_expand_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ontology").mkdir(parents=True)
            (root / "knowledge/entities").mkdir(parents=True)
            shutil.copy2(ROOT / "ontology/ecl-context.jsonld", root / "ontology/ecl-context.jsonld")
            fixture = root / "knowledge/entities/ORG-SOURCE.json"
            fixture.write_text(
                json.dumps(
                    {
                        "@context": "../../ontology/ecl-context.jsonld",
                        "iri": "ecl:ORG-SOURCE",
                        "id": "ORG-SOURCE",
                        "type": "Organization",
                        "identityLifecycle": "superseded",
                        "supersededBy": "ecl:ORG-SUCCESSOR",
                        "partOf": ["ecl:ORG-PARENT"],
                        "controls": "ecl:PROJECT-CONTROLLED",
                        "participatesIn": "ecl:PROJECT-PARTICIPATION",
                        "operates": "ecl:PROJECT-OPERATED",
                        "deploys": "ecl:DEPLOYMENT-X",
                    }
                ),
                encoding="utf-8",
            )
            graph = Graph().parse(fixture, format="json-ld")
            source = ECL["ORG-SOURCE"]
            self.assertIn((source, RDF.type, ECL.Organization), graph)
            self.assertIn((source, ECL.stableId, Literal("ORG-SOURCE")), graph)
            self.assertIn((source, ECL.status, Literal("superseded")), graph)
            self.assertIn((source, ECL.partOf, ECL["ORG-PARENT"]), graph)
            self.assertIn((source, ECL.controls, ECL["PROJECT-CONTROLLED"]), graph)
            self.assertIn((source, ECL.participatesIn, ECL["PROJECT-PARTICIPATION"]), graph)
            self.assertIn((source, ECL.operates, ECL["PROJECT-OPERATED"]), graph)
            self.assertIn((source, ECL.deploys, ECL["DEPLOYMENT-X"]), graph)
            self.assertIn((ECL["ORG-SUCCESSOR"], ECL.supersedes, source), graph)


if __name__ == "__main__":
    unittest.main(verbosity=2)
