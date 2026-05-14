"""
المهام المجدولة: تقارير يومية، فحص أسعار، تحديث الرصيد، التحويلات التلقائية
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from telegram.ext import Application, ContextTypes

from . import config, database as db, usdt
from . import database
from .notify import notify_admin

logger = logging.getLogger(__name__)


# ==================== دوال مساعدة ====================

async def _send_admin(app: Application, text: str) -> None:
    """يرسل رسالة للأدمن عبر البوت."""
    if config.ADMIN_ID:
        try:
            await app.bot.send_message(chat_id=config.ADMIN_ID, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send message to admin: {e}")


def _since_iso(days: int = 0, hours: int = 0) -> str:
    """يرجع ISO timestamp لـ X يوم/ساعة قبل الآن (UTC)."""
    dt = datetime.now(timezone.utc) - timedelta(days=days, hours=hours)
    return dt.replace(tzinfo=None).isoformat()


def _today_start_iso() -> str:
    """بداية اليوم الحالي UTC (منتصف الليل)."""
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    return midnight.isoformat()


def _fmt_syp(val: float) -> str:
    return f"{val:,.0f}".replace(",", "،")


# ==================== تقرير اليوم ====================

async def build_today_report() -> str:
    """يبني نص تقرير اليوم (يُستدعى من زر الأدمن)."""
    since = _today_start_iso()

    stats = await asyncio.to_thread(db.get_sales_stats_since, since)
    global_stats = await asyncio.to_thread(db.get_stats)

    rate = config.get_usd_to_syp()
    revenue = float(stats.get("total_revenue_syp") or 0)
    cost_usd = float(stats.get("total_cost_usd") or 0)
    cost_syp = cost_usd * rate
    profit = revenue - cost_syp
    margin = (profit / revenue * 100) if revenue > 0 else 0.0

    completed = int(stats.get("completed") or 0)
    refunded = int(stats.get("refunded") or 0)
    pending = int(stats.get("pending") or 0)

    by_game: Dict[str, Any] = stats.get("by_game") or {}

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "📊 *تقرير اليوم*",
        "━━━━━━━━━━━━━━━━━",
        f"🕐 التوقيت: `{now_str}`",
        "",
        "💰 *المبيعات:*",
        f"  ✅ مكتمل: *{completed}* طلب — {_fmt_syp(revenue)} ل.س",
        f"  ❌ مرفوض: {refunded}   |   ⏳ معلق: {pending}",
        "",
        "📈 *الأرباح:*",
        f"  💵 إيرادات: *{_fmt_syp(revenue)}* ل.س",
        f"  💸 تكلفة:   {_fmt_syp(cost_syp)} ل.س",
        f"  📊 صافي:   *{_fmt_syp(profit)}* ل.س  ({margin:.1f}%)",
        "",
    ]

    if by_game:
        lines.append("🎮 *تفصيل بحسب الفئة:*")
        for game, data in sorted(by_game.items(), key=lambda x: -x[1]["revenue"])[:8]:
            lines.append(
                f"  • {game}: {data['count']} طلب — {_fmt_syp(data['revenue'])} ل.س"
            )
        lines.append("")

    lines += [
        "👥 *الإجماليات:*",
        f"  المستخدمين الكلي: *{global_stats['users']}*",
        f"  الطلبات الكلية:   *{global_stats['orders']}*",
    ]

    return "\n".join(lines)


# ==================== تقارير الأرباح ====================

async def _build_profit_report(label: str, since_iso: str) -> str:
    """دالة مساعدة تبني تقرير الأرباح لفترة معيّنة."""
    stats = await asyncio.to_thread(db.get_sales_stats_since, since_iso)

    rate = config.get_usd_to_syp()
    revenue = float(stats.get("total_revenue_syp") or 0)
    cost_usd = float(stats.get("total_cost_usd") or 0)
    cost_syp = cost_usd * rate
    profit = revenue - cost_syp
    margin = (profit / revenue * 100) if revenue > 0 else 0.0
    completed = int(stats.get("completed") or 0)
    by_game: Dict[str, Any] = stats.get("by_game") or {}

    lines = [
        f"💵 *تقرير الأرباح — {label}*",
        "━━━━━━━━━━━━━━━━━",
        "",
        f"📦 طلبات مكتملة: *{completed}*",
        f"💰 إيرادات:      *{_fmt_syp(revenue)}* ل.س",
        f"💸 تكلفة (USD):  ${cost_usd:.2f} ≈ {_fmt_syp(cost_syp)} ل.س",
        f"📊 ربح صافي:    *{_fmt_syp(profit)}* ل.س",
        f"📈 هامش الربح:   *{margin:.1f}%*",
        "",
        f"_(سعر الدولار المستخدم: {_fmt_syp(rate)} ل.س/$)_",
    ]

    if by_game:
        lines.append("")
        lines.append("🎮 *تفصيل بحسب الفئة:*")
        for game, data in sorted(by_game.items(), key=lambda x: -x[1]["revenue"])[:10]:
            r = _fmt_syp(data["revenue"])
            lines.append(f"  • {game}: {data['count']} طلب — {r} ل.س")

    return "\n".join(lines)


async def build_profit_today() -> str:
    return await _build_profit_report("اليوم", _today_start_iso())


async def build_profit_week() -> str:
    return await _build_profit_report("آخر 7 أيام", _since_iso(days=7))


async def build_profit_month() -> str:
    return await _build_profit_report("آخر 30 يوم", _since_iso(days=30))


async def build_profit_all_time() -> str:
    return await _build_profit_report("كل الفترة", "2000-01-01T00:00:00")


# ==================== فحص الأسعار ====================

async def compute_price_check_data() -> Dict[str, Any]:
    """
    يجلب أسعار Fastcard الحالية ويقارنها بأسعار config.
    يرجع dict:
    {
        ok: bool,
        error: str|None,
        rate: float,          # سعر صرف الدولار المستخدم
        loss: [...],          # منتجات ببيع بخسارة
        thin: [...],          # منتجات بربح أقل من 5%
        ok_items: [...],      # منتجات بأسعار صحيحة
        fc_balance: float,    # رصيد Fastcard
    }
    كل عنصر في القوائم: {label, product_id, config_price, fc_cost_usd, fc_cost_syp, margin_pct, suggested_price}
    """
    from . import fastcard

    if not fastcard.is_enabled():
        return {"ok": False, "error": "Fastcard غير مفعّل (FASTCARD_TOKEN فاضي)"}

    # جلب رصيد ومنتجات Fastcard
    try:
        profile = await asyncio.to_thread(fastcard.get_profile)
        fc_balance = float(profile.get("balance") or 0)
    except Exception as e:
        fc_balance = 0.0
        logger.warning("compute_price_check: get_profile failed: %s", e)

    # جمع كل العروض التي فيها product_id + cost_usd
    priced_offers = config.collect_priced_offers()
    if not priced_offers:
        return {"ok": True, "loss": [], "thin": [], "ok_items": [], "fc_balance": fc_balance,
                "rate": config.get_syp_per_usd(), "error": None}

    # جلب أسعار Fastcard للمنتجات المحددة
    product_ids = [o["product_id"] for o in priced_offers]
    try:
        fc_products_raw = await asyncio.to_thread(fastcard.get_products, product_ids)
    except Exception as e:
        return {"ok": False, "error": f"فشل جلب منتجات Fastcard: {e}"}

    # بناء قاموس product_id -> price (USD)
    fc_price_map: Dict[int, float] = {}
    for p in fc_products_raw:
        pid = p.get("id")
        price = p.get("price")
        if pid and price is not None:
            try:
                fc_price_map[int(pid)] = float(price)
            except (ValueError, TypeError):
                pass

    rate = config.get_syp_per_usd()
    target_margin = 0.12  # هامش الربح المستهدف 12%
    warn_margin = 0.05    # تحذير لو الهامش أقل من 5%

    loss: List[Dict[str, Any]] = []
    thin: List[Dict[str, Any]] = []
    ok_items: List[Dict[str, Any]] = []

    for offer in priced_offers:
        pid = offer["product_id"]
        label = offer["label"]
        config_price = config.get_offer_price(offer["raw_offer"])

        fc_cost_usd = fc_price_map.get(pid)
        if fc_cost_usd is None:
            # منتج غير موجود على Fastcard — نتجاهله
            continue

        qty = offer["raw_offer"].get("qty", 1) or 1
        fc_cost_syp = float(fc_cost_usd) * float(qty) * rate
        suggested_price = config.round_up_to_500(fc_cost_syp * (1 + target_margin))

        if config_price <= 0:
            margin_pct = -999.0
        else:
            margin_pct = (config_price - fc_cost_syp) / config_price * 100

        item = {
            "label": label,
            "product_id": pid,
            "offer_id": offer.get("id"),
            "config_price": config_price,
            "fc_cost_usd": fc_cost_usd,
            "fc_cost_syp": fc_cost_syp,
            "margin_pct": margin_pct,
            "suggested_price": suggested_price,
        }

        if margin_pct < 0:
            loss.append(item)
        elif margin_pct < warn_margin * 100:
            thin.append(item)
        else:
            ok_items.append(item)

    return {
        "ok": True,
        "error": None,
        "rate": rate,
        "fc_balance": fc_balance,
        "loss": loss,
        "thin": thin,
        "ok_items": ok_items,
    }


def format_price_check_report(data: Dict[str, Any]) -> str:
    """يُحوّل نتيجة compute_price_check_data إلى نص تقرير جاهز للإرسال."""
    if not data.get("ok"):
        return f"❌ *فحص الأسعار فشل*\n\n`{data.get('error', 'خطأ غير معروف')}`"

    rate = float(data.get("rate") or 0)
    fc_balance = float(data.get("fc_balance") or 0)
    loss: List[Dict[str, Any]] = data.get("loss") or []
    thin: List[Dict[str, Any]] = data.get("thin") or []
    ok_items: List[Dict[str, Any]] = data.get("ok_items") or []
    total = len(loss) + len(thin) + len(ok_items)

    lines = [
        "🔍 *فحص أسعار Fastcard*",
        "━━━━━━━━━━━━━━━━━",
        f"💵 رصيد Fastcard: *${fc_balance:.4f}*",
        f"📊 سعر الصرف: `{_fmt_syp(rate)} ل.س/$`",
        f"📦 منتجات مفحوصة: *{total}*",
        "",
    ]

    if loss:
        lines.append(f"🆘 *منتجات خاسرة ({len(loss)}):*")
        for item in loss[:10]:
            lines.append(
                f"  • {item['label'][:40]}\n"
                f"    بيع: {_fmt_syp(item['config_price'])} ل.س | "
                f"تكلفة: {_fmt_syp(item['fc_cost_syp'])} ل.س | "
                f"هامش: *{item['margin_pct']:.1f}%* ⚠️"
            )
        if len(loss) > 10:
            lines.append(f"  _... و {len(loss) - 10} منتجات إضافية_")
        lines.append("")

    if thin:
        lines.append(f"⚠️ *منتجات بربح ضعيف ({len(thin)}):*")
        for item in thin[:10]:
            lines.append(
                f"  • {item['label'][:40]}\n"
                f"    بيع: {_fmt_syp(item['config_price'])} ل.س | "
                f"هامش: {item['margin_pct']:.1f}%"
            )
        if len(thin) > 10:
            lines.append(f"  _... و {len(thin) - 10} منتجات إضافية_")
        lines.append("")

    if ok_items:
        lines.append(f"✅ *منتجات بأسعار صحيحة: {len(ok_items)}*")
        lines.append("")

    if not loss and not thin:
        lines.append("✅ *كل الأسعار صحيحة — لا يوجد منتجات تحتاج تعديل.*")
    else:
        lines.append(
            f"💡 اضغط *«تطبيق الأسعار المقترحة»* لتصحيح {len(loss) + len(thin)} منتج تلقائياً بهامش 12%."
        )

    return "\n".join(lines)


async def build_price_check_report() -> str:
    """دالة مختصرة: يحسب ويُنسّق تقرير فحص الأسعار."""
    data = await compute_price_check_data()
    return format_price_check_report(data)


async def apply_price_fix(check_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    يطبّق الأسعار المقترحة على المنتجات الخاسرة أو ذات الهامش الضعيف.
    يرجع: {applied: int, skipped: int, details: [...]}
    كل عنصر في details: {label, old, new}
    """
    loss: List[Dict[str, Any]] = check_data.get("loss") or []
    thin: List[Dict[str, Any]] = check_data.get("thin") or []
    items_to_fix = loss + thin

    applied = 0
    skipped = 0
    details: List[Dict[str, Any]] = []

    for item in items_to_fix:
        offer_id = item.get("offer_id")
        suggested = int(item.get("suggested_price") or 0)
        old_price = int(item.get("config_price") or 0)

        if not offer_id or suggested <= 0:
            skipped += 1
            continue

        try:
            await asyncio.to_thread(db.set_price_override, offer_id, suggested)
            applied += 1
            details.append({
                "label": item.get("label", offer_id),
                "old": old_price,
                "new": suggested,
            })
        except Exception as e:
            logger.warning("apply_price_fix: set_price_override failed for %s: %s", offer_id, e)
            skipped += 1

    return {"applied": applied, "skipped": skipped, "details": details}


