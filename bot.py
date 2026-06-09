"""
AngelBot PRO MAX v4.0 - CLEAN VERSION
6 Indices | Telegram | Google Sheets | Trailing SL
Target: 10% | Stop Loss: 5% | Daily Loss: 5%
"""

import os, time, logging, json, requests, base64
from datetime import datetime, date, timedelta, time as dtime
from SmartApi import SmartConnect
import pyotp
import numpy as np

# ═══ CREDENTIALS ════════════════════════════════════
API_KEY     = os.getenv("ANGEL_API_KEY",   "rjRimMjk")
CLIENT_ID   = os.getenv("ANGEL_CLIENT_ID", "M410221")
PASSWORD    = os.getenv("ANGEL_PASSWORD",  "9864")
TOTP_SECRET = os.getenv("ANGEL_TOTP",      "NNWTNV7ZSNVUYRNF4ZY4TY3LDU")
CAPITAL     = float(os.getenv("CAPITAL",   "4000"))

# ═══ TELEGRAM ═══════════════════════════════════════
TG_TOKEN   = os.getenv("TG_TOKEN",   "8531854367:AAGvxR2XYFx0EHHiZNYQQP0JGxHkV0vZXIE")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "1061234677")

# ═══ GOOGLE SHEETS ══════════════════════════════════
SHEET_ID     = os.getenv("SHEET_ID",     "1NFr0P0lEwiHvg7FC_HQaTnaQfUoONQeNBEaMsA8f3K8")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS", "")

# ═══ RULES ══════════════════════════════════════════
TARGET_PCT       = 10.0
SL_PCT           = 5.0
TRAIL_SL_PCT     = 3.0
DAILY_LOSS_LIMIT = 5.0
MAX_TRADE_PCT    = 0.20

# ═══ INDICES ════════════════════════════════════════
INDICES = {
    "NIFTY":      {"token": "99926000", "exchange": "NSE", "gap": 50,  "lot": 50,  "exch": "NFO"},
    "BANKNIFTY":  {"token": "99926009", "exchange": "NSE", "gap": 100, "lot": 15,  "exch": "NFO"},
    "SENSEX":     {"token": "99919000", "exchange": "BSE", "gap": 100, "lot": 10,  "exch": "BFO"},
    "MIDCPNIFTY": {"token": "99926074", "exchange": "NSE", "gap": 25,  "lot": 75,  "exch": "NFO"},
    "BANKEX":     {"token": "99919012", "exchange": "BSE", "gap": 100, "lot": 15,  "exch": "BFO"},
    "FINNIFTY":   {"token": "99926037", "exchange": "NSE", "gap": 50,  "lot": 40,  "exch": "NFO"},
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
log = logging.getLogger("AngelBot")


def tg(msg):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            "https://api.telegram.org/bot" + TG_TOKEN + "/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=5
        )
    except:
        pass


