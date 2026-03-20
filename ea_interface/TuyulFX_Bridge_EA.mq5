//+------------------------------------------------------------------+
//| TuyulFX Bridge EA — DUMB EXECUTOR                                 |
//| Reads JSON commands from file, executes, writes reports           |
//| ZERO intelligence. ZERO analysis. ZERO overrides.                  |
//| All trade decisions come exclusively from L12 Constitution via    |
//| the dashboard risk governor. This EA only executes what it reads. |
//+------------------------------------------------------------------+
#property copyright "TuyulFX"
#property version   "2.00"
#property strict

#include <Trade\Trade.mqh>

input string BridgeDir       = "C:\\TuyulFX\\bridge"; // Bridge directory path
input int    PollIntervalMs  = 500;                    // Poll interval in milliseconds
input int    MagicNumber     = 151515;                 // Magic number for our orders
input int    MaxSlippagePoints = 20;                   // Max slippage on market orders (points)

CTrade g_trade;

//+------------------------------------------------------------------+
//| Expert initialization function                                     |
//+------------------------------------------------------------------+
int OnInit()
{
    string cmd_dir     = BridgeDir + "\\commands";
    string reports_dir = BridgeDir + "\\reports";
    string archive_dir = BridgeDir + "\\archive";

    if(!FileIsExist(cmd_dir + "\\", FILE_COMMON))
        Print("WARN: Bridge commands dir not found — EA will poll anyway: ", cmd_dir);

    g_trade.SetExpertMagicNumber(MagicNumber);
    g_trade.SetDeviationInPoints(MaxSlippagePoints);
    g_trade.SetTypeFilling(ORDER_FILLING_IOC);
    g_trade.LogLevel(LOG_LEVEL_ERRORS);

    Print("TuyulFX Bridge EA v2 initialized. BridgeDir=", BridgeDir,
          " | Poll=", PollIntervalMs, "ms | Magic=", MagicNumber);
    EventSetMillisecondTimer(PollIntervalMs);
    return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                    |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    EventKillTimer();
    Print("TuyulFX Bridge EA deinitialized. Reason: ", reason);
}

//+------------------------------------------------------------------+
//| Timer — poll commands directory for new JSON files                 |
//+------------------------------------------------------------------+
void OnTimer()
{
    string filename;
    string pattern = BridgeDir + "\\commands\\*.json";
    long   search  = FileFindFirst(pattern, filename, FILE_COMMON);

    if(search == INVALID_HANDLE)
        return;

    do
    {
        string full_path = BridgeDir + "\\commands\\" + filename;
        ProcessCommandFile(full_path, filename);
    }
    while(FileFindNext(search, filename));

    FileFindClose(search);
}

//+------------------------------------------------------------------+
//| ── JSON HELPERS ──────────────────────────────────────────────── |
//| Minimal hand-rolled parser: no dependencies, no extra libs.       |
//+------------------------------------------------------------------+

// Extract string value for a given key, e.g. "symbol": "EURUSD"
string JsonGetString(const string &json, const string key, const string def = "")
{
    string search = "\"" + key + "\"";
    int pos = StringFind(json, search);
    if(pos < 0) return def;
    pos = StringFind(json, ":", pos + (int)StringLen(search));
    if(pos < 0) return def;
    pos++;
    // skip whitespace
    while(pos < StringLen(json) && StringGetCharacter(json, pos) == ' ') pos++;
    if(pos >= StringLen(json)) return def;
    ushort ch = StringGetCharacter(json, pos);
    if(ch == '"')
    {
        pos++; // skip opening quote
        int end = StringFind(json, "\"", pos);
        if(end < 0) return def;
        return StringSubstr(json, pos, end - pos);
    }
    // bare value (number / bool / null)
    int end = pos;
    while(end < StringLen(json))
    {
        ushort c = StringGetCharacter(json, end);
        if(c == ',' || c == '}' || c == '\n' || c == '\r') break;
        end++;
    }
    return StringSubstr(json, pos, end - pos);
}

