//+------------------------------------------------------------------+
//| TuyulFX_RiskGuard.mqh — Client-side risk guard (defense-in-depth)|
//| NOTE: Backend is the ultimate authority. This is a local          |
//| pre-flight check only, not a strategy or decision layer.          |
//| Zone : ea_interface/v2/ — local guard, no backend authority       |
//+------------------------------------------------------------------+
#property copyright "TuyulFX"
#property strict

#ifndef TUYULFX_RISKGUARD_MQH
#define TUYULFX_RISKGUARD_MQH

#include "TuyulFX_Common.mqh"

//+------------------------------------------------------------------+
//| CTuyulRiskGuard — local risk checks before sending to backend    |
//+------------------------------------------------------------------+
class CTuyulRiskGuard
{
private:
    double m_max_daily_dd_pct;     // Max daily drawdown % (e.g. 4.0 = 4%)
    double m_max_total_dd_pct;     // Max total drawdown % (e.g. 8.0 = 8%)
    int    m_max_concurrent;       // Max concurrent open positions
    double m_max_lot_size;         // Max lot size per trade
    int    m_magic_number;         // Only count our own positions

    double m_equity_high;          // Equity high-water mark
    double m_day_start_balance;    // Balance at start of trading day
    datetime m_day_start_time;     // Timestamp of last daily reset

    string m_last_block_reason;    // Human-readable reason for last block

    //+--------------------------------------------------------------+
    //| SumFloatingPnL — sum profits of all open positions with our  |
    //| magic number                                                  |
    //+--------------------------------------------------------------+
    double SumFloatingPnL()
    {
        double total = 0.0;
        int total_positions = PositionsTotal();
        for(int i = 0; i < total_positions; i++)
        {
            ulong ticket = PositionGetTicket(i);
            if(ticket == 0) continue;
            if(PositionGetInteger(POSITION_MAGIC) != m_magic_number) continue;
            total += PositionGetDouble(POSITION_PROFIT);
        }
        return total;
    }

    //+--------------------------------------------------------------+
    //| CountOurPositions — count open positions with our magic       |
    //+--------------------------------------------------------------+
    int CountOurPositions()
    {
        int count = 0;
        int total_positions = PositionsTotal();
        for(int i = 0; i < total_positions; i++)
        {
            ulong ticket = PositionGetTicket(i);
            if(ticket == 0) continue;
            if(PositionGetInteger(POSITION_MAGIC) == m_magic_number)
                count++;
        }
        return count;
    }

public:
    //+--------------------------------------------------------------+
    //| Constructor                                                   |
    //+--------------------------------------------------------------+
    CTuyulRiskGuard(double maxDailyDDPercent, double maxTotalDDPercent,
                    int maxConcurrentTrades, double maxLotSize,
                    int magicNumber = 151515)
    {
        m_max_daily_dd_pct  = maxDailyDDPercent;
        m_max_total_dd_pct  = maxTotalDDPercent;
        m_max_concurrent    = maxConcurrentTrades;
        m_max_lot_size      = maxLotSize;
        m_magic_number      = magicNumber;
        m_last_block_reason = "";

        // Initialise watermarks
        m_equity_high       = AccountInfoDouble(ACCOUNT_EQUITY);
        m_day_start_balance = AccountInfoDouble(ACCOUNT_BALANCE);
        m_day_start_time    = TimeCurrent();
    }

    //+--------------------------------------------------------------+
    //| UpdateEquityHigh — track equity high-water mark              |
    //+--------------------------------------------------------------+
    void UpdateEquityHigh(double currentEquity)
    {
        if(currentEquity > m_equity_high)
            m_equity_high = currentEquity;
    }

    //+--------------------------------------------------------------+
    //| ResetDaily — call at new-day rollover                        |
    //+--------------------------------------------------------------+
    void ResetDaily()
    {
        m_day_start_balance = AccountInfoDouble(ACCOUNT_BALANCE);
        m_day_start_time    = TimeCurrent();
        Print(StringFormat("[RiskGuard] Daily reset. New start balance=%.2f",
                           m_day_start_balance));
    }

    //+--------------------------------------------------------------+
    //| CheckDailyDrawdown — compare daily P/L vs limit              |
    //+--------------------------------------------------------------+
    bool CheckDailyDrawdown()
    {
        double equity      = AccountInfoDouble(ACCOUNT_EQUITY);
        double daily_dd    = m_day_start_balance - equity;
        double dd_pct      = (m_day_start_balance > 0.0)
                             ? (daily_dd / m_day_start_balance) * 100.0 : 0.0;
        if(dd_pct >= m_max_daily_dd_pct)
        {
            m_last_block_reason = StringFormat(
                "Daily drawdown limit reached: %.2f%% >= %.2f%%",
                dd_pct, m_max_daily_dd_pct);
            return false;
        }
        return true;
    }

