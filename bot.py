"""
AngelBot PRO MAX v3.0
All Index Options: Nifty + BankNifty + Sensex + Midcap + Bankex + FinNifty
AI Strategy | Telegram | Google Sheets | Trailing SL
Target: 10% | Stop Loss: 5% | Daily Loss Limit: 5%
"""

import os, time, logging, json, requests, base64
from datetime import datetime, date, timedelta, time as dtime
from SmartApi import SmartConnect
import pyotp
import numpy as np

# ═══ ANGEL ONE CREDENTIALS ═════════════════════════════
API_KEY     = os.getenv("ANGEL_API_KEY",    "rjRimMjk")
CLIENT_ID   = os.getenv("ANGEL_CLIENT_ID",  "M410221")
PASSWORD    = os.getenv("ANGEL_PASSWORD",   "9864")
TOTP_SECRET = os.getenv("ANGEL_TOTP",       "NNWTNV7ZSNVUYRNF4ZY4TY3LDU")
CAPITAL     = float(os.getenv("CAPITAL",    "50000"))
PAPER_TRADE = os.getenv("PAPER_TRADE", "true").lower() == "true"  # True = no real orders

# ═══ TELEGRAM ══════════════════════════════════════════
TG_TOKEN    = os.getenv("TG_TOKEN",    "8531854367:AAGvxR2XYFx0EHHiZNYQQP0JGxHkV0vZXIE")
TG_CHAT_ID  = os.getenv("TG_CHAT_ID",  "1061234677")

# ═══ GOOGLE SHEETS ══════════════════════════════════════
SHEET_ID    = os.getenv("SHEET_ID",    "1NFr0P0lEwiHvg7FC_HQaTnaQfUoONQeNBEaMsA8f3K8")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS", "")  # Railway mein JSON paste karna hoga

# ═══ FIXED RULES ═══════════════════════════════════════
TARGET_PCT        = 10.0   # 10% profit pe exit
SL_PCT            = 5.0    # 5% stop loss
TRAIL_SL_PCT      = 3.0    # 3% trailing stop loss
DAILY_LOSS_LIMIT  = 5.0    # 5% capital loss pe band
MAX_CAPITAL_TRADE = 0.20   # 20% capital per trade

# ═══ ALL 6 INDICES ══════════════════════════════════════
INDICES = {
    "NIFTY": {
        "token": "99926000", "exchange": "NSE",
        "strike_gap": 50, "lot_size": 50,
        "opt_exch": "NFO", "prefix": "NIFTY",
    },
    "BANKNIFTY": {
        "token": "99926009", "exchange": "NSE",
        "strike_gap": 100, "lot_size": 15,
        "opt_exch": "NFO", "prefix": "BANKNIFTY",
    },
    "SENSEX": {
        "token": "99919000", "exchange": "BSE",
        "strike_gap": 100, "lot_size": 10,
        "opt_exch": "BFO", "prefix": "SENSEX",
    },
    "MIDCPNIFTY": {
        "token": "99926074", "exchange": "NSE",
        "strike_gap": 25, "lot_size": 75,
        "opt_exch": "NFO", "prefix": "MIDCPNIFTY",
    },
    "BANKEX": {
        "token": "99919012", "exchange": "BSE",
        "strike_gap": 100, "lot_size": 15,
        "opt_exch": "BFO", "prefix": "BANKEX",
    },
    "FINNIFTY": {
        "token": "99926037", "exchange": "NSE",
        "strike_gap": 50, "lot_size": 40,
        "opt_exch": "NFO", "prefix": "FINNIFTY",
    },
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
log = logging.getLogger("AngelBot")


# ═══ TELEGRAM ══════════════════════════════════════════
def tg(msg):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=5
        )
    except:
        pass


