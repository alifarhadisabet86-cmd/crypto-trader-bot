"""
ماژول مدیریت ۵ اسلات هوشمند و سپر همبستگی (Slot Manager & Correlation Shield)
Institutional Trading Bot V2.5 - Smart Slot Matrix
"""

from typing import Dict, Any, List, Optional

from core.config import WATCHLIST, RISK_RULES


def _extract_coin_key(coin_or_symbol: str) -> str:
    """استخراج کلید استاندارد دارایی (مثلاً BTC یا XAU) از نماد یا نام ارز."""
    clean = str(coin_or_symbol).strip().upper()
    if clean in ("PAXG/USDT", "PAXG", "XAUUSD", "GOLD", "XAU/USDT"):
        return "XAU"
    if "/" in clean:
        base = clean.split("/")[0]
        return "XAU" if base == "PAXG" else base
    return clean


def _is_crypto_asset(coin_key: str) -> bool:
    """بررسی اینکه آیا دارایی جزو گروه کریپتو است یا دارایی امن (طلا)."""
    info = WATCHLIST.get(coin_key, {})
    corr_group = str(info.get("correlated_group") or info.get("correlation_group", "CRYPTO_HIGH"))
    category = str(info.get("category", "CRYPTO_MAJOR"))
    if coin_key == "XAU" or "SAFE_HAVEN" in corr_group or category == "COMMODITY":
        return False
    return True


def can_open_new_position(
    open_positions: List[Dict[str, Any]],
    candidate_coin: str,
    candidate_side: str,
    candidate_score: float = 0.0,
    confluence_score: Optional[float] = None,
) -> Dict[str, Any]:
    """
    بررسی امکان باز کردن پوزیشن جدید بر اساس ماتریس ۵ اسلات هوشمند و سپر همبستگی.

    خروجی:
        Dict شامل:
        - allowed (bool): آیا مجوز باز کردن پوزیشن صادر می‌شود؟
        - reason (str): کد وضعیت یا دلیل رد شدن
        - details (str): توضیح کامل فارسی/انگلیسی برای لاگ و رادار سایه
        - slot_metrics (dict): آمار لحظه‌ای اسلات‌ها
    """
    max_pos: int = int(RISK_RULES.get("MAX_OPEN_POSITIONS", RISK_RULES.get("max_concurrent_positions", 5)))
    max_normal_slots: int = int(RISK_RULES.get("STANDARD_SLOTS", RISK_RULES.get("max_normal_score_slots", 3)))
    golden_threshold: float = float(RISK_RULES.get("GOLDEN_SLOTS_MIN_SCORE", RISK_RULES.get("golden_score_threshold", 80.0)))
    max_crypto_same_side: int = int(RISK_RULES.get("MAX_CORRELATED_ALTS", RISK_RULES.get("max_crypto_correlated_same_side", 3)))

    cand_key = _extract_coin_key(candidate_coin)
    cand_side = str(candidate_side).strip().upper()
    cand_score = float(confluence_score if confluence_score is not None else candidate_score)

    # ۱. بررسی عدم وجود پوزیشن باز تکراری روی همین نماد
    for pos in open_positions:
        pos_coin = _extract_coin_key(pos.get("coin") or pos.get("symbol", ""))
        if pos_coin == cand_key:
            return {
                "allowed": False,
                "reason": "DUPLICATE_SYMBOL",
                "details": f"Active position already exists on {cand_key}.",
                "slot_metrics": _build_slot_metrics(open_positions, max_pos),
            }

    # ۲. بررسی سقف مطلق تعداد کل پوزیشن‌های باز (۵ اسلات)
    total_open = len(open_positions)
    if total_open >= max_pos:
        return {
            "allowed": False,
            "reason": "MAX_SLOTS_FULL",
            "details": f"All {max_pos}/{max_pos} portfolio slots are currently occupied.",
            "slot_metrics": _build_slot_metrics(open_positions, max_pos),
        }

    # ۳. تفکیک پوزیشن‌های دارای ریسک فعال (آن‌هایی که هنوز به TP1/Risk-Free نرسیده‌اند)
    active_risk_positions = [
        p for p in open_positions
        if not bool(p.get("tp1_hit", False) or p.get("is_risk_free", False) or p.get("risk_free", False))
    ]
    active_risk_count = len(active_risk_positions)

    # ۴. قانون رزرو اسلات برای ستاپ‌های طلایی (Score >= golden_threshold)
    if cand_score < golden_threshold:
        if active_risk_count >= max_normal_slots:
            return {
                "allowed": False,
                "reason": "RESERVED_FOR_GOLDEN_SETUP",
                "details": (
                    f"Score {cand_score:.1f} < {golden_threshold:.1f}: Normal setups capped at "
                    f"{max_normal_slots} active-risk slots (remaining slots reserved for Golden Setups)."
                ),
                "slot_metrics": _build_slot_metrics(open_positions, max_pos),
            }

    # ۵. سپر همبستگی (Correlation Shield) برای گروه کریپتو (BTC, ETH, SOL, XRP)
    if _is_crypto_asset(cand_key):
        same_side_crypto_active = [
            p
            for p in active_risk_positions
            if _is_crypto_asset(_extract_coin_key(p.get("coin") or p.get("symbol", "")))
            and str(p.get("side", "")).strip().upper() == cand_side
        ]
        if len(same_side_crypto_active) >= max_crypto_same_side:
            return {
                "allowed": False,
                "reason": "CORRELATION_SHIELD_BLOCKED",
                "details": (
                    f"Correlation Shield: Already {len(same_side_crypto_active)} active-risk {cand_side} "
                    f"crypto positions open (Max {max_crypto_same_side}). Remaining slots reserved for Hedge or XAU."
                ),
                "slot_metrics": _build_slot_metrics(open_positions, max_pos),
            }

    # صدور مجوز نهایی
    slot_type = "GOLDEN_SLOT" if cand_score >= golden_threshold else "STANDARD_SLOT"
    return {
        "allowed": True,
        "reason": "SLOT_APPROVED",
        "slot_type": slot_type,
        "details": f"Slot approved ({slot_type}) for {cand_key} {cand_side} (Score: {cand_score:.1f}).",
        "slot_metrics": _build_slot_metrics(open_positions, max_pos),
    }


def _build_slot_metrics(open_positions: List[Dict[str, Any]], max_pos: int) -> Dict[str, int]:
    """محاسبه آمار لحظه‌ای اسلات‌های کل، ریسک‌فری شده و دارای ریسک فعال."""
    total_open = len(open_positions)
    risk_free_count = sum(
        1 for p in open_positions
        if bool(p.get("tp1_hit", False) or p.get("is_risk_free", False) or p.get("risk_free", False))
    )
    active_risk_count = total_open - risk_free_count
    return {
        "max_slots": max_pos,
        "total_open": total_open,
        "active_risk_slots": active_risk_count,
        "risk_free_slots": risk_free_count,
        "available_slots": max(0, max_pos - total_open),
    }
