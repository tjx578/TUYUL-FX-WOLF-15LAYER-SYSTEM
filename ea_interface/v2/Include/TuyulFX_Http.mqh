//+------------------------------------------------------------------+
//| TuyulFX_Http.mqh — HTTP client wrapper for Agent Manager API     |
//| Uses MQL5 WebRequest() for all HTTP calls                         |
//| Endpoints: /api/v1/agent-ingest/* and /api/v1/agent-manager/*    |
//| Zone : ea_interface/v2/ — transport only, no decision authority   |
//+------------------------------------------------------------------+
#property copyright "TuyulFX"
#property strict

#ifndef TUYULFX_HTTP_MQH
#define TUYULFX_HTTP_MQH

#include "TuyulFX_Common.mqh"
#include "TuyulFX_Json.mqh"

//+------------------------------------------------------------------+
//| CTuyulHttpClient — HTTP client for the Agent Manager backend     |
//+------------------------------------------------------------------+
class CTuyulHttpClient
{
private:
    string   m_base_url;          // e.g. "http://localhost:8000"
    string   m_api_key;           // Bearer token
    string   m_agent_id;          // UUID string
    string   m_account_id;        // MT5 account number as string
    datetime m_start_time;        // Used to compute uptime_seconds
    ulong    m_last_request_ms;   // Rate-limit gate (milliseconds from GetTickCount64)
    int      m_consecutive_fails; // Network failure counter

    // Cached config fields (refreshed by FetchAgentConfig)
    bool     m_safe_mode;
    bool     m_locked;
    string   m_strategy_profile;
    double   m_risk_multiplier;
    string   m_news_lock_setting;

    //+--------------------------------------------------------------+
    //| BuildJsonPayload — generic key/value JSON builder            |
    //+--------------------------------------------------------------+
    string BuildJsonPayload(string &keys[], string &values[],
                            bool &isStr[], int count)
    {
        return JsonBuildObject(keys, values, isStr, count);
    }

    //+--------------------------------------------------------------+
    //| RateLimit — enforce minimum 500 ms between requests          |
    //+--------------------------------------------------------------+
    void RateLimit()
    {
        ulong now_ms = GetTickCount64();
        if(m_last_request_ms > 0 && (now_ms - m_last_request_ms) < 500)
            Sleep((int)(500 - (now_ms - m_last_request_ms)));
        m_last_request_ms = GetTickCount64();
    }

    //+--------------------------------------------------------------+
    //| DoRequest — single HTTP call with retry logic                |
    //| Returns HTTP status code, fills responseBody on success       |
    //+--------------------------------------------------------------+
    int DoRequest(const string method, const string endpoint,
                  const string body, string &responseBody,
                  int timeout_ms = 5000)
    {
        RateLimit();

        string url = m_base_url + endpoint;

        // Build headers
        string headers = "Content-Type: application/json\r\n"
                       + "Authorization: Bearer " + m_api_key + "\r\n"
                       + "X-Agent-Id: " + m_agent_id + "\r\n"
                       + "X-EA-Version: " + TUYULFX_VERSION + "\r\n";

        char   post_data[];
        char   result_data[];
        string result_headers;
        int    http_code = 0;

        if(StringLen(body) > 0)
            StringToCharArray(body, post_data, 0, StringLen(body));

        // Retry up to 3 times on network errors (not on 4xx)
        int delays[] = {0, 1000, 2000};
        for(int attempt = 0; attempt < 3; attempt++)
        {
            if(attempt > 0)
            {
                Print(StringFormat("[HTTP] Retry %d/2 for %s %s", attempt, method, endpoint));
                Sleep(delays[attempt]);
            }

            ArrayFree(result_data);
            http_code = WebRequest(method, url, headers, timeout_ms,
                                   post_data, result_data, result_headers);

            if(http_code < 0)
            {
                int err = GetLastError();
                Print(StringFormat("[HTTP] Network error %d on attempt %d: %s %s",
                                   err, attempt + 1, method, endpoint));
                m_consecutive_fails++;
                continue; // retry
            }

            // Got a response (even 4xx/5xx) — stop retrying
            break;
        }

        if(http_code < 0)
        {
            Print(StringFormat("[HTTP] All retries failed for %s %s", method, endpoint));
            return http_code;
        }

        responseBody = CharArrayToString(result_data, 0, ArraySize(result_data), CP_UTF8);
        m_consecutive_fails = 0;
        return http_code;
    }

