//+------------------------------------------------------------------+
//| Wolf15 Dumb Executor - one-shot engineering DEMO canary          |
//+------------------------------------------------------------------+
#property copyright "Wolf15"
#property version   "1.00"
#property strict
#property description "DEMO ACCOUNT ONLY. One signed D0 market command, maximum one OrderSend."

// Reuse the audited HTTPS, JSON, signed-wire, HMAC, UUID and symbol-map
// implementation without changing the SHADOW artifact or compiling broker
// mutation into it. Event handlers are renamed before inclusion; this file
// owns the only active handlers in the DEMO artifact.
#define OnInit W15ShadowTransportOnInitUnused
#define OnTimer W15ShadowTransportOnTimerUnused
#define OnTick W15ShadowTransportOnTickUnused
#define OnTradeTransaction W15ShadowTransportOnTradeTransactionUnused
#define OnDeinit W15ShadowTransportOnDeinitUnused
#define InpExecutionEnabled InpLegacyShadowExecutionDisabled
#define AppendLedger W15ShadowAppendLedger
#include "Wolf15_DumbExecutor_Shadow.mq5"
#undef AppendLedger
#undef InpExecutionEnabled
#undef OnDeinit
#undef OnTradeTransaction
#undef OnTick
#undef OnTimer
#undef OnInit

#define W15_DEMO_VERSION "0.1-engineering-demo-canary-v1"
#define W15_DEMO_SOURCE "ENGINEERING_DEMO_CANARY"
#define W15_DEMO_SCHEMA "wolf15.mt5.engineering-demo-canary.v1"
#define W15_DEMO_AUTHORITY "WOLF15_ENGINEERING_DEMO_OPERATOR_V1"
#define W15_DEMO_PURPOSE "EXECUTION_PLUMBING_VALIDATION"
#define W15_DEMO_STATE_MAGIC "W15-D0-STATE-V1"
#define W15_DEMO_MAGIC 150016

input bool   InpDemoExecutionArmed    = false;
input string InpApprovedCanonicalSymbol = "EURUSD";
input string InpApprovedBrokerSymbol    = "EURUSD";

struct DemoExecutionState
{
   string executor_id;
   string account_id;
   string command_id;
   string idempotency_key;
   string request_hash;
   string claim_token;
   string command_json;
   string phase;
   string pending_report_id;
   string pending_report_body;
   int    pending_report_sequence;
   int    last_ack_sequence;
   bool   submit_attempted;
   ulong  order_ticket;
   ulong  deal_ticket;
   ulong  position_id;
   string integrity_tag;
};

bool     g_demo_registered = false;
bool     g_demo_blocked = false;
bool     g_trade_event_pending = false;
datetime g_demo_last_heartbeat = 0;
datetime g_demo_last_poll = 0;
datetime g_demo_last_recovery = 0;

//+------------------------------------------------------------------+
void AppendLedger(const string command_id, const string state, const string detail)
{
   int handle = FileOpen("Wolf15ExecutorDemo\\demo-ledger.csv",
                         FILE_READ | FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_SHARE_READ,
                         ';');
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("[W15-D0] Local ledger open failed error=%d", GetLastError());
      return;
   }
   FileSeek(handle, 0, SEEK_END);
   FileWrite(handle, UtcTimestamp(), command_id, state, detail);
   FileFlush(handle);
   FileClose(handle);
}

//+------------------------------------------------------------------+
string DemoStatePath()
{
   return "Wolf15ExecutorDemo\\execution-state-" + InpExecutorId + ".bin";
}

//+------------------------------------------------------------------+
string DemoStateTempPath()
{
   return DemoStatePath() + ".tmp";
}

//+------------------------------------------------------------------+
void ResetDemoState(DemoExecutionState &state)
{
   state.executor_id = "";
   state.account_id = "";
   state.command_id = "";
   state.idempotency_key = "";
   state.request_hash = "";
   state.claim_token = "";
   state.command_json = "";
   state.phase = "";
   state.pending_report_id = "-";
   state.pending_report_body = "-";
   state.pending_report_sequence = 0;
   state.last_ack_sequence = 0;
   state.submit_attempted = false;
   state.order_ticket = 0;
   state.deal_ticket = 0;
   state.position_id = 0;
   state.integrity_tag = "";
}

//+------------------------------------------------------------------+
bool DemoStateExists()
{
   return (FileIsExist(DemoStatePath(), 0) || FileIsExist(DemoStateTempPath(), 0));
}

//+------------------------------------------------------------------+
string DemoStateMaterial(const DemoExecutionState &state)
{
   return W15_DEMO_STATE_MAGIC + "\n" +
          "executor_id=" + state.executor_id + "\n" +
          "account_id=" + state.account_id + "\n" +
          "command_id=" + state.command_id + "\n" +
          "idempotency_key=" + state.idempotency_key + "\n" +
          "request_hash=" + state.request_hash + "\n" +
          "claim_token=" + state.claim_token + "\n" +
          "command_json=" + state.command_json + "\n" +
          "phase=" + state.phase + "\n" +
          "pending_report_id=" + state.pending_report_id + "\n" +
          "pending_report_body=" + state.pending_report_body + "\n" +
          "pending_report_sequence=" + IntegerToString(state.pending_report_sequence) + "\n" +
          "last_ack_sequence=" + IntegerToString(state.last_ack_sequence) + "\n" +
          "submit_attempted=" + (state.submit_attempted ? "true" : "false") + "\n" +
          "order_ticket=" + (string)state.order_ticket + "\n" +
          "deal_ticket=" + (string)state.deal_ticket + "\n" +
          "position_id=" + (string)state.position_id;
}

//+------------------------------------------------------------------+
bool ComputeDemoIntegrityTag(const DemoExecutionState &state, string &tag)
{
   uchar verification_key[];
   uchar material[];
   uchar digest[];
   if(!TaggedHexToBytes(InpCommandVerificationKey, "hex:", 32, verification_key) ||
      !AsciiToBytes(DemoStateMaterial(state), material) ||
      !HmacSha256Bytes(verification_key, material, digest))
      return false;
   tag = "hmac-sha256:" + BytesToHex(digest);
   return true;
}

