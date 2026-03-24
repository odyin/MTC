"""PowerLanguage/EasyLanguage code generator from YAML strategy config.

Reads a strategy YAML, renders Jinja2 templates to produce a .pla file
compatible with MultiCharts.
"""

import yaml
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


# Map condition DSL operators to PowerLanguage syntax
CONDITION_OPS = {
    "crosses_above": "crosses above",
    "crosses_below": "crosses below",
    "above": ">",
    "below": "<",
}

# Map indicator source names to PowerLanguage
SOURCE_MAP = {
    "close": "Close",
    "open": "Open",
    "high": "High",
    "low": "Low",
    "volume": "Volume",
}


class PowerLanguageGenerator:
    """Generates MultiCharts PowerLanguage code from YAML strategy config."""

    def __init__(self, template_dir: str | Path = "templates"):
        self.template_dir = Path(template_dir)
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate(self, config_path: str | Path, output_dir: str | Path = "output/powerlanguage") -> Path:
        """Generate PowerLanguage .pla file from strategy YAML config."""
        config_path = Path(config_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        with open(config_path) as f:
            config = yaml.safe_load(f)

        code = self._render(config)

        name = config.get("name", "Strategy")
        version = config.get("version", "1.0")
        filename = f"{name}_v{version}.pla"
        output_path = output_dir / filename

        output_path.write_text(code, encoding="utf-8")
        return output_path

    def generate_code(self, config: dict) -> str:
        """Generate PowerLanguage code string from config dict."""
        return self._render(config)

    def _render(self, config: dict) -> str:
        """Render the complete strategy code."""
        inputs = self._build_inputs(config)
        variables = self._build_variables(config)
        calculations = self._build_calculations(config)
        entry_rules = self._build_entry_rules(config)
        exit_rules = self._build_exit_rules(config)
        risk_mgmt = self._build_risk_management(config)

        template = self.env.get_template("base_strategy.j2")
        return template.render(
            name=config.get("name", "Strategy"),
            version=config.get("version", "1.0"),
            description=config.get("description", ""),
            inputs_block=inputs,
            variables_block=variables,
            indicator_calculations=calculations,
            entry_rules=entry_rules,
            exit_rules=exit_rules,
            risk_management=risk_mgmt,
        )

    def _build_inputs(self, config: dict) -> str:
        """Build the Inputs: block."""
        lines = ["Inputs:"]
        params = []

        # Non-numeric params that should not become Inputs
        skip_params = {"method", "source"}

        for indicator in config.get("indicators", []):
            name = indicator["name"]
            for pname, pval in indicator.get("params", {}).items():
                if pname in skip_params:
                    continue
                if isinstance(pval, dict):
                    default = pval.get("default", 0)
                else:
                    default = pval
                # Skip string values (not valid PowerLanguage input)
                if isinstance(default, str):
                    continue
                param_name = f"{name}_{pname}"
                params.append(f"    {param_name}({default})")

        # Exit params
        exit_cfg = config.get("exit", {})
        if "stop_loss" in exit_cfg:
            params.append(f"    StopLossPoints({exit_cfg['stop_loss'].get('value', 0)})")
        if "take_profit" in exit_cfg:
            params.append(f"    TakeProfitPoints({exit_cfg['take_profit'].get('value', 0)})")
        if exit_cfg.get("trailing_stop", {}).get("enabled", False):
            params.append(f"    TrailingStopPoints({exit_cfg['trailing_stop'].get('value', 0)})")

        # Risk params
        risk_cfg = config.get("risk", {})
        if risk_cfg.get("max_daily_loss", 0) > 0:
            params.append(f"    MaxDailyLoss({risk_cfg['max_daily_loss']})")

        lines.append(",\n".join(params) + ";")
        return "\n".join(lines)

    def _build_variables(self, config: dict) -> str:
        """Build the Variables: block."""
        lines = ["Variables:"]
        vars_list = []

        for indicator in config.get("indicators", []):
            itype = indicator["type"]
            name = indicator["name"]

            if itype == "ma":
                vars_list.append(f"    {name}(0)")
            elif itype == "rsi":
                vars_list.append(f"    {name}(0)")
            elif itype == "macd":
                vars_list.append(f"    {name}_val(0)")
                vars_list.append(f"    {name}_avg(0)")
                vars_list.append(f"    {name}_hist(0)")
            elif itype == "bollinger":
                vars_list.append(f"    {name}_mid(0)")
                vars_list.append(f"    {name}_std(0)")
                vars_list.append(f"    {name}_upper(0)")
                vars_list.append(f"    {name}_lower(0)")
            elif itype == "kd":
                vars_list.append(f"    {name}_fastk(0)")
                vars_list.append(f"    {name}_k(0)")
                vars_list.append(f"    {name}_d(0)")
            elif itype == "atr":
                vars_list.append(f"    {name}(0)")

        vars_list.append("    intrabarpersalivedone(false)")
        lines.append(",\n".join(vars_list) + ";")
        return "\n".join(lines)

    def _build_calculations(self, config: dict) -> str:
        """Build indicator calculation code using Jinja2 indicator templates."""
        blocks = []
        for indicator in config.get("indicators", []):
            itype = indicator["type"]
            name = indicator["name"]
            params = indicator.get("params", {})

            template_path = f"indicators/{itype}.j2"
            try:
                tmpl = self.env.get_template(template_path)
            except Exception:
                blocks.append(f"// WARNING: No template for indicator type '{itype}'")
                continue

            # Build template context
            ctx = {"name": name}
            source = params.get("source", "close")
            ctx["source"] = SOURCE_MAP.get(source, "Close")

            if itype == "ma":
                ctx["period_param"] = f"{name}_period"
                method = params.get("method", "SMA")
                if isinstance(method, dict):
                    method = method.get("default", "SMA")
                ctx["method"] = method
            elif itype == "rsi":
                ctx["period_param"] = f"{name}_period"
            elif itype == "macd":
                ctx["fast_param"] = f"{name}_fast"
                ctx["slow_param"] = f"{name}_slow"
                ctx["signal_param"] = f"{name}_signal"
            elif itype == "bollinger":
                ctx["period_param"] = f"{name}_period"
                ctx["std_dev_param"] = f"{name}_std_dev"
            elif itype == "kd":
                ctx["k_period_param"] = f"{name}_k_period"
                ctx["k_smooth_param"] = f"{name}_k_smooth"
                ctx["d_smooth_param"] = f"{name}_d_smooth"
            elif itype == "atr":
                ctx["period_param"] = f"{name}_period"

            blocks.append(tmpl.render(**ctx))

        return "\n".join(blocks)

    def _build_entry_rules(self, config: dict) -> str:
        """Build entry condition code in PowerLanguage."""
        lines = []
        entry = config.get("entry", {})
        name = config.get("name", "Strategy")

        long_cfg = entry.get("long", {})
        if long_cfg and long_cfg.get("condition"):
            condition_pl = self._translate_condition(long_cfg["condition"])
            contracts = long_cfg.get("contracts", 1)
            lines.append(f"// Long Entry")
            lines.append(f"If {condition_pl} Then")
            if contracts > 1:
                lines.append(f'    Buy ("{name}_L") {contracts} contracts next bar at market;')
            else:
                lines.append(f'    Buy ("{name}_L") next bar at market;')
            lines.append("")

        short_cfg = entry.get("short", {})
        if short_cfg and short_cfg.get("condition"):
            condition_pl = self._translate_condition(short_cfg["condition"])
            contracts = short_cfg.get("contracts", 1)
            lines.append(f"// Short Entry")
            lines.append(f"If {condition_pl} Then")
            if contracts > 1:
                lines.append(f'    SellShort ("{name}_S") {contracts} contracts next bar at market;')
            else:
                lines.append(f'    SellShort ("{name}_S") next bar at market;')

        return "\n".join(lines)

    def _build_exit_rules(self, config: dict) -> str:
        """Build exit rules in PowerLanguage."""
        lines = []
        exit_cfg = config.get("exit", {})
        name = config.get("name", "Strategy")

        # Stop loss
        if "stop_loss" in exit_cfg:
            sl = exit_cfg["stop_loss"]
            if sl.get("type") == "points":
                lines.append("SetStopLoss(StopLossPoints * BigPointValue);")
            elif sl.get("type") == "percent":
                lines.append(f"SetPercentTrailing(StopLossPoints, StopLossPoints);")

        # Take profit
        if "take_profit" in exit_cfg:
            tp = exit_cfg["take_profit"]
            if tp.get("type") == "points":
                lines.append("SetProfitTarget(TakeProfitPoints * BigPointValue);")

        # Trailing stop
        ts = exit_cfg.get("trailing_stop", {})
        if ts.get("enabled", False):
            lines.append("")
            lines.append("// Trailing Stop")
            lines.append("SetPercentTrailing(TrailingStopPoints * BigPointValue, TrailingStopPoints * BigPointValue);")

        # Time exit
        te = exit_cfg.get("time_exit", {})
        if te.get("enabled", False):
            time_str = te.get("time", "13:30")
            time_val = time_str.replace(":", "")
            lines.append("")
            lines.append(f"// Time Exit - close before session end")
            lines.append(f"If Time >= {time_val} Then Begin")
            lines.append(f"    If MarketPosition = 1 Then")
            lines.append(f'        Sell ("{name}_TimeL") next bar at market;')
            lines.append(f"    If MarketPosition = -1 Then")
            lines.append(f'        BuyToCover ("{name}_TimeS") next bar at market;')
            lines.append("End;")

        return "\n".join(lines)

    def _build_risk_management(self, config: dict) -> str:
        """Build risk management code."""
        lines = []
        risk = config.get("risk", {})

        max_daily = risk.get("max_daily_loss", 0)
        if max_daily > 0:
            name = config.get("name", "Strategy")
            lines.append("// Max Daily Loss Protection")
            lines.append("If OpenPositionProfit <= -MaxDailyLoss * BigPointValue Then Begin")
            lines.append("    If MarketPosition = 1 Then")
            lines.append(f'        Sell ("{name}_MDL_L") next bar at market;')
            lines.append("    If MarketPosition = -1 Then")
            lines.append(f'        BuyToCover ("{name}_MDL_S") next bar at market;')
            lines.append("End;")

        return "\n".join(lines)

    def _translate_condition(self, condition: str) -> str:
        """Translate DSL condition string to PowerLanguage syntax.

        Input:  "fast_ma crosses_above slow_ma"
        Output: "fast_ma crosses above slow_ma"

        Handles 'and' / 'or' compound conditions.
        """
        # Handle compound conditions
        parts = []
        if " and " in condition:
            sub_conditions = condition.split(" and ")
            translated = [self._translate_condition(c.strip()) for c in sub_conditions]
            return " and " .join(translated)
        if " or " in condition:
            sub_conditions = condition.split(" or ")
            translated = [self._translate_condition(c.strip()) for c in sub_conditions]
            return " or ".join(translated)

        tokens = condition.strip().split()
        if len(tokens) == 3:
            left, op, right = tokens
            pl_op = CONDITION_OPS.get(op, op)
            return f"{left} {pl_op} {right}"

        return condition