# ═══ GOOGLE SHEETS ══════════════════════════════════════
def sheets_append(row_data):
    """Google Sheets mein trade data save karo"""
    if not GOOGLE_CREDS or not SHEET_ID:
        return
    try:
        creds = json.loads(GOOGLE_CREDS)
        # Get access token
        import urllib.request, urllib.parse
        token_url = "https://oauth2.googleapis.com/token"
        now = int(time.time())
        header = base64.urlsafe_b64encode(json.dumps({"alg":"RS256","typ":"JWT"}).encode()).decode().rstrip("=")
        payload = base64.urlsafe_b64encode(json.dumps({
            "iss": creds["client_email"],
            "scope": "https://www.googleapis.com/auth/spreadsheets",
            "aud": token_url,
            "exp": now + 3600,
            "iat": now
        }).encode()).decode().rstrip("=")

        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        private_key = serialization.load_pem_private_key(
            creds["private_key"].encode(), password=None
        )
        sig = base64.urlsafe_b64encode(
            private_key.sign(f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
        ).decode().rstrip("=")
        jwt = f"{header}.{payload}.{sig}"

        r = requests.post(token_url, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": jwt
        }, timeout=10)
        access_token = r.json()["access_token"]

        # Append to sheet
        requests.post(
            f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Sheet1!A1:append",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"valueInputOption": "RAW"},
            json={"values": [row_data]},
            timeout=10
        )
        log.info("Google Sheets updated!")
    except Exception as e:
        log.warning(f"Sheets error: {e}")


def init_sheet_headers():
    """Sheet mein headers daalo pehli baar"""
    headers = ["Date", "Time", "Index", "Direction", "Strike",
               "Buy Price", "Sell Price", "Qty", "Lots",
               "P&L (₹)", "P&L (%)", "Reason", "Duration", "Today P&L"]
    sheets_append(headers)


# ═══ AI BRAIN ══════════════════════════════════════════
class AIBrain:
    def __init__(self):
        self.prices = {k: [] for k in INDICES}

    def add(self, index, price):
        p = self.prices[index]
        p.append(float(price))
        if len(p) > 200:
            p.pop(0)

    def ema(self, arr, n):
        if len(arr) < n:
            return arr[-1]
        k, e = 2/(n+1), arr[-n]
        for x in arr[-n+1:]:
            e = x*k + e*(1-k)
        return round(e, 2)

    def rsi(self, arr, n=14):
        if len(arr) < n+1:
            return 50.0
        d = np.diff(arr[-(n+1):])
        g = d[d>0].mean() if (d>0).any() else 1e-9
        l = abs(d[d<0].mean()) if (d<0).any() else 1e-9
        return round(100 - 100/(1+g/l), 2)

    def macd(self, arr):
        if len(arr) < 26:
            return 0.0
        return round(self.ema(arr, 12) - self.ema(arr, 26), 2)

    def bollinger(self, arr, n=20):
        if len(arr) < n:
            return None, None, None
        a = np.array(arr[-n:])
        return round(a.mean()+2*a.std(), 2), round(a.mean(), 2), round(a.mean()-2*a.std(), 2)

    def supertrend(self, arr):
        if len(arr) < 20:
            return "neutral"
        mid = np.mean(arr[-20:])
        cur = arr[-1]
        if cur > mid * 1.002:
            return "bullish"
        elif cur < mid * 0.998:
            return "bearish"
        return "neutral"

    def vwap(self, arr):
        return round(np.mean(arr[-20:]), 2) if len(arr) >= 20 else arr[-1]

    def momentum(self, arr, n=10):
        if len(arr) < n+1:
            return 0
        return round((arr[-1]-arr[-(n+1)])/arr[-(n+1)]*100, 3)

    def market_structure(self, arr):
        if len(arr) < 20:
            return "neutral"
        r = arr[-20:]
        m = len(r)//2
        if max(r[m:]) > max(r[:m]) and min(r[m:]) > min(r[:m]):
            return "uptrend"
        elif max(r[m:]) < max(r[:m]) and min(r[m:]) < min(r[:m]):
            return "downtrend"
        return "sideways"

    def analyze(self, index):
        arr = self.prices[index]
        if len(arr) < 15:
            return None, 0, [f"Data collect ho raha hai ({len(arr)}/15)"]

        cur = arr[-1]
        rsi_v = self.rsi(arr)
        macd_v = self.macd(arr)
        e9, e21, e50 = self.ema(arr,9), self.ema(arr,21), self.ema(arr,min(50,len(arr)))
        ub, mb, lb = self.bollinger(arr)
        st = self.supertrend(arr)
        vwap_v = self.vwap(arr)
        mom = self.momentum(arr)
        ms = self.market_structure(arr)

        ce = pe = 0
        reasons = []

        # RSI
        if rsi_v < 30:   ce += 35; reasons.append(f"RSI={rsi_v} oversold→CE")
        elif rsi_v < 40: ce += 20; reasons.append(f"RSI={rsi_v} weak→CE")
        elif rsi_v > 70: pe += 35; reasons.append(f"RSI={rsi_v} overbought→PE")
        elif rsi_v > 60: pe += 20; reasons.append(f"RSI={rsi_v} high→PE")

        # MACD
        if macd_v > 0:   ce += 25; reasons.append(f"MACD={macd_v} bullish→CE")
        else:            pe += 25; reasons.append(f"MACD={macd_v} bearish→PE")

        # EMA
        if cur > e9 > e21 > e50:   ce += 25; reasons.append("Strong uptrend→CE")
        elif cur > e9 > e21:       ce += 15; reasons.append("Uptrend→CE")
        elif cur < e9 < e21 < e50: pe += 25; reasons.append("Strong downtrend→PE")
        elif cur < e9 < e21:       pe += 15; reasons.append("Downtrend→PE")

        # Bollinger
        if ub and lb:
            if cur < lb:   ce += 20; reasons.append("Below lower BB→CE bounce")
            elif cur > ub: pe += 20; reasons.append("Above upper BB→PE reversal")

        # Supertrend
        if st == "bullish":   ce += 20; reasons.append("Supertrend bullish→CE")
        elif st == "bearish": pe += 20; reasons.append("Supertrend bearish→PE")

        # VWAP
        if cur > vwap_v:   ce += 10; reasons.append(f"Above VWAP→CE")
        else:              pe += 10; reasons.append(f"Below VWAP→PE")

        # Momentum
        if mom > 0.5:    ce += 15; reasons.append(f"Strong momentum→CE")
        elif mom > 0:    ce += 5
        elif mom < -0.5: pe += 15; reasons.append(f"Negative momentum→PE")
        elif mom < 0:    pe += 5

        # Market structure
        if ms == "uptrend":   ce += 15; reasons.append("Higher highs→CE")
        elif ms == "downtrend": pe += 15; reasons.append("Lower lows→PE")
        elif ms == "sideways":
            ce = int(ce * 0.85)
            pe = int(pe * 0.85)

        total = ce + pe
        if total == 0:
            return None, 0, reasons

        if ce > pe:
            return "CE", min(95, int(ce/total*100+10)), reasons
        else:
            return "PE", min(95, int(pe/total*100+10)), reasons

    def best_index(self, prices_dict):
        best_idx = best_dir = best_reasons = None
        best_conf = 0
        for idx in INDICES:
            if not prices_dict.get(idx):
                continue
            direction, conf, reasons = self.analyze(idx)
            if direction and conf > best_conf:
                best_conf = conf
                best_idx = idx
                best_dir = direction
                best_reasons = reasons
        return best_idx, best_dir, best_conf, best_reasons or []


