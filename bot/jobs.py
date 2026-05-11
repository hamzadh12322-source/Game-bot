"""
المهام المجدولة: تقارير يومية، فحص أسعار، تحديث الرصيد، التحويلات التلقائية
"""
import logging
from telegram.ext import Application, ContextTypes
from . import config, database as db, usdt
from .notify import notify_admin

logger = logging.getLogger(__name__)


async def _send_admin(app: Application, text: str) -> None:
    """يرسل رسالة للأدمن عبر البوت."""
    if config.ADMIN_ID:
        try:
            await app.bot.send_message(chat_id=config.ADMIN_ID, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send message to admin: {e}")


async def check_usdt_transactions(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    يفحص التحويلات الجديدة على محفظة USDT كل دقيقة.
    ينبّه الأدمن لكل تحويل جديد.
    """
    if not usdt.is_enabled():
        return
    
    try:
        new_txs = await usdt.sync_wallet_transactions()
        
        for tx in new_txs:
            amount_usdt = tx["value"]
            from_address = tx["from"]
            tx_hash = tx["hash"]
            
            # تحويل USDT إلى SYP
            rate = usdt.get_usdt_rate()
            amount_syp = int(amount_usdt * rate)
            
            message = (
                f"✅ **تحويل USDT جديد!**\n\n"
                f"💰 المبلغ: `{amount_usdt:.2f}` USDT\n"
                f"💵 بالليرة: `{amount_syp:,}` ل.س\n"
                f"📍 من: `{from_address}`\n"
                f"🔗 [عرض على BSCScan](https://bscscan.com/tx/{tx_hash})\n"
            )
            
            await notify_admin(context.application.bot, message)
            logger.info(f"Notified admin about USDT transaction: {amount_usdt} USDT")
    
    except Exception as e:
        logger.error(f"check_usdt_transactions failed: {e}")


def schedule_jobs(app: Application) -> None:
    """تسجيل كل المهام المجدولة."""
    job_queue = app.job_queue
    
    # فحص تحويلات USDT كل دقيقة (إذا كانت مفعّلة)
    if usdt.is_enabled():
        job_queue.run_repeating(
            check_usdt_transactions,
            interval=config.USDT_CHECK_INTERVAL,
            first=5,
            name="check_usdt_transactions"
        )
        logger.info("✅ USDT transaction checker scheduled")
    
    logger.info("✅ All jobs scheduled successfully")