# ==================== المهام المجدولة ====================

async def check_usdt_transactions(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    يفحص التحويلات الجديدة على محفظة USDT كل دقيقة.
    يُطابق كل تحويل مع إيداع معلّق تلقائياً ويُضيف الرصيد للمستخدم.
    لو لم يجد تطابق — يُنبّه الأدمن للمراجعة اليدوية.
    """
    if not usdt.is_enabled():
        return

    # أولاً: أنهِ الإيداعات المنتهية الصلاحية
    try:
        expired_count = await asyncio.to_thread(database.expire_usdt_pending)
        if expired_count:
            logger.info("Expired %d USDT pending deposits", expired_count)
    except Exception as e:
        logger.warning("expire_usdt_pending failed: %s", e)

    # ثانياً: جلب التحويلات الجديدة من BSCScan
    try:
        new_txs = await usdt.sync_wallet_transactions()
    except Exception as e:
        logger.error("check_usdt_transactions: sync_wallet_transactions failed: %s", e)
        return

    for tx in new_txs:
        amount_usdt: float = tx["value"]
        from_address: str = tx["from"]
        tx_hash: str = tx["hash"]
        rate = usdt.get_usdt_rate()
        amount_syp = int(amount_usdt * rate)

        logger.info("New USDT tx: %.4f USDT from %s", amount_usdt, from_address)

        # ابحث عن إيداع معلّق يطابق هذا المبلغ
        try:
            pending = await asyncio.to_thread(
                database.find_usdt_pending_by_amount, amount_usdt
            )
        except Exception as e:
            logger.error("find_usdt_pending_by_amount failed: %s", e)
            pending = None

        if pending:
            # ✅ تطابق — أضف الرصيد واغلق الإيداع
            user_id = int(pending["user_id"])
            pending_id = int(pending["id"])

            matched = await asyncio.to_thread(
                database.match_usdt_pending, pending_id, tx_hash, float(amount_syp)
            )
            if not matched:
                # تمّت المطابقة بواسطة دورة أخرى — تجاهل
                continue

            state = await asyncio.to_thread(
                database.update_balance, user_id, float(amount_syp), True
            )

            if state:
                new_balance = float(state.get("balance") or 0)
                referrer_id = state.get("referrer_id")

                # إشعار المستخدم
                try:
                    await context.application.bot.send_message(
                        chat_id=user_id,
                        text=(
                            "✅ *تم الإيداع بنجاح!*\n"
                            "━━━━━━━━━━━━━━━━━\n\n"
                            f"💰 مبلغ مُضاف: *{amount_syp:,} ل.س*\n".replace(",", "،") +
                            f"🪙 ({amount_usdt:.4f} USDT)\n"
                            f"💼 رصيدك الآن: *{new_balance:,.0f} ل.س*\n".replace(",", "،") +
                            f"🔗 [التحقق من التحويل](https://bscscan.com/tx/{tx_hash})"
                        ),
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                    )
                except Exception as e:
                    logger.warning("Failed to notify user %s about USDT deposit: %s", user_id, e)

                # إشعار الأدمن
                user_data = await asyncio.to_thread(database.get_user, user_id)
                uname = (user_data or {}).get("username") or str(user_id)
                await notify_admin(
                    context.application.bot,
                    f"✅ *إيداع USDT تلقائي*\n\n"
                    f"المستخدم: @{uname} (`{user_id}`)\n"
                    f"المبلغ: *{amount_usdt:.4f} USDT* ≈ {amount_syp:,} ل.س\n".replace(",", "،") +
                    f"رصيده الجديد: {new_balance:,.0f} ل.س\n".replace(",", "،") +
                    f"[BSCScan](https://bscscan.com/tx/{tx_hash})",
                )

                # عمولة الإحالة
                if referrer_id:
                    from . import handlers_user as _hu
                    try:
                        await _hu.apply_referral_commission(
                            context.application.bot, user_id,
                            float(amount_syp), int(referrer_id)
                        )
                    except Exception as e:
                        logger.warning("referral commission failed for USDT deposit: %s", e)

                logger.info(
                    "USDT deposit matched: user=%s, %.4f USDT → %d SYP",
                    user_id, amount_usdt, amount_syp
                )
            else:
                logger.error("update_balance failed for user %s after USDT match", user_id)

        else:
            # ❌ لم يجد تطابق — ينبّه الأدمن للمراجعة اليدوية
            await notify_admin(
                context.application.bot,
                f"⚠️ *تحويل USDT بدون تطابق!*\n\n"
                f"💰 المبلغ: *{amount_usdt:.4f} USDT* ≈ {amount_syp:,} ل.س\n".replace(",", "،") +
                f"📍 من: `{from_address}`\n"
                f"🔗 [BSCScan](https://bscscan.com/tx/{tx_hash})\n\n"
                "_لم يجد إيداع معلّق بهذا المبلغ. أضف الرصيد يدوياً للمستخدم المناسب._",
            )
            logger.warning(
                "Unmatched USDT tx: %.4f USDT from %s (hash=%s)",
                amount_usdt, from_address, tx_hash
            )


async def job_daily_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    """مهمة مجدولة: يرسل التقرير اليومي للأدمن."""
    try:
        text = await build_today_report()
        await notify_admin(context.application.bot, text)
        logger.info("Daily report sent to admin.")
    except Exception as e:
        logger.error(f"job_daily_report failed: {e}")


async def job_price_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """مهمة مجدولة: فحص أسعار Fastcard اليومي."""
    try:
        from . import fastcard
        if not fastcard.is_enabled():
            return
        check_data = await compute_price_check_data()
        report = format_price_check_report(check_data)
        # قص الرسالة إذا تجاوزت حد تليغرام
        if len(report) > 3900:
            cut = report.rfind("\n", 0, 3900)
            report = report[: cut if cut > 0 else 3900] + "\n\n_... (تم اقتطاع التقرير لطوله)_"
        await notify_admin(context.application.bot, report)
        logger.info("Daily price check report sent.")
    except Exception as e:
        logger.error(f"job_price_check failed: {e}")


async def job_auto_coupon(context: ContextTypes.DEFAULT_TYPE) -> None:
    """مهمة مجدولة: يولّد كوبون تلقائي كل فترة محددة."""
    if not config.AUTO_COUPON_ENABLED:
        return
    try:
        import random
        import string
        code = "AUTO" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        cid = db.create_coupon(
            code=code,
            discount_type="fixed",
            discount_value=float(config.AUTO_COUPON_VALUE_SYP),
            min_order=0,
            max_uses=config.AUTO_COUPON_MAX_USES,
            expires_at=None,
        )
        if cid:
            msg = (
                f"🎟 *كوبون تلقائي جديد*\n\n"
                f"الكود: `{code}`\n"
                f"القيمة: *{config.AUTO_COUPON_VALUE_SYP:,} ل.س*\n"
                f"الاستخدامات: {config.AUTO_COUPON_MAX_USES}\n\n"
                "_انشره لزبائنك متى تريد._"
            ).replace(",", "،")
            await notify_admin(context.application.bot, msg)
            logger.info(f"Auto coupon generated: {code}")
    except Exception as e:
        logger.error(f"job_auto_coupon failed: {e}")


async def job_check_fastcard_balance(context: ContextTypes.DEFAULT_TYPE) -> None:
    """مهمة مجدولة: ينبّه الأدمن لو رصيد Fastcard وصل للحد الأدنى."""
    try:
        from . import fastcard
        if not fastcard.is_enabled():
            return
        profile = await asyncio.to_thread(fastcard.get_profile)
        balance = float(profile.get("balance") or 0)
        threshold = config.LOW_BALANCE_THRESHOLD_USD
        if balance < threshold:
            await notify_admin(
                context.application.bot,
                f"⚠️ *تنبيه: رصيد Fastcard منخفض!*\n\n"
                f"💵 الرصيد الحالي: *${balance:.4f}*\n"
                f"📉 الحد الأدنى: ${threshold:.2f}\n\n"
                "_أعد تعبئة رصيد المتجر لتفادي فشل الطلبات._",
            )
    except Exception as e:
        logger.warning(f"job_check_fastcard_balance failed: {e}")


def schedule_jobs(app: Application) -> None:
    """تسجيل كل المهام المجدولة."""
    job_queue = app.job_queue

    # فحص تحويلات USDT كل دقيقة (إذا كانت مفعّلة)
    if usdt.is_enabled():
        job_queue.run_repeating(
            check_usdt_transactions,
            interval=config.USDT_CHECK_INTERVAL,
            first=5,
            name="check_usdt_transactions",
        )
        logger.info("✅ USDT transaction checker scheduled")

    # التقرير اليومي — يُرسل كل يوم على الساعة المحددة (UTC)
    job_queue.run_daily(
        job_daily_report,
        time=_make_time(config.DAILY_REPORT_HOUR_UTC, config.DAILY_REPORT_MINUTE_UTC),
        name="daily_report",
    )
    logger.info(
        "✅ Daily report scheduled at %02d:%02d UTC",
        config.DAILY_REPORT_HOUR_UTC,
        config.DAILY_REPORT_MINUTE_UTC,
    )

    # فحص أسعار Fastcard اليومي
    job_queue.run_daily(
        job_price_check,
        time=_make_time(config.PRICE_CHECK_HOUR_UTC, config.PRICE_CHECK_MINUTE_UTC),
        name="daily_price_check",
    )
    logger.info(
        "✅ Daily price check scheduled at %02d:%02d UTC",
        config.PRICE_CHECK_HOUR_UTC,
        config.PRICE_CHECK_MINUTE_UTC,
    )

    # كوبونات تلقائية كل X يوم
    if config.AUTO_COUPON_ENABLED:
        job_queue.run_repeating(
            job_auto_coupon,
            interval=config.AUTO_COUPON_INTERVAL_DAYS * 86400,
            first=timedelta(days=config.AUTO_COUPON_INTERVAL_DAYS),
            name="auto_coupon",
        )
        logger.info("✅ Auto coupon job scheduled every %d days", config.AUTO_COUPON_INTERVAL_DAYS)

    # فحص رصيد Fastcard كل X ثانية
    job_queue.run_repeating(
        job_check_fastcard_balance,
        interval=config.BALANCE_CHECK_INTERVAL,
        first=60,
        name="fastcard_balance_check",
    )
    logger.info("✅ Fastcard balance check scheduled every %ds", config.BALANCE_CHECK_INTERVAL)

    logger.info("✅ All jobs scheduled successfully")


def _make_time(hour: int, minute: int):
    """يبني كائن datetime.time بتوقيت UTC للاستخدام مع run_daily."""
    from datetime import time as _time
    return _time(hour=hour % 24, minute=minute % 60, tzinfo=timezone.utc)
