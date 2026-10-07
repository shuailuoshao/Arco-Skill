"""Phase 1 planning contract; no image or provider invocation."""

import json
import unittest
from pathlib import Path

from scripts.revision_intent import (
    GeneratedOutputRole,
    RevisionPlan,
    RevisionType,
    SourceStrategy,
    normalize_revision_text,
    resolve_revision_intent,
)


class RevisionPlanTests(unittest.TestCase):
    def test_first_generation_entrypoint_bypasses_resolver(self):
        import ast
        production = (Path(__file__).resolve().parent / "arco_production.py").read_text(encoding="utf-8")
        module = ast.parse(production)
        for name in ("plan_production_generation", "run_production_generation"):
            entry = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == name)
            source = ast.get_source_segment(production, entry)
            self.assertNotIn("resolve_revision_intent", source)
            self.assertNotIn("RevisionPlan", source)

    def test_closed_types_and_bool_validation(self):
        args = (RevisionType.SCENE_ONLY, SourceStrategy.EDIT_CURRENT,
                GeneratedOutputRole.PRIMARY_EDIT_SOURCE, False, False, False)
        self.assertEqual(RevisionPlan(*args).revision_type, RevisionType.SCENE_ONLY)
        with self.assertRaises(TypeError):
            RevisionPlan("scene_only", *args[1:])
        with self.assertRaises(TypeError):
            RevisionPlan(*args[:3], 0, False, False)
        with self.assertRaises(TypeError):
            RevisionPlan(*args[:2], "primary_edit_source", *args[3:])

    def test_serialization_and_normalization(self):
        plan = resolve_revision_intent("  背景  亮一点  ")
        self.assertEqual(list(plan.as_dict()), [
            "revision_type", "source_strategy", "generated_output_role",
            "requires_original_identity", "requires_original_outfit", "requires_external_refs"])
        self.assertEqual(json.loads(json.dumps(plan.as_dict()))["revision_type"], "scene_only")
        self.assertEqual(normalize_revision_text("  ＨＡＩＲ\n  Color  "), "hair color")
        self.assertEqual(plan, resolve_revision_intent("背景 亮一点"))


class RoutingTests(unittest.TestCase):
    CASES = [
        ("背景亮一点", "scene_only", False, False),
        ("天空颜色偏冷一点", "scene_only", False, False),
        ("脸再像阿尔可一点", "character_detail", True, False),
        ("红色眼睛恢复原设", "character_detail", True, False),
        ("头太大", "character_detail", False, False),
        ("手部结构修正常", "character_detail", False, False),
        ("衣服改回原来的结构", "character_detail", False, True),
        ("人物往左移动", "composition", False, False),
        ("人物再大一点", "composition", False, False),
        ("画风简化", "style", False, False),
        ("有波浪纹", "artifact_repair", False, False),
        ("背景出现莫尔纹", "artifact_repair", False, False),
        ("背景暗一点，同时脸改回原设", "mixed", True, False),
        ("保留构图，把人物重新画清楚", "mixed", False, False),
        ("背景不变，只修改头发", "character_detail", True, False),
        ("人物往近一点", "composition", False, False),
        ("人物不要这么远", "composition", False, False),
        ("让人物在画面中占比更高", "composition", False, False),
        ("镜头靠近人物一点", "composition", False, False),
        ("人物往近一点，让脸清楚", "mixed", True, False),
        ("人物再大一点，让衣服能看清", "mixed", False, True),
        ("人物不要这么远，我想看清脸", "mixed", True, False),
        ("镜头靠近人物一点，让发型看得清", "mixed", True, False),
        ("让人物在画面中占比更高，五官要能分辨", "mixed", True, False),
        ("人物太远了，但我想保留大面积天空", "composition", False, False),
        ("脸不像阿尔可", "character_detail", True, False),
        ("眼睛不对", "character_detail", True, False),
        ("头发改回原设", "character_detail", True, False),
        ("衣服结构改回原设", "character_detail", False, True),
        ("人物在画面里太大", "composition", False, False),
        ("人物靠近镜头一点", "composition", False, False),
        ("把人物放大一些", "composition", False, False),
        ("人物占画面更多一些", "composition", False, False),
        ("人物小一点", "composition", False, False),
        ("脸小一点", "character_detail", True, False),
    ]

    def test_fixed_matrix(self):
        for request, kind, identity, outfit in self.CASES:
            with self.subTest(request=request):
                plan = resolve_revision_intent(request)
                self.assertEqual(plan.revision_type.value, kind)
                self.assertEqual(plan.requires_original_identity, identity)
                self.assertEqual(plan.requires_original_outfit, outfit)

    def test_strategy_table(self):
        expected = [
            ("背景亮一点", "edit_current", "primary_edit_source"),
            ("头发不对", "reanchor_and_regenerate", "composition_anchor"),
            ("人物往左移动", "edit_current", "primary_edit_source"),
            ("画风简化", "reanchor_and_regenerate", "composition_anchor"),
            ("有波浪纹", "source_reset", "excluded"),
            ("背景暗一点，同时脸改回原设", "reanchor_and_regenerate", "composition_anchor"),
            ("有波浪纹，同时把脸修好", "source_reset", "excluded"),
            ("请改一下", "reanchor_and_regenerate", "composition_anchor"),
        ]
        for request, strategy, role in expected:
            with self.subTest(request=request):
                plan = resolve_revision_intent(request)
                self.assertEqual(plan.source_strategy.value, strategy)
                self.assertEqual(plan.generated_output_role.value, role)

    def test_risk_and_constraint_boundaries(self):
        for request, kind, identity, outfit in [
            ("背景保持不变，把脸重新修得像阿尔可", "character_detail", True, False),
            ("把背景波浪纹修掉", "artifact_repair", False, False),
            ("人物往左一点，同时把头发改回原设", "mixed", True, False),
            ("画风简化一点，但衣服结构恢复原设", "mixed", False, True),
            ("背景暗一点，同时把莫尔纹修掉", "mixed", False, False),
            ("请改一下", "mixed", False, False),
        ]:
            with self.subTest(request=request):
                plan = resolve_revision_intent(request)
                self.assertEqual((plan.revision_type.value, plan.requires_original_identity,
                                  plan.requires_original_outfit), (kind, identity, outfit))

    def test_external_how_is_explicit_and_supplied(self):
        how = ({"source_scope": "external_how"},)
        self.assertFalse(resolve_revision_intent("背景亮一点", external_references=how).requires_external_refs)
        self.assertFalse(resolve_revision_intent("继续用外部参考图，背景亮一点").requires_external_refs)
        self.assertTrue(resolve_revision_intent("继续用外部参考图，背景亮一点", external_references=how).requires_external_refs)
        self.assertFalse(resolve_revision_intent("继续用外部参考图，背景亮一点", external_references=({"source_scope": "managed_arco"},)).requires_external_refs)

    def test_determinism(self):
        for request in ("背景亮一点", "脸再像阿尔可一点", "背景出现莫尔纹", "背景暗一点，同时脸改回原设"):
            with self.subTest(request=request):
                plans = [resolve_revision_intent(request).as_dict() for _ in range(20)]
                self.assertTrue(all(plan == plans[0] for plan in plans))


if __name__ == "__main__":
    unittest.main()
