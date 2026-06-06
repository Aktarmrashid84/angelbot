"""
╔══════════════════════════════════════════════════════╗
║   AngelBot PRO — AI Options Trading Bot              ║
║   Nifty/BankNifty CE/PE Auto Trading                 ║
║   Target: 10%  |  Stop Loss: 5%                     ║
║   24/7 Cloud — Phone/Laptop OFF ho tab bhi chalta    ║
╚══════════════════════════════════════════════════════╝
"""

import os, time, logging, math, json, requests
from datetime import datetime, date, timedelta, time as dtime
from SmartApi import SmartConnect
import pyotp
import numpy as np

# ═══════════════════════════════════════════════════════
#  SIRF YEH BHARO — BAAKI SAB BOT KHUD DECIDE KAREGA
# ═══════════════════════════════════════════════════════
API_KEY      = os.getenv("ANGEL_API_KEY",   "rjRimMjk")
CLIENT_ID    = os.getenv("ANGEL_CLIENT_ID", "M410221")
PASSWORD     = os.getenv("ANGEL_PASSWORD",  "APNA_PIN")
TOTP_SECRET  = os.getenv("ANGEL_TOTP",      "NNWTNV7ZSNVUYRNF4ZY4TY3LDU")
CAPITAL      = float(os.getenv("CAPITAL",   "50000"))   # aapka total capital ₹

# ═══════════════════════════════════════════════════════
#  FIXED RULES (aapki marzi ke hisaab se)
# ═══════════════════════════════════════════════════════
TARGET_PCT   = 10.0   # 10% profit pe exit
SL_PCT       = 5.0    # 5% loss pe exit
MAX_CAPITAL_PER_TRADE_PCT = 20  # capital ka max 20% ek trade mein
MAX_TRADES_PER_DAY = 0  # 0 = bot khud decide karta hai (market condition ke hisaab se)

# ═══════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("AngelBotPRO")

# ─── INDEX CONFIG ──────────────────────────────────────
INDICES = {
    "NIFTY": {
        "token":        "99926000",
        "exchange":     "NSE",
        "strike_gap":   50,       # Nifty strikes 50-50 pe hote hain
        "lot_size":     50,       # 1 lot = 50 qty
        "option_exch":  "NFO",
    },
    "BANKNIFTY": {
        "token":        "99926009",
        "exchange":     "NSE",
        "strike_gap":   100,      # BankNifty strikes 100-100
        "lot_size":     15,
        "option_exch":  "NFO",
    }
}


