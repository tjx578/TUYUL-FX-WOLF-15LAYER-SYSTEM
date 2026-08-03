//+------------------------------------------------------------------+
//| Wolf15 Dumb Executor - SHADOW transport and validation scaffold  |
//| No signal logic. No risk calculation. No broker side effect.     |
//+------------------------------------------------------------------+
#property strict
#property version   "1.22"
#property description "Wolf15 pull/claim/report client. SHADOW ONLY."

input string InpBaseUrl             = "https://replace-me.up.railway.app";
input string InpExecutorId          = "";
input string InpExecutorToken       = "";
input string InpCommandVerificationKeyId = "";
input string InpCommandVerificationKey   = "";
input string InpExpectedAccountId   = "";
input string InpLoginHash           = "";
input string InpExpectedBrokerServer= "";
input int    InpMagic               = 150015;
input int    InpPollIntervalSeconds = 2;
input int    InpHeartbeatSeconds    = 10;
input int    InpHttpTimeoutMs       = 1500;
input int    InpRecoveryRetrySeconds= 5;
input bool   InpExecutionEnabled    = false;
input bool   InpRestartDrillHoldAfterDurableSave = false;

#define W15_PROTOCOL "wolf15.mt5.exec.v1"
#define W15_VERSION  "0.22-shadow-acceptance-v1"
#define W15_SIGNED_WIRE "wolf15.mt5.exec.signed-bytes.v2"
#define W15_SIGNED_DOMAIN "WOLF15-MT5-COMMAND-V2"
#define W15_PENDING_MAGIC "WOLF15-PENDING-REPORT-V2"
#define W15_STRATEGY "STRATEGY_5S_CR_FINAL"
#define W15_CONFIRMATION_POLICY "H1_CLOSED_PLUS_M15_BREAK_ACCEPTANCE_OR_FAILED_RECLAIM_RETEST"
#define W15_ACCEPTANCE_SCHEMA "wolf15.mt5.shadow-acceptance.v1"
#define W15_ACCEPTANCE_AUTHORITY "WOLF15_SHADOW_ACCEPTANCE_OPERATOR_V1"
#define W15_ACCEPTANCE_PURPOSE "BROKER_CONNECTED_SHADOW_VALIDATION"
#define W15_GOLDEN_EXECUTOR_ID "12345678-1234-5678-9234-567812345678"
#define W15_GOLDEN_KEY_ID "exec-test-2026-08.v2"
#define W15_GOLDEN_KEY_HEX "c6f28f7e3e483b947780d0f1d9a3e50ab10976facb989c582d353457cae282d7"
#define W15_GOLDEN_PAYLOAD_B64 "eyJhcnJheSI6WzEuMCwxZS0wNywwLjMwMDAwMDAwMDAwMDAwMDA0XSwidW5pY29kZSI6Ilx1MjBhYyJ9"
#define W15_GOLDEN_PAYLOAD_SHA256 "sha256:18ed07b452adbec6fc29ec9fd6d347dc342216de60a24d009828a4fa69aaca7a"
#define W15_GOLDEN_SIGNATURE "base64url:TYmshMY5I9eQhq7Qyi-UlIl7Q0j4e3ZfkribNBwxKIg"
#define W15_SYMBOL_COUNT 30
#define W15_SYMBOL_UNIVERSE "WOLF15_XM_30_V1"

string W15_CANONICAL_SYMBOLS[W15_SYMBOL_COUNT] =
{
   "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
   "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
   "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
   "AUDJPY", "AUDNZD", "AUDCAD", "AUDCHF",
   "NZDJPY", "NZDCHF", "NZDCAD",
   "CADJPY", "CADCHF", "CHFJPY", "XAUUSD", "XAGUSD"
};

string W15_BROKER_SYMBOLS[W15_SYMBOL_COUNT] =
{
   "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
   "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
   "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
   "AUDJPY", "AUDNZD", "AUDCAD", "AUDCHF",
   "NZDJPY", "NZDCHF", "NZDCAD",
   "CADJPY", "CADCHF", "CHFJPY", "GOLD", "SILVER"
};

datetime g_last_poll = 0;
datetime g_last_heartbeat = 0;
bool     g_registered = false;
string   g_last_command_id = "";
string   g_quarantined_command_id = "";
datetime g_last_recovery = 0;
bool     g_recovery_blocked = false;

