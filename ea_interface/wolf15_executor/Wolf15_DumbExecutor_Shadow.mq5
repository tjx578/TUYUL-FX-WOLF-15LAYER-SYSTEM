//+------------------------------------------------------------------+
//| Wolf15 Dumb Executor - SHADOW transport and validation scaffold  |
//| No signal logic. No risk calculation. No broker side effect.     |
//+------------------------------------------------------------------+
#property strict
#property version   "1.12"
#property description "Wolf15 pull/claim/report client. SHADOW ONLY."

input string InpBaseUrl             = "https://replace-me.up.railway.app";
input string InpExecutorId          = "";
input string InpExecutorToken       = "";
input string InpCommandVerificationKeyId = "";
input string InpCommandVerificationKey   = "";
input string InpExpectedAccountId   = "";
input string InpLoginHash           = "";
input string InpExpectedBrokerServer= "";
input string InpCanonicalSymbol     = "EURUSD";
input string InpBrokerSymbol        = "EURUSD";
input int    InpMagic               = 150015;
input int    InpPollIntervalSeconds = 2;
input int    InpHeartbeatSeconds    = 10;
input int    InpHttpTimeoutMs       = 1500;
input bool   InpExecutionEnabled    = false;

#define W15_PROTOCOL "wolf15.mt5.exec.v1"
#define W15_VERSION  "0.12-shadow-signed-wire"
#define W15_SIGNED_WIRE "wolf15.mt5.exec.signed-bytes.v2"
#define W15_SIGNED_DOMAIN "WOLF15-MT5-COMMAND-V2"
#define W15_STRATEGY "STRATEGY_5S_CR_FINAL"
#define W15_CONFIRMATION_POLICY "H1_CLOSED_PLUS_M15_BREAK_ACCEPTANCE_OR_FAILED_RECLAIM_RETEST"
#define W15_GOLDEN_EXECUTOR_ID "12345678-1234-5678-9234-567812345678"
#define W15_GOLDEN_KEY_ID "exec-test-2026-08.v2"
#define W15_GOLDEN_KEY_HEX "c6f28f7e3e483b947780d0f1d9a3e50ab10976facb989c582d353457cae282d7"
#define W15_GOLDEN_PAYLOAD_B64 "eyJhcnJheSI6WzEuMCwxZS0wNywwLjMwMDAwMDAwMDAwMDAwMDA0XSwidW5pY29kZSI6Ilx1MjBhYyJ9"
#define W15_GOLDEN_PAYLOAD_SHA256 "sha256:18ed07b452adbec6fc29ec9fd6d347dc342216de60a24d009828a4fa69aaca7a"
#define W15_GOLDEN_SIGNATURE "base64url:TYmshMY5I9eQhq7Qyi-UlIl7Q0j4e3ZfkribNBwxKIg"

datetime g_last_poll = 0;
datetime g_last_heartbeat = 0;
bool     g_registered = false;
string   g_last_command_id = "";
string   g_quarantined_command_id = "";

//+------------------------------------------------------------------+
string EscapeJson(const string value)
{
   string out = value;
   StringReplace(out, "\\", "\\\\");
   StringReplace(out, "\"", "\\\"");
   StringReplace(out, "\r", "\\r");
   StringReplace(out, "\n", "\\n");
   return out;
}

//+------------------------------------------------------------------+
string UtcTimestamp()
{
   MqlDateTime part;
   TimeToStruct(TimeGMT(), part);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ",
                       part.year, part.mon, part.day,
                       part.hour, part.min, part.sec);
}

//+------------------------------------------------------------------+
datetime ParseUtc(const string value)
{
   if(StringLen(value) < 20)
      return 0;
   MqlDateTime part;
   part.year = (int)StringToInteger(StringSubstr(value, 0, 4));
   part.mon  = (int)StringToInteger(StringSubstr(value, 5, 2));
   part.day  = (int)StringToInteger(StringSubstr(value, 8, 2));
   part.hour = (int)StringToInteger(StringSubstr(value, 11, 2));
   part.min  = (int)StringToInteger(StringSubstr(value, 14, 2));
   part.sec  = (int)StringToInteger(StringSubstr(value, 17, 2));
   return StructToTime(part);
}

//+------------------------------------------------------------------+
string MakeUuid()
{
   MathSrand((int)(GetTickCount() ^ (uint)AccountInfoInteger(ACCOUNT_LOGIN)));
   string hex = "0123456789abcdef";
   string out = "";
   for(int index = 0; index < 32; index++)
   {
      if(index == 8 || index == 12 || index == 16 || index == 20)
         out += "-";
      int digit = MathRand() % 16;
      if(index == 12)
         digit = 4;
      if(index == 16)
         digit = (digit & 3) | 8;
      out += StringSubstr(hex, digit, 1);
   }
   return out;
}