class MarketBrain:
    """AI brain — khud decide karta hai kya karna hai"""

    def __init__(self):
        self.price_history = {"NIFTY": [], "BANKNIFTY": []}
        self.vix_history   = []

    def add_price(self, index, price):
        h = self.price_history[index]
        h.append(float(price))
        if len(h) > 200:
            h.pop(0)

    # ── RSI ──────────────────────────────────────────
    def rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50.0
        deltas = np.diff(prices[-(period+1):])
        g = deltas[deltas > 0].mean() if (deltas > 0).any() else 1e-9
        l = abs(deltas[deltas < 0].mean()) if (deltas < 0).any() else 1e-9
        return round(100 - 100 / (1 + g / l), 2)

    # ── EMA ──────────────────────────────────────────
    def ema(self, prices, period):
        if len(prices) < period:
            return prices[-1]
        k, e = 2 / (period + 1), prices[-period]
        for p in prices[-period+1:]:
            e = p * k + e * (1 - k)
        return round(e, 2)

    # ── MACD ─────────────────────────────────────────
    def macd(self, prices):
        if len(prices) < 26:
            return 0.0
        return round(self.ema(prices, 12) - self.ema(prices, 26), 2)

    # ── SUPERTREND (simplified) ────────────────────
    def supertrend_signal(self, prices):
        if len(prices) < 20:
            return "neutral"
        mid = np.mean(prices[-20:])
        cur = prices[-1]
        if cur > mid * 1.002:
            return "bullish"
        elif cur < mid * 0.998:
            return "bearish"
        return "neutral"

    # ── BOLLINGER BANDS ───────────────────────────
    def bollinger(self, prices, period=20):
        if len(prices) < period:
            return None, None, None
        arr  = np.array(prices[-period:])
        mid  = arr.mean()
        std  = arr.std()
        return round(mid + 2*std, 2), round(mid, 2), round(mid - 2*std, 2)

    # ── VOLATILITY ────────────────────────────────
    def volatility(self, prices, period=10):
        if len(prices) < period + 1:
            return 1.0
        returns = np.diff(np.log(prices[-period-1:]))
        return round(float(np.std(returns) * 100), 3)

    # ══════════════════════════════════════════════
    #  MAIN DECISION — Bot khud decide karta hai
    #  Returns: (index, ce_or_pe, confidence, reasons)
    # ══════════════════════════════════════════════
    def decide(self, nifty_price, banknifty_price):
        scores = {"NIFTY_CE": 0, "NIFTY_PE": 0,
                  "BANKNIFTY_CE": 0, "BANKNIFTY_PE": 0}
        reasons = []

        for idx, price in [("NIFTY", nifty_price), ("BANKNIFTY", banknifty_price)]:
            ph = self.price_history[idx]
            if len(ph) < 15:
                reasons.append(f"{idx}: data collect ho raha hai ({len(ph)}/15)")
                continue

            rsi_val  = self.rsi(ph)
            macd_val = self.macd(ph)
            st_sig   = self.supertrend_signal(ph)
            ub, mb, lb = self.bollinger(ph)
            vol      = self.volatility(ph)
            ema9     = self.ema(ph, 9)
            ema21    = self.ema(ph, 21)
            cur      = ph[-1]

            # ── BULLISH signals → BUY CE ──────────
            if rsi_val < 35:
                scores[f"{idx}_CE"] += 35
                reasons.append(f"{idx} RSI={rsi_val} oversold → CE")
            if rsi_val > 65:
                scores[f"{idx}_PE"] += 35
                reasons.append(f"{idx} RSI={rsi_val} overbought → PE")

            if macd_val > 0:
                scores[f"{idx}_CE"] += 25
                reasons.append(f"{idx} MACD={macd_val} bullish → CE")
            else:
                scores[f"{idx}_PE"] += 25
                reasons.append(f"{idx} MACD={macd_val} bearish → PE")

            if st_sig == "bullish":
                scores[f"{idx}_CE"] += 20
                reasons.append(f"{idx} Supertrend bullish → CE")
            elif st_sig == "bearish":
                scores[f"{idx}_PE"] += 20
                reasons.append(f"{idx} Supertrend bearish → PE")

            if ub and cur > ub:
                scores[f"{idx}_PE"] += 15
                reasons.append(f"{idx} price above upper BB → PE reversal")
            elif lb and cur < lb:
                scores[f"{idx}_CE"] += 15
                reasons.append(f"{idx} price below lower BB → CE bounce")

            if ema9 > ema21:
                scores[f"{idx}_CE"] += 15
                reasons.append(f"{idx} EMA9>EMA21 uptrend → CE")
            else:
                scores[f"{idx}_PE"] += 15
                reasons.append(f"{idx} EMA9<EMA21 downtrend → PE")

            # High volatility mein zyada lot size adjust
            if vol > 0.3:
                scores[f"{idx}_CE"] = int(scores[f"{idx}_CE"] * 0.9)
                scores[f"{idx}_PE"] = int(scores[f"{idx}_PE"] * 0.9)
                reasons.append(f"{idx} high volatility — score reduced")

        # ── Best option select karo ────────────────
        best = max(scores, key=scores.get)
        best_score = scores[best]

        if best_score < 50:
            return None, None, best_score, ["Signal weak — wait karo"]

        parts     = best.split("_")
        index     = parts[0]
        direction = parts[1]  # CE or PE
        return index, direction, best_score, reasons

    # ── How many trades today ─────────────────────
    def max_trades_today(self, vix_approx=15):
        """Market condition ke hisaab se decide karta hai"""
        if vix_approx > 20:
            return 2   # high volatility — cautious
        elif vix_approx > 15:
            return 3   # normal
        else:
            return 4   # low volatility — more trades ok


