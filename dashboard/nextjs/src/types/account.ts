export interface Account {
  account_id: string;
  name: string;
  balance?: number;
  equity?: number;
  prop_firm?: string | boolean;
  status?: string;
}