//+------------------------------------------------------------------+
string JsonValue(const string json, const string key, const string fallback = "")
{
   string marker = "\"" + key + "\"";
   int pos = StringFind(json, marker);
   if(pos < 0)
      return fallback;
   pos = StringFind(json, ":", pos + StringLen(marker));
   if(pos < 0)
      return fallback;
   pos++;
   while(pos < StringLen(json) &&
         (StringGetCharacter(json, pos) == ' ' || StringGetCharacter(json, pos) == '\n'))
      pos++;
   if(pos >= StringLen(json))
      return fallback;

   if(StringGetCharacter(json, pos) == '"')
   {
      pos++;
      string out = "";
      bool escaped = false;
      for(int index = pos; index < StringLen(json); index++)
      {
         ushort ch = StringGetCharacter(json, index);
         if(escaped)
         {
            out += ShortToString(ch);
            escaped = false;
         }
         else if(ch == '\\')
            escaped = true;
         else if(ch == '"')
            return out;
         else
            out += ShortToString(ch);
      }
      return fallback;
   }

   int end = pos;
   while(end < StringLen(json))
   {
      ushort ch = StringGetCharacter(json, end);
      if(ch == ',' || ch == '}' || ch == ']' || ch == '\r' || ch == '\n')
         break;
      end++;
   }
   string out = StringSubstr(json, pos, end - pos);
   StringTrimLeft(out);
   StringTrimRight(out);
   return out;
}

//+------------------------------------------------------------------+
bool JsonBool(const string json, const string key)
{
   string value = JsonValue(json, key, "false");
   return (value == "true" || value == "1");
}

//+------------------------------------------------------------------+
string JsonObject(const string json, const string key)
{
   string marker = "\"" + key + "\"";
   int pos = StringFind(json, marker);
   if(pos < 0)
      return "";
   pos = StringFind(json, ":", pos + StringLen(marker));
   if(pos < 0)
      return "";
   pos++;
   while(pos < StringLen(json) &&
         (StringGetCharacter(json, pos) == ' ' ||
          StringGetCharacter(json, pos) == '\r' ||
          StringGetCharacter(json, pos) == '\n' ||
          StringGetCharacter(json, pos) == '\t'))
      pos++;
   if(pos >= StringLen(json) || StringGetCharacter(json, pos) != '{')
      return "";

   int depth = 0;
   bool in_string = false;
   bool escaped = false;
   for(int index = pos; index < StringLen(json); index++)
   {
      ushort ch = StringGetCharacter(json, index);
      if(in_string)
      {
         if(escaped)
            escaped = false;
         else if(ch == '\\')
            escaped = true;
         else if(ch == '"')
            in_string = false;
         continue;
      }
      if(ch == '"')
      {
         in_string = true;
         continue;
      }
      if(ch == '{')
         depth++;
      else if(ch == '}')
      {
         depth--;
         if(depth == 0)
            return StringSubstr(json, pos, index - pos + 1);
         if(depth < 0)
            return "";
      }
   }
   return "";
}

//+------------------------------------------------------------------+
bool AsciiToBytes(const string value, uchar &result[])
{
   ArrayResize(result, 0);
   for(int index = 0; index < StringLen(value); index++)
   {
      if(StringGetCharacter(value, index) > 127)
         return false;
   }
   int copied = StringToCharArray(value, result, 0, WHOLE_ARRAY, CP_UTF8);
   if(copied <= 0)
      return (StringLen(value) == 0);
   if(ArraySize(result) > 0 && result[ArraySize(result) - 1] == 0)
      ArrayResize(result, ArraySize(result) - 1);
   return (ArraySize(result) == StringLen(value));
}

//+------------------------------------------------------------------+
int HexNibble(const ushort ch)
{
   if(ch >= '0' && ch <= '9')
      return (int)(ch - '0');
   if(ch >= 'a' && ch <= 'f')
      return (int)(ch - 'a' + 10);
   if(ch >= 'A' && ch <= 'F')
      return (int)(ch - 'A' + 10);
   return -1;
}

//+------------------------------------------------------------------+
bool HexToBytes(const string hex, uchar &result[])
{
   int length = StringLen(hex);
   if(length == 0 || (length % 2) != 0)
      return false;
   ArrayResize(result, length / 2);
   for(int index = 0; index < length; index += 2)
   {
      int high = HexNibble(StringGetCharacter(hex, index));
      int low = HexNibble(StringGetCharacter(hex, index + 1));
      if(high < 0 || low < 0)
      {
         ArrayResize(result, 0);
         return false;
      }
      result[index / 2] = (uchar)((high << 4) | low);
   }
   return true;
}

//+------------------------------------------------------------------+
bool TaggedHexToBytes(const string value,
                      const string prefix,
                      const int expected_size,
                      uchar &result[])
{
   if(StringFind(value, prefix) != 0 || !HexToBytes(StringSubstr(value, StringLen(prefix)), result))
      return false;
   return (ArraySize(result) == expected_size);
}