// Extract numeric (double) value
double JsonGetDouble(const string &json, const string key, const double def = 0.0)
{
    string s = JsonGetString(json, key, "");
    if(StringLen(s) == 0) return def;
    return StringToDouble(s);
}

// Extract integer value
long JsonGetLong(const string &json, const string key, const long def = 0)
{
    string s = JsonGetString(json, key, "");
    if(StringLen(s) == 0) return def;
    return StringToInteger(s);
}

//+------------------------------------------------------------------+
//| Write execution report JSON to reports directory                   |
//+------------------------------------------------------------------+
void WriteReport(
    const string signal_id,
    const string event,           // ORDER_PLACED, ORDER_FILLED, ORDER_CANCELLED, ORDER_FAILED
    const long   broker_ticket,
    const double fill_price,
    const double slippage_pips,
    const string error_message)
{
    string ts      = DoubleToString((double)TimeTradeServer(), 0);
    string report  = "{\n";
    report += "  \"signal_id\": \""    + signal_id      + "\",\n";
    report += "  \"event\": \""        + event           + "\",\n";
    report += "  \"broker_ticket\": "  + (string)broker_ticket + ",\n";
    report += "  \"fill_price\": "     + DoubleToString(fill_price, 5) + ",\n";
    report += "  \"slippage_pips\": "  + DoubleToString(slippage_pips, 1) + ",\n";
    report += "  \"error_message\": \"" + error_message + "\",\n";
    report += "  \"timestamp\": "      + ts              + "\n";
    report += "}\n";

    string fname = BridgeDir + "\\reports\\" + signal_id + "_" + ts + ".json";
    int fh = FileOpen(fname, FILE_WRITE | FILE_TXT | FILE_COMMON);
    if(fh == INVALID_HANDLE)
    {
        Print("ERROR: Cannot write report for ", signal_id, " err=", GetLastError());
        return;
    }
    FileWriteString(fh, report);
    FileClose(fh);
    Print("Report written: ", fname, " | event=", event, " | ticket=", broker_ticket);
}

//+------------------------------------------------------------------+
//| Archive (move) processed command file                              |
//+------------------------------------------------------------------+
void ArchiveCommand(const string src_path, const string filename)
{
    string dst = BridgeDir + "\\archive\\" + filename;
    // In MT5 FILE_COMMON scope, use FileCopy + FileDelete
    if(!FileCopy(src_path, FILE_COMMON, dst, FILE_COMMON))
        Print("WARN: FileCopy to archive failed for ", filename, " err=", GetLastError());
    FileDelete(src_path, FILE_COMMON);
}

