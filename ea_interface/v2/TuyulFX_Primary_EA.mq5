//+------------------------------------------------------------------+
//| TuyulFX_Primary_EA.mq5 — PRIMARY class EA                        |
//| Full execution + reporting via HTTP Agent Manager API             |
//| Optionally maintains backwards-compat with legacy file bridge     |
//|                                                                   |
//| ZERO analysis. ZERO strategy. ZERO overrides.                     |
//| All trade decisions come from L12 Constitution / backend.         |
//| This EA only executes and reports.                                |
//+------------------------------------------------------------------+
#property copyright "TuyulFX"
#property version   "3.00"
#property strict

#include "Include/TuyulFX_Common.mqh"
#include "Include/TuyulFX_Json.mqh"
#include "Include/TuyulFX_Http.mqh"
#include "Include/TuyulFX_RiskGuard.mqh"
#include <Trade\Trade.mqh>

//+------------------------------------------------------------------+
//| Input parameters                                                  |
//+------------------------------------------------------------------+

// --- Agent Manager integration ---
input string AgentId              = "";                       // Agent Manager agent UUID (REQUIRED)
input string ApiBaseUrl           = "http://localhost:8000";  // Backend API URL
input string ApiKey               = "";                       // Bearer token for auth

// --- EA identity ---
input string EAClass              = EA_CLASS_PRIMARY;         // EA class (PRIMARY)
input string EASubtype            = EA_SUBTYPE_BROKER;        // EA subtype
input string ExecutionMode        = EXEC_MODE_LIVE;           // LIVE/DEMO/SHADOW

// --- Trade settings ---
input int    MagicNumber          = 151515;                   // Magic number for orders
input int    MaxSlippagePoints    = 20;                       // Max slippage (points)

// --- Timing ---
input int    HeartbeatIntervalSec = 30;                       // Heartbeat frequency
input int    ConfigPollIntervalSec = 60;                      // Config refresh frequency
input int    SnapshotIntervalSec  = 300;                      // Portfolio snapshot frequency

// --- Local risk guard (defense-in-depth) ---
input double MaxDailyDDPercent    = 4.0;                      // Max daily drawdown %
input double MaxTotalDDPercent    = 8.0;                      // Max total drawdown %
input int    MaxConcurrentTrades  = 3;                        // Max concurrent positions
input double MaxLotSize           = 1.0;                      // Max lot size per trade
input double MaxSpreadPips        = 3.0;                      // Max spread (pips)

// --- Legacy bridge backwards compatibility ---
input string BridgeDir            = "C:\\TuyulFX\\bridge";   // Legacy bridge directory
input bool   UseLegacyBridge      = false;                    // Poll legacy file commands
input bool   UseHttpBridge        = true;                     // Use HTTP-based protocol

//+------------------------------------------------------------------+
//| Globals                                                           |
//+------------------------------------------------------------------+
CTuyulHttpClient *g_http         = NULL;
CTuyulRiskGuard  *g_risk         = NULL;
CTrade            g_trade;

ENUM_EA_STATE g_state            = EA_STATE_INIT;
datetime      g_start_time       = 0;  // EA start time for uptime tracking
datetime      g_last_heartbeat   = 0;
datetime      g_last_config_poll = 0;
datetime      g_last_snapshot    = 0;
datetime      g_last_backend_ok  = 0;  // Last successful HTTP call
datetime      g_day_start        = 0;  // For new-day detection

int           g_exec_fail_streak = 0;  // Consecutive execution failures
bool          g_safe_mode        = false;
bool          g_locked           = false;

//+------------------------------------------------------------------+
//| Utility — collect floating P/L across all positions               |
//+------------------------------------------------------------------+
double CollectFloatingPnL()
{
    double total = 0.0;
    int n = PositionsTotal();
    for(int i = 0; i < n; i++)
    {
        ulong ticket = PositionGetTicket(i);
        if(ticket == 0) continue;
        if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
        total += PositionGetDouble(POSITION_PROFIT);
    }
    return total;
}