class OptionsHelper:
    """Option strike dhundhta hai"""

    @staticmethod
    def nearest_strike(price, gap):
        return int(round(price / gap) * gap)

    @staticmethod
    def get_expiry():
        """Current week ka Thursday expiry"""
        today = date.today()
        days_till_thu = (3 - today.weekday()) % 7
        expiry = today + timedelta(days=days_till_thu)
        if expiry < today:
            expiry += timedelta(days=7)
        return expiry.strftime("%d%b%Y").upper()  # e.g. 06JUN2024

    @staticmethod
    def build_symbol(index, strike, direction, expiry):
        """e.g. NIFTY06JUN2024C24000"""
        opt_type = "C" if direction == "CE" else "P"
        return f"{index}{expiry}{opt_type}{strike}"


class AngelBotPRO:

    def __init__(self):
        self.api        = None
        self.brain      = MarketBrain()
        self.opt        = OptionsHelper()
        self.position   = None
        self.trades_today = 0
        self.pnl_today  = 0.0
        self.daily_log  = []
        self.last_date  = date.today()

    # ── LOGIN ─────────────────────────────────────
    def login(self):
        try:
            totp = pyotp.TOTP(TOTP_SECRET).now()
            self.api = SmartConnect(api_key=API_KEY)
            data = self.api.generateSession(CLIENT_ID, PASSWORD, totp)
            if data["status"]:
                log.info(f"✓ Login success: {CLIENT_ID}")
                return True
            log.error(f"✗ Login failed: {data['message']}")
        except Exception as e:
            log.error(f"Login exception: {e}")
        return False

    # ── MARKET HOURS ──────────────────────────────
    def is_market_open(self):
        now   = datetime.now()
        t     = now.time()
        wday  = now.weekday()
        if wday >= 5:
            return False
        return dtime(9, 15) <= t <= dtime(15, 25)

    def is_trading_window(self):
        """Best time for intraday options: 9:20 to 3:15"""
        t = datetime.now().time()
        return dtime(9, 20) <= t <= dtime(15, 15)

    def time_to_close(self):
        return datetime.now().time() >= dtime(15, 15)

    # ── GET PRICE ─────────────────────────────────
    def get_ltp(self, token, exchange="NSE"):
        try:
            data = self.api.ltpData(exchange, "", token)
            if data["status"]:
                return float(data["data"]["ltp"])
        except Exception as e:
            log.warning(f"LTP error token={token}: {e}")
        return None

    # ── GET OPTION TOKEN ──────────────────────────
    def get_option_token(self, symbol, exchange="NFO"):
        """Option ka token fetch karo Angel API se"""
        try:
            data = self.api.searchScrip(exchange, symbol)
            if data["status"] and data["data"]:
                return data["data"][0]["symboltoken"]
        except Exception as e:
            log.warning(f"Option token error {symbol}: {e}")
        return None

    # ── PLACE ORDER ───────────────────────────────
    def place_order(self, symbol, token, side, qty, exchange="NFO"):
        try:
            order = self.api.placeOrder({
                "variety":         "NORMAL",
                "tradingsymbol":   symbol,
                "symboltoken":     token,
                "transactiontype": side,
                "exchange":        exchange,
                "ordertype":       "MARKET",
                "producttype":     "INTRADAY",
                "duration":        "DAY",
                "price":           "0",
                "squareoff":       "0",
                "stoploss":        "0",
                "quantity":        str(qty),
            })
            if order["status"]:
                oid = order["data"]["orderid"]
                log.info(f"✓ ORDER: {side} {symbol} x{qty} | ID:{oid}")
                return oid
            else:
                log.error(f"✗ Order failed: {order['message']}")
        except Exception as e:
            log.error(f"Order exception: {e}")
        return None

    # ── EXECUTE TRADE ─────────────────────────────
    def open_trade(self, index, direction, entry_price):
        cfg        = INDICES[index]
        lot_size   = cfg["lot_size"]
        max_cap    = CAPITAL * MAX_CAPITAL_PER_TRADE_PCT / 100
        lots       = max(1, int(max_cap / (entry_price * lot_size)))
        qty        = lots * lot_size

        # Strike calculation
        spot       = self.get_ltp(cfg["token"], cfg["exchange"])
        if not spot:
            log.error("Cannot get spot price"); return

        strike     = self.opt.nearest_strike(spot, cfg["strike_gap"])
        expiry     = self.opt.get_expiry()
        symbol     = self.opt.build_symbol(index, strike, direction, expiry)
        token      = self.get_option_token(symbol, cfg["option_exch"])

        if not token:
            log.error(f"Token not found for {symbol}"); return

        sl_px  = round(entry_price * (1 - SL_PCT / 100), 2)
        tp_px  = round(entry_price * (1 + TARGET_PCT / 100), 2)

        oid = self.place_order(symbol, token, "BUY", qty, cfg["option_exch"])
        if oid:
            self.position = {
                "index":     index,
                "direction": direction,
                "symbol":    symbol,
                "token":     token,
                "exchange":  cfg["option_exch"],
                "qty":       qty,
                "lots":      lots,
                "entry":     entry_price,
                "sl":        sl_px,
                "tp":        tp_px,
                "oid":       oid,
                "open_time": datetime.now(),
            }
            self.trades_today += 1
            log.info(f"★ TRADE OPEN | {index} {direction} {strike} | "
                     f"Entry ₹{entry_price} | SL ₹{sl_px} | TP ₹{tp_px} | "
                     f"Qty:{qty} ({lots} lots)")

    def close_trade(self, current_price, reason):
        if not self.position:
            return
        pos = self.position
        oid = self.place_order(
            pos["symbol"], pos["token"], "SELL",
            pos["qty"], pos["exchange"]
        )
        if oid:
            pnl = round((current_price - pos["entry"]) * pos["qty"], 2)
            self.pnl_today += pnl
            duration = str(datetime.now() - pos["open_time"]).split(".")[0]

            log.info(f"★ TRADE CLOSED [{reason}]")
            log.info(f"  Entry: ₹{pos['entry']}  Exit: ₹{current_price}")
            log.info(f"  P&L: ₹{pnl}  Duration: {duration}")
            log.info(f"  Today P&L: ₹{self.pnl_today} | Trades: {self.trades_today}")

            self.daily_log.append({
                "symbol":  pos["symbol"],
                "entry":   pos["entry"],
                "exit":    current_price,
                "pnl":     pnl,
                "reason":  reason,
                "time":    str(datetime.now()),
            })
            self.position = None

    # ── MONITOR OPEN POSITION ─────────────────────
    def monitor_position(self):
        if not self.position:
            return
        pos   = self.position
        price = self.get_ltp(pos["token"], pos["exchange"])
        if not price:
            return

        pct_change = (price - pos["entry"]) / pos["entry"] * 100
        log.info(f"  Position: {pos['symbol']} | Now ₹{price} | "
                 f"Change: {pct_change:+.2f}% | SL ₹{pos['sl']} | TP ₹{pos['tp']}")

        if price >= pos["tp"]:
            log.info(f"TARGET HIT! +{TARGET_PCT}%")
            self.close_trade(price, f"TARGET +{TARGET_PCT}%")
        elif price <= pos["sl"]:
            log.info(f"STOP LOSS HIT! -{SL_PCT}%")
            self.close_trade(price, f"STOP LOSS -{SL_PCT}%")

    # ── DAILY SUMMARY ─────────────────────────────
    def daily_summary(self):
        wins   = sum(1 for t in self.daily_log if t["pnl"] > 0)
        losses = sum(1 for t in self.daily_log if t["pnl"] <= 0)
        log.info("=" * 55)
        log.info(f"  DAY SUMMARY — {date.today()}")
        log.info(f"  Total Trades : {self.trades_today}")
        log.info(f"  Wins         : {wins}")
        log.info(f"  Losses       : {losses}")
        log.info(f"  Net P&L      : ₹{round(self.pnl_today, 2)}")
        log.info(f"  Capital      : ₹{CAPITAL}")
        log.info(f"  Return       : {round(self.pnl_today/CAPITAL*100, 2)}%")
        log.info("=" * 55)
        # Save to file
        with open(f"summary_{date.today()}.json", "w") as f:
            json.dump({
                "date":        str(date.today()),
                "pnl":         self.pnl_today,
                "trades":      self.trades_today,
                "wins":        wins,
                "losses":      losses,
                "trade_log":   self.daily_log,
            }, f, indent=2)

    # ══════════════════════════════════════════════
    #  MAIN LOOP
    # ══════════════════════════════════════════════
    def run(self):
        log.info("╔══════════════════════════════════════════════════╗")
        log.info("║   AngelBot PRO — AI Options Trading Bot          ║")
        log.info(f"║   Capital: ₹{CAPITAL:<10} SL: {SL_PCT}%  TP: {TARGET_PCT}%          ║")
        log.info("╚══════════════════════════════════════════════════╝")

        if not self.login():
            log.error("Login failed — exiting"); return

        vix_approx    = 15
        scan_interval = 60  # seconds
        max_trades    = self.brain.max_trades_today(vix_approx)
        log.info(f"Today max trades allowed: {max_trades}")

        while True:
            now = datetime.now()

            # ── New day reset ───────────────────────
            if now.date() != self.last_date:
                self.daily_summary()
                self.trades_today = 0
                self.pnl_today    = 0.0
                self.daily_log    = []
                self.last_date    = now.date()
                self.login()  # re-login
                max_trades = self.brain.max_trades_today(vix_approx)
                log.info(f"New day! Max trades: {max_trades}")

            # ── Market closed ───────────────────────
            if not self.is_market_open():
                log.info("Market closed. Next scan in 5 mins...")
                time.sleep(300)
                continue

            # ── Square off time ─────────────────────
            if self.time_to_close():
                if self.position:
                    log.warning("3:15 PM — Force closing all positions")
                    price = self.get_ltp(
                        self.position["token"],
                        self.position["exchange"]
                    ) or self.position["entry"]
                    self.close_trade(price, "Market Close 3:15PM")
                self.daily_summary()
                log.info("Sleeping till tomorrow 9:15 AM...")
                time.sleep(300)
                continue

            # ── Fetch index prices ──────────────────
            nifty_price = self.get_ltp(
                INDICES["NIFTY"]["token"],
                INDICES["NIFTY"]["exchange"]
            )
            banknifty_price = self.get_ltp(
                INDICES["BANKNIFTY"]["token"],
                INDICES["BANKNIFTY"]["exchange"]
            )

            if nifty_price:
                self.brain.add_price("NIFTY", nifty_price)
                log.info(f"Nifty: {nifty_price}")
            if banknifty_price:
                self.brain.add_price("BANKNIFTY", banknifty_price)
                log.info(f"BankNifty: {banknifty_price}")

            # ── Monitor open position ───────────────
            if self.position:
                self.monitor_position()
                time.sleep(scan_interval)
                continue

            # ── Check if can take new trade ─────────
            if not self.is_trading_window():
                log.info("Outside ideal trading window (9:20-3:15)")
                time.sleep(scan_interval)
                continue

            if self.trades_today >= max_trades:
                log.info(f"Max trades ({max_trades}) done today. Monitoring only.")
                time.sleep(scan_interval)
                continue

            # ── AI Decision ─────────────────────────
            index, direction, confidence, reasons = self.brain.decide(
                nifty_price or 0,
                banknifty_price or 0
            )

            for r in reasons:
                log.info(f"  Brain: {r}")

            if not index or confidence < 55:
                log.info(f"Signal weak ({confidence}) — skipping. Next scan in {scan_interval}s")
                time.sleep(scan_interval)
                continue

            # ── Get option price and trade ───────────
            cfg   = INDICES[index]
            spot  = nifty_price if index == "NIFTY" else banknifty_price
            if not spot:
                time.sleep(scan_interval); continue

            strike  = OptionsHelper.nearest_strike(spot, cfg["strike_gap"])
            expiry  = OptionsHelper.get_expiry()
            symbol  = OptionsHelper.build_symbol(index, strike, direction, expiry)
            token   = self.get_option_token(symbol, cfg["option_exch"])

            if token:
                option_price = self.get_ltp(token, cfg["option_exch"])
                if option_price and option_price > 5:
                    log.info(
                        f"SIGNAL: {index} {direction} {strike} | "
                        f"Option ₹{option_price} | Confidence: {confidence}%"
                    )
                    self.open_trade(index, direction, option_price)
                else:
                    log.warning(f"Option price too low or unavailable: {option_price}")
            else:
                log.warning(f"Could not find token for {symbol}")

            time.sleep(scan_interval)


if __name__ == "__main__":
    bot = AngelBotPRO()
    bot.run()
