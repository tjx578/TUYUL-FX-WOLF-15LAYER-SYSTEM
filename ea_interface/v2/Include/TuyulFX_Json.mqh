//+------------------------------------------------------------------+
//| TuyulFX_Json.mqh — JSON parser / builder (v2)                    |
//| Improved over v1: nested support, null handling, proper escaping  |
//| Zone : ea_interface/v2/ — pure utility, no side-effects           |
//+------------------------------------------------------------------+
#property copyright "TuyulFX"
#property strict

#ifndef TUYULFX_JSON_MQH
#define TUYULFX_JSON_MQH

//+------------------------------------------------------------------+
//| JsonGetString — extract string/bare value for a given key        |
//| Handles: "key": "value"  and  "key": 123 / true / null           |
//| Also supports 1-level nested path: "outer.inner"                  |
//+------------------------------------------------------------------+
string JsonGetString(const string &json, const string key,
                     const string defaultVal = "")
{
    // Support simple "outer.inner" path (one level only)
    int dot = StringFind(key, ".");
    if(dot > 0)
    {
        string outer = StringSubstr(key, 0, dot);
        string inner = StringSubstr(key, dot + 1);
        // Find the outer object block
        string search_outer = "\"" + outer + "\"";
        int pos_outer = StringFind(json, search_outer);
        if(pos_outer < 0) return defaultVal;
        int colon = StringFind(json, ":", pos_outer + (int)StringLen(search_outer));
        if(colon < 0) return defaultVal;
        // Skip whitespace after colon
        int brace_start = colon + 1;
        while(brace_start < StringLen(json) &&
              StringGetCharacter(json, brace_start) == ' ') brace_start++;
        if(brace_start >= StringLen(json) ||
           StringGetCharacter(json, brace_start) != '{') return defaultVal;
        // Find matching closing brace
        int depth = 0, brace_end = brace_start;
        for(; brace_end < StringLen(json); brace_end++)
        {
            ushort c = StringGetCharacter(json, brace_end);
            if(c == '{') depth++;
            else if(c == '}') { depth--; if(depth == 0) break; }
        }
        string sub = StringSubstr(json, brace_start, brace_end - brace_start + 1);
        return JsonGetString(sub, inner, defaultVal);
    }

    string search = "\"" + key + "\"";
    int pos = StringFind(json, search);
    if(pos < 0) return defaultVal;

    // Allow for the same key appearing as a nested key: require the char
    // before the quote to be a structural character or whitespace.
    // Simple heuristic: accept first occurrence (sufficient for our payloads).

    pos = StringFind(json, ":", pos + (int)StringLen(search));
    if(pos < 0) return defaultVal;
    pos++; // skip ':'
    // Skip whitespace
    while(pos < StringLen(json) && StringGetCharacter(json, pos) == ' ') pos++;
    if(pos >= StringLen(json)) return defaultVal;

    ushort ch = StringGetCharacter(json, pos);

    // Quoted string value
    if(ch == '"')
    {
        pos++; // skip opening quote
        string result = "";
        while(pos < StringLen(json))
        {
            ushort c = StringGetCharacter(json, pos);
            if(c == '\\')
            {
                pos++;
                if(pos >= StringLen(json)) break;
                ushort esc = StringGetCharacter(json, pos);
                if(esc == '"')       result += "\"";
                else if(esc == '\\') result += "\\";
                else if(esc == 'n')  result += "\n";
                else if(esc == 'r')  result += "\r";
                else if(esc == 't')  result += "\t";
                else                 result += ShortToString(esc);
            }
            else if(c == '"') break; // end of string
            else result += ShortToString(c);
            pos++;
        }
        return result;
    }

    // Bare value: number, bool, null
    int end = pos;
    while(end < StringLen(json))
    {
        ushort c = StringGetCharacter(json, end);
        if(c == ',' || c == '}' || c == ']' || c == '\n' || c == '\r') break;
        end++;
    }
    string bare = StringSubstr(json, pos, end - pos);
    StringTrimRight(bare);
    return bare;
}

//+------------------------------------------------------------------+
//| JsonGetDouble — extract double value for a given key             |
//+------------------------------------------------------------------+
double JsonGetDouble(const string &json, const string key,
                     double defaultVal = 0.0)
{
    string s = JsonGetString(json, key, "");
    if(StringLen(s) == 0 || s == "null") return defaultVal;
    return StringToDouble(s);
}

//+------------------------------------------------------------------+
//| JsonGetLong — extract long (integer) value for a given key       |
//+------------------------------------------------------------------+
long JsonGetLong(const string &json, const string key, long defaultVal = 0)
{
    string s = JsonGetString(json, key, "");
    if(StringLen(s) == 0 || s == "null") return defaultVal;
    return StringToInteger(s);
}

//+------------------------------------------------------------------+
//| JsonGetBool — extract bool value for a given key                 |
//| Recognises: true / false / 1 / 0                                 |
//+------------------------------------------------------------------+
bool JsonGetBool(const string &json, const string key, bool defaultVal = false)
{
    string s = JsonGetString(json, key, "");
    if(StringLen(s) == 0) return defaultVal;
    if(s == "true"  || s == "1") return true;
    if(s == "false" || s == "0") return false;
    return defaultVal;
}

//+------------------------------------------------------------------+
//| JsonBuildObject — build a JSON object from parallel arrays       |
//| isString[i] = true  → value is quoted                            |
//| isString[i] = false → value is bare (number / bool / null)       |
//+------------------------------------------------------------------+
string JsonBuildObject(string &keys[], string &values[],
                       bool &isString[], int count)
{
    string obj = "{";
    for(int i = 0; i < count; i++)
    {
        if(i > 0) obj += ",";
        obj += "\"" + keys[i] + "\":";
        if(isString[i])
            obj += "\"" + values[i] + "\"";
        else
            obj += values[i];
    }
    obj += "}";
    return obj;
}

//+------------------------------------------------------------------+
//| JsonBuildArray — build a JSON array from string items            |
//+------------------------------------------------------------------+
string JsonBuildArray(string &items[], int count)
{
    string arr = "[";
    for(int i = 0; i < count; i++)
    {
        if(i > 0) arr += ",";
        arr += "\"" + items[i] + "\"";
    }
    arr += "]";
    return arr;
}

#endif // TUYULFX_JSON_MQH