//+------------------------------------------------------------------+
//| Utility — check for new trading day and reset guard              |
//+------------------------------------------------------------------+
void CheckDayRollover()
{
    MqlDateTime now_dt, day_dt;
    TimeToStruct(TimeCurrent(), now_dt);
    TimeToStruct(g_day_start,   day_dt);
    if(now_dt.day != day_dt.day || now_dt.mon != day_dt.mon)
    {
        Print("[PRIMARY] New trading day detected — resetting daily counters");
        if(g_risk != NULL)
            g_risk.ResetDaily();
        g_day_start = TimeCurrent();
    }
}

//+------------------------------------------------------------------+
//| WriteReport — legacy file-based report (backwards compat)        |
//+------------------------------------------------------------------+
void WriteReport(const string signal_id, const string event,
                 const long broker_ticket, const double fill_price,
                 const double slippage_pips, const string error_message)
{
    if(!UseLegacyBridge) return;

    string ts     = DoubleToString((double)TimeTradeServer(), 0);
    string report = "{\n"
        + "  \"signal_id\": \""     + signal_id        + "\",\n"
        + "  \"event\": \""         + event             + "\",\n"
        + "  \"broker_ticket\": "   + (string)broker_ticket + ",\n"
        + "  \"fill_price\": "      + DoubleToString(fill_price, 5) + ",\n"
        + "  \"slippage_pips\": "   + DoubleToString(slippage_pips, 1) + ",\n"
        + "  \"error_message\": \"" + EscapeJsonString(error_message) + "\",\n"
        + "  \"timestamp\": "       + ts                + "\n"
        + "}\n";

    string fname = BridgeDir + "\\reports\\" + signal_id + "_" + ts + ".json";
    int fh = FileOpen(fname, FILE_WRITE | FILE_TXT | FILE_COMMON);
    if(fh == INVALID_HANDLE)
    {
        Print("[PRIMARY] ERROR: Cannot write legacy report err=", GetLastError());
        return;
    }
    FileWriteString(fh, report);
    FileClose(fh);
}

//+------------------------------------------------------------------+
//| ArchiveCommand — legacy file archive helper                       |
//+------------------------------------------------------------------+
void ArchiveCommand(const string src_path, const string filename)
{
    string dst = BridgeDir + "\\archive\\" + filename;
    if(!FileCopy(src_path, FILE_COMMON, dst, FILE_COMMON))
        Print("[PRIMARY] WARN: FileCopy to archive failed for ", filename,
              " err=", GetLastError());
    FileDelete(src_path, FILE_COMMON);
}