//+------------------------------------------------------------------+
bool Base64UrlToBytes(const string value, uchar &result[])
{
   int length = StringLen(value);
   if(length == 0 || (length % 4) == 1)
      return false;
   for(int index = 0; index < length; index++)
   {
      ushort ch = StringGetCharacter(value, index);
      bool valid = ((ch >= 'A' && ch <= 'Z') ||
                    (ch >= 'a' && ch <= 'z') ||
                    (ch >= '0' && ch <= '9') || ch == '-' || ch == '_');
      if(!valid)
         return false;
   }
   string encoded = value;
   StringReplace(encoded, "-", "+");
   StringReplace(encoded, "_", "/");
   while((StringLen(encoded) % 4) != 0)
      encoded += "=";

   uchar encoded_bytes[];
   uchar empty_key[];
   if(!AsciiToBytes(encoded, encoded_bytes))
      return false;
   ResetLastError();
   int decoded = CryptDecode(CRYPT_BASE64, encoded_bytes, empty_key, result);
   if(decoded <= 0)
   {
      ArrayResize(result, 0);
      return false;
   }
   ArrayResize(result, decoded);
   return true;
}

//+------------------------------------------------------------------+
bool Sha256Bytes(const uchar &data[], uchar &digest[])
{
   uchar empty_key[];
   ResetLastError();
   int produced = CryptEncode(CRYPT_HASH_SHA256, data, empty_key, digest);
   if(produced != 32)
   {
      ArrayResize(digest, 0);
      return false;
   }
   ArrayResize(digest, produced);
   return true;
}

//+------------------------------------------------------------------+
bool HmacSha256Bytes(const uchar &key[], const uchar &message[], uchar &digest[])
{
   if(ArraySize(key) != 32)
      return false;

   uchar inner_pad[];
   uchar outer_pad[];
   ArrayResize(inner_pad, 64);
   ArrayResize(outer_pad, 64);
   for(int index = 0; index < 64; index++)
   {
      uchar key_byte = (index < ArraySize(key)) ? key[index] : (uchar)0;
      inner_pad[index] = (uchar)(key_byte ^ 0x36);
      outer_pad[index] = (uchar)(key_byte ^ 0x5c);
   }

   uchar inner_source[];
   ArrayResize(inner_source, 64 + ArraySize(message));
   for(int index = 0; index < 64; index++)
      inner_source[index] = inner_pad[index];
   for(int index = 0; index < ArraySize(message); index++)
      inner_source[64 + index] = message[index];

   uchar inner_digest[];
   if(!Sha256Bytes(inner_source, inner_digest))
      return false;

   uchar outer_source[];
   ArrayResize(outer_source, 64 + ArraySize(inner_digest));
   for(int index = 0; index < 64; index++)
      outer_source[index] = outer_pad[index];
   for(int index = 0; index < ArraySize(inner_digest); index++)
      outer_source[64 + index] = inner_digest[index];
   return Sha256Bytes(outer_source, digest);
}

//+------------------------------------------------------------------+
bool ConstantTimeBytesEqual(const uchar &left[], const uchar &right[])
{
   if(ArraySize(left) != ArraySize(right))
      return false;
   uint difference = 0;
   for(int index = 0; index < ArraySize(left); index++)
      difference |= (uint)(left[index] ^ right[index]);
   return (difference == 0);
}

//+------------------------------------------------------------------+
bool IsSafeWireIdentifier(const string value)
{
   int length = StringLen(value);
   if(length < 1 || length > 100)
      return false;
   for(int index = 0; index < length; index++)
   {
      ushort ch = StringGetCharacter(value, index);
      bool valid = ((ch >= 'A' && ch <= 'Z') ||
                    (ch >= 'a' && ch <= 'z') ||
                    (ch >= '0' && ch <= '9') ||
                    ch == '.' || ch == '_' || ch == ':' || ch == '-');
      if(!valid)
         return false;
   }
   return true;
}

//+------------------------------------------------------------------+
string SignedEnvelopePreimage(const string key_id,
                              const string executor_id,
                              const string payload_sha256,
                              const string payload_b64)
{
   return W15_SIGNED_DOMAIN + "\n" +
          "key_id=" + key_id + "\n" +
          "executor_id=" + executor_id + "\n" +
          "payload_sha256=" + payload_sha256 + "\n" +
          "payload_b64=" + payload_b64;
}