def save_to_sheets(row):
    if not GOOGLE_CREDS or not SHEET_ID:
        return
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        creds = json.loads(GOOGLE_CREDS)
        token_url = "https://oauth2.googleapis.com/token"
        now = int(time.time())
        hdr = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).decode().rstrip("=")
        pld = base64.urlsafe_b64encode(json.dumps({
            "iss": creds["client_email"],
            "scope": "https://www.googleapis.com/auth/spreadsheets",
            "aud": token_url, "exp": now + 3600, "iat": now
        }).encode()).decode().rstrip("=")
        pk = serialization.load_pem_private_key(creds["private_key"].encode(), password=None)
        sig = base64.urlsafe_b64encode(
            pk.sign((hdr + "." + pld).encode(), padding.PKCS1v15(), hashes.SHA256())
        ).decode().rstrip("=")
        jwt = hdr + "." + pld + "." + sig
        r = requests.post(token_url, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": jwt
        }, timeout=10)
        access_token = r.json()["access_token"]
        requests.post(
            "https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID + "/values/Sheet1!A1:append",
            headers={"Authorization": "Bearer " + access_token},
            params={"valueInputOption": "RAW"},
            json={"values": [row]},
            timeout=10
        )
        log.info("Google Sheets updated!")
    except Exception as e:
        log.warning("Sheets error: " + str(e))


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
        k = 2.0 / (n + 1)
        e = arr[-n]
        for x in arr[-n+1:]:
            e = x * k + e * (1 - k)
        return round(e, 2)

    def rsi(self, arr, n=14):
        if len(arr) < n + 1:
            return 50.0
        d = np.diff(arr[-(n+1):])
        g = d[d > 0].mean() if (d > 0).any() else 1e-9
        l = abs(d[d < 0].mean()) if (d < 0).any() else 1e-9
        return round(100 - 100 / (1 + g / l), 2)

    def analyze(self, index):
        arr = self.prices[index]
        if len(arr) < 15:
            return None, 0, []
        cur = arr[-1]
        rsi_v = self.rsi(arr)
        macd_v = round(self.ema(arr, 12) - self.ema(arr, 26), 2)
        e9 = self.ema(arr, 9)
        e21 = self.ema(arr, 21)
        vwap = round(np.mean(arr[-20:]), 2) if len(arr) >= 20 else cur

        ce = pe = 0
        reasons = []

        if rsi_v < 30:
            ce += 35
            reasons.append("RSI=" + str(rsi_v) + " oversold->CE")
        elif rsi_v < 40:
            ce += 20
        elif rsi_v > 70:
            pe += 35
            reasons.append("RSI=" + str(rsi_v) + " overbought->PE")
        elif rsi_v > 60:
            pe += 20

        if macd_v > 0:
            ce += 25
            reasons.append("MACD bullish->CE")
        else:
            pe += 25
            reasons.append("MACD bearish->PE")

        if cur > e9 > e21:
            ce += 25
            reasons.append("Uptrend->CE")
        elif cur < e9 < e21:
            pe += 25
            reasons.append("Downtrend->PE")

        if cur > vwap:
            ce += 10
        else:
            pe += 10

        total = ce + pe
        if total == 0:
            return None, 0, []

        if ce > pe:
            return "CE", min(95, int(ce / total * 100 + 10)), reasons
        else:
            return "PE", min(95, int(pe / total * 100 + 10)), reasons

    def best_signal(self, prices_dict):
        best = (None, None, 0, [])
        for idx in INDICES:
            if not prices_dict.get(idx):
                continue
            d, conf, reasons = self.analyze(idx)
            if d and conf > best[2]:
                best = (idx, d, conf, reasons)
        return best