struct PendingReportState
{
   string executor_id;
   string account_id;
   string command_id;
   string report_id;
   string request_hash;
   string claim_token;
   string report_body;
   string integrity_tag;
};

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
string BytesToHex(const uchar &value[])
{
   string result = "";
   for(int index = 0; index < ArraySize(value); index++)
      result += StringFormat("%02x", (uint)value[index]);
   return result;
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
bool IsSafeAsciiToken(const string value,
                      const int minimum_length,
                      const int maximum_length)
{
   int length = StringLen(value);
   if(length < minimum_length || length > maximum_length)
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
bool IsSafeWireIdentifier(const string value)
{
   return IsSafeAsciiToken(value, 1, 100);
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
//| Diagnostics helpers.                                             |
//|                                                                  |
//| These exist to explain transport failures without ever printing   |
//| anything that could authenticate a request or reveal an order.    |
//| Nothing here changes claim, report or recovery behaviour.         |
//+------------------------------------------------------------------+

//| Strip control characters and cap length before printing a value   |
//| that arrived from the network.                                    |
string SafeLogValue(const string value, const int max_length = 120)
{
   string out = "";
   int limit = MathMin(StringLen(value), max_length);
   for(int index = 0; index < limit; index++)
   {
      ushort character = StringGetCharacter(value, index);
      bool unsafe_control = (character < 32 || character == 127 || character == 0x0085 ||
                             character == 0x2028 || character == 0x2029 ||
                             (character >= 0x202A && character <= 0x202E) ||
                             (character >= 0x2066 && character <= 0x2069));
      out += unsafe_control ? " " : ShortToString(character);
   }
   if(StringLen(value) > max_length)
      out += "...";
   return out;
}

//| Read one response header by name. Only whitelisted names are ever  |
//| requested by the caller; the full header block is never printed.   |
string ResponseHeaderValue(const string response_headers, const string name)
{
   string lines[];
   int count = StringSplit(response_headers, StringGetCharacter("\n", 0), lines);
   string wanted = name;
   StringToLower(wanted);
   for(int index = 0; index < count; index++)
   {
      string line = lines[index];
      StringTrimLeft(line);
      StringTrimRight(line);
      int separator = StringFind(line, ":");
      if(separator <= 0)
         continue;
      string key = StringSubstr(line, 0, separator);
      StringTrimLeft(key);
      StringTrimRight(key);
      StringToLower(key);
      if(key != wanted)
         continue;
      string value = StringSubstr(line, separator + 1);
      StringTrimLeft(value);
      StringTrimRight(value);
      return SafeLogValue(value);
   }
   return "";
}

//| Classify what WebRequest actually returned.                       |
//| MQL5 documents the return as an HTTP status code, or -1 on error;  |
//| anything else is outside the documented contract and is the case   |
//| we most need named rather than guessed at.                        |
string WebRequestOutcome(const int code)
{
   if(code == -1)
      return "WEBREQUEST_TRANSPORT_ERROR";
   if(code >= 100 && code <= 599)
      return "HTTP_RESPONSE";
   return "WEBREQUEST_NON_HTTP_RETURN";
}

//| Shape of the body, never its content: enough to tell a proxy or    |
//| challenge page from an API response without logging either.        |
void ClassifyResponseShape(const uchar &payload[],
                           string &digest_hex,
                           bool &looks_like_html,
                           bool &looks_like_json)
{
   digest_hex = "";
   looks_like_html = false;
   looks_like_json = false;
   int size = ArraySize(payload);
   if(size <= 0)
      return;

   uchar digest[];
   if(Sha256Bytes(payload, digest))
      digest_hex = BytesToHex(digest);

   int index = 0;
   while(index < size && (payload[index] == ' ' || payload[index] == '\t' ||
                          payload[index] == '\r' || payload[index] == '\n' ||
                          payload[index] == 0xEF || payload[index] == 0xBB || payload[index] == 0xBF))
      index++;
   if(index >= size)
      return;

   uchar first = payload[index];
   looks_like_json = (first == '{' || first == '[');
   looks_like_html = (first == '<');
}

//+------------------------------------------------------------------+
int HttpRequest(const string method,
                const string endpoint,
                const string body,
                const string claim_token,
                string &response)
{
   string request_id = MakeUuid();
   string headers = "Content-Type: application/json\r\n"
                    "Authorization: Bearer " + InpExecutorToken + "\r\n"
                    "X-Executor-Id: " + InpExecutorId + "\r\n"
                    "X-Request-Id: " + request_id + "\r\n";
   if(StringLen(claim_token) > 0)
      headers += "X-Claim-Token: " + claim_token + "\r\n";

   char request_data[];
   char response_data[];
   string response_headers;
   if(StringLen(body) > 0)
      StringToCharArray(body, request_data, 0, StringLen(body), CP_UTF8);

   ResetLastError();
   uint started_ms = GetTickCount();
   int code = WebRequest(method, InpBaseUrl + endpoint, headers,
                         InpHttpTimeoutMs, request_data,
                         response_data, response_headers);
   int last_error = GetLastError();
   uint elapsed_ms = GetTickCount() - started_ms;
   string outcome = WebRequestOutcome(code);

   if(code == -1)
   {
      PrintFormat("[W15] HTTP transport error outcome=%s method=%s endpoint=%s code=%d "
                  "last_error=%d elapsed_ms=%u request_id=%s",
                  outcome, method, endpoint, code, last_error, elapsed_ms, request_id);
      response = "";
      return code;
   }

   if(outcome == "WEBREQUEST_NON_HTTP_RETURN")
   {
      PrintFormat("[W15] WebRequest non-HTTP return outcome=%s method=%s endpoint=%s code=%d "
                  "last_error=%d elapsed_ms=%u request_id=%s",
                  outcome, method, endpoint, code, last_error, elapsed_ms, request_id);
      response = "";
      return code;
   }

   int response_bytes = ArraySize(response_data);
   response = CharArrayToString(response_data, 0, response_bytes, CP_UTF8);

   // Silence on the healthy path: successes stay as quiet as before, so this
   // patch adds diagnosis without adding noise to a working poll loop.
   if(outcome == "HTTP_RESPONSE" && (code == 200 || code == 201 || code == 204))
      return code;

   string digest_hex;
   bool looks_like_html = false;
   bool looks_like_json = false;
   uchar payload[];
   ArrayResize(payload, response_bytes);
   for(int index = 0; index < response_bytes; index++)
      payload[index] = (uchar)response_data[index];
   ClassifyResponseShape(payload, digest_hex, looks_like_html, looks_like_json);

   PrintFormat("[W15] HTTP anomaly outcome=%s method=%s endpoint=%s code=%d last_error=%d "
               "elapsed_ms=%u response_bytes=%d response_sha256=%s looks_like_html=%s "
               "looks_like_json=%s content_type=%s server=%s date=%s retry_after=%s "
               "cf_ray=%s response_request_id=%s request_id=%s",
               outcome, method, endpoint, code, last_error, elapsed_ms, response_bytes,
               digest_hex, looks_like_html ? "true" : "false",
               looks_like_json ? "true" : "false",
               ResponseHeaderValue(response_headers, "Content-Type"),
               ResponseHeaderValue(response_headers, "Server"),
               ResponseHeaderValue(response_headers, "Date"),
               ResponseHeaderValue(response_headers, "Retry-After"),
               ResponseHeaderValue(response_headers, "CF-Ray"),
               ResponseHeaderValue(response_headers, "X-Request-Id"),
               request_id);
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
string PendingReportPath()
{
   return "Wolf15Executor\\pending-report-" + InpExecutorId + ".bin";
}

//+------------------------------------------------------------------+
string PendingReportTempPath()
{
   return PendingReportPath() + ".tmp";
}

//+------------------------------------------------------------------+
void ResetPendingReport(PendingReportState &pending)
{
   pending.executor_id = "";
   pending.account_id = "";
   pending.command_id = "";
   pending.report_id = "";
   pending.request_hash = "";
   pending.claim_token = "";
   pending.report_body = "";
   pending.integrity_tag = "";
}

//+------------------------------------------------------------------+
bool PendingReportExists()
{
   return (FileIsExist(PendingReportPath(), 0) ||
           FileIsExist(PendingReportTempPath(), 0));
}

//+------------------------------------------------------------------+
bool WriteSizedAscii(const int handle, const string value, const int maximum_length)
{
   int length = StringLen(value);
   uchar ascii[];
   if(length < 1 || length > maximum_length || !AsciiToBytes(value, ascii))
      return false;
   if(FileWriteInteger(handle, length, INT_VALUE) != 4)
      return false;
   return (FileWriteString(handle, value, length) == (uint)length);
}

//+------------------------------------------------------------------+
bool ReadSizedAscii(const int handle,
                    const int maximum_length,
                    string &value)
{
   int length = FileReadInteger(handle, INT_VALUE);
   if(length < 1 || length > maximum_length)
      return false;
   value = FileReadString(handle, length);
   if(StringLen(value) != length)
      return false;
   uchar ascii[];
   return AsciiToBytes(value, ascii);
}

//+------------------------------------------------------------------+
bool ComputePendingIntegrityTag(const PendingReportState &pending,
                                string &integrity_tag)
{
   uchar verification_key[];
   uchar material_bytes[];
   uchar digest[];
   string material = W15_PENDING_MAGIC + "\n" +
                     "executor_id=" + pending.executor_id + "\n" +
                     "account_id=" + pending.account_id + "\n" +
                     "command_id=" + pending.command_id + "\n" +
                     "report_id=" + pending.report_id + "\n" +
                     "request_hash=" + pending.request_hash + "\n" +
                     "claim_token=" + pending.claim_token + "\n" +
                     "report_body=" + pending.report_body;
   if(!TaggedHexToBytes(InpCommandVerificationKey,
                        "hex:",
                        32,
                        verification_key) ||
      !AsciiToBytes(material, material_bytes) ||
      !HmacSha256Bytes(verification_key, material_bytes, digest))
      return false;
   integrity_tag = "hmac-sha256:" + BytesToHex(digest);
   return true;
}

//+------------------------------------------------------------------+
bool ValidatePendingReportState(const PendingReportState &pending,
                                string &error)
{
   uchar request_digest[];
   uchar report_bytes[];
   uchar stored_integrity[];
   uchar expected_integrity[];
   if(pending.executor_id != InpExecutorId ||
      pending.account_id != InpExpectedAccountId)
   {
      error = "PENDING_REPORT_BINDING_MISMATCH";
      return false;
   }
   if(StringLen(pending.command_id) != 36 ||
      StringLen(pending.report_id) != 36 ||
      !IsSafeWireIdentifier(pending.command_id) ||
      !IsSafeWireIdentifier(pending.report_id) ||
      !TaggedHexToBytes(pending.request_hash, "sha256:", 32, request_digest) ||
      !IsSafeAsciiToken(pending.claim_token, 32, 512))
   {
      error = "PENDING_REPORT_SHAPE_INVALID";
      return false;
   }
   if(StringLen(pending.report_body) > 131072 ||
      !AsciiToBytes(pending.report_body, report_bytes))
   {
      error = "PENDING_REPORT_BODY_INVALID";
      return false;
   }
   if(JsonValue(pending.report_body, "protocol_version") != W15_PROTOCOL ||
      JsonValue(pending.report_body, "report_id") != pending.report_id ||
      JsonValue(pending.report_body, "command_id") != pending.command_id ||
      JsonValue(pending.report_body, "executor_id") != pending.executor_id ||
      JsonValue(pending.report_body, "account_id") != pending.account_id ||
      JsonValue(pending.report_body, "request_hash") != pending.request_hash ||
      JsonValue(pending.report_body, "sequence") != "1" ||
      JsonValue(pending.report_body, "filled_volume") != "0")
   {
      error = "PENDING_REPORT_CONTENT_MISMATCH";
      return false;
   }
   string state = JsonValue(pending.report_body, "state");
   if(state != "WOULD_EXECUTE" && state != "WOULD_REJECT")
   {
      error = "PENDING_REPORT_STATE_INVALID";
      return false;
   }
   string expected_integrity_tag = "";
   if(!ComputePendingIntegrityTag(pending, expected_integrity_tag) ||
      !TaggedHexToBytes(pending.integrity_tag,
                        "hmac-sha256:",
                        32,
                        stored_integrity) ||
      !TaggedHexToBytes(expected_integrity_tag,
                        "hmac-sha256:",
                        32,
                        expected_integrity) ||
      !ConstantTimeBytesEqual(stored_integrity, expected_integrity))
   {
      error = "PENDING_REPORT_INTEGRITY_INVALID";
      return false;
   }
   error = "";
   return true;
}

//+------------------------------------------------------------------+
bool SavePendingReport(PendingReportState &pending, string &error)
{
   if(!ComputePendingIntegrityTag(pending, pending.integrity_tag))
   {
      error = "PENDING_REPORT_INTEGRITY_FAILED";
      return false;
   }
   if(!ValidatePendingReportState(pending, error))
      return false;
   string temporary_path = PendingReportTempPath();
   int handle = FileOpen(temporary_path,
                         FILE_WRITE | FILE_BIN | FILE_ANSI,
                         0,
                         CP_UTF8);
   if(handle == INVALID_HANDLE)
   {
      error = "PENDING_REPORT_TEMP_OPEN_FAILED";
      return false;
   }
   bool written = (
      WriteSizedAscii(handle, W15_PENDING_MAGIC, 64) &&
      WriteSizedAscii(handle, pending.executor_id, 100) &&
      WriteSizedAscii(handle, pending.account_id, 100) &&
      WriteSizedAscii(handle, pending.command_id, 100) &&
      WriteSizedAscii(handle, pending.report_id, 100) &&
      WriteSizedAscii(handle, pending.request_hash, 100) &&
      WriteSizedAscii(handle, pending.claim_token, 512) &&
      WriteSizedAscii(handle, pending.report_body, 131072) &&
      WriteSizedAscii(handle, pending.integrity_tag, 100)
   );
   FileFlush(handle);
   FileClose(handle);
   if(!written)
   {
      error = "PENDING_REPORT_TEMP_WRITE_FAILED";
      return false;
   }
   ResetLastError();
   if(!FileMove(temporary_path, 0, PendingReportPath(), FILE_REWRITE))
   {
      error = "PENDING_REPORT_ATOMIC_RENAME_FAILED";
      return false;
   }
   error = "";
   return true;
}

//+------------------------------------------------------------------+
bool LoadPendingReport(PendingReportState &pending, string &error)
{
   ResetPendingReport(pending);
   string path = PendingReportPath();
   string temporary_path = PendingReportTempPath();
   if(!FileIsExist(path, 0) && FileIsExist(temporary_path, 0))
   {
      ResetLastError();
      if(!FileMove(temporary_path, 0, path, FILE_REWRITE))
      {
         error = "PENDING_REPORT_TEMP_RECOVERY_FAILED";
         return false;
      }
   }
   if(!FileIsExist(path, 0))
   {
      error = "";
      return true;
   }

   int handle = FileOpen(path, FILE_READ | FILE_BIN | FILE_ANSI, 0, CP_UTF8);
   if(handle == INVALID_HANDLE)
   {
      error = "PENDING_REPORT_OPEN_FAILED";
      return false;
   }
   string magic = "";
   bool read = (
      ReadSizedAscii(handle, 64, magic) &&
      ReadSizedAscii(handle, 100, pending.executor_id) &&
      ReadSizedAscii(handle, 100, pending.account_id) &&
      ReadSizedAscii(handle, 100, pending.command_id) &&
      ReadSizedAscii(handle, 100, pending.report_id) &&
      ReadSizedAscii(handle, 100, pending.request_hash) &&
      ReadSizedAscii(handle, 512, pending.claim_token) &&
      ReadSizedAscii(handle, 131072, pending.report_body) &&
      ReadSizedAscii(handle, 100, pending.integrity_tag)
   );
   bool exact_size = (FileTell(handle) == FileSize(handle));
   FileClose(handle);
   if(!read || !exact_size || magic != W15_PENDING_MAGIC)
   {
      error = "PENDING_REPORT_FILE_CORRUPT";
      return false;
   }
   return ValidatePendingReportState(pending, error);
}

//+------------------------------------------------------------------+
bool ClearPendingReport()
{
   bool cleared = true;
   if(FileIsExist(PendingReportPath(), 0) &&
      !FileDelete(PendingReportPath(), 0))
      cleared = false;
   if(FileIsExist(PendingReportTempPath(), 0) &&
      !FileDelete(PendingReportTempPath(), 0))
      cleared = false;
   return cleared;
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
int SymbolPairIndex(const string canonical_symbol,
                    const string broker_symbol)
{
   for(int index = 0; index < W15_SYMBOL_COUNT; index++)
   {
      if(W15_CANONICAL_SYMBOLS[index] == canonical_symbol &&
         W15_BROKER_SYMBOLS[index] == broker_symbol)
      {
         return index;
      }
   }
   return -1;
}

//+------------------------------------------------------------------+
bool InitializeSymbolUniverse(string &reason)
{
   for(int index = 0; index < W15_SYMBOL_COUNT; index++)
   {
      for(int previous = 0; previous < index; previous++)
      {
         if(W15_CANONICAL_SYMBOLS[index] == W15_CANONICAL_SYMBOLS[previous] ||
            W15_BROKER_SYMBOLS[index] == W15_BROKER_SYMBOLS[previous])
         {
            reason = "SYMBOL_UNIVERSE_DUPLICATE";
            return false;
         }
      }
      string broker_symbol = W15_BROKER_SYMBOLS[index];
      if(!SymbolSelect(broker_symbol, true))
      {
         reason = "SYMBOL_SELECT_FAILED:" + broker_symbol;
         return false;
      }
      if((ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(
            broker_symbol, SYMBOL_TRADE_MODE) != SYMBOL_TRADE_MODE_FULL)
      {
         reason = "SYMBOL_NOT_FULL_TRADE_MODE:" + broker_symbol;
         return false;
      }
      if(SymbolInfoDouble(broker_symbol, SYMBOL_POINT) <= 0.0 ||
         SymbolInfoDouble(broker_symbol, SYMBOL_TRADE_TICK_SIZE) <= 0.0 ||
         SymbolInfoDouble(broker_symbol, SYMBOL_TRADE_TICK_VALUE_PROFIT) <= 0.0 ||
         SymbolInfoDouble(broker_symbol, SYMBOL_TRADE_TICK_VALUE_LOSS) <= 0.0 ||
         SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_MIN) <= 0.0 ||
         SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_STEP) <= 0.0)
      {
         reason = "SYMBOL_CAPABILITY_INVALID:" + broker_symbol;
         return false;
      }
   }

   for(int attempt = 0; attempt < 30; attempt++)
   {
      bool all_synchronized = true;
      for(int index = 0; index < W15_SYMBOL_COUNT; index++)
      {
         if(!SymbolIsSynchronized(W15_BROKER_SYMBOLS[index]))
         {
            all_synchronized = false;
            break;
         }
      }
      if(all_synchronized)
      {
         reason = "READY";
         return true;
      }
      Sleep(100);
   }
   reason = "SYMBOL_UNIVERSE_NOT_SYNCHRONIZED";
   return false;
}

//+------------------------------------------------------------------+
string BuildSymbolsJson()
{
   string out = "[";
   for(int index = 0; index < W15_SYMBOL_COUNT; index++)
   {
      string canonical_symbol = W15_CANONICAL_SYMBOLS[index];
      string broker_symbol = W15_BROKER_SYMBOLS[index];
      if(!SymbolSelect(broker_symbol, true) || !SymbolIsSynchronized(broker_symbol))
      {
         PrintFormat("[W15] Symbol capability unavailable symbol=%s", broker_symbol);
         return "";
      }
      if(index > 0)
         out += ",";
      out += StringFormat(
         "{\"canonical_symbol\":\"%s\",\"broker_symbol\":\"%s\","
         "\"digits\":%d,\"point\":%.10f,\"tick_size\":%.10f,"
         "\"tick_value_profit\":%.8f,\"tick_value_loss\":%.8f,"
         "\"volume_min\":%.8f,\"volume_max\":%.8f,\"volume_step\":%.8f,"
         "\"stops_level_points\":%d,\"freeze_level_points\":%d,"
         "\"expiration_modes\":[\"SPECIFIED\"]}",
         EscapeJson(canonical_symbol), EscapeJson(broker_symbol),
         (int)SymbolInfoInteger(broker_symbol, SYMBOL_DIGITS),
         SymbolInfoDouble(broker_symbol, SYMBOL_POINT),
         SymbolInfoDouble(broker_symbol, SYMBOL_TRADE_TICK_SIZE),
         SymbolInfoDouble(broker_symbol, SYMBOL_TRADE_TICK_VALUE_PROFIT),
         SymbolInfoDouble(broker_symbol, SYMBOL_TRADE_TICK_VALUE_LOSS),
         SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_MIN),
         SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_MAX),
         SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_STEP),
         (int)SymbolInfoInteger(broker_symbol, SYMBOL_TRADE_STOPS_LEVEL),
         (int)SymbolInfoInteger(broker_symbol, SYMBOL_TRADE_FREEZE_LEVEL));
   }
   out += "]";
   return out;
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
      PrintFormat("[W15] Registration rejected code=%d", code);
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

   string symbols_json = BuildSymbolsJson();
   if(StringLen(symbols_json) == 0)
      return false;
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
      BuildPositionsJson(), symbols_json);
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
bool ValidateShadowAcceptanceCommand(const string json, string &reason)
{
   if(JsonValue(json, "source_schema_version") != W15_ACCEPTANCE_SCHEMA ||
      JsonValue(json, "operator_authority") != W15_ACCEPTANCE_AUTHORITY ||
      JsonValue(json, "purpose") != W15_ACCEPTANCE_PURPOSE)
   {
      reason = "SHADOW_ACCEPTANCE_AUTHORITY_REJECTED";
      return false;
   }
   string phase = JsonValue(json, "phase");
   if((phase != "A1" && phase != "A2") ||
      !IsSafeAsciiToken(JsonValue(json, "acceptance_run_id"), 3, 64))
   {
      reason = "SHADOW_ACCEPTANCE_LINEAGE_REJECTED";
      return false;
   }
   if(JsonValue(json, "execution_authority", "missing") != "false" ||
      JsonValue(json, "broker_execution") != "FORBIDDEN" ||
      JsonValue(json, "guard_type") != "SHADOW_ACCEPTANCE" ||
      !JsonBool(json, "kill_switch_required") ||
      StringFind(json, "\"risk_reservation_id\"") >= 0 ||
      StringFind(json, "\"risk_snapshot_id\"") >= 0)
   {
      reason = "SHADOW_ACCEPTANCE_GUARD_REJECTED";
      return false;
   }
   if(JsonValue(json, "account_id") != InpExpectedAccountId ||
      JsonValue(json, "broker_server") != InpExpectedBrokerServer)
   {
      reason = "ACCOUNT_BINDING_MISMATCH";
      return false;
   }
   string broker_symbol = JsonValue(json, "broker_symbol");
   string canonical_symbol = JsonValue(json, "canonical_symbol");
   if(phase == "A1" && canonical_symbol != "EURUSD")
   {
      reason = "SHADOW_ACCEPTANCE_A1_SYMBOL_REJECTED";
      return false;
   }
   if(SymbolPairIndex(canonical_symbol, broker_symbol) < 0)
   {
      reason = "SYMBOL_BINDING_MISMATCH";
      return false;
   }
   if(!SymbolSelect(broker_symbol, true) || !SymbolIsSynchronized(broker_symbol) ||
      (ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(
         broker_symbol, SYMBOL_TRADE_MODE) != SYMBOL_TRADE_MODE_FULL)
   {
      reason = "SYMBOL_RUNTIME_NOT_READY";
      return false;
   }
   if(!IsSafeAsciiToken(JsonValue(json, "idempotency_key"), 8, 250))
   {
      reason = "IDEMPOTENCY_KEY_UNSAFE";
      return false;
   }
   datetime expiry = ParseUtc(JsonValue(json, "expires_at_utc"));
   if(expiry <= 0 || TimeGMT() >= expiry)
   {
      reason = "SHADOW_ACCEPTANCE_EXPIRED";
      return false;
   }
   if(JsonValue(json, "action") != "RECONCILE_ONLY" ||
      JsonValue(json, "order", "missing") != "null")
   {
      reason = "SHADOW_ACCEPTANCE_ACTION_REJECTED";
      return false;
   }
   reason = "SHADOW_ACCEPTANCE_VALIDATED_SIGNATURE_VERIFIED";
   return true;
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
   if(JsonValue(json, "source_event") == "SHADOW_ACCEPTANCE")
      return ValidateShadowAcceptanceCommand(json, reason);
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
   string broker_symbol = JsonValue(json, "broker_symbol");
   string canonical_symbol = JsonValue(json, "canonical_symbol");
   if(SymbolPairIndex(canonical_symbol, broker_symbol) < 0)
   {
      reason = "SYMBOL_BINDING_MISMATCH";
      return false;
   }
   if(!SymbolSelect(broker_symbol, true) || !SymbolIsSynchronized(broker_symbol) ||
      (ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(
         broker_symbol, SYMBOL_TRADE_MODE) != SYMBOL_TRADE_MODE_FULL)
   {
      reason = "SYMBOL_RUNTIME_NOT_READY";
      return false;
   }
   if(!IsSafeAsciiToken(JsonValue(json, "idempotency_key"), 8, 250))
   {
      reason = "IDEMPOTENCY_KEY_UNSAFE";
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
   double min_volume = SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_MIN);
   double max_volume = SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_STEP);
   if(volume < min_volume || volume > max_volume || !IsStepCompatible(volume, step))
   {
      reason = "VOLUME_NOT_EXACTLY_REPRESENTABLE";
      return false;
   }
   reason = "SHADOW_PREFLIGHT_PASSED_SIGNATURE_VERIFIED";
   return true;
}

//+------------------------------------------------------------------+
void BlockPendingRecovery(const string command_id, const string reason)
{
   g_recovery_blocked = true;
   AppendLedger(command_id, "PENDING_REPORT_BLOCKED", reason);
   PrintFormat("[W15] Pending report recovery blocked reason=%s", reason);
}

//+------------------------------------------------------------------+
int PostPendingReport(const PendingReportState &pending,
                      string &response)
{
   return HttpRequest("POST",
                      "/api/v1/commands/" + pending.command_id + "/reports",
                      pending.report_body,
                      pending.claim_token,
                      response);
}

//+------------------------------------------------------------------+
bool FinalizePendingReport(const PendingReportState &pending,
                           const string outcome)
{
   AppendLedger(pending.command_id, "REPORT_RECONCILED", outcome);
   if(!ClearPendingReport())
   {
      BlockPendingRecovery(pending.command_id, "PENDING_REPORT_CLEAR_FAILED");
      return false;
   }
   g_last_command_id = pending.command_id;
   return true;
}

//+------------------------------------------------------------------+
bool HandlePendingPostResult(const PendingReportState &pending,
                             const int code,
                             const string response)
{
   if(code >= 200 && code <= 299)
   {
      if(!JsonBool(response, "accepted") ||
         JsonValue(response, "command_id") != pending.command_id)
      {
         BlockPendingRecovery(pending.command_id, "PENDING_REPORT_ACK_INVALID");
         return false;
      }
      return FinalizePendingReport(pending, "REPORT_ACKNOWLEDGED");
   }
   if(code >= 400 && code <= 499 && code != 403 && code != 409)
      BlockPendingRecovery(pending.command_id,
                           "PENDING_REPORT_HTTP_" + IntegerToString(code));
   return false;
}

//+------------------------------------------------------------------+
bool ReclaimPendingReport(PendingReportState &pending)
{
   string claim_response;
   int code = HttpRequest("POST",
                          "/api/v1/commands/" + pending.command_id + "/claim",
                          "{\"lease_seconds\":30}",
                          "",
                          claim_response);
   if(code != 200)
      return false;

   string response_hash = JsonValue(claim_response, "request_hash");
   string new_claim_token = JsonValue(claim_response, "claim_token");
   string command_json = "";
   string reason = "";
   if(response_hash != pending.request_hash ||
      StringLen(new_claim_token) < 32 ||
      !VerifySignedEnvelope(claim_response,
                            pending.command_id,
                            pending.request_hash,
                            command_json,
                            reason) ||
      JsonValue(command_json, "idempotency_key") !=
         JsonValue(pending.report_body, "idempotency_key"))
   {
      BlockPendingRecovery(pending.command_id,
                           "PENDING_REPORT_RECLAIM_BINDING_FAILED");
      return false;
   }

   pending.claim_token = new_claim_token;
   if(!SavePendingReport(pending, reason))
   {
      BlockPendingRecovery(pending.command_id, reason);
      return false;
   }
   AppendLedger(pending.command_id, "PENDING_REPORT_RECLAIMED", "TOKEN_ROTATED_DURABLY");
   return true;
}

//+------------------------------------------------------------------+
bool RecoverPendingReport()
{
   PendingReportState pending;
   string error = "";
   if(!LoadPendingReport(pending, error))
   {
      BlockPendingRecovery("-", error);
      return false;
   }
   if(StringLen(pending.command_id) == 0)
      return true;

   string status_response;
   int status_code = HttpRequest(
      "GET",
      "/api/v1/executors/" + InpExecutorId +
         "/commands/" + pending.command_id + "/status",
      "",
      "",
      status_response
   );
   if(status_code != 200)
   {
      if(status_code >= 400 && status_code <= 499)
         BlockPendingRecovery(pending.command_id,
                              "PENDING_STATUS_HTTP_" + IntegerToString(status_code));
      return false;
   }
   if(JsonValue(status_response, "request_hash") != pending.request_hash)
   {
      BlockPendingRecovery(pending.command_id, "PENDING_STATUS_HASH_MISMATCH");
      return false;
   }
   if(JsonBool(status_response, "terminal"))
   {
      string latest_report = JsonObject(status_response, "latest_report");
      if(StringLen(latest_report) == 0 ||
         JsonValue(latest_report, "request_hash") != pending.request_hash)
      {
         BlockPendingRecovery(pending.command_id, "PENDING_STATUS_TERMINAL_AMBIGUOUS");
         return false;
      }
      string outcome = (JsonValue(latest_report, "report_id") == pending.report_id)
         ? "REPORT_CONFIRMED_AFTER_RESTART"
         : "TERMINAL_REPORT_CONFIRMED_BY_SERVER";
      return FinalizePendingReport(pending, outcome);
   }

   string report_response;
   int report_code = PostPendingReport(pending, report_response);
   if(HandlePendingPostResult(pending, report_code, report_response))
      return true;
   if(g_recovery_blocked || (report_code != 403 && report_code != 409))
      return false;
   if(!ReclaimPendingReport(pending))
      return false;
   report_code = PostPendingReport(pending, report_response);
   return HandlePendingPostResult(pending, report_code, report_response);
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
   bool acceptance = (JsonValue(command_json, "source_event") == "SHADOW_ACCEPTANCE");
   string reason_code = accepted
                        ? (acceptance ? "SHADOW_ACCEPTANCE_VALIDATED" : "SHADOW_PREFLIGHT_PASSED")
                        : reason;
   double volume = StringToDouble(JsonValue(command_json, "volume"));
   double entry = StringToDouble(JsonValue(command_json, "entry_price"));
   double stop = StringToDouble(JsonValue(command_json, "stop_loss"));
   double target = StringToDouble(JsonValue(command_json, "take_profit"));
   PendingReportState pending;
   pending.executor_id = InpExecutorId;
   pending.account_id = InpExpectedAccountId;
   pending.command_id = command_id;
   pending.report_id = MakeUuid();
   pending.request_hash = request_hash;
   pending.claim_token = claim_token;
   if(acceptance)
      pending.report_body = StringFormat(
         "{\"event\":\"execution_report\",\"protocol_version\":\"%s\","
         "\"report_id\":\"%s\",\"command_id\":\"%s\","
         "\"idempotency_key\":\"%s\",\"sequence\":1,\"state\":\"%s\","
         "\"event_time_utc\":\"%s\",\"executor_id\":\"%s\","
         "\"account_id\":\"%s\",\"request_hash\":\"%s\","
         "\"broker\":{},\"execution\":{\"filled_volume\":0},"
         "\"reason_code\":\"%s\",\"reason_detail\":\"%s\"}",
         W15_PROTOCOL, pending.report_id, command_id, EscapeJson(idempotency_key), state,
         UtcTimestamp(), InpExecutorId, EscapeJson(InpExpectedAccountId), request_hash,
         reason_code, EscapeJson(reason));
   else
      pending.report_body = StringFormat(
         "{\"event\":\"execution_report\",\"protocol_version\":\"%s\","
         "\"report_id\":\"%s\",\"command_id\":\"%s\","
         "\"idempotency_key\":\"%s\",\"sequence\":1,\"state\":\"%s\","
         "\"event_time_utc\":\"%s\",\"executor_id\":\"%s\","
         "\"account_id\":\"%s\",\"request_hash\":\"%s\","
         "\"broker\":{},\"execution\":{\"requested_volume\":%.8f,"
         "\"filled_volume\":0,\"requested_price\":%.10f,\"filled_price\":null,"
         "\"stop_loss\":%.10f,\"take_profit\":%.10f,\"observed_spread_points\":null},"
         "\"reason_code\":\"%s\",\"reason_detail\":\"%s\"}",
         W15_PROTOCOL, pending.report_id, command_id, EscapeJson(idempotency_key), state,
         UtcTimestamp(), InpExecutorId, EscapeJson(InpExpectedAccountId), request_hash,
         volume, entry, stop, target, reason_code, EscapeJson(reason));

   string storage_error = "";
   if(!SavePendingReport(pending, storage_error))
   {
      BlockPendingRecovery(command_id, storage_error);
      return false;
   }
   AppendLedger(command_id, "REPORT_DURABLE", state + ":" + reason);
   if(InpRestartDrillHoldAfterDurableSave)
   {
      g_recovery_blocked = true;
      AppendLedger(command_id, "RESTART_DRILL_ARMED",
                   "PENDING_REPORT_PERSISTED_BEFORE_POST");
      Print("[W15] Restart drill armed: pending report is durable and has not "
            "been posted. Restart this EA to reconcile it.");
      return false;
   }
   string response;
   int code = PostPendingReport(pending, response);
   return HandlePendingPostResult(pending, code, response);
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
   if(InpRecoveryRetrySeconds < 1)
   {
      Print("[W15] Recovery retry interval must be positive.");
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
   string symbol_universe_reason = "";
   if(!InitializeSymbolUniverse(symbol_universe_reason))
   {
      PrintFormat("[W15] 30-symbol universe rejected reason=%s",
                  symbol_universe_reason);
      return INIT_FAILED;
   }
   FolderCreate("Wolf15Executor", 0);
   FolderCreate("Wolf15Executor", FILE_COMMON);
   PendingReportState pending;
   string pending_error = "";
   if(!LoadPendingReport(pending, pending_error))
   {
      PrintFormat("[W15] Durable pending state rejected reason=%s", pending_error);
      return INIT_FAILED;
   }
   if(StringLen(pending.command_id) > 0)
      Print("[W15] Durable pending report found; reconciliation required before polling.");
   EventSetTimer(1);
   PrintFormat("[W15] Shadow executor initialized with signed-wire verification, "
               "durable recovery, and symbol_universe=%s count=%d. No broker "
               "side effects are compiled in.",
               W15_SYMBOL_UNIVERSE, W15_SYMBOL_COUNT);
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
   if(g_recovery_blocked)
      return;
   if(PendingReportExists())
   {
      if(now - g_last_recovery >= InpRecoveryRetrySeconds)
      {
         RecoverPendingReport();
         g_last_recovery = now;
      }
      if(g_recovery_blocked || PendingReportExists())
         return;
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
