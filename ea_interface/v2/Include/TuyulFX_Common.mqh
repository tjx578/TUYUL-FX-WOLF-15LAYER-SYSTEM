//+------------------------------------------------------------------+
//| TuyulFX_Common.mqh — Shared constants, enums, and utilities      |
//| Version : 3.0.0                                                   |
//| Zone    : ea_interface/v2/ — MQL5 client layer, no decision auth  |
//+------------------------------------------------------------------+
#property copyright "TuyulFX"
#property strict

#ifndef TUYULFX_COMMON_MQH
#define TUYULFX_COMMON_MQH

//+------------------------------------------------------------------+
//| Version                                                           |
//+------------------------------------------------------------------+
#define TUYULFX_VERSION "3.0.0"

//+------------------------------------------------------------------+
//| Backend enum mirrors — EA class                                   |
//+------------------------------------------------------------------+
#define EA_CLASS_PRIMARY   "PRIMARY"
#define EA_CLASS_PORTFOLIO "PORTFOLIO"

//+------------------------------------------------------------------+
//| Backend enum mirrors — EA subtype                                 |
//+------------------------------------------------------------------+
#define EA_SUBTYPE_BROKER            "BROKER"
#define EA_SUBTYPE_PROP_FIRM         "PROP_FIRM"
#define EA_SUBTYPE_EDUMB             "EDUMB"
#define EA_SUBTYPE_STANDARD_REPORTER "STANDARD_REPORTER"

//+------------------------------------------------------------------+
//| Backend enum mirrors — Execution mode                             |
//+------------------------------------------------------------------+
#define EXEC_MODE_LIVE   "LIVE"
#define EXEC_MODE_DEMO   "DEMO"
#define EXEC_MODE_SHADOW "SHADOW"

//+------------------------------------------------------------------+
//| Backend enum mirrors — Reporter mode                              |
//+------------------------------------------------------------------+
#define REPORTER_FULL         "FULL"
#define REPORTER_BALANCE_ONLY "BALANCE_ONLY"
#define REPORTER_DISABLED     "DISABLED"

//+------------------------------------------------------------------+
//| Backend enum mirrors — Agent status                               |
//+------------------------------------------------------------------+
#define STATUS_ONLINE      "ONLINE"
#define STATUS_WARNING     "WARNING"
#define STATUS_OFFLINE     "OFFLINE"
#define STATUS_QUARANTINED "QUARANTINED"
#define STATUS_DISABLED    "DISABLED"

//+------------------------------------------------------------------+
//| Internal EA state enum                                            |
//+------------------------------------------------------------------+
enum ENUM_EA_STATE
{
    EA_STATE_INIT      = 0,   // Initializing — not yet ready
    EA_STATE_RUNNING   = 1,   // Normal operation
    EA_STATE_SAFE_MODE = 2,   // Safe mode — no execution, monitoring only
    EA_STATE_LOCKED    = 3,   // Locked by backend — all activity blocked
    EA_STATE_ERROR     = 4    // Unrecoverable error state
};

//+------------------------------------------------------------------+
//| TuyulTimestamp — ISO 8601 UTC timestamp string                    |
//| Returns e.g. "2026-03-21T15:30:00Z"                              |
//+------------------------------------------------------------------+
string TuyulTimestamp()
{
    datetime utc = TimeGMT();
    MqlDateTime dt;
    TimeToStruct(utc, dt);
    return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ",
                        dt.year, dt.mon, dt.day,
                        dt.hour, dt.min, dt.sec);
}

