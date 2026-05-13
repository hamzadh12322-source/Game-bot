
"""
عميل USDT Wallet API (بلوك تشين BSC/BEP20)
يتابع المحفظة الموحدة ويسجّل التحويلات الواردة تلقائياً.
"""
import logging
import hashlib
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from . import config, database as db

logger = logging.getLogger(__name__)

# عنوان محفظتنا الموحدة (BSC/BEP20)
USDT_WALLET_ADDRESS = "0x9a82c889ed9acbc370ac3315134e6286e93a15d5"
USDT_CONTRACT_ADDRESS = "0x55dd5ee1f5360d8cdba15e16bfd81c0480067955"  # USDT على BSC
USDT_DECIMALS = 18

# BSCScan API
BSCSCAN_API_URL = "https://api.bscscan.com/api"

# سعر صرف افتراضي (ل.س لكل USDT)
DEFAULT_USDT_RATE = 13100


class USDTError(Exception):
    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.code = code


def is_enabled() -> bool:
    """تحقّق من تفعيل خاصية USDT"""
    return config.USDT_ENABLED and bool(config.BSCSCAN_API_KEY)


def get_wallet_address() -> str:
    """ترجع عنوان محفظة USDT الموحدة"""
    return USDT_WALLET_ADDRESS


def set_usdt_rate(rate: int) -> None:
    """تعديل سعر صرف USDT (ل.س)"""
    db.set_setting("usdt_rate", str(rate))
    logger.info(f"تم تحديث سعر USDT: {rate} ل.س")


def get_usdt_rate() -> int:
    """الحصول على سعر USDT الحالي (ل.س)"""
    rate_str = db.get_setting("usdt_rate")
    if rate_str:
        try:
            return int(rate_str)
        except ValueError:
            pass
    return DEFAULT_USDT_RATE


def _fetch_transactions_bscscan(start_block: int = 0, end_block: int = 99999999) -> List[Dict[str, Any]]:
    """
    يجلب تحويلات USDT للمحفظة من BSCScan API.
    يفلتر فقط التحويلات الواردة (to=wallet) و الناجحة (isError=0).
    """
    if not config.BSCSCAN_API_KEY:
        raise USDTError("BSCSCAN_API_KEY غير مضبوط", "AUTH_MISSING")
    
    params = {
        "apikey": config.BSCSCAN_API_KEY,
        "module": "account",
        "action": "tokentx",
        "address": USDT_WALLET_ADDRESS,
        "contractaddress": USDT_CONTRACT_ADDRESS,
        "startblock": start_block,
        "endblock": end_block,
        "page": 1,
        "offset": 10000,
        "sort": "desc",
    }
    
    try:
        resp = requests.get(BSCSCAN_API_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise USDTError(f"فشل الاتصال بـ BSCScan: {e}", "NETWORK")
    except ValueError:
        raise USDTError("رد غير متوقع من BSCScan", "INVALID_JSON")
    
    if data.get("status") != "1":
        msg = data.get("message", "خطأ غير معروف")
        raise USDTError(f"خطأ من BSCScan: {msg}", data.get("status"))
    
    txs = data.get("result", [])
    if not isinstance(txs, list):
        return []
    
    # فلترة: واردة فقط (to=wallet) و ناجحة (isError=0)
    filtered = [
        tx for tx in txs
        if tx.get("to", "").lower() == USDT_WALLET_ADDRESS.lower()
        and tx.get("isError") == "0"
    ]
    return filtered


def _tx_hash_to_id(tx_hash: str) -> int:
    """يحوّل hash التحويل لرقم معرّف ثابت (لتخزينه في DB)"""
    s = tx_hash.strip().lower().encode("utf-8")
    h = hashlib.sha256(s).digest()
    return 10**18 + int.from_bytes(h[:7], "big")  # prefix لتجنب التصادم


def parse_tx_amount(tx: Dict[str, Any]) -> float:
    """يستخرج المبلغ من transaction بصيغة USDT (بعد تقسيم DECIMALS)"""
    try:
        value = int(tx.get("value", 0))
        return value / (10 ** USDT_DECIMALS)
    except (TypeError, ValueError):
        return 0.0


async def sync_wallet_transactions(since_timestamp: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    يجلب التحويلات الجديدة من BSCScan ويسجّلها في DB.
    يرجع قائمة التحويلات الجديدة المكتشفة.
    """
    if not is_enabled():
        return []
    
    try:
        txs = _fetch_transactions_bscscan()
    except USDTError as e:
        logger.error(f"sync_wallet_transactions failed: {e}")
        return []
    
    new_txs = []
    for tx in txs:
        tx_hash = tx.get("hash", "")
        if not tx_hash:
            continue
        
        tx_id = _tx_hash_to_id(tx_hash)
        
        # تحقّق من عدم تسجيل هذا التحويل سابقاً
        if db.is_transaction_consumed(tx_id):
            continue
        
        # تحقّق من الطابع الزمني إن لزم
        if since_timestamp:
            try:
                tx_timestamp = int(tx.get("timeStamp", 0))
                if tx_timestamp < since_timestamp:
                    continue
            except (TypeError, ValueError):
                pass
        
        amount = parse_tx_amount(tx)
        if amount <= 0:
            continue
        
        tx_data = {
            "hash": tx_hash,
            "from": tx.get("from", "").lower(),
            "to": USDT_WALLET_ADDRESS.lower(),
            "value": amount,
            "block_number": tx.get("blockNumber", ""),
            "timestamp": int(tx.get("timeStamp", 0)),
        }
        new_txs.append(tx_data)
        
        # سجّل التحويل في DB كمعاملة مستقبلة
        db.consume_transaction(tx_id, user_id=0, amount=amount)
        logger.info(f"✅ تحويل USDT جديد: {amount} USDT من {tx_data['from']}")
    
    return new_txs


def get_wallet_balance() -> Optional[float]:
    """
    يجلب رصيد محفظة USDT الحالي.
    يرجع None عند فشل الاتصال.
    """
    if not is_enabled():
        return None
    
    params = {
        "apikey": config.BSCSCAN_API_KEY,
        "module": "account",
        "action": "tokenbalance",
        "contractaddress": USDT_CONTRACT_ADDRESS,
        "address": USDT_WALLET_ADDRESS,
        "tag": "latest",
    }
    
    try:
        resp = requests.get(BSCSCAN_API_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch USDT balance: {e}")
        return None
    except ValueError:
        logger.error("Invalid JSON response from BSCScan balance")
        return None
    
    if data.get("status") != "1":
        logger.warning(f"BSCScan balance error: {data.get('message')}")
        return None
    
    try:
        balance_wei = int(data.get("result", 0))
        return balance_wei / (10 ** USDT_DECIMALS)
    except (TypeError, ValueError):
        return None