//+------------------------------------------------------------------+
bool RunSignedWireCryptoSelfTest()
{
   uchar key[];
   uchar payload[];
   uchar expected_payload_hash[];
   uchar actual_payload_hash[];
   uchar expected_signature[];
   uchar actual_signature[];
   uchar preimage_bytes[];
   if(!HexToBytes(W15_GOLDEN_KEY_HEX, key) || ArraySize(key) != 32)
      return false;
   if(!Base64UrlToBytes(W15_GOLDEN_PAYLOAD_B64, payload))
      return false;
   if(!TaggedHexToBytes(W15_GOLDEN_PAYLOAD_SHA256, "sha256:", 32, expected_payload_hash))
      return false;
   if(!Sha256Bytes(payload, actual_payload_hash) ||
      !ConstantTimeBytesEqual(expected_payload_hash, actual_payload_hash))
      return false;
   if(StringFind(W15_GOLDEN_SIGNATURE, "base64url:") != 0 ||
      !Base64UrlToBytes(StringSubstr(W15_GOLDEN_SIGNATURE, 10), expected_signature) ||
      ArraySize(expected_signature) != 32)
      return false;

   string preimage = SignedEnvelopePreimage(
      W15_GOLDEN_KEY_ID,
      W15_GOLDEN_EXECUTOR_ID,
      W15_GOLDEN_PAYLOAD_SHA256,
      W15_GOLDEN_PAYLOAD_B64
   );
   if(!AsciiToBytes(preimage, preimage_bytes) ||
      !HmacSha256Bytes(key, preimage_bytes, actual_signature) ||
      !ConstantTimeBytesEqual(expected_signature, actual_signature))
      return false;

   uchar tampered_bytes[];
   uchar tampered_signature[];
   if(!AsciiToBytes(preimage + "x", tampered_bytes) ||
      !HmacSha256Bytes(key, tampered_bytes, tampered_signature))
      return false;
   return !ConstantTimeBytesEqual(expected_signature, tampered_signature);
}

//+------------------------------------------------------------------+
bool VerifySignedEnvelope(const string response_json,
                          const string expected_command_id,
                          const string request_hash,
                          string &command_json,
                          string &reason)
{
   command_json = "";
   string envelope = JsonObject(response_json, "signed_envelope");
   if(StringLen(envelope) == 0)
   {
      reason = "SIGNED_ENVELOPE_MISSING";
      return false;
   }

   string wire_version = JsonValue(envelope, "wire_version");
   string payload_encoding = JsonValue(envelope, "payload_encoding");
   string payload_b64 = JsonValue(envelope, "payload_b64");
   string payload_sha256 = JsonValue(envelope, "payload_sha256");
   string algorithm = JsonValue(envelope, "algorithm");
   string key_id = JsonValue(envelope, "key_id");
   string executor_id = JsonValue(envelope, "executor_id");
   string signature = JsonValue(envelope, "signature");

   if(wire_version != W15_SIGNED_WIRE || payload_encoding != "base64url" ||
      algorithm != "HMAC-SHA256")
   {
      reason = "SIGNED_WIRE_VERSION_REJECTED";
      return false;
   }
   if(key_id != InpCommandVerificationKeyId || !IsSafeWireIdentifier(key_id))
   {
      reason = "SIGNED_WIRE_KEY_ID_REJECTED";
      return false;
   }
   if(executor_id != InpExecutorId)
   {
      reason = "SIGNED_WIRE_EXECUTOR_REJECTED";
      return false;
   }
   if(StringLen(payload_b64) < 1 || StringLen(payload_b64) > 262144 ||
      StringLen(payload_sha256) != 71 || StringLen(signature) != 53 ||
      request_hash != payload_sha256)
   {
      reason = "SIGNED_WIRE_SHAPE_REJECTED";
      return false;
   }

   uchar verification_key[];
   uchar signature_bytes[];
   uchar preimage_bytes[];
   uchar calculated_signature[];
   if(!TaggedHexToBytes(InpCommandVerificationKey, "hex:", 32, verification_key) ||
      StringFind(signature, "base64url:") != 0 ||
      !Base64UrlToBytes(StringSubstr(signature, 10), signature_bytes) ||
      ArraySize(signature_bytes) != 32)
   {
      reason = "SIGNED_WIRE_SIGNATURE_MALFORMED";
      return false;
   }
   string preimage = SignedEnvelopePreimage(key_id, executor_id, payload_sha256, payload_b64);
   if(!AsciiToBytes(preimage, preimage_bytes) ||
      !HmacSha256Bytes(verification_key, preimage_bytes, calculated_signature) ||
      !ConstantTimeBytesEqual(signature_bytes, calculated_signature))
   {
      reason = "SIGNED_WIRE_SIGNATURE_INVALID";
      return false;
   }

   uchar payload_bytes[];
   uchar expected_payload_hash[];
   uchar calculated_payload_hash[];
   if(!Base64UrlToBytes(payload_b64, payload_bytes))
   {
      reason = "SIGNED_WIRE_PAYLOAD_DECODE_FAILED";
      return false;
   }
   if(!TaggedHexToBytes(payload_sha256, "sha256:", 32, expected_payload_hash) ||
      !Sha256Bytes(payload_bytes, calculated_payload_hash) ||
      !ConstantTimeBytesEqual(expected_payload_hash, calculated_payload_hash))
   {
      reason = "SIGNED_WIRE_PAYLOAD_HASH_MISMATCH";
      return false;
   }

   command_json = CharArrayToString(payload_bytes, 0, ArraySize(payload_bytes), CP_UTF8);
   if(JsonValue(command_json, "command_id") != expected_command_id)
   {
      reason = "SIGNED_WIRE_COMMAND_ID_MISMATCH";
      command_json = "";
      return false;
   }
   if(JsonValue(command_json, "executor_id") != InpExecutorId)
   {
      reason = "SIGNED_WIRE_COMMAND_BINDING_MISMATCH";
      command_json = "";
      return false;
   }
   reason = "SIGNED_WIRE_VERIFIED";
   return true;
}