//+------------------------------------------------------------------+
bool ValidateDemoState(const DemoExecutionState &state, string &reason)
{
   uchar request_digest[];
   uchar stored_tag[];
   uchar expected_tag[];
   if(state.executor_id != InpExecutorId || state.account_id != InpExpectedAccountId)
   {
      reason = "DEMO_STATE_BINDING_MISMATCH";
      return false;
   }
   if(StringLen(state.command_id) != 36 ||
      !IsSafeWireIdentifier(state.command_id) ||
      !IsSafeAsciiToken(state.idempotency_key, 8, 250) ||
      !TaggedHexToBytes(state.request_hash, "sha256:", 32, request_digest) ||
      !IsSafeAsciiToken(state.claim_token, 32, 512) ||
      StringLen(state.command_json) < 2 || StringLen(state.command_json) > 131072 ||
      JsonValue(state.command_json, "command_id") != state.command_id ||
      JsonValue(state.command_json, "idempotency_key") != state.idempotency_key)
   {
      reason = "DEMO_STATE_SHAPE_INVALID";
      return false;
   }
   if(state.pending_report_sequence < 0 || state.last_ack_sequence < 0 ||
      state.pending_report_sequence < state.last_ack_sequence ||
      (state.pending_report_id == "-") != (state.pending_report_body == "-"))
   {
      reason = "DEMO_STATE_SEQUENCE_INVALID";
      return false;
   }
   if(state.pending_report_id != "-" &&
      (JsonValue(state.pending_report_body, "report_id") != state.pending_report_id ||
       JsonValue(state.pending_report_body, "command_id") != state.command_id ||
       JsonValue(state.pending_report_body, "request_hash") != state.request_hash ||
       StringToInteger(JsonValue(state.pending_report_body, "sequence")) !=
          state.pending_report_sequence))
   {
      reason = "DEMO_PENDING_REPORT_MISMATCH";
      return false;
   }
   string expected = "";
   if(!ComputeDemoIntegrityTag(state, expected) ||
      !TaggedHexToBytes(state.integrity_tag, "hmac-sha256:", 32, stored_tag) ||
      !TaggedHexToBytes(expected, "hmac-sha256:", 32, expected_tag) ||
      !ConstantTimeBytesEqual(stored_tag, expected_tag))
   {
      reason = "DEMO_STATE_INTEGRITY_INVALID";
      return false;
   }
   reason = "";
   return true;
}

//+------------------------------------------------------------------+
bool SaveDemoState(DemoExecutionState &state, string &reason)
{
   if(!ComputeDemoIntegrityTag(state, state.integrity_tag) ||
      !ValidateDemoState(state, reason))
      return false;
   int handle = FileOpen(DemoStateTempPath(), FILE_WRITE | FILE_BIN | FILE_ANSI, 0, CP_UTF8);
   if(handle == INVALID_HANDLE)
   {
      reason = "DEMO_STATE_TEMP_OPEN_FAILED";
      return false;
   }
   bool written = (
      WriteSizedAscii(handle, W15_DEMO_STATE_MAGIC, 64) &&
      WriteSizedAscii(handle, state.executor_id, 100) &&
      WriteSizedAscii(handle, state.account_id, 100) &&
      WriteSizedAscii(handle, state.command_id, 100) &&
      WriteSizedAscii(handle, state.idempotency_key, 250) &&
      WriteSizedAscii(handle, state.request_hash, 100) &&
      WriteSizedAscii(handle, state.claim_token, 512) &&
      WriteSizedAscii(handle, state.command_json, 131072) &&
      WriteSizedAscii(handle, state.phase, 64) &&
      WriteSizedAscii(handle, state.pending_report_id, 100) &&
      WriteSizedAscii(handle, state.pending_report_body, 131072) &&
      WriteSizedAscii(handle, IntegerToString(state.pending_report_sequence), 20) &&
      WriteSizedAscii(handle, IntegerToString(state.last_ack_sequence), 20) &&
      WriteSizedAscii(handle, state.submit_attempted ? "true" : "false", 5) &&
      WriteSizedAscii(handle, (string)state.order_ticket, 32) &&
      WriteSizedAscii(handle, (string)state.deal_ticket, 32) &&
      WriteSizedAscii(handle, (string)state.position_id, 32) &&
      WriteSizedAscii(handle, state.integrity_tag, 100)
   );
   FileFlush(handle);
   FileClose(handle);
   if(!written || !FileMove(DemoStateTempPath(), 0, DemoStatePath(), FILE_REWRITE))
   {
      reason = "DEMO_STATE_ATOMIC_PERSIST_FAILED";
      return false;
   }
   AppendLedger(state.command_id, "STATE_DURABLE", state.phase);
   reason = "";
   return true;
}

//+------------------------------------------------------------------+
bool LoadDemoState(DemoExecutionState &state, string &reason)
{
   ResetDemoState(state);
   if(!FileIsExist(DemoStatePath(), 0) && FileIsExist(DemoStateTempPath(), 0))
   {
      if(!FileMove(DemoStateTempPath(), 0, DemoStatePath(), FILE_REWRITE))
      {
         reason = "DEMO_STATE_TEMP_RECOVERY_FAILED";
         return false;
      }
   }
   if(!FileIsExist(DemoStatePath(), 0))
   {
      reason = "";
      return true;
   }
   int handle = FileOpen(DemoStatePath(), FILE_READ | FILE_BIN | FILE_ANSI, 0, CP_UTF8);
   if(handle == INVALID_HANDLE)
   {
      reason = "DEMO_STATE_OPEN_FAILED";
      return false;
   }
   string magic = "";
   string pending_sequence = "";
   string ack_sequence = "";
   string attempted = "";
   string order_ticket = "";
   string deal_ticket = "";
   string position_id = "";
   bool read = (
      ReadSizedAscii(handle, 64, magic) &&
      ReadSizedAscii(handle, 100, state.executor_id) &&
      ReadSizedAscii(handle, 100, state.account_id) &&
      ReadSizedAscii(handle, 100, state.command_id) &&
      ReadSizedAscii(handle, 250, state.idempotency_key) &&
      ReadSizedAscii(handle, 100, state.request_hash) &&
      ReadSizedAscii(handle, 512, state.claim_token) &&
      ReadSizedAscii(handle, 131072, state.command_json) &&
      ReadSizedAscii(handle, 64, state.phase) &&
      ReadSizedAscii(handle, 100, state.pending_report_id) &&
      ReadSizedAscii(handle, 131072, state.pending_report_body) &&
      ReadSizedAscii(handle, 20, pending_sequence) &&
      ReadSizedAscii(handle, 20, ack_sequence) &&
      ReadSizedAscii(handle, 5, attempted) &&
      ReadSizedAscii(handle, 32, order_ticket) &&
      ReadSizedAscii(handle, 32, deal_ticket) &&
      ReadSizedAscii(handle, 32, position_id) &&
      ReadSizedAscii(handle, 100, state.integrity_tag)
   );
   bool exact = (FileTell(handle) == FileSize(handle));
   FileClose(handle);
   state.pending_report_sequence = (int)StringToInteger(pending_sequence);
   state.last_ack_sequence = (int)StringToInteger(ack_sequence);
   state.submit_attempted = (attempted == "true");
   state.order_ticket = (ulong)StringToInteger(order_ticket);
   state.deal_ticket = (ulong)StringToInteger(deal_ticket);
   state.position_id = (ulong)StringToInteger(position_id);
   if(!read || !exact || magic != W15_DEMO_STATE_MAGIC)
   {
      reason = "DEMO_STATE_FILE_CORRUPT";
      return false;
   }
   return ValidateDemoState(state, reason);
}

