import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from arco_production import run_production_generation  # noqa: E402
from reference_runtime import ReferenceRuntimeError  # noqa: E402


STYLE_PATH = (ROOT / "evaluation" / "style-regression" / "private-assets" / "style-references" / "case-01.jpg").resolve()


class FakeProvider:
    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.calls = []

    def __call__(self, *, prompt: str, referenced_image_paths: list[str]):
        self.calls.append({"prompt": prompt, "referenced_image_paths": referenced_image_paths})
        self.output_path.write_bytes(b"\x89PNG\r\n\x1a\nproduction-smoke")
        return self.output_path


def external_style(*, duties=None, reference_id="external-style-test"):
    return {
        "reference_id": reference_id,
        "source_scope": "external_how",
        "path": str(STYLE_PATH),
        "role": "style_reference",
        "duties": duties or ["style_reference"],
        "authority": "user_request_external",
        "persistent": False,
        "calibrating": False,
        "inherit": ["pose", "composition"],
        "do_not_inherit": [
            "identity",
            "hair",
            "eyes",
            "face",
            "body_proportions",
            "outfit",
            "variant",
        ],
        "coverage": {},
        "style_priority": "primary",
        "style_axes": ["linework", "shading"],
    }


def style_brief(reference_id="external-style-test"):
    return {
        "schema_version": 1,
        "source_reference_id": reference_id,
        "style_priority": "primary",
        "active_axes": ["linework", "shading"],
        "axes": {
            "linework": {
                "description": "thin clean restrained contours",
                "confidence": "HIGH",
            },
            "shading": {
                "description": "restrained cel shading with limited blending",
                "confidence": "MEDIUM",
            },
        },
    }


def base_request(**overrides):
    request = {
        "base_prompt": "Arco stands in a quiet garden.",
        "exposure_profile": "upper_body",
        "variant_id": "casual-outfit",
    }
    request.update(overrides)
    return request


class ProductionGenerationTests(unittest.TestCase):
    def run_request(self, request):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        provider = FakeProvider(Path(temp.name) / "generated.png")
        result = run_production_generation(request, builtin_image_gen=provider, root=ROOT)
        return result, provider

    def test_external_style_reference_compiles_and_reaches_provider(self):
        result, provider = self.run_request(
            base_request(
                external_references=[external_style()],
                style_briefs=[style_brief()],
            )
        )

        self.assertEqual(result.style_context["mode"], "external")
        self.assertEqual(result.style_context["primary_reference_id"], "external-style-test")
        self.assertIn("Rendering style requirements:", result.prompt)
        self.assertNotIn("Rendering hygiene guardrails:", result.prompt)
        self.assertEqual(set(provider.calls[0]), {"prompt", "referenced_image_paths"})
        self.assertEqual(len(provider.calls[0]["referenced_image_paths"]), 3)

    def test_no_external_style_uses_official_fallback_and_hygiene_is_off(self):
        result, provider = self.run_request(base_request())

        self.assertEqual(result.style_context["mode"], "official_fallback")
        self.assertIn("Rendering style requirements:", result.prompt)
        self.assertNotIn("Rendering hygiene guardrails:", result.prompt)
        self.assertEqual(len(provider.calls), 1)

    def test_multi_duty_style_reference_is_one_ordered_image_input(self):
        reference = external_style(
            duties=["style_reference", "lighting_reference", "composition_reference"],
            reference_id="multi-duty-style",
        )
        brief = style_brief("multi-duty-style")
        result, provider = self.run_request(
            base_request(external_references=[reference], style_briefs=[brief])
        )

        external = [item for item in result.selected_references if item["source_scope"] == "external_how"]
        self.assertEqual(len(external), 1)
        self.assertEqual(external[0]["reference_id"], "multi-duty-style")
        self.assertEqual(external[0]["duties"], ["style_reference", "lighting_reference", "composition_reference"])
        paths = provider.calls[0]["referenced_image_paths"]
        self.assertEqual(paths, [str(item["path"]) for item in result.selected_references])
        self.assertEqual(paths.count(str(STYLE_PATH)), 1)

    def test_hygiene_requires_explicit_opt_in(self):
        result, _ = self.run_request(base_request(rendering_hygiene="hygiene_v11"))
        self.assertIn("Rendering hygiene guardrails:", result.prompt)

    def test_invalid_hygiene_mode_fails_closed(self):
        with self.assertRaises(ReferenceRuntimeError) as raised:
            run_production_generation(
                base_request(rendering_hygiene=True),
                builtin_image_gen=lambda **_: None,
                root=ROOT,
            )
        self.assertEqual(raised.exception.code, "INVALID_RENDERING_HYGIENE_MODE")

    def test_non_boolean_uncertain_working_flag_fails_closed(self):
        with self.assertRaises(ReferenceRuntimeError) as raised:
            run_production_generation(
                base_request(allow_uncertain_working="yes"),
                builtin_image_gen=lambda **_: self.fail("provider must not be called"),
                root=ROOT,
            )
        self.assertEqual(raised.exception.code, "MALFORMED_GENERATION_PLAN")

    def test_external_style_without_brief_fails_before_provider(self):
        with self.assertRaises(ReferenceRuntimeError) as raised:
            run_production_generation(
                base_request(external_references=[external_style()]),
                builtin_image_gen=lambda **_: self.fail("provider must not be called"),
                root=ROOT,
            )
        self.assertEqual(raised.exception.code, "STYLE_BRIEF_MISSING")

    def test_external_identity_pollution_and_unknown_experiment_fields_fail_closed(self):
        polluted = external_style()
        polluted["inherit"] = ["identity"]
        polluted["do_not_inherit"] = [
            field for field in polluted["do_not_inherit"] if field != "identity"
        ]
        with self.assertRaises(ReferenceRuntimeError) as raised:
            run_production_generation(
                base_request(external_references=[polluted], style_briefs=[style_brief()]),
                builtin_image_gen=lambda **_: self.fail("provider must not be called"),
                root=ROOT,
            )
        self.assertEqual(raised.exception.code, "EXTERNAL_IDENTITY_POLLUTION")

        with self.assertRaises(ReferenceRuntimeError) as raised:
            run_production_generation(
                base_request(group="B"),
                builtin_image_gen=lambda **_: self.fail("provider must not be called"),
                root=ROOT,
            )
        self.assertEqual(raised.exception.code, "MALFORMED_GENERATION_PLAN")

    def test_external_reference_limit_is_enforced(self):
        references = [
            {
                **external_style(reference_id=f"pose-{index}"),
                "role": "pose_reference",
                "duties": ["pose_reference"],
                "style_priority": None,
                "style_axes": [],
            }
            for index in range(3)
        ]
        for reference in references:
            reference.pop("style_priority", None)
            reference.pop("style_axes", None)
        with self.assertRaises(ReferenceRuntimeError) as raised:
            run_production_generation(
                base_request(external_references=references),
                builtin_image_gen=lambda **_: self.fail("provider must not be called"),
                root=ROOT,
            )
        self.assertEqual(raised.exception.code, "REFERENCE_LIMIT_EXCEEDED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