    //+--------------------------------------------------------------+
    //| CheckTotalDrawdown — equity vs high-water mark               |
    //+--------------------------------------------------------------+
    bool CheckTotalDrawdown()
    {
        double equity   = AccountInfoDouble(ACCOUNT_EQUITY);
        double total_dd = m_equity_high - equity;
        double dd_pct   = (m_equity_high > 0.0)
                          ? (total_dd / m_equity_high) * 100.0 : 0.0;
        if(dd_pct >= m_max_total_dd_pct)
        {
            m_last_block_reason = StringFormat(
                "Total drawdown limit reached: %.2f%% >= %.2f%%",
                dd_pct, m_max_total_dd_pct);
            return false;
        }
        return true;
    }

    //+--------------------------------------------------------------+
    //| CheckConcurrentTrades — open positions vs limit              |
    //+--------------------------------------------------------------+
    bool CheckConcurrentTrades()
    {
        int open = CountOurPositions();
        if(open >= m_max_concurrent)
        {
            m_last_block_reason = StringFormat(
                "Max concurrent trades: %d >= %d", open, m_max_concurrent);
            return false;
        }
        return true;
    }

    //+--------------------------------------------------------------+
    //| CheckMaxLotSize — lot vs configured maximum                  |
    //+--------------------------------------------------------------+
    bool CheckMaxLotSize(double lot)
    {
        if(lot > m_max_lot_size)
        {
            m_last_block_reason = StringFormat(
                "Lot size %.2f exceeds max %.2f", lot, m_max_lot_size);
            return false;
        }
        return true;
    }

    //+--------------------------------------------------------------+
    //| CheckSpread — current spread vs max allowed pips             |
    //+--------------------------------------------------------------+
    bool CheckSpread(const string symbol, double maxSpreadPips)
    {
        double ask    = SymbolInfoDouble(symbol, SYMBOL_ASK);
        double bid    = SymbolInfoDouble(symbol, SYMBOL_BID);
        double spread = ask - bid;
        double point  = SymbolInfoDouble(symbol, SYMBOL_POINT);
        int    digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
        double pip    = (digits == 5 || digits == 3) ? point * 10.0 : point;
        double spread_pips = (pip > 0.0) ? spread / pip : 0.0;

        if(spread_pips > maxSpreadPips)
        {
            m_last_block_reason = StringFormat(
                "Spread %.1f pips exceeds max %.1f pips",
                spread_pips, maxSpreadPips);
            return false;
        }
        return true;
    }

    //+--------------------------------------------------------------+
    //| CheckMarginAvailable — free margin check for new position    |
    //+--------------------------------------------------------------+
    bool CheckMarginAvailable(double lotSize, const string symbol)
    {
        double margin_required = 0.0;
        ENUM_ORDER_TYPE otype = ORDER_TYPE_BUY; // conservative check
        if(!OrderCalcMargin(otype, symbol, lotSize,
                            SymbolInfoDouble(symbol, SYMBOL_ASK),
                            margin_required))
        {
            Print(StringFormat("[RiskGuard] OrderCalcMargin failed err=%d",
                               GetLastError()));
            return true; // Allow on calculation failure — backend will re-check
        }

        double free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
        if(margin_required > free_margin * 0.9) // 10% safety buffer
        {
            m_last_block_reason = StringFormat(
                "Insufficient free margin: required=%.2f available=%.2f",
                margin_required, free_margin);
            return false;
        }
        return true;
    }

    //+--------------------------------------------------------------+
    //| PreFlightCheck — run all checks before submitting a trade    |
    //| Returns true if trade passes all local checks                 |
    //+--------------------------------------------------------------+
    bool PreFlightCheck(const string symbol, double lotSize, double slPips,
                        double maxSpreadPips)
    {
        m_last_block_reason = "";
        UpdateEquityHigh(AccountInfoDouble(ACCOUNT_EQUITY));

        if(!CheckDailyDrawdown())   return false;
        if(!CheckTotalDrawdown())   return false;
        if(!CheckConcurrentTrades()) return false;
        if(!CheckMaxLotSize(lotSize)) return false;
        if(!CheckSpread(symbol, maxSpreadPips)) return false;
        if(!CheckMarginAvailable(lotSize, symbol)) return false;

        return true;
    }

    //+--------------------------------------------------------------+
    //| GetLastBlockReason — human-readable reason for last failure  |
    //+--------------------------------------------------------------+
    string GetLastBlockReason() const { return m_last_block_reason; }

    //+--------------------------------------------------------------+
    //| IsDailyDDBreached — public accessor for auto-quarantine      |
    //+--------------------------------------------------------------+
    bool IsDailyDDBreached() { return !CheckDailyDrawdown(); }
};

#endif // TUYULFX_RISKGUARD_MQH
