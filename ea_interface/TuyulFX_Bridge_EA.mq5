//+------------------------------------------------------------------+
//| TuyulFX Bridge EA — DUMB EXECUTOR                                 |
//| Reads JSON commands from file, executes, writes reports           |
//| ZERO intelligence. ZERO analysis. ZERO overrides.                  |
//+------------------------------------------------------------------+
#property copyright "TuyulFX"
#property version   "1.00"
#property strict

input string BridgeDir = "C:\\TuyulFX\\bridge";  // Bridge directory path
input int    PollIntervalMs = 500;                // Poll interval in milliseconds
input int    MagicNumber = 151515;                // Magic number for our orders

//+------------------------------------------------------------------+
//| Expert initialization function                                     |
//+------------------------------------------------------------------+
int OnInit()
{
    // Verify bridge directories exist
    if(!FileIsExist(BridgeDir + "\\commands\\", FILE_COMMON))
    {
        Print("ERROR: Bridge commands directory not found: ", BridgeDir);
        // EA will still run but log warnings
    }
    
    Print("TuyulFX Bridge EA initialized. Polling: ", BridgeDir);
    EventSetMillisecondTimer(PollIntervalMs);
    return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Timer function — polls for new commands                            |
//+------------------------------------------------------------------+
void OnTimer()
{
    // Poll commands directory for new JSON files
    string filename;
    long search_handle = FileFindFirst(BridgeDir + "\\commands\\*.json", filename, FILE_COMMON);
    
    if(search_handle == INVALID_HANDLE)
        return;
    
    do
    {
        ProcessCommandFile(BridgeDir + "\\commands\\" + filename);
    }
    while(FileFindNext(search_handle, filename));
    
    FileFindClose(search_handle);
}

//+------------------------------------------------------------------+
//| Process a single command file                                      |
//+------------------------------------------------------------------+
void ProcessCommandFile(string filepath)
{
    // Read JSON, parse, execute order, write report, delete command
    // ... (full implementation per broker specifics)
    
    Print("Processing command: ", filepath);
    
    // NOTE: This EA does NOT validate the trade direction.
    // It does NOT check if BUY or SELL "makes sense."
    // All decisions come from L12 constitution via dashboard.
    // We are a DUMB EXECUTOR.
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                    |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    EventKillTimer();
    Print("TuyulFX Bridge EA deinitialized. Reason: ", reason);
}