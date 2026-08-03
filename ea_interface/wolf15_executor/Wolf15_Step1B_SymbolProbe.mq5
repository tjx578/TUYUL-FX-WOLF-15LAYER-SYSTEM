#property script_show_inputs
#property strict
#property version "1.00"

input string InpOutputFile = "Wolf15_Step1B_BrokerSymbolMap.csv";

string CanonicalSymbols[30] =
{
   "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
   "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
   "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
   "AUDJPY", "AUDNZD", "AUDCAD", "AUDCHF",
   "NZDJPY", "NZDCHF", "NZDCAD",
   "CADJPY", "CADCHF", "CHFJPY",
   "XAUUSD", "XAGUSD"
};

string Upper(string value)
{
   StringToUpper(value);
   return value;
}

string UtcTimestamp()
{
   MqlDateTime part;
   TimeToStruct(TimeGMT(), part);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ",
                       part.year, part.mon, part.day,
                       part.hour, part.min, part.sec);
}

bool IsStepCompatible(const double value, const double step)
{
   if(step <= 0.0)
      return false;
   double units = value / step;
   return MathAbs(units - MathRound(units)) <= 0.0000001;
}

string NormalizeSymbol(const string value)
{
   string upper = Upper(value);
   string normalized = "";
   for(int index = 0; index < StringLen(upper); index++)
   {
      ushort character = StringGetCharacter(upper, index);
      if((character >= 'A' && character <= 'Z') ||
         (character >= '0' && character <= '9'))
      {
         normalized += StringSubstr(upper, index, 1);
      }
   }
   return normalized;
}

int CandidateScore(const string canonical, const string broker_symbol)
{
   string canonical_upper = Upper(canonical);
   string broker_upper = Upper(broker_symbol);
   if(broker_upper == canonical_upper)
      return 1000;

   string canonical_normalized = NormalizeSymbol(canonical_upper);
   string broker_normalized = NormalizeSymbol(broker_upper);
   string tokens[3];
   int token_count = 1;
   tokens[0] = canonical_normalized;
   if(canonical_upper == "XAUUSD")
   {
      tokens[1] = "GOLD";
      tokens[2] = "XAU";
      token_count = 3;
   }
   else if(canonical_upper == "XAGUSD")
   {
      tokens[1] = "SILVER";
      tokens[2] = "XAG";
      token_count = 3;
   }

   int best_score = -1;
   for(int token_index = 0; token_index < token_count; token_index++)
   {
      string token = tokens[token_index];
      if(broker_normalized == token)
      {
         int exact_score = (token_index == 0) ? 950 : 925;
         if(exact_score > best_score)
            best_score = exact_score;
         continue;
      }

      int position = StringFind(broker_normalized, token);
      if(position < 0)
         continue;
      bool boundary_match = (position == 0 ||
                             position + StringLen(token) == StringLen(broker_normalized));
      if(!boundary_match)
         continue;
      int affix_size = StringLen(broker_normalized) - StringLen(token);
      int affix_score = 800 - MathMin(affix_size, 100);
      if(token_index > 0)
         affix_score -= 25;
      if(affix_score > best_score)
         best_score = affix_score;
   }
   return best_score;
}

bool ResolveBrokerSymbol(const string canonical,
                         string &broker_symbol,
                         string &reason)
{
   broker_symbol = "";
   reason = "NO_MATCH";
   int best_score = -1;
   int best_count = 0;
   int total = SymbolsTotal(false);
   for(int index = 0; index < total; index++)
   {
      string candidate = SymbolName(index, false);
      int score = CandidateScore(canonical, candidate);
      if(score < 0)
         continue;
      if(score > best_score)
      {
         best_score = score;
         best_count = 1;
         broker_symbol = candidate;
      }
      else if(score == best_score && candidate != broker_symbol)
      {
         best_count++;
      }
   }

   if(best_score < 0)
      return false;
   if(best_count > 1)
   {
      broker_symbol = "";
      reason = "AMBIGUOUS_MATCH";
      return false;
   }
   reason = "MATCHED";
   return true;
}

string BoolText(const bool value)
{
   return value ? "true" : "false";
}