class AngelBot:
    def __init__(self):
        self.api = None
        self.brain = AIBrain()
        self.position = None
        self.trades_today = 0
        self.pnl_today = 0.0
        self.daily_log = []
        self.last_date = date.today()
        self.spot_prices = {}
        self.nfo_tokens = {}
        self.highest_price = 0

    def get_public_ip(self):
        try:
            r = requests.get("https://api.ipify.org?format=json", timeout=5)
            ip = r.json()["ip"]
            log.info("Public IP: " + ip)
            return ip
        except:
            return "106.193.147.98"

    def login(self):
        try:
            public_ip = self.get_public_ip()
            totp = pyotp.TOTP(TOTP_SECRET).now()
            self.api = SmartConnect(api_key=API_KEY)
            self.api.root = "https://apiconnect.angelbroking.com"
            # Set correct public IP
            import SmartApi.smartConnect as sc
            sc.DEFAULT_PUBLIC_IP = public_ip
            r = self.api.generateSession(CLIENT_ID, PASSWORD, totp)
            if r["status"]:
                log.info("Login OK: " + CLIENT_ID)
                tg("<b>AngelBot Started!</b>\nCapital: Rs." + str(CAPITAL) + "\nTarget: " + str(TARGET_PCT) + "% | SL: " + str(SL_PCT) + "%")
                return True
            log.error("Login failed: " + r["message"])
        except Exception as e:
            log.error("Login error: " + str(e))
        return False

    def load_nfo_tokens(self):
        if self.nfo_tokens:
            return
        try:
            r = requests.get(
                "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            data = r.json()
            for s in data:
                if s.get("exch_seg") in ["NFO", "BFO"] and s.get("instrumenttype") in ["OPTIDX"]:
                    self.nfo_tokens[s["symbol"]] = s["token"]
            log.info("NFO tokens loaded: " + str(len(self.nfo_tokens)))
        except Exception as e:
            log.warning("NFO load error: " + str(e))

    def find_token(self, index, strike, direction):
        self.load_nfo_tokens()
        cfg = INDICES[index]
        opt = direction  # CE or PE
        # Search for matching symbol
        for name, tok in self.nfo_tokens.items():
            if (name.startswith(index) and
                    name.endswith(opt) and
                    str(strike) in name):
                log.info("Token found: " + name + " = " + tok)
                return name, tok
        log.warning("Token not found for " + index + " " + str(strike) + " " + opt)
        return None, None

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
        return self.pnl_today <= -(CAPITAL * DAILY_LOSS_LIMIT / 100)

    def get_ltp(self, token, exchange="NSE"):
        try:
            r = self.api.ltpData(exchange, "", token)
            if r["status"]:
                return float(r["data"]["ltp"])
        except Exception as e:
            log.warning("LTP error: " + str(e))
        return None

    def place_order(self, symbol, token, side, qty, exchange):
        try:
            r = self.api.placeOrder({
                "variety": "NORMAL",
                "tradingsymbol": symbol,
                "symboltoken": token,
                "transactiontype": side,
                "exchange": exchange,
                "ordertype": "MARKET",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "price": "0",
                "quantity": str(qty),
            })
            if r["status"]:
                oid = r["data"]["orderid"]
                log.info("Order OK: " + side + " " + symbol + " x" + str(qty) + " ID:" + str(oid))
                return oid
            log.error("Order failed: " + r["message"])
        except Exception as e:
            log.error("Order error: " + str(e))
        return None

    def open_trade(self, index, direction, reasons):
        cfg = INDICES[index]
        spot = self.spot_prices.get(index)
        if not spot:
            return

        strike = int(round(spot / cfg["gap"]) * cfg["gap"])
        sym, token = self.find_token(index, strike, direction)

        if not token:
            return

        price = self.get_ltp(token, cfg["exch"])
        if not price or price < 5:
            log.warning("Option price too low: " + str(price))
            return

        lots = max(1, int(CAPITAL * MAX_TRADE_PCT / (price * cfg["lot"])))
        qty = lots * cfg["lot"]
        sl = round(price * (1 - SL_PCT / 100), 2)
        tp = round(price * (1 + TARGET_PCT / 100), 2)

        oid = self.place_order(sym, token, "BUY", qty, cfg["exch"])
        if oid:
            self.position = {
                "index": index, "direction": direction,
                "symbol": sym, "token": token,
                "exchange": cfg["exch"], "qty": qty,
                "entry": price, "sl": sl, "tp": tp,
                "highest": price, "open_time": datetime.now(),
            }
            self.highest_price = price
            self.trades_today += 1
            reason_str = " | ".join(reasons[:3])
            log.info("TRADE OPEN: " + index + " " + direction + " " + str(strike) + " Rs." + str(price))
            tg("<b>TRADE OPEN</b>\n" + index + " " + direction + " " + str(strike) + "\nEntry: Rs." + str(price) + "\nSL: Rs." + str(sl) + " | TP: Rs." + str(tp) + "\n" + reason_str)

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
            log.info("TRADE CLOSED: " + reason + " P&L Rs." + str(pnl))
            emoji = "PROFIT" if pnl > 0 else "LOSS"
            tg("<b>TRADE CLOSED - " + emoji + "</b>\n" + p["symbol"] + "\nEntry: Rs." + str(p["entry"]) + " | Exit: Rs." + str(price) + "\nP&L: Rs." + str(pnl) + " (" + str(pnl_pct) + "%)\nReason: " + reason + "\nToday: Rs." + str(round(self.pnl_today, 2)))
            now = datetime.now()
            save_to_sheets([
                now.strftime("%d-%m-%Y"), now.strftime("%H:%M:%S"),
                p["index"], p["direction"], str(p["entry"]),
                str(price), str(p["qty"]), str(pnl), str(pnl_pct),
                reason, dur, str(round(self.pnl_today, 2))
            ])
            self.daily_log.append({"pnl": pnl})
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
        log.info("Monitor: " + p["symbol"] + " Rs." + str(price) + " " + str(round(pct, 2)) + "%")

        # Trailing SL
        if price > self.highest_price:
            self.highest_price = price
            new_sl = round(price * (1 - TRAIL_SL_PCT / 100), 2)
            if new_sl > p["sl"]:
                p["sl"] = new_sl
                log.info("Trailing SL: Rs." + str(new_sl))

        if price >= p["tp"]:
            self.close_trade(price, "TARGET +" + str(TARGET_PCT) + "%")
        elif price <= p["sl"]:
            self.close_trade(price, "STOP LOSS -" + str(SL_PCT) + "%")

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
        ret = round(self.pnl_today / CAPITAL * 100, 2)
        log.info("DAY DONE | P&L Rs." + str(round(self.pnl_today, 2)) + " | W:" + str(wins) + " L:" + str(loss))
        tg("<b>Day Summary</b>\nTrades: " + str(self.trades_today) + "\nWins: " + str(wins) + " | Loss: " + str(loss) + "\nP&L: Rs." + str(round(self.pnl_today, 2)) + "\nReturn: " + str(ret) + "%")

    def run(self):
        log.info("AngelBot PRO MAX v4.0 Starting...")
        if not self.login():
            return

        # Load NFO tokens at startup
        self.load_nfo_tokens()

        while True:
            now = datetime.now()

            # New day reset
            if now.date() != self.last_date:
                self.daily_summary()
                self.trades_today = 0
                self.pnl_today = 0.0
                self.daily_log = []
                self.last_date = now.date()
                self.nfo_tokens = {}  # Reload tokens each day
                self.login()
                self.load_nfo_tokens()

            # Market closed - sleep till next open
            if not self.is_market_open():
                next_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
                if now.time() >= dtime(15, 30):
                    next_open += timedelta(days=1)
                    while next_open.weekday() >= 5:
                        next_open += timedelta(days=1)
                secs = max(60, (next_open - now).total_seconds())
                log.info("Market closed. Sleeping " + str(int(secs // 3600)) + "h " + str(int((secs % 3600) // 60)) + "m")
                time.sleep(secs)
                continue

            # Force close at 3:10 PM
            if self.closing_time():
                if self.position:
                    p = self.get_ltp(self.position["token"], self.position["exchange"])
                    self.close_trade(p or self.position["entry"], "Market Close 3:10PM")
                self.daily_summary()
                time.sleep(300)
                continue

            # Daily loss limit
            if self.daily_loss_hit():
                if self.position:
                    p = self.get_ltp(self.position["token"], self.position["exchange"])
                    self.close_trade(p or self.position["entry"], "Daily Loss Limit")
                tg("Daily loss limit hit! Bot stopped for today.")
                time.sleep(300)
                continue

            # Fetch prices
            for idx, cfg in INDICES.items():
                price = self.get_ltp(cfg["token"], cfg["exchange"])
                if price:
                    self.spot_prices[idx] = price
                    self.brain.add(idx, price)
                    log.info(idx + ": Rs." + str(price))

            # Monitor position
            if self.position:
                self.monitor()
                time.sleep(60)
                continue

            if self.trades_today >= self.max_trades():
                log.info("Max trades done: " + str(self.trades_today))
                time.sleep(60)
                continue

            if not self.best_time():
                time.sleep(60)
                continue

            # AI Signal
            idx, direction, conf, reasons = self.brain.best_signal(self.spot_prices)
            log.info("AI: " + str(idx) + " " + str(direction) + " " + str(conf) + "%")
            for r in reasons[:3]:
                log.info("  -> " + r)

            if not idx or conf < 60:
                log.info("Signal weak (" + str(conf) + "%) - waiting...")
                time.sleep(60)
                continue

            log.info("SIGNAL: " + idx + " " + direction + " " + str(conf) + "%")
            self.open_trade(idx, direction, reasons)
            time.sleep(60)


if __name__ == "__main__":
    bot = AngelBot()
    bot.run()