//+------------------------------------------------------------------+
bool ClearDemoState()
{
   bool ok = true;
   if(FileIsExist(DemoStatePath(), 0) && !FileDelete(DemoStatePath(), 0))
      ok = false;
   if(FileIsExist(DemoStateTempPath(), 0) && !FileDelete(DemoStateTempPath(), 0))
      ok = false;
   return ok;
}

//+------------------------------------------------------------------+
string OptionalPriceJson(const double value)
{
   return value > 0.0 ? DoubleToString(value, 10) : "null";
}

//+------------------------------------------------------------------+
string BuildPendingOrdersJson()
{
   string out = "[";
   int written = 0;
   for(int index = 0; index < OrdersTotal(); index++)
   {
      ulong ticket = OrderGetTicket(index);
      if(ticket == 0 || !OrderSelect(ticket))
         continue;
      ENUM_ORDER_TYPE type = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      string type_name = "";
      if(type == ORDER_TYPE_BUY_LIMIT) type_name = "BUY_LIMIT";
      if(type == ORDER_TYPE_SELL_LIMIT) type_name = "SELL_LIMIT";
      if(type == ORDER_TYPE_BUY_STOP) type_name = "BUY_STOP";
      if(type == ORDER_TYPE_SELL_STOP) type_name = "SELL_STOP";
      if(type == ORDER_TYPE_BUY_STOP_LIMIT) type_name = "BUY_STOP_LIMIT";
      if(type == ORDER_TYPE_SELL_STOP_LIMIT) type_name = "SELL_STOP_LIMIT";
      if(StringLen(type_name) == 0)
         continue;
      if(written++ > 0)
         out += ",";
      out += StringFormat(
         "{\"order_ticket\":%I64u,\"symbol\":\"%s\",\"order_type\":\"%s\","
         "\"volume\":%.8f,\"requested_price\":%.10f,\"stop_loss\":%s,"
         "\"take_profit\":%s,\"magic\":%I64d,\"comment\":\"%s\"}",
         ticket, EscapeJson(OrderGetString(ORDER_SYMBOL)), type_name,
         OrderGetDouble(ORDER_VOLUME_INITIAL), OrderGetDouble(ORDER_PRICE_OPEN),
         OptionalPriceJson(OrderGetDouble(ORDER_SL)), OptionalPriceJson(OrderGetDouble(ORDER_TP)),
         OrderGetInteger(ORDER_MAGIC), EscapeJson(OrderGetString(ORDER_COMMENT)));
   }
   out += "]";
   return out;
}

//+------------------------------------------------------------------+
bool RegisterDemoExecutor()
{
   string body = StringFormat(
      "{\"protocol_version\":\"%s\",\"executor_id\":\"%s\","
      "\"account_id\":\"%s\",\"login_hash\":\"%s\","
      "\"broker_server\":\"%s\",\"terminal_build\":%d,"
      "\"ea_version\":\"%s\",\"requested_mode\":\"DEMO\"}",
      W15_PROTOCOL, InpExecutorId, EscapeJson(InpExpectedAccountId), InpLoginHash,
      EscapeJson(InpExpectedBrokerServer), (int)TerminalInfoInteger(TERMINAL_BUILD),
      W15_DEMO_VERSION);
   string response;
   int code = HttpRequest("POST", "/api/v1/executors/register", body, "", response);
   if((code != 200 && code != 201) || JsonValue(response, "execution_mode") != "DEMO")
   {
      PrintFormat("[W15-D0] DEMO registration rejected code=%d", code);
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
bool SendDemoHeartbeat()
{
   string snapshot_id = "snap-" + MakeUuid();
   string captured = UtcTimestamp();
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   bool trade_allowed = (bool)AccountInfoInteger(ACCOUNT_TRADE_ALLOWED);
   bool auto_enabled = (bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED);
   string symbols_json = BuildSymbolsJson();
   string positions_json = BuildPositionsJson();
   string orders_json = BuildPendingOrdersJson();
   if(StringLen(symbols_json) == 0 || StringLen(positions_json) == 0 || StringLen(orders_json) == 0)
      return false;
   string margin_level = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL) > 0
                         ? DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_LEVEL), 4) : "null";
   string snapshot = StringFormat(
      "{\"snapshot_id\":\"%s\",\"captured_at_utc\":\"%s\","
      "\"executor_id\":\"%s\",\"account_id\":\"%s\",\"currency\":\"%s\","
      "\"balance\":%.2f,\"equity\":%.2f,\"floating_pnl\":%.2f,"
      "\"used_margin\":%.2f,\"free_margin\":%.2f,\"margin_level_pct\":%s,"
      "\"margin_mode\":\"%s\",\"trade_allowed\":%s,\"autotrading_enabled\":%s,"
      "\"open_positions\":%s,\"pending_orders\":%s,"
      "\"broker_ledger_reconciled\":false,\"symbols\":%s}",
      snapshot_id, captured, InpExecutorId, EscapeJson(InpExpectedAccountId),
      EscapeJson(AccountInfoString(ACCOUNT_CURRENCY)), balance, equity, equity - balance,
      AccountInfoDouble(ACCOUNT_MARGIN), AccountInfoDouble(ACCOUNT_MARGIN_FREE),
      margin_level, MarginModeName(), trade_allowed ? "true" : "false",
      auto_enabled ? "true" : "false", positions_json, orders_json, symbols_json);
   string body = StringFormat(
      "{\"protocol_version\":\"%s\",\"executor_id\":\"%s\","
      "\"sent_at_utc\":\"%s\",\"terminal_connected\":%s,"
      "\"trade_allowed\":%s,\"autotrading_enabled\":%s,\"account_snapshot\":%s}",
      W15_PROTOCOL, InpExecutorId, captured,
      (bool)TerminalInfoInteger(TERMINAL_CONNECTED) ? "true" : "false",
      trade_allowed ? "true" : "false", auto_enabled ? "true" : "false", snapshot);
   string response;
   int code = HttpRequest("POST", "/api/v1/executors/" + InpExecutorId + "/heartbeat",
                          body, "", response);
   return (code >= 200 && code <= 299);
}