//+------------------------------------------------------------------+
int HttpRequest(const string method,
                const string endpoint,
                const string body,
                const string claim_token,
                string &response)
{
   string headers = "Content-Type: application/json\r\n"
                    "Authorization: Bearer " + InpExecutorToken + "\r\n"
                    "X-Executor-Id: " + InpExecutorId + "\r\n"
                    "X-Request-Id: " + MakeUuid() + "\r\n";
   if(StringLen(claim_token) > 0)
      headers += "X-Claim-Token: " + claim_token + "\r\n";

   char request_data[];
   char response_data[];
   string response_headers;
   if(StringLen(body) > 0)
      StringToCharArray(body, request_data, 0, StringLen(body), CP_UTF8);
   ResetLastError();
   int code = WebRequest(method, InpBaseUrl + endpoint, headers,
                         InpHttpTimeoutMs, request_data,
                         response_data, response_headers);
   if(code < 0)
   {
      PrintFormat("[W15] HTTP transport error=%d endpoint=%s", GetLastError(), endpoint);
      response = "";
      return code;
   }
   response = CharArrayToString(response_data, 0, ArraySize(response_data), CP_UTF8);
   return code;
}

//+------------------------------------------------------------------+
void AppendLedger(const string command_id, const string state, const string detail)
{
   int handle = FileOpen("Wolf15Executor\\shadow-ledger.csv",
                         FILE_READ | FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_SHARE_READ,
                         ';');
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("[W15] Local ledger open failed error=%d", GetLastError());
      return;
   }
   FileSeek(handle, 0, SEEK_END);
   FileWrite(handle, UtcTimestamp(), command_id, state, detail);
   FileFlush(handle);
   FileClose(handle);
}