//+------------------------------------------------------------------+
//| TuyulUUID — pseudo-UUID v4 (MT5 has no native UUID)              |
//| Format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx                      |
//+------------------------------------------------------------------+
string TuyulUUID()
{
    // Seed from tick count + account number for entropy
    MathSrand((int)(GetTickCount() ^ (uint)AccountInfoInteger(ACCOUNT_LOGIN)));

    string hex = "0123456789abcdef";
    string uuid = "";
    int i;

    for(i = 0; i < 32; i++)
    {
        if(i == 8 || i == 12 || i == 16 || i == 20)
            uuid += "-";
        int r = MathRand() % 16;
        if(i == 12)
            r = 4;  // version 4
        else if(i == 16)
            r = (r & 0x3) | 0x8;  // variant bits
        uuid += StringSubstr(hex, r, 1);
    }
    return uuid;
}

//+------------------------------------------------------------------+
//| IsMarketOpen — checks if the current symbol market is open       |
//+------------------------------------------------------------------+
bool IsMarketOpen()
{
    return IsMarketOpen(_Symbol);
}

bool IsMarketOpen(const string symbol)
{
    datetime current = TimeCurrent();
    MqlDateTime dt;
    TimeToStruct(current, dt);
    ENUM_DAY_OF_WEEK dow = (ENUM_DAY_OF_WEEK)dt.day_of_week;

    // Calculate seconds since midnight for the current time
    datetime midnight = current - dt.hour * 3600 - dt.min * 60 - dt.sec;
    datetime time_in_day = current - midnight;

    // Check each session for the current day
    datetime from, to;
    for(int s = 0; s < 10; s++)
    {
        if(!SymbolInfoSessionTrade(symbol, dow, s, from, to)) break;
        if(time_in_day >= from && time_in_day < to) return true;
    }
    return false;
}

//+------------------------------------------------------------------+
//| GetPipDigits — returns pip decimal count for a symbol            |
//| JPY pairs → 2/3, others → 4/5                                    |
//+------------------------------------------------------------------+
int GetPipDigits(const string symbol)
{
    int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
    // JPY pairs and similar 2/3-digit symbols
    if(digits == 2 || digits == 3)
        return digits;
    // Standard 4-digit and 5-digit (fractional pip) symbols
    return (digits == 5 || digits == 3) ? 4 : digits;
}

//+------------------------------------------------------------------+
//| PipValue — pip value in account currency for 1 lot               |
//+------------------------------------------------------------------+
double PipValue(const string symbol)
{
    double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
    double tick_size  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
    double point      = SymbolInfoDouble(symbol, SYMBOL_POINT);
    int    digits     = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

    if(tick_size <= 0.0 || point <= 0.0) return 0.0;

    // Pip = 10 points on 5-digit brokers, 1 point on 4-digit
    double pip_size = (digits == 5 || digits == 3) ? point * 10.0 : point;
    return tick_value * (pip_size / tick_size);
}

//+------------------------------------------------------------------+
//| EscapeJsonString — escapes a string for safe JSON embedding       |
//+------------------------------------------------------------------+
string EscapeJsonString(const string input)
{
    string result = "";
    int len = StringLen(input);
    for(int i = 0; i < len; i++)
    {
        ushort ch = StringGetCharacter(input, i);
        if(ch == '"')        result += "\\\"";
        else if(ch == '\\')  result += "\\\\";
        else if(ch == '\n')  result += "\\n";
        else if(ch == '\r')  result += "\\r";
        else if(ch == '\t')  result += "\\t";
        else if(ch < 0x20)   result += StringFormat("\\u%04x", ch);
        else                 result += ShortToString(ch);
    }
    return result;
}

//+------------------------------------------------------------------+
//| PipCalcFromSlippage — compute slippage pips from price delta     |
//| Centralised to avoid duplication across EA files                  |
//+------------------------------------------------------------------+
double PipCalcFromSlippage(const string symbol,
                           double actual_price, double reference_price)
{
    double point  = SymbolInfoDouble(symbol, SYMBOL_POINT);
    int    digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
    double pip    = (digits == 5 || digits == 3) ? point * 10.0 : point;
    return (pip > 0.0) ? MathAbs(actual_price - reference_price) / pip : 0.0;
}

#endif // TUYULFX_COMMON_MQH