//+------------------------------------------------------------------+
//| ProcessCommand — execute a trade command (HTTP or file protocol) |
//+------------------------------------------------------------------+
void ProcessCommand(const string signal_id, const string symbol,
                    const string direction, const string order_type_s,
                    double entry_price, double stop_loss, double take_profit,
                    double lot_size, long magic, const string comment_str,
                    double expiry_sec)
{
    //--- 1. Safe/locked guard ----------------------------------------
    if(g_safe_mode || g_locked)
    {
        Print(StringFormat("[PRIMARY] BLOCKED — safe_mode=%d locked=%d | signal=%s",
                           (int)g_safe_mode, (int)g_locked, signal_id));
        g_http.SendEvent("EXECUTION_BLOCKED", "WARNING",
                         "EA in safe/locked mode — signal rejected: " + signal_id);
        return;
    }

    //--- 2. Local risk pre-flight check ------------------------------
    if(!g_risk.PreFlightCheck(symbol, lot_size, 0.0, MaxSpreadPips))
    {
        string reason = g_risk.GetLastBlockReason();
        Print(StringFormat("[PRIMARY] RISK_GUARD_BLOCK | signal=%s reason=%s",
                           signal_id, reason));
        g_http.SendEvent("RISK_GUARD_BLOCK", "WARNING", reason);
        WriteReport(signal_id, "ORDER_FAILED", 0, 0.0, 0.0,
                    "LOCAL_RISK_BLOCK: " + reason);

        // Auto-quarantine if daily DD breached
        if(g_risk.IsDailyDDBreached())
        {
            g_http.SendStatusChange(STATUS_QUARANTINED,
                                    "Daily drawdown limit breached");
            g_safe_mode = true;
        }
        return;
    }

    //--- 3. Shadow mode — log only, no execution --------------------
    if(ExecutionMode == EXEC_MODE_SHADOW)
    {
        Print(StringFormat("[PRIMARY] SHADOW_SIGNAL | signal=%s sym=%s dir=%s lot=%.2f",
                           signal_id, symbol, direction, lot_size));
        g_http.SendEvent("SHADOW_SIGNAL", "INFO",
                         StringFormat("Shadow: %s %s %s lot=%.2f",
                                      signal_id, symbol, direction, lot_size));
        return;
    }

    //--- 4. Resolve order type and action ----------------------------
    ENUM_ORDER_TYPE              otype;
    ENUM_TRADE_REQUEST_ACTIONS   action;

    if(order_type_s == "MARKET")
    {
        action = TRADE_ACTION_DEAL;
        otype  = (direction == "BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
        entry_price = (direction == "BUY")
                      ? SymbolInfoDouble(symbol, SYMBOL_ASK)
                      : SymbolInfoDouble(symbol, SYMBOL_BID);
    }
    else if(order_type_s == "LIMIT")
    {
        action = TRADE_ACTION_PENDING;
        otype  = (direction == "BUY") ? ORDER_TYPE_BUY_LIMIT
                                      : ORDER_TYPE_SELL_LIMIT;
    }
    else if(order_type_s == "STOP")
    {
        action = TRADE_ACTION_PENDING;
        otype  = (direction == "BUY") ? ORDER_TYPE_BUY_STOP
                                      : ORDER_TYPE_SELL_STOP;
    }
    else
    {
        string err = "Unknown order_type: " + order_type_s;
        Print("[PRIMARY] ERROR: ", err);
        g_http.SendEvent("ORDER_FAILED", "ERROR", err);
        WriteReport(signal_id, "ORDER_FAILED", 0, 0.0, 0.0, err);
        return;
    }

    //--- 5. Normalise prices ----------------------------------------
    int digits      = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
    entry_price     = NormalizeDouble(entry_price, digits);
    stop_loss       = NormalizeDouble(stop_loss,   digits);
    take_profit     = NormalizeDouble(take_profit, digits);

    //--- 6. Build and send trade request ----------------------------
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

    if(action == TRADE_ACTION_PENDING && expiry_sec > 0.0)
    {
        req.type_time  = ORDER_TIME_SPECIFIED;
        req.expiration = (datetime)(TimeTradeServer() + (long)expiry_sec);
    }
    else
    {
        req.type_time = ORDER_TIME_GTC;
    }

    bool sent = OrderSend(req, res);

    //--- 7. Evaluate and report results -----------------------------
    if(!sent || (res.retcode != TRADE_RETCODE_DONE &&
                 res.retcode != TRADE_RETCODE_PLACED))
    {
        string err_msg = StringFormat("OrderSend failed: retcode=%d | %s",
                                      (int)res.retcode, res.comment);
        Print("[PRIMARY] ERROR: ", err_msg, " | signal=", signal_id);
        g_exec_fail_streak++;
        g_http.SendEvent("ORDER_FAILED", "ERROR",
                         signal_id + ": " + err_msg);
        WriteReport(signal_id, "ORDER_FAILED", (long)res.order,
                    0.0, 0.0, err_msg);

        // 3 consecutive failures → send WARNING
        if(g_exec_fail_streak >= 3)
        {
            g_http.SendStatusChange(STATUS_WARNING,
                StringFormat("3 consecutive execution failures (last: %s)",
                             err_msg));
        }
        return;
    }

    // Success
    g_exec_fail_streak = 0;
    g_last_backend_ok  = TimeCurrent();

    string event_name;
    double fill_price    = 0.0;
    double slippage_pips = 0.0;

    if(action == TRADE_ACTION_DEAL)
    {
        event_name    = "ORDER_FILLED";
        fill_price    = res.price;
        slippage_pips = PipCalcFromSlippage(symbol, fill_price, entry_price);
    }
    else
    {
        event_name = "ORDER_PLACED";
        fill_price = entry_price;
    }

    Print(StringFormat("[PRIMARY] %s | signal=%s ticket=%d fill=%.5f slip=%.1f",
                       event_name, signal_id, (int)res.order,
                       fill_price, slippage_pips));

    g_http.SendEvent(event_name, "INFO",
                     StringFormat("%s sym=%s dir=%s lot=%.2f ticket=%d",
                                  signal_id, symbol, direction,
                                  lot_size, (int)res.order));
    WriteReport(signal_id, event_name, (long)res.order,
                fill_price, slippage_pips, "");
}

//+------------------------------------------------------------------+
//| PollLegacyBridgeFiles — legacy file-based command polling        |
//+------------------------------------------------------------------+
void PollLegacyBridgeFiles()
{
    if(!UseLegacyBridge) return;

    string filename;
    string pattern = BridgeDir + "\\commands\\*.json";
    long   search  = FileFindFirst(pattern, filename, FILE_COMMON);

    if(search == INVALID_HANDLE) return;

    do
    {
        string full_path = BridgeDir + "\\commands\\" + filename;

        int fh = FileOpen(full_path, FILE_READ | FILE_TXT | FILE_COMMON);
        if(fh == INVALID_HANDLE) continue;

        string json = "";
        while(!FileIsEnding(fh))
            json += FileReadString(fh);
        FileClose(fh);

        if(StringLen(json) < 10)
        {
            FileDelete(full_path, FILE_COMMON);
            continue;
        }

        string signal_id    = JsonGetString(json, "signal_id",    "UNKNOWN");
        string symbol       = JsonGetString(json, "symbol",        _Symbol);
        string direction    = JsonGetString(json, "direction",     "");
        string order_type_s = JsonGetString(json, "order_type",    "MARKET");
        double entry_price  = JsonGetDouble(json, "entry_price",   0.0);
        double stop_loss    = JsonGetDouble(json, "stop_loss",     0.0);
        double take_profit  = JsonGetDouble(json, "take_profit",   0.0);
        double lot_size     = JsonGetDouble(json, "lot_size",      0.0);
        long   magic        = JsonGetLong  (json, "magic_number",  MagicNumber);
        string comment_str  = JsonGetString(json, "comment",       "TUYUL-FX");
        double expiry_sec   = JsonGetDouble(json, "expiry_seconds",300.0);
        double cmd_ts       = JsonGetDouble(json, "timestamp",     0.0);

        // Expiry check
        if(cmd_ts > 0.0)
        {
            double age = (double)TimeTradeServer() - cmd_ts;
            if(age > expiry_sec)
            {
                string msg = StringFormat("Command expired (age=%.0fs)", age);
                Print("[PRIMARY] WARN: ", msg, " signal=", signal_id);
                WriteReport(signal_id, "ORDER_EXPIRED", 0, 0.0, 0.0, msg);
                ArchiveCommand(full_path, filename);
                continue;
            }
        }

        if(StringLen(direction) > 0 && lot_size > 0.0)
            ProcessCommand(signal_id, symbol, direction, order_type_s,
                           entry_price, stop_loss, take_profit, lot_size,
                           magic, comment_str, expiry_sec);
        else
            Print("[PRIMARY] WARN: Invalid legacy command fields, signal=", signal_id);

        ArchiveCommand(full_path, filename);
    }
    while(FileFindNext(search, filename));

    FileFindClose(search);
}

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit()
{
    Print("===========================================================");
    Print("[PRIMARY] TuyulFX Primary EA v", TUYULFX_VERSION, " initializing...");
    Print(StringFormat("[PRIMARY] AgentId=%s ApiBaseUrl=%s", AgentId, ApiBaseUrl));
    Print(StringFormat("[PRIMARY] EAClass=%s EASubtype=%s ExecMode=%s",
                       EAClass, EASubtype, ExecutionMode));
    Print(StringFormat("[PRIMARY] Magic=%d MaxSlippage=%d HeartbeatSec=%d",
                       MagicNumber, MaxSlippagePoints, HeartbeatIntervalSec));
    Print(StringFormat("[PRIMARY] UseLegacyBridge=%d UseHttpBridge=%d",
                       (int)UseLegacyBridge, (int)UseHttpBridge));

    //--- Validate required inputs ---
    if(StringLen(AgentId) == 0)
    {
        Print("[PRIMARY] FATAL: AgentId is empty — cannot connect to Agent Manager");
        return(INIT_FAILED);
    }
    if(StringLen(ApiBaseUrl) == 0)
    {
        Print("[PRIMARY] FATAL: ApiBaseUrl is empty");
        return(INIT_FAILED);
    }

    //--- Initialise objects ---
    g_http = new CTuyulHttpClient(ApiBaseUrl, ApiKey, AgentId);
    g_risk = new CTuyulRiskGuard(MaxDailyDDPercent, MaxTotalDDPercent,
                                  MaxConcurrentTrades, MaxLotSize, MagicNumber);

    //--- Configure CTrade ---
    g_trade.SetExpertMagicNumber(MagicNumber);
    g_trade.SetDeviationInPoints(MaxSlippagePoints);
    g_trade.SetTypeFilling(ORDER_FILLING_IOC);
    g_trade.LogLevel(LOG_LEVEL_ERRORS);

    //--- Initialise state trackers ---
    g_start_time      = TimeCurrent();
    g_day_start       = TimeCurrent();
    g_last_backend_ok = TimeCurrent();
    g_state           = EA_STATE_RUNNING;

    //--- Initial heartbeat and config fetch ---
    if(UseHttpBridge)
    {
        if(!g_http.SendHeartbeat(0, 0.0))
            Print("[PRIMARY] WARN: Initial heartbeat failed — will retry on timer");
        else
            g_last_backend_ok = TimeCurrent();

        if(!g_http.FetchAgentConfig())
            Print("[PRIMARY] WARN: Initial config fetch failed — using defaults");
        else
        {
            g_safe_mode = g_http.IsSafeMode();
            g_locked    = g_http.IsLocked();
            g_last_backend_ok = TimeCurrent();
        }

        if(g_locked)
        {
            Print("[PRIMARY] WARN: Agent is LOCKED — entering safe mode");
            g_safe_mode = true;
            g_state     = EA_STATE_LOCKED;
        }

        g_http.SendStatusChange(STATUS_ONLINE, "EA initialized successfully");
    }

    //--- Start timer — fire every second, handle intervals internally ---
    EventSetTimer(1);

    g_last_heartbeat   = TimeCurrent();
    g_last_config_poll = TimeCurrent();
    g_last_snapshot    = TimeCurrent();

    Print(StringFormat("[PRIMARY] Init complete. safe_mode=%d locked=%d state=%d",
                       (int)g_safe_mode, (int)g_locked, (int)g_state));
    Print("===========================================================");
    return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    Print(StringFormat("[PRIMARY] Deinitializing. Reason=%d", reason));

    if(g_http != NULL && UseHttpBridge)
    {
        // Send final portfolio snapshot
        double bal = AccountInfoDouble(ACCOUNT_BALANCE);
        double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
        double mu  = AccountInfoDouble(ACCOUNT_MARGIN);
        double mf  = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
        int    op  = PositionsTotal();
        double fp  = CollectFloatingPnL();
        g_http.SendPortfolioSnapshot(bal, eq, mu, mf, op, eq - bal, fp);

        g_http.SendStatusChange(STATUS_OFFLINE,
                                StringFormat("EA deinitialized (reason=%d)", reason));
    }

    EventKillTimer();

    if(g_http != NULL) { delete g_http; g_http = NULL; }
    if(g_risk != NULL) { delete g_risk; g_risk = NULL; }

    Print("[PRIMARY] Shutdown complete.");
}

//+------------------------------------------------------------------+
//| OnTimer — primary event loop                                      |
//+------------------------------------------------------------------+
void OnTimer()
{
    datetime now = TimeCurrent();

    // Check for new day
    CheckDayRollover();

    // Auto safe-mode if backend unreachable for 5 minutes
    if(UseHttpBridge && !g_safe_mode && !g_locked)
    {
        if((now - g_last_backend_ok) >= 300)
        {
            Print("[PRIMARY] WARN: Backend unreachable for 5 minutes — entering safe mode");
            g_safe_mode = true;
            g_state     = EA_STATE_SAFE_MODE;
            g_http.SendEvent("AUTO_SAFE_MODE", "WARNING",
                             "Backend unreachable >5 min — safe mode activated");
        }
    }

    // Heartbeat
    if(UseHttpBridge && (now - g_last_heartbeat) >= HeartbeatIntervalSec)
    {
        int uptime = (int)(now - g_start_time);
        if(g_http.SendHeartbeat(uptime, 0.0))
            g_last_backend_ok = now;
        g_last_heartbeat = now;
    }

    // Config poll
    if(UseHttpBridge && (now - g_last_config_poll) >= ConfigPollIntervalSec)
    {
        if(g_http.FetchAgentConfig())
        {
            bool new_safe = g_http.IsSafeMode();
            bool new_lock = g_http.IsLocked();
            if(new_safe != g_safe_mode)
            {
                Print(StringFormat("[PRIMARY] safe_mode changed: %d → %d",
                                   (int)g_safe_mode, (int)new_safe));
                g_safe_mode = new_safe;
            }
            if(new_lock != g_locked)
            {
                Print(StringFormat("[PRIMARY] locked changed: %d → %d",
                                   (int)g_locked, (int)new_lock));
                g_locked = new_lock;
            }
            // If unlocked and no local issues, restore running state
            if(!g_locked && !g_safe_mode && g_state != EA_STATE_ERROR)
                g_state = EA_STATE_RUNNING;
            g_last_backend_ok = now;
        }
        g_last_config_poll = now;
    }

    // Portfolio snapshot
    if(UseHttpBridge && (now - g_last_snapshot) >= SnapshotIntervalSec)
    {
        double bal = AccountInfoDouble(ACCOUNT_BALANCE);
        double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
        double mu  = AccountInfoDouble(ACCOUNT_MARGIN);
        double mf  = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
        int    op  = PositionsTotal();
        double fp  = CollectFloatingPnL();
        if(g_http.SendPortfolioSnapshot(bal, eq, mu, mf, op, eq - bal, fp))
            g_last_backend_ok = now;
        g_last_snapshot = now;
    }

    // Poll legacy bridge files
    if(UseLegacyBridge)
        PollLegacyBridgeFiles();
}

//+------------------------------------------------------------------+
//| OnTick — minimal; most logic lives in OnTimer                    |
//+------------------------------------------------------------------+
void OnTick()
{
    // Gate — no execution in safe or locked state
    if(g_safe_mode || g_locked || g_state == EA_STATE_ERROR)
        return;

    // Update equity high-water mark on every tick for accurate DD tracking
    if(g_risk != NULL)
        g_risk.UpdateEquityHigh(AccountInfoDouble(ACCOUNT_EQUITY));
}
