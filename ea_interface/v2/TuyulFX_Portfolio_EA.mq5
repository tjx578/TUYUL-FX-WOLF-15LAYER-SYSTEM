//+------------------------------------------------------------------+
//| TuyulFX_Portfolio_EA.mq5 — PORTFOLIO class EA                    |
//| Reporter-only. No execution. No file bridge. No risk guard.       |
//| Monitors account state and sends portfolio snapshots periodically.|
//|                                                                   |
//| Zone : ea_interface/v2/ — reporter only, no execution authority   |
//+------------------------------------------------------------------+
#property copyright "TuyulFX"
#property version   "3.00"
#property strict

#include "Include/TuyulFX_Common.mqh"
#include "Include/TuyulFX_Json.mqh"
#include "Include/TuyulFX_Http.mqh"

//+------------------------------------------------------------------+
//| Input parameters                                                  |
//+------------------------------------------------------------------+

// --- Agent Manager integration ---
input string AgentId               = "";                       // Agent Manager agent UUID (REQUIRED)
input string ApiBaseUrl            = "http://localhost:8000";  // Backend API URL
input string ApiKey                = "";                       // Bearer token for auth

// --- EA identity ---
input string EASubtype             = EA_SUBTYPE_STANDARD_REPORTER; // STANDARD_REPORTER or BALANCE_ONLY
input string ReporterMode          = REPORTER_FULL;                 // FULL / BALANCE_ONLY / DISABLED

// --- Timing ---
input int    HeartbeatIntervalSec  = 60;   // Heartbeat frequency (seconds)
input int    SnapshotIntervalSec   = 60;   // Snapshot frequency (more frequent than Primary)
input int    ConfigPollIntervalSec = 120;  // Config refresh frequency

//+------------------------------------------------------------------+
//| Globals                                                           |
//+------------------------------------------------------------------+
CTuyulHttpClient *g_http          = NULL;

ENUM_EA_STATE g_state             = EA_STATE_INIT;
datetime      g_start_time        = 0;  // EA start time for uptime tracking
datetime      g_last_heartbeat    = 0;
datetime      g_last_config_poll  = 0;
datetime      g_last_snapshot     = 0;
datetime      g_last_backend_ok   = 0;
datetime      g_day_start_time    = 0;  // For daily P/L tracking
double        g_day_start_balance = 0.0;// Balance at start of trading day

bool          g_disabled          = false;  // Set if backend says DISABLED
bool          g_locked            = false;

//+------------------------------------------------------------------+
//| CollectFloatingPnL — sum all open position profits               |
//+------------------------------------------------------------------+
double CollectFloatingPnL()
{
    double total = 0.0;
    int n = PositionsTotal();
    for(int i = 0; i < n; i++)
    {
        ulong ticket = PositionGetTicket(i);
        if(ticket == 0) continue;
        total += PositionGetDouble(POSITION_PROFIT);
    }
    return total;
}

