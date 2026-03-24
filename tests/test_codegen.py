"""Tests for PowerLanguage code generation."""

import pytest
import yaml
from pathlib import Path
from src.codegen.generator import PowerLanguageGenerator
from src.codegen.validator import validate_powerlanguage


@pytest.fixture
def generator():
    return PowerLanguageGenerator(template_dir="templates")


@pytest.fixture
def ma_cross_config():
    with open("strategies/examples/ma_cross.yaml") as f:
        return yaml.safe_load(f)


class TestPowerLanguageGenerator:
    def test_generate_ma_cross(self, generator, ma_cross_config):
        code = generator.generate_code(ma_cross_config)
        assert "Inputs:" in code
        assert "Variables:" in code
        assert "fast_ma" in code
        assert "slow_ma" in code
        assert "Buy" in code
        assert "SellShort" in code
        assert "SetStopLoss" in code

    def test_generate_creates_file(self, generator, tmp_path):
        output = generator.generate(
            "strategies/examples/ma_cross.yaml",
            output_dir=str(tmp_path),
        )
        assert output.exists()
        assert output.suffix == ".pla"

    def test_validate_generated_code(self, generator, ma_cross_config):
        code = generator.generate_code(ma_cross_config)
        errors = validate_powerlanguage(code)
        assert len(errors) == 0, f"Validation errors: {errors}"

    def test_condition_translation(self, generator):
        cond = generator._translate_condition("fast_ma crosses_above slow_ma")
        assert cond == "fast_ma crosses above slow_ma"

    def test_compound_condition(self, generator):
        cond = generator._translate_condition("rsi1 crosses_above 30 and close above trend_ma")
        assert "crosses above" in cond
        assert ">" in cond

    def test_all_example_strategies(self, generator):
        """Test that all example strategies generate valid code."""
        examples_dir = Path("strategies/examples")
        for yaml_file in examples_dir.glob("*.yaml"):
            with open(yaml_file) as f:
                config = yaml.safe_load(f)
            code = generator.generate_code(config)
            errors = validate_powerlanguage(code)
            assert len(errors) == 0, f"{yaml_file.name}: {errors}"