//+------------------------------------------------------------------+
bool ValidateDemoCommand(const string json, string &reason)
{
   if(JsonValue(json, "protocol_version") != W15_PROTOCOL ||
      JsonValue(json, "execution_mode") != "DEMO" ||
      JsonValue(json, "source_event") != W15_DEMO_SOURCE ||
      JsonValue(json, "source_schema_version") != W15_DEMO_SCHEMA ||
      JsonValue(json, "command_source_class") != W15_DEMO_SOURCE ||
      JsonValue(json, "operator_authority") != W15_DEMO_AUTHORITY ||
      JsonValue(json, "purpose") != W15_DEMO_PURPOSE)
   {
      reason = "DEMO_CANARY_LINEAGE_REJECTED";
      return false;
   }
   if(JsonValue(json, "strategy_authority", "missing") != "false" ||
      JsonValue(json, "strategy_scorecard_eligible", "missing") != "false" ||
      JsonValue(json, "research_result_eligible", "missing") != "false" ||
      JsonValue(json, "live_real_money_allowed", "missing") != "false" ||
      JsonValue(json, "demo_only", "missing") != "true" ||
      JsonValue(json, "order_role") != "PARENT" ||
      JsonValue(json, "max_broker_effects") != "1")
   {
      reason = "DEMO_CANARY_AUTHORITY_REJECTED";
      return false;
   }
   if(JsonValue(json, "approved_executor_id") != InpExecutorId ||
      JsonValue(json, "approved_account_id") != InpExpectedAccountId ||
      JsonValue(json, "approved_broker_server") != InpExpectedBrokerServer ||
      JsonValue(json, "approved_canonical_symbol") != InpApprovedCanonicalSymbol ||
      JsonValue(json, "approved_broker_symbol") != InpApprovedBrokerSymbol ||
      JsonValue(json, "account_id") != InpExpectedAccountId ||
      JsonValue(json, "broker_server") != InpExpectedBrokerServer)
   {
      reason = "DEMO_CANARY_BINDING_REJECTED";
      return false;
   }
   if(JsonValue(json, "canonical_symbol") != InpApprovedCanonicalSymbol ||
      JsonValue(json, "broker_symbol") != InpApprovedBrokerSymbol ||
      SymbolPairIndex(InpApprovedCanonicalSymbol, InpApprovedBrokerSymbol) < 0)
   {
      reason = "DEMO_CANARY_SYMBOL_REJECTED";
      return false;
   }
   if(JsonValue(json, "guard_type") != W15_DEMO_SOURCE ||
      !JsonBool(json, "scoped_demo_window_required") ||
      !JsonBool(json, "broker_ledger_reconciled") ||
      !JsonBool(json, "require_attached_sl") ||
      !JsonBool(json, "require_attached_tp") ||
      JsonValue(json, "max_submit_attempts") != "1" ||
      JsonValue(json, "broker_execution") != "DEMO_ONLY" ||
      StringFind(json, "\"risk_reservation_id\"") >= 0 ||
      StringFind(json, "\"risk_snapshot_id\"") >= 0)
   {
      reason = "DEMO_CANARY_GUARD_REJECTED";
      return false;
   }
   if(JsonValue(json, "action") != "PLACE_MARKET" ||
      !IsSafeAsciiToken(JsonValue(json, "canary_id"), 3, 64) ||
      !IsSafeAsciiToken(JsonValue(json, "idempotency_key"), 8, 250) ||
      StringFind(JsonValue(json, "comment_tag"), "W15D0:") != 0 ||
      StringToInteger(JsonValue(json, "magic")) != W15_DEMO_MAGIC ||
      JsonValue(json, "time_in_force") != "GTC")
   {
      reason = "DEMO_CANARY_COMMAND_SHAPE_REJECTED";
      return false;
   }
   datetime expiry = ParseUtc(JsonValue(json, "expires_at_utc"));
   if(expiry <= 0 || TimeGMT() >= expiry)
   {
      reason = "DEMO_CANARY_EXPIRED";
      return false;
   }
   string side = JsonValue(json, "side");
   string order_type = JsonValue(json, "order_type");
   double entry = StringToDouble(JsonValue(json, "entry_price"));
   double stop = StringToDouble(JsonValue(json, "stop_loss"));
   double target = StringToDouble(JsonValue(json, "take_profit"));
   double volume = StringToDouble(JsonValue(json, "volume"));
   if((side != "BUY" && side != "SELL") || order_type != side ||
      (side == "BUY" && !(stop < entry && entry < target)) ||
      (side == "SELL" && !(target < entry && entry < stop)))
   {
      reason = "DEMO_CANARY_PRICE_OR_SIDE_REJECTED";
      return false;
   }
   double minimum = SymbolInfoDouble(InpApprovedBrokerSymbol, SYMBOL_VOLUME_MIN);
   double step = SymbolInfoDouble(InpApprovedBrokerSymbol, SYMBOL_VOLUME_STEP);
   if(MathAbs(volume - minimum) > 0.0000001 || !IsStepCompatible(volume, step))
   {
      reason = "DEMO_CANARY_NOT_MINIMUM_VOLUME";
      return false;
   }
   MqlTick tick;
   double point = SymbolInfoDouble(InpApprovedBrokerSymbol, SYMBOL_POINT);
   if(!SymbolInfoTick(InpApprovedBrokerSymbol, tick) || point <= 0)
   {
      reason = "DEMO_CANARY_QUOTE_UNAVAILABLE";
      return false;
   }
   double live_price = (side == "BUY") ? tick.ask : tick.bid;
   int spread_points = (int)MathRound((tick.ask - tick.bid) / point);
   int drift_points = (int)MathRound(MathAbs(live_price - entry) / point);
   if(spread_points > (int)StringToInteger(JsonValue(json, "max_spread_points")) ||
      drift_points > (int)StringToInteger(JsonValue(json, "max_price_drift_points")))
   {
      reason = "DEMO_CANARY_MARKET_PREFLIGHT_REJECTED";
      return false;
   }
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO ||
      !(bool)AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) ||
      !(bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) ||
      JsonValue(json, "expected_margin_mode") != MarginModeName() ||
      MathAbs(AccountInfoDouble(ACCOUNT_BALANCE) -
              StringToDouble(JsonValue(json, "balance_snapshot"))) > 0.005 ||
      MathAbs(AccountInfoDouble(ACCOUNT_EQUITY) -
              StringToDouble(JsonValue(json, "equity_snapshot"))) > 0.005 ||
      PositionsTotal() != 0 || OrdersTotal() != 0)
   {
      reason = "DEMO_CANARY_ACCOUNT_NOT_FLAT_READY_DEMO";
      return false;
   }
   reason = "DEMO_CANARY_VALIDATED_SIGNATURE_VERIFIED";
   return true;
}

