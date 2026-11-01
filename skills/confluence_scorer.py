"""
مهارت چهارم: امتیازدهی فازی (۰ تا ۱۰۰) + اعمال ضرایب یادگیری ماشین (Confluence Scorer Skill)
Institutional Trading Bot V2 - Multi-Factor Fuzzy Confluence Engine
"""

from typing import Dict, Any, Optional, List
from core.config import SCORING_RULES


class ConfluenceScorerSkill:
    """
    کلاس محاسبه امتیاز هم‌گرایی فازی از ۴ دسته شواهد (رژیم، ساختار ۱۵ دقیقه، نقدینگی/حجم،
    جریان سفارشات/زمان) و اعمال ضرایب تطبیقی یادگیری ماشین از strategy_memory.json.
    """

    def __init__(self) -> None:
        self.min_score_to_trade: float = float(SCORING_RULES.get("min_score_to_trade", 65.0))
        self.full_size_threshold: float = float(SCORING_RULES.get("full_size_score_threshold", 80.0))

    @staticmethod
    def _clean_coin_key(coin_or_symbol: str) -> str:
        clean = str(coin_or_symbol).strip().upper()
        if clean in ("PAXG/USDT", "PAXG", "XAUUSD", "GOLD", "XAU/USDT"):
            return "XAU"
        if "/" in clean:
            base = clean.split("/")[0]
            return "XAU" if base == "PAXG" else base
        return clean

    def evaluate_confluence(
        self,
        coin: str,
        candidate_side: str,
        regime_data: Dict[str, Any],
        scan_data: Dict[str, Any],
        orderbook_data: Dict[str, Any],
        killzone_data: Dict[str, Any],
        smt_data: Dict[str, Any],
        strategy_memory: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        محاسبه امتیاز خام، اعمال ضرایب یادگیری ماشین و تعیین وضعیت تایید و سایزینگ ستاپ.
        """
        side = str(candidate_side).strip().upper()
        coin_key = self._clean_coin_key(coin)

        if side not in ("LONG", "SHORT") or not bool(regime_data.get("tradable", True)):
            return {
                "passed": False,
                "raw_score": 0.0,
                "final_score": 0.0,
                "tier": "REJECTED",
                "size_multiplier": 0.0,
                "coin_multiplier": 1.0,
                "regime_multiplier": 1.0,
                "breakdown": {},
                "reasons": ["Market regime non-tradable or invalid candidate side"],
            }

        reasons: List[str] = []

        # ======================================================================
        # ۱. دسته اول: رژیم بازار (حداکثر ۲۸ امتیاز)
        # ======================================================================
        regime_score = 0.0
        regime = str(regime_data.get("regime", "RANGING")).upper()
        htf_bias = str(regime_data.get("htf_bias", "NEUTRAL")).upper()

        if (side == "LONG" and regime == "TRENDING_BULL") or (
            side == "SHORT" and regime == "TRENDING_BEAR"
        ):
            regime_score += 22.0
            reasons.append(f"Aligned with 1H trend ({regime}: +22)")
        elif regime == "RANGING":
            regime_score += 18.0
            reasons.append("Tradable 1H ranging structure (+18)")

        if (side == "LONG" and htf_bias == "BULLISH") or (
            side == "SHORT" and htf_bias == "BEARISH"
        ):
            regime_score += 6.0
            reasons.append(f"Confirmed by 4H macro bias ({htf_bias}: +6)")
        elif htf_bias == "NEUTRAL":
            regime_score += 3.0
            reasons.append("Neutral 4H macro bias (+3)")

        # ======================================================================
        # ۲. دسته دوم: ساختار ۱۵ دقیقه (حداکثر ۳۴ امتیاز)
        # ======================================================================
        structure_score = 0.0
        near_fvg = bool(scan_data.get("near_fvg", False))
        range_pos = float(scan_data.get("range_position_pct", 50.0))

        if near_fvg:
            structure_score += 18.0
            reasons.append("Price inside/near unmitigated 15m FVG (+18)")

        if side == "LONG":
            if range_pos <= 30.0:
                structure_score += 16.0
                reasons.append(f"Deep Discount zone ({range_pos:.1f}% <= 30%: +16)")
            elif range_pos <= 50.0:
                structure_score += 10.0
                reasons.append(f"Lower half of range ({range_pos:.1f}% <= 50%: +10)")
        else:  # SHORT
            if range_pos >= 70.0:
                structure_score += 16.0
                reasons.append(f"Deep Premium zone ({range_pos:.1f}% >= 70%: +16)")
            elif range_pos >= 50.0:
                structure_score += 10.0
                reasons.append(f"Upper half of range ({range_pos:.1f}% >= 50%: +10)")

        # ======================================================================
        # ۳. دسته سوم: نقدینگی و حجم نهنگ (حداکثر ۲۱ امتیاز)
        # ======================================================================
        liquidity_score = 0.0
        sweep_type = str(scan_data.get("sweep_type", "NONE")).upper()
        vol_spike = float(scan_data.get("volume_spike", 1.0))

        aligned_sweep = (side == "LONG" and sweep_type == "BULLISH_SWEEP") or (
            side == "SHORT" and sweep_type == "BEARISH_SWEEP"
        )

        if aligned_sweep:
            liquidity_score += 16.0
            reasons.append(f"Aligned 15m liquidity sweep ({sweep_type}: +16)")
            if vol_spike >= 1.30:
                liquidity_score += 5.0
                reasons.append(f"Whale volume on sweep ({vol_spike:.2f}x >= 1.3x: +5)")
        else:
            if vol_spike >= 1.25:
                liquidity_score += 6.0
                reasons.append(f"Standalone volume spike ({vol_spike:.2f}x >= 1.25x: +6)")

        # ======================================================================
        # ۴. دسته چهارم: جریان سفارشات، SMT و زمان (حداکثر ۲۸ امتیاز)
        # ======================================================================
        flow_score = 0.0
        buy_pressure = float(orderbook_data.get("buy_pressure_pct", 50.0))

        if side == "LONG":
            if buy_pressure >= 53.0:
                flow_score += 10.0
                reasons.append(f"Bullish OrderBook pressure ({buy_pressure:.1f}% >= 53%: +10)")
            elif 47.0 <= buy_pressure < 53.0:
                flow_score += 5.0
                reasons.append(f"Balanced OrderBook ({buy_pressure:.1f}%: +5)")
        else:  # SHORT
            if buy_pressure <= 47.0:
                flow_score += 10.0
                reasons.append(f"Bearish OrderBook pressure ({buy_pressure:.1f}% <= 47%: +10)")
            elif 47.0 < buy_pressure <= 53.0:
                flow_score += 5.0
                reasons.append(f"Balanced OrderBook ({buy_pressure:.1f}%: +5)")

        smt_div = str(smt_data.get("smt_divergence", "NONE")).upper()
        if (side == "LONG" and smt_div == "BULLISH_SMT") or (
            side == "SHORT" and smt_div == "BEARISH_SMT"
        ):
            flow_score += 8.0
            reasons.append(f"Confirmed by {smt_div} divergence (+8)")

        kz_bonus = float(killzone_data.get("score_bonus", 0.0))
        kz_session = str(killzone_data.get("session", "UNKNOWN"))
        if kz_bonus > 0:
            flow_score += kz_bonus
            reasons.append(f"Active session bonus ({kz_session}: +{kz_bonus:.0f})")

        # ======================================================================
        # ۵. اعمال ضرایب یادگیری ماشین بیزی (ML Multipliers)
        # ======================================================================
        raw_score = regime_score + structure_score + liquidity_score + flow_score

        mem = strategy_memory or {}
        coin_mults = mem.get("coin_multipliers", {})
        reg_weights = mem.get("regime_weights", {})

        coin_mult = float(coin_mults.get(coin_key, 1.0))
        reg_mult = float(reg_weights.get(regime, 1.0))

        adjusted_score = raw_score * coin_mult * reg_mult
        final_score = round(min(100.0, max(0.0, adjusted_score)), 2)

        # ======================================================================
        # ۶. تعیین طبقه سایزینگ و وضعیت عبور از فیلتر
        # ======================================================================
        if final_score >= self.full_size_threshold:
            passed = True
            tier = "FULL_SIZE (100%)"
            size_multiplier = 1.0
        elif final_score >= self.min_score_to_trade:
            passed = True
            tier = "STANDARD_SIZE (75%)"
            size_multiplier = 0.75
        else:
            passed = False
            tier = "REJECTED"
            size_multiplier = 0.0

        return {
            "passed": passed,
            "raw_score": round(raw_score, 2),
            "final_score": final_score,
            "tier": tier,
            "size_multiplier": size_multiplier,
            "coin_multiplier": round(coin_mult, 4),
            "regime_multiplier": round(reg_mult, 4),
            "breakdown": {
                "regime_score": round(regime_score, 2),
                "structure_score": round(structure_score, 2),
                "liquidity_score": round(liquidity_score, 2),
                "flow_score": round(flow_score, 2),
            },
            "reasons": reasons,
        }