void WriteHeader(const int handle)
{
   FileWrite(handle,
      "canonical_symbol", "broker_symbol", "status", "reason",
      "captured_at_utc", "company", "server",
      "selected", "synchronized", "trade_mode", "calc_mode",
      "currency_base", "currency_profit", "currency_margin", "digits",
      "bid", "ask", "spread_points", "spread_float", "point",
      "tick_size", "tick_value", "tick_value_profit", "tick_value_loss",
      "contract_size", "volume_min", "volume_max", "volume_step",
      "volume_limit", "stops_level_points", "freeze_level_points",
      "filling_mode_flags", "order_mode_flags", "expiration_mode_flags",
      "margin_calc_ok", "margin_min_lot", "diagnostic_volume",
      "tick_pnl_calc_ok", "one_tick_pnl_diagnostic_volume",
      "tick_value_relative_error", "tick_value_consistent");
}

bool ProbeSymbol(const int handle, const string canonical)
{
   string broker_symbol = "";
   string reason = "";
   bool resolved = ResolveBrokerSymbol(canonical, broker_symbol, reason);
   if(!resolved)
   {
      FileWrite(handle, canonical, "", "FAIL_REVIEW_REQUIRED", reason,
                UtcTimestamp(), AccountInfoString(ACCOUNT_COMPANY),
                AccountInfoString(ACCOUNT_SERVER));
      PrintFormat("canonical=%s broker= status=FAIL_REVIEW_REQUIRED reason=%s",
                  canonical, reason);
      return false;
   }

   ResetLastError();
   bool selected = SymbolSelect(broker_symbol, true);
   int select_error = GetLastError();
   bool synchronized = SymbolIsSynchronized(broker_symbol);
   for(int attempt = 0; selected && !synchronized && attempt < 10; attempt++)
   {
      Sleep(100);
      synchronized = SymbolIsSynchronized(broker_symbol);
   }

   ENUM_SYMBOL_TRADE_MODE trade_mode =
      (ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(broker_symbol, SYMBOL_TRADE_MODE);
   ENUM_SYMBOL_CALC_MODE calc_mode =
      (ENUM_SYMBOL_CALC_MODE)SymbolInfoInteger(broker_symbol, SYMBOL_TRADE_CALC_MODE);
   long digits = SymbolInfoInteger(broker_symbol, SYMBOL_DIGITS);
   long spread_points = SymbolInfoInteger(broker_symbol, SYMBOL_SPREAD);
   long stops_level = SymbolInfoInteger(broker_symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long freeze_level = SymbolInfoInteger(broker_symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   long filling_flags = SymbolInfoInteger(broker_symbol, SYMBOL_FILLING_MODE);
   long order_flags = SymbolInfoInteger(broker_symbol, SYMBOL_ORDER_MODE);
   long expiration_flags = SymbolInfoInteger(broker_symbol, SYMBOL_EXPIRATION_MODE);
   bool spread_float = (bool)SymbolInfoInteger(broker_symbol, SYMBOL_SPREAD_FLOAT);
   double bid = SymbolInfoDouble(broker_symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(broker_symbol, SYMBOL_ASK);
   double point = SymbolInfoDouble(broker_symbol, SYMBOL_POINT);
   double tick_size = SymbolInfoDouble(broker_symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(broker_symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_value_profit = SymbolInfoDouble(broker_symbol, SYMBOL_TRADE_TICK_VALUE_PROFIT);
   double tick_value_loss = SymbolInfoDouble(broker_symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   double contract_size = SymbolInfoDouble(broker_symbol, SYMBOL_TRADE_CONTRACT_SIZE);
   double volume_min = SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_MIN);
   double volume_max = SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_MAX);
   double volume_step = SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_STEP);
   double volume_limit = SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_LIMIT);

   double margin_min_lot = 0.0;
   bool margin_ok = false;
   if(ask > 0.0 && volume_min > 0.0)
      margin_ok = OrderCalcMargin(ORDER_TYPE_BUY, broker_symbol,
                                  volume_min, ask, margin_min_lot);

   double diagnostic_volume = MathMin(1.0, volume_max);
   if(diagnostic_volume < volume_min)
      diagnostic_volume = volume_min;
   if(volume_step > 0.0)
      diagnostic_volume = MathFloor(diagnostic_volume / volume_step + 0.0000001) * volume_step;
   double one_tick_pnl_diagnostic_volume = 0.0;
   bool tick_pnl_ok = false;
   if(ask > 0.0 && tick_size > 0.0 && diagnostic_volume > 0.0 &&
      IsStepCompatible(diagnostic_volume, volume_step))
   {
      tick_pnl_ok = OrderCalcProfit(ORDER_TYPE_BUY, broker_symbol,
                                    diagnostic_volume, ask, ask - tick_size,
                                    one_tick_pnl_diagnostic_volume);
   }

   double expected_tick_loss = tick_value_loss * diagnostic_volume;
   double tick_value_relative_error = 1.0;
   if(expected_tick_loss > 0.0)
   {
      tick_value_relative_error =
         MathAbs(MathAbs(one_tick_pnl_diagnostic_volume) - expected_tick_loss) /
         expected_tick_loss;
   }
   bool tick_value_consistent = tick_pnl_ok && tick_value_relative_error <= 0.02;

   bool pass = selected && synchronized &&
               trade_mode != SYMBOL_TRADE_MODE_DISABLED &&
               bid > 0.0 && ask > bid && point > 0.0 && tick_size > 0.0 &&
               tick_value_profit > 0.0 && tick_value_loss > 0.0 &&
               volume_min > 0.0 && volume_max >= volume_min &&
               volume_step > 0.0 && margin_ok && tick_value_consistent;
   string status = pass ? "PASS_CANDIDATE" : "FAIL_REVIEW_REQUIRED";
   if(!pass)
      reason = "CAPABILITY_OR_MARKET_DATA_INVALID";

   FileWrite(handle,
      canonical, broker_symbol, status, reason,
      UtcTimestamp(), AccountInfoString(ACCOUNT_COMPANY),
      AccountInfoString(ACCOUNT_SERVER),
      BoolText(selected), BoolText(synchronized), EnumToString(trade_mode),
      EnumToString(calc_mode),
      SymbolInfoString(broker_symbol, SYMBOL_CURRENCY_BASE),
      SymbolInfoString(broker_symbol, SYMBOL_CURRENCY_PROFIT),
      SymbolInfoString(broker_symbol, SYMBOL_CURRENCY_MARGIN),
      (int)digits, DoubleToString(bid, (int)digits),
      DoubleToString(ask, (int)digits), (int)spread_points,
      BoolText(spread_float), DoubleToString(point, 12),
      DoubleToString(tick_size, 12), DoubleToString(tick_value, 8),
      DoubleToString(tick_value_profit, 8), DoubleToString(tick_value_loss, 8),
      DoubleToString(contract_size, 2), DoubleToString(volume_min, 8),
      DoubleToString(volume_max, 8), DoubleToString(volume_step, 8),
      DoubleToString(volume_limit, 8), (int)stops_level, (int)freeze_level,
      (int)filling_flags, (int)order_flags, (int)expiration_flags,
      BoolText(margin_ok), DoubleToString(margin_min_lot, 8),
      DoubleToString(diagnostic_volume, 8), BoolText(tick_pnl_ok),
      DoubleToString(one_tick_pnl_diagnostic_volume, 8),
      DoubleToString(tick_value_relative_error, 8),
      BoolText(tick_value_consistent));

   PrintFormat("canonical=%s broker=%s status=%s reason=%s select_error=%d",
               canonical, broker_symbol, status, reason, select_error);
   return pass;
}

void OnStart()
{
   Print("========== WOLF15_STEP1B_BEGIN ==========");
   PrintFormat("company=%s", AccountInfoString(ACCOUNT_COMPANY));
   PrintFormat("server=%s", AccountInfoString(ACCOUNT_SERVER));
   Print("canonical_count=30");

   int handle = FileOpen(InpOutputFile, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("result=FAIL_REVIEW_REQUIRED reason=CSV_OPEN_FAILED error=%d",
                  GetLastError());
      Print("=========== WOLF15_STEP1B_END ===========");
      return;
   }

   WriteHeader(handle);
   int pass_count = 0;
   for(int index = 0; index < ArraySize(CanonicalSymbols); index++)
   {
      if(ProbeSymbol(handle, CanonicalSymbols[index]))
         pass_count++;
   }
   FileFlush(handle);
   FileClose(handle);

   int fail_count = ArraySize(CanonicalSymbols) - pass_count;
   PrintFormat("pass_count=%d", pass_count);
   PrintFormat("fail_count=%d", fail_count);
   PrintFormat("csv_file=%s", InpOutputFile);
   PrintFormat("result=%s",
               fail_count == 0 ? "PASS_CANDIDATE" : "FAIL_REVIEW_REQUIRED");
   Print("=========== WOLF15_STEP1B_END ===========");
}