# ═══ MAIN BOT ══════════════════════════════════════════
class AngelBot:

    def __init__(self):
        self.api           = None
        self.brain         = AIBrain()
        self.position      = None
        self.trades_today  = 0
        self.pnl_today     = 0.0
        self.daily_log     = []
        self.last_date     = date.today()
        self.spot_prices   = {}
        self.headers_added = False
        self.highest_price = 0  # for trailing SL

    def login(self):
        try:
            totp = pyotp.TOTP(TOTP_SECRET).now()
            self.api = SmartConnect(api_key=API_KEY)
            r = self.api.generateSession(CLIENT_ID, PASSWORD, totp)
            if r["status"]:
                log.info(f"✓ Login: {CLIENT_ID}")
                tg(f"🤖 <b>AngelBot PRO MAX Started!</b>\n"
                   f"💰 Capital: ₹{CAPITAL}\n"
                   f"🎯 Target: {TARGET_PCT}% | 🛑 SL: {SL_PCT}%\n"
                   f"📉 Daily Loss Limit: {DAILY_LOSS_LIMIT}%\n"
                   f"📊 Indices: NIFTY, BANKNIFTY, SENSEX, MIDCAP, BANKEX, FINNIFTY")
                return True
            log.error(f"✗ Login: {r['message']}")
            tg(f"❌ Login failed: {r['message']}")
        except Exception as e:
            log.error(f"Login error: {e}")
        return False

    def is_market_open(self):
        now = datetime.now()
        if now.weekday() >= 5:
            return False
        t = now.time()
        return dtime(9, 15) <= t <= dtime(15, 25)

    def best_time(self):
        t = datetime.now().time()
        return dtime(9, 20) <= t <= dtime(15, 10)

    def closing_time(self):
        return datetime.now().time() >= dtime(15, 10)

    def daily_loss_hit(self):
        limit = CAPITAL * DAILY_LOSS_LIMIT / 100
        return self.pnl_today <= -limit

    def get_ltp(self, token, exchange="NSE"):
        try:
            r = self.api.ltpData(exchange, "", token)
            if r["status"]:
                return float(r["data"]["ltp"])
        except Exception as e:
            log.warning(f"LTP error: {e}")
        return None

    def load_nfo_tokens(self):
        """NFO scrip master load karo — options tokens ke liye"""
        if hasattr(self, 'nfo_tokens'):
            return
        try:
            r = requests.get(
                "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            data = r.json()
            # Only NFO options
            self.nfo_tokens = {}
            for s in data:
                if s.get("exch_seg") in ["NFO", "BFO"] and s.get("instrumenttype") in ["OPTIDX", "OPTSTK"]:
                    self.nfo_tokens[s["symbol"]] = s["token"]
            log.info(f"NFO tokens loaded: {len(self.nfo_tokens)}")
            # Sample
            sample = list(self.nfo_tokens.keys())[:3]
            log.info(f"Sample NFO: {sample}")
        except Exception as e:
            log.warning(f"NFO load error: {e}")
            self.nfo_tokens = {}

    def get_option_token(self, symbol, exchange):
        """NFO token fetch karo"""
        # Try NFO scrip master first
        self.load_nfo_tokens()
        if hasattr(self, 'nfo_tokens') and symbol in self.nfo_tokens:
            log.info(f"✓ NFO Token: {symbol} = {self.nfo_tokens[symbol]}")
            return self.nfo_tokens[symbol]
        
        # Fallback: searchScrip
        try:
            r = self.api.searchScrip(exchange, symbol)
            if r["status"] and r["data"]:
                for item in r["data"]:
                    if item.get("tradingsymbol","") == symbol:
                        log.info(f"✓ Search Token: {symbol}")
                        return item["symboltoken"]
                return r["data"][0]["symboltoken"]
        except Exception as e:
            log.warning(f"Token search error: {e}")
        
        log.warning(f"Token not found: {symbol}")
        return None

    def place_order(self, symbol, token, side, qty, exchange):
        # PAPER TRADE MODE
        if PAPER_TRADE:
            fake_id = f"PAPER_{side}_{symbol}_{int(time.time())}"
            log.info(f"📝 PAPER {side} {symbol} x{qty} | ID:{fake_id}")
            tg(f"PAPER TRADE {side}\n{symbol} x{qty}\nSimulated")
            return fake_id
        # REAL ORDER
        try:
            r = self.api.placeOrder({
                "variety": "NORMAL", "tradingsymbol": symbol,
                "symboltoken": token, "transactiontype": side,
                "exchange": exchange, "ordertype": "MARKET",
                "producttype": "INTRADAY", "duration": "DAY",
                "price": "0", "quantity": str(qty),
            })
            if r["status"]:
                log.info(f"✓ {side} {symbol} x{qty} | ID:{r['data']['orderid']}")
                return r["data"]["orderid"]
            log.error(f"✗ {r['message']}")
        except Exception as e:
            log.error(f"Order error: {e}")
        return None

    def get_expiry(self):
        today = date.today()
        days = (3 - today.weekday()) % 7
        exp = today + timedelta(days=days)
        if exp <= today:
            exp += timedelta(days=7)
        return exp.strftime("%d%b%y").upper()

    def open_trade(self, index, direction, reasons):
        cfg = INDICES[index]
        spot = self.spot_prices.get(index)
        if not spot:
            return

        strike = int(round(spot / cfg["strike_gap"]) * cfg["strike_gap"])
        expiry = self.get_expiry()  # e.g. 12JUN26
        opt_type = "CE" if direction == "CE" else "PE"
        sym = f"{cfg['prefix']}{expiry}{strike}{opt_type}"
        
        # Search in NFO tokens with fuzzy match
        self.load_nfo_tokens()
        token = None
        sym = None
        
        if hasattr(self, 'nfo_tokens'):
            opt_type = "CE" if direction == "CE" else "PE"
            # Find closest matching token
            prefix = cfg['prefix']
            for name, tok in self.nfo_tokens.items():
                if (name.startswith(prefix) and 
                    name.endswith(opt_type) and 
                    str(strike) in name):
                    sym = name
                    token = tok
                    log.info(f"✓ Found matching token: {name} = {tok}")
                    break
        
        if not token:
            log.warning(f"No token found for {cfg['prefix']} {strike} {direction}")
            return
        
        log.info(f"Using symbol: {sym}")

        price = self.get_ltp(token, cfg["opt_exch"])
        if not price or price < 5:
            log.warning(f"Option price too low: {price}")
            return

        lots = max(1, int(CAPITAL * MAX_CAPITAL_TRADE / (price * cfg["lot_size"])))
        qty = lots * cfg["lot_size"]
        sl = round(price * (1 - SL_PCT/100), 2)
        tp = round(price * (1 + TARGET_PCT/100), 2)

        oid = self.place_order(sym, token, "BUY", qty, cfg["opt_exch"])
        if oid:
            self.position = {
                "index": index, "direction": direction,
                "symbol": sym, "token": token,
                "exchange": cfg["opt_exch"], "qty": qty,
                "lots": lots, "entry": price, "sl": sl, "tp": tp,
                "highest": price, "open_time": datetime.now(),
            }
            self.highest_price = price
            self.trades_today += 1

            reason_text = " | ".join(reasons[:3]) if reasons else "AI Signal"
            log.info(f"★ OPEN | {index} {direction} {strike} | ₹{price} | SL:₹{sl} TP:₹{tp} | {lots} lots")
            tg(f"🟢 <b>TRADE OPEN</b>\n"
               f"📊 {index} {direction} {strike}\n"
               f"💰 Entry: ₹{price}\n"
               f"🛑 SL: ₹{sl} | 🎯 TP: ₹{tp}\n"
               f"📦 Lots: {lots} | Qty: {qty}\n"
               f"🧠 {reason_text}\n"
               f"⏰ {datetime.now().strftime('%H:%M:%S')}")

    def close_trade(self, price, reason):
        if not self.position:
            return
        p = self.position
        oid = self.place_order(p["symbol"], p["token"], "SELL", p["qty"], p["exchange"])
        if oid:
            pnl = round((price - p["entry"]) * p["qty"], 2)
            pnl_pct = round((price - p["entry"]) / p["entry"] * 100, 2)
            self.pnl_today += pnl
            dur = str(datetime.now() - p["open_time"]).split(".")[0]

            log.info(f"★ CLOSE [{reason}] | Entry:₹{p['entry']} Exit:₹{price} | P&L:₹{pnl} ({pnl_pct}%)")
            log.info(f"  Today P&L: ₹{self.pnl_today} | Trades: {self.trades_today}")

            emoji = "✅" if pnl > 0 else "❌"
            tg(f"{emoji} <b>TRADE CLOSED</b>\n"
               f"📊 {p['symbol']}\n"
               f"💰 Entry: ₹{p['entry']} → Exit: ₹{price}\n"
               f"{'🟢' if pnl>0 else '🔴'} P&amp;L: ₹{pnl} ({pnl_pct}%)\n"
               f"📋 Reason: {reason}\n"
               f"📈 Today Total: ₹{round(self.pnl_today,2)}\n"
               f"⏱ Duration: {dur}")

            # Google Sheets save
            now = datetime.now()
            sheets_append([
                now.strftime("%d-%m-%Y"),
                now.strftime("%H:%M:%S"),
                p["index"], p["direction"],
                p["symbol"].replace(p["index"],"").replace("C","").replace("P","")[-5:],
                p["entry"], price,
                p["qty"], p["lots"],
                pnl, pnl_pct,
                reason, dur,
                round(self.pnl_today, 2)
            ])

            self.daily_log.append({
                "symbol": p["symbol"], "entry": p["entry"],
                "exit": price, "pnl": pnl, "reason": reason
            })
            self.position = None
            self.highest_price = 0

    def monitor(self):
        if not self.position:
            return
        p = self.position
        price = self.get_ltp(p["token"], p["exchange"])
        if not price:
            return

        pct = (price - p["entry"]) / p["entry"] * 100
        log.info(f"  Monitor: {p['symbol']} ₹{price} | {pct:+.2f}% | SL:₹{p['sl']} TP:₹{p['tp']}")

        # Trailing SL update
        if price > self.highest_price:
            self.highest_price = price
            new_sl = round(price * (1 - TRAIL_SL_PCT/100), 2)
            if new_sl > p["sl"]:
                p["sl"] = new_sl
                log.info(f"  Trailing SL updated: ₹{new_sl}")

        # Check exit conditions
        if price >= p["tp"]:
            self.close_trade(price, f"TARGET +{TARGET_PCT}%")
        elif price <= p["sl"]:
            self.close_trade(price, f"STOP LOSS -{SL_PCT}%")

    def max_trades(self):
        if self.trades_today == 0:
            return 1
        last = self.daily_log[-1] if self.daily_log else None
        if last and last["pnl"] > 0:
            return self.trades_today + 2
        return self.trades_today + 1

    def daily_summary(self):
        wins = sum(1 for t in self.daily_log if t["pnl"] > 0)
        loss = len(self.daily_log) - wins
        ret = round(self.pnl_today/CAPITAL*100, 2)
        log.info(f"DAY SUMMARY | P&L:₹{self.pnl_today} | W:{wins} L:{loss} | {ret}%")
        tg(f"📊 <b>Day Summary — {date.today()}</b>\n"
           f"Total Trades: {self.trades_today}\n"
           f"✅ Wins: {wins} | ❌ Loss: {loss}\n"
           f"💰 Net P&amp;L: ₹{round(self.pnl_today,2)}\n"
           f"📈 Return: {ret}%\n"
           f"🏦 Capital: ₹{CAPITAL}")

    def run(self):
        log.info("╔══════════════════════════════════════════════════╗")
        log.info("║  AngelBot PRO MAX v3.0                           ║")
        log.info("║  6 Indices | Telegram | Sheets | Trailing SL    ║")
        log.info("╚══════════════════════════════════════════════════╝")

        if not self.login():
            return

        while True:
            now = datetime.now()

            # New day reset
            if now.date() != self.last_date:
                self.daily_summary()
                self.trades_today = 0
                self.pnl_today    = 0.0
                self.daily_log    = []
                self.last_date    = now.date()
                self.headers_added = False
                self.login()

            # Market closed
            if not self.is_market_open():
                now = datetime.now()
                # Calculate seconds until next market open (9:15 AM)
                next_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
                if now.time() >= dtime(15, 30):
                    # Market closed for today - sleep till tomorrow 9:15 AM
                    next_open += timedelta(days=1)
                    # Skip weekends
                    while next_open.weekday() >= 5:
                        next_open += timedelta(days=1)
                
                sleep_secs = max(60, (next_open - now).total_seconds())
                sleep_hrs  = int(sleep_secs // 3600)
                sleep_mins = int((sleep_secs % 3600) // 60)
                log.info(f"Market closed. Sleeping {sleep_hrs}h {sleep_mins}m till {next_open.strftime('%d %b %H:%M')}...")
                time.sleep(sleep_secs)
                continue

            # Sheet headers
            if not self.headers_added:
                init_sheet_headers()
                self.headers_added = True

            # Force close 3:10 PM
            if self.closing_time():
                if self.position:
                    log.warning("3:10 PM — Force closing!")
                    p = self.get_ltp(self.position["token"], self.position["exchange"])
                    self.close_trade(p or self.position["entry"], "Market Close 3:10PM")
                self.daily_summary()
                time.sleep(300)
                continue

            # Daily loss limit
            if self.daily_loss_hit():
                log.warning(f"Daily loss limit hit! P&L: ₹{self.pnl_today}")
                if self.position:
                    p = self.get_ltp(self.position["token"], self.position["exchange"])
                    self.close_trade(p or self.position["entry"], "Daily Loss Limit")
                tg(f"🚨 <b>Daily Loss Limit Hit!</b>\n"
                   f"Loss: ₹{abs(round(self.pnl_today,2))} ({DAILY_LOSS_LIMIT}%)\n"
                   f"Bot band ho gaya aaj ke liye!")
                time.sleep(300)
                continue

            # Fetch all 6 index prices
            for idx, cfg in INDICES.items():
                price = self.get_ltp(cfg["token"], cfg["exchange"])
                if price:
                    self.spot_prices[idx] = price
                    self.brain.add(idx, price)
                    log.info(f"  {idx}: ₹{price}")

            # Monitor open position
            if self.position:
                self.monitor()
                time.sleep(60)
                continue

            # Max trades check
            if self.trades_today >= self.max_trades():
                log.info(f"Max trades done ({self.trades_today})")
                time.sleep(60)
                continue

            if not self.best_time():
                time.sleep(60)
                continue

            # AI Decision
            idx, direction, conf, reasons = self.brain.best_index(self.spot_prices)

            log.info(f"AI Analysis: {idx} {direction} | {conf}%")
            for r in (reasons or [])[:3]:
                log.info(f"  → {r}")

            if not idx or conf < 60:
                log.info(f"Signal weak ({conf}%) — waiting...")
                time.sleep(60)
                continue

            log.info(f"★ SIGNAL: {idx} {direction} | {conf}%")
            self.open_trade(idx, direction, reasons or [])
            time.sleep(60)


if __name__ == "__main__":
    bot = AngelBot()
    bot.run()