    //+--------------------------------------------------------------+
    //| ParseConfigResponse — extract config fields from GET /agents |
    //+--------------------------------------------------------------+
    bool ParseConfigResponse(const string &json)
    {
        m_safe_mode         = JsonGetBool  (json, "safe_mode",         false);
        m_locked            = JsonGetBool  (json, "locked",            false);
        m_strategy_profile  = JsonGetString(json, "strategy_profile",  "default");
        m_risk_multiplier   = JsonGetDouble(json, "risk_multiplier",   1.0);
        m_news_lock_setting = JsonGetString(json, "news_lock_setting", "DEFAULT");
        return true;
    }

public:
    //+--------------------------------------------------------------+
    //| Constructor                                                   |
    //+--------------------------------------------------------------+
    CTuyulHttpClient(const string baseUrl, const string apiKey,
                     const string agentId)
    {
        m_base_url           = baseUrl;
        m_api_key            = apiKey;
        m_agent_id           = agentId;
        m_account_id         = (string)AccountInfoInteger(ACCOUNT_LOGIN);
        m_start_time         = TimeCurrent();
        m_last_request_ms    = 0;
        m_consecutive_fails  = 0;
        m_safe_mode          = false;
        m_locked             = false;
        m_strategy_profile   = "default";
        m_risk_multiplier    = 1.0;
        m_news_lock_setting  = "DEFAULT";
    }

    //+--------------------------------------------------------------+
    //| Accessors for cached config                                   |
    //+--------------------------------------------------------------+
    bool   IsSafeMode()         const { return m_safe_mode; }
    bool   IsLocked()           const { return m_locked; }
    string GetStrategyProfile() const { return m_strategy_profile; }
    double GetRiskMultiplier()  const { return m_risk_multiplier; }
    string GetNewsLockSetting() const { return m_news_lock_setting; }
    int    GetConsecutiveFails()const { return m_consecutive_fails; }

    //+--------------------------------------------------------------+
    //| SendHeartbeat — POST /api/v1/agent-ingest/heartbeat          |
    //+--------------------------------------------------------------+
    bool SendHeartbeat(int uptime_sec = 0, double latency_ms = 0.0)
    {
        if(uptime_sec <= 0)
            uptime_sec = (int)(TimeCurrent() - m_start_time);

        // Build ISO-8601 timestamp
        string ts = TuyulTimestamp();

        // Build body
        string body = StringFormat(
            "{\"agent_id\":\"%s\","
            "\"timestamp\":\"%s\","
            "\"uptime_seconds\":%d,"
            "\"cpu_usage_pct\":null,"
            "\"memory_mb\":null,"
            "\"connection_latency_ms\":%.1f}",
            m_agent_id, ts, uptime_sec, latency_ms
        );

        string response;
        int code = DoRequest("POST", "/api/v1/agent-ingest/heartbeat",
                             body, response, 5000);
        if(code < 200 || code > 299)
        {
            Print(StringFormat("[HTTP] Heartbeat failed — code=%d resp=%s", code, response));
            return false;
        }
        return true;
    }

    //+--------------------------------------------------------------+
    //| SendStatusChange — POST /api/v1/agent-ingest/status-change   |
    //+--------------------------------------------------------------+
    bool SendStatusChange(const string newStatus, const string reason = "")
    {
        string safe_reason = EscapeJsonString(reason);
        string body = StringFormat(
            "{\"agent_id\":\"%s\","
            "\"new_status\":\"%s\","
            "\"reason\":\"%s\"}",
            m_agent_id, newStatus, safe_reason
        );

        string response;
        int code = DoRequest("POST", "/api/v1/agent-ingest/status-change",
                             body, response, 5000);
        if(code < 200 || code > 299)
        {
            Print(StringFormat("[HTTP] StatusChange failed — status=%s code=%d",
                               newStatus, code));
            return false;
        }
        Print(StringFormat("[HTTP] Status changed to %s", newStatus));
        return true;
    }