//+------------------------------------------------------------------+
string NullableTicket(const ulong value)
{
   return value == 0 ? "null" : (string)value;
}

//+------------------------------------------------------------------+
string NullableRetcode(const uint value)
{
   return value == 0 ? "null" : IntegerToString((int)value);
}

//+------------------------------------------------------------------+
bool PrepareDemoReport(DemoExecutionState &state,
                       const string report_state,
                       const string reason_code,
                       const string reason_detail,
                       const double filled_volume,
                       const double filled_price,
                       const uint broker_retcode)
{
   int sequence = state.last_ack_sequence + 1;
   string command = state.command_json;
   double requested_volume = StringToDouble(JsonValue(command, "volume"));
   double requested_price = StringToDouble(JsonValue(command, "entry_price"));
   double stop = StringToDouble(JsonValue(command, "stop_loss"));
   double target = StringToDouble(JsonValue(command, "take_profit"));
   state.pending_report_id = MakeUuid();
   state.pending_report_sequence = sequence;
   state.pending_report_body = StringFormat(
      "{\"event\":\"execution_report\",\"protocol_version\":\"%s\","
      "\"report_id\":\"%s\",\"command_id\":\"%s\","
      "\"idempotency_key\":\"%s\",\"sequence\":%d,\"state\":\"%s\","
      "\"event_time_utc\":\"%s\",\"executor_id\":\"%s\","
      "\"account_id\":\"%s\",\"request_hash\":\"%s\","
      "\"broker\":{\"order_ticket\":%s,\"deal_ticket\":%s,"
      "\"position_id\":%s,\"retcode\":%s},\"execution\":{\"requested_volume\":%.8f,"
      "\"filled_volume\":%.8f,\"requested_price\":%.10f,\"filled_price\":%s,"
      "\"stop_loss\":%.10f,\"take_profit\":%.10f},"
      "\"reason_code\":\"%s\",\"reason_detail\":\"%s\"}",
      W15_PROTOCOL, state.pending_report_id, state.command_id,
      EscapeJson(state.idempotency_key), sequence, report_state, UtcTimestamp(),
      InpExecutorId, EscapeJson(InpExpectedAccountId), state.request_hash,
      NullableTicket(state.order_ticket), NullableTicket(state.deal_ticket),
      NullableTicket(state.position_id), NullableRetcode(broker_retcode),
      requested_volume, filled_volume,
      requested_price, filled_price > 0 ? DoubleToString(filled_price, 10) : "null",
      stop, target, reason_code, EscapeJson(reason_detail));
   string error = "";
   if(!SaveDemoState(state, error))
   {
      g_demo_blocked = true;
      AppendLedger(state.command_id, "REPORT_PERSIST_FAILED", error);
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
bool PostPreparedDemoReport(DemoExecutionState &state)
{
   if(state.pending_report_id == "-")
      return true;
   string response;
   int code = HttpRequest("POST", "/api/v1/commands/" + state.command_id + "/reports",
                          state.pending_report_body, state.claim_token, response);
   if(code != 200 && code != 202)
   {
      AppendLedger(state.command_id, "REPORT_POST_PENDING", IntegerToString(code));
      return false;
   }
   state.last_ack_sequence = state.pending_report_sequence;
   string command_state = JsonValue(response, "command_state");
   state.pending_report_id = "-";
   state.pending_report_body = "-";
   state.pending_report_sequence = state.last_ack_sequence;
   string error = "";
   if(!SaveDemoState(state, error))
   {
      g_demo_blocked = true;
      return false;
   }
   AppendLedger(state.command_id, "REPORT_ACKNOWLEDGED", command_state);
   if(command_state == "REJECTED" || command_state == "FILLED" ||
      command_state == "CANCELLED" || command_state == "COMPLETED" ||
      command_state == "EXPIRED")
   {
      g_last_command_id = state.command_id;
      if(!ClearDemoState())
         g_demo_blocked = true;
   }
   return true;
}

//+------------------------------------------------------------------+
bool SendDemoReport(DemoExecutionState &state,
                    const string report_state,
                    const string reason_code,
                    const string reason_detail,
                    const double filled_volume = 0.0,
                    const double filled_price = 0.0,
                    const uint broker_retcode = 0)
{
   if(!PrepareDemoReport(state, report_state, reason_code, reason_detail,
                         filled_volume, filled_price, broker_retcode))
      return false;
   return PostPreparedDemoReport(state);
}

//+------------------------------------------------------------------+
ENUM_ORDER_TYPE_FILLING DemoFillingMode(const string symbol)
{
   long flags = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
   if((flags & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
      return ORDER_FILLING_FOK;
   if((flags & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
      return ORDER_FILLING_IOC;
   return ORDER_FILLING_RETURN;
}

//+------------------------------------------------------------------+
bool MergeUniqueDemoTicket(const ulong candidate,
                           ulong &current,
                           const string conflict_reason,
                           string &reason)
{
   if(candidate == 0)
      return true;
   if(current != 0 && current != candidate)
   {
      reason = conflict_reason;
      return false;
   }
   current = candidate;
   return true;
}

//+------------------------------------------------------------------+
bool ReconcileDemoBrokerState(DemoExecutionState &state,
                              double &filled_volume,
                              double &filled_price,
                              string &reason)
{
   filled_volume = 0.0;
   filled_price = 0.0;
   string symbol = JsonValue(state.command_json, "broker_symbol");
   string comment = JsonValue(state.command_json, "comment_tag");
   double expected_stop = StringToDouble(JsonValue(state.command_json, "stop_loss"));
   double expected_target = StringToDouble(JsonValue(state.command_json, "take_profit"));
   int symbol_digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   datetime issued = ParseUtc(JsonValue(state.command_json, "issued_at_utc"));
   if(issued <= 0 || symbol == "" || comment == "" || symbol_digits < 0 ||
      expected_stop <= 0.0 || expected_target <= 0.0)
   {
      reason = "DEMO_RECONCILIATION_LINEAGE_INVALID";
      return false;
   }
   if(!HistorySelect(issued - 300, TimeCurrent() + 60))
   {
      reason = "DEMO_RECONCILIATION_HISTORY_UNAVAILABLE";
      return false;
   }

   ulong order_ticket = state.order_ticket;
   ulong deal_ticket = state.deal_ticket;
   ulong position_id = state.position_id;

   for(int index = 0; index < OrdersTotal(); index++)
   {
      ulong ticket = OrderGetTicket(index);
      if(ticket == 0 || !OrderSelect(ticket) ||
         OrderGetInteger(ORDER_MAGIC) != W15_DEMO_MAGIC ||
         OrderGetString(ORDER_SYMBOL) != symbol ||
         OrderGetString(ORDER_COMMENT) != comment)
         continue;
      if(!MergeUniqueDemoTicket(ticket, order_ticket,
                                "DEMO_RECONCILIATION_MULTIPLE_ORDERS", reason))
         return false;
   }

   for(int index = 0; index < HistoryOrdersTotal(); index++)
   {
      ulong ticket = HistoryOrderGetTicket(index);
      if(ticket == 0 ||
         HistoryOrderGetInteger(ticket, ORDER_MAGIC) != W15_DEMO_MAGIC ||
         HistoryOrderGetString(ticket, ORDER_SYMBOL) != symbol ||
         HistoryOrderGetString(ticket, ORDER_COMMENT) != comment)
         continue;
      if(!MergeUniqueDemoTicket(ticket, order_ticket,
                                "DEMO_RECONCILIATION_MULTIPLE_ORDERS", reason))
         return false;
   }

   for(int index = 0; index < PositionsTotal(); index++)
   {
      ulong ticket = PositionGetTicket(index);
      if(ticket == 0 || !PositionSelectByTicket(ticket) ||
         PositionGetInteger(POSITION_MAGIC) != W15_DEMO_MAGIC ||
         PositionGetString(POSITION_SYMBOL) != symbol ||
         PositionGetString(POSITION_COMMENT) != comment)
         continue;
      ulong identifier = (ulong)PositionGetInteger(POSITION_IDENTIFIER);
      if(NormalizeDouble(PositionGetDouble(POSITION_SL), symbol_digits) !=
            NormalizeDouble(expected_stop, symbol_digits) ||
         NormalizeDouble(PositionGetDouble(POSITION_TP), symbol_digits) !=
            NormalizeDouble(expected_target, symbol_digits))
      {
         reason = "DEMO_RECONCILIATION_PROTECTION_MISMATCH";
         return false;
      }
      if(!MergeUniqueDemoTicket(identifier, position_id,
                                "DEMO_RECONCILIATION_MULTIPLE_POSITIONS", reason))
         return false;
   }

   for(int index = 0; index < HistoryDealsTotal(); index++)
   {
      ulong ticket = HistoryDealGetTicket(index);
      if(ticket == 0 ||
         HistoryDealGetInteger(ticket, DEAL_MAGIC) != W15_DEMO_MAGIC ||
         HistoryDealGetString(ticket, DEAL_SYMBOL) != symbol)
         continue;
      ENUM_DEAL_TYPE deal_type = (ENUM_DEAL_TYPE)HistoryDealGetInteger(ticket, DEAL_TYPE);
      if(deal_type != DEAL_TYPE_BUY && deal_type != DEAL_TYPE_SELL)
         continue;
      ulong linked_order = (ulong)HistoryDealGetInteger(ticket, DEAL_ORDER);
      string deal_comment = HistoryDealGetString(ticket, DEAL_COMMENT);
      if((order_ticket != 0 && linked_order != order_ticket) ||
         (order_ticket == 0 && deal_comment != comment))
         continue;
      if(!MergeUniqueDemoTicket(linked_order, order_ticket,
                                "DEMO_RECONCILIATION_MULTIPLE_ORDERS", reason) ||
         !MergeUniqueDemoTicket(ticket, deal_ticket,
                                "DEMO_RECONCILIATION_MULTIPLE_DEALS", reason) ||
         !MergeUniqueDemoTicket(
            (ulong)HistoryDealGetInteger(ticket, DEAL_POSITION_ID), position_id,
            "DEMO_RECONCILIATION_MULTIPLE_POSITIONS", reason))
         return false;
      filled_volume = HistoryDealGetDouble(ticket, DEAL_VOLUME);
      filled_price = HistoryDealGetDouble(ticket, DEAL_PRICE);
   }

   bool changed = (state.order_ticket != order_ticket ||
                   state.deal_ticket != deal_ticket ||
                   state.position_id != position_id);
   state.order_ticket = order_ticket;
   state.deal_ticket = deal_ticket;
   state.position_id = position_id;
   if(changed)
   {
      string persistence_error = "";
      state.phase = "BROKER_HISTORY_RECONCILED";
      if(!SaveDemoState(state, persistence_error))
      {
         reason = persistence_error;
         return false;
      }
   }
   reason = (order_ticket > 0 || deal_ticket > 0 || position_id > 0)
            ? "DEMO_BROKER_EFFECT_RECONCILED"
            : "DEMO_BROKER_EFFECT_NOT_FOUND";
   return true;
}

//+------------------------------------------------------------------+
bool BuildCheckedDemoRequest(const string json,
                             MqlTradeRequest &request,
                             MqlTradeCheckResult &check,
                             string &reason)
{
   if(!ValidateDemoCommand(json, reason))
      return false;
   string symbol = JsonValue(json, "broker_symbol");
   string side = JsonValue(json, "side");
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
   {
      reason = "DEMO_QUOTE_UNAVAILABLE";
      return false;
   }
   ZeroMemory(request);
   ZeroMemory(check);
   request.action = TRADE_ACTION_DEAL;
   request.symbol = symbol;
   request.volume = StringToDouble(JsonValue(json, "volume"));
   request.type = (side == "BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   request.price = (side == "BUY") ? tick.ask : tick.bid;
   request.sl = StringToDouble(JsonValue(json, "stop_loss"));
   request.tp = StringToDouble(JsonValue(json, "take_profit"));
   request.deviation = (ulong)StringToInteger(JsonValue(json, "max_price_drift_points"));
   request.magic = W15_DEMO_MAGIC;
   request.comment = JsonValue(json, "comment_tag");
   request.type_time = ORDER_TIME_GTC;
   request.type_filling = DemoFillingMode(symbol);
   if(!OrderCheck(request, check) ||
      (check.retcode != TRADE_RETCODE_DONE && check.retcode != TRADE_RETCODE_PLACED))
   {
      reason = "DEMO_ORDER_CHECK_REJECTED_" + IntegerToString((int)check.retcode);
      return false;
   }
   reason = "DEMO_ORDER_CHECK_PASSED";
   return true;
}

//+------------------------------------------------------------------+
bool ExecuteDemoCommand(DemoExecutionState &state)
{
   string json = state.command_json;
   MqlTradeRequest request = {};
   MqlTradeCheckResult check = {};
   MqlTradeResult result = {};
   string preflight_reason = "";
   if(!BuildCheckedDemoRequest(json, request, check, preflight_reason))
      return SendDemoReport(state, "PREFLIGHT_REJECTED", "DEMO_INITIAL_PREFLIGHT_REJECTED",
                            preflight_reason);

   if(!SendDemoReport(state, "SUBMITTING", "DEMO_ORDER_CHECK_PASSED",
                      "durable submit boundary established"))
      return false;

   // The SUBMITTING acknowledgement is blocking network I/O. Rebuild from a
   // fresh tick and re-run every mutable account/market check and OrderCheck
   // immediately before the irreversible local submit marker.
   if(!BuildCheckedDemoRequest(json, request, check, preflight_reason))
      return SendDemoReport(state, "PREFLIGHT_REJECTED", "DEMO_FINAL_PREFLIGHT_REJECTED",
                            preflight_reason);

   // This durable write is the point of no return. Recovery never invokes
   // OrderSend again once submit_attempted=true, regardless of ambiguity.
   state.submit_attempted = true;
   state.phase = "SUBMITTING_PERSISTED";
   string persistence_error = "";
   if(!SaveDemoState(state, persistence_error))
   {
      g_demo_blocked = true;
      return false;
   }
   AppendLedger(state.command_id, "PERSIST_BEFORE_ORDERSEND", "ATTEMPT_1_OF_1");
   bool sent = OrderSend(request, result);
   state.order_ticket = result.order;
   state.deal_ticket = result.deal;
   state.phase = sent ? "BROKER_RESPONSE_RECEIVED" : "BROKER_RESPONSE_FAILED";
   if(!SaveDemoState(state, persistence_error))
   {
      g_demo_blocked = true;
      return false;
   }
   if(sent && result.deal > 0)
   {
      if(result.volume <= 0.0 || result.price <= 0.0)
         return SendDemoReport(state, "AMBIGUOUS_REQUIRES_RECONCILIATION",
                               "DEMO_DEAL_EVIDENCE_INCOMPLETE", result.comment,
                               0.0, 0.0, result.retcode);
      if(result.volume < request.volume - 0.0000001)
         return SendDemoReport(state, "AMBIGUOUS_REQUIRES_RECONCILIATION",
                               "DEMO_ONE_ORDER_PARTIAL_REQUIRES_RECONCILIATION",
                               result.comment, result.volume, result.price, result.retcode);
      if(MathAbs(result.volume - request.volume) <= 0.0000001)
         return SendDemoReport(state, "AMBIGUOUS_REQUIRES_RECONCILIATION",
                               "DEMO_ONE_ORDER_FILL_REQUIRES_HISTORY_RECONCILIATION",
                               result.comment, result.volume, result.price, result.retcode);
      return SendDemoReport(state, "AMBIGUOUS_REQUIRES_RECONCILIATION",
                            "DEMO_FILL_VOLUME_EXCEEDS_COMMAND", result.comment,
                            0.0, 0.0, result.retcode);
   }
   if(sent && result.order > 0)
      return SendDemoReport(state, "BROKER_ACCEPTED", "DEMO_ONE_ORDER_ACCEPTED",
                            result.comment, 0.0, 0.0, result.retcode);
   if(result.retcode == TRADE_RETCODE_REJECT || result.retcode == TRADE_RETCODE_INVALID ||
      result.retcode == TRADE_RETCODE_INVALID_VOLUME || result.retcode == TRADE_RETCODE_INVALID_STOPS ||
      result.retcode == TRADE_RETCODE_TRADE_DISABLED || result.retcode == TRADE_RETCODE_MARKET_CLOSED)
      return SendDemoReport(state, "BROKER_REJECTED", "DEMO_BROKER_REJECTED",
                            result.comment, 0.0, 0.0, result.retcode);
   return SendDemoReport(state, "AMBIGUOUS_REQUIRES_RECONCILIATION",
                         "DEMO_SUBMIT_AMBIGUOUS", result.comment,
                         0.0, 0.0, result.retcode);
}

//+------------------------------------------------------------------+
void PollOneDemoCommand()
{
   string response;
   int code = HttpRequest("GET", "/api/v1/executors/" + InpExecutorId + "/commands/next",
                          "", "", response);
   if(code == 204)
      return;
   if(code != 200)
      return;
   string command_id = JsonValue(response, "command_id");
   if(StringLen(command_id) == 0 || command_id == g_last_command_id || DemoStateExists())
      return;
   string claim_response;
   int claim_code = HttpRequest("POST", "/api/v1/commands/" + command_id + "/claim",
                                "{\"lease_seconds\":30}", "", claim_response);
   if(claim_code != 200)
      return;
   string claim_token = JsonValue(claim_response, "claim_token");
   string request_hash = JsonValue(claim_response, "request_hash");
   string command_json = "";
   string reason = "";
   if(!VerifySignedEnvelope(claim_response, command_id, request_hash, command_json, reason))
   {
      g_quarantined_command_id = command_id;
      AppendLedger(command_id, "QUARANTINED", reason);
      return;
   }
   if(!ValidateDemoCommand(command_json, reason))
   {
      DemoExecutionState rejected;
      ResetDemoState(rejected);
      rejected.executor_id = InpExecutorId;
      rejected.account_id = InpExpectedAccountId;
      rejected.command_id = command_id;
      rejected.idempotency_key = JsonValue(command_json, "idempotency_key");
      rejected.request_hash = request_hash;
      rejected.claim_token = claim_token;
      rejected.command_json = command_json;
      rejected.phase = "VALIDATION_REJECTED";
      string storage_error = "";
      if(SaveDemoState(rejected, storage_error))
         SendDemoReport(rejected, "VALIDATION_REJECTED", reason, "signed command failed DEMO validation");
      else
         g_demo_blocked = true;
      return;
   }
   DemoExecutionState state;
   ResetDemoState(state);
   state.executor_id = InpExecutorId;
   state.account_id = InpExpectedAccountId;
   state.command_id = command_id;
   state.idempotency_key = JsonValue(command_json, "idempotency_key");
   state.request_hash = request_hash;
   state.claim_token = claim_token;
   state.command_json = command_json;
   state.phase = "VALIDATED";
   string storage_error = "";
   if(!SaveDemoState(state, storage_error))
   {
      g_demo_blocked = true;
      return;
   }
   ExecuteDemoCommand(state);
}

//+------------------------------------------------------------------+
bool RecoverDemoState()
{
   DemoExecutionState state;
   string reason = "";
   if(!LoadDemoState(state, reason))
   {
      g_demo_blocked = true;
      AppendLedger("-", "RECOVERY_BLOCKED", reason);
      return false;
   }
   if(StringLen(state.command_id) == 0)
      return true;
   string status_response;
   int status_code = HttpRequest(
      "GET", "/api/v1/executors/" + InpExecutorId + "/commands/" + state.command_id + "/status",
      "", "", status_response);
   if(status_code != 200 || JsonValue(status_response, "request_hash") != state.request_hash)
   {
      g_demo_blocked = true;
      AppendLedger(state.command_id, "RECOVERY_BLOCKED", "STATUS_UNAVAILABLE_OR_HASH_MISMATCH");
      return false;
   }
   if(JsonBool(status_response, "terminal"))
   {
      AppendLedger(state.command_id, "RECOVERY_TERMINAL_CONFIRMED", JsonValue(status_response, "command_state"));
      g_last_command_id = state.command_id;
      return ClearDemoState();
   }
   if(state.pending_report_id != "-")
      return PostPreparedDemoReport(state);
   if(!state.submit_attempted)
      return SendDemoReport(state, "PREFLIGHT_REJECTED", "DEMO_RESTART_BEFORE_SUBMIT",
                            "durable state proves OrderSend was not attempted");

   // submit_attempted=true is permanently one-way. Never call OrderSend from
   // recovery; reconcile exact broker artifacts first.
   double filled_volume = 0.0;
   double filled_price = 0.0;
   if(!ReconcileDemoBrokerState(state, filled_volume, filled_price, reason))
   {
      g_demo_blocked = true;
      AppendLedger(state.command_id, "RECOVERY_BLOCKED", reason);
      return false;
   }
   string command_state = JsonValue(status_response, "command_state");
   double requested_volume = StringToDouble(JsonValue(state.command_json, "volume"));
   if(state.deal_ticket > 0 && filled_volume > 0.0 && filled_price > 0.0)
   {
      if(MathAbs(filled_volume - requested_volume) > 0.0000001)
      {
         if(command_state != "AMBIGUOUS")
         {
            if(!SendDemoReport(state, "AMBIGUOUS_REQUIRES_RECONCILIATION",
                               "DEMO_RESTART_PARTIAL_REQUIRES_OPERATOR_RECONCILIATION",
                               reason, filled_volume, filled_price))
               return false;
         }
         AppendLedger(state.command_id, "RECOVERY_BLOCKED",
                      "DEMO_PARTIAL_FILL_REQUIRES_OPERATOR_RECONCILIATION");
         g_demo_blocked = true;
         return false;
      }
      if(state.order_ticket == 0 || state.position_id == 0)
      {
         if(command_state == "AMBIGUOUS")
            return true;
         return SendDemoReport(state, "AMBIGUOUS_REQUIRES_RECONCILIATION",
                               "DEMO_RESTART_FILL_LINEAGE_INCOMPLETE",
                               reason, filled_volume, filled_price);
      }
      return SendDemoReport(state, "FILLED", "DEMO_RESTART_DEAL_RECONCILED",
                            reason, filled_volume, filled_price);
   }
   if(state.deal_ticket > 0 || state.position_id > 0)
   {
      if(command_state == "AMBIGUOUS")
         return true;
      return SendDemoReport(state, "AMBIGUOUS_REQUIRES_RECONCILIATION",
                            "DEMO_RESTART_BROKER_LINEAGE_INCOMPLETE", reason);
   }
   if(state.order_ticket > 0)
   {
      if(command_state == "BROKER_ACCEPTED" || command_state == "AMBIGUOUS")
         return true;
      return SendDemoReport(state, "AMBIGUOUS_REQUIRES_RECONCILIATION",
                            "DEMO_RESTART_ORDER_WITHOUT_RETCODE", reason);
   }
   if(command_state == "AMBIGUOUS")
      return true;
   return SendDemoReport(state, "AMBIGUOUS_REQUIRES_RECONCILIATION",
                         "DEMO_RESTART_SUBMIT_AMBIGUOUS", reason);
}

//+------------------------------------------------------------------+
int OnInit()
{
   if(!InpDemoExecutionArmed || InpLegacyShadowExecutionDisabled ||
      AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO)
   {
      Print("[W15-D0] Dedicated DEMO build requires explicit arm and a broker DEMO account.");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(InpApprovedCanonicalSymbol == "" || InpApprovedBrokerSymbol == "" ||
      SymbolPairIndex(InpApprovedCanonicalSymbol, InpApprovedBrokerSymbol) < 0)
      return INIT_PARAMETERS_INCORRECT;
   if(StringFind(InpBaseUrl, "https://") != 0 || StringLen(InpExecutorId) < 30 ||
      StringLen(InpExecutorToken) < 32 || StringLen(InpLoginHash) != 71)
      return INIT_PARAMETERS_INCORRECT;
   uchar verification_key[];
   if(!IsSafeWireIdentifier(InpCommandVerificationKeyId) ||
      !TaggedHexToBytes(InpCommandVerificationKey, "hex:", 32, verification_key) ||
      !RunSignedWireCryptoSelfTest())
      return INIT_FAILED;
   if((string)AccountInfoInteger(ACCOUNT_LOGIN) != InpExpectedAccountId ||
      AccountInfoString(ACCOUNT_SERVER) != InpExpectedBrokerServer)
      return INIT_FAILED;
   string universe_reason = "";
   if(!InitializeSymbolUniverse(universe_reason))
      return INIT_FAILED;
   FolderCreate("Wolf15ExecutorDemo", 0);
   FolderCreate("Wolf15ExecutorDemo", FILE_COMMON);
   DemoExecutionState state;
   string state_error = "";
   if(!LoadDemoState(state, state_error))
   {
      PrintFormat("[W15-D0] Durable state rejected reason=%s", state_error);
      return INIT_FAILED;
   }
   EventSetTimer(1);
   AppendLedger("-", "STARTED", "DEMO_ONLY_MAX_ONE_ORDERSEND");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnTimer()
{
   datetime now = TimeCurrent();
   if(!g_demo_registered)
   {
      g_demo_registered = RegisterDemoExecutor();
      return;
   }
   if(now - g_demo_last_heartbeat >= InpHeartbeatSeconds)
   {
      SendDemoHeartbeat();
      g_demo_last_heartbeat = now;
   }
   if(g_demo_blocked)
      return;
   if(DemoStateExists())
   {
      if(now - g_demo_last_recovery >= InpRecoveryRetrySeconds || g_trade_event_pending)
      {
         RecoverDemoState();
         g_demo_last_recovery = now;
         g_trade_event_pending = false;
      }
      return;
   }
   if(now - g_demo_last_poll >= InpPollIntervalSeconds)
   {
      PollOneDemoCommand();
      g_demo_last_poll = now;
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   // No analysis, direction, sizing, risk, trailing, or strategy logic.
}

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(request.magic != W15_DEMO_MAGIC && !DemoStateExists())
      return;
   AppendLedger("-", "TRADE_TRANSACTION_OBSERVED",
                StringFormat("type=%d order=%I64u deal=%I64u retcode=%u",
                             (int)trans.type, trans.order, trans.deal, result.retcode));
   g_trade_event_pending = true;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   AppendLedger("-", "STOPPED", IntegerToString(reason));
}
