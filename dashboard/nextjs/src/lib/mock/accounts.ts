export const accountsMock = {
  "cards": [
    { "label": "Accounts", "value": "3" },
    { "label": "Total Equity", "value": "$154,320" },
    { "label": "Daily DD", "value": "1.1%", "color": "red" },
    { "label": "Best Account", "value": "FTMO-02", "color": "blue" }
  ],
  "items": [
    { "id": "acc1", "name": "FTMO-01", "type": "Prop", "balance": "$50,000", "equity": "$49,620", "dailyDd": "0.76%", "maxDd": "8%", "rules": "Phase 1", "status": "Linked", "statusColor": "green" },
    { "id": "acc2", "name": "FTMO-02", "type": "Prop", "balance": "$100,000", "equity": "$101,540", "dailyDd": "0.22%", "maxDd": "10%", "rules": "Funded", "status": "Linked", "statusColor": "green" },
    { "id": "acc3", "name": "Manual-01", "type": "Personal", "balance": "$5,000", "equity": "$4,960", "dailyDd": "0.80%", "maxDd": "15%", "rules": "Manual Risk", "status": "Manual", "statusColor": "orange" }
  ]
} as const;