//+------------------------------------------------------------------+
//| SendSnapshot — collect account data and send to backend          |
//+------------------------------------------------------------------+
void SendSnapshot()
{
    if(g_disabled || g_http == NULL) return;

    double bal = AccountInfoDouble(ACCOUNT_BALANCE);
    double eq  = AccountInfoDouble(ACCOUNT_EQUITY);

    if(ReporterMode == REPORTER_BALANCE_ONLY)
    {
        // Minimal snapshot: balance and equity only (zero the rest)
        g_http.SendPortfolioSnapshot(bal, eq, 0.0, 0.0, 0, 0.0, 0.0);
        return;
    }

    // FULL snapshot
    double mu  = AccountInfoDouble(ACCOUNT_MARGIN);
    double mf  = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
    int    op  = PositionsTotal();
    double fp  = CollectFloatingPnL();
    // Daily P/L = current equity - day-start balance (includes floating)
    double dnl = eq - g_day_start_balance;

    g_http.SendPortfolioSnapshot(bal, eq, mu, mf, op, dnl, fp);
}

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit()
{
    Print("===========================================================");
    Print("[PORTFOLIO] TuyulFX Portfolio EA v", TUYULFX_VERSION, " initializing...");
    Print(StringFormat("[PORTFOLIO] AgentId=%s ApiBaseUrl=%s", AgentId, ApiBaseUrl));
    Print(StringFormat("[PORTFOLIO] EASubtype=%s ReporterMode=%s",
                       EASubtype, ReporterMode));
    Print(StringFormat("[PORTFOLIO] HeartbeatSec=%d SnapshotSec=%d ConfigPollSec=%d",
                       HeartbeatIntervalSec, SnapshotIntervalSec, ConfigPollIntervalSec));

    //--- Validate required inputs ---
    if(StringLen(AgentId) == 0)
    {
        Print("[PORTFOLIO] FATAL: AgentId is empty — cannot connect to Agent Manager");
        return(INIT_FAILED);
    }
    if(StringLen(ApiBaseUrl) == 0)
    {
        Print("[PORTFOLIO] FATAL: ApiBaseUrl is empty");
        return(INIT_FAILED);
    }

    //--- Validate reporter mode ---
    if(ReporterMode != REPORTER_FULL &&
       ReporterMode != REPORTER_BALANCE_ONLY &&
       ReporterMode != REPORTER_DISABLED)
    {
        Print("[PORTFOLIO] WARN: Unknown ReporterMode '", ReporterMode,
              "' — defaulting to FULL");
    }

    if(ReporterMode == REPORTER_DISABLED)
    {
        Print("[PORTFOLIO] INFO: ReporterMode=DISABLED — EA will not send snapshots");
        g_disabled = true;
    }

    //--- Initialise HTTP client ---
    g_http = new CTuyulHttpClient(ApiBaseUrl, ApiKey, AgentId);

    //--- Initial heartbeat ---
    if(!g_http.SendHeartbeat(0, 0.0))
        Print("[PORTFOLIO] WARN: Initial heartbeat failed — will retry on timer");
    else
        g_last_backend_ok = TimeCurrent();

    //--- Fetch initial config ---
    if(!g_http.FetchAgentConfig())
        Print("[PORTFOLIO] WARN: Initial config fetch failed — using defaults");
    else
    {
        g_locked = g_http.IsLocked();
        g_last_backend_ok = TimeCurrent();
    }

    //--- Send ONLINE status ---
    g_http.SendStatusChange(STATUS_ONLINE, "Portfolio EA initialized");

    //--- Start timer ---
    EventSetTimer(1);

    g_start_time        = TimeCurrent();
    g_day_start_time    = TimeCurrent();
    g_day_start_balance = AccountInfoDouble(ACCOUNT_BALANCE);
    g_last_heartbeat    = TimeCurrent();
    g_last_config_poll  = TimeCurrent();
    g_last_snapshot     = TimeCurrent();
    g_state             = EA_STATE_RUNNING;

    Print(StringFormat("[PORTFOLIO] Init complete. disabled=%d locked=%d",
                       (int)g_disabled, (int)g_locked));
    Print("===========================================================");
    return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    Print(StringFormat("[PORTFOLIO] Deinitializing. Reason=%d", reason));

    if(g_http != NULL)
    {
        // Final snapshot before going offline
        SendSnapshot();
        g_http.SendStatusChange(STATUS_OFFLINE,
                                StringFormat("Portfolio EA deinitialized (reason=%d)",
                                             reason));
    }

    EventKillTimer();

    if(g_http != NULL) { delete g_http; g_http = NULL; }

    Print("[PORTFOLIO] Shutdown complete.");
}

//+------------------------------------------------------------------+
//| OnTimer — main event loop                                         |
//+------------------------------------------------------------------+
void OnTimer()
{
    datetime now = TimeCurrent();

    // New day rollover — reset day-start balance
    MqlDateTime now_dt, day_dt;
    TimeToStruct(now,             now_dt);
    TimeToStruct(g_day_start_time, day_dt);
    if(now_dt.day != day_dt.day || now_dt.mon != day_dt.mon)
    {
        g_day_start_balance = AccountInfoDouble(ACCOUNT_BALANCE);
        g_day_start_time    = now;
        Print("[PORTFOLIO] New trading day — day_start_balance reset to ",
              DoubleToString(g_day_start_balance, 2));
    }

    // Heartbeat
    if((now - g_last_heartbeat) >= HeartbeatIntervalSec)
    {
        int uptime = (int)(now - g_start_time);
        if(g_http.SendHeartbeat(uptime, 0.0))
            g_last_backend_ok = now;
        g_last_heartbeat = now;
    }

    // Config poll
    if((now - g_last_config_poll) >= ConfigPollIntervalSec)
    {
        if(g_http.FetchAgentConfig())
        {
            bool new_lock = g_http.IsLocked();
            if(new_lock != g_locked)
            {
                Print(StringFormat("[PORTFOLIO] locked changed: %d → %d",
                                   (int)g_locked, (int)new_lock));
                g_locked = new_lock;
            }

            // Check if reporter has been disabled via backend
            // (no dedicated flag — we honour safe_mode as disabled signal)
            bool new_safe = g_http.IsSafeMode();
            if(new_safe && !g_disabled)
            {
                Print("[PORTFOLIO] INFO: safe_mode set by backend — pausing snapshots");
                g_disabled = true;
            }
            else if(!new_safe && g_disabled &&
                    ReporterMode != REPORTER_DISABLED)
            {
                Print("[PORTFOLIO] INFO: safe_mode cleared — resuming snapshots");
                g_disabled = false;
            }
            g_last_backend_ok = now;
        }
        g_last_config_poll = now;
    }

    // Portfolio snapshot
    if(!g_disabled && (now - g_last_snapshot) >= SnapshotIntervalSec)
    {
        SendSnapshot();
        g_last_snapshot = now;
        g_last_backend_ok = now;
    }
}

//+------------------------------------------------------------------+
//| OnTick — this EA does not trade; tick handler is intentionally   |
//| minimal.                                                          |
//+------------------------------------------------------------------+
void OnTick()
{
    // Nothing — Portfolio EA does not execute trades.
}
