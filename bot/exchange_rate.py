"""
جلب سعر صرف الدولار مقابل الليرة السورية من موقع liratoday.com تلقائياً.
يُحدَّث كل ساعة ويُحفظ في DB.
"""
import logging
import re
import asyncio
import requests

from . import config, database as db

logger = logging.getLogger(__name__)

LIRATODAY_URL = "https://liratoday.com/syrian-pound.html"
REQUEST_TIMEOUT = 15


def _fetch_rate_from_site() -> float:
    """
    يجلب سعر الدولار من موقع الليرة اليوم (liratoday.com).
    يرجع سعر الشراء (السعر الأول بعد "دولار أمريكي").
    """
    resp = requests.get(LIRATODAY_URL, timeout=REQUEST_TIMEOUT, headers={
        "User-Agent": "Mozilla/5.0 (compatible; Bot/1.0)"
    })
    resp.raise_for_status()
    html = resp.text

    # نبحث عن سعر الدولار: <span>دولار أمريكي</span> ثم أول <strong>رقم</strong>
    match = re.search(
        r'دولار أمريكي.*?<strong>([\d,\.]+)</strong>',
        html,
        re.DOTALL
    )
    if not match:
        raise ValueError("لم يتم العثور على سعر الدولار في الصفحة")

    rate_str = match.group(1).replace(",", "")
    rate = float(rate_str)

    if rate < 1000 or rate > 200000:
        raise ValueError(f"سعر غير منطقي من الموقع: {rate}")

    return rate


async def update_rate_from_site() -> dict:
    """
    يجلب السعر من الموقع ويحفظه في DB.
    يرجع: {"rate": float, "changed": bool, "old_rate": float}
    """
    old_rate = config.get_syp_per_usd()

    try:
        new_rate = await asyncio.to_thread(_fetch_rate_from_site)
    except Exception as e:
        logger.warning("فشل جلب سعر الصرف من liratoday.com: %s", e)
        raise

    changed = abs(new_rate - old_rate) >= 1.0
    if changed:
        db.set_setting("syp_per_usd", str(new_rate))
        logger.info("تم تحديث سعر الصرف: %.2f → %.2f", old_rate, new_rate)
    else:
        logger.info("سعر الصرف لم يتغير: %.2f", new_rate)

    return {"rate": new_rate, "changed": changed, "old_rate": old_rate}