//+------------------------------------------------------------------+
string MarginModeName()
{
   long mode = AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   if(mode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
      return "HEDGING";
   return "NETTING";
}

//+------------------------------------------------------------------+
string BuildPositionsJson()
{
   string out = "[";
   int written = 0;
   for(int index = 0; index < PositionsTotal(); index++)
   {
      ulong ticket = PositionGetTicket(index);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if(written > 0)
         out += ",";
      string side = ((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      out += StringFormat(
         "{\"position_id\":%I64u,\"symbol\":\"%s\",\"side\":\"%s\","
         "\"volume\":%.8f,\"entry_price\":%.10f,\"current_price\":%.10f,"
         "\"stop_loss\":%s,\"take_profit\":%s,\"magic\":%I64d,"
         "\"comment\":\"%s\",\"floating_pnl\":%.2f}",
         ticket,
         EscapeJson(PositionGetString(POSITION_SYMBOL)),
         side,
         PositionGetDouble(POSITION_VOLUME),
         PositionGetDouble(POSITION_PRICE_OPEN),
         PositionGetDouble(POSITION_PRICE_CURRENT),
         PositionGetDouble(POSITION_SL) > 0 ? DoubleToString(PositionGetDouble(POSITION_SL), 10) : "null",
         PositionGetDouble(POSITION_TP) > 0 ? DoubleToString(PositionGetDouble(POSITION_TP), 10) : "null",
         PositionGetInteger(POSITION_MAGIC),
         EscapeJson(PositionGetString(POSITION_COMMENT)),
         PositionGetDouble(POSITION_PROFIT));
      written++;
   }
   out += "]";
   return out;
}

//+------------------------------------------------------------------+
string BuildSymbolsJson()
{
   if(!SymbolSelect(InpBrokerSymbol, true))
      return "[]";
   return StringFormat(
      "[{\"canonical_symbol\":\"%s\",\"broker_symbol\":\"%s\","
      "\"digits\":%d,\"point\":%.10f,\"tick_size\":%.10f,"
      "\"tick_value_profit\":%.8f,\"tick_value_loss\":%.8f,"
      "\"volume_min\":%.8f,\"volume_max\":%.8f,\"volume_step\":%.8f,"
      "\"stops_level_points\":%d,\"freeze_level_points\":%d,"
      "\"expiration_modes\":[\"SPECIFIED\"]}]",
      EscapeJson(InpCanonicalSymbol), EscapeJson(InpBrokerSymbol),
      (int)SymbolInfoInteger(InpBrokerSymbol, SYMBOL_DIGITS),
      SymbolInfoDouble(InpBrokerSymbol, SYMBOL_POINT),
      SymbolInfoDouble(InpBrokerSymbol, SYMBOL_TRADE_TICK_SIZE),
      SymbolInfoDouble(InpBrokerSymbol, SYMBOL_TRADE_TICK_VALUE_PROFIT),
      SymbolInfoDouble(InpBrokerSymbol, SYMBOL_TRADE_TICK_VALUE_LOSS),
      SymbolInfoDouble(InpBrokerSymbol, SYMBOL_VOLUME_MIN),
      SymbolInfoDouble(InpBrokerSymbol, SYMBOL_VOLUME_MAX),
      SymbolInfoDouble(InpBrokerSymbol, SYMBOL_VOLUME_STEP),
      (int)SymbolInfoInteger(InpBrokerSymbol, SYMBOL_TRADE_STOPS_LEVEL),
      (int)SymbolInfoInteger(InpBrokerSymbol, SYMBOL_TRADE_FREEZE_LEVEL));
}

//+------------------------------------------------------------------+
bool RegisterExecutor()
{
   string body = StringFormat(
      "{\"protocol_version\":\"%s\",\"executor_id\":\"%s\","
      "\"account_id\":\"%s\",\"login_hash\":\"%s\","
      "\"broker_server\":\"%s\",\"terminal_build\":%d,"
      "\"ea_version\":\"%s\",\"requested_mode\":\"SHADOW\"}",
      W15_PROTOCOL, InpExecutorId, EscapeJson(InpExpectedAccountId),
      InpLoginHash, EscapeJson(InpExpectedBrokerServer),
      (int)TerminalInfoInteger(TERMINAL_BUILD), W15_VERSION);
   string response;
   int code = HttpRequest("POST", "/api/v1/executors/register", body, "", response);
   if(code != 200 && code != 201)
   {
      PrintFormat("[W15] Registration rejected code=%d response=%s", code, response);
      return false;
   }
   if(JsonValue(response, "execution_mode") != "SHADOW")
   {
      Print("[W15] Registration did not return SHADOW. Refusing to run.");
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
bool SendHeartbeat()
{
   string snapshot_id = "snap-" + MakeUuid();
   string captured = UtcTimestamp();
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double floating = equity - balance;
   string margin_level = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL) > 0
                         ? DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_LEVEL), 4)
                         : "null";
   bool trade_allowed = (bool)AccountInfoInteger(ACCOUNT_TRADE_ALLOWED);
   bool auto_enabled = (bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED);
   string bool_trade = trade_allowed ? "true" : "false";
   string bool_auto = auto_enabled ? "true" : "false";

   string snapshot = StringFormat(
      "{\"snapshot_id\":\"%s\",\"captured_at_utc\":\"%s\","
      "\"executor_id\":\"%s\",\"account_id\":\"%s\",\"currency\":\"%s\","
      "\"balance\":%.2f,\"equity\":%.2f,\"floating_pnl\":%.2f,"
      "\"used_margin\":%.2f,\"free_margin\":%.2f,\"margin_level_pct\":%s,"
      "\"margin_mode\":\"%s\",\"trade_allowed\":%s,\"autotrading_enabled\":%s,"
      "\"open_positions\":%s,\"symbols\":%s}",
      snapshot_id, captured, InpExecutorId, EscapeJson(InpExpectedAccountId),
      EscapeJson(AccountInfoString(ACCOUNT_CURRENCY)), balance, equity, floating,
      AccountInfoDouble(ACCOUNT_MARGIN), AccountInfoDouble(ACCOUNT_MARGIN_FREE),
      margin_level, MarginModeName(), bool_trade, bool_auto,
      BuildPositionsJson(), BuildSymbolsJson());
   string body = StringFormat(
      "{\"protocol_version\":\"%s\",\"executor_id\":\"%s\","
      "\"sent_at_utc\":\"%s\",\"terminal_connected\":%s,"
      "\"trade_allowed\":%s,\"autotrading_enabled\":%s,"
      "\"account_snapshot\":%s}",
      W15_PROTOCOL, InpExecutorId, captured,
      (bool)TerminalInfoInteger(TERMINAL_CONNECTED) ? "true" : "false",
      bool_trade, bool_auto, snapshot);
   string response;
   int code = HttpRequest("POST", "/api/v1/executors/" + InpExecutorId + "/heartbeat",
                          body, "", response);
   return (code >= 200 && code <= 299);
}

//+------------------------------------------------------------------+
bool IsStepCompatible(const double value, const double step)
{
   if(step <= 0)
      return false;
   double units = value / step;
   return (MathAbs(units - MathRound(units)) <= 0.0000001);
}

//+------------------------------------------------------------------+
bool ValidateShadowCommand(const string json, string &reason)
{
   if(JsonValue(json, "protocol_version") != W15_PROTOCOL)
   {
      reason = "PROTOCOL_MISMATCH";
      return false;
   }
   if(JsonValue(json, "execution_mode") != "SHADOW" || InpExecutionEnabled)
   {
      reason = "SHADOW_ONLY_BUILD";
      return false;
   }
   if(JsonValue(json, "source_event") != "signal_json" ||
      !JsonBool(json, "valid_for_execution") ||
      !JsonBool(json, "execution_gate_passed") ||
      !JsonBool(json, "tradeplan_valid"))
   {
      reason = "SOURCE_GATE_REJECTED";
      return false;
   }
   if(JsonValue(json, "strategy_model") != W15_STRATEGY ||
      JsonValue(json, "strategy_rule_status") != "FROZEN" ||
      JsonValue(json, "context_resolution_status") != "RESOLVED" ||
      JsonValue(json, "confirmation_policy") != W15_CONFIRMATION_POLICY)
   {
      reason = "STRATEGY_5SCR_SOURCE_PROOF_REJECTED";
      return false;
   }
   if(JsonValue(json, "account_id") != InpExpectedAccountId ||
      JsonValue(json, "broker_server") != InpExpectedBrokerServer)
   {
      reason = "ACCOUNT_BINDING_MISMATCH";
      return false;
   }
   if(JsonValue(json, "broker_symbol") != InpBrokerSymbol ||
      JsonValue(json, "canonical_symbol") != InpCanonicalSymbol)
   {
      reason = "SYMBOL_BINDING_MISMATCH";
      return false;
   }
   datetime expiry = ParseUtc(JsonValue(json, "expires_at_utc"));
   if(expiry <= 0 || TimeGMT() >= expiry)
   {
      reason = "COMMAND_EXPIRED";
      return false;
   }
   string action = JsonValue(json, "action");
   if(action != "PLACE_MARKET" && action != "PLACE_PENDING")
   {
      reason = "ACTION_NOT_IMPLEMENTED_IN_SHADOW_SCAFFOLD";
      return false;
   }

   double entry = StringToDouble(JsonValue(json, "entry_price"));
   double stop = StringToDouble(JsonValue(json, "stop_loss"));
   double target = StringToDouble(JsonValue(json, "take_profit"));
   double volume = StringToDouble(JsonValue(json, "volume"));
   string side = JsonValue(json, "side");
   if((side == "BUY" && !(stop < entry && entry < target)) ||
      (side == "SELL" && !(target < entry && entry < stop)))
   {
      reason = "PRICE_RELATION_INVALID";
      return false;
   }
   double min_volume = SymbolInfoDouble(InpBrokerSymbol, SYMBOL_VOLUME_MIN);
   double max_volume = SymbolInfoDouble(InpBrokerSymbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(InpBrokerSymbol, SYMBOL_VOLUME_STEP);
   if(volume < min_volume || volume > max_volume || !IsStepCompatible(volume, step))
   {
      reason = "VOLUME_NOT_EXACTLY_REPRESENTABLE";
      return false;
   }
   reason = "SHADOW_PREFLIGHT_PASSED_SIGNATURE_VERIFIED";
   return true;
}

//+------------------------------------------------------------------+
bool SendShadowReport(const string command_json,
                      const string claim_token,
                      const string request_hash,
                      const bool accepted,
                      const string reason)
{
   string command_id = JsonValue(command_json, "command_id");
   string idempotency_key = JsonValue(command_json, "idempotency_key");
   string state = accepted ? "WOULD_EXECUTE" : "WOULD_REJECT";
   string reason_code = accepted ? "SHADOW_PREFLIGHT_PASSED" : reason;
   double volume = StringToDouble(JsonValue(command_json, "volume"));
   double entry = StringToDouble(JsonValue(command_json, "entry_price"));
   double stop = StringToDouble(JsonValue(command_json, "stop_loss"));
   double target = StringToDouble(JsonValue(command_json, "take_profit"));
   string report_id = MakeUuid();
   string body = StringFormat(
      "{\"event\":\"execution_report\",\"protocol_version\":\"%s\","
      "\"report_id\":\"%s\",\"command_id\":\"%s\","
      "\"idempotency_key\":\"%s\",\"sequence\":1,\"state\":\"%s\","
      "\"event_time_utc\":\"%s\",\"executor_id\":\"%s\","
      "\"account_id\":\"%s\",\"request_hash\":\"%s\","
      "\"broker\":{},\"execution\":{\"requested_volume\":%.8f,"
      "\"filled_volume\":0,\"requested_price\":%.10f,\"filled_price\":null,"
      "\"stop_loss\":%.10f,\"take_profit\":%.10f,\"observed_spread_points\":null},"
      "\"reason_code\":\"%s\",\"reason_detail\":\"%s\"}",
      W15_PROTOCOL, report_id, command_id, EscapeJson(idempotency_key), state,
      UtcTimestamp(), InpExecutorId, EscapeJson(InpExpectedAccountId), request_hash,
      volume, entry, stop, target, reason_code, EscapeJson(reason));

   AppendLedger(command_id, state, reason);
   string response;
   int code = HttpRequest("POST", "/api/v1/commands/" + command_id + "/reports",
                          body, claim_token, response);
   return (code >= 200 && code <= 299);
}

//+------------------------------------------------------------------+
void PollOneCommand()
{
   string response;
   int code = HttpRequest("GET", "/api/v1/executors/" + InpExecutorId + "/commands/next",
                          "", "", response);
   if(code == 204)
      return;
   if(code != 200)
   {
      PrintFormat("[W15] Command poll failed code=%d", code);
      return;
   }
   string command_id = JsonValue(response, "command_id");
   if(StringLen(command_id) == 0 ||
      command_id == g_last_command_id ||
      command_id == g_quarantined_command_id)
      return;

   string claim_response;
   int claim_code = HttpRequest("POST", "/api/v1/commands/" + command_id + "/claim",
                                "{\"lease_seconds\":30}", "", claim_response);
   if(claim_code != 200)
      return;
   string claim_token = JsonValue(claim_response, "claim_token");
   string request_hash = JsonValue(claim_response, "request_hash");
   if(StringLen(claim_token) == 0 || StringLen(request_hash) == 0)
      return;

   string command_json = "";
   string reason = "";
   if(!VerifySignedEnvelope(claim_response, command_id, request_hash, command_json, reason))
   {
      g_quarantined_command_id = command_id;
      AppendLedger(command_id, "QUARANTINED", reason);
      PrintFormat("[W15] Command quarantined reason=%s", reason);
      return;
   }

   bool accepted = ValidateShadowCommand(command_json, reason);
   if(SendShadowReport(command_json, claim_token, request_hash, accepted, reason))
      g_last_command_id = command_id;
}

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpExecutionEnabled)
   {
      Print("[W15] This build is SHADOW ONLY. Set InpExecutionEnabled=false.");
      return INIT_PARAMETERS_INCORRECT;
   }
   const bool https_endpoint = (StringFind(InpBaseUrl, "https://") == 0);
   const int executor_id_length = StringLen(InpExecutorId);
   const int executor_token_length = StringLen(InpExecutorToken);
   const int verification_key_id_length = StringLen(InpCommandVerificationKeyId);
   const int verification_key_length = StringLen(InpCommandVerificationKey);
   const int login_hash_length = StringLen(InpLoginHash);
   uchar verification_key[];
   if(!https_endpoint ||
      executor_id_length < 30 ||
      executor_token_length < 32 ||
      !IsSafeWireIdentifier(InpCommandVerificationKeyId) ||
      !TaggedHexToBytes(InpCommandVerificationKey, "hex:", 32, verification_key) ||
      login_hash_length != 71)
   {
      PrintFormat(
         "[W15] Invalid endpoint/credential shape: https=%s "
         "executor_id_length=%d token_length=%d verification_key_id_length=%d "
         "verification_key_length=%d login_hash_length=%d",
         https_endpoint ? "true" : "false",
         executor_id_length,
         executor_token_length,
         verification_key_id_length,
         verification_key_length,
         login_hash_length
      );
      return INIT_PARAMETERS_INCORRECT;
   }
   if(!RunSignedWireCryptoSelfTest())
   {
      Print("[W15] Signed-wire cryptographic self-test failed.");
      return INIT_FAILED;
   }
   const string actual_account_id = (string)AccountInfoInteger(ACCOUNT_LOGIN);
   if(actual_account_id != InpExpectedAccountId)
   {
      Print("[W15] MT5 account binding mismatch.");
      return INIT_FAILED;
   }
   if(AccountInfoString(ACCOUNT_SERVER) != InpExpectedBrokerServer)
   {
      Print("[W15] Broker server binding mismatch.");
      return INIT_FAILED;
   }
   FolderCreate("Wolf15Executor", FILE_COMMON);
   EventSetTimer(1);
   Print("[W15] Shadow executor initialized with signed-wire verification. No broker side effects are compiled in.");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnTimer()
{
   datetime now = TimeCurrent();
   if(!g_registered)
   {
      g_registered = RegisterExecutor();
      return;
   }
   if(now - g_last_heartbeat >= InpHeartbeatSeconds)
   {
      SendHeartbeat();
      g_last_heartbeat = now;
   }
   if(now - g_last_poll >= InpPollIntervalSeconds)
   {
      PollOneCommand();
      g_last_poll = now;
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   // Deliberately empty: no analysis, management, trailing, or risk logic.
}

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   // Shadow scaffold observes no broker side effects and performs no network I/O here.
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   AppendLedger("-", "STOPPED", IntegerToString(reason));
}
