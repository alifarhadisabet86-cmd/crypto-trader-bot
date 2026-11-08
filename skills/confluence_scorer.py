"""
مهارت چهارم (نسخه V2.6 Pro): موتور امتیازدهی فازی ۰ تا ۱۰۰ به همراه دلایل فارسی X-Ray و قطب‌نمای لیدر BTC
Institutional Trading Bot V2.6 Pro - Fuzzy Confluence Scorer, BTC Lead-Lag Filter & X-Ray Breakdown
"""

from typing import Dict, Any, List, Optional
import numpy as np

from core.config import RISK_CONFIG


class ConfluenceScorerSkill:
    """
    کلاس محاسبه امتیاز هم‌گرایی فازی (۰ تا ۱۰۰) به همراه استخراج دلایل فارسی X-Ray
    جهت نمایش در کپشن شکار سازمانی تلگرام.
    """

    def __init__(self) -> None:
        self.min_score: float = float(RISK_CONFIG["MIN_CONFLUENCE_SCORE"])
        self.golden_score: float = float(RISK_CONFIG["GOLDEN_SLOTS_MIN_SCORE"])

    def evaluate_confluence(
        self,
        coin: str,
        candidate_side: str,
        regime_data: Dict[str, Any],
        scan_data: Dict[str, Any],
        orderbook_data: Optional[Dict[str, Any]] = None,
        killzone_data: Optional[Dict[str, Any]] = None,
        smt_data: Optional[Dict[str, Any]] = None,
        strategy_memory: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        side = str(candidate_side).upper().strip()
        if side not in ("LONG", "SHORT") or not regime_data.get("tradable", False):
            return self._build_result(0.0, 0.0, 1.0, 1.0, {}, [], "NON_TRADABLE_OR_NO_SIDE")

        xray_reasons: List[str] = []
        coin_key = str(coin).upper().strip()

        # ۱. امتیاز هم‌راستایی رژیم و روند (حداکثر ۳۰ امتیاز)
        regime_score = self._score_regime_alignment(side, regime_data, xray_reasons)

        # ۲. امتیاز ساختار ۱۵ دقیقه: FVG + Discount/Premium + Asian Sweep (حداکثر ۳۰ امتیاز)
        structure_score = self._score_15m_structure(side, scan_data, xray_reasons)

        # ۳. امتیاز نقدینگی و شکار استاپ + حجم (حداکثر ۲۰ امتیاز)
        liquidity_score = self._score_liquidity_and_volume(side, scan_data, xray_reasons)

        # ۴. امتیاز جریان سفارشات، سشن Killzone، واگرایی SMT و قطب‌نمای لیدر BTC (حداکثر ۲۰ امتیاز)
        flow_score = self._score_orderflow_and_intel(
            coin_key, side, orderbook_data or {}, killzone_data or {}, smt_data or {}, xray_reasons
        )

        raw_score = float(
            np.clip(
                regime_score + structure_score + liquidity_score + flow_score,
                0.0,
                100.0,
            )
        )

        # ۵. اعمال ضرایب یادگیری ماشین
        regime_name = str(regime_data.get("regime", "RANGING"))

        coin_mult = 1.0
        regime_mult = 1.0
        if isinstance(strategy_memory, dict):
            coin_mult = float(strategy_memory.get("coin_multipliers", {}).get(coin_key, 1.0))
            regime_mult = float(strategy_memory.get("regime_multipliers", {}).get(regime_name, 1.0))

        coin_mult = float(np.clip(coin_mult, 0.80, 1.15))
        regime_mult = float(np.clip(regime_mult, 0.85, 1.12))

        final_score = float(np.clip(raw_score * coin_mult * regime_mult, 0.0, 100.0))

        breakdown = {
            "regime_alignment": round(regime_score, 2),
            "structure_15m": round(structure_score, 2),
            "liquidity_volume": round(liquidity_score, 2),
            "orderflow_intel": round(flow_score, 2),
        }

        return self._build_result(
            raw_score=raw_score,
            final_score=final_score,
            coin_mult=coin_mult,
            regime_mult=regime_mult,
            breakdown=breakdown,
            xray_reasons=xray_reasons,
            reason="OK",
        )

    @staticmethod
    def _score_regime_alignment(
        side: str, regime_data: Dict[str, Any], xray_reasons: List[str]
    ) -> float:
        score = 0.0
        regime = regime_data.get("regime", "RANGING")
        htf_bias = regime_data.get("htf_bias", "NEUTRAL")
        adx = float(regime_data.get("adx", regime_data.get("trend_strength", 20.0)))

        if (side == "LONG" and regime == "TRENDING_BULL") or (
            side == "SHORT" and regime == "TRENDING_BEAR"
        ):
            adx_bonus = float(np.clip((adx - 20.0) * 0.2, 0.0, 4.0))
            pts = round(20.0 + adx_bonus, 1)
            score += pts
            xray_reasons.append(f"هم‌راستا با روند ۱ ساعته (+{pts:.0f})")
        elif regime == "RANGING":
            score += 14.0
            xray_reasons.append("ساختار بازگشت به میانگین رنج (+14)")
        else:
            score += 0.0

        if (side == "LONG" and htf_bias == "BULLISH") or (
            side == "SHORT" and htf_bias == "BEARISH"
        ):
            score += 6.0
            xray_reasons.append("حمایت ساختار ۴ ساعته (+6)")
        elif htf_bias == "NEUTRAL":
            score += 3.0

        return float(np.clip(score, 0.0, 30.0))

    @staticmethod
    def _score_15m_structure(
        side: str, scan_data: Dict[str, Any], xray_reasons: List[str]
    ) -> float:
        score = 0.0
        current_price = float(scan_data.get("current_price", 0.0))
        atr = max(float(scan_data.get("atr_15m", 1.0)), 1e-8)
        range_pct = float(scan_data.get("range_position_pct", 50.0))
        active_fvg = scan_data.get("active_fvg")

        if isinstance(active_fvg, dict):
            fvg_type = active_fvg.get("type")
            if (side == "LONG" and fvg_type == "BULLISH") or (
                side == "SHORT" and fvg_type == "BEARISH"
            ):
                top = float(active_fvg["top"])
                bottom = float(active_fvg["bottom"])
                if bottom <= current_price <= top:
                    score += 18.0
                    xray_reasons.append("حضور قیمت در ناحیه FVG دست‌نخورده (+18)")
                else:
                    dist = min(abs(current_price - top), abs(current_price - bottom))
                    proximity_factor = float(np.clip(1.0 - (dist / (2.0 * atr)), 0.2, 0.9))
                    pts = round(18.0 * proximity_factor, 1)
                    score += pts
                    xray_reasons.append(f"مجاورت با FVG معتبر (+{pts:.0f})")

        if side == "LONG":
            zone_score = float(np.clip(((60.0 - range_pct) / 40.0) * 12.0, 0.0, 12.0))
            if zone_score >= 6.0:
                xray_reasons.append(f"ناحیه ارزان‌فروشی Discount (+{zone_score:.0f})")
        else:
            zone_score = float(np.clip(((range_pct - 40.0) / 40.0) * 12.0, 0.0, 12.0))
            if zone_score >= 6.0:
                xray_reasons.append(f"ناحیه گران‌فروشی Premium (+{zone_score:.0f})")

        score += zone_score
        return float(np.clip(score, 0.0, 30.0))

    @staticmethod
    def _score_liquidity_and_volume(
        side: str, scan_data: Dict[str, Any], xray_reasons: List[str]
    ) -> float:
        score = 0.0
        sweep = scan_data.get("liquidity_sweep", "NONE")
        asian_sweep = scan_data.get("asian_range", {}).get("asian_sweep", "NONE")
        vol_ratio = float(scan_data.get("volume_ratio", 1.0))

        if (side == "LONG" and sweep == "BULLISH_SWEEP") or (
            side == "SHORT" and sweep == "BEARISH_SWEEP"
        ):
            score += 12.0
            xray_reasons.append("شکار نقدینگی و استاپ‌هانت ۱۵m (+12)")
        elif (side == "LONG" and asian_sweep == "ASIAN_LOW_SWEEP_BULL") or (
            side == "SHORT" and asian_sweep == "ASIAN_HIGH_SWEEP_BEAR"
        ):
            score += 11.0
            xray_reasons.append("شکار نقدینگی سشن آسیا (+11)")
        elif sweep == "NONE":
            score += 4.0

        vol_pts = float(np.clip((vol_ratio - 0.7) * 8.0, 0.0, 8.0))
        score += vol_pts
        if vol_pts >= 4.5:
            xray_reasons.append(f"حجم تراکنش بالاتر از میانگین (+{vol_pts:.0f})")

        return float(np.clip(score, 0.0, 20.0))

    @staticmethod
    def _score_orderflow_and_intel(
        coin_key: str,
        side: str,
        orderbook_data: Dict[str, Any],
        killzone_data: Dict[str, Any],
        smt_data: Dict[str, Any],
        xray_reasons: List[str],
    ) -> float:
        score = 0.0
        buy_pressure = float(orderbook_data.get("buy_pressure_pct", 50.0))
        if side == "LONG":
            ob_pts = float(np.clip(((buy_pressure - 45.0) / 20.0) * 7.0, 1.0, 7.0))
        else:
            sell_pressure = 100.0 - buy_pressure
            ob_pts = float(np.clip(((sell_pressure - 45.0) / 20.0) * 7.0, 1.0, 7.0))
        score += ob_pts
        if ob_pts >= 4.5:
            xray_reasons.append(f"تایید فشار اردربوک صرافی (+{ob_pts:.0f})")

        kz_bonus = float(killzone_data.get("score_bonus", 4.0))
        kz_pts = float(np.clip(kz_bonus * 0.7, 1.5, 7.0))
        score += kz_pts
        if killzone_data.get("in_killzone"):
            xray_reasons.append(f"سشن Killzone فعال (+{kz_pts:.0f})")

        if (side == "LONG" and smt_data.get("bullish_smt")) or (
            side == "SHORT" and smt_data.get("bearish_smt")
        ):
            score += 6.0
            xray_reasons.append("واگرایی پول هوشمند SMT (+6)")
        elif smt_data.get("smt_divergence") == "NONE":
            score += 2.0

        # قطب‌نمای رهبری بیت‌کوین برای آلت‌کوین‌ها (BTC Lead-Lag Filter)
        btc_impulse = str(smt_data.get("btc_impulse", "NEUTRAL"))
        if coin_key in ("ETH", "SOL", "XRP"):
            if side == "LONG" and btc_impulse == "STRONG_DUMP":
                score -= 10.0
                xray_reasons.append("⚠️ ریزش شارپ لیدر BTC (-10)")
            elif side == "SHORT" and btc_impulse == "STRONG_PUMP":
                score -= 10.0
                xray_reasons.append("⚠️ پامپ شارپ لیدر BTC (-10)")
            elif (side == "LONG" and btc_impulse == "STRONG_PUMP") or (
                side == "SHORT" and btc_impulse == "STRONG_DUMP"
            ):
                score += 3.0
                xray_reasons.append("هم‌سو با مومنتوم لیدر BTC (+3)")

        return float(np.clip(score, -10.0, 20.0))

    def _build_result(
        self,
        raw_score: float,
        final_score: float,
        coin_mult: float,
        regime_mult: float,
        breakdown: Dict[str, float],
        xray_reasons: List[str],
        reason: str,
    ) -> Dict[str, Any]:
        if final_score >= self.golden_score:
            tier = "FULL_SIZE"
            size_multiplier = 1.0
            passed = True
        elif final_score >= self.min_score:
            tier = "STANDARD_SIZE"
            size_multiplier = 0.75
            passed = True
        else:
            tier = "REJECTED"
            size_multiplier = 0.0
            passed = False

        xray_str = " | ".join(xray_reasons) if xray_reasons else "بدون تاییدیه ساختاری کافی"

        return {
            "passed": passed,
            "raw_score": round(raw_score, 2),
            "final_score": round(final_score, 2),
            "tier": tier,
            "size_multiplier": size_multiplier,
            "coin_multiplier": round(coin_mult, 4),
            "regime_multiplier": round(regime_mult, 4),
            "breakdown": breakdown,
            "xray_reasons": xray_reasons,
            "xray_summary_fa": xray_str,
            "reason": reason,
        }