    //+--------------------------------------------------------------+
    //| SendPortfolioSnapshot                                         |
    //| POST /api/v1/agent-ingest/portfolio-snapshot                  |
    //+--------------------------------------------------------------+
    bool SendPortfolioSnapshot(double balance, double equity,
                               double marginUsed, double marginFree,
                               int openPositions, double dailyPnl,
                               double floatingPnl)
    {
        string body = StringFormat(
            "{\"agent_id\":\"%s\","
            "\"account_id\":\"%s\","
            "\"balance\":%.2f,"
            "\"equity\":%.2f,"
            "\"margin_used\":%.2f,"
            "\"margin_free\":%.2f,"
            "\"open_positions\":%d,"
            "\"daily_pnl\":%.2f,"
            "\"floating_pnl\":%.2f}",
            m_agent_id, EscapeJsonString(m_account_id),
            balance, equity, marginUsed, marginFree,
            openPositions, dailyPnl, floatingPnl
        );

        string response;
        int code = DoRequest("POST", "/api/v1/agent-ingest/portfolio-snapshot",
                             body, response, 5000);
        if(code < 200 || code > 299)
        {
            Print(StringFormat("[HTTP] PortfolioSnapshot failed — code=%d", code));
            return false;
        }
        return true;
    }

    //+--------------------------------------------------------------+
    //| FetchAgentConfig — GET /api/v1/agent-manager/agents/{id}     |
    //| Reads: safe_mode, locked, strategy_profile, risk_multiplier,  |
    //|        news_lock_setting                                       |
    //+--------------------------------------------------------------+
    bool FetchAgentConfig()
    {
        string endpoint = "/api/v1/agent-manager/agents/" + m_agent_id;
        string response;
        // Use longer timeout for config fetch
        int code = DoRequest("GET", endpoint, "", response, 10000);
        if(code < 200 || code > 299)
        {
            Print(StringFormat("[HTTP] FetchAgentConfig failed — code=%d", code));
            return false;
        }
        return ParseConfigResponse(response);
    }

    //+--------------------------------------------------------------+
    //| SendEvent — POST /api/v1/agent-manager/agents/{id}/events    |
    //| Note: the agent manager router exposes events as read-only;   |
    //| events are inserted by the ingest endpoints internally.       |
    //| This method logs the event locally for transparency.          |
    //+--------------------------------------------------------------+
    bool SendEvent(const string eventType, const string severity,
                   const string message)
    {
        // Events are created server-side on status-change / heartbeat.
        // We log locally so the EA journal shows the event.
        Print(StringFormat("[EVENT] type=%s severity=%s msg=%s",
                           eventType, severity, EscapeJsonString(message)));
        return true;
    }

    //+--------------------------------------------------------------+
    //| Ping — POST /api/v1/ea/ping                                  |
    //| Verify connectivity, API key validity, and agent registration |
    //| Called on OnInit() to confirm the backend is reachable.       |
    //| Returns true on success; fills outServerTime and outStatus.   |
    //+--------------------------------------------------------------+
    bool Ping(string &outServerTime, string &outAgentStatus,
              const string eaVersion = TUYULFX_VERSION,
              const string eaClass   = EA_CLASS_PRIMARY)
    {
        string keys[]   = {"agent_id",    "ea_version", "ea_class"};
        string values[] = {m_agent_id,    eaVersion,    eaClass};
        bool   isStr[]  = {true,          true,         true};
        string body     = BuildJsonPayload(keys, values, isStr, 3);

        string response;
        int code = DoRequest("POST", "/api/v1/ea/ping", body, response);
        if(code < 200 || code > 299)
        {
            Print(StringFormat("[HTTP] Ping failed — code=%d body=%s", code, response));
            return false;
        }

        // Parse response fields
        outServerTime  = JsonGetString(response, "server_time");
        outAgentStatus = JsonGetString(response, "agent_status");
        string status  = JsonGetString(response, "status");
        return (status == "ok");
    }
};

#endif // TUYULFX_HTTP_MQH