//+------------------------------------------------------------------+
//| CORE: Process a single command JSON file                           |
//| Protocol (matches mt5_bridge.py ExecutionCommand):                |
//|   signal_id, symbol, direction, order_type, entry_price,          |
//|   stop_loss, take_profit, lot_size, magic_number, comment,        |
//|   expiry_seconds, timestamp                                        |
//|                                                                    |
//| NOTE: This EA does NOT validate trade direction or analyse the     |
//| market. It executes whatever the L12 Constitution decided.         |
//+------------------------------------------------------------------+
void ProcessCommandFile(const string filepath, const string filename)
{
    //--- 1. Read the file -------------------------------------------
    int fh = FileOpen(filepath, FILE_READ | FILE_TXT | FILE_COMMON);
    if(fh == INVALID_HANDLE)
    {
        Print("ERROR: Cannot open command file: ", filepath, " err=", GetLastError());
        return;
    }

    string json = "";
    while(!FileIsEnding(fh))
        json += FileReadString(fh);
    FileClose(fh);

    if(StringLen(json) < 10)
    {
        Print("WARN: Empty/corrupt command file: ", filepath);
        FileDelete(filepath, FILE_COMMON);
        return;
    }

    //--- 2. Parse fields from JSON ----------------------------------
    string signal_id     = JsonGetString(json, "signal_id",   "UNKNOWN");
    string symbol        = JsonGetString(json, "symbol",       _Symbol);
    string direction     = JsonGetString(json, "direction",    "");
    string order_type_s  = JsonGetString(json, "order_type",   "MARKET");
    double entry_price   = JsonGetDouble(json, "entry_price",  0.0);
    double stop_loss     = JsonGetDouble(json, "stop_loss",    0.0);
    double take_profit   = JsonGetDouble(json, "take_profit",  0.0);
    double lot_size      = JsonGetDouble(json, "lot_size",     0.0);
    long   magic         = JsonGetLong  (json, "magic_number", MagicNumber);
    string comment_str   = JsonGetString(json, "comment",      "TUYUL-FX");
    double expiry_sec    = JsonGetDouble(json, "expiry_seconds", 300.0);
    double cmd_timestamp = JsonGetDouble(json, "timestamp",    0.0);

    Print("CMD | signal=", signal_id, " sym=", symbol, " dir=", direction,
          " type=", order_type_s, " entry=", entry_price,
          " sl=", stop_loss, " tp=", take_profit, " lot=", lot_size);

    //--- 3. Validate required fields --------------------------------
    if(StringLen(signal_id) == 0 || StringLen(direction) == 0 || lot_size <= 0.0)
    {
        string err = "Invalid command fields (signal_id/direction/lot_size)";
        Print("ERROR: ", err, " — ", filepath);
        WriteReport(signal_id, "ORDER_FAILED", 0, 0.0, 0.0, err);
        ArchiveCommand(filepath, filename);
        return;
    }

    //--- 4. Expiry guard — reject stale commands --------------------
    if(cmd_timestamp > 0.0)
    {
        double age = (double)TimeTradeServer() - cmd_timestamp;
        if(age > expiry_sec)
        {
            string msg = "Command expired (age=" + DoubleToString(age, 0) + "s)";
            Print("WARN: ", msg, " signal=", signal_id);
            WriteReport(signal_id, "ORDER_EXPIRED", 0, 0.0, 0.0, msg);
            ArchiveCommand(filepath, filename);
            return;
        }
    }

    //--- 5. Resolve order type and trade action ---------------------
    ENUM_ORDER_TYPE  otype;
    ENUM_TRADE_REQUEST_ACTIONS action;

    if(order_type_s == "MARKET")
    {
        action = TRADE_ACTION_DEAL;
        otype  = (direction == "BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
        // Market orders: entry_price is ignored (use current Bid/Ask)
        entry_price = (direction == "BUY")
                      ? SymbolInfoDouble(symbol, SYMBOL_ASK)
                      : SymbolInfoDouble(symbol, SYMBOL_BID);
    }
    else if(order_type_s == "LIMIT")
    {
        action = TRADE_ACTION_PENDING;
        otype  = (direction == "BUY") ? ORDER_TYPE_BUY_LIMIT : ORDER_TYPE_SELL_LIMIT;
    }
    else if(order_type_s == "STOP")
    {
        action = TRADE_ACTION_PENDING;
        otype  = (direction == "BUY") ? ORDER_TYPE_BUY_STOP : ORDER_TYPE_SELL_STOP;
    }
    else
    {
        string err = "Unknown order_type: " + order_type_s;
        Print("ERROR: ", err);
        WriteReport(signal_id, "ORDER_FAILED", 0, 0.0, 0.0, err);
        ArchiveCommand(filepath, filename);
        return;
    }

    //--- 6. Normalize prices to symbol digits -----------------------
    int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
    entry_price = NormalizeDouble(entry_price, digits);
    stop_loss   = NormalizeDouble(stop_loss,   digits);
    take_profit = NormalizeDouble(take_profit, digits);

    //--- 7. Build and send the trade request ------------------------
    MqlTradeRequest req = {};
    MqlTradeResult  res = {};

    req.action       = action;
    req.magic        = magic;
    req.symbol       = symbol;
    req.volume       = lot_size;
    req.price        = entry_price;
    req.sl           = stop_loss;
    req.tp           = take_profit;
    req.type         = otype;
    req.type_filling = ORDER_FILLING_IOC;
    req.comment      = comment_str;
    req.deviation    = MaxSlippagePoints;

    // Pending order expiry
    if(action == TRADE_ACTION_PENDING && expiry_sec > 0.0)
    {
        req.type_time = ORDER_TIME_SPECIFIED;
        req.expiration = (datetime)(TimeTradeServer() + (long)expiry_sec);
    }
    else
    {
        req.type_time = ORDER_TIME_GTC;
    }

    bool sent = OrderSend(req, res);

    //--- 8. Evaluate result and write report ------------------------
    if(!sent || (res.retcode != TRADE_RETCODE_DONE && res.retcode != TRADE_RETCODE_PLACED))
    {
        string err_msg = "OrderSend failed: retcode=" + (string)res.retcode
                         + " | " + res.comment;
        Print("ERROR: ", err_msg, " | signal=", signal_id);
        WriteReport(signal_id, "ORDER_FAILED", (long)res.order, 0.0, 0.0, err_msg);
        ArchiveCommand(filepath, filename);
        return;
    }

    // Success
    string event_name;
    double fill_price    = 0.0;
    double slippage_pips = 0.0;

    if(action == TRADE_ACTION_DEAL)
    {
        event_name   = "ORDER_FILLED";
        fill_price   = res.price;
        double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
        double pip   = (digits == 3 || digits == 5) ? point * 10.0 : point;
        slippage_pips = (pip > 0.0) ? MathAbs(fill_price - entry_price) / pip : 0.0;
    }
    else
    {
        event_name = "ORDER_PLACED";
        fill_price = entry_price;
    }

    Print("SUCCESS: ", event_name, " | signal=", signal_id,
          " | ticket=", res.order, " | fill=", fill_price,
          " | slippage_pips=", DoubleToString(slippage_pips, 1));

    WriteReport(signal_id, event_name, (long)res.order, fill_price, slippage_pips, "");

    //--- 9. Archive the processed command file ----------------------
    ArchiveCommand(filepath, filename);
}

//+------------------------------------------------------------------+
//| Redis channel for real-time command push (EA subscribes if available)
EA_COMMAND_CHANNEL = "ea:commands"


class FileBasedMT5Bridge:
    """Dumb executor bridge — writes commands, reads reports. No strategy logic."""

    def __init__(self, bridge_dir: str = "C:\\TuyulFX\\bridge"):
        self._commands_dir = Path(bridge_dir) / "commands"
        self._reports_dir = Path(bridge_dir) / "reports"
        self._commands_dir.mkdir(parents=True, exist_ok=True)
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self._redis: Any | None = None

        # Try to connect Redis for real-time push (best-effort)
        try:
            from storage.redis_client import redis_client  # noqa: PLC0415
            self._redis = redis_client
            logger.info("EA bridge: Redis real-time channel available")
        except Exception:
            logger.info("EA bridge: Redis unavailable, file-only mode")

    def send_command(self, command: Any) -> bool:
        """Write execution command as JSON file for EA to pick up.

        Also publishes to Redis pub/sub for near-instant delivery
        if the EA supports WebSocket/Redis subscription.

        Authority: this method does NOT make trade decisions.
        It only relays prepared execution plans.
        """
        payload = asdict(command)
        filename = f"{command.signal_id}_{int(command.timestamp)}.json"
        filepath = self._commands_dir / filename

        # 1. Always write file (guaranteed delivery, EA polls this)
        try:
            filepath.write_text(json.dumps(payload, indent=2))
            logger.info("EA command written: %s", filename)
        except Exception as exc:
            logger.error("Failed to write EA command file: %s", exc)
            return False

        # 2. Best-effort Redis pub/sub push (near-instant if EA subscribes)
        if self._redis is not None:
            try:
                self._redis.publish(
                    EA_COMMAND_CHANNEL,
                    json.dumps({
                        "command": payload,
                        "file": filename,
                        "ts": time.time(),
                    }),
                )
                logger.debug("EA command pushed via Redis: %s", command.signal_id)
            except Exception as exc:
                logger.warning("Redis push failed (file fallback active): %s", exc)

        return